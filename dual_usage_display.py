import argparse
import json
import random
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import serial
from serial.tools import list_ports

from usage_provider import AntigravityUsageProvider

W, H = 160, 80
BAUD = 19200


def get_matrix_font(size, bold=True):
    candidates = [
        r'C:\Windows\Fonts\consolab.ttf' if bold else r'C:\Windows\Fonts\consola.ttf',
        r'C:\Windows\Fonts\lucon.ttf',
        r'C:\Windows\Fonts\courbd.ttf' if bold else r'C:\Windows\Fonts\cour.ttf',
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


COL_W = 7
COLS = W // COL_W  # 22


class MatrixRain:
    def __init__(self, w=160, h=80):
        self.w = w
        self.h = h
        self.chars = '0123456789ABCDEFXY$#@<>:;*+=-!%?&Z'
        self.font_rain = get_matrix_font(8, bold=True)
        self.f_main = get_matrix_font(21, bold=True)
        self.f_num = get_matrix_font(21, bold=True)
        self.f_dt = get_matrix_font(15, bold=True)
        self.cols = []
        for _ in range(COLS):
            y = random.uniform(-50, h)
            spd = random.uniform(1.5, 2.5)  # Smooth 1.5 ~ 2.5 pixels displacement per frame
            length = random.randint(7, 14)
            c_list = [random.choice(self.chars) for _ in range(length)]
            self.cols.append({'y': y, 'spd': spd, 'len': length, 'chars': c_list})

    def update(self):
        for c in self.cols:
            c['y'] += c['spd']  # Exact continuous vertical pixel movement
            # Low mutation rate preserves the visual perception of characters gliding down smoothly
            if random.random() < 0.05:
                c['chars'][random.randint(0, c['len'] - 1)] = random.choice(self.chars)
            # Seamless reset when the entire trail passes off the bottom
            if c['y'] - c['len'] * 8 > self.h:
                c['y'] = random.uniform(-30, -5)
                c['spd'] = random.uniform(1.5, 2.5)
                c['len'] = random.randint(7, 14)
                c['chars'] = [random.choice(self.chars) for _ in range(c['len'])]

    def _draw_value(self, d, val, y_base, color):
        if ' ' in val and ':' in val:
            d_str, t_str = val.split(' ', 1)
            w1 = d.textbbox((0, 0), d_str, font=self.f_dt)[2]
            w2 = d.textbbox((0, 0), t_str, font=self.f_dt)[2]
            d.text((self.w - 4 - w1, y_base - 5), d_str, font=self.f_dt, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
            d.text((self.w - 4 - w2, y_base + 12), t_str, font=self.f_dt, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
        else:
            vw = d.textbbox((0, 0), val, font=self.f_num)[2]
            d.text((self.w - 4 - vw, y_base), val, font=self.f_num, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))

    def render_frame(self, g_val='80.4%', c_val='0.0%', flash_g=False, flash_c=False):
        base = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 255))
        rain_im = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))
        d_rain = ImageDraw.Draw(rain_im)

        # 1. Pixel-by-pixel scrolling streams
        for i, col in enumerate(self.cols):
            x = i * COL_W + 1
            y_head = col['y']
            for j in range(col['len']):
                y = int(y_head - j * 8)  # Rendered at continuous pixel positions
                if -8 <= y < self.h:
                    ch = col['chars'][j]
                    if j == 0:
                        col_rgba = (225, 255, 225, 195)  # Bright glowing head
                    elif j < 3:
                        col_rgba = (0, 255, 65, 175)     # Saturated Matrix green
                    elif j < 6:
                        col_rgba = (0, 215, 55, 145)     # Mid green
                    elif j < 9:
                        col_rgba = (0, 160, 40, 120)     # Visible deep green
                    else:
                        col_rgba = (0, 110, 28, 95)      # Faint trail green

                    d_rain.text((x, y), ch, font=self.font_rain, fill=col_rgba)

        im = Image.alpha_composite(base, rain_im)

        # 2. Semi-translucent backing overlay (alpha=70) + Sharp green divider
        overlay = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))
        d_ov = ImageDraw.Draw(overlay)
        d_ov.rounded_rectangle([(1, 4), (self.w - 2, 36)], radius=2, fill=(0, 0, 0, 70))
        d_ov.rounded_rectangle([(1, 44), (self.w - 2, 76)], radius=2, fill=(0, 0, 0, 70))
        d_ov.line([(0, 39), (self.w - 1, 39)], fill=(0, 180, 48, 230), width=1)

        im = Image.alpha_composite(im, overlay)
        d = ImageDraw.Draw(im)

        # 3. Pure Matrix Phosphor Green Text with 2px black cutout stroke
        matrix_green = (0, 255, 65)
        flash_color = (230, 255, 230)

        # Line 1: GEMINI
        d.text((4, 7), 'GEMINI', font=self.f_main, fill=matrix_green, stroke_width=2, stroke_fill=(0, 0, 0))
        self._draw_value(d, g_val, 7, flash_color if flash_g else matrix_green)

        # Line 2: CLAUDE
        d.text((4, 47), 'CLAUDE', font=self.f_main, fill=matrix_green, stroke_width=2, stroke_fill=(0, 0, 0))
        self._draw_value(d, c_val, 47, flash_color if flash_c else matrix_green)

        return im.convert('RGB')


def rgb565_bytes(im):
    out = bytearray()
    rgb = im.convert('RGB')
    pixels = rgb.get_flattened_data() if hasattr(rgb, 'get_flattened_data') else rgb.getdata()
    for r, g, b in pixels:
        v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out += v.to_bytes(2, 'big')
    return bytes(out)


def find_port(explicit=None):
    if explicit:
        return explicit
    ports = list(list_ports.comports())
    ch = [p for p in ports if (p.vid == 0x1A86 and p.pid in (0x7523, 0xFE0C)) or 'CH340' in (p.description or '').upper()]
    if len(ch) == 1:
        return ch[0].device
    if not ch:
        raise RuntimeError('找不到 CH340/MSU2 MINI 串口；請確認裝置已連接。')
    raise RuntimeError('找到多個 CH340 串口，請用 --port COMx 指定。')


def be16(v):
    return bytes([(int(v) // 256) & 0xff, int(v) % 256])


def set_xy(s, x, y):
    s.write(bytes([2, 0]) + be16(x) + be16(y))


def set_size(s, w, h):
    s.write(bytes([2, 1]) + be16(w) + be16(h))


def drain_rx(s):
    try:
        if s.in_waiting:
            return s.read(s.in_waiting)
    except Exception:
        pass
    return b''


def wait_rx(s, timeout=0.4):
    t0 = time.monotonic()
    buf = bytearray()
    while time.monotonic() - t0 < timeout:
        try:
            n = s.in_waiting
            if n:
                buf.extend(s.read(n))
                if len(buf) >= 6:
                    return bytes(buf)
        except Exception:
            break
        time.sleep(0.002)
    return bytes(buf)


def wait_mcu_ready(s, timeout=0.5):
    """Send Read_ADC_CH(9) to ensure MCU completed SPI rendering buffer."""
    drain_rx(s)
    s.write(bytes([8, 9, 0, 0, 0, 0]))
    return wait_rx(s, timeout=timeout)


def lcd_add(s, x, y, w, h):
    drain_rx(s)
    set_xy(s, x, y)
    set_size(s, w, h)
    s.write(bytes([2, 3, 7, 0, 0, 0]))
    return wait_rx(s, timeout=0.4)


def compress_pixels_payload(pix):
    """Hardware RLE mode compression: ~39KB -> ~5KB."""
    out = bytearray()
    mv = memoryview(pix)
    total = len(mv)
    full = total // 256
    for b_idx in range(full):
        block = mv[b_idx * 256 : (b_idx + 1) * 256]
        words = [bytes(block[i * 4 : i * 4 + 4]) for i in range(64)]
        counts = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        mode_word = max(counts, key=counts.get)
        out += b'\x02\x04' + mode_word
        for i, w in enumerate(words):
            if w != mode_word:
                out += bytes([4, i]) + w
        out += b'\x02\x03\x08\x01\x00\x00'
    rem = total % 256
    if rem:
        tail = bytearray(mv[full * 256 :]) + (b'\xff' * (256 - rem))
        for i in range(64):
            out += bytes([4, i]) + tail[i * 4 : i * 4 + 4]
        out += bytes([2, 3, 8, 0, rem, 0])
    return bytes(out)


def send_pixels(s, pix):
    payload = compress_pixels_payload(pix)
    s.write(payload)
    wait_mcu_ready(s, timeout=0.6)


def handshake(s, force=False):
    """Handshake when device broadcasts \\x00MSN01."""
    try:
        time.sleep(0.25)
        rx = drain_rx(s)
        if force or (b'MSN' in rx):
            s.write(b'\x00MSNCN')
            time.sleep(0.25)
            drain_rx(s)
            return True
    except Exception:
        pass
    return False


def apply_brightness(im, brightness=0.72):
    if brightness >= 0.99:
        return im
    from PIL import ImageEnhance
    return ImageEnhance.Brightness(im.convert('RGB')).enhance(max(0.1, float(brightness)))


def main():
    ap = argparse.ArgumentParser(description='MSU2 MINI Pure Matrix Green Preview')
    ap.add_argument('--output', default='matrix_pure_green_preview.png')
    args = ap.parse_args()

    rain = MatrixRain()
    for _ in range(20):
        rain.update()
    im = rain.render_frame('80.4%', '0.0%')
    im.save(args.output)
    print(f'Pure Matrix green preview saved to {args.output}')


if __name__ == '__main__':
    main()
