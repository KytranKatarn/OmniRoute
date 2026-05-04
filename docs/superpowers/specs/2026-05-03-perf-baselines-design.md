# P.R.O.B.E. Performance Baselines + Deploy Gate — Design Spec

**Date:** 2026-05-03
**Task:** #1755 (Project #239 — P.R.O.B.E. Phase 3)
**Status:** Approved — ready for implementation plan
**Author:** Claude (Opus 4.7)

---

## Context

P.R.O.B.E. (the platform's QA system) already captures `response_time_ms` per test in `qa_test_results`, populated by `qa_e2e_runner.py`. It has 54 active suites and runs them on every Repair Bay post-deploy scan.

What's missing: **historical perspective**. There's no way to know if today's run is faster, slower, or comparable to yesterday's. There's no automated reaction to perf regressions — they sit in raw timings and are noticed only by manual inspection.

This spec defines a **baseline service**, **regression detection**, and a **post-deploy gate** that ties Repair Bay's existing `AutoRollbackManager` to perf regressions, with `paused_for_perf_review` for non-critical regressions.

The work plugs into existing rails:
- `qa_test_results` already has the timing data
- `safe_deployment_protocol` already has rollback infrastructure
- `improvement_proposals` state machine already has `regression` and gets `paused_for_perf_review` added
- `sandbox_queue` only needs a 1-line check before claiming approved proposals

---

## Decisions

Five clarifying decisions made during brainstorming (each chosen by the user):

| # | Decision | Choice |
|---|---|---|
| 1 | Outcome | Visibility + alert + **gate** (block deploys on regression) |
| 2 | Baseline computation | **Hybrid** — auto-baseline (rolling p95 over 30 runs) + per-test `baseline_ms_override` opt-in |
| 3 | Trigger | **Combination** — critical-tagged tests trip on single run; non-critical require 2-of-3 consecutive; threshold 200% over baseline |
| 4 | Gate action | **Combination** — auto-rollback for critical regression; pause-future-deploys for non-critical |
| 5 | Section approvals | All 4 design sections approved as presented |

---

## Architecture

### New tables (single migration)

```sql
-- Rolling baseline per (suite, test). Recomputed nightly.
CREATE TABLE qa_perf_baselines (
    id              SERIAL PRIMARY KEY,
    suite_id        INTEGER NOT NULL REFERENCES qa_test_suites(id),
    test_name       TEXT NOT NULL,
    baseline_p95_ms INTEGER NOT NULL,
    sample_count    INTEGER NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE(suite_id, test_name)
);

-- Per-regression observation. Drives gate decisions + dashboard timeline.
CREATE TABLE qa_perf_regressions (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES qa_test_runs(id),
    suite_id        INTEGER NOT NULL,
    test_name       TEXT NOT NULL,
    baseline_ms     INTEGER NOT NULL,
    observed_ms     INTEGER NOT NULL,
    pct_over        INTEGER NOT NULL,
    is_critical     BOOLEAN NOT NULL,
    action_taken    TEXT,
    proposal_id     INTEGER REFERENCES improvement_proposals(id),
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cleared_at      TIMESTAMPTZ,
    cleared_by      TEXT,
    UNIQUE(run_id, test_name)
);

CREATE INDEX qa_perf_regressions_pending ON qa_perf_regressions(status) WHERE status = 'pending';

-- Operator-marked acceptances — exclude pre-accept history from baseline calc
CREATE TABLE qa_perf_acceptances (
    id          SERIAL PRIMARY KEY,
    suite_id    INTEGER NOT NULL,
    test_name   TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_by TEXT,
    UNIQUE(suite_id, test_name)
);

-- Extend improvement_proposals.status check to include the new state
ALTER TABLE improvement_proposals
    DROP CONSTRAINT IF EXISTS improvement_proposals_status_check;
ALTER TABLE improvement_proposals
    ADD CONSTRAINT improvement_proposals_status_check
    CHECK (status IN ('proposed', 'approved', 'sandboxed', 'deployed', 'regression', 'paused_for_perf_review', 'rejected'));
```

### YAML spec extensions (per-test, opt-in)

```yaml
- name: faith_devotional
  type: page_load
  url: /tools/faith
  timeout_ms: 120000
  critical: true                # NEW — single-run trip + auto-rollback (default false)
  baseline_ms_override: 60000   # NEW — pin a hard limit; bypass auto-baseline (optional)
```

When fields are absent: `critical: false`, no override → auto-baseline path. Existing 54 suites continue working unchanged.

---

## Components & Data Flow

### New service

`platform_v2/services/qa_baseline_service.py` (~250 LOC, pure functions, no Flask import):

| Function | Purpose |
|---|---|
| `compute_baseline(suite_id, test_name) → (p95_ms, sample_count)` | Read qa_test_results history (filtered by qa_perf_acceptances.accepted_at if exists), return p95 and sample count |
| `recompute_all_baselines() → int` | Nightly batch — UPSERT qa_perf_baselines for every test with ≥10 successful runs in the most recent 30 runs window. Returns count updated. |
| `check_regression(suite_id, test_name, observed_ms) → bool` | Reads qa_perf_baselines OR YAML override. Returns True iff observed_ms > 2× baseline AND sample_count ≥ 10. |
| `evaluate_post_deploy(run_id, proposal_id) → 'rollback'\|'pause'\|'flag'\|'none'` | Walks pending regressions for run, applies decide_action per row, UPDATE qa_perf_regressions, returns strongest action |
| `decide_action(is_critical, recent_regressions_count) → action` | Implements 2-of-3 logic; cleared regressions <24h old excluded from window |

### Per-test write flow (modify `qa_e2e_runner.py`)

```
qa_e2e_runner runs test → captures response_time_ms
  → INSERT qa_test_results (existing)
  → qa_baseline_service.check_regression(suite_id, test_name, response_time_ms)
       → wrapped in try/except — must never break a QA run
       → if True → INSERT qa_perf_regressions (status='pending', action_taken=NULL)
                   ON CONFLICT (run_id, test_name) DO NOTHING
```

### Post-deploy gate flow (modify `safe_deployment_protocol.py`)

```
safe_deployment_protocol completes deploy + post-deploy QA scan
  → qa_baseline_service.evaluate_post_deploy(run_id, proposal_id)
       → for each pending regression for this run:
            if is_critical → action='rollback'
            else, look at last 3 runs of (suite_id, test_name):
                count regressions where status != 'cleared' OR cleared_at > NOW() - 24h
                if count ≥ 2 → action='pause'
                else → action='flag'
            UPDATE qa_perf_regressions SET action_taken=..., proposal_id=...
       → return strongest action: 'rollback' > 'pause' > 'flag' > 'none'
  → wrapped in try/except — fail-open (return 'none') + Telegram "perf gate failed open"
  → 'rollback' → AutoRollbackManager.rollback_deployment + proposal.status='regression'
                  if rollback fails → Telegram MANUAL ROLLBACK REQUIRED + commit SHA
  → 'pause'    → proposal.status='paused_for_perf_review'
                  + system_config['deploy_paused_perf']=true
  → 'flag'     → no proposal change, dashboard surfaces the row
  → all paths  → Telegram via existing notify path with action + observed/baseline diff
```

### Pause/dequeue interaction (modify `sandbox_queue.py`)

`sandbox_queue` claim loop adds one check before claiming a new `approved` proposal:
```python
if get_system_config('deploy_paused_perf', default=False):
    return None  # skip claim; alert operator already fired
```

Operator clears via `POST /api/qa/regressions/{id}/clear`. The clear endpoint resets `system_config['deploy_paused_perf']` to `false` only when no other pending regressions remain.

### Nightly recompute (add to `ai_bridge/agent_loop.py`)

```
03:00 UTC daily: recompute_perf_baselines job
  → qa_baseline_service.recompute_all_baselines()
       → for each (suite_id, test_name) with ≥10 successful runs:
            window = last 30 successful runs (filtered by qa_perf_acceptances.accepted_at if present)
            p95_ms = percentile_cont(0.95) over window.response_time_ms
            UPSERT qa_perf_baselines
  → log to autonomy_loop_log
```

### New API endpoints (consumed by Task #1757 dashboard later)

| Endpoint | Purpose |
|---|---|
| `GET /api/qa/baselines` | list current baselines (suite, test, p95, sample_count) |
| `GET /api/qa/regressions?status=pending` | list pending regressions |
| `POST /api/qa/regressions/{id}/clear` | operator marks as false positive — flips pause flag if no other pending |
| `POST /api/qa/regressions/{id}/accept` | operator accepts new normal — inserts qa_perf_acceptances row, immediately recomputes that test's baseline |

### Files touched (implementation plan input)

| File | Change | LOC |
|---|---|---|
| `platform_v2/services/qa_baseline_service.py` | NEW · pure helper | ~250 |
| `platform_v2/services/qa_e2e_runner.py` | hook check_regression after each test | +~10 |
| `platform_v2/tools/repair_bay/services/safe_deployment_protocol.py` | post-deploy evaluate + dispatch action | +~30 |
| `platform_v2/tools/repair_bay/services/sandbox_queue.py` | check pause flag before claim | +~5 |
| `platform_v2/ai_bridge/agent_loop.py` | nightly recompute job | +~15 |
| `platform_v2/services/qa_routes.py` (or new file) | 4 new endpoints | +~80 |
| `platform_v2/database/migrations/NNN_qa_perf_baselines.sql` | NEW · 3 tables + status check extension | ~50 |
| `platform_v2/services/qa_spec_runner.py` | parse `critical` and `baseline_ms_override` from YAML | +~10 |
| `platform_v2/qa_specs/*.yaml` | unchanged this PR (operators add fields opt-in only) | 0 |

---

## Failure Modes & Rollback Safety

Defensive design — perf gate must never break the platform.

| Failure mode | Mitigation |
|---|---|
| Cold-start: test has < 10 historical runs | `check_regression` returns False unconditionally when sample_count < 10. Critical tests get same protection. |
| Baseline service crashes during per-test write | `try/except Exception` → log warning, return False. Test result still persists normally. |
| Baseline service crashes during post-deploy evaluate | `try/except Exception` → log warning, return `'none'` (fail-open). Telegram "perf gate failed open" alert. |
| Auto-rollback fails (backup missing, git conflict) | AutoRollbackManager error caught → Telegram `MANUAL ROLLBACK REQUIRED` with commit SHA. Proposal stays `deployed`. |
| YAML override misconfigured (negative, string, missing) | Spec parser logs warning, falls back to auto-baseline for that test. Spec load doesn't fail. |
| LLM cold-load false positive on critical test | Operator discipline — avoid `critical: true` on LLM-backed routes. 200% threshold is wider than typical cold-load variance. |
| Flapping (oscillates around threshold) | Cleared regressions excluded from 2-of-3 window for **24h** after clear. |
| Race on parallel test runs | `UNIQUE(run_id, test_name)` constraint + `ON CONFLICT DO NOTHING` insert. |
| Stale baseline after intentional perf change | Operator clicks "accept" → `qa_perf_acceptances` row recorded. Nightly recompute filters `WHERE created_at > accepted_at`. |
| Test renamed in YAML | Old baseline orphaned, new test starts fresh. Acceptable; document. |
| Wave of bad deploys piles up regressions | Pause flag is its own rate limiter — no new claims until operator clears. Self-throttling. |
| Telegram down | Alerts not load-bearing. Log warning, continue. Dashboard still shows pending regressions. |
| Deploys outside `safe_deployment_protocol` (manual `forge_pipeline.deploy_via_merge`, hand-pushed PRs) | Skip the perf gate. v1 scope limit. Acceptable since gate's purpose is automated deploy safety. |

### Defensive defaults summary

| Setting | Default | Why |
|---|---|---|
| Trip threshold | **200% over baseline** | Wider than typical LLM cold-load variance (~1.5x) |
| Min samples for baseline | **10 successful runs** | Statistical floor; below this no baseline exists |
| 2-of-3 window | **3 most recent runs** of the same test | Filters single-run noise |
| Cleared-regression cooldown | **24h** | Prevents flap loops |
| `critical: true` default | **`false`** | Opt-in for stronger response |
| `baseline_ms_override` default | **unset** | Auto-baseline used unless explicit |

### Schema migration safety

- All new tables; additive only. `CREATE TABLE IF NOT EXISTS`.
- `improvement_proposals.status` CHECK constraint extended idempotently (`DROP CONSTRAINT IF EXISTS ... ADD CONSTRAINT ...`).
- No down-migration needed — drop tables + revert constraint.

---

## Testing & Rollout

### Test pyramid

| Layer | File | Tests | What they cover |
|---|---|---|---|
| Unit | `tests/test_qa_baseline_service.py` | ~15 | compute_baseline, check_regression, decide_action, evaluate_post_deploy fail-open, all defensive defaults |
| Integration | `tests/test_perf_gate_integration.py` | ~6 | Full deploy flow with critical → rollback called; 2-of-3 non-critical → pause flag set; single non-critical → flag only; pause flag blocks claim; clear/accept endpoints round-trip |
| API | `tests/test_qa_baseline_routes.py` | ~4 | 4 new endpoints with auth |

**Smoke (post-merge, manual)**: `/archie-scan` on a real module → confirm no false positives (every test starts at 0 baseline samples, so check_regression returns False for all — gate must not trip during the warmup period).

### Rollout

Single PR, merge to main directly. No wave plan needed — this is a feature-add, not a wide migration. The gate is **dormant for 30 days** by definition (no test has 10 baseline samples on day 1) — this is a built-in soak period.

After PR merges:
1. Nightly recompute job starts populating qa_perf_baselines
2. After ~10 daily runs per suite, baselines exist and check_regression starts evaluating
3. Operator monitors qa_perf_regressions table for first real trips
4. Operators opt specific tests into `critical: true` once they trust the baseline

### Rollback plan

- Pre-merge regression: fix on branch
- Post-merge: revert PR via `gh pr revert`. Migration tables can be dropped trivially. Status constraint reverted by re-running an inverse `ALTER TABLE`.
- Defensive try/except means worst-case live failure is empty regression detection (no rollback fires inappropriately).

### Success criteria

- All 25+ tests green
- Migration applies cleanly to production DB (idempotent re-runs OK)
- One nightly recompute cycle runs without error within 24h of merge
- One `/archie-scan` runs end-to-end without spurious regression rows on existing 54 suites
- Project #239 progresses 40% → 60% (1 of 3 remaining tasks closed)

---

## Out of Scope (Deliberate)

- **Dashboard UI surface** — Task #1757 owns it. This PR ships the API endpoints; #1757 wires the chart.
- **Telegram message templates** — use existing notify path with simple text. Rich formatting is a follow-up once the dashboard exists.
- **Multi-environment baselines** (staging vs prod separation) — single hub for v1.
- **AI-driven baseline tuning / anomaly classification** — future research.
- **Production user-request perf monitoring (APM)** — different problem; this PR is QA-suite-scoped only.
- **Auto-derivation of `critical: true`** — operator decision; never inferred.
- **Plugging into `forge_pipeline.deploy_via_merge`** (hand-pushed PRs) — operator-driven deploys are operator-aware. v1 scope is `safe_deployment_protocol` path only.

---

## Open Followups (Tasks to Create)

1. Wire baselines + regressions into Task #1757 dashboard (pending tab + trend chart)
2. Build a `qa_perf_changelog` to surface "this test got 3x faster — celebrate" alongside regressions (positive signal)
3. Operator playbook for clearing/accepting regressions

---

## References

- Task: #1755 (Project #239 — P.R.O.B.E. Phase 3)
- Existing infra leveraged: `qa_e2e_runner.py`, `qa_test_results`, `safe_deployment_protocol.py`, `AutoRollbackManager`, `sandbox_queue.py`, `improvement_proposals` state machine
- Sibling task: #1757 (E2E report dashboard) — consumes the API surface this PR ships
- Sibling task: #1756 (AI auto-generated test specs) — independent of this work
- Rules: `.claude/rules/repair-bay.md`
