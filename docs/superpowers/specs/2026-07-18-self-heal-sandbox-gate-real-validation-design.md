# Self-Heal Sandbox Gate — Real Apply + Validate (HoloDeck-P0 / Repair Phase 2a)

**Date:** 2026-07-18
**Project:** #387 — HoloDeck + Self-Healing Repair + Creative Studios Modularization
**Relates to:** ADR-001 (decision #930, KB #281371), audit blueprint KB #281365, task #4930
**Branch:** `fix/self-heal-sandbox-gate-apply`

## Problem

The self-heal repair pipeline's fixer→sandbox→deploy→verify half has been **theater since ~2026-05-12**. The scan→propose→fix-generate half works (fix-gen contract fixed in PR #2291 + today's #2325/#2326), producing a **unified diff** stored in `improvement_proposals.code_changes`. But the sandbox gate — the step that is supposed to *validate a fix before it can deploy* — cannot apply that diff:

- `_apply_fix_to_sandbox` (`platform_v2/services/proposal_service.py:1316`) `json.loads()`es `code_changes` expecting a list `[{file_path, content}]` of full files. Fix-gen now stores a **unified diff string** → `json.loads` fails → the gate fails closed → **no fix is ever validated**.
- The stored diff uses **basename-only paths** (`--- a/department_dispatcher.py`), from `CodeDiffEngine(filename=os.path.basename(file_path))` at `audit_pipeline.py:1182`. `git apply` cannot locate the real file from a basename.
- The gate **never reverts** the staging worktree after a run, so consecutive runs would accumulate/drift.

Net effect today: `deploy_to_production` writes no code by design (it logs *"automatic code application disabled for safety"*, flips `status='deployed'`, marks the issue fixed — the "33 deployed / 76 fixed" are false-positives that never touched a source file). The gate that should gate real deploys can never validate anything.

**Safety invariant (ADR-001):** *never enable real apply/deploy until the artifact fix (done) AND a real sandbox validation are both live.* This spec builds the **real sandbox validation** half. It does **not** enable real production apply — `deploy_to_production` stays theater.

## Verified current state (live, 2026-07-18)

| Piece | Status |
|---|---|
| `archie_staging` on `:3003` (`0.0.0.0:3003->3000`) + `archie_staging_db` | ✅ up, healthy |
| Staging worktree at `/mnt/archie_sandbox` on branch `_sandbox_preview`; `.git` at the **worktree root** (`platform_v2/` is a subdir, so `/mnt/archie_sandbox/platform_v2/.git` does not exist) | ✅ exists |
| `archie_platform` mounts `/mnt/archie_sandbox` **rw**, has `git`, mounts `docker-compose.staging.yml`, can `docker compose restart archie_staging` | ✅ |
| `archie_staging` mounts `/mnt/archie_sandbox/platform_v2 -> /app` (worktree writes take effect on restart) | ✅ |
| QA suite **#79 = `staging-smoke`** → `http://archie_staging:3000`; `_sandbox_gate` already restarts staging + runs suite #79 (`qa_service.run_suite`) + returns pass/fail | ✅ |
| `_apply_fix_to_sandbox` applies the diff | ❌ broken (JSON-vs-diff mismatch) |
| Diff carries a repo-relative path `git apply` can locate | ❌ basename-only |
| Gate reverts the worktree after a run | ❌ missing |

## Design

Three focused changes. Each unit has one purpose and is independently testable.

### Component 1 — fix-gen emits a git-appliable diff (`platform_v2/services/audit_pipeline.py`)

At the diff-generation site (~L1176-1184), generate the unified diff with a **repo-relative path** instead of a basename, so `git apply` (run from the worktree root `/mnt/archie_sandbox`) can locate the file:

- Resolve the stored `metadata.file_path` to a real repo-relative path via a small **path-alias resolver**: `[APP_CORE]/…` → `platform_v2/…`, `[ai_bridge]/ai_bridge/…` → `ai_bridge/…`, bare `platform_v2/…` / `ai_bridge/…` pass through. If a path cannot be resolved to an existing file under the repo, fix-gen records the failure and does **not** mark the proposal `ready_for_review` (no un-appliable diff enters the queue).
- Pass the resolved relative path to `CodeDiffEngine.generate_diff(filename=…)` (or post-process the `---/+++` headers) so the diff reads `--- a/platform_v2/tools/.../department_dispatcher.py`.
- The resolver is a pure function (`resolve_repo_path(file_path) -> str | None`) — unit-testable in isolation.

### Component 2 — the gate applies + reverts for real (`platform_v2/services/proposal_service.py`)

Rewrite `_apply_fix_to_sandbox(sandbox_path, code_changes)` to apply a **unified diff** via git, fail-closed, drift-safe:

- Worktree root is `/mnt/archie_sandbox` (not `…/platform_v2`). Confirm it is a git worktree; if the mount is absent → fail closed (existing behavior).
- Write the diff to a temp file. Run `git -C /mnt/archie_sandbox apply --check <diff>` first. **If `--check` fails** (the diff does not apply cleanly against *current* staging code — i.e. the source drifted since generation) → return an error → gate fails closed, **no QA runs**. This is the drift-safety guarantee: a stale fix can never false-pass.
- On clean check: `git -C /mnt/archie_sandbox apply <diff>`, return the list of touched files (parsed from the diff) so the caller can restart + validate + revert exactly those.

**Base-sync requirement (correctness).** The proposal's diff is generated against **prod's** current source (`audit_pipeline.py` reads the on-disk file in `archie_platform` = `/mnt/archie_brain/platform_v2/…`). `git apply --check` in the staging worktree only succeeds if staging's touched files **match that base**. If `_sandbox_preview` has drifted from main, a legitimately-fresh fix would fail-closed for the wrong reason. So before apply, the gate must **sync the touched files to the fix's base** — refresh only the touched files in `_sandbox_preview` from prod HEAD / the current prod source, then `git apply`, then revert. Exact mechanism (per-file refresh from prod source vs `reset --hard` of the worktree to prod HEAD) is decided in the plan; the invariant is: apply against the same base the diff was cut from, and leave the worktree clean afterward.

Add **revert-after** to `_sandbox_gate` (~L1424-1450): in a `finally`, `git -C /mnt/archie_sandbox checkout -- <touched files>` (and restart `archie_staging` back to clean) regardless of pass/fail, so the worktree and running staging app return to a clean `_sandbox_preview` state. Revert must run even when QA raises.

Keep everything else in `_sandbox_gate` as-is: restart `archie_staging`, `run_suite(79, …)`, `gate_passed = total > 0 and passed == total`, fail-closed returns.

### Component 3 — archive the 43 legacy blobs (housekeeping)

The 43 current `ready_for_review` proposals are pre-format full-file blobs (whole-file-delete diffs, `import .routes` SyntaxError, model prose) that can never `git apply`. Reversibly archive them (`status='archived'`, `metadata.archived_by='gate_fix_legacy_blob'`, `metadata.archived_at`) so only clean git-appliable diffs flow and the false "43 ready" signal clears. Idempotent; reversible by the `archived_by` tag (mirrors the #4940 pattern).

### Safety boundary (unchanged)

`deploy_to_production` (`proposal_service.py:959`) stays theater — no real source write to production. This slice makes the **sandbox validation** real; the real production-apply lane (`deploy_via_forge` → branch → PR → F.O.R.G.E. review → human `/merge-pr`) is a **later, separately-approved slice**. Nothing in this spec applies code to production.

## Data flow (after this change)

```
ready_for_review proposal (clean unified diff, repo-relative path)
  → request_tiered_deploy_approval → approval gate
  → _sandbox_gate(proposal):
       _apply_fix_to_sandbox: git apply --check (fail-closed on drift) → git apply
       → docker compose restart archie_staging
       → qa_service.run_suite(79)  [staging-smoke @ :3003]
       → finally: git checkout -- <files> + restart staging (revert to clean)
       → {passed, passed_count, total, run_id}
  → deploy_to_production: (UNCHANGED — theater; marks status, writes no prod code)
```

## Testing

- **Unit (TDD):**
  - `resolve_repo_path`: `[APP_CORE]/x` → `platform_v2/x`; `[ai_bridge]/ai_bridge/x` → `ai_bridge/x`; bare paths pass through; nonexistent → `None`.
  - `_apply_fix_to_sandbox`: clean diff applies + returns touched files; drifted diff → `git apply --check` fails → error set, no write; missing worktree → fail closed.
  - Diff-header rewrite produces `a/<repo-rel>` / `b/<repo-rel>`.
- **Integration (live, against `archie_staging`):** generate one fresh fix on a small leaf file → confirm repo-relative diff + `git apply --check` clean → run `_sandbox_gate` → confirm: applies to `/mnt/archie_sandbox`, restarts `:3003`, runs suite #79, returns real pass/fail, then worktree is clean again (`git status --porcelain` empty on `_sandbox_preview`).
- **Regression:** existing fail-closed paths (missing worktree, unparseable diff) still return `passed=False` without running QA.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| `git apply` mutates staging and a crash leaves it dirty → next gate false-passes | Revert in `finally`; `--check` before apply; `_sandbox_preview` is disposable and re-derivable |
| Diff drifted since generation | `git apply --check` fail-closed → gate fails, fix re-generated fresh later |
| Path-alias resolver misses a prefix | Unresolved path → proposal not marked ready (no un-appliable diff enters queue); resolver is unit-tested |
| Accidental prod write | `deploy_to_production` untouched; no code path in this spec writes to `/app` in `archie_platform`/prod |
| Concurrent gate runs share `_sandbox_preview` | Gate is invoked serially by the approval worker; out of scope to parallelize (documented) |

## Rollback

- Code: revert the PR (single branch). No schema change.
- Data: un-archive the 43 via `metadata.archived_by='gate_fix_legacy_blob'`.
- Staging: `git -C /mnt/archie_sandbox checkout -- .` + restart `archie_staging`.

## Out of scope (future, separately-approved)

- Wiring `deploy_via_forge` (the real PR lane) and enabling real production apply.
- The recurring `forge_fix_pr_drain` job / autoheal `engine_build=True` (Phase 2 full).
- Retry-instead-of-park + reset of the ~821 parked proposals (Phase 2).
- HoloDeck module extraction (Phase 1+).
