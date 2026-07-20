"""
capture.py

Records frames of the CELL·NET console (Gosper gun preset) as PNGs, which
are then assembled into docs/media/cellnet_demo.gif.

Paths are derived from this file's location, so it runs from a fresh clone
with no editing. Needs Playwright:  pip install playwright && playwright install chromium

Usage:
  python3 docs/media/capture.py            # writes frames next to this file
  python3 docs/media/capture.py --frames 60 --speed 14
"""

import argparse
import glob
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "frames")
HTML_PATH = "file://" + os.path.join(
    REPO_ROOT, "software_prototype", "cellnet_console.html"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=42)
    ap.add_argument("--interval-ms", type=int, default=110)
    ap.add_argument("--speed", type=str, default="14")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 620, "height": 900}, device_scale_factor=2
        )
        page.goto(HTML_PATH)
        page.wait_for_timeout(300)

        # select the Gosper Gun preset for a legible, on-theme animation
        page.locator(".preset", has_text="Gun").click()
        page.wait_for_timeout(200)

        # bump clock rate a bit so the gif shows real motion in a short clip
        page.locator("#speed").fill(args.speed)
        page.wait_for_timeout(100)

        # start the run
        page.locator("#playBtn").click()

        for i in range(args.frames):
            page.wait_for_timeout(args.interval_ms)
            page.screenshot(path=os.path.join(OUT_DIR, f"frame_{i:03d}.png"))

        browser.close()

    print("captured", len(glob.glob(os.path.join(OUT_DIR, "*.png"))), "frames")


if __name__ == "__main__":
    main()
