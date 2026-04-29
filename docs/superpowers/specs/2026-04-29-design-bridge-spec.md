# Design Bridge — Visual Annotation & AI Collaboration Spec

> **Date:** 2026-04-29
> **Status:** Approved
> **Project:** #223 — Visual Layout Communication
> **Scope:** 3 phases — Phase 1 buildable now, Phase 3 is the target state

---

## Problem

When Claude Code works on UI layouts, there is no mechanism for pointing at visual elements. The user must describe problems in words ("the left column looks too narrow"), Claude measures pixels, misses the visual appearance issue, and iterates blind. KB #254918 documents 5 failure patterns from session 14. ADR-002 blocked all LCARS nav work until this tooling exists.

---

## Solution Overview

Two AIs collaborate:
- **Claude Design** (`claude.ai/design`) — user's target state. Shows what it should look like.
- **Claude Code + Playwright** — current state diagnosis. Identifies the exact element that's wrong, its computed styles, bounding box.

You direct the collaboration: share a Claude Design mockup in the terminal, point at what's broken on the live page, Claude Code bridges the gap.

---

## Phase 1 — Playwright Element Inspector (Build now)

### What it does
A Python + Playwright script (`scripts/inspect_element.py`) that:
1. Navigates to a URL
2. Takes a full-page screenshot
3. Serves the screenshot in the brainstorm browser (brainstorm.kytranempowerment.com)
4. User clicks the element they want identified
5. Script reads click coordinates from brainstorm events JSONL
6. Runs `document.elementFromPoint(x, y)` in the page
7. Returns: tag, id, classes, computed CSS (width, height, padding, margin, font-size, font-family, color, background-color, border, border-radius, display, position, top, left, flex, gap, z-index, opacity, overflow, box-shadow), bounding box (x, y, w, h), text content (first 100 chars)
8. Re-renders the screenshot with a red highlight box over the identified element
9. Outputs structured JSON to stdout — Claude Code reads it directly from terminal

The script auto-discovers the active brainstorm session by reading the last entry from `/tmp/brainstorm-launcher.log`. If no server is running it prints a warning and writes the screenshot to `/tmp/inspect_screenshot.png` as fallback.

### Entry point
```bash
python scripts/inspect_element.py <URL> [--output /tmp/element.json]
```

Claude Code terminal usage:
```
> python scripts/inspect_element.py http://192.168.1.200:3000/tools/department-hq
```

### Claude Design handoff workflow
1. User works in Claude Design → exports/screenshots the target mockup
2. User pastes the Claude Design image into the Claude Code terminal: "make it look like this"
3. Claude Code runs `inspect_element.py` on the live page → user clicks the problem element
4. Claude Code receives element JSON + has the Claude Design image → writes targeted CSS fix

### Files
- `scripts/inspect_element.py` — Playwright inspector (Python, ~120 lines)
- `scripts/inspect_element_workflow.md` — workflow guide + Claude Design handoff patterns
- `platform_v2/tests/test_inspect_element.py` — unit tests for element JSON parsing

---

## Phase 2 — Design Bridge Platform Module (Future)

### What it does
A new ARCHIE platform module (`design_bridge`) with a two-panel UI:
- **Left panel**: Claude Design output — user pastes image URL or uploads screenshot
- **Right panel**: Live Playwright screenshot of a running page with clickable elements
- **Output panel**: Structured comparison report — CSS diffs, missing elements, layout gaps
- Sessions stored in `design_bridge_sessions` DB table for reference

### Entry point
`/tools/design-bridge` in ARCHIE platform

### Key routes
- `POST /api/design-bridge/session` — create session with design_image + live_url
- `POST /api/design-bridge/inspect` — click coordinates → element details
- `GET /api/design-bridge/compare` — generate comparison report
- `POST /api/design-bridge/dispatch` — send delta to Claude Code via delegate_task

### Files
- `platform_v2/tools/design_bridge/` — Flask blueprint
- `platform_v2/tools/design_bridge/templates/` — LCARS two-panel UI
- `platform_v2/tools/design_bridge/comparison_service.py` — image diff + CSS delta logic
- `database/migrations/NNN_design_bridge.sql` — sessions table

---

## Phase 3 — Agent-to-Agent Design Comparison (Target state)

### What it does
A DHQ capability `design_comparison` owned by **Creative & Design** (M.U.S.E. as director). Claude Code delegates comparison tasks autonomously — no manual steps.

```python
delegate_task(
    capability='design_comparison',
    reason='User shared Claude Design mockup for DHQ roster page',
    context={
        'design_image_path': '/tmp/claude_design_export.png',
        'live_url': 'http://192.168.1.200:3000/tools/department-hq#roster',
        'focus_selector': '.agent-card',  # optional — focus comparison on a specific element
    },
    delegation_source='claude'
)
```

Agent returns:
```json
{
  "delta_summary": "3 layout differences found",
  "diffs": [
    {"element": ".agent-card", "property": "padding", "current": "8px", "target": "16px"},
    {"element": ".agent-avatar", "property": "border-radius", "current": "4px", "target": "50%"},
    {"element": ".agent-name", "property": "font-size", "current": "13px", "target": "15px"}
  ],
  "screenshot_annotated": "/tmp/design_bridge_annotated.png"
}
```

### Capability wiring
- Add `design_comparison` to `CAPABILITY_DEPARTMENT_MAP` → `"Creative & Design"`
- Seed M.U.S.E. with `design_comparison` Lv4 skill in `agent_skills`
- New `design_comparison_worker` job (on-demand, triggered by delegate_task)

### Files
- `platform_v2/services/design_comparison_service.py` — Playwright + image diff + CSS delta
- `platform_v2/tools/department_hq/services/department_coordinator.py` — add capability map entry
- `database/migrations/NNN_design_comparison_capability.sql` — M.U.S.E. skill seed

---

## Phase 1 Success Criteria

- `inspect_element.py <URL>` navigates to page, shows screenshot in brainstorm browser
- User clicks an element → JSON output includes tag, classes, top 20 computed CSS properties, bounding box
- Screenshot re-renders with highlight box over identified element
- Works on hub platform pages (192.168.1.200:3000) and public sites
- Claude Code can paste-read the JSON output directly from terminal
- Claude Design + element inspector workflow is documented and tested manually end-to-end

## Phase 3 Success Criteria (long-term)

- `delegate_task(capability='design_comparison', ...)` returns structured delta within 60s
- Delta report contains exact CSS property diffs Claude Code can act on without further clarification
- Zero manual steps between "here's my Claude Design mockup" and "here's what needs to change"
