# A.R.C.H.I.E. Unified Voice — Completion Design

**Date**: 2026-04-24
**Project**: #277 — A.R.C.H.I.E. Unified Voice — Sole Outbound Escalation Authority
**Tasks**: #2267, #2225, #2234, #2224, #2265, #2268
**Status**: Approved by user 2026-04-24

---

## Goal

Complete the Unified Voice project: A.R.C.H.I.E. becomes the sole path by which alerts, reports, and notifications reach Telegram. All direct Telegram callers are eliminated. The platform gets an operational inbox UI that complements the existing conversational interface at archie.kytranempowerment.com.

---

## Architecture

### Two Complementary Surfaces (Shared DB)

| Surface | Role | Triage? |
|---------|------|---------|
| `archie.kytranempowerment.com` | Conversational — chat with A.R.C.H.I.E., reports arrive as messages, escalation via dialogue | Yes (conversational) |
| Platform COMs tab (Dept HQ) | Operational — bulk triage, stats, policy management, ops context alongside fleet/roster | Yes (bulk/admin) |

Both surfaces read/write the same `director_reports` table. Actions in one are reflected in the other within 10 seconds. The COMs tab "Open in A.R.C.H.I.E." button bridges to the archie_comms chat for conversational follow-up on any report.

### Target Message Flow

```
Any sender (B.A.S.E., V.I.G.I.L., F.O.R.G.E., agent_loop, etc.)
    │
    ▼
director_report_service.submit_via_inbox()    [authenticated, X-Service-Token]
    │
    ▼
director_reports table (PostgreSQL)           [deduped via SELECT FOR UPDATE SKIP LOCKED]
    │
    ▼
triage_policy engine applies rules
    │ escalate only
    ▼
archie_triage_consumer → Telegram API         [sole exit point]
```

---

## Task Designs

### Task 1 — #2267: Source Verification (tiny)

**Problem**: platform_v2 → archie_comms POST calls carry no authentication. Any process that can reach port 3002 can inject reports.

**Fix**: Add `X-Service-Token: {ARCHIE_COMMS_SERVICE_TOKEN}` header to all platform_v2 calls to archie_comms. Reuses the existing env var and the same `hmac.compare_digest` check already in place on `/api/director/report`.

**Files**:
- `platform_v2/services/director_report_service.py` — verify header is on all POST calls (it already is on `submit_via_inbox`; audit for any others)
- `archie-comms/app_comms.py` — add token check to any internal endpoints not yet protected

**No new secrets needed** — `ARCHIE_COMMS_SERVICE_TOKEN` is already in docker-compose.yml.

---

### Task 2 — #2225: Migrate Direct Senders (medium)

**Problem**: Four call sites bypass the inbox and hit the Telegram API directly.

**Fix**: Each migrates to `director_report_service.submit_via_inbox(department, director_agent, category, title, summary, severity)`.

| Call site | Current | After |
|-----------|---------|-------|
| `tools/repair_bay/forge_pipeline.py` | `requests.post(sendMessage)` inline | `submit_via_inbox(department="Engineering & Technology", director_agent="F.O.R.G.E.", ...)` |
| `tools/repair_bay/forge_self_heal.py` | `_send_telegram(text)` helper | Same pattern, helper deleted |
| `ai_bridge/agent_loop.py:183` | `_send_approval_telegram()` → Telegram API | `submit_via_inbox(...)` — approval context maps to `category="approval_request"` |
| `platform_v2/services/telegram_service.py` send_* wrappers | `send_security/system/forge/agent/sync/info()` → `send()` → Telegram API | Each wrapper calls `submit_via_inbox()` with appropriate field mapping |

**Severity mapping**:
- `send_security` → severity=`critical`
- `send_system` → severity=`warning`
- `send_forge` / `send_sync` / `send_info` → severity=`info`
- `send_agent` → severity=`info`

---

### Task 3 — #2234: Gunicorn Race Condition (tiny)

**Problem**: archie_comms runs 2 gunicorn workers. Both can simultaneously read the same `pending` row from `director_reports` and send it to Telegram — double-send.

**Fix**: Use `SELECT ... FOR UPDATE SKIP LOCKED` when the triage consumer fetches pending reports. Any worker that can't lock a row skips it — guaranteed single processing per row.

```sql
SELECT * FROM director_reports
WHERE triage_status = 'pending'
ORDER BY severity_rank, created_at
FOR UPDATE SKIP LOCKED
LIMIT 10;
```

**File**: `archie-comms/app_comms.py` — the polling/dispatch function that reads and processes pending reports.

**Note**: This requires the fetch + status update to happen inside a single transaction (BEGIN → SELECT FOR UPDATE → UPDATE triage_status → COMMIT). Any error rolls back and the row stays available for the next cycle.

---

### Task 4 — #2224: Privilege Guardrail (medium)

**Problem**: Any code can call `telegram_service.send()` and bypass the inbox. Needs to be enforced at the code level after all callers are migrated.

**Fix**: `telegram_service.send()` raises `PermissionError` if `source_agent` is not in `_PRIVILEGED_SOURCES`. Hard error — not a soft redirect. By this point all callers must be migrated, so a loud failure is the right signal for anything that slipped through.

```python
_PRIVILEGED_SOURCES = frozenset({"A.R.C.H.I.E.", "archie_triage_consumer", "system_bootstrap"})

def send(category, title, message, source_agent, ...):
    if source_agent not in _PRIVILEGED_SOURCES:
        raise PermissionError(
            f"telegram_service.send() called by unprivileged source '{source_agent}'. "
            f"Use director_report_service.submit_via_inbox() instead."
        )
    ...
```

**File**: `platform_v2/services/telegram_service.py`

**Dependency**: Must be applied AFTER task 2 (all callers migrated).

---

### Task 5 — #2265: Final Routing Enforcement (medium)

**Problem**: After migration, confirm no direct Telegram API calls remain anywhere in the codebase outside archie-comms.

**Fix**:
1. Grep audit: search for `TELEGRAM_BOT_TOKEN`, `api.telegram.org`, `sendMessage` across entire codebase excluding `archie-comms/`
2. Remove or migrate any remaining callers found
3. Add a CI-style assertion: a test file `tests/test_telegram_isolation.py` that greps the codebase and fails if any direct Telegram API usage is found outside `archie-comms/`

**Files**: Any remaining callers found + `tests/test_telegram_isolation.py` (new)

---

### Task 6 — #2268: Unified Inbox UI (medium)

**Design**: Split pane replacing the current COMs director-reports view. Enhances (not replaces) the COMs tab — triage policies section stays below the split pane.

#### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ INBOX  [5 pending]                          [Mark all resolved] │
├─────────────────────────┬───────────────────────────────────────┤
│ ● CRITICAL  V.I.G.I.L.  │  V.I.G.I.L. — CRITICAL               │
│   Container probe warn  │  Container probe warning on archie_   │
│   2 min ago             │  platform                             │
│─────────────────────────│                                       │
│ ● WARNING   B.A.S.E.    │  Dept: Security & Compliance          │
│   Disk usage at 78%     │  Received: 2 min ago                  │
│   8 min ago             │  Severity: critical                   │
│─────────────────────────│                                       │
│ ● INFO      F.O.R.G.E.  │  archie_platform health probe         │
│   PR #290 complete      │  returned non-200. Auto-restart       │
│   15 min ago            │  attempted, container stable.         │
│                         │                                       │
│                         │  [ESCALATE] [SUPPRESS] [RESOLVE]      │
│                         │  [Open in A.R.C.H.I.E. ↗]            │
└─────────────────────────┴───────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ TRIAGE POLICIES                                   [+ Add rule]  │
│  (existing policies table)                                      │
└─────────────────────────────────────────────────────────────────┘
```

#### Behaviour

- **Left pane**: sorted by severity (critical → warning → info) then time. Click row → loads detail in right pane. Active row highlighted.
- **Right pane**: full report detail + 3 triage buttons (Escalate / Suppress / Resolve) + "Open in A.R.C.H.I.E." link that opens `https://archie.kytranempowerment.com` in a new tab.
- **Header**: pending count badge refreshed every 10s via `setInterval`. "Mark all resolved" bulk action.
- **Toggle**: "Show resolved" checkbox to include non-pending reports in the list.
- **Data**: `GET /api/coms/director-reports/pending` (exists). Triage actions: `POST /api/coms/director-reports/:id/ack` (exists). Both endpoints already built.
- **Refresh**: 10-second `setInterval` poll — consistent with other platform tab patterns. No websocket needed.

#### "Open in A.R.C.H.I.E." Link

Opens `https://archie.kytranempowerment.com` in a new tab. No deep-link to a specific report needed for MVP — the user navigates to the report in the chat interface. Future enhancement: add `?report_id=` query param if archie_comms supports it.

#### Files

- `platform_v2/tools/department_hq/coms_routes.py` — no route changes needed (all endpoints exist)
- `platform_v2/templates/tools/department_hq.html` — replace COMs tab director-reports section with split pane markup
- `platform_v2/static/css/department_hq.css` (or equivalent) — split pane styles using existing LCARS tokens

---

## Implementation Sequence

Execute in this order to avoid breaking anything mid-migration:

1. **#2267** — auth first (safe, additive)
2. **#2225** — migrate all senders (removes direct Telegram calls)
3. **#2234** — race condition fix (safe, DB-level)
4. **#2224** — enforce guardrail (safe only after #2225 complete)
5. **#2265** — audit + isolation test (verification pass)
6. **#2268** — UI (independent, can ship anytime)

Each task gets its own commit. All on branch `feat/unified-voice-completion-2277`. Single PR at end.

---

## Testing

| Task | Verification |
|------|-------------|
| #2267 | Remove token from a test POST to archie_comms — confirm 401 |
| #2225 | Send a forge_pipeline notification — confirm it appears in `director_reports`, NOT in Telegram directly |
| #2234 | Start 2 workers simultaneously processing same pending row — confirm single Telegram message sent |
| #2224 | Call `send("info", ...)` with unprivileged source — confirm `PermissionError` raised |
| #2265 | Run `test_telegram_isolation.py` — confirm 0 direct API calls found outside archie-comms |
| #2268 | Playwright: open COMs tab, confirm split pane loads, click report, verify detail pane, click Resolve, confirm row disappears |
