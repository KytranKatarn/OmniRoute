#!/usr/bin/env python3
"""Replace old nav in all HTML files with the new mega-dropdown nav partial."""
import os
import re
import glob

SITE_DIR = os.path.dirname(os.path.abspath(__file__))

# Read the nav partial
with open(os.path.join(SITE_DIR, '_nav-partial.html'), 'r', encoding='utf-8') as f:
    nav_partial = f.read().strip()

# Indent the nav partial to match typical indentation (4 spaces)
nav_indented = '\n'.join('    ' + line if line.strip() else '' for line in nav_partial.split('\n'))

html_files = sorted(glob.glob(os.path.join(SITE_DIR, '*.html')))

replaced = 0
skipped = 0

for filepath in html_files:
    basename = os.path.basename(filepath)
    # Skip partials (files starting with _)
    if basename.startswith('_'):
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern: match from <nav to </nav> (greedy enough to get the whole nav block)
    # Also capture any leading whitespace/comments before <nav
    nav_pattern = re.compile(
        r'([ \t]*(?:<!--[^>]*Navigation[^>]*-->\s*)?)'  # optional comment before nav
        r'<nav\b[^>]*>.*?</nav>',
        re.DOTALL
    )

    match = nav_pattern.search(content)
    if not match:
        print(f"  SKIP (no nav found): {basename}")
        skipped += 1
        continue

    # Also check for and remove any old mobile menu div that follows the nav
    # Look for div.nav-mobile or div#mobileMenu or div with mobile-menu class
    old_mobile_pattern = re.compile(
        r'\s*<div\s+(?:class="(?:nav-mobile|mobile-menu)[^"]*"|id="(?:navMobile|mobileMenu)")[^>]*>.*?</div>\s*(?=\s*<)',
        re.DOTALL
    )

    # Replace the nav
    leading = match.group(1) or '    '
    # Use the leading whitespace from the original nav
    indent = '    '

    # Build replacement with proper indentation
    replacement_lines = []
    for line in nav_partial.split('\n'):
        if line.strip():
            replacement_lines.append(indent + line)
        else:
            replacement_lines.append('')
    replacement = '\n'.join(replacement_lines)

    # Add the navigation comment back
    replacement = f'    <!-- Navigation -->\n{replacement}'

    new_content = content[:match.start()] + '\n' + replacement + '\n' + content[match.end():]

    # Remove any old mobile menu divs (shouldn't exist but just in case)
    new_content = old_mobile_pattern.sub('', new_content)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)

    replaced += 1
    print(f"  DONE: {basename}")

print(f"\nReplaced nav in {replaced} files, skipped {skipped}")
