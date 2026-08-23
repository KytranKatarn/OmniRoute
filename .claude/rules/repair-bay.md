---
globs: ["platform_v2/tools/repair_bay/**", "platform_v2/services/scan_service.py", "platform_v2/services/proposal_service.py", "platform_v2/services/scan_pipeline.py"]
---

# Repair Bay Rules

## Structure
- Route: `/tools/repair-bay` | 9 tabs: Dashboard (Reviews), PR Review, Repairs, Diagnose, Test Bay, Ship, P.R.O.B.E. (QA), Pushes, Module Review + ENGINEERING station panel
- Service layer: `scan_service.py`, `proposal_service.py`, `sandbox_service.py` (business logic)
- Route files are thin HTTP handlers calling service functions
- Category: `AI_COMMAND` (not DEVELOPMENT_TOOLS — deleted)
- `SandboxManager` class at `platform_v2/tools/repair_bay/services/sandbox_manager.py` (top-level `platform_v2/sandbox_manager.py` does NOT exist — corrected 2026-05-29)

## Self-Evolution Pipeline
- Scan -> Proposal -> Sandbox -> Deploy (deploy stays manual)
- Critical/high -> individual proposals, medium -> weekly batch (Sunday 02:00)
- Proactive scan: `_run_proactive_scan()` in agent_loop (every 6h)
- Deduplication: `_has_open_proposal()` checks file_path + issue_type

## Review workflow — operational facts (measured 2026-07-28)

- **A review takes 10–15 minutes.** One `mistral:7b` pass measured at **494 s**, and
  the integrity gates run several passes. Kick `review_pr` with `run_in_background`
  and poll; do not sit in a 90 s foreground loop and conclude it is stuck.
- **`review_status='in_progress'` while YOUR OWN re-review is in flight is just your
  run**, not a stalled review. `review_pr` calls `mark_review_started` immediately, so
  a concurrent `get_review` shows `in_progress` alongside the PREVIOUS run's stored
  summary. Reading that as "stuck" wasted two diagnostic cycles. Check whether a
  review process is alive (`ps` in the container) before re-driving.
- **Never restart `archie_platform` while a review is running** — `review_pr` executes
  inside the container via `docker exec`; a restart kills it mid-dispatch and leaves
  the row stuck `in_progress` for real (the KB #270002 trap).
- **A REQUEST CHANGES often quotes an EXCERPT.** On PR #2491 F.O.R.G.E. flagged a
  Telegram call "on the dispatch path" from `+` lines that showed the inner `try:` but
  not the `daemon` thread wrapping it. Fetch the surrounding function before accepting
  **or** rejecting the finding, disprove it IN WRITING on the PR, then re-review — it
  independently flipped to APPROVE with no code change. See KB #285011.

## Cross-repo review (F.O.R.G.E. beyond archie-platform)

Two capabilities that are easy to conflate — they have different tokens:

| | Mechanism | Scope |
|---|---|---|
| **Review** | `review_pr(pr_number, repo="owner/name")` | `FORGE_REVIEW_TOKEN` = read PAT, **all repos** |
| **Merge** | `merge_pr(..., repo=)` | write token has **push+admin on archie-platform, archie-code, KSO and creed**; the 4 watch repos + KBS return 404 → human merge. ⚠️ NOT platform-scoped — corrected 2026-08-23 (#5981) |

- `GITHUB_REPOS` (the auto-poll list) = archie-platform + the 4 watch repos + **kytran-system-operations** (added since #5369). ⚠️ **archie-code is NOT in it** — the repo holding the TUI and engine is never auto-polled, despite the write token having admin there; it is reviewed only when a caller passes `repo=` explicitly. **A repo
  not in that list is never polled**, so its PRs never reach Repair Bay, never get a
  stored verdict, and `_automerge_governance_ok` then fails closed — correctly, but it
  means nothing can ever merge there.
- **KSO (`kytran-system-operations`) is NOT in the list** and had zero review
  automation until PR #8 was reviewed by passing `repo=` explicitly. Task **#5369**
  tracks adding it; the same blind spot likely covers archie-code, KBS, creed and the
  media_hub standalone — if a repo ships a live product and is absent from
  `GITHUB_REPOS`, its PRs are unreviewed by construction.
- Adding a repo to `GITHUB_REPOS` grants **review only** — no new write authority.
  Whether F.O.R.G.E. may ever *merge* on a product repo is an authority decision for
  Kytran (decision #953: safety properties are universal, authority limits are
  per-actor), not a config tweak.

## Gotchas
- `audit_log` from `logging_config` not `rbac`
- `register_*_routes(bp, admin_required)` pattern
- **Tests that cannot fail are worse than no tests.** Prove a new test catches the bug
  it targets: reintroduce the defect in a **copy** of the module
  (`importlib.util.spec_from_file_location`) and confirm the test fails against it —
  never mutate the live file. Done for `test_website_deploy_worker.py` (#5364).
