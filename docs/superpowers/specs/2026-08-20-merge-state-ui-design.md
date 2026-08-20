# Merge state must be visible before you click — design

**Date:** 2026-08-20 · **Status:** **Surface 1 IMPLEMENTED (PR #2737, open)** — Surface 2 (DHQ Approvals) still open · **For:** a fresh session

> **Update 2026-08-20:** Surface 1 (Repair Bay > PR Review) is built and live-verified — see PR #2737, KB #292213/#292214. The spec's open question about the stale #2717/#2713 `pr_merge` rows is ANSWERED: nothing closed them at all (not a resolver misfire, not pre-dating a fix) — fixed and shipped as #5862 / PR #2736. Surface 2's stale-row half therefore also landed; its merge-state DISPLAY half has not. Also still open: the SECOND Merge affordance at `static/js/repair-bay-main.js` ~333, which renders from a GitHub-shaped payload with no `merge_state`.

## Problem

The Merge affordance communicates nothing about whether the merge will succeed. You find out by
clicking and reading an alert.

Verified in `platform_v2/templates/tools/repair_bay.html` (~line 3544):

```js
if (pr.state === 'open') {
    mergeBtn.textContent = 'Merge';        // ALWAYS green, ALWAYS enabled
    mergeBtn.onclick = ... confirmMergePR(pr.pr_number);
}
```

The button is unconditionally green and enabled for **every open PR**. The badge beside it
(~line 3521) renders `pr.review_status`, whose green `reviewed` value is identical for an
APPROVE, a REQUEST CHANGES, and a coverage demotion. **A rejected PR displays a green badge next
to a green Merge button** — the UI actively signals "good to go" on something the gate refuses.

This is the trap the module index already documents in prose:
`review_status='reviewed'` means a review FINISHED, **not that it APPROVED** (root cause of #5194).

⚠️ **Second defect, observed live 2026-08-20:** the badge is also STALE. PR #2725's row still
read `in_progress` after the server held a fresh APPROVE — the list polls on a 30s timer. The
gate read live and merged correctly, so at the moment of the click the UI contradicted reality.

### Why this keeps happening

Same shape as three other defects fixed this week — state that exists but is not rendered:
- K.I.N. benched agents rendered pixel-identical to healthy (#5157)
- a mailbox with a forked credential rendered identical to a working one (#5844)
- a coverage demotion indistinguishable from a REQUEST CHANGES (#5834 follow-up)

## Principle (do not violate)

**The verdict rule stays on the SERVER. The UI renders a state; it never derives one.**

Re-deriving "is this approved" in JS would be a second implementation of a safety rule. #2722
existed specifically to collapse two such implementations into one (`verdict_refusal`), and
#2458 reached main because a safety rule lived in one path and not another. A JS copy would
reintroduce exactly that.

## Derived state

Compute server-side from the EXISTING functions — no new predicates:

| state | source condition |
|---|---|
| `reviewing` | `review_status='in_progress'` |
| `awaiting_review` | no review row, or `review_status='pending'`, or empty `ai_summary` |
| `approved` | `verdict_is_approved(summary)` |
| `coverage_only` | `coverage_only_demotion(summary)` (`pr_review_service`) |
| `changes_requested` | otherwise |

Also return `merge_hint` — reuse `verdict_refusal(summary, vok)`'s string VERBATIM so the row
and the refusal say the same words — and `dropped_files` from `coverage_dropped_paths(summary)`.

Order matters: check `approved` BEFORE `coverage_only`, and `coverage_only` before
`changes_requested`, or a demoted approval falls through to the wrong bucket.

## Surface 1 — Repair Bay → PR Review

Data: `pr_reviews` via `pr_review_service.list_reviews()` (currently `SELECT *`, ~line 787).
Render: `templates/tools/repair_bay.html` ~3505-3555. Merge handler `confirmMergePR` ~3675
(already coverage-ack aware from #2724). A second caller `_doMergePr` lives in
`static/js/repair-bay-main.js` ~487 — also already ack-aware. **Both must be updated or neither.**

| state | badge | Merge button |
|---|---|---|
| `approved` | **APPROVED** green | green **Merge** |
| `coverage_only` | **COVERAGE · N unread** amber | amber **Merge (N unread)** |
| `changes_requested` | **CHANGES REQUESTED** red | **disabled** — "Blocked — re-review" |
| `awaiting_review` | **WAITING FOR REVIEW** grey | **disabled** — "Waiting for review" |
| `reviewing` | **REVIEWING…** cyan | **disabled** — "Reviewing…" |

A disabled button must carry `title=merge_hint` so the reason is reachable without clicking.

**Staleness:** the 30s poll stays, but a row older than ~60s should visibly mark itself
(dim, or an `⧖` prefix) rather than assert a state it cannot vouch for. Mirror the pattern
already used by the K.I.N. tab's `stats_stale` (`⧖ stats <age> old`, PR #2454) instead of
inventing a new one.

## Surface 2 — DHQ → Approvals

Data: `autonomy_approval_queue`, `action_type='pr_merge'`. The tab's execution path
(`ai_bridge/agent_loop.py` ~5996) already computes the refusal via `tab_merge_refusal`
(`agent_loop.py:199`) — the row should DISPLAY what that path would decide, so the tap outcome
is predictable before tapping.

⚠️ **NOT YET INVESTIGATED — do this first.** I did not open the DHQ Approvals renderer. Locate
it (likely `tools/department_hq/static/js/department-hq.js`) and its list endpoint before
designing the markup. Do not assume it mirrors Repair Bay's shape.

**Additionally: show STALE rows.** Measured 2026-08-20: `pr_merge` rows for **#2717 and #2713**
sit `pending` against PRs that merged the previous day. Those are the orphans that get tapped
later against an already-merged PR — the #5283/#5338 third-surface bug. The row should show
"already merged" and be resolvable, and it is worth determining whether
`resolve_pr_merge_approval` simply is not firing on every surface or whether those two predate
the fix. **Determine which; do not assume.**

## Testing

1. Pure mapping table (summary → state) — no DB, no Flask. Include a REQUEST CHANGES that ALSO
   carries a coverage block: it must map to `changes_requested`, never `coverage_only`.
2. A guard asserting the JS does NOT reimplement verdict parsing — grep the templates/JS for
   `VERDICT`/`verdict_is_approved`-equivalents and fail if the rule leaks client-side.
3. **A LIVE BROWSER DRIVE IS MANDATORY, NOT OPTIONAL.** Per KB #283579, 23 unit tests and a
   F.O.R.G.E. APPROVE both passed on the broken #2463 build; only a real DOM check caught it.
   The same thing happened again on 2026-08-20: a patch landed in the WRONG FUNCTION
   (`email_provision_mailbox` instead of `email_rotate_mailbox_password`), and host greps,
   container greps, an AST parse and a restart all "confirmed" it. Only clicking the button
   exposed it. Drive every one of the five states in a browser and screenshot them.

## Traps for whoever picks this up

- **`def forge_merge_pr(` CONTAINS the substring `merge_pr(`.** A plain `.index()` finds the
  function's own name at offset ~10. Use `\bmerge_pr\(` — `_` is a word character, so the
  boundary holds.
- **Black reformats and ABORTS the first `git commit`** — five times on 2026-08-20. Always
  re-stage and re-check `git log -1` after committing.
- **A merge deploys NOTHING here.** `archie_platform` bind-mounts `platform_v2` → `/app`, so it
  runs the CHECKED-OUT branch. `git checkout main && git pull` is the deploy step. See
  `.claude/rules/deploy-provenance.md` (added #2725).
- **Do not restart `archie_platform` while a PR review is in flight** — it executes inside that
  container and the row is left stuck `in_progress` (KB #270002).

## Out of scope

- Changing any gate's BEHAVIOUR. This is display only; every refusal stays exactly as it is.
- The severity-calibration problem (four non-defect blockers in one day). Rubric work, tracked
  separately — do not let it creep in here.
- #5848 chunked review. Related (five consecutive PRs had their substantive files truncated)
  but a different change.
