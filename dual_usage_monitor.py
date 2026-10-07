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
    handshake, apply_brightness
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
        self.gemini_frac = 1.0
        self.claude_frac = 0.0

        if DATA_FILE.exists():
            try:
                cached = json.loads(DATA_FILE.read_text(encoding='utf-8'))
                self.gemini_str = cached.get('gemini', self.gemini_str)
                self.claude_str = cached.get('claude', self.claude_str)
                self.gemini_frac = float(cached.get('gemini_frac', self.gemini_frac))
                self.claude_frac = float(cached.get('claude_frac', self.claude_frac))
            except Exception:
                pass
        
        self.flash_g = 0
        self.flash_c = 0
        self.running = True

    def start(self):
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def _poll_loop(self):
        last_g = None
        last_c = None
        last_written = None
        
        while self.running:
            try:
                data = self.provider.get()
                g_str = data.get('gemini_str', f"{data.get('gemini_left', 100)}%")
                c_str = data.get('claude_str', f"{data.get('claude_left', 0)}%")
                g_frac = data.get('gemini_frac', 1.0)
                c_frac = data.get('claude_frac', 0.0)

                with self.lock:
                    if last_g is not None and abs(g_frac - last_g) > 0.0001:
                        self.flash_g = 4
                        log(f'[REALTIME TOKEN PUSH] Gemini (5h): {last_g*100:.2f}% -> {g_frac*100:.2f}% ({g_str})')
                    if last_c is not None and abs(c_frac - last_c) > 0.0001:
                        self.flash_c = 4
                        log(f'[REALTIME TOKEN PUSH] Claude (5h): {last_c*100:.2f}% -> {c_frac*100:.2f}% ({c_str})')

                    self.gemini_str = g_str
                    self.claude_str = c_str
                    self.gemini_frac = g_frac
                    self.claude_frac = c_frac

                last_g = g_frac
                last_c = c_frac

                cur_state = (g_str, c_str, round(g_frac, 5), round(c_frac, 5))
                if cur_state != last_written:
                    try:
                        DATA_FILE.write_text(
                            json.dumps({'gemini': g_str, 'claude': c_str, 'gemini_frac': g_frac, 'claude_frac': c_frac}, indent=2),
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
            if self.flash_g > 0: self.flash_g -= 1
            if self.flash_c > 0: self.flash_c -= 1
            return self.gemini_str, self.claude_str, fg, fc


def run_monitor(port=None, fps=8.0, brightness=0.72):
    if not acquire_lock():
        log('Another dual monitor instance is already running. Exiting.')
        print('Another dual monitor instance is already running.')
        return

    log(f'Matrix Realtime Monitor started. fps={fps}, brightness={brightness}')
    print(f'Matrix Realtime Monitor started (PID {os.getpid()}). Press Ctrl+C to stop.')

    tracker = RealtimeUsageTracker(poll_interval=0.6)
    tracker.start()

    rain = MatrixRain()
    ser = None
    frame_duration = 1.0 / fps

    try:
        while True:
            t0 = time.monotonic()

            # 1. Ensure serial connection
            if ser is None:
                try:
                    actual_port = find_port(port)
                    ser = serial.Serial(actual_port, BAUD, timeout=0.25, write_timeout=5)
                    handshake(ser)
                    log(f'Connected to serial port {actual_port}')
                except Exception as e:
                    time.sleep(1.0)
                    continue

            # 2. Get latest usage state
            g_str, c_str, flash_g, flash_c = tracker.get_state()

            # 3. Update rain animation & render frame
            rain.update()
            im = rain.render_frame(g_str, c_str, flash_g=flash_g, flash_c=flash_c)
            im_adj = apply_brightness(im, brightness=brightness)
            pix = rgb565_bytes(im_adj)

            # 4. Stream frame to screen
            try:
                lcd_add(ser, 0, 0, W, H)
                send_pixels(ser, pix)
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
    ap.add_argument('--port', help='Explicit COM port (e.g. COM7)')
    ap.add_argument('--fps', type=float, default=9.0, help='Matrix rain frame rate (default: 9.0 FPS)')
    ap.add_argument('--brightness', type=float, default=0.88, help='Dimming brightness (0.1~1.0, default: 0.88)')
    args = ap.parse_args()

    run_monitor(
        port=args.port,
        fps=args.fps,
        brightness=args.brightness
    )


if __name__ == '__main__':
    main()
