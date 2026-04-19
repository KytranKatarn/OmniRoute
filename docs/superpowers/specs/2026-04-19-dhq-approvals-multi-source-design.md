# DHQ Approvals — Multi-Source Dispatch + Escalation Display

- **Date**: 2026-04-19
- **Project**: #261 LLM Resource Management — Agent Model Assignment + RAM Budget
- **Tasks closed**: #2162 (DHQ Approvals UI — tab + poller + approve/deny buttons), #2163 (Extend approve/deny endpoints to contractor + bridge_jobs sources)
- **Related KB**: morning session handoff (2026-04-19), `.claude/rules/department-hq-dispatch.md` § Approval Queue Surface

## Background

The Approvals tab, pending-list UI, 15s poller, 30s badge updater, LCARS confirm/reason modals, and history panel are all already shipped in `platform_v2/tools/department_hq/templates/department_hq.html`. The unified `GET /api/approvals/pending` endpoint (shipped this morning) returns rows from three sources with source-prefixed string IDs: `autonomy:123`, `contractor:456`, `bridge:789`.

The gap is that the web approve/deny endpoints only work for `autonomy_approval_queue` rows. The route is declared as `/api/approvals/<int:approval_id>/approve`, so `contractor:456` and `bridge:789` 404 at routing time. Even if routing worked, the SQL only touches `autonomy_approval_queue`.

A second gap: Telegram escalation notifications (`send_escalation_notification` in `ai_bridge/telegram_gateway.py`) bypass `services/telegram_service.py:send()` and call `bot.send_message()` directly. This means escalation Telegrams do **not** insert into `telegram_message_log` and do not appear in the DHQ COMs tab feed. The COMs tab is the audit feed for all platform Telegram activity, so escalations are a visibility hole.

A third observation: the escalation flow is `agent → director → A.R.C.H.I.E. → user`, but the approval card doesn't show that chain. Seeing *why* a request reached the user (which director passed it up) is useful context that can be derived from the agent's department via `smart_router.get_department_escalation_chain`.

## Goals

1. Web approve/deny works for all three approval sources, matching the Telegram approve semantics for each.
2. Approval cards render source-specific detail (compliance rule / contractor cost / cloud dispatch module) and show the escalation chain that produced them.
3. History panel shows approvals from all three sources, not just autonomy.
4. Escalation Telegrams appear in the COMs feed.

## Non-goals

- Re-dispatch logic for `bridge_jobs` after approval. Writing `status='approved'` on a bridge_jobs row is currently a dead-letter flag — no code reads it to resume the original dispatch. This spec covers the approval write only; the resume path is a follow-up (filed as a new task).
- Telegram parity beyond logging. The Telegram handler continues to only accept `esc_approve_<int>` for autonomy rows. Extending Telegram to handle contractor/bridge rows is out of scope.
- Cross-linking COMs ↔ Approvals tabs (e.g. clicking an escalation message jumps to its row). Nice-to-have, not required.
- Changes to `autonomy_approval_queue` approve/deny behaviour (already works, stays the same).

## Design

### 1. Backend — `approvals_routes.py`

**Route signature change.** Replace `<int:approval_id>` with `<path:approval_id>` on both `/approve` and `/deny` handlers so colons route correctly. Example: `/api/approvals/contractor:456/approve`.

**Prefix parsing.** At the top of each handler, split on `:` once. Reject inputs that don't match `{autonomy|contractor|bridge}:<int>` with 400. The numeric component becomes the primary key lookup.

**Three private helpers** (keep handlers thin):

- `_approve_autonomy(source_id, user_id)` — current SQL on `autonomy_approval_queue` (unchanged). Returns `(ok, action_type)`.
- `_approve_contractor(source_id, user_id)` — `UPDATE contractor_approval_requests SET status='approved', approved_by=%s, approved_at=NOW(), expires_at=NOW() + INTERVAL '14 days' WHERE id=%s AND status='pending' RETURNING task_type`. The 14-day window matches the lookup in `archie_bridge.request_contractor_approval`, which re-checks for any approved row within its `expires_at`.
- `_approve_bridge(source_id, user_id)` — `UPDATE bridge_jobs SET status='approved', completed_at=NULL WHERE id=%s AND status='pending_approval' RETURNING job_type`. Log a governance event noting the approval has no active consumer yet (so it's clear in audit logs why nothing happened downstream).

**Deny helpers** mirror the same shape:

- `_deny_autonomy` — unchanged (`status='rejected'`, `rejected_reason`).
- `_deny_contractor` — `status='denied'`, `denied_reason`, `denied_by`, `denied_at`.
- `_deny_bridge` — `status='cancelled'`, `cancellation_reason`, `cancelled_by`, `cancelled_at`. (If any of these columns don't exist on `contractor_approval_requests` / `bridge_jobs`, a migration adds them. Schema check is a first-step task in the implementation plan.)

**Escalation chain on `/pending`.** Each row gets a new `escalation_chain` field: a list of display names representing the chain up to A.R.C.H.I.E.

The chain is derived from:
1. The originating agent's department (looked up once per unique department in the request, not per row).
2. `smart_router.get_department_escalation_chain(department)` returns the escalation tier list. Exact return shape must be verified against the current implementation before coding — this spec assumes it yields an ordered list of department identifiers but implementation will confirm and adapt.
3. Map each tier to its department's director via `agent_service.get_agent_cache()`.
4. Prepend the originating agent; append `'A.R.C.H.I.E.'` as the terminal node. Consumers see the originating agent, every director in the escalation tier, and A.R.C.H.I.E. as the final hop to the user. If the chain is longer than 4 entries, truncate with an ellipsis entry (e.g. `Pixel → M.U.S.E. → … → A.R.C.H.I.E.`) to keep the UI line short.

Rows where the chain can't be derived (missing department, agent not in cache) get `escalation_chain: null`. UI hides the line when null.

**Unified `/api/approvals/history`.** Three SELECT queries, UNION-ed and sorted by `decided_at DESC LIMIT %s`. Each source contributes a normalised row:

```
{
  id: "autonomy:12" | "contractor:34" | "bridge:56",
  source: "autonomy_approval_queue" | "contractor_approval_requests" | "bridge_jobs",
  display_name: "...",
  status: "approved" | "denied" | "cancelled" | "executed" | "expired",
  decided_at: iso timestamp,
  decided_by: user_id | null,
  reason: string | null
}
```

`decided_at` maps to `approved_at` / `denied_at` / `cancelled_at` / `executed_at` / `expires_at` depending on status. History renderer only needs to display name + status + timestamp, so it stays simple.

### 2. Frontend — `department_hq.html`

**Row renderer specialization.** `_renderApprovalCard(a)` already branches on `a.category` for `compliance_fix`. Add two branches:

- `a.category === 'contractor_dispatch'`: render a details block with provider, model, estimated cost (bold red if `> 0.10`, amber if `> 0.01`, grey otherwise), estimated tokens. Example: `Provider: openai/gpt-4o-mini · Cost: $0.023 · Tokens: ~1,500`.
- `a.category === 'cloud_dispatch'`: render module source + first 200 chars of description. Example: `Module: media_studio · "Generate marketing banner for Printful launch..."`.

**Escalation chain line.** After the details block, before the buttons, add a subtle line:

```
<div class="dhq-approval-chain" style="font-size:0.7rem;color:#64748b;margin-bottom:8px">
  Escalated: Pixel → M.U.S.E. → A.R.C.H.I.E.
</div>
```

Rendered only when `a.escalation_chain` is a non-empty array. Joiner is `' → '`.

**Source badge pill.** Top-right of the card header, next to the priority badge:

- `AUTONOMY` — teal `#00e5ff`
- `CONTRACTOR` — amber `#fbbf24`
- `CLOUD` — purple `#a855f7`

This makes the three kinds of decisions visually distinguishable at a glance.

**Approve/deny button wiring.** No JS changes required. `a.id` already contains the prefix; the URL `/api/approvals/${a.id}/approve` works once the backend uses `<path:approval_id>`. The existing LCARS confirm / reason modals work unchanged.

### 3. Telegram → COMs linkage

`send_escalation_notification` currently constructs its message text, builds an `InlineKeyboardMarkup`, and calls `bot.send_message` directly. It does not insert into `telegram_message_log`, so the message is invisible to the COMs feed.

Fix: after the successful `bot.send_message` call (inside the `for row in rows` loop), insert a row into `telegram_message_log` with `category='escalation'`, `source_agent=context.get('agent_name')`, `title=f"Escalation #{approval_id}"`, `message=text`, `telegram_id=row[0]`, `status='sent'`. Use the same schema as `telegram_service.send()` does at line 352 — keep the INSERT inline here rather than refactoring through `telegram_service` because the escalation flow needs the inline button markup, and `telegram_service.send()` doesn't currently handle that.

This fix is small (~15 lines) and covers the gap without a wider refactor.

### 4. Tests / verification

**Unit** (new file `tests/test_approvals_multi_source.py`):

- `test_approve_autonomy_ok` — seed `autonomy_approval_queue`, POST `/approvals/autonomy:ID/approve`, assert DB state.
- `test_approve_contractor_sets_14d_expiry` — seed `contractor_approval_requests`, POST approve, assert `expires_at` is ~14d out.
- `test_approve_bridge_flips_status` — seed `bridge_jobs` with `status='pending_approval'`, POST approve, assert `status='approved'`.
- Mirror three `deny` tests.
- `test_invalid_prefix_400` — POST `/approvals/junk:123/approve` returns 400.
- `test_approve_idempotent` — second approve on already-approved row returns 404 (matches current pattern).

**Integration** (extend existing DHQ QA suite):

- Hit `/api/approvals/pending` with seed rows in all three tables; assert response shape includes `escalation_chain` field and source-prefixed IDs.
- Hit `/api/approvals/history` with rows in all three tables across approved/denied states; assert UNION returns all.

**Browser** (Playwright or manual):

- Open `/tools/department-hq/#approvals`; seed one row per source; verify rendering shows source badge, specialized details, escalation chain.
- Click approve on each; verify row disappears on next poll tick.
- Click deny on each; enter reason; verify row disappears.
- Check COMs tab after triggering a test escalation; verify the Telegram text shows in the feed with `source_agent` set.

### 5. Rollout + follow-ups

- Ship as a single PR (approx. 300–400 lines backend + frontend + tests).
- After merge, file follow-up tasks under Project #261:
  - "bridge_jobs resume path — consume `status='approved'` to re-dispatch original request" (medium).
  - "COMs ↔ Approvals cross-link — click escalation message to scroll to its approval row" (small, nice-to-have).

### 6. Risk + mitigation

- **Schema assumption** — `contractor_approval_requests` / `bridge_jobs` may not have `denied_reason` / `cancelled_reason` / `denied_by` / `cancelled_by` columns. Mitigation: first implementation step is a schema check; if missing, a small idempotent migration adds them.
- **Contractor re-lookup window** — 14 days is a defensible default but the existing code in `archie_bridge.request_contractor_approval` uses whatever `expires_at` was set at creation, not a fixed lookup window. If agents create new rows with a shorter expiry, the approval could outlive the new row's expiry. Verify the insert path's `expires_at` default before locking 14 days; adjust if needed.
- **Escalation chain derivation** — depends on `agent_service.get_agent_cache()` being populated and on the agent row having a `department` field. Cache is populated at boot; if it's empty, `escalation_chain` is null and the UI gracefully hides. No hard failure.
- **Telegram log schema drift** — if `telegram_message_log` schema changes between `telegram_service.send()` line 352 and here, the duplicated INSERT drifts. Mitigation: extract a small `_log_telegram_send(conn, cur, **fields)` helper in `telegram_service.py` and have both call it.
