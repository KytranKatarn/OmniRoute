"""Candidate supervisor-owned publication journal; not provisioned or admission authority.

Only a trusted host adapter may call this API. It must persist intent BEFORE each
push/PR-create, acknowledge independently reconciled outcomes, and prevent bypass.
No network commands, production wiring, key changes or recovery enablement here.
"""

from contextlib import closing, contextmanager
import hashlib
import json
import sqlite3


class PublicationBlocked(RuntimeError):
    """Missing, conflicting or unsettled authoritative publication evidence."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class PublicationFence:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def _transaction(self):
        # mode=rw deliberately refuses missing journals; observation never recreates one.
        from pathlib import Path

        with closing(sqlite3.connect(Path(self.path).resolve().as_uri() + "?mode=rw", uri=True, timeout=5)) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def provision(self):
        """Explicit disposable/provisioning step, never an implicit recovery action."""
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS publication_events "
                "(sequence INTEGER PRIMARY KEY, assignment TEXT NOT NULL, kind TEXT NOT NULL, "
                "payload TEXT NOT NULL, previous_digest TEXT NOT NULL, digest TEXT NOT NULL)"
            )

    @staticmethod
    def _events(conn, assignment):
        rows = conn.execute(
            "SELECT sequence,assignment,kind,payload,previous_digest,digest "
            "FROM publication_events ORDER BY sequence"
        ).fetchall()
        previous = ""
        expected_sequence = 1
        result = []
        for sequence, owner, kind, payload, prior, digest in rows:
            raw = _canonical([sequence, owner, kind, payload, prior])
            if sequence != expected_sequence or prior != previous or hashlib.sha256(raw.encode()).hexdigest() != digest:
                raise PublicationBlocked("journal_continuity_invalid")
            previous = digest
            expected_sequence += 1
            if owner == assignment:
                result.append((kind, json.loads(payload), sequence, digest))
        return result, expected_sequence, previous

    @staticmethod
    def _append(conn, assignment, kind, payload, sequence, previous):
        payload = _canonical(payload)
        digest = hashlib.sha256(_canonical([sequence, assignment, kind, payload, previous]).encode()).hexdigest()
        conn.execute(
            "INSERT INTO publication_events VALUES (?,?,?,?,?,?)",
            (sequence, assignment, kind, payload, previous, digest),
        )

    def register(self, assignment, *, repo, branch, head_sha, host_id, boot_id):
        context = dict(
            repo=repo,
            branch=branch,
            head_sha=head_sha,
            host_id=host_id,
            boot_id=boot_id,
        )
        if not all(type(v) is str and v for v in [assignment, *context.values()]):
            raise PublicationBlocked("identity_missing")
        if len(head_sha) != 40 or any(c not in "0123456789abcdef" for c in head_sha):
            raise PublicationBlocked("head_invalid")
        with self._transaction() as conn:
            events, sequence, previous = self._events(conn, assignment)
            if events:
                if events[0][0] != "register" or events[0][1] != context:
                    raise PublicationBlocked("assignment_conflict")
                return
            self._append(conn, assignment, "register", context, sequence, previous)

    def begin(self, assignment, operation_id, *, operation):
        if operation not in {"push", "pr_create"} or type(operation_id) is not str or not operation_id:
            raise PublicationBlocked("operation_invalid")
        with self._transaction() as conn:
            events, sequence, previous = self._events(conn, assignment)
            if not events or any(e[0] == "stop" for e in events):
                raise PublicationBlocked("assignment_stopping_or_missing")
            if any(e[0] == "intent" and e[1]["operation_id"] == operation_id for e in events):
                # Never grant a second execution capability on a retry, even if identical.
                raise PublicationBlocked("operation_already_registered")
            self._append(
                conn,
                assignment,
                "intent",
                dict(operation_id=operation_id, operation=operation),
                sequence,
                previous,
            )

    def stop(self, assignment):
        with self._transaction() as conn:
            events, sequence, previous = self._events(conn, assignment)
            if not events:
                raise PublicationBlocked("assignment_missing")
            if not any(e[0] == "stop" for e in events):
                self._append(conn, assignment, "stop", {}, sequence, previous)

    def acknowledge(self, assignment, operation_id, *, disposition, evidence):
        # Timeouts are NOT dispositions. Failed/absent must be independently proven.
        if disposition not in {"confirmed", "confirmed_absent"} or type(evidence) is not dict or not evidence:
            raise PublicationBlocked("outcome_unknown")
        payload = dict(operation_id=operation_id, disposition=disposition, evidence=evidence)
        with self._transaction() as conn:
            events, sequence, previous = self._events(conn, assignment)
            if not any(e[0] == "intent" and e[1]["operation_id"] == operation_id for e in events):
                raise PublicationBlocked("intent_missing")
            old = [e[1] for e in events if e[0] == "ack" and e[1]["operation_id"] == operation_id]
            if old:
                if old[0] != payload:
                    raise PublicationBlocked("acknowledgement_conflict")
                return
            self._append(conn, assignment, "ack", payload, sequence, previous)

    def inspect(self, assignment, *, expected):
        """Diagnostic readiness only: cannot certify host gating or trusted completion."""
        try:
            with self._transaction() as conn:
                events, _, _ = self._events(conn, assignment)
                if not events or events[0][0] != "register" or events[0][1] != expected:
                    raise PublicationBlocked("assignment_context_mismatch")
                pending = {e[1]["operation_id"] for e in events if e[0] == "intent"}
                pending -= {e[1]["operation_id"] for e in events if e[0] == "ack"}
                stopped = any(e[0] == "stop" for e in events)
                return dict(
                    assignment_id=assignment,
                    context=expected,
                    pending_ops=sorted(pending),
                    journal_ready=stopped and not pending,
                    sequence=events[-1][2],
                    digest=events[-1][3],
                    settled=False,
                    recovery_eligible=False,
                )
        except (
            OSError,
            sqlite3.Error,
            ValueError,
            TypeError,
            KeyError,
            PublicationBlocked,
        ):
            return None
