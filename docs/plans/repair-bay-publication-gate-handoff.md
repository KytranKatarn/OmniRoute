# Repair Bay publication gate: candidate and remaining host work

2026-10-14. Execution and replacement admission stay OFF. This is a reviewable
implementation package and pilot proposal, not a completed production trust gate.

## Five requested follow-ups

1. **Code Health sorting deployed.** The two files from merged #3867 were applied
   to the bind-mounted hub with a conflict-checked three-way merge that preserved
   the existing JavaScript edits. The running HTTP service returned the sorting
   helper. Rollback snapshots and hashes: `/tmp/code-health-deploy-1792003575/`.
   Neural Core #3868 also remains deployed with its separate rollback snapshot.
   No restart was issued by Codex; a platform restart occurred during verification.
2. **Publication journal candidate implemented in this PR.** No broker production
   wiring is added. The SQLite event log records immutable assignment context,
   push/PR-create intent, independently supplied acknowledgement, stop intent,
   sequence and previous digest. BEGIN IMMEDIATE serializes intent versus stop;
   successful return follows durable commit with synchronous=FULL. Missing journals
   are never recreated on observation. Duplicate intent cannot authorize a repeat
   network request; lost responses remain pending across restart. Boot/context
   mismatch, corruption and write failure block readiness. `settled` and
   `recovery_eligible` are ALWAYS false, including when journal_ready is true.
   Provisioning is explicit and has only been used on disposable test storage.
3. **Real trusted host exercise remains blocked by provisioning/integration.**
   Fixture tests validate the broker/consumer contract but cannot prove containment
   or control of actual Git/network operations. The running broker reports
   User=kytran, Group=kytran, active/running; a same-user identity alone does not
   establish issuer isolation. No production trusted completion is claimed.
4. **Single pilot proposed below, not activated.** Evidence review must precede
   approval of coding admission. This package does not change the diagnostic-only
   consumer or admission flags.
5. **What The Fact re-audited and recorded.** Product audit 14346: 52 total findings,
   0 critical, findings_open, 835 files/143558 lines. Previous audit 14285 had 56
   total findings and 3 critical. Website audit 14347: 3 total, 0 critical,
   findings_open, 11 files/1668 lines, unchanged from 14291. Counts were independently
   parsed from persisted notes. Audit history was written through log_audit only:
   no repair submission, proposal reconciliation, model inference or product rebuild.
   Source growth means this is a current-tree comparison, not a controlled claim
   that every delta was caused by one PR. Full evidence: `/tmp/wtf-reaudit-2026-10-14.jsonl`.

## Required Host OpenCode implementation

Codex's AGENTS.md forbids edits to the host runner scripts, infrastructure and
service configuration (except the exact Python worker exception). Do not move
those changes into platform_v2 to evade the boundary. Host OpenCode must read its
own lane configuration and obtain any provisioning authorization that is missing.

- Provision an isolated supervisor identity, private journal/key directory and
  fixed authenticated local operations. Ordinary runner/coder identities must not
  write the journal or call acknowledgement/register operations as the supervisor.
  Hash linkage detects accidental changes, not malicious rewriting by its owner;
  it is not a signature, trusted external checkpoint or defense against tail rollback.
- Make the supervisor the exclusive holder of push/PR-create credentials and the
  exclusive caller of real publishing operations. Persist intent and COMMIT before
  issuing each operation; no direct-runner fallback, alternate publisher or restart
  path may bypass the gate. Gate Docker start/stop separately as required by the
  trusted-stop contract. This candidate does not claim to fence Docker starts.
- Bind registration to the verified durable broker seal, current attempt/generation,
  host/boot and exact repository/branch/head, never browser/task JSON alone. Extend
  the candidate context before production if required by the canonical receipt.
- Reconcile acknowledgements independently using retained operation/request identity
  and authoritative outcome. A timeout, empty PR list or unchanged branch snapshot
  cannot prove a timed-out request was absent. Arbitrary evidence dictionaries in
  the candidate API are NOT validated observations and cannot mint trust.
- Stop new intents atomically before process termination; settle all admitted
  operations. A pending intent, unavailable remote, lost journal or uncertain
  outcome remains UNKNOWN. Journal readiness alone never implies settled.
- Wire the trusted adapter to the broker only after exact-head review and a host
  exercise. Broker completion must bind the publication disposition, sequence,
  digest and operation outcomes into the signed durable receipt; then extend the
  consumer to independently verify the complete trusted-stop contract. Its current
  diagnostic result must continue to refuse recovery in this phase.

## Isolated host exercise acceptance matrix

Use a separate socket/journal/key directory, unique temporary namespace and
supervisor process. Disposable sleep processes/container only; no inference, real
coding jobs, pushes, branches, PR creation or production assignment writes.
Network adapters must be local controlled endpoints capable of delayed responses.
Test actual runner-to-supervisor ordering, not only calling journal methods.

| Case | Required evidence |
| --- | --- |
| Intent admitted before stop | Pending after stop, no trusted completion before reconciled acknowledgement |
| Stop wins concurrent race | No network operation issued; later intent denied |
| Delayed push/PR-create success | Durable intent survives timeout and broker restart; request identity reconciled |
| Unknown remote outcome | UNKNOWN; token preserved; no replacement |
| Journal write failure | Network operation never starts; no acknowledgement fabricated |
| Missing journal/tail rollback | UNKNOWN; compare externally pinned sequence/digest, never auto-provision |
| Different attempt/boot/repo/branch/head | Rejected before operation or completion |
| Migrated child/PID reuse/container label mismatch | Rejected using independent lifecycle evidence |
| Positive completion | Exact persisted signed receipt verified against independent assignment context; still no recovery admission |
| Cleanup | Before/after process/container/branch inventory matches; retain logs/journals |

Preserve revision hashes, commands, all expected and actual results, effective
unit permissions, exact receipt and consumer verdict. Redact credentials. An
exercise that omits the real host publication gate is not a pass for this matrix.

## Bounded repair pilot proposal (only after the matrix passes)

Choose ONE fresh approved in-scope finding with a stable fingerprint from the
latest audit. Prefer a small, reversible source-only change with a deterministic
regression; select the exact proposal after freshness/scope review, not an old ID.
Record proposal/task/attempt, source hash, original count, budget and timeout.
Admit one task, demonstrate duplicate requests do not allocate a second one,
require F.O.R.G.E. review of the current head, human merge and separate deployment
verification, then re-audit and verify that exact finding is absent. No backlog
or automatic replacement enablement. A closed PR or failed QA remains blocked
unless the complete independently verified stop contract passes again.

Approval is for this named single pilot only after evidence review; requesting
these five follow-ups does not silently activate supervised execution.

## Validation and rollback

```sh
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  platform_v2/tests/test_publication_fence.py \
  platform_v2/tests/test_broker_fixes.py \
  platform_v2/tests/test_broker_observers.py \
  platform_v2/tests/test_codex_broker_consumer.py \
  platform_v2/tests/test_codex_worker_supervision.py
```

Tests include real SQLite concurrency, persisted restart state, trigger-induced
write failure and an in-memory mutation proving that removing the stop guard
makes the after-stop assertion fail. No production storage or credentials used.

This PR adds an unreferenced candidate module: revert via reviewed PR without
changing production data or services. Do not erase journal evidence to retry.
For later host deployment, snapshot keys/journals with restrictive permissions,
verify restoration on disposable storage, close admission first, preserve unknown
attempt artifacts and require fresh host/boot evidence after rollback. Never reset
or overwrite shared live JavaScript wholesale to roll back sorting; reverse only
that deployed patch after checking for newer owner edits.
