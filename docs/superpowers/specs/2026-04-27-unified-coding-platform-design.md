# Sub-E: Unified Coding Platform — Design Spec
**Project**: #288 ARCHIE Command Center
**Task**: #2353
**Date**: 2026-04-27
**Status**: Approved by user

---

## Overview

Add coding shortcuts and feature planning to the archie.kytranempowerment.com Command
Center chat. Builds entirely on Sub-C's delegation system — no new backend framework,
just new command aliases, quick-action buttons, a planning system prompt, and a Repair
Bay indicator.

---

## 1. Coding Slash Commands

Four new aliases handled in `doSend()` before the normal message path:

| Command | Capability | Department | Notes |
|---------|-----------|-----------|-------|
| `/review <description>` | `code_review` | Engineering & Technology (F.O.R.G.E.) | reason = description text |
| `/test` | `run_qa_suite` | Engineering & Technology (P.R.O.B.E.) | known-tool shortcut, no LLM |
| `/debug <description>` | `debug` | Engineering & Technology (F.O.R.G.E.) | reason = description text |
| `/plan <feature>` | Special — see Section 3 | ARCHIE + F.O.R.G.E. | |

`/review`, `/test`, `/debug` use the identical flow as `/delegate` (Sub-C): call
`POST /api/delegation/submit`, render a `DelegationCard`, poll for results. Only `/plan`
has special behaviour.

---

## 2. Quick-Action Pill Buttons

Three small pill buttons rendered between the chat input and SEND button, desktop only
(hidden ≤768px):

```html
<div class="ac-quick-actions" id="ac-quick-actions">
  <button class="ac-quick-btn" data-cmd="/review ">Review Code</button>
  <button class="ac-quick-btn" data-cmd="/test">Run Tests</button>
  <button class="ac-quick-btn" data-cmd="/plan ">Plan Feature</button>
</div>
```

Behaviour:
- **Run Tests**: inserts `/test` into input, fires immediately (no text needed)
- **Review Code**: inserts `/review ` into input, moves focus to input for user to complete
- **Plan Feature**: inserts `/plan ` into input, moves focus for user to describe feature

CSS: `.ac-quick-actions` flex row gap-6px, hidden below 768px. `.ac-quick-btn` small
pill with cyan border, matches LCARS theme.

---

## 3. `/plan` — Feature Planning

`/plan build a LinkedIn post scheduler` triggers ARCHIE's LLM (NOT a direct delegation).
`doSend()` detects `/plan ` prefix and sends it as a normal chat message with `is_plan_request=true`
in the body.

`api_chat_send_message` checks `is_plan_request=true` and prepends `_PLANNING_SYSTEM_PROMPT`
to the ARCHIE system prompt for that single request.

### _PLANNING_SYSTEM_PROMPT

```
[FEATURE PLANNING] The user wants to plan a software feature. Your job:
1. Decompose the feature into 3-5 concrete implementation tasks (ordered)
2. Present the plan clearly in your response
3. Include ONE {{DELEGATE}} marker for the FIRST task only:
   {{DELEGATE capability="code_review" reason="implement: <task 1 description>"}}

Format your response as:
"Here is the plan for [feature]:
1. [Task 1] — [brief description]
2. [Task 2] — [brief description]
...

Delegating task 1 to F.O.R.G.E. now."

Only delegate the first task. The user will kick off subsequent tasks manually.
```

ARCHIE responds with the plan as visible chat text + the `{{DELEGATE}}` marker fires
the first task automatically via the existing Sub-C pipeline. A `DelegationCard` appears
for task 1. The full plan text is persisted to `unified_messages` (with the marker
stripped as usual).

---

## 4. Repair Bay Indicator in Status Panel

New section added below Platform health in the right sidebar:

```
REPAIR BAY
⟳ 3 proposals pending   →
```

Clicking the row opens `http://192.168.1.200:3000/tools/repair-bay` in a new tab.

### New endpoint: `GET /api/internal/repair/count` (platform)

```python
@app.route("/api/internal/repair/count")
@_require_internal_key
def api_internal_repair_count():
    # Returns count of proposals with status IN ('proposed', 'approved', 'testing')
    with get_db_cursor() as (conn, cur):
        cur.execute(
            -- Verify table name: run \dt in psql and check repair_bay module
        -- Likely: repair_proposals with status IN ('proposed','approved','testing')
        "SELECT COUNT(*) AS cnt FROM repair_proposals WHERE status IN ('proposed', 'approved', 'testing')"
        )
        return jsonify({"count": cur.fetchone()["cnt"]})
```

### New endpoint: `GET /api/repair/count` (archie_comms)

Proxy to platform, same `INTERNAL_API_KEY` auth. Returns `{count: N}`.

`StatusPanel.refresh()` calls this and updates the repair bay section every 30s (different
from agent poll at 10s to reduce noise).

---

## Components Touched

| File | Change |
|------|--------|
| `platform_v2/app.py` | Add `GET /api/internal/repair/count` (reuses `_require_internal_key`) |
| `archie-comms/app_comms.py` | Add `GET /api/repair/count` proxy; accept `is_plan_request` in `api_chat_send_message` |
| `archie-comms/services/conversation_service.py` | Add `_PLANNING_SYSTEM_PROMPT`; inject when `is_plan_request=True` in `stream_send_message` |
| `archie-comms/static/js/archie-chat.js` | `/review`, `/test`, `/debug`, `/plan` command handlers in `doSend`; `StatusPanel` repair bay section; quick-action button wiring in boot |
| `archie-comms/static/css/archie-chat.css` | `.ac-quick-actions`, `.ac-quick-btn` styles |
| `archie-comms/templates/chat.html` | Quick-action buttons HTML between input and send |

---

## What This Does NOT Include

- A dedicated "Code" tab panel (future sprint)
- Multi-task parallel dispatch (user kicks off tasks one at a time)
- Repair Bay proposal preview in chat (link only — full UI in platform)
- OpenCode/Continue.dev IDE integration (future sprint)

---

## Success Criteria

1. `/review check the dispatch routing` → DelegationCard appears for F.O.R.G.E., resolves with review notes
2. `/test` → DelegationCard appears for P.R.O.B.E., resolves with QA results
3. Click "Plan Feature", type description, press Enter → ARCHIE responds with structured plan + task-1 delegation card fires
4. Right panel shows "REPAIR BAY · N proposals" updated every 30s
5. Clicking Repair Bay row opens platform repair bay in new tab
6. Quick-action buttons visible on desktop, hidden on mobile
7. No regression to Sub-A through Sub-D features
