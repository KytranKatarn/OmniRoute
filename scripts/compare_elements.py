#!/usr/bin/env python3
"""compare_elements.py — "make A look like B" CSS diff tool for Design Bridge Phase 1.

Extends inspect_element.py (task #2449): reuses get_element_details(), _CSS_PROPS,
draw_highlight(), and find_session_dir() to inspect two elements (A = the broken /
target element, B = the reference element), diff their computed CSS, and emit the
CSS rule block that makes A match B.

Usage:
    # Two elements on different pages:
    python scripts/compare_elements.py <urlA> <urlB> \\
        --selector-a ".broken" --selector-b ".reference"

    # Two elements on the SAME page (urlB defaults to urlA):
    python scripts/compare_elements.py <url> \\
        --selector-a ".broken" --selector-b ".reference"

    # By page coordinates:
    python scripts/compare_elements.py <urlA> <urlB> \\
        --xy-a "100,200" --xy-b "300,400"

Output:
    - Readable diff table → stderr
    - JSON {elementA, elementB, diff, generated_css} → stdout (and --output FILE)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Optional

# Reuse the inspect_element plumbing (both files live in scripts/).
from inspect_element import (  # noqa: E402
    _CSS_PROPS,
    draw_highlight,
    find_session_dir,
    get_element_details,
)

# Widen the comparison surface beyond inspect_element's base 20 props.
# These are the layout/typography/border properties most likely to differ
# when one element looks "off" versus a reference.
_EXTRA_PROPS = [
    "align-items", "justify-content", "line-height", "letter-spacing",
    "text-align", "border-width", "border-style", "border-color",
    "min-width", "max-width", "min-height", "max-height",
]

# Preserve order, no duplicates.
_COMPARE_PROPS = list(dict.fromkeys(_CSS_PROPS + _EXTRA_PROPS))


def diff_styles(a: dict, b: dict) -> dict:
    """Return {prop: {"A": valA, "B": valB}} for every prop where A and B differ.

    `a` and `b` are the `computed_css` dicts from get_element_details(). Props
    present in only one side are still reported (missing side as empty string).
    """
    css_a = a.get("computed_css", {})
    css_b = b.get("computed_css", {})
    diff: dict = {}
    for prop in _COMPARE_PROPS:
        val_a = css_a.get(prop, "")
        val_b = css_b.get(prop, "")
        if val_a != val_b:
            diff[prop] = {"A": val_a, "B": val_b}
    return diff


def _selector_for_rule(details: dict, fallback: Optional[str]) -> str:
    """Build a CSS selector string for the generated rule block.

    Prefers the user-supplied selector; otherwise derives one from the element's
    id or first class; otherwise falls back to the lowercased tag name.
    """
    if fallback:
        return fallback
    if details.get("id"):
        return f"#{details['id']}"
    classes = details.get("classes", [])
    if classes:
        return "." + ".".join(classes)
    tag = details.get("tag", "div")
    return tag.lower()


def generate_css(diff: dict, selector: str) -> str:
    """Emit a CSS rule block applying B's values to selector A.

    Returns a string like:
        .broken {
            color: #fff;
            padding: 8px 12px;
        }
    """
    if not diff:
        return f"{selector} {{\n    /* No differences — A already matches B */\n}}"
    lines = [f"{selector} {{"]
    for prop in sorted(diff):
        lines.append(f"    {prop}: {diff[prop]['B']};")
    lines.append("}")
    return "\n".join(lines)


def _print_diff_table(diff: dict) -> None:
    """Print a human-readable A-vs-B diff table to stderr."""
    if not diff:
        print("[compare] No computed-CSS differences found.", file=sys.stderr)
        return
    prop_w = max((len(p) for p in diff), default=8)
    a_w = max((len(d["A"]) for d in diff.values()), default=1)
    a_w = max(a_w, len("A (target)"))
    header = f"{'property'.ljust(prop_w)}  {'A (target)'.ljust(a_w)}  B (reference)"
    print(f"\n[compare] {len(diff)} differing properties:", file=sys.stderr)
    print(header, file=sys.stderr)
    print("-" * len(header), file=sys.stderr)
    for prop in sorted(diff):
        d = diff[prop]
        a_val = d["A"] or "(unset)"
        b_val = d["B"] or "(unset)"
        print(f"{prop.ljust(prop_w)}  {a_val.ljust(a_w)}  {b_val}", file=sys.stderr)
    print("", file=sys.stderr)


def _parse_xy(raw: Optional[str], label: str) -> Optional[tuple[int, int]]:
    """Parse an 'x,y' string into an (int, int) tuple, or None."""
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        print(f"ERROR: --xy-{label} must be 'x,y' e.g. '456,789'", file=sys.stderr)
        sys.exit(1)
    return (int(parts[0].strip()), int(parts[1].strip()))


def _inspect_on_page(page, url: str, selector, xy, label: str) -> dict:
    """Navigate to url and inspect one element. Exits on not-found."""
    print(f"[compare] [{label}] Navigating to {url} ...", file=sys.stderr)
    page.goto(url, wait_until="networkidle", timeout=30000)
    # Use the widened prop list for both elements.
    details = get_element_details(page, selector=selector, xy=xy)
    if not details.get("found"):
        ident = selector or (f"x={xy[0]},y={xy[1]}" if xy else "unknown")
        print(f"[compare] ERROR: No element {label} found for '{ident}'", file=sys.stderr)
        sys.exit(1)
    return details


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Diff computed CSS of two elements and generate CSS to '
        'make element A look like element B.'
    )
    parser.add_argument("url_a", help="Page URL for element A (the target/broken element)")
    parser.add_argument(
        "url_b",
        nargs="?",
        default=None,
        help="Page URL for element B (the reference). Defaults to url_a (same page).",
    )
    parser.add_argument("--selector-a", help="CSS selector of element A")
    parser.add_argument("--selector-b", help="CSS selector of element B")
    parser.add_argument("--xy-a", help='Element A page coordinates "x,y"')
    parser.add_argument("--xy-b", help='Element B page coordinates "x,y"')
    parser.add_argument(
        "--output", "-o", help="Write JSON to this file path (default: stdout only)"
    )
    parser.add_argument(
        "--screenshots",
        action="store_true",
        help="Also render highlighted screenshots to the brainstorm display",
    )
    args = parser.parse_args()

    url_b = args.url_b or args.url_a

    selector_a = args.selector_a
    selector_b = args.selector_b
    xy_a = _parse_xy(args.xy_a, "a")
    xy_b = _parse_xy(args.xy_b, "b")

    if selector_a is None and xy_a is None:
        print("ERROR: provide --selector-a or --xy-a for element A", file=sys.stderr)
        sys.exit(1)
    if selector_b is None and xy_b is None:
        print("ERROR: provide --selector-b or --xy-b for element B", file=sys.stderr)
        sys.exit(1)

    screen_dir, _state_dir = find_session_dir()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        details_a = _inspect_on_page(page, args.url_a, selector_a, xy_a, "A")
        if args.screenshots:
            tmp_a = "/tmp/compare_a.png"
            page.screenshot(path=tmp_a, full_page=True)
            draw_highlight(tmp_a, "/tmp/compare_a_hl.png", details_a["bounding_box"])

        details_b = _inspect_on_page(page, url_b, selector_b, xy_b, "B")
        if args.screenshots:
            tmp_b = "/tmp/compare_b.png"
            page.screenshot(path=tmp_b, full_page=True)
            draw_highlight(tmp_b, "/tmp/compare_b_hl.png", details_b["bounding_box"])

        if args.screenshots and screen_dir:
            for src, name in (
                ("/tmp/compare_a_hl.png", "compare_a_hl.png"),
                ("/tmp/compare_b_hl.png", "compare_b_hl.png"),
            ):
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(screen_dir, name))
            html_path = os.path.join(screen_dir, "compare_view.html")
            with open(html_path, "w") as f:
                f.write(
                    '<h2>Element Comparison — make A look like B</h2>'
                    '<p class="subtitle">A = target (left), B = reference (right)</p>'
                    '<div style="display:flex;gap:12px">'
                    '<div><strong>A (target)</strong><br>'
                    '<img src="compare_a_hl.png" style="max-width:100%;border:1px solid rgba(255,255,255,.1);border-radius:6px"></div>'
                    '<div><strong>B (reference)</strong><br>'
                    '<img src="compare_b_hl.png" style="max-width:100%;border:1px solid rgba(255,255,255,.1);border-radius:6px"></div>'
                    '</div>'
                )
            print(
                "[compare] Side-by-side screenshots displayed at "
                "brainstorm.kytranempowerment.com",
                file=sys.stderr,
            )

        browser.close()

    diff = diff_styles(details_a, details_b)
    rule_selector = _selector_for_rule(details_a, selector_a)
    generated_css = generate_css(diff, rule_selector)

    _print_diff_table(diff)
    print("[compare] Generated CSS:\n", file=sys.stderr)
    print(generated_css, file=sys.stderr)
    print("", file=sys.stderr)

    result = {
        "elementA": details_a,
        "elementB": details_b,
        "diff": diff,
        "generated_css": generated_css,
    }
    output = json.dumps(result, indent=2)
    print(output)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"[compare] JSON written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
