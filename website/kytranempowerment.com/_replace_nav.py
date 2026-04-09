#!/usr/bin/env python3
"""Replace nav + lang overlay + mobile nav in all HTML files with the nav partial.

The partial contains everything from <nav> through the closing </div> of nav-mobile.
This script replaces the ENTIRE navigation block — not just <nav>...</nav>.
"""
import os
import re
import glob

SITE_DIR = os.path.dirname(os.path.abspath(__file__))

# Read the nav partial
with open(os.path.join(SITE_DIR, '_nav-partial.html'), 'r', encoding='utf-8') as f:
    nav_partial = f.read().strip()

html_files = sorted(glob.glob(os.path.join(SITE_DIR, '*.html')))

replaced = 0
skipped = 0

for filepath in html_files:
    basename = os.path.basename(filepath)
    if basename.startswith('_'):
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the start: <!-- Navigation --> or <nav
    start_pattern = re.compile(r'[ \t]*(?:<!--\s*Navigation\s*-->\s*)?<nav\b')
    start_match = start_pattern.search(content)
    if not start_match:
        print(f"  SKIP (no nav found): {basename}")
        skipped += 1
        continue

    # Find the end: last </div> of the nav-mobile block.
    # The partial ends with </div> after nav-mobile. We need to find
    # the closing </div> of nav-mobile in the page.
    # Strategy: find the LAST occurrence of nav-mobile's closing pattern
    # which is right before <!-- Page content --> or <main or <section
    # that is NOT inside nav.
    after_nav = content[start_match.start():]

    # Find where the page content begins (first <main or <!-- Page content -->)
    end_pattern = re.compile(r'\n[ \t]*(?:<!--\s*Page\s*content\s*-->|<main\b|<section\b(?!.*nav))')
    end_match = end_pattern.search(after_nav)

    if not end_match:
        # Fallback: just find </nav> and replace only that
        print(f"  WARN (no page content marker): {basename}")
        skipped += 1
        continue

    # The replacement region is from start_match.start() to start_match.start() + end_match.start()
    region_end = start_match.start() + end_match.start()

    # Build indented replacement
    indent = '    '
    replacement_lines = []
    for line in nav_partial.split('\n'):
        if line.strip():
            replacement_lines.append(indent + line)
        else:
            replacement_lines.append('')
    replacement = '\n'.join(replacement_lines)
    replacement = f'    <!-- Navigation -->\n{replacement}\n'

    new_content = content[:start_match.start()] + '\n' + replacement + '\n' + content[region_end:]

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)

    replaced += 1
    print(f"  DONE: {basename}")

print(f"\nReplaced nav in {replaced} files, skipped {skipped}")
