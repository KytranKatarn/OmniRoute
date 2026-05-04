# SIGNAL Calendar — Living Dashboard — Design Spec

**Date**: 2026-05-04
**Project**: TBD — successor of Project #316 (Agent Social Identity SP3+SP4) or new
**Triggered by**: 2026-05-04 9 AM #1111 outage — failed silently for hours because the SIGNAL Calendar tab showed scheduled slots only, not actual post status. No surface existed where a single glance would catch a stuck daily post.

## Goal

Turn the DHQ → Department HQ → S.I.G.N.A.L. → Calendar sub-tab into the **single living dashboard** for the entire LinkedIn posting pipeline. Each day-cell shows the actual lifecycle state of every post (drafted → Telegram approval → executing → posted | failed | rejected | deferred). One click from the calendar opens a modal with full content, error diagnostics, action buttons, and a synchronized Telegram deep-link.

The calendar becomes the surface where Kytran catches stuck posts at a glance and retries them from a single click — no more digging through Telegram, DB, or skill logs.

## Out of scope (v2 follow-ons)

- Inline content editing before approval
- Engagement metrics (likes, comments, impressions) per post
- Drag-and-drop to reschedule posts
- Server-Sent Events (SSE) live push (v1 uses 30s polling)
- 30-day backfill / month view (v1 = current week only)
- Personal-account-specific UX differences (v1 reuses same calendar UI for all 3 accounts)

## State of the world (recon)

| Component | Current state |
|---|---|
| `social_content_calendar` | Theme schedule template (3 rows). `(day_of_week, slot_order, theme_id, account?)` |
| `social_content_themes` | 9 themes |
| `autonomy_approval_queue` | Source of truth for draft → approval → execution (action_type='linkedin_post', post_type='company'/'personal', execution_result jsonb) |
| `linkedin_post_log` | Final posted/failed log with status='posted'/'failed' |
| `GET /api/signal/calendar` | Returns 7-day theme grid (`get_week_calendar` in `tools/media_studio/services/calendar_service.py`) |
| `GET /api/signal/themes` | Returns themes with scenes |
| Existing JS | `loadSignalTab('calendar')` fetches `/api/signal/calendar` and renders. Currently shows theme slots, no post status. |
| Telegram approval flow | Inline-button callbacks (`esc_approve_<id>`, `esc_deny_<id>`) update `autonomy_approval_queue.status`. Calendar must read from same source. |
| Telegram message ID | **Need to verify**: is `telegram_message_id` stored on `autonomy_approval_queue`? If not, migration adds it (FK to `system_notifications` or new column). |

## Architecture

```
┌─ Source-of-truth tables (existing) ───────────────────────────┐
│  social_content_calendar  (theme schedule template)           │
│  social_content_themes    (9 themes)                          │
│  autonomy_approval_queue  (draft → pending → approved/denied  │
│                            → executed; execution_result)      │
│  linkedin_post_log        (final posted/failed)               │
└───────────────────────────────────────────────────────────────┘
            │
            ▼
   GET /api/signal/calendar/live?account=<personal|company|creed>
            │  (new endpoint — single JOIN across 4 tables)
            ▼
   {
     "account": "company",
     "week_start": "2026-05-04",
     "today": "2026-05-04",
     "days": [
       {
         "date": "2026-05-04",
         "is_today": true,
         "posts": [
           {
             "approval_id": 1111,
             "lang": "en",
             "status": "posted",                  # state machine: see Q4
             "post_type": "company",
             "drafted_at": "2026-05-04T13:00:43Z",
             "approved_at": "2026-05-04T13:12:33Z",
             "posted_at": "2026-05-04T16:04:47Z",
             "linkedin_url": "https://www.linkedin.com/feed/update/...",
             "preview": "🚀 WHY WE'RE BUILDING — THE BIGGER PICTURE 🚀\nIn today's AI landscape...",
             "telegram_message_id": 2583,
             "error": null
           },
           { /* FR equivalent */ }
         ]
       },
       /* 6 more days */
     ]
   }
            │
            ▼
   Frontend: 7-day horizontal grid; each cell stacks EN + FR chips
   Polling every 30 seconds (existing _signalTabTTL pattern)
```

### Container topology
No new containers. All in `archie_platform`. JS in `tools/department_hq/static/js/department-hq.js`. Backend in `tools/department_hq/social_routes.py` (new endpoint) + `tools/media_studio/services/calendar_service.py` (extended).

## Components

### 1. New endpoint — `GET /api/signal/calendar/live`

**Path**: `/tools/department-hq/api/signal/calendar/live`
**Auth**: `@admin_required` (existing pattern)
**Query params**:
- `account` (required) — `personal` | `company` | `creed`
- `week_start` (optional, defaults to current week's Monday)

**Response shape**: see Architecture diagram above.

**Implementation** (in `services/signal_calendar_live_service.py` — new file):

1. Compute `week_start` (Monday of given/current week) and `week_end` (Sunday).
2. Query `autonomy_approval_queue WHERE action_type = 'linkedin_post' AND post_type matches account AND created_at BETWEEN week_start AND week_end`. Returns N approval rows.
3. For each approval row:
   - Detect `lang` from action_data or reason text (English/Français pattern match)
   - Look up linkedin_post_log row for matching approval (if any) — gives final posted/failed status + url
   - Compute `status` via state classifier (Component 2)
4. Group rows by date → return 7-day array (empty arrays for days with no posts)
5. Cache with 30s TTL — calendar polling hits this hot path.

### 2. Status classifier — `services/signal_post_status.py`

Pure function: `classify(approval_row, post_log_row) -> status` where status is one of:

| status | Conditions |
|---|---|
| `pending` | approval_row.status='pending' (Telegram fired, awaiting tap) |
| `executing` | approval_row.status='approved' AND no execution_result yet |
| `posted` | post_log_row exists with status='posted' OR (approval_row.status='executed' AND execution_result.success=true) |
| `failed` | approval_row.status='executed' AND (execution_result.success=false OR execution_result._status in ('failed','timeout')) |
| `rejected` | approval_row.status='rejected' |
| `deferred` | approval_row.status='deferred_session' (Phase 4 of Layer A — not v1) |

Plus the **virtual** state (no DB row): `no_draft` — generated client-side when day-cell has no approval row for a given (account, lang).

### 3. Frontend chip component

In `static/js/department-hq.js`, extend `renderSignalCalendar`:

- 7 day-cells horizontally; today highlighted with cyan border.
- Each cell renders 0–2 chips (one per language). Empty cell shows "+ Draft now" ghost button.
- Chip = small rounded box with: language emoji + status icon + status color background.
- Visual matrix:

| status | bg color | icon | clickable? |
|---|---|---|---|
| posted | green-500 | ✓ | yes — modal with [Open on LinkedIn] |
| pending | amber-500 | ⏳ | yes — modal with [Approve] [Reject] |
| executing | blue-500 (pulsing) | ⟳ | yes — modal read-only "currently posting…" |
| failed | red-500 | ✗ | yes — modal with [Retry] [Mark Won't Fix] |
| rejected | grey-400 | 🚫 | yes — modal with [Re-draft] |
| deferred | purple-500 | ⏸ | yes — modal with [Reconnect] (Phase 5) |
| no_draft | grey-200 dashed border | — | yes — fires `signal_linkedin_draft(account, lang)` directly |

### 4. Click-through modal

Triggered on chip click. Renders into existing LCARS `bm-overlay` modal pattern (see `bridge.html` reference per `.claude/rules/frontend.md`).

Sections:
- **Header**: `{Account} · {Day} · {🇨🇦 EN | ⚜️ FR} · {Status badge}`
- **Content** (collapsible accordion): full post text + hashtags. Default expanded if state in {pending, failed}; collapsed if posted.
- **Error block** (only if state=failed): `error_text` + links to `screenshot_path` + diagnostic dump.
- **Timeline** (vertical list with timestamps and Telegram deep-link):
  ```
  09:00 ✓ Drafted
  09:00 ✓ Telegram sent → [▢ open in Telegram]
  09:12 ✓ Approved by Kytran
  09:13 ✗ Skill execution failed: Could not find Start a post button
  16:04 ✓ Manually retried — POSTED
  📎 https://www.linkedin.com/feed/update/urn:li:activity:...
  ```
- **Action row** (state-dependent — Q4 mapping):
  - posted → `[Open on LinkedIn]` `[Close]`
  - pending → `[Approve]` `[Reject]` `[Close]`
  - executing → `[Close]` (no actions while running)
  - failed → `[Retry]` `[Mark Won't Fix]` `[Close]`
  - rejected → `[Re-draft]` `[Close]`
  - deferred → `[Reconnect]` `[Close]`

### 5. Telegram synchronization

Two views on the **same** `autonomy_approval_queue` row. Modal action buttons hit the **same** backend endpoints as Telegram inline-button callbacks. State changes propagate to both surfaces via polling.

The Telegram deep-link in the timeline requires `telegram_message_id` to be on the approval row. **If absent, migration 373 adds it** (`ALTER TABLE autonomy_approval_queue ADD COLUMN telegram_message_id BIGINT`). The Telegram bot already knows the message_id when it fires the alert — needs a 1-line addition to `briefing_service` to persist it.

### 6. Action endpoints (mostly reuse)

| Action | Endpoint | Implementation |
|---|---|---|
| Approve | `POST /tools/department-hq/api/signal/pending/<approval_id>/approve` | **Exists** — reuse |
| Reject | `POST /tools/department-hq/api/signal/pending/<approval_id>/deny` | **Exists** — reuse |
| Retry | `POST /tools/department-hq/api/signal/posts/<approval_id>/retry` | **New** — re-fires skill with original action_data |
| Draft-now | `POST /tools/department-hq/api/signal/draft-now` body `{account, lang}` | **New** — wraps `signal_linkedin_draft(account_filter)` for single-language fire |
| Mark-won't-fix | `POST /tools/department-hq/api/signal/posts/<approval_id>/abandon` | **New** — marks status='abandoned' on approval row, no skill action |
| Re-draft | Same as Draft-now (just fires fresh) | reuse Draft-now |

### 7. Polling integration

Reuse existing pattern from `loadSignalTab(tab)` with TTL cache:
- Set `_signalTabTTL.calendar = 30` (seconds)
- Cache key includes `account` so switching busts stale data
- Re-poll on tab focus (existing `forceRefresh`)
- Existing pattern in `static/js/department-hq.js`

## Test plan

- **Unit (status classifier)**: each of 6 status enum values covered + edge cases (missing post_log, malformed execution_result, executed-but-success=true)
- **Unit (signal_calendar_live_service)**: returns 7-day array; correct lang detection; correct grouping by date; week boundaries (Mon-Sun)
- **Integration (endpoint)**: hit `/api/signal/calendar/live?account=company` for current week → matches fixture rows
- **E2E (today's #1111 case)**: open Calendar → see red ✗ chip on Today/EN → click → modal shows error + Retry → fires retry → polling 30s → chip turns green ✓
- **Telegram sync**: approve via Telegram → poll → chip moves pending→executing→posted within ≤30s

## Acceptance criteria (v1)

- [ ] `GET /api/signal/calendar/live?account=company` returns JOINed view with all 6 status states correctly classified
- [ ] Frontend 7-day grid renders chips with correct colors per state
- [ ] Click chip → modal opens with header/content/timeline/actions
- [ ] Calendar [Approve] button on a `pending` chip = same effect as Telegram [Approve] button
- [ ] [Retry] on failed chip re-fires skill; chip transitions to executing → posted (or stays failed with new error)
- [ ] [+ Draft now] on no_draft cell triggers `signal_linkedin_draft` for that account+lang
- [ ] Telegram deep-link in timeline opens chat at original message
- [ ] 30s polling auto-refreshes chip status without page reload
- [ ] All 3 accounts (Kytran / KE Inc. / Creed-AI) work via same UI; switching account in selector re-fetches

## Migration (if needed)

`platform_v2/database/migrations/373_telegram_message_id.sql`:
```sql
BEGIN;
ALTER TABLE autonomy_approval_queue
    ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_aaq_telegram_message
    ON autonomy_approval_queue(telegram_message_id)
    WHERE telegram_message_id IS NOT NULL;
COMMIT;
```

Skip if column already exists (verify during recon phase of plan).

## Implementation phases

| Phase | Scope | Effort |
|---|---|---|
| **1** | Migration + status classifier + signal_calendar_live_service + GET endpoint | ~3 hr |
| **2** | Frontend chip component + grid renderer + state→visual mapping | ~3 hr |
| **3** | Modal: header + content + timeline + action row + Telegram deep-link | ~3 hr |
| **4** | Action endpoints: retry, draft-now, abandon | ~2 hr |
| **5** | Polling integration + cache busting on account switch | ~1 hr |
| **6** | Tests (unit + integration + E2E) + acceptance verification | ~2 hr |

Estimated total: 14 hr (1.5–2 sessions).

## References

- Today's #1111 outage — was the trigger
- Layer A (Project: Browser Session Lifecycle) — Phase 1 shipped tonight (PR #531) provides foundation
- Phase 4 of Layer A introduces `deferred_session` status — calendar's `deferred` chip type wires to it
- Phase 5 of Layer A is noVNC sidecar — calendar's `[Reconnect]` action on `deferred` chips deep-links to it
- Existing pattern: `dispatch_pending_queue` + cold-model deferral
- KB #261583+ — S.I.G.N.A.L. Command tab implementation history
