import argparse
import atexit
import ctypes
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import serial

from dual_usage_display import (
    BAUD, W, H, find_port, MatrixRain, rgb565_bytes, lcd_add, send_pixels,
    handshake, drain_rx, apply_brightness
)
from usage_provider import AntigravityUsageProvider

BASE = Path(__file__).resolve().parent
LOCK_FILE = BASE / 'dual_usage_monitor.lock'
DATA_FILE = BASE / 'dual_usage.json'
LOG_FILE = BASE / 'dual_usage_monitor.log'
MAX_LOG = 512 * 1024


def stamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log(msg):
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG:
            old = LOG_FILE.with_suffix('.log.old')
            try:
                old.unlink(missing_ok=True)
            except Exception:
                pass
            LOG_FILE.replace(old)
        with LOG_FILE.open('a', encoding='utf-8') as f:
            f.write(f'[{stamp()}] {msg}\n')
            f.flush()
    except Exception:
        pass


def pid_alive(pid):
    if pid == os.getpid():
        return True
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if h:
            code = ctypes.c_ulong()
            res = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(res and code.value == 259)
    except Exception:
        pass
    return False


def acquire_lock():
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text().strip())
            if pid_alive(old):
                return False
        except Exception:
            pass
    LOCK_FILE.write_text(str(os.getpid()), encoding='ascii')
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))
    return True


class RealtimeUsageTracker:
    def __init__(self, poll_interval=0.7):
        self.provider = AntigravityUsageProvider()
        self.poll_interval = poll_interval
        self.lock = threading.Lock()
        
        self.gemini_str = "100.0%"
        self.claude_str = "0.0%"
        self.argon_str = "100.0%"
        self.gemini_frac = 1.0
        self.claude_frac = 0.0
        self.argon_frac = 1.0

        if DATA_FILE.exists():
            try:
                cached = json.loads(DATA_FILE.read_text(encoding='utf-8'))
                self.gemini_str = cached.get('gemini', self.gemini_str)
                self.claude_str = cached.get('claude', self.claude_str)
                self.argon_str = cached.get('argon', self.argon_str)
                self.gemini_frac = float(cached.get('gemini_frac', self.gemini_frac))
                self.claude_frac = float(cached.get('claude_frac', self.claude_frac))
                self.argon_frac = float(cached.get('argon_frac', self.argon_frac))
            except Exception:
                pass
        
        self.flash_g = 0
        self.flash_c = 0
        self.flash_a = 0
        self.running = True

    def start(self):
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def _poll_loop(self):
        last_g = None
        last_c = None
        last_a = None
        last_written = None
        
        while self.running:
            try:
                data = self.provider.get()
                g_str = data.get('gemini_str', f"{data.get('gemini_left', 100)}%")
                c_str = data.get('claude_str', f"{data.get('claude_left', 0)}%")
                a_str = data.get('argon_str', f"{data.get('argon_left', 100)}%")
                g_frac = data.get('gemini_frac', 1.0)
                c_frac = data.get('claude_frac', 0.0)
                a_frac = data.get('argon_frac', 1.0)

                with self.lock:
                    if last_g is not None and abs(g_frac - last_g) > 0.0001:
                        self.flash_g = 4
                        log(f'[REALTIME TOKEN PUSH] Gemini (5h): {last_g*100:.2f}% -> {g_frac*100:.2f}% ({g_str})')
                    if last_c is not None and abs(c_frac - last_c) > 0.0001:
                        self.flash_c = 4
                        log(f'[REALTIME TOKEN PUSH] Claude (5h): {last_c*100:.2f}% -> {c_frac*100:.2f}% ({c_str})')
                    if last_a is not None and abs(a_frac - last_a) > 0.0001:
                        self.flash_a = 4
                        log(f'[REALTIME TOKEN PUSH] Argon (Weekly): {last_a*100:.2f}% -> {a_frac*100:.2f}% ({a_str})')

                    self.gemini_str = g_str
                    self.claude_str = c_str
                    self.argon_str = a_str
                    self.gemini_frac = g_frac
                    self.claude_frac = c_frac
                    self.argon_frac = a_frac

                last_g = g_frac
                last_c = c_frac
                last_a = a_frac

                cur_state = (g_str, c_str, a_str, round(g_frac, 5), round(c_frac, 5), round(a_frac, 5))
                if cur_state != last_written:
                    try:
                        DATA_FILE.write_text(
                            json.dumps({
                                'gemini': g_str,
                                'claude': c_str,
                                'argon': a_str,
                                'gemini_frac': g_frac,
                                'claude_frac': c_frac,
                                'argon_frac': a_frac,
                            }, indent=2),
                            encoding='utf-8'
                        )
                        last_written = cur_state
                    except Exception:
                        pass

                time.sleep(self.poll_interval)
            except Exception:
                # Back off when Antigravity is closed so startup residency uses near-zero CPU
                time.sleep(5.0)

    def get_state(self):
        with self.lock:
            fg = self.flash_g > 0
            fc = self.flash_c > 0
            fa = self.flash_a > 0
            if self.flash_g > 0: self.flash_g -= 1
            if self.flash_c > 0: self.flash_c -= 1
            if self.flash_a > 0: self.flash_a -= 1
            return self.gemini_str, self.claude_str, self.argon_str, fg, fc, fa


def should_auto_rotate():
    """Detect if current machine requires 180-degree flip (e.g. left-side USB port)."""
    import socket, platform
    hostname = socket.gethostname().upper()
    node = platform.node().upper()
    # Machine DESKTOP-27HOL47 (ZEUS NB) has USB on the left side
    left_usb_machines = {'DESKTOP-27HOL47'}
    return hostname in left_usb_machines or node in left_usb_machines


def run_monitor(port=None, fps=8.0, brightness=0.72, rotate=None):
    if not acquire_lock():
        log('Another dual monitor instance is already running. Exiting.')
        print('Another dual monitor instance is already running.')
        return

    if rotate is None:
        rotate = 180 if should_auto_rotate() else 0

    log(f'Matrix Realtime Monitor started. fps={fps}, brightness={brightness}, rotate={rotate}')
    print(f'Matrix Realtime Monitor started (PID {os.getpid()}). rotate={rotate}. Press Ctrl+C to stop.')

    tracker = RealtimeUsageTracker(poll_interval=0.6)
    tracker.start()

    rain = MatrixRain()
    ser = None
    frame_duration = 1.0 / fps
    missed_acks = 0

    try:
        while True:
            t0 = time.monotonic()

            # 1. Ensure serial connection
            if ser is None:
                try:
                    actual_port = find_port(port)
                    ser = serial.Serial(actual_port, BAUD, timeout=0.25, write_timeout=5)
                    drain_rx(ser)
                    handshake(ser, force=True)
                    log(f'Connected to serial port {actual_port} (handshake completed)')
                    missed_acks = 0
                except Exception as e:
                    time.sleep(1.0)
                    continue

            # 2. Get latest usage state
            g_str, c_str, a_str, flash_g, flash_c, flash_a = tracker.get_state()

            # 3. Update rain animation & render frame
            rain.update()
            im = rain.render_frame(g_str, c_str, a_str, flash_g=flash_g, flash_c=flash_c, flash_a=flash_a)
            im_adj = apply_brightness(im, brightness=brightness)
            if rotate == 180:
                im_adj = im_adj.rotate(180)
            pix = rgb565_bytes(im_adj)

            # 4. Stream frame to screen
            try:
                lcd_add(ser, 0, 0, W, H)
                ok = send_pixels(ser, pix)
                if not ok:
                    missed_acks += 1
                    if missed_acks >= 4:
                        log('MCU not responding (sleep/disconnect detected). Re-establishing connection...')
                        try:
                            if ser: ser.close()
                        except Exception:
                            pass
                        ser = None
                        time.sleep(0.5)
                        continue
                else:
                    missed_acks = 0
            except (serial.SerialException, OSError) as e:
                log(f'Serial write error: {e}. Reconnecting...')
                try:
                    if ser: ser.close()
                except Exception:
                    pass
                ser = None
                time.sleep(1.0)
                continue
            except Exception as e:
                log(f'Render error: {e}')

            # 5. Maintain steady frame rate
            dt = time.monotonic() - t0
            time.sleep(max(0.005, frame_duration - dt))

    except KeyboardInterrupt:
        log('Matrix Monitor stopped by user.')
    finally:
        tracker.running = False
        if ser:
            try: ser.close()
            except Exception: pass
        LOCK_FILE.unlink(missing_ok=True)
        log('Matrix Monitor terminated.')


def main():
    ap = argparse.ArgumentParser(description='MSU2 MINI Matrix Real-time Token Monitor')
    ap.add_argument('--port', help='Explicit COM port (e.g. COM7 or COM13)')
    ap.add_argument('--fps', type=float, default=9.0, help='Matrix rain frame rate (default: 9.0 FPS)')
    ap.add_argument('--brightness', type=float, default=0.88, help='Dimming brightness (0.1~1.0, default: 0.88)')
    ap.add_argument('--rotate', type=int, choices=[0, 180], default=None, help='Screen orientation (0 or 180, default: auto-detect by machine)')
    args = ap.parse_args()

    run_monitor(
        port=args.port,
        fps=args.fps,
        brightness=args.brightness,
        rotate=args.rotate
    )


if __name__ == '__main__':
    main()
