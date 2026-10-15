# Enabled broker assignment must gate runner launch

2026-10-14. Follows merged publication journal #3870 and process exercise #3871.
Execution and replacement admission remain OFF. No host provisioning is included.

## Corrected launch paths

The supervisor previously continued to systemd-run when an enabled broker returned
no assignment/fence; it marked launched before even submitting the broker request.
The worker also silently substituted broker=None when its explicitly enabled
broker socket was absent or its endpoint configuration was invalid.

With this fix, explicit broker enablement preserves the dependency even when the
socket is missing. Invalid endpoint configuration blocks the worker before calling
supervision. Enabled-broker assignment must return a dictionary without an error,
a nonempty bounded string assignment ID and fence token, and no whitespace in
either. Assignment observation must persist with a strict True return and the
attempt must still be owned. Only then may systemd-run be attempted. The launched
flag is set immediately before the command so lost launch responses still trigger
bounded cleanup; a rejected broker request triggers no host-service/Docker command.

Rejected/malformed/unavailable assignments produce the sanitized diagnostic outcome
supervisor_broker_assignment_unconfirmed. Loss of persistence/claim blocks launch
as supervisor_claim_lost. Existing stop_confirmed=False survives the broker-assigned
observation, rather than being dropped by replacing the observation dictionary.

Broker-disabled behavior is unchanged. This does not implement exclusive publishing,
validate all assignment provenance, provision a dedicated issuer or certify the
complete trusted-stop contract. The current assignment request/seal discovery still
needs host integration; a broker rejection is a blocker, never a reason to bypass it.

## Validation

Isolated tests cover missing/malformed assignments, broker errors even alongside a
complete assignment, nonstring/whitespace tokens, transport failure, failed durable
observation, claim cancellation, successful ordering, missing socket and invalid
configuration. Assertions require no launch, barrier, fallback PR or promotion on
the applicable failure paths. A complete assignment positive control retains the
existing diagnostic-only launch flow. Existing cleanup tests cover ambiguous launch
and stop escalation. An in-memory copy removing the broker error check makes the
actual no-command assertion fail; no live module is mutated.

```sh
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  platform_v2/tests/test_publication_publisher.py \
  platform_v2/tests/test_publication_fence.py \
  platform_v2/tests/test_broker_fixes.py \
  platform_v2/tests/test_broker_observers.py \
  platform_v2/tests/test_codex_broker_consumer.py \
  platform_v2/tests/test_codex_worker_supervision.py \
  platform_v2/tests/test_codex_worker_attempts.py
```

No production assignment, inference, Docker operation, service restart, credentials
or database migration is used by the tests. The exact Python worker path is Codex's
recorded scope exception; no protected shell runner or infrastructure is changed.

## Rollout and rollback

Require F.O.R.G.E. exact-head review and human merge. Deploy the merged Python
changes through the owner workflow, preserving unrelated checkout edits; verify
worker behavior on a disposable task harness, not a real coding dispatch. Do not
restart the broker or enable any flags for this fix. Cron workers import new code
on their next invocation after source deployment; long-lived Python callers require
separate process-version verification. A merge alone does not update this checkout.

If rollback is necessary, close admission and preserve diagnostics/attempt artifacts
first, then revert via reviewed PR. Do not restore bypass behavior while broker mode
is enabled. Preserve authoritative journals and signing material. The exclusive
host publisher, real broker exercise and single-pilot proposal remain separate gates
tracked in repair-bay-publication-gate-handoff.md.
