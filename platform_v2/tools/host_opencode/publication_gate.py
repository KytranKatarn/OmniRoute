"""Host publication gate — exclusive publishing, reconciliation, receipt binding.

Lane scope: ``platform_v2`` only. This is the host-side adapter the Repair Bay
publication-gate handoff asks Host OpenCode to complete. It does **not** provision
the isolated supervisor identity, the systemd unit or the push/PR credentials:
those are host provisioning steps that require owner authorization. Until they
exist, every entry point verifies supervisor provisioning and fails closed.

Constraints from ``docs/plans/repair-bay-publication-gate-handoff.md``:

* Persistent intent is COMMITted before any push/PR-create; no direct-runner
  fallback or alternate publisher may bypass the gate.
* Registration binds to the verified durable broker seal **plus** the current
  attempt/generation, host/boot and exact repo/branch/head — never browser/task
  JSON alone.
* Reconciliation accepts only an outcome produced by a named authority that
  retains the operation/request identity. Arbitrary evidence dicts cannot mint
  trust, and a timeout, empty lookup or unchanged snapshot never proves absence.
* Journal readiness never implies settled. This module never certifies the
  trusted-stop contract and never authorises recovery.

Nothing imports this module in production yet. Broker wiring (a publish message
and the receipt ``publication_binding``) is the post-review step described in
``docs/plans/repair-bay-publication-gate-host-status.md``.
"""

from contextlib import closing, contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat as stat_mod
import uuid
from types import MappingProxyType

from tools.host_opencode.publication_fence import PublicationBlocked, PublicationFence, _canonical

__all__ = [
    "PublicationBlocked",
    "Provisioning",
    "verify_supervisor_provisioning",
    "ValidatedObservation",
    "ObservationAuthority",
    "FileObservationAuthority",
    "PublicationGate",
    "DockerStartStopGate",
    "verify_publication_binding",
    "build_publication_observer",
]

VALID_DISPOSITIONS = frozenset({"confirmed", "confirmed_absent"})


# ---------------------------------------------------------------------------
# 1. Isolated supervisor identity / journal / key directory (fail closed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provisioning:
    supervisor_uid: int
    journal_path: str
    keys_dir: str


def _stat(stat_fn, path):
    try:
        return (stat_fn or os.stat)(path)
    except OSError:
        return None


def verify_supervisor_provisioning(
    journal_path,
    keys_dir,
    *,
    supervisor_uid,
    euid=None,
    stat_fn=None,
):
    """Assert the caller is the isolated supervisor and its storage is private.

    This is the code half of the handoff's "isolated supervisor identity, private
    journal/key directory" requirement. It cannot *create* that identity — no
    separate OS user exists yet — so on an unprovisioned host it always raises and
    the gate refuses to publish. That refusal is the correct fail-closed default.

    Checks, all of which must hold:
    * the effective uid is the supervisor uid (a runner/coder identity is refused);
    * the journal is a regular file owned by the supervisor with no group/other
      write bit, inside a supervisor-owned directory with no group/other write bit;
    * the keys directory is owned by the supervisor and has no group/other access.
    """
    if type(supervisor_uid) is not int or supervisor_uid <= 0:
        raise PublicationBlocked("supervisor_uid_invalid")
    effective = os.geteuid() if euid is None else euid
    if effective != supervisor_uid:
        raise PublicationBlocked("not_supervisor_identity")

    st = _stat(stat_fn, journal_path)
    if st is None or not stat_mod.S_ISREG(st.st_mode):
        raise PublicationBlocked("journal_missing")
    if st.st_uid != supervisor_uid:
        raise PublicationBlocked("journal_not_supervisor_owned")
    if st.st_mode & 0o022:
        raise PublicationBlocked("journal_group_or_world_writable")

    parent = os.path.dirname(os.path.abspath(str(journal_path))) or "."
    pst = _stat(stat_fn, parent)
    if pst is None or not stat_mod.S_ISDIR(pst.st_mode):
        raise PublicationBlocked("journal_dir_missing")
    if pst.st_uid != supervisor_uid:
        raise PublicationBlocked("journal_dir_not_supervisor_owned")
    if pst.st_mode & 0o022:
        raise PublicationBlocked("journal_dir_group_or_world_writable")

    kst = _stat(stat_fn, keys_dir)
    if kst is None or not stat_mod.S_ISDIR(kst.st_mode):
        raise PublicationBlocked("keys_dir_missing")
    if kst.st_uid != supervisor_uid:
        raise PublicationBlocked("keys_dir_not_supervisor_owned")
    if kst.st_mode & 0o077:
        raise PublicationBlocked("keys_dir_not_private")

    return Provisioning(
        supervisor_uid=supervisor_uid,
        journal_path=str(journal_path),
        keys_dir=str(keys_dir),
    )


# ---------------------------------------------------------------------------
# 2. Independently reconciled observations (a dict cannot mint trust)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidatedObservation:
    """One operation outcome produced by a named observation authority.

    Only an :class:`ObservationAuthority` that *retains* the operation/request
    identity may construct one. ``matches`` re-checks every identity field, so a
    correctly-shaped object for a different operation is still refused.
    """

    authority_id: str
    assignment_id: str
    operation_id: str
    operation: str
    request_id: str
    disposition: str
    observed_at: int
    detail: dict = field(default_factory=dict)

    def matches(self, *, authority_id, assignment_id, operation_id, operation, request_id) -> bool:
        return (
            self.authority_id == authority_id
            and self.assignment_id == assignment_id
            and self.operation_id == operation_id
            and self.operation == operation
            and self.request_id == request_id
            and self.disposition in VALID_DISPOSITIONS
            and type(self.observed_at) is int
            and isinstance(self.detail, dict)
        )

    def evidence(self) -> dict:
        return {
            "authority_id": self.authority_id,
            "request_id": self.request_id,
            "observed_at": self.observed_at,
            "disposition": self.disposition,
            "detail": dict(self.detail),
        }


class ObservationAuthority:
    """Base class: an authority that can independently confirm an operation outcome.

    Implementations must be backed by evidence that outlives the publishing
    client — the supervisor's outbound-operation ledger, or a controlled remote
    endpoint addressed by the retained request identity. A GitHub snapshot alone
    is not such an authority: an empty PR list or an unchanged branch cannot
    prove a timed-out create was absent. ``observe`` returns ``None`` (UNKNOWN)
    whenever the authoritative source cannot decide.
    """

    authority_id = ""

    def observe(self, *, assignment_id, operation_id, operation, request_id):
        raise NotImplementedError


class FileObservationAuthority(ObservationAuthority):
    """Authority backed by a JSONL ledger written by the external operation endpoint.

    This is the exercise/host-test implementation of the interface. In production
    the same interface would be satisfied by the supervisor's outbound-operation
    ledger. Records are matched on the full retained identity; a record missing
    any identity field is ignored, and duplicate conflicting records stay UNKNOWN.
    """

    def __init__(self, path, *, authority_id):
        if type(authority_id) is not str or not authority_id:
            raise PublicationBlocked("authority_id_missing")
        self.path = str(path)
        self.authority_id = authority_id

    def observe(self, *, assignment_id, operation_id, operation, request_id):
        if not all(type(v) is str and v for v in (assignment_id, operation_id, operation, request_id)):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            return None
        matches = []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                return None
            if not isinstance(record, dict):
                return None
            if (
                record.get("authority_id") == self.authority_id
                and record.get("assignment_id") == assignment_id
                and record.get("operation_id") == operation_id
                and record.get("operation") == operation
                and record.get("request_id") == request_id
            ):
                matches.append(record)
        if len(matches) != 1:
            return None
        record = matches[0]
        disposition = record.get("disposition")
        observed_at = record.get("observed_at")
        if disposition not in VALID_DISPOSITIONS or type(observed_at) is not int:
            return None
        detail = record.get("detail", {})
        if not isinstance(detail, dict):
            return None
        return ValidatedObservation(
            authority_id=self.authority_id,
            assignment_id=assignment_id,
            operation_id=operation_id,
            operation=operation,
            request_id=request_id,
            disposition=disposition,
            observed_at=observed_at,
            detail=dict(detail),
        )


def record_outcome(
    path, *, authority_id, assignment_id, operation_id, operation, request_id, disposition, observed_at, detail=None
):
    """Endpoint-side helper: append one authoritative outcome record (JSONL).

    Called by the external endpoint that actually accepts the request — never by
    the publishing client. Kept here so the exercise can drive the real interface.
    """
    if disposition not in VALID_DISPOSITIONS:
        raise PublicationBlocked("disposition_invalid")
    record = {
        "authority_id": authority_id,
        "assignment_id": assignment_id,
        "operation_id": operation_id,
        "operation": operation,
        "request_id": request_id,
        "disposition": disposition,
        "observed_at": int(observed_at),
        "detail": dict(detail or {}),
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# 3. The gate: bind registration, publish with durable intent, reconcile
# ---------------------------------------------------------------------------


def _seal_get(seal, key, default=""):
    if isinstance(seal, dict):
        return seal.get(key, default)
    return getattr(seal, key, default)


def _hex40(value):
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


class PublicationGate:
    """Supervisor-only exclusive publisher for one assignment.

    Construction is inert. ``register_from_seal`` binds the gate to the durable
    broker seal; ``publish`` persists intent and COMMITs before the injected
    transport runs; ``reconcile`` records an independently observed outcome.
    """

    def __init__(
        self,
        fence,
        assignment,
        *,
        transport,
        authority,
        provisioning,
        verify_seal=None,
        external_pin=None,
        euid_fn=None,
        stat_fn=None,
    ):
        self.fence = fence
        self.assignment = assignment
        self.transport = transport
        self.authority = authority
        self.provisioning = provisioning
        self.verify_seal = verify_seal
        self.external_pin = tuple(external_pin) if external_pin is not None else None
        self._euid_fn = euid_fn or os.geteuid
        self._stat_fn = stat_fn
        self.expected = None

    # -- provisioning / readiness ------------------------------------------

    def _require_provisioning(self):
        verify_supervisor_provisioning(
            self.provisioning.journal_path,
            self.provisioning.keys_dir,
            supervisor_uid=self.provisioning.supervisor_uid,
            euid=self._euid_fn(),
            stat_fn=self._stat_fn,
        )

    def _require_ready(self):
        self._require_provisioning()
        if self.expected is None:
            raise PublicationBlocked("not_registered")
        if self.external_pin is not None:
            self._verify_external_pin()

    def _verify_external_pin(self):
        seq, digest = self.external_pin
        snap = self.fence.snapshot(self.assignment, expected=self.expected)
        if snap is None:
            raise PublicationBlocked("journal_unavailable")
        if snap["sequence"] != seq or snap["digest"] != digest:
            # A truncated/rewritten journal is internally consistent; only the
            # externally pinned tail can reveal it. Never auto-provision.
            raise PublicationBlocked("tail_rollback_or_missing")

    # -- registration ------------------------------------------------------

    def register_from_seal(self, seal, *, host_id, boot_id, generation, attempt_id=None, pinned_public_key_pem=None):
        """Bind this gate to a verified durable broker seal and boot/attempt.

        The seal fields are authoritative — the caller cannot substitute browser
        or task JSON for repo/branch/head. Every identity field must be present.
        """
        self._require_provisioning()
        if not all(type(v) is str and v for v in (host_id, boot_id, generation)):
            raise PublicationBlocked("binding_incomplete")

        verifier = self.verify_seal
        if verifier is None:
            if not pinned_public_key_pem:
                raise PublicationBlocked("seal_verifier_missing")

            def verifier(candidate):
                from tools.host_opencode.broker import verify_sealed_assignment

                return verify_sealed_assignment(candidate, _seal_get(candidate, "cgroup"), pinned_public_key_pem)

        try:
            verified = verifier(seal)
        except Exception:
            verified = False
        if verified is not True:
            raise PublicationBlocked("seal_invalid")

        if _seal_get(seal, "assignment_id") != self.assignment:
            raise PublicationBlocked("seal_assignment_mismatch")
        repo = _seal_get(seal, "repo")
        branch = _seal_get(seal, "branch")
        head = _seal_get(seal, "commit_sha")
        if not (repo and branch):
            raise PublicationBlocked("seal_publication_unbound")
        if not _hex40(head):
            raise PublicationBlocked("head_invalid")

        attempt = attempt_id or self.assignment
        if type(attempt) is not str or not attempt:
            raise PublicationBlocked("attempt_missing")
        expected = dict(
            repo=repo,
            branch=branch,
            head_sha=head,
            host_id=host_id,
            boot_id=boot_id,
            attempt_id=attempt,
            generation=generation,
        )
        if self.expected is not None and self.expected != expected:
            raise PublicationBlocked("context_conflict")
        self.fence.register(
            self.assignment,
            repo=repo,
            branch=branch,
            head_sha=head,
            host_id=host_id,
            boot_id=boot_id,
            attempt_id=attempt,
            generation=generation,
        )
        self.expected = expected

    # -- exclusive publishing ---------------------------------------------

    def publish(self, operation_id, *, operation, request_id):
        """Persist intent (COMMIT) then issue exactly one external operation.

        The transport's return value is NOT an acknowledgement: a success stays
        pending until an independent authority reports the outcome.
        """
        self._require_ready()
        if type(request_id) is not str or not request_id:
            raise PublicationBlocked("request_identity_missing")
        # durable intent — committed before the transport can act. Stop wins
        # => begin raises and the transport is never called.
        try:
            self.fence.begin(self.assignment, operation_id, operation=operation, request_id=request_id)
        except PublicationBlocked:
            # the fence's own refusal (stop already recorded, duplicate intent)
            raise
        except sqlite3.Error as exc:
            # mode=rw refuses a missing journal; never recreate one on publish.
            raise PublicationBlocked("journal_unavailable") from exc
        except Exception as exc:  # noqa: BLE001 — fail closed; the refusal type is the contract.
            raise PublicationBlocked("journal_intent_failed") from exc
        return self.transport(
            assignment_id=self.assignment,
            operation_id=operation_id,
            operation=operation,
            request_id=request_id,
            context=MappingProxyType(dict(self.expected)),
        )

    def stop(self):
        """Atomically stop new intents before process termination.

        Every failure is a REFUSAL, never an unhandled traceback. The fence's own
        ``PublicationBlocked`` (``assignment_missing``, a conflict) propagates
        unchanged, a journal fault becomes ``journal_unavailable``, and anything
        else — an unexpected exception from the durable journal — becomes
        ``journal_stop_failed``. A caller can therefore catch one exception type
        and still know that "no exception" means the stop is durably recorded.
        """
        self._require_provisioning()
        try:
            self.fence.stop(self.assignment)
        except PublicationBlocked:
            raise
        except sqlite3.Error as exc:
            # mode=rw refuses a missing journal; never recreate one on stop.
            raise PublicationBlocked("journal_unavailable") from exc
        except Exception as exc:  # noqa: BLE001 — fail closed; the refusal type is the contract.
            raise PublicationBlocked("journal_stop_failed") from exc

    def reconcile(self, operation_id, *, operation):
        """Record an outcome only if a named authority independently confirms it.

        Returns the observation on success, or ``None`` (UNKNOWN) when the
        authority cannot decide — a pending intent is preserved, never fabricated.
        """
        self._require_ready()
        snap = self.fence.snapshot(self.assignment, expected=self.expected)
        if snap is None:
            raise PublicationBlocked("journal_unavailable")
        intent = next(
            (
                e["payload"]
                for e in snap["events"]
                if e["kind"] == "intent" and e["payload"].get("operation_id") == operation_id
            ),
            None,
        )
        if intent is None:
            raise PublicationBlocked("intent_missing")
        request_id = intent.get("request_id", "")
        observation = self.authority.observe(
            assignment_id=self.assignment,
            operation_id=operation_id,
            operation=operation,
            request_id=request_id,
        )
        if not isinstance(observation, ValidatedObservation):
            return None
        if not observation.matches(
            authority_id=getattr(self.authority, "authority_id", ""),
            assignment_id=self.assignment,
            operation_id=operation_id,
            operation=operation,
            request_id=request_id,
        ):
            return None
        self.fence.acknowledge(
            self.assignment,
            operation_id,
            disposition=observation.disposition,
            evidence=observation.evidence(),
        )
        return observation

    # -- receipt binding / read-only state ---------------------------------

    def receipt_binding(self):
        """Build the publication binding for the signed durable receipt.

        Carries the fence disposition, sequence, digest and per-operation
        outcomes. It deliberately never reports a trusted-stop/settled verdict.
        """
        self._require_ready()
        snap = self.fence.snapshot(self.assignment, expected=self.expected)
        if snap is None:
            raise PublicationBlocked("journal_unavailable")
        operations = {}
        for event in snap["events"]:
            if event["kind"] == "intent":
                oid = event["payload"]["operation_id"]
                operations[oid] = {
                    "operation_id": oid,
                    "operation": event["payload"]["operation"],
                    "request_id": event["payload"].get("request_id", ""),
                    "disposition": "pending",
                }
            elif event["kind"] == "ack":
                oid = event["payload"]["operation_id"]
                operations[oid]["disposition"] = event["payload"]["disposition"]
        stopped = any(e["kind"] == "stop" for e in snap["events"])
        pending = any(op["disposition"] == "pending" for op in operations.values())
        return {
            "assignment_id": self.assignment,
            "disposition": "publication_settled" if (stopped and not pending) else "unsettled",
            "sequence": snap["sequence"],
            "digest": snap["digest"],
            "operations": [operations[k] for k in sorted(operations)],
        }

    def state(self):
        """Read-only publication state for the broker's completion observer.

        ``settled`` here means publication-settled (the fence), matching the
        existing publication-observer contract. It is not a trusted-stop verdict.
        """
        if self.expected is None:
            return None
        try:
            binding = self.receipt_binding()
        except PublicationBlocked:
            return None
        return {
            "settled": binding["disposition"] == "publication_settled",
            "repo": self.expected["repo"],
            "branch": self.expected["branch"],
            "head_sha": self.expected["head_sha"],
            "binding": binding,
        }

    def inspect(self):
        self._require_ready()
        return self.fence.inspect(self.assignment, expected=self.expected)


def build_publication_observer(gate):
    """Return a broker ``publication_observe(assignment_id)`` closure for a gate.

    Read-only. Unknown/unregistered journals yield ``None`` (fail closed). Wiring
    it into ``_provision_observers`` is the post-review step; see the status doc.
    """

    def _observe(assignment_id):
        if assignment_id != gate.assignment:
            return None
        return gate.state()

    return _observe


# ---------------------------------------------------------------------------
# 4. Receipt binding verification (consumer side, single source of truth)
# ---------------------------------------------------------------------------

_BINDING_KEYS = frozenset({"assignment_id", "disposition", "sequence", "digest", "operations"})
_OPERATION_KEYS = frozenset({"operation_id", "operation", "request_id", "disposition"})
_OPERATION_DISPOSITIONS = frozenset({"confirmed", "confirmed_absent", "pending"})


def _hex64(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def verify_publication_binding(binding):
    """Validate a receipt ``publication_binding``.

    Returns ``("ok", settled_bool)`` when the binding is well formed, or
    ``(error_code, None)`` otherwise. It verifies internal structure only; it can
    never authorize recovery, and a missing binding is not success.
    """
    if not isinstance(binding, dict) or set(binding) != _BINDING_KEYS:
        return "binding_invalid", None
    if type(binding["assignment_id"]) is not str or not binding["assignment_id"]:
        return "binding_invalid", None
    if binding["disposition"] not in ("publication_settled", "unsettled"):
        return "binding_invalid", None
    if type(binding["sequence"]) is not int or binding["sequence"] < 1:
        return "binding_invalid", None
    if not _hex64(binding["digest"]):
        return "binding_invalid", None
    operations = binding["operations"]
    if not isinstance(operations, list):
        return "binding_invalid", None
    for op in operations:
        if not isinstance(op, dict) or set(op) != _OPERATION_KEYS:
            return "binding_invalid", None
        if op["operation"] not in ("push", "pr_create"):
            return "binding_invalid", None
        if op["disposition"] not in _OPERATION_DISPOSITIONS:
            return "binding_invalid", None
        if any(type(op[k]) is not str or not op[k] for k in ("operation_id", "request_id")):
            return "binding_invalid", None
    has_pending = any(op["disposition"] == "pending" for op in operations)
    if binding["disposition"] == "publication_settled" and has_pending:
        return "binding_inconsistent", None
    return "ok", binding["disposition"] == "publication_settled"


# ---------------------------------------------------------------------------
# 5. Separate durable containment gate for container start/stop
# ---------------------------------------------------------------------------


class DockerStartStopGate:
    """Durable start/stop gate for the trusted-stop contract.

    The publication fence covers push/PR-create; this covers the container
    lifecycle the handoff says to gate separately. A start is admitted durably
    before it may run; a stop is refused unless the container was admitted (no
    stopping foreign containers) and is persisted BEFORE the real stop, so a
    crash mid-stop leaves a durable UNKNOWN rather than a false success.
    """

    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def _transaction(self):
        uri = Path(self.path).resolve().as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def provision(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS docker_admissions "
                "(sequence INTEGER PRIMARY KEY, container TEXT NOT NULL, kind TEXT NOT NULL, "
                "token TEXT NOT NULL, previous_digest TEXT NOT NULL, digest TEXT NOT NULL)"
            )

    @staticmethod
    def _events(conn):
        rows = conn.execute(
            "SELECT sequence,container,kind,token,previous_digest,digest FROM docker_admissions ORDER BY sequence"
        ).fetchall()
        previous = ""
        expected_sequence = 1
        result = []
        for sequence, container, kind, token, prior, digest in rows:
            raw = _canonical([sequence, container, kind, token, prior])
            if sequence != expected_sequence or prior != previous or hashlib.sha256(raw.encode()).hexdigest() != digest:
                raise PublicationBlocked("containment_journal_invalid")
            previous = digest
            expected_sequence += 1
            result.append({"container": container, "kind": kind, "token": token, "sequence": sequence})
        return result, expected_sequence, previous

    @staticmethod
    def _append(conn, container, kind, token, sequence, previous):
        digest = hashlib.sha256(_canonical([sequence, container, kind, token, previous]).encode()).hexdigest()
        conn.execute(
            "INSERT INTO docker_admissions VALUES (?,?,?,?,?,?)",
            (sequence, container, kind, token, previous, digest),
        )

    def _state(self, conn, container):
        events, sequence, previous = self._events(conn)
        mine = [e for e in events if e["container"] == container]
        outstanding = None
        for event in mine:
            if event["kind"] == "start":
                outstanding = event["token"]
            elif event["kind"] == "stop" and outstanding == event["token"]:
                outstanding = None
        return mine, outstanding, sequence, previous

    def admit_start(self, container):
        """Durably admit a start; returns a token to execute it. Refuses a live start."""
        if type(container) is not str or not container:
            raise PublicationBlocked("container_invalid")
        with self._transaction() as conn:
            _mine, outstanding, sequence, previous = self._state(conn, container)
            if outstanding is not None:
                raise PublicationBlocked("container_already_started")
            token = uuid.uuid4().hex
            self._append(conn, container, "start", token, sequence, previous)
            return token

    def admit_stop(self, container, token):
        """Durably admit a stop; refuses a foreign/never-admitted container."""
        with self._transaction() as conn:
            _mine, outstanding, sequence, previous = self._state(conn, container)
            if outstanding is None or outstanding != token:
                raise PublicationBlocked("stop_not_admitted")
            self._append(conn, container, "stop", token, sequence, previous)

    def history(self, container):
        try:
            with self._transaction() as conn:
                mine, outstanding, _seq, _prev = self._state(conn, container)
                return {"events": mine, "outstanding_start": outstanding}
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, PublicationBlocked):
            return None

    def guarded_run(self, kind, container, token, executor):
        """Execute a container action only after its durable admission exists.

        ``executor`` is the real Docker call (injected). Without a matching
        admission the executor is never invoked — no bypass path.
        """
        if kind not in ("start", "stop"):
            raise PublicationBlocked("operation_invalid")
        with self._transaction() as conn:
            mine, outstanding, _seq, _prev = self._state(conn, container)
        if kind == "start":
            if outstanding != token:
                raise PublicationBlocked("start_not_admitted")
        else:
            # stop admission is written before execution; it must be present and
            # the start it closes must have existed.
            admissions = [e for e in mine if e["kind"] == "stop" and e["token"] == token]
            if not admissions:
                raise PublicationBlocked("stop_not_admitted")
        return executor(kind=kind, container=container, token=token)
