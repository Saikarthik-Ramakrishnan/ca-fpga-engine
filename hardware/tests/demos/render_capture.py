# render_capture.py
#
# Turns uart_capture.json (produced by demo_capture.py) into an animated
# GIF. Every frame here comes from real decoded UART data, not the
# golden model, since demo_capture.py only ever touches tx_serial, the
# same wire a real PC's serial adapter would see.
#
# Usage:
#   python3 render_capture.py
# Reads uart_capture.json from the same directory, writes
# phase4_live_capture.gif next to it.

import json
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(__file__)
CAPTURE_PATH = os.path.join(HERE, "uart_capture.json")
OUTPUT_PATH = os.path.join(HERE, "phase4_live_capture.gif")

# flip-dot console palette, matching cellnet_console.html
BG = (26, 24, 21)         # graphite
DOT_OFF = (33, 30, 24)    # dim, unlit dot
DOT_ON = (242, 193, 78)   # amber, lit dot
DOT_ON_EDGE = (201, 146, 43)

CELL = 56
PAD = 18


def bits_to_grid(bits: int, rows: int, cols: int):
    return [[(bits >> (r * cols + c)) & 1 for c in range(cols)] for r in range(rows)]


def render_frame(bits: int, rows: int, cols: int) -> Image.Image:
    w = cols * CELL + PAD * 2
    h = rows * CELL + PAD * 2
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    grid = bits_to_grid(bits, rows, cols)
    for r in range(rows):
        for c in range(cols):
            cx = PAD + c * CELL + CELL // 2
            cy = PAD + r * CELL + CELL // 2
            rad = CELL // 2 - 4
            if grid[r][c]:
                draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                             fill=DOT_ON, outline=DOT_ON_EDGE, width=2)
            else:
                draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                             fill=DOT_OFF)
    return img


def main():
    with open(CAPTURE_PATH) as f:
        data = json.load(f)

    rows, cols, frames = data["rows"], data["cols"], data["frames"]
    frames = [int(f, 16) if isinstance(f, str) else f for f in frames]
    if not frames:
        raise SystemExit("uart_capture.json has no frames, run demo_capture.py first")

    images = [render_frame(f, rows, cols) for f in frames]

    if len(images) > 2:
        durations = [500] + [350] * (len(images) - 2) + [500]
    else:
        durations = [500] * len(images)

    images[0].save(
        OUTPUT_PATH,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
    )
    print(f"Rendered {len(images)} frames to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
