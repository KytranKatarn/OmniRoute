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
