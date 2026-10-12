# Broker observer boundaries — 2026-10-12

This corrective change does not authorize activation. Recovery and replacement
admission remain disabled; the receipt consumer remains diagnostic only.

The provisioned host callback accepts (cgroup, assignment_id), checks the cgroup
against the durable assignment, and requires an explicitly injected supervisor
reap ledger callback (assignment_id, pid). The production caller supplies none,
so host completion remains unknown. A disappeared PID is not reaping evidence.

GitHub compare and pull snapshots cannot establish publication quiescence. The
live publication factory therefore returns unknown until an authoritative
supervisor operation fence and reconciliation provider are implemented. No
pending_ops=[] value is synthesized from remote snapshots.

Validation: 133 isolated broker/observer/consumer tests passed. The added handler
positive control uses fixture reaping evidence explicitly; it proves wiring, not
production containment. A disposable parent-owned sleep process was terminated
and wait() confirmed reaping. A uniquely named, network-disabled Alpine sleep
container was created, started, stopped, inspected as exited, and removed.
No production service, inference, GitHub publication, keys or data were changed.
This exercise does not prove cgroup escape prevention or publication fencing.

Remaining host-owner work: durable parent-owned reap ledger; per-attempt service
and cgroup identity/containment; Docker ownership labels from trusted assignment
context; atomic start/stop and publication-operation fences; independent live
reconciliation. Then run an isolated integrated containment/fence exercise before
requesting approval for any production pilot.

Rollback: revert this corrective commit through review. Do not reactivate the
previous fabricated confirmation paths; keep execution/admission disabled during
rollback. No migration, data restoration or service restart is required by this PR.
