# Hire Visibility — Surface Pending Hiring Candidates in Roster + K.I.N.

**Date**: 2026-08-20
**Module**: Department HQ → Roster, K.I.N.
**Status**: design approved, implementation plan pending
**Sub-project**: B of 5 (A Roster table · **B this** · C agent lifecycle · D portraits · E identity & access)

---

## 1. Problem

K.I.N. proposes hires when it detects a capability gap. Those proposals land in
`hiring_candidates` and are **invisible from the two places you would look for them** — the
Roster (where the workforce is) and the K.I.N. tab (where workforce health is).

Measured 2026-08-20:

| `hiring_candidates.status` | count |
|---|---|
| **pending** | **15** |
| approved | 61 |
| rejected | 191 |
| expired | 131 |

Fifteen open proposals about missing capability, sitting in a surface nobody passes through
during normal work.

They are also **not** in `autonomy_approval_queue` — that table's pending rows are
`deploy_approve` (9), `linkedin_*` (15), `email_reply` (2), `improvement_approve_red` (2),
`website_deploy` (1). Any attempt to find hires by querying the approvals queue returns
nothing and reads as "there are no pending hires". This spec exists partly to remove that
trap.

## 2. Goals

1. Make the 15 pending candidates visible where the workforce is managed.
2. Show enough per candidate to triage without leaving the page.
3. Keep it strictly read-only.

## 3. Non-goals

- **No new writes.** Approving/rejecting continues to happen on the existing hiring surface
  (`/api/approvals/hire/...`, `approvals_routes.py`). This spec adds a window, not a door.
- **No change to how candidates are generated.** `kin_generate_hire_proposals` and
  `recommend_pool_staffing_gaps` are untouched.
- **No auto-hiring.** Unchanged: hires are human-approved.

## 4. Data

`hiring_candidates` columns (verified live):

```
id, capability, gap_reason, gap_alert_id, narrative, shortlist,
proposed_at, proposed_by_agent_id, status, chosen_agent_id,
decided_by_user_id, decided_at, decision_notes,
precheck_status, precheck_message
```

Displayed per candidate: `capability`, `gap_reason`, `precheck_status` +
`precheck_message`, `proposed_at` (age), and a link into the existing approval surface.
`narrative` and `shortlist` are shown on expand, not in the strip.

⚠️ `proposed_at`, not `created_at` — the table has no `created_at` column.

## 5. Design

### 5.1 New endpoint

`GET /tools/department-hq/api/hiring/pending` — `@admin_required`.

```
{ "candidates": [ {"id":…, "capability":"…", "gap_reason":"…",
                   "precheck_status":"…", "precheck_message":"…",
                   "proposed_at":"…", "age_hours": N} ],
  "count": 15 }
```

Ordered newest first. Bounded `LIMIT 50` with the total reported separately, so a
truncated list never reads as the complete set.

### 5.2 Roster — "Needed agents" strip

A collapsible strip above the roster table (sub-project A's surface), rendering
`⚠ 15 agents proposed but not hired`. Collapsed by default when count is 0 — and when the
count is 0 it renders as an explicit empty state, never as an absent element, so "no
proposals" is distinguishable from "the panel failed to load".

Each row: capability · gap reason · precheck badge · age · link.

### 5.3 K.I.N. tab — same data, workforce-health framing

The same endpoint feeds a counter beside the existing welfare cards. K.I.N. already owns
staffing-gap logic (`recommend_pool_staffing_gaps`), so this is the natural second home —
a gap it proposed, still open.

### 5.4 Shared renderer

One render function used by both mounts. Two copies of this list is how they drift; the
Roster's own duplicated count-query (sub-project A §8) is the same mistake one file away.

## 6. Interaction with sub-project A

B renders into A's surface, but does not depend on A's internals: the strip sits above the
table and reads its own endpoint. If A ships first, B mounts into it. If B ships first, it
mounts above the existing table. Either order works.

## 7. Testing

**Unit**
- Endpoint returns only `status='pending'` — not approved/rejected/expired.
- `age_hours` computed **in SQL** — `hiring_candidates.proposed_at` must be checked for
  `timestamp WITHOUT time zone` before any Python arithmetic; a naive/aware mismatch raises
  `TypeError` (this exact bug 500'd the whole K.I.N. tab once — KB #283579).
- Count of 0 returns an empty list plus `count: 0`, not a 404 or a null.
- Truncation: with >50 pending, `count` reports the true total.

**Live browser drive** — required. Verify the strip renders on both mounts, the counts
agree with the DB, and the empty state appears rather than a missing panel.

## 8. Risks

| risk | mitigation |
|---|---|
| Panel silently absent on load failure vs. genuinely zero | explicit empty state; never render-nothing |
| Naive/aware timestamp `TypeError` 500s the tab | compute age in SQL (§7) |
| Two renderers drift | one shared render function (§5.4) |
| A truncated list reads as complete | `LIMIT 50` + true `count` reported separately |

## 9. Open questions

None.
