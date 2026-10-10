# Repair Bay trusted stop receipts and host containment

Status: prepared for implementation review, 2026-10-10. Builds on merged #3787
(`8dc4e0edc`). Kytran approved per-attempt systemd/cgroup containment and a
dedicated authenticated supervisor receipt path. This document defines the next
implementation phase; it does not activate supervised execution, apply migrations,
provision identities or enable replacement admission.

## Observed constraints

- #3787's `CODEX_WORKER_SUPERVISED` adapter defaults off. Its observations force
  `stop_confirmed=false` and `trusted_receipt=false`; they must remain ineligible.
- The running platform connects as PostgreSQL `archie`, `rolsuper=true` (verified
  through its database helper). Grants/triggers in that same database cannot
  prevent that role from rewriting data. Do not claim an isolated writer merely
  because a table has REVOKE statements.
- `services/internal_auth.py` accepts legacy internal keys with all registered
  scopes when legacy acceptance is enabled. The new issuer endpoint must have no
  legacy-key, coder-lane-key, user-session or generic repair-write fallback.
- The adapter uses a transient **user service**. This coordinates work but does
  not establish a privileged issuer boundary: processes running under the same
  account may access its manager, sockets and files.
- Current task metadata has multiple writers. Neither a receipt embedded there
  nor the mutable association alone can establish trusted assignment provenance.
- The canonical migration procedure targets `database/migrations/`, which is
  outside Codex's current allowed roots. The latest observed number was 492;
  choose a number afresh at implementation. Do not relocate an authoritative
  migration into another directory to evade scope.
- The legacy runner's pruning still compares `codex/<branch>` to basename via
  `find -name`. Host OpenCode must fix and test this separately; supervised mode
  currently skips the pruning path.

## Authority boundary

Implement a dedicated host supervisor/broker with its own service identity and
authoritative append-only journal outside coding-agent, ordinary platform and
runner writable mounts. The broker owns execution assignment, container start,
stop observations and receipt issuance. It is not a thin API that signs a boolean
reported by the worker. The existing poller coordinates requests; it cannot mint
positive receipts.

Use a local authenticated supervisor interface for execution control. Prefer a
Unix socket with peer credentials and strict per-operation authorization, on a
host-owned directory. Distinguish trusted issuer operations from a poller request:
accepting a connection from `kytran` is not enough to trust caller-supplied stop
observations or arbitrary commands. The broker re-observes kernel/Docker state
itself. No generic command execution, arbitrary Docker targeting or wildcard
unit creation is exposed.

The platform consumes signed, versioned receipts from the broker. Use a dedicated
asymmetric signing key held only by that issuer; the platform receives pinned
public verification keys, never the private key. A PostgreSQL projection can aid
UI/querying but is not the authoritative journal. Altered/unsigned projection
rows fail verification; deletion/missing journal availability blocks recovery.
This avoids treating grants in the platform's superuser database as a security
boundary. Signing dependency/provisioning must be explicitly reviewed; no new
crypto dependency is assumed from the current requirements file.

This boundary defends against browser requests, generic task/metadata writes,
ordinary internal callers and accidental stale callbacks. A compromised host
administrator, Docker administrator or broker is outside this boundary; do not
claim containment against actors that can change the host or signing keys.

## Assignment and startup protocol

1. Poller submits task/proposal/attempt identity and expected source/PR association
   to the broker. The broker validates the server-owned planned-work association
   and current claim, then records an immutable assignment with its own ID and
   generation. Generic metadata cannot substitute a different assignment later.
2. Broker accepts only the fixed reviewed runner path, bounded prompt data and
   validated identity. It records host boot ID, runner version, assigned scope,
   expected labels, worktree and intended container name before execution.
3. Broker creates a transient systemd **service**, with a distinct cgroup for
   runner/gates/publishing, while the supervisor remains outside that cgroup.
   Required effective properties include control-group termination, no restart,
   bounded runtime and bounded stop escalation. Do not use `--scope`.
4. Host OpenCode must demonstrate that runner processes cannot migrate out of the
   assigned cgroup, access its manager/control channel, or obtain issuer secrets.
   Configure the supported host isolation rather than assuming a user unit or
   `setsid` provides that guarantee. No wildcard sudo/polkit grants.
5. Runner creates the labeled container without starting it. Broker resolves the
   full container ID, independently checks assignment/task/attempt/host/boot labels,
   expected sandbox configuration and restart-disabled state, then durably records
   that identity. Reject symlinks, stale coordination files and mismatched IDs.
6. Only the broker can release startup. Define an atomic start-versus-stop state
   transition; a last-moment file check is not the authority. A delayed Docker
   start request must not be able to restart execution after receipt issuance.
7. Preserve current sandbox UID/mount/resource/credential restrictions. Do not add
   the supervisor socket, journal or signing key to a coding container.

For create/start races, the lifecycle journal must record request and observed
outcome separately. Lost responses are UNKNOWN. Recover by the immutable full ID
and exact labels; never delete or stop a container based on a name alone.

## Stop and sealing protocol

1. Atomically transition the broker assignment to stopping. Refuse new starts,
   fallback publishing, callbacks that initiate work and repeat activation.
2. Stop the owned host service, then verify its entire cgroup and descendants are
   quiescent. A supervisor-side reaper/verified systemd lifecycle must account for
   child exits; an empty `cgroup.procs` at one instant alone is insufficient.
3. Independently stop the exact validated Docker container. On a bounded graceful
   timeout, revalidate identity before kill escalation. Verify terminal container
   state and no restart path. Daemon unavailability or ambiguous removal is UNKNOWN.
4. Settle any in-flight Docker start before sealing. Keep the stopped container
   inspectable until receipt persistence; removal is a later recorded operation.
5. Reconcile host Git push and PR create/fallback outcomes after no local process
   can issue additional requests. Preserve exact repository, branch and all PR/head
   observations. A timed-out GitHub create can succeed remotely; a single empty
   lookup or elapsed grace period cannot establish that it failed.
6. Seal assignment in the broker journal, preventing all future starts or issue of
   a new runner capability for that attempt. Append and fsync the terminal receipt
   transaction before returning it. Unknown execution/publication state yields an
   unknown receipt, never a positive stop decision.
7. Only then clean up container, credential copies and coordination files, with
   separate cleanup observations. Preserve bounded forensic evidence and unknown
   worktrees. Retention must never remove an active/unknown attempt's artifacts.

When the supervisor crashes or the host reboots, inventory registered assignments
without claiming new coding work. A changed boot ID, lease expiry, missing PID,
absent unit or `blocked` status cannot stand in for the protocol above.

## Receipt wire contract, version 1

The signed envelope contains exact canonical payload bytes, key ID, algorithm,
signature and payload digest. Pin the permitted algorithm; never let input choose
an arbitrary verification method. Reject duplicate JSON keys, unknown version,
noncanonical encoding, oversized payloads, malformed types and unknown/revoked
keys. Define canonicalization before signer/verifier implementation; fixtures must
use identical bytes across both sides. No floats or implicit truthy coercions.

Required payload groups:

| Group | Required fields |
| --- | --- |
| Identity | receipt ID, protocol version, assignment ID/generation, task ID, proposal ID, attempt UUID |
| Issuer | registered issuer ID, host ID, boot ID, effective supervisor/runner version |
| Host execution | exact service/cgroup identity, terminal observation and reaping evidence |
| Docker execution | full container ID, expected ownership labels, observed terminal state, restart/start reconciliation |
| Publication | reconciliation disposition, exact repo/branch and retained PR/head identities, outstanding-operation status |
| Lifecycle | stop reason, assignment sealed, observation timestamps, journal sequence and previous digest |
| Outcome | explicit execution_stopped/publication_settled/assignment_sealed/cleanup_complete values; bounded diagnostic codes |

Use explicit `confirmed`, `unknown`, `not_applicable` states rather than defaulting
missing fields to true. No caller-controlled `stop_confirmed` is authoritative.
Positive eligibility requires confirmed execution stop, settled publication and
sealed assignment. `not_applicable` needs a protocol-defined proof, such as an
assignment that never obtained a startup capability. Cleanup does not erase
evidence; a cleanup failure stays visible even when execution is proven quiescent.

The consumer validates signature, issuer/key registry, exact assignment identity
and generation, required observations, allowed state transitions and journal
continuity against the broker. It also rechecks the current task/proposal linkage.
It must not accept a historical receipt transplanted onto another attempt, even
if the signature is valid. The later executor independently rechecks fresh GitHub,
scope/governance/admission and expected source/head before allocating replacement.

## Authoritative persistence contract

Broker journal has assignments, lifecycle events and terminal receipts. Store
assignment snapshot/hash, ordered events and exact signed envelope bytes. Use
atomic transactions with unique assignment/generation and terminal receipt keys.
Identical retries return the original result. Conflicting payload under an
existing identity is refused and logged; it never overwrites the old record.

Normal broker API/DB roles have no event/receipt update/delete operation. Separate
maintenance authority handles explicit retention/rotation under an audited policy.
An app-local PostgreSQL cache, if added, cannot be the authority. Any schema/role
provisioning must identify the actual target datastore and prove grants with real
identities. Do not use the production `archie` superuser to "test" append denial.

## Codex implementation package

- Pure strict envelope/payload validator and fixtures; no positive decisions from
  unsigned #3787 metadata, user-supplied JSON or a generic internal token.
- Broker client with bounded timeouts and fail-closed reads, using the provisioned
  trusted verification registry; no secrets in task/prompt/log output.
- Receipt projection and progress UI/status, preserving unknown blockers; browser
  can request intent but cannot assert issuance or stopped state.
- Worker integration with broker assignment/stop protocol and stale-write tests.
- Replacement remains hard-disabled in this phase.

## Host OpenCode implementation package

- Verify lane permissions, then implement/provision the narrowly scoped supervisor,
  its service identity, journal, signing-key isolation and authenticated local API.
- Implement runner/service/container ownership and atomic start/stop sealing;
  adapt the existing `.sh` runner protocol without granting the runner issuer rights.
- Supply effective unit properties and executable containment evidence; no blanket
  privileges or infrastructure edits without the required owner authorization.
- Implement authoritative journal schema/roles and public-key distribution. Any
  canonical platform migrations remain owner/authorized-lane work, not Codex scope.
- Fix the remaining legacy pruning basename mismatch with a nested-worktree test.

Copyable task brief: implement the Host OpenCode package above from this reviewed
contract. Keep existing production execution unchanged; prepare isolated PRs and
synthetic evidence, report any additional permission/provisioning requirements,
and coordinate the broker interface with Codex before activation. Never launch
real coding work, bulk backfill stop receipts or enable replacement as part of it.

## Verification and rollout gates

First run deterministic fixtures with fake Docker/systemd/broker boundaries. Prove
tests reject injected unsafe mutations in copies. Then separately authorize an
isolated host exercise with disposable sleep processes/containers, no inference,
no real PR creation and no production task/proposal mutation.

Required failures: detached/TERM-ignoring child, live daemon-owned container after
client death, pending Docker start after stop request, label/ID mismatch, PID reuse,
supervisor crash at each journal boundary, reboot, DB/journal outage, duplicate or
conflicting receipt, signature/key/version tampering, forged task metadata, legacy
internal token, stale assignment, missing cgroup, ambiguous remote PR create,
worktree retention and a still-active unrelated native review.

Each case either proves all required terminal observations or remains UNKNOWN.
Never terminate production services/native reviews to demonstrate the failure.

Review/merge broker and consumer PRs; verify provisioning and running versions;
activate only the bounded evidence path with owner approval. Prove ordinary
platform/coder/browser identities cannot issue receipts. Keep supervised admission
and replacement execution off until the containment/authentication checks pass.
The replacement executor and one approved Department HQ pilot follow separately.
