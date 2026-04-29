#!/usr/bin/env python3
"""inspect_element.py — Playwright element inspector for Design Bridge Phase 1.

Usage:
    python scripts/inspect_element.py <URL> [--selector ".my-class" | --xy "456,789"]
    python scripts/inspect_element.py http://192.168.1.200:3000/tools/department-hq

The script:
1. Navigates to the URL via Playwright
2. Takes a full-page screenshot and displays it in the brainstorm browser
3. Asks you to identify an element (CSS selector or x,y page coordinates)
4. Returns a JSON report: tag, id, classes, computed CSS, bounding box, text
5. Re-renders the screenshot with a red highlight box over the element
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Optional


def find_session_dir(
    log_path: str = "/tmp/brainstorm-launcher.log",
) -> tuple[Optional[str], Optional[str]]:
    """Read the active brainstorm session directories from the launcher log.

    Returns (screen_dir, state_dir) of the most recent server-started entry,
    or (None, None) if the log is missing or has no server-started lines.
    """
    try:
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return None, None

    screen_dir = None
    state_dir = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "server-started":
                sd = data.get("screen_dir")
                st = data.get("state_dir")
                if sd is not None and st is not None:
                    screen_dir = sd
                    state_dir = st
        except (json.JSONDecodeError, AttributeError):
            continue

    return screen_dir, state_dir


_CSS_PROPS = [
    "width", "height", "padding", "margin", "font-size", "font-family",
    "color", "background-color", "border", "border-radius", "display",
    "position", "top", "left", "flex", "gap", "z-index", "opacity",
    "overflow", "box-shadow",
]

_ELEMENT_JS = """
({ selector, x, y, props }) => {
    const el = selector
        ? document.querySelector(selector)
        : document.elementFromPoint(x, y);
    if (!el) return { found: false };
    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return {
        found: true,
        tag: el.tagName,
        id: el.id || '',
        classes: Array.from(el.classList),
        text: (el.textContent || '').trim().slice(0, 100),
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        styles: Object.fromEntries(props.map(p => [p, cs.getPropertyValue(p).trim()])),
    };
}
"""


def get_element_details(
    page,
    selector: Optional[str] = None,
    xy: Optional[tuple[int, int]] = None,
) -> dict:
    """Inspect an element on a Playwright page by CSS selector or page coordinates.

    Pass exactly one of `selector` or `xy`. Returns a dict with:
    - found (bool)
    - tag, id, classes, text
    - bounding_box: {x, y, width, height}
    - computed_css: {property: value} for the 20 layout/visual properties
    """
    if selector is None and xy is None:
        raise ValueError("Pass either selector= or xy=")

    js_args = {
        "selector": selector,
        "x": xy[0] if xy else None,
        "y": xy[1] if xy else None,
        "props": _CSS_PROPS,
    }
    raw = page.evaluate(_ELEMENT_JS, js_args)

    if not raw.get("found"):
        return {"found": False}

    return {
        "found": True,
        "tag": raw["tag"],
        "id": raw.get("id", ""),
        "classes": raw.get("classes", []),
        "text": raw.get("text", ""),
        "bounding_box": raw.get("rect", {}),
        "computed_css": raw.get("styles", {}),
    }


def draw_highlight(src_path: str, out_path: str, bbox: dict) -> None:
    """Overlay a red highlight rectangle on a screenshot PNG.

    bbox keys: x, y, width, height (page coordinates, floats).
    Writes the result to out_path.
    """
    from PIL import Image, ImageDraw

    img = Image.open(src_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
    draw.rectangle(
        [(int(x), int(y)), (int(x + w), int(y + h))],
        outline="#ef4444",
        width=3,
    )
    img.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a page element and return its computed CSS as JSON."
    )
    parser.add_argument("url", help="Page URL to navigate to")
    parser.add_argument("--selector", "-s", help="CSS selector of the target element")
    parser.add_argument(
        "--xy", help='Page coordinates as "x,y" (e.g. "456,789")'
    )
    parser.add_argument(
        "--output", "-o", help="Write JSON to this file path (default: stdout only)"
    )
    args = parser.parse_args()

    # Resolve element identification method
    selector: Optional[str] = args.selector
    xy: Optional[tuple[int, int]] = None
    if args.xy:
        parts = args.xy.split(",")
        if len(parts) != 2:
            print("ERROR: --xy must be 'x,y' e.g. '456,789'", file=sys.stderr)
            sys.exit(1)
        xy = (int(parts[0].strip()), int(parts[1].strip()))

    # Find active brainstorm session
    screen_dir, _state_dir = find_session_dir()

    element_not_found = False

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        print(f"[inspect] Navigating to {args.url} ...", file=sys.stderr)
        page.goto(args.url, wait_until="networkidle", timeout=30000)

        # Screenshot → brainstorm display
        tmp_ss = "/tmp/inspect_screenshot.png"
        page.screenshot(path=tmp_ss, full_page=True)

        if screen_dir:
            ss_dest = os.path.join(screen_dir, "inspect_screenshot.png")
            shutil.copy2(tmp_ss, ss_dest)
            # Write brainstorm screen pointing at the screenshot
            html_path = os.path.join(screen_dir, "inspect_view.html")
            with open(html_path, "w") as f:
                f.write(
                    '<h2>Element Inspector</h2>'
                    '<p class="subtitle">Page loaded — respond in terminal with selector or x,y coordinates</p>'
                    f'<img src="inspect_screenshot.png" style="max-width:100%;border:1px solid rgba(255,255,255,.1);border-radius:6px">'
                )
            print(f"[inspect] Screenshot displayed at brainstorm.kytranempowerment.com", file=sys.stderr)
        else:
            print(f"[inspect] No brainstorm session — screenshot saved to {tmp_ss}", file=sys.stderr)

        # If no selector/xy provided, ask interactively
        if selector is None and xy is None:
            print(
                '\n[inspect] Identify the element:\n'
                '  CSS selector: e.g. "#roster-header" or ".agent-card"\n'
                '  Coordinates:  e.g. "x=456 y=789"\n'
                '  Text search:  e.g. "text=ARCHIE"\n',
                file=sys.stderr,
            )
            user_input = input(">>> ").strip()
            if user_input.startswith("x="):
                try:
                    parts = user_input.split()
                    xy = (int(parts[0][2:]), int(parts[1][2:]))
                except (IndexError, ValueError):
                    print("[inspect] ERROR: coordinates must be 'x=N y=M' e.g. 'x=456 y=789'", file=sys.stderr)
                    sys.exit(1)
            elif user_input.startswith("text="):
                selector = f':text("{user_input[5:]}")'
            else:
                selector = user_input

        # Inspect the element
        details = get_element_details(page, selector=selector, xy=xy)
        element_not_found = not details["found"]

        if element_not_found:
            label = selector or (f"x={xy[0]},y={xy[1]}" if xy else "unknown")
            print(f"[inspect] ERROR: No element found for '{label}'", file=sys.stderr)

        if not element_not_found:
            # Draw highlight on screenshot
            highlighted_path = "/tmp/inspect_highlighted.png"
            draw_highlight(tmp_ss, highlighted_path, details["bounding_box"])
            if screen_dir:
                shutil.copy2(highlighted_path, os.path.join(screen_dir, "inspect_highlighted.png"))
                # Update brainstorm screen with highlighted version
                html_path = os.path.join(screen_dir, "inspect_result_highlighted.html")
                with open(html_path, "w") as f:
                    f.write(
                        f'<h2>{details["tag"]}#{details["id"]} .{" .".join(details["classes"][:3])}</h2>'
                        '<p class="subtitle">Element identified — see JSON output in terminal</p>'
                        '<img src="inspect_highlighted.png" style="max-width:100%;border:1px solid rgba(255,255,255,.1);border-radius:6px">'
                    )

    if element_not_found:
        sys.exit(1)

    # Output JSON
    output = json.dumps(details, indent=2)
    print(output)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"[inspect] JSON written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
