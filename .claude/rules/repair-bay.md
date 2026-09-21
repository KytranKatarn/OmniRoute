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

## The patient-model escalation — three traps, all fixed 2026-09-16 (#6779)

`_review_is_strong` escalates an over-window chunk to `gemma3:12b` (the "patient" full-window
model). **It had never once actually run that model.** Three stacked defects, each hiding the
next; all three are the same shape as #5194 / #5862 / #2738 — a correct guard, not wired here.

1. **The node pin overrode the model.** `_dispatch_json_review` passed `prefer_model=gemma3:12b`
   *and* `preferred_node=_review_preferred_nodes()` — the 7B cluster (Runabout, Defiant).
   `can_node_run_model('gemma3:12b')` returns **`['Archie Starbase']`** only, so the OVERLAP was
   **empty** and the pin won. The dispatch returned `status='parsed'` having been served by a 7B:
   a SUCCESS carrying the wrong model, reported nowhere.

2. 🔴 **`prefer_model` DOES NOT BIND A MODEL.** Per the dispatcher's own docstring it is
   *"resolved to the first matching agent in the roster; if no agent uses the model, routing falls
   back to capability-based selection"* — silently. The only agents carrying `gemma3:12b` are
   **K.I.N.** (HR) and **V.I.G.I.L.** (Security); neither serves the `code_review` capability
   (V.I.G.I.L.'s `gh:code-review` is an ingested skill NAME, not the capability). So every
   escalation fell back to F.O.R.G.E./`qwen2.5:7b`.
   **Use `model_override` when you mean "run THIS model"** — it binds to the agent actually
   selected (`model = model_override or agent.get("model")`), and the coordinator model-floor
   explicitly yields to a caller-pinned model.

3. **"Strong" meant DESERVING, not REACHABLE — and that is what cost coverage.**
   `_review_is_strong` is the ONE definition shared by the model choice AND the coverage note's
   cap. It answered the wrong question, so the prompt was built at the 18,768 strong cap, served
   by a 7B, slow enough to fail, and the freeform retry re-truncated to 9,000. **That is the whole
   89% / 49% partial-coverage story** — and why coverage-demoted PRs could not be re-reviewed out
   of the demotion. It now returns False when the model is unreachable, so cap, note and model
   cannot disagree.

**New helper `_nodes_for_model(model)`** — online nodes passing BOTH `can_node_run_model`
(capacity) and `node_has_model` (presence; they disagree on real nodes, #5862). 60s TTL,
**fail-CLOSED**: an empty list means "do not ask for this model", which yields an honest weak-cap
review. Fail-open would restore the doomed dispatch.

⚠️ **Verify by the SERVED model, never by the request.** The proof is the dispatcher line:
`Fleet dispatch → Archie Starbase … agent=F.O.R.G.E. model=gemma3:12b`. Before the fix the same
probe read `… USS-245 … model=qwen2.5:7b` while returning `status='parsed'`.

## Gotchas
- `audit_log` from `logging_config` not `rbac`
- `register_*_routes(bp, admin_required)` pattern
- **Tests that cannot fail are worse than no tests.** Prove a new test catches the bug
  it targets: reintroduce the defect in a **copy** of the module
  (`importlib.util.spec_from_file_location`) and confirm the test fails against it —
  never mutate the live file. Done for `test_website_deploy_worker.py` (#5364).
