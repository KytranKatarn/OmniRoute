# Review resource optimization

Large complete asset additions can exhaust review windows without improving code
review. On Atlas commit `335d59a26`, deterministic preparation reduces 9,654,108
diff characters to 7,149 code characters, with separate reports for 23 SVGs and
one JSON dataset (approximately 0.8 seconds locally). This is input reduction,
not a measured inference speedup or approval of the assets.

## Implemented scope

- Repair Bay mechanically validates bounded, complete additions of large SVGs and
  data/fixture JSON. Partial edits remain code-review input. Unsupported assets
  are explicitly unvalidated. Reports preserve byte hashes and require human
  visual, licensing, provenance and factual review; asset-bearing reviews cannot
  automatically approve. Blocking code findings remain blocking.
- Shared ModelService reports configured RAM-budget and GPU-headroom shortages
  separately. Large models still require GPU headroom. No model placement,
  loading, eviction, production settings or CPU fallback policy is changed.
- Review passes stop launching after 25 new passes or 1,200 elapsed seconds by
  default. Settings `forge:review_max_passes` (1–100) and
  `forge:review_time_budget_seconds` (60–7,200) bound these limits. An already
  dispatched call finishes or reaches its existing timeout; this is not hard
  cancellation. Remaining files are marked incomplete and require review.
- `forge:review_resume_enabled` defaults OFF. Interrupted passes may reuse
  bounded checkpoints in existing `pr_reviews.metadata` only with matching PR,
  full diff, freshly fetched head/base, reviewer, window, source policy, settings
  and reference context. Changed context, completed reviews and wide reviews
  bypass reuse. Checkpoint persistence failure cannot manufacture approval.
- `forge:review_kb_context_enabled` defaults OFF. It reuses bounded same-repository
  README/AGENTS records already indexed by Consciousness. There is no new crawl,
  embedding, training or direct model call. Historical context is untrusted,
  explicitly freshness-unverified, and cannot serve as diff evidence.

## Department HQ and dispatch follow-up

The shared capacity diagnostics are available to callers now, but this PR does
not change the protected `department_dispatcher.py`. Its owner must propagate
capacity reasons into queue/UI state, use bounded retry/backoff, and implement
host/GPU reservations spanning model loading **and inference**, released on
success, failure, cancellation and expiry. Reservations need host boot identity,
atomic admission and reconciliation after crashes. Existing load locks are not
full-inference reservations. Do not claim system-wide GPU contention is solved
by these review changes. All inference continues through Department HQ.

## Validation and rollout

Run isolated tests from this worktree (the opt-in plugin prevents route bootstrap
and blocks database/network access):

```bash
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  platform_v2/tests/test_review_assets.py \
  platform_v2/tests/test_model_capacity_diagnostics.py \
  platform_v2/tests/test_review_checkpoints.py \
  platform_v2/tests/test_review_context.py \
  platform_v2/tests/test_review_resource_limits.py \
  platform_v2/tests/test_review_coverage.py \
  platform_v2/tests/test_review_coverage_binary_band.py \
  platform_v2/tests/test_chunked_review_loop.py \
  platform_v2/tests/test_review_scope_override.py
git diff --check
```

Verify negative SVG validation in a temporary mutated module copy; never mutate
the live source. Pipeline tests verify interrupted reuse, fresh review after
completion, honest unread-file coverage, and pass/time limits. No live inference
benchmark, service restart, schema migration or production deployment is part
of this PR. The already-running Atlas review is not cancelled or replaced.

After human merge, the deployment owner should verify the loaded implementation
in a newly started review process and compare input sizes, coverage and verdicts
on disposable fixtures before enabling either optional setting. A merge alone
does not update an already-imported module. Keep supervised execution and
replacement admission OFF.

Rollback: disable the two optional settings through the existing authorized
settings workflow, revert this PR and follow the normal deployment procedure
to load the previous implementation. Existing checkpoint metadata may remain
inert; no schema/data rollback is needed. Do not interrupt active production
reviews as an incidental part of rollback.
