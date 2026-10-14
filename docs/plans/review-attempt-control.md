# Review cancellation and resource ownership

Depends on #3844.

## First phase: implemented here

All HTTP, bulk and scheduled review entry points use `review_pr`. A stable
PostgreSQL advisory lock keyed by repository and PR prevents competing processes
from reviewing the same PR, including after an operator resets its status. The
lock remains held while a provider call is running and is released on return or
process death. One pooled connection is occupied for the duration of each review;
this is PR ownership, not a GPU reservation.

Each attempt stores an ID and head identity in existing `pr_reviews.metadata`.
Heartbeat, progress, reset and final-verdict writes are fenced to that attempt
and head. Final publication also checks the current GitHub head. Legacy writers
cannot overwrite an owned attempt. No schema migration is needed.

Skip and Retry revoke publication permission and expire explicitly linked queued
jobs. Running jobs are retained as running until the worker actually finishes;
we do not claim that changing review status terminates inference. A retry cannot
enter while the original owner or an explicitly linked dispatch is still alive.
Cancellation is checked before passes, dispatch and queue polling. Every queued
pass polls its original dispatch ID; structured escalation no longer dispatches
again merely to wait. Raw callbacks never publish an individual pass as a whole
PR verdict. Complete output must pass the live owner's normal integrity and
coverage gates. Bulk review runs serially and pauses on queue/failure.

## Remaining dispatcher-owner work

`department_dispatcher.py` is explicitly protected by the Codex lane. Its owner
must add attempt identity atomically at enqueue and propagate cancellation into
the provider transport. A process crash between enqueue and caller-side linking
can still leave an unlinked job; this PR cannot eliminate that boundary. Existing
direct model calls may continue until their configured timeout. A permanent
background-worker supervisor is also needed to replace daemon web threads and
reconcile reviews after process crashes.

Full GPU reservations must be host/device scoped and held from admission through
model loading, inference and confirmed termination. Require atomic capacity
accounting, boot identity, owner/attempt identity, bounded leases, and cleanup on
success/failure/cancellation. Lease expiry alone must not admit replacement work
while the old workload remains alive. Queue priority and auxiliary-agent slots
are not hardware exclusivity. This PR does not change budgets, model placement,
GPU settings or auxiliary-power configuration.

## Validation and rollout

Tests use mocked DB boundaries and prohibit production HTTP/database access.
They cover duplicate admission, stable cross-process lock keys, cleanup after
exceptions, attempt/head write predicates, cancelled queued jobs, same-ID polling
and rejection of raw/legacy callbacks. PostgreSQL session-lock concurrency still
requires an isolated real-PostgreSQL exercise before production activation; no
local PostgreSQL binaries are installed in this environment.

Run the focused suite from the feature worktree:

```bash
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  platform_v2/tests/test_review_attempts.py \
  platform_v2/tests/test_chunked_review_loop.py \
  platform_v2/tests/test_review_progress_heartbeat.py \
  platform_v2/tests/test_pr_review_async_callback.py
git diff --check
```

Prove the late-callback test fails against a temporary copy restoring the old
unguarded publication. Never mutate the live source for negative controls.

Human merge is required. Do not deploy in the middle of existing reviews:
older imported code does not gain these guards from a merge. The deployment
owner must first drain or explicitly cancel old review processes, then load the
new HTTP and queue-worker implementations together and verify the isolated
ownership/cancel/late-result exercise through those processes. Keep Repair Bay
supervised execution and replacement admission OFF.

Rollback requires quiescing new attempts and resolving their running dispatches
before reverting/reloading both producer and callback consumer. Do not restore
the old unguarded callback while cancelled work can still return. Attempt metadata
can remain inert; no production data deletion or schema rollback is required.
