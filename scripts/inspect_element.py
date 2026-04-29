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
from pathlib import Path
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
                screen_dir = data.get("screen_dir")
                state_dir = data.get("state_dir")
        except (json.JSONDecodeError, AttributeError):
            continue

    return screen_dir, state_dir
