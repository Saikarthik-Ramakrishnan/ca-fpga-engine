import time, glob, os
from playwright.sync_api import sync_playwright

OUT_DIR = "/home/claude/ca_fpga_engine/docs/media/frames"
os.makedirs(OUT_DIR, exist_ok=True)
HTML_PATH = "file:///home/claude/ca_fpga_engine/software_prototype/cellnet_console.html"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 620, "height": 900}, device_scale_factor=2)
    page.goto(HTML_PATH)
    page.wait_for_timeout(300)

    # select the Gosper Gun preset for a legible, on-theme animation
    page.locator(".preset", has_text="Gun").click()
    page.wait_for_timeout(200)

    # bump clock rate a bit so the gif shows real motion in a short clip
    page.locator("#speed").fill("14")
    page.wait_for_timeout(100)

    # start the run
    page.locator("#playBtn").click()

    n_frames = 42
    interval_ms = 110
    for i in range(n_frames):
        page.wait_for_timeout(interval_ms)
        page.screenshot(path=f"{OUT_DIR}/frame_{i:03d}.png")

    browser.close()

print("captured", len(glob.glob(OUT_DIR + "/*.png")), "frames")
