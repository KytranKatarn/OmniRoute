# Repair Bay closure gates — 2026-10-13

Execution and replacement admission remain off. This is the engineering closure
checklist, not permission to deploy or activate. The diagnostic consumer always
returns recovery_eligible=false and stop_confirmed=false.

## Completion correctness

The corrective branch makes one atomic transaction cover the stop journal entry,
trusted token consumption and exact signed completion. A receipt-write failure
rolls all three back and permits retry. Simultaneous trusted completions have one
winner. Observers run once per request. Assignment retries retain the same token;
a failed token write returns no assignment. SQLite handles close on all paths.
The consumer round-trip fixture now follows the fence-token protocol.

Run from an isolated worktree:

```sh
PYTHONPATH=platform_v2 python3 -m pytest --noconftest -p no:cacheprovider -q \
  platform_v2/tests/test_broker_fixes.py \
  platform_v2/tests/test_broker_observers.py \
  platform_v2/tests/test_codex_broker_consumer.py
```

Tests use temporary SQLite/keys, real simultaneous handler calls and SQL triggers
for actual write failures. A temporary-copy mutation commits the token early and
must make the rollback test fail. No production database or inference is used.
The former skipped "integrated host exercise" did not create host resources and
could never satisfy provisioning. It is replaced by an explicit negative test:
unprovisioned live observers cannot issue trusted completion or consume a token.
This replacement does NOT complete the host exercise gate.

## Host OpenCode/operator work still required

1. Own each runner's process creation and wait/reaping records; bind PID identity
   to host boot/process start time, not a reusable PID number alone.
2. Provision dedicated issuer identity/key/journal isolation. Same-user access to
   systemd, Docker and private signing keys is not an isolation boundary.
3. Use a per-attempt systemd service/cgroup, independently verify effective
   properties and prohibit runner migration/control access. Unit name/cgroup
   strings supplied by callers are insufficient.
4. Gate real Docker create/start, stop and restart with the broker state machine.
   Bind full container ID and attempt/task/host/boot labels before releasing start.
   Current token consumption only arbitrates completion; it does not fence starts.
5. Gate actual push and PR-create operations, including pending operation intent,
   acknowledgement, restart reconciliation and rejection after stop intent.
   A GitHub snapshot cannot prove that no publication operation is in flight.
6. Extend the signed envelope/journal to the canonical trusted-stop contract:
   proposal/attempt/generation, issuer/host/boot, lifecycle outcome, exact publication
   disposition and durable sequence/digest. Independently bind consumer context.
7. Run the real isolated host exercise after those adapters exist: unique disposable
   sleep processes/containers and branch namespace, no inference or real PRs.
   Verify start/stop races, escaped-child detection, parent-owned reap evidence,
   label mismatch, unavailable observers, broker restart, write failure/retry and
   no post-stop publication. Preserve exact revision/commands/results and cleanup.
8. Obtain review, human merge and separate deployment authorization; verify code
   through the running broker process. Only then propose a single approved pilot.

Codex cannot edit scripts/agents/run-codex-task.sh or other protected runner/host
infrastructure paths under the current config/agents/codex.yaml. Only the exact
codex-delegation-worker.py exception is allowed. Do not widen that scope or move
infrastructure changes into platform_v2 to evade it. These host gates require the
host owner workflow, and cannot be certified by unit tests in this PR.

## Rollback

Revert the corrective commit via a reviewed PR while leaving execution/admission
off. There is no schema migration or production data change in this correction.
Do not delete authoritative journal evidence, tokens or completions to permit a
retry. Preserve journals/keys before any later deployment; validate restoration
on disposable storage. Require fresh host/boot-bound evidence after rollback.
