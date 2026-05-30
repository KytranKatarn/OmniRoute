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
In Claude Code terminal (run from `/mnt/archie_brain`):
```bash
python3 scripts/inspect_element.py http://192.168.1.200:3000/tools/department-hq
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

## Examples

**Inspect by selector:**
```bash
python3 scripts/inspect_element.py http://192.168.1.200:3000/tools/department-hq --selector "#roster-header"
```

**Inspect by coordinates:**
```bash
python3 scripts/inspect_element.py http://192.168.1.200:3000 --xy "720,50"
```

**Save output to file:**
```bash
python3 scripts/inspect_element.py http://192.168.1.200:3000 --selector "body" --output /tmp/element.json
```

## Compare two elements — "make A look like B"

`scripts/compare_elements.py` extends the inspector: it inspects two elements
(A = the target/broken element, B = the reference), diffs their computed CSS, and
emits a CSS rule block that makes A match B. It reuses the same `get_element_details`,
`draw_highlight`, and brainstorm-display plumbing as `inspect_element.py`, plus a
widened property list (align-items, justify-content, line-height, letter-spacing,
text-align, border-*, min/max-width/height).

**Two elements on the same page** (`url_b` defaults to `url_a`):
```bash
python3 scripts/compare_elements.py http://192.168.1.200:3000/tools/department-hq \
    --selector-a ".broken-card" --selector-b ".reference-card"
```

**Two elements on different pages:**
```bash
python3 scripts/compare_elements.py <urlA> <urlB> \
    --selector-a ".broken" --selector-b ".reference"
```

**By page coordinates:**
```bash
python3 scripts/compare_elements.py <url> --xy-a "100,200" --xy-b "300,400"
```

**With side-by-side highlighted screenshots and saved JSON:**
```bash
python3 scripts/compare_elements.py <url> \
    --selector-a ".broken" --selector-b ".reference" \
    --screenshots --output /tmp/compare.json
```

Output: a readable diff table + generated CSS on stderr, and JSON
`{elementA, elementB, diff, generated_css}` on stdout (and `--output FILE`).
