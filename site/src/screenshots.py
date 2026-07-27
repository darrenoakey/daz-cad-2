"""Screenshot capture for example models using Playwright."""

import subprocess
import sys
from pathlib import Path


MODELS = [
    {"file": "default.js", "wait": 10},
    {"file": "demo_patterns.js", "wait": 15},
    {"file": "gridfinity-demo.js", "wait": 10},
    {"file": "open-box.js", "wait": 10},
    {"file": "baseplate-demo.js", "wait": 10},
    {"file": "border-demo.js", "wait": 10},
    {"file": "demo_lines_pattern.js", "wait": 10},
    {"file": "tab-demo.js", "wait": 10},
    {"file": "clip-demo.js", "wait": 10},
    {"file": "baseplate-on-surface.js", "wait": 10},
]


def capture_screenshots(server_url: str, output_dir: Path) -> None:
    """Capture screenshots of all example models.

    Requires a running daz-cad server and Playwright installed.

    Args:
        server_url: URL of the running server (e.g., http://127.0.0.1:8766).
        output_dir: Directory to save screenshots.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use Playwright via Python subprocess to capture screenshots
    for model in MODELS:
        filename = model["file"]
        wait_time = model["wait"]
        output_file = output_dir / filename.replace(".js", ".png")

        if output_file.exists():
            print(f"  Skipping {filename} (already exists)")
            continue

        print(f"  Capturing {filename} (wait {wait_time}s)...")

        script = f"""
import asyncio
from playwright.async_api import async_playwright

async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={{"width": 1280, "height": 800}})
        await page.goto("{server_url}/static/editor.html")

        # Wait for OpenCascade to load
        await page.wait_for_function("() => window.cadEditor && window.cadEditor.isReady", timeout=60000)

        # Select the file
        await page.evaluate('''() => {{
            if (window.cadEditor && window.cadEditor._selectFile) {{
                window.cadEditor._selectFile("{filename}");
            }}
        }}''')

        # Wait for render
        await asyncio.sleep({wait_time})

        # Screenshot just the viewer area
        viewer = page.locator("#viewer-container")
        await viewer.screenshot(path="{output_file}")

        await browser.close()

asyncio.run(capture())
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"  Failed to capture {filename}: {result.stderr[:200]}")
        else:
            print(f"  Saved {output_file.name}")


def capture_editor_screenshot(server_url: str, output_path: Path) -> None:
    """Capture a full editor UI screenshot."""
    if output_path.exists():
        print(f"  Skipping editor screenshot (already exists)")
        return

    print("  Capturing full editor UI...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    script = f"""
import asyncio
from playwright.async_api import async_playwright

async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={{"width": 1920, "height": 1080}})
        await page.goto("{server_url}/static/editor.html")
        await page.wait_for_function("() => window.cadEditor && window.cadEditor.isReady", timeout=60000)
        await asyncio.sleep(15)
        await page.screenshot(path="{output_path}")
        await browser.close()

asyncio.run(capture())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"  Failed to capture editor: {result.stderr[:200]}")
    else:
        print(f"  Saved {output_path.name}")
