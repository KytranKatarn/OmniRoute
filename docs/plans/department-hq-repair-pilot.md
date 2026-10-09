# Department HQ planned-repair pilot

Status: prepared checks; not a completed live repair. New planned dispatch remains
OFF. Closed-PR replacement requests record intent only and have no executor.
Do not enable repair admission merely because these regression tests pass.

## Fixture checks (safe to run now)

Run from the candidate worktree, without production conftest:

```bash
PYTHONPATH=platform_v2:. pytest -q --noconftest \
  platform_v2/tests/test_planned_repair_closed.py \
  platform_v2/tests/test_planned_repair_results.py \
  platform_v2/tests/test_planned_repair_completion.py \
  platform_v2/tests/test_planned_repair_verification.py \
  platform_v2/tests/test_planned_repair_receipt.py \
  platform_v2/tests/test_planned_repair_recovery.py \
  platform_v2/tests/test_planned_repair_ui.py
```

| Failure injected in fixtures/copies | Expected result |
| --- | --- |
| PR head differs from reviewed head | No reviewed manifest linkage or merge-ready display |
| Fresh QA missing, failed, or incomplete for an affected module | No completion receipt; proposal stays open |
| Closed PR reopened or merged | Old replacement request invalidated; original PR resumes tracking |
| Closed PR head changes | Old intent invalidated; old-head request rejected |
| Concurrent duplicate replacement requests | One request identity and one write; zero coding tasks |
| Missing GitHub data or foreign task/repo/branch/PR | Visible blocker; preserved prior evidence; no replacement |
| Proposal/task changes during observation | Stale observation cannot overwrite the new attempt |
| Browser asserts worker_stopped or execute | Fields ignored; execution remains disabled |
| Worker stop receipt appears before executor contract exists | Still no execution in this phase |
| Changed deployed artifact, oversized extraction, stale runtime | No completion receipt or reduced count |

Mutation-check the guards in in-memory copies only. Never change live code, review
records, QA outcomes or deployment files merely to make a negative test fail.
The browser fixture captures ready/requested-blocked/reopened screenshots and
checks exact task/PR/head payloads. This is distinct from authenticated live QA.

## Live baseline (read-only, before any repair)

1. Verify merged commits AND the running serving endpoint, not only mounted files.
2. Authenticate through native P.R.O.B.E. using its configured account. Never use
   owner or Claude credentials. Inspect Department HQ Code Health and Repair Bay.
3. Record the fresh audit ID, finding counts, proposal/task/PR identities and
   matching source fingerprint. Proposal #661 (jobs.py LARGE_FILE) is a historical
   candidate, not an assumption that it is still eligible. Reclassify current source
   and scope; do not select protected oversight or SQL assessment work for this pilot.
4. Confirm planned dispatch is OFF, scheduler can reach the authenticated serving
   verifier via its configured mesh URL, and unauthenticated calls are refused.
5. If an actual closed planned PR exists, inspect its observation and blocked
   replacement control. Do not close/reopen a production PR or create artificial
   production tasks to simulate this case; use fixtures above.

## Authorized single-repair pilot (future execution gate)

Only proceed after worker attempt/stop evidence and replacement executor contracts
are implemented, reviewed, merged and active, and the owner authorizes one pilot.
Use a bounded single admission; no unattended backlog enablement for this check.

- Record the original approved unprotected LARGE_FILE finding and current source.
- Request once in UI, repeat the same request, and prove one linked coding task.
- Capture real worker attempt identity, isolated branch, changed-file inventory,
  tests and PR. Capture confirmed terminal/stop evidence before considering retry.
- Require native F.O.R.G.E. approval of the exact current head. A later push needs
  a fresh review; no stale approval can make a repair merge-ready.
- Human merges. Separately authorize deployment; verify serving commit ancestry,
  every artifact and fresh runtime. Never restart during a native review.
- Run fresh passing active P.R.O.B.E. suites for every affected module. Require a
  serving-process completion receipt, original-finding disappearance and fresh
  Code Health re-audit before claiming the issue count fell because of this repair.
- If QA or deployment proof fails, keep the same repair open and expose the blocker.
  Reverification must not create another coding task.
- A closed PR needs fresh server-side closure identity and retained old task/PR/head/
  review/manifest history; a reopened PR invalidates replacement intent. No replacement
  task may start on absent, expired or guessed worker-stop evidence.

## Evidence to retain

Audit/proposal/task/attempt IDs; source fingerprint; PR/reviewed head; full manifest;
merge/deployed SHAs; runtime and deployment timestamps; native QA run IDs and
outcomes; serving completion receipt; post-repair audit and count changes; any
replacement request identity, invalidation reason and preserved attempt history.
No credentials belong in the report. Unknown evidence is a blocker, not success.
