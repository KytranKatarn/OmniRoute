# Design Bridge Phase 1 — Playwright Element Inspector

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/inspect_element.py` — a Playwright script that navigates to any URL, shows the page screenshot in the brainstorm browser, takes a selector or coordinates from the terminal, and returns a JSON report of the identified element's computed CSS, bounding box, and metadata.

**Architecture:** The script uses Playwright's sync API to navigate and query elements. The brainstorm browser (brainstorm.kytranempowerment.com) is used as a read-only display (shows the screenshot for spatial reference). The terminal is the interaction channel (user types selector or "x=N y=N" coordinates). The script reads the active brainstorm session from `/tmp/brainstorm-launcher.log`. Three pure helper functions (`find_session_dir`, `get_element_details`, `draw_highlight`) are tested in isolation; the main CLI function wires them together.

**Tech Stack:** Python 3.11, `playwright` (sync_api), `Pillow` (PIL) for highlight overlay, `argparse`, `json`, `subprocess` (for screenshot fallback)

---

## File Structure

```
scripts/
  inspect_element.py          ← main script (~130 lines)
  inspect_element_workflow.md ← Claude Design handoff guide

platform_v2/tests/
  test_inspect_element.py     ← unit tests for pure helpers
```

---

### Task 1: `find_session_dir()` helper + tests

**Files:**
- Create: `scripts/inspect_element.py` (skeleton + `find_session_dir` only)
- Create: `platform_v2/tests/test_inspect_element.py`

- [ ] **Step 1: Write the failing test**

Create `platform_v2/tests/test_inspect_element.py`:

```python
"""Tests for inspect_element.py helpers.

Run: docker exec archie_platform python -m pytest tests/test_inspect_element.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import patch

# The script is in scripts/, not on the Python path — import it directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))


class TestFindSessionDir:
    def test_returns_screen_dir_from_last_server_started_line(self, tmp_path):
        """find_session_dir reads screen_dir from last server-started entry in launcher log."""
        from inspect_element import find_session_dir

        log = tmp_path / "brainstorm-launcher.log"
        log.write_text(
            json.dumps({"type": "server-started", "screen_dir": "/old/session/content", "state_dir": "/old/session/state"})
            + "\n"
            + json.dumps({"type": "server-started", "screen_dir": "/new/session/content", "state_dir": "/new/session/state"})
            + "\n"
        )

        result = find_session_dir(log_path=str(log))
        assert result == ("/new/session/content", "/new/session/state")

    def test_returns_none_when_log_missing(self, tmp_path):
        """find_session_dir returns (None, None) when launcher log doesn't exist."""
        from inspect_element import find_session_dir

        result = find_session_dir(log_path=str(tmp_path / "nonexistent.log"))
        assert result == (None, None)

    def test_returns_none_when_no_server_started_entries(self, tmp_path):
        """find_session_dir returns (None, None) when log has no server-started lines."""
        from inspect_element import find_session_dir

        log = tmp_path / "brainstorm-launcher.log"
        log.write_text('{"error": "Server failed to start within 5 seconds"}\n')

        result = find_session_dir(log_path=str(log))
        assert result == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py::TestFindSessionDir -v
```

Expected: `ModuleNotFoundError: No module named 'inspect_element'`

- [ ] **Step 3: Create `scripts/inspect_element.py` with `find_session_dir`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py::TestFindSessionDir -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/inspect_element.py platform_v2/tests/test_inspect_element.py
git commit -m "feat(design-bridge): inspect_element.py skeleton + find_session_dir"
```

---

### Task 2: `get_element_details()` helper + tests

**Files:**
- Modify: `scripts/inspect_element.py` (add `get_element_details`)
- Modify: `platform_v2/tests/test_inspect_element.py` (add `TestGetElementDetails`)

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_inspect_element.py`:

```python
class TestGetElementDetails:
    def test_extracts_tag_and_id_from_page(self):
        """get_element_details returns tag, id, classes for a found element."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = [
            # First call: querySelector returns element info dict
            {
                "tag": "DIV",
                "id": "roster-header",
                "classes": ["lcars-header", "sc-live"],
                "text": "AI Roster",
                "rect": {"x": 10.0, "y": 20.0, "width": 800.0, "height": 48.0},
                "styles": {
                    "width": "800px",
                    "height": "48px",
                    "padding": "8px 16px",
                    "margin": "0px",
                    "font-size": "18px",
                    "font-family": "Orbitron, sans-serif",
                    "color": "rgb(0, 229, 255)",
                    "background-color": "rgba(0, 0, 0, 0)",
                    "border": "none",
                    "border-radius": "0px",
                    "display": "flex",
                    "position": "relative",
                    "top": "auto",
                    "left": "auto",
                    "flex": "0 0 auto",
                    "gap": "0px",
                    "z-index": "auto",
                    "opacity": "1",
                    "overflow": "visible",
                    "box-shadow": "none",
                },
                "found": True,
            }
        ]

        result = get_element_details(mock_page, selector="#roster-header")

        assert result["tag"] == "DIV"
        assert result["id"] == "roster-header"
        assert "lcars-header" in result["classes"]
        assert result["bounding_box"]["width"] == 800.0
        assert result["computed_css"]["font-size"] == "18px"
        assert result["found"] is True

    def test_returns_not_found_for_missing_selector(self):
        """get_element_details returns found=False when selector matches nothing."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.evaluate.return_value = {"found": False}

        result = get_element_details(mock_page, selector=".nonexistent-class")

        assert result["found"] is False

    def test_supports_xy_coordinates(self):
        """get_element_details accepts x,y coordinates and uses elementFromPoint."""
        from inspect_element import get_element_details
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.evaluate.return_value = {
            "tag": "IMG",
            "id": "",
            "classes": ["agent-avatar"],
            "text": "",
            "rect": {"x": 50.0, "y": 100.0, "width": 64.0, "height": 64.0},
            "styles": {"border-radius": "50%", "width": "64px"},
            "found": True,
        }

        result = get_element_details(mock_page, xy=(200, 350))

        assert result["tag"] == "IMG"
        assert result["found"] is True
        # Verify the correct evaluate call was made with elementFromPoint
        call_args = mock_page.evaluate.call_args[0][0]
        assert "elementFromPoint" in call_args
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py::TestGetElementDetails -v
```

Expected: `AttributeError: module 'inspect_element' has no attribute 'get_element_details'`

- [ ] **Step 3: Add `get_element_details` to `scripts/inspect_element.py`**

Add after `find_session_dir`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py::TestGetElementDetails -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Run all tests**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py -v
```

Expected: 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/inspect_element.py platform_v2/tests/test_inspect_element.py
git commit -m "feat(design-bridge): get_element_details — selector + xy coordinate support"
```

---

### Task 3: `draw_highlight()` helper + screenshot overlay

**Files:**
- Modify: `scripts/inspect_element.py` (add `draw_highlight`)
- Modify: `platform_v2/tests/test_inspect_element.py` (add `TestDrawHighlight`)

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_inspect_element.py`:

```python
class TestDrawHighlight:
    def test_creates_highlighted_image_file(self, tmp_path):
        """draw_highlight writes a new PNG with a red rectangle overlay."""
        from inspect_element import draw_highlight
        from PIL import Image, ImageDraw

        # Create a 400x300 white test image
        src = tmp_path / "screenshot.png"
        img = Image.new("RGB", (400, 300), "white")
        img.save(str(src))

        out = tmp_path / "highlighted.png"
        draw_highlight(
            src_path=str(src),
            out_path=str(out),
            bbox={"x": 50.0, "y": 80.0, "width": 200.0, "height": 60.0},
        )

        assert out.is_file()
        result = Image.open(str(out))
        assert result.size == (400, 300)

    def test_highlight_box_is_red(self, tmp_path):
        """draw_highlight draws a red (#ef4444) rectangle border."""
        from inspect_element import draw_highlight
        from PIL import Image

        src = tmp_path / "screenshot.png"
        Image.new("RGB", (400, 300), "white").save(str(src))

        out = tmp_path / "highlighted.png"
        draw_highlight(
            src_path=str(src),
            out_path=str(out),
            bbox={"x": 50.0, "y": 80.0, "width": 200.0, "height": 60.0},
        )

        result = Image.open(str(out))
        # Sample a pixel on the top edge of the highlight box
        pixel = result.getpixel((51, 80))
        # Should be red-ish (PIL uses RGB tuples)
        assert pixel[0] > 200 and pixel[1] < 100 and pixel[2] < 100
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py::TestDrawHighlight -v
```

Expected: `AttributeError: module 'inspect_element' has no attribute 'draw_highlight'`

- [ ] **Step 3: Add `draw_highlight` to `scripts/inspect_element.py`**

Add after `get_element_details`:

```python
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
```

- [ ] **Step 4: Run all tests**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py -v
```

Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/inspect_element.py platform_v2/tests/test_inspect_element.py
git commit -m "feat(design-bridge): draw_highlight — red box overlay on screenshot PNG"
```

---

### Task 4: Main CLI — navigate, screenshot, display, inspect, output

**Files:**
- Modify: `scripts/inspect_element.py` (add `main()` and `if __name__ == "__main__"`)

- [ ] **Step 1: Add `main()` to `scripts/inspect_element.py`**

Append after `draw_highlight`:

```python
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
            import shutil
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
                parts = user_input.split()
                xy = (int(parts[0][2:]), int(parts[1][2:]))
            elif user_input.startswith("text="):
                selector = f':text("{user_input[5:]}")'
            else:
                selector = user_input

        # Inspect the element
        details = get_element_details(page, selector=selector, xy=xy)

        if not details["found"]:
            label = selector or f"x={xy[0]},y={xy[1]}"
            print(f"[inspect] ERROR: No element found for '{label}'", file=sys.stderr)
            browser.close()
            sys.exit(1)

        # Draw highlight on screenshot
        highlighted_path = "/tmp/inspect_highlighted.png"
        draw_highlight(tmp_ss, highlighted_path, details["bounding_box"])
        if screen_dir:
            import shutil
            shutil.copy2(highlighted_path, os.path.join(screen_dir, "inspect_highlighted.png"))
            # Update brainstorm screen with highlighted version
            html_path = os.path.join(screen_dir, "inspect_result.html")
            with open(html_path, "w") as f:
                f.write(
                    f'<h2>{details["tag"]}#{details["id"]} .{" .".join(details["classes"][:3])}</h2>'
                    '<p class="subtitle">Element identified — see JSON output in terminal</p>'
                    '<img src="inspect_highlighted.png" style="max-width:100%;border:1px solid rgba(255,255,255,.1);border-radius:6px">'
                )

        browser.close()

    # Output JSON
    output = json.dumps(details, indent=2)
    print(output)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"[inspect] JSON written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x scripts/inspect_element.py
```

- [ ] **Step 3: Smoke test against the platform**

```bash
docker exec archie_platform python scripts/inspect_element.py \
  http://192.168.1.200:3000 \
  --selector "body" \
  --output /tmp/body_element.json
```

Expected output (JSON to stdout):
```json
{
  "found": true,
  "tag": "BODY",
  "id": "",
  "classes": [...],
  "text": "...",
  "bounding_box": {"x": 0.0, "y": 0.0, "width": 1440.0, "height": ...},
  "computed_css": {
    "width": "1440px",
    "display": "block",
    ...
  }
}
```

- [ ] **Step 4: Test with coordinates**

```bash
docker exec archie_platform python scripts/inspect_element.py \
  http://192.168.1.200:3000 \
  --xy "720,50"
```

Expected: JSON with the element found at center-top of the platform homepage.

- [ ] **Step 5: Run full test suite to ensure no regressions**

```bash
docker exec archie_platform python -m pytest tests/test_inspect_element.py tests/test_deploy_service.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/inspect_element.py
git commit -m "feat(design-bridge): main() CLI — navigate, screenshot, brainstorm display, inspect, JSON output"
```

---

### Task 5: Workflow guide

**Files:**
- Create: `scripts/inspect_element_workflow.md`

- [ ] **Step 1: Write the workflow guide**

Create `scripts/inspect_element_workflow.md`:

```markdown
# Design Bridge Phase 1 — Workflow Guide

Two AIs collaborate to fix visual layout issues:
- **Claude Design** — shows what you want it to look like
- **Playwright Element Inspector** — identifies what's currently broken

## The Workflow

### Step 1: Create your target in Claude Design
1. Open [claude.ai/design](https://claude.ai/design)
2. Describe or sketch the layout you want
3. Screenshot or export the Claude Design output

### Step 2: Inspect the broken element
In Claude Code terminal:
```bash
python scripts/inspect_element.py http://192.168.1.200:3000/tools/department-hq
```

The page screenshot appears in the brainstorm browser.
Then identify the problem element:
- By selector: `#roster-header`
- By text: `text=AI Directors`
- By coordinates: `x=456 y=789`

### Step 3: Share both with Claude Code
Paste the Claude Design screenshot into the terminal:
> "Make this element match the Claude Design mockup: [paste image]"

Claude Code now has:
- The **target** (Claude Design image)
- The **current state** (element JSON with exact CSS)
- The **gap** is obvious — write the fix

## Common Selectors for ARCHIE Platform

| What you see | Selector |
|---|---|
| Agent card | `.agent-card` |
| Department header | `.dept-header` |
| LCARS frame | `.bm-frame` |
| Nav sidebar | `.sc-sidebar` |
| Status badge | `.sc-badge` |

## Output JSON Fields

| Field | What it tells you |
|---|---|
| `tag` | HTML element type (DIV, SPAN, IMG...) |
| `id` | Element id attribute |
| `classes` | CSS class list |
| `bounding_box` | x, y, width, height in page pixels |
| `computed_css.width/height` | Actual rendered size |
| `computed_css.padding/margin` | Spacing values |
| `computed_css.font-size/color` | Typography |
| `computed_css.display/position` | Layout mode |
```

- [ ] **Step 2: Commit**

```bash
git add scripts/inspect_element_workflow.md
git commit -m "docs(design-bridge): Claude Design + element inspector workflow guide"
```

---

### Task 6: Push and close task

- [ ] **Step 1: Push to origin**

```bash
git push origin main
```

- [ ] **Step 2: Mark task #2449 complete in Dev HQ**

```python
# Run in Claude Code terminal:
mcp__archie__complete_task(task_id=2449, notes="inspect_element.py shipped — 8 tests, selector + xy + text= modes, brainstorm display, highlight overlay, workflow guide")
mcp__archie__complete_task(task_id=2450, notes="scripts/inspect_element_workflow.md written — Claude Design handoff workflow, common ARCHIE selectors, JSON field reference")
```

---

## Self-Review

### Spec coverage
- ✅ Navigate to URL via Playwright
- ✅ Screenshot + brainstorm browser display
- ✅ User input: selector, x/y coordinates, text= search
- ✅ Returns tag, id, classes, 20 computed CSS properties, bounding box, text content
- ✅ Red highlight box re-render
- ✅ JSON to stdout + optional --output file
- ✅ Auto-discovers brainstorm session from `/tmp/brainstorm-launcher.log`
- ✅ Fallback warning when no brainstorm session active
- ✅ Claude Design handoff workflow guide
- ✅ Tests for all 3 pure helpers

### No placeholders — all code is complete and runnable

### Type consistency
- `find_session_dir()` → `tuple[Optional[str], Optional[str]]` — used consistently in `main()`
- `get_element_details(page, selector, xy)` → `dict` — used consistently in `main()` and tests
- `draw_highlight(src_path, out_path, bbox)` — `bbox` is a dict with x/y/width/height — consistent with `get_element_details` return value
