# Publication gate process exercise — 2026-10-14

Builds on merged #3870 (`0d6ef6a94`). This is a candidate supervisor adapter plus
an isolated process exercise, not deployment of an exclusive host publisher.
Execution and replacement admission remain OFF. No production code imports it.

## What advances in this PR

`PublicationPublisher` takes the supervisor-owned journal, assignment and
independently supplied expected context, plus a trusted transport. It validates
context and persists/commits intent before calling the transport. Stop or write
failure prevents issuance. Once intent is admitted, the operation remains pending
across timeout, process death and supervisor reconstruction, even if the transport
returns success. It never acknowledges its own response. A separate trusted
reconciliation path must record the exact observed operation outcome.

No arbitrary shell commands, runner entry point, production API route, credentials,
service configuration, signing-key changes or broker activation are introduced.
The injected transport is a host integration interface, not authority by itself.
MappingProxyType prevents the transport from accidentally changing expected context;
it is not a security boundary against code in the same supervisor process.

## Executed checks

The new tests use disposable SQLite journals and actual local child processes with
an AF_UNIX socketpair. There is no external network, Docker access, inference,
Git branch/push, real PR or production task/journal mutation.

- The transport reads intent through a separate SQLite connection and proves that
  it committed before invocation. Successful transport responses stay pending.
- Duplicate intent, stop, wrong boot, missing journal and trigger-induced write
  failure issue no transport operation. Lost journals are not recreated.
- A controlled endpoint accepts a simulated PR-create, delays its response, and
  records its successful outcome AFTER the publishing client is terminated and
  reaped. A reconstructed supervisor still observes pending publication; the
  client's death never becomes evidence of absence. Only independent reading of
  the controlled endpoint's assignment/operation/context permits acknowledgement.
- Separate start and stop processes race on the actual SQLite transaction. If
  intent wins it remains pending; if stop wins no request is issued. New intents
  after stop are denied in either case.
- Every started child is joined/reaped in finally cleanup, with bounded terminate
  and kill escalation targeting only the test's Process objects. Sockets and the
  multiprocessing queue are closed. No production PID or service is targeted.
- Removing the commit-before-transport call in an IN-MEMORY COPY makes the actual
  durable-intent assertion fail. The previous fence stop-guard mutation remains.
- Even after a simulated positive reconciliation, settled and recovery_eligible
  remain false. This cannot satisfy the trusted-stop or replacement gate.

Run from the isolated worktree:

```sh
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  --junitxml=/tmp/publication-gate-exercise/results.xml \
  platform_v2/tests/test_publication_publisher.py \
  platform_v2/tests/test_publication_fence.py \
  platform_v2/tests/test_broker_fixes.py \
  platform_v2/tests/test_broker_observers.py \
  platform_v2/tests/test_codex_broker_consumer.py \
  platform_v2/tests/test_codex_worker_supervision.py
```

The fixture uses the Linux fork multiprocessing context, matching this host; it
is not a portability check for platforms without fork. This evidence is reproducible
from checked-in code. It does not claim the production broker ran these cases.

## Required next host step

Host OpenCode must integrate the reviewed adapter into the exclusive publishing
path from `repair-bay-publication-gate-handoff.md`: isolated identity/key/journal,
no credentialed bypass/fallback, durable operation identity, current boot/attempt
binding, independent reconciliation and real start/stop containment. Re-run the
same delayed-response and stop-race cases through that real adapter. Include the
Docker/systemd cases and complete signed receipt/consumer binding before proposing
admission. The prior GitHub-snapshot-only observer remains insufficient.

Codex cannot edit the protected `.sh` runner or infrastructure under AGENTS.md.
This candidate does not relocate either into platform_v2. The full trusted host
exercise and activation remain pending that owner work; fixture results do not
silently close those gates. The single repair pilot remains a proposal only.

## Rollback

This module is unreferenced by production. Revert this three-file PR through review
without touching journals, keys, flags or services. Later host integration needs
its own reviewed rollout and rollback preserving unknown attempts and publication
intent; never discard evidence to unblock a retry.
