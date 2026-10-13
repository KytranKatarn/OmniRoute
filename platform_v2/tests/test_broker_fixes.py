"""
Isolated regression tests for the Host OpenCode broker.

Covers the Codex-verified failures through the actual request handlers
(not only unit helpers):
  1. untrusted peers (mocked UID 99999 rejected even when broker euid trusted)
  2. forged receipts (tampered payload or wrong key rejected)
  3. missing assignments (completion for nonexistent assignment rejected)
  4. caller-supplied stop claims (running / not stopped rejected)
  5. journal persist failures (assign/complete fail when append returns False)
  6. fabricated seals (journal entry with signature "forged" rejected)
  7. unbound observation targets (caller container mismatch rejected;
     observers receive sealed assignment identity)
  8. usable receipt envelope (complete persists/returns exact signed bytes)

Plus positive controls proving valid terminal evidence verifies.

Isolation: tmp keys/journal dirs only; no /var/lib writes; no network;
no platform DB. Run with: python3 platform_v2/tests/test_broker_fixes.py
"""

import json
import os
import struct as _struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "host_opencode"))

import broker as B


def _make_keys(tmpdir):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    keys_dir = Path(tmpdir) / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        priv.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    (keys_dir / "broker_private.key").write_text(priv_pem)
    os.chmod(keys_dir / "broker_private.key", 0o600)
    (keys_dir / "broker_public.key").write_text(pub_pem)
    os.chmod(keys_dir / "broker_public.key", 0o644)
    return keys_dir, priv_pem, pub_pem


def _other_public_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return (
        other.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


class _FakeConn:
    """Fake Unix socket: scripted inbound bytes, captured outbound, peer UID."""

    def __init__(self, inbound: bytes, uid=None, fail_cred=False):
        self._inbound = bytes(inbound)
        self._uid = uid
        self._fail_cred = fail_cred
        self.sent = b""
        self.closed = False

    def settimeout(self, _timeout):
        return None

    def recv(self, n):
        if not self._inbound:
            return b""
        chunk, self._inbound = self._inbound[:n], self._inbound[n:]
        return chunk

    def sendall(self, data):
        self.sent += bytes(data)

    def close(self):
        self.closed = True

    def fileno(self):
        return -1

    def getsockopt(self, _level, _opt, buflen):
        if self._fail_cred or self._uid is None:
            raise OSError("no peercred")
        assert buflen == 12
        return _struct.pack("iii", 1234, int(self._uid), 100)


FULL_W = "abcdef0123456789" * 4  # 64 hex chars: pinned container ID


def _terminal_observers(
    container,
    assignment="a-handler-001",
    cgroup="host-opencode-runner",
    full_id=None,
    repo="o/r",
    branch="main",
):
    calls = {}
    bound_full = full_id if full_id is not None else FULL_W

    def docker_observe(cid, aid):
        calls["docker"] = (cid, aid)
        assert cid == container, f"observer must receive sealed container, got {cid!r}"
        assert aid == assignment, f"observer must receive assignment identity, got {aid!r}"
        return {
            "id": cid,
            "full_id": bound_full,
            "state": "stopped",
            "restart_disabled": True,
            "labels_match": True,
        }

    def host_observe(cg, aid):
        calls["host"] = (cg, aid)
        assert cg == cgroup, f"observer must receive sealed cgroup, got {cg!r}"
        assert aid == assignment
        return {"cgroup_empty": True, "service": "stopped", "reaped": True}

    def publication_observe(aid):
        calls["pub"] = aid
        assert aid == assignment
        return {"settled": True, "repo": repo, "branch": branch}

    return docker_observe, host_observe, publication_observe, calls


_ASSIGNMENT = {
    "assignment_id": "a-handler-001",
    "task_id": "t-handler-001",
    "runner_id": "",
    "scope": "test",
    "cgroup": "host-opencode-runner",
    "container_name": "c-handler-001",
    "broker_id": "broker-test",
    "created_at": "2026-01-01T00:00:00Z",
    "container_id": FULL_W,
    "runner_pids": [4242],
    "repo": "o/r",
    "branch": "main",
    "commit_sha": "a" * 40,
}


class BrokerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "journal.db")
        self.keys_dir, self.priv_pem, self.pub_pem = _make_keys(self.tmp.name)
        self.assertTrue(B.journal_init(self.db))

    def _handle(self, message, peer_uid=1000, observers=None):
        conn = _FakeConn(json.dumps(message).encode(), uid=peer_uid)
        kwargs = dict(
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=peer_uid,
        )
        if observers is not None:
            docker, host, pub = observers
            kwargs.update(docker_observe=docker, host_observe=host, publication_observe=pub)
        B.handle_broker_connection(conn, self.priv_pem, B.journal_append, **kwargs)
        return json.loads(conn.sent.decode())

    def _assign(self, peer_uid=1000):
        resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=peer_uid,
        )
        self.assertIn("assignment", resp)
        self.assertIsNotNone(resp["assignment"], f"assign failed: {resp}")
        return resp["assignment"]

    def _get_fence_token(self, assignment_id="a-handler-001", peer_uid=1000):
        """Get fence token for an assignment by assigning and extracting token."""
        resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=peer_uid,
        )
        self.assertIn("assignment", resp)
        assignment = resp["assignment"]
        self.assertIsNotNone(assignment, f"assign failed: {resp}")
        self.assertIn("fence_token", assignment, "assignment must include fence_token")
        return assignment["fence_token"]

    def test_provisioned_host_requires_owned_reaping(self):
        from unittest.mock import patch
        from tools.host_opencode import observers

        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp)
        fence_token = assign_resp["assignment"]["fence_token"]
        aid = _ASSIGNMENT["assignment_id"]
        cg = _ASSIGNMENT["cgroup"]
        with patch.object(observers, "systemd_state_live", return_value="inactive"), patch.object(
            observers, "cgroup_pids_live", return_value=[]
        ):
            _, host, _ = B._provision_observers(self.db)
            self.assertIsNone(host(cg, aid))
            calls = []

            def reaped(assignment_id, pid):
                calls.append((assignment_id, pid))
                return True

            _, host, _ = B._provision_observers(self.db, reap_observe=reaped)
            self.assertIsNone(host("other-cgroup", aid))
            self.assertEqual(calls, [])
            self.assertEqual(host(cg, aid), {"cgroup_empty": True, "service": "stopped", "reaped": True})
            self.assertEqual(calls, [(aid, 4242)])
            docker, _, pub, _ = _terminal_observers(_ASSIGNMENT["container_name"])
            response = self._handle(
                {
                    "type": "complete_assignment",
                    "assignment_id": aid,
                    "details": {
                        "container_id": _ASSIGNMENT["container_name"],
                        "docker_state": "stopped",
                        "stop_observation": "stopped",
                        "fence_token": fence_token,
                    },
                },
                observers=(docker, host, pub),
            )
            self.assertTrue(response.get("trusted"), response)

    def test_untrusted_peer_rejected(self):
        """UID 99999 is rejected even though the broker itself runs trusted."""
        self.assertFalse(
            B.validate_peer_identity(_FakeConn(b"", uid=99999), {1000}),
            "untrusted peer UID 99999 must be rejected",
        )
        self.assertTrue(
            B.validate_peer_identity(_FakeConn(b"", uid=1000), {1000}),
            "trusted peer UID must be accepted",
        )
        self.assertFalse(
            B.validate_peer_identity(_FakeConn(b"", uid=None, fail_cred=True), {1000}),
            "unreadable peer credentials must fail closed",
        )

    def _complete_terminal(self, aid="a-handler-001", container="c-handler-001", fence_token=None):
        if fence_token is None:
            # Auto-assign to get a fence token
            resp = self._handle(
                {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
                peer_uid=1000,
            )
            self.assertIn("assignment", resp)
            fence_token = resp["assignment"]["fence_token"]

        docker, host, pub, _ = _terminal_observers(container, assignment=aid)
        return self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": aid,
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": container,
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )

    def test_forged_receipt_rejected_through_handler(self):
        """Tampered payloads, wrong keys, transplants, wrong UIDs rejected."""
        self._assign(peer_uid=1000)
        done = self._complete_terminal()
        self.assertTrue(done["success"], f"setup completion failed: {done}")
        good_blob, good_sig = done["receipt_blob"], done["receipt_signature"]

        def _verify(peer_uid=1000, key=None, blob=None, sig=None, aid="a-handler-001"):
            body = {
                "type": "verify_receipt",
                "signed_blob": blob if blob is not None else good_blob,
                "signature_b64": sig if sig is not None else good_sig,
                "assignment_id": aid,
                "expected_sender_uid": 1000,
            }
            if key is not None:
                body["public_key_pem"] = key
            conn = _FakeConn(json.dumps(body).encode(), uid=peer_uid)
            B.handle_broker_connection(
                conn,
                self.priv_pem,
                B.journal_append,
                journal_db=self.db,
                keys_dir=self.keys_dir,
                peer_uid=peer_uid,
            )
            return json.loads(conn.sent.decode())

        self.assertTrue(_verify()["valid"], "persisted pinned receipt must verify")
        self.assertFalse(_verify(key=_other_public_key())["valid"], "wrong key must fail")
        self.assertFalse(
            _verify(blob=good_blob.replace("stopped", "running"))["valid"],
            "tampered payload must fail",
        )
        self.assertFalse(_verify(aid="a-other")["valid"], "transplanted receipt must fail")
        conn = _FakeConn(
            json.dumps(
                {
                    "type": "verify_receipt",
                    "signed_blob": good_blob,
                    "signature_b64": good_sig,
                    "assignment_id": "a-handler-001",
                    "expected_sender_uid": 1000,
                }
            ).encode(),
            uid=1000,
        )
        B.handle_broker_connection(
            conn,
            self.priv_pem,
            B.journal_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=None,
        )
        self.assertFalse(json.loads(conn.sent.decode())["valid"], "missing peer UID must fail")

    def test_missing_assignment_rejected_through_handler(self):
        """Completion for a nonexistent assignment is rejected by the handler."""
        docker, host, pub, _ = _terminal_observers("c-x", assignment="a-does-not-exist")
        resp = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-does-not-exist",
                "runner_id": "r-1",
                "success": True,
                "details": {"docker_state": "stopped", "stop_observation": "verified"},
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp["success"])
        self.assertEqual(resp.get("error"), "assignment_not_found")

    def test_caller_supplied_stop_claims_rejected_through_handler(self):
        """running / not-stopped claims rejected even with a sealed assignment."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp)
        fence_token = assign_resp["assignment"]["fence_token"]
        docker, host, pub, _ = _terminal_observers("c-handler-001")
        resp = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "running",
                    "stop_observation": "not stopped",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp["success"], "forged running/not-stopped claims must be rejected")
        self.assertFalse(resp["trusted"], "forged claims must not be trusted")

        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=_terminal_observers("c-handler-001")[:3],
        )
        self.assertTrue(resp2["success"] and resp2["trusted"], "terminal evidence must pass")
        self.assertIn("receipt_blob", resp2, "usable receipt envelope must be returned")
        self.assertIn("receipt_signature", resp2, "usable receipt signature must be returned")
        # The returned envelope must verify against the pinned key and the journal.
        self.assertTrue(
            B.verify_receipt(
                resp2["receipt_blob"],
                resp2["receipt_signature"],
                "a-handler-001",
                1000,
                pinned_public_key_pem=self.pub_pem,
                journal_db=self.db,
                peer_uid=1000,
            ),
            "returned receipt envelope must verify",
        )

    def test_forged_seal_rejected(self):
        """A replaced seal signature does not verify against the pinned key."""
        sealed = B.seal_assignment(dict(_ASSIGNMENT), self.priv_pem)
        self.assertTrue(
            B.verify_sealed_assignment(sealed, "host-opencode-runner", self.pub_pem),
            "genuine seal must verify",
        )
        forged = B.SealedAssignment(
            assignment_id=sealed.assignment_id,
            task_id=sealed.task_id,
            runner_id=sealed.runner_id,
            scope=sealed.scope,
            cgroup=sealed.cgroup,
            container_name=sealed.container_name,
            creator_broker_id=sealed.creator_broker_id,
            created_at=sealed.created_at,
            signature="forged",
            cgroup_proof=sealed.cgroup_proof,
        )
        self.assertFalse(
            B.verify_sealed_assignment(forged, "host-opencode-runner", self.pub_pem),
            "forged seal signature must fail",
        )
        self.assertFalse(
            B.verify_sealed_assignment(sealed, "host-opencode-runner", _other_public_key()),
            "seal verified against wrong key must fail",
        )

    def test_fabricated_journal_seal_rejected(self):
        """A fabricated journal entry with signature 'forged' fails completion."""
        B.journal_append(
            "a-fabricated",
            "assignment_sealed",
            {
                "assignment_id": "a-fabricated",
                "task_id": "t-f",
                "runner_id": "",
                "scope": "test",
                "cgroup": "host-opencode-runner",
                "container_name": "c-fabricated",
                "creator_broker_id": "broker-test",
                "created_at": "2026-01-01T00:00:00Z",
                "cgroup_proof": "0" * 16,
            },
            "forged",
            db_path=self.db,
        )
        docker, host, pub, _ = _terminal_observers("c-fabricated", assignment="a-fabricated")
        resp = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-fabricated",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-fabricated",
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp["success"], "fabricated seal must fail completion")
        self.assertFalse(resp.get("trusted", True), "fabricated seal must not be trusted")

    def test_journal_failure_fails_closed(self):
        """Failed persistence fails the operation; no assignment or success."""

        def failing_append(*_a, **_k):
            return False

        conn = _FakeConn(
            json.dumps({"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)}).encode(),
            uid=1000,
        )
        B.handle_broker_connection(
            conn,
            self.priv_pem,
            failing_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=1000,
        )
        resp = json.loads(conn.sent.decode())
        self.assertIsNone(resp.get("assignment"), "failed persist must return no assignment")
        self.assertEqual(resp.get("error"), "journal_persist_failed")

        self._assign(peer_uid=1000)
        assign_resp2 = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp2)
        fence_token = assign_resp2["assignment"]["fence_token"]
        docker, host, pub, _ = _terminal_observers("c-handler-001")
        conn2 = _FakeConn(
            json.dumps(
                {
                    "type": "complete_assignment",
                    "assignment_id": "a-handler-001",
                    "runner_id": "r-1",
                    "success": True,
                    "details": {
                        "docker_state": "stopped",
                        "stop_observation": "verified",
                        "container_id": "c-handler-001",
                        "fence_token": fence_token,
                    },
                }
            ).encode(),
            uid=1000,
        )
        B.handle_broker_connection(
            conn2,
            self.priv_pem,
            failing_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=1000,
            docker_observe=docker,
            host_observe=host,
            publication_observe=pub,
        )
        resp2 = json.loads(conn2.sent.decode())
        self.assertFalse(resp2["success"], "failed completion persist must not succeed")
        self.assertFalse(resp2.get("trusted", True), "failed persist must not be trusted")
        self.assertEqual(resp2.get("error"), "journal_persist_failed")

    def test_observation_targets_bound_to_seal(self):
        """Caller container mismatch rejected; observers get sealed identity."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp)
        fence_token = assign_resp["assignment"]["fence_token"]
        docker, host, pub, calls = _terminal_observers("c-handler-001")
        resp = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-evil",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp["success"], "caller container mismatch must fail")
        self.assertEqual(resp.get("error"), "container_mismatch")

        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=_terminal_observers("c-handler-001")[:3],
        )
        self.assertTrue(resp2["trusted"], "bound observers must be consulted for sealed target")

    def test_verify_requires_persisted_completion(self):
        """A validly signed receipt with only a seal record must be rejected."""
        self._assign(peer_uid=1000)
        # Sign a well-formed envelope but never persist a completion for it.
        signed = B.sign_payload({"assignment_id": "a-handler-001", "stop": "stopped"}, self.priv_pem)
        conn = _FakeConn(
            json.dumps(
                {
                    "type": "verify_receipt",
                    "signed_blob": signed["signed_blob"],
                    "signature_b64": signed["signature_b64"],
                    "assignment_id": "a-handler-001",
                    "expected_sender_uid": 1000,
                }
            ).encode(),
            uid=1000,
        )
        B.handle_broker_connection(
            conn,
            self.priv_pem,
            B.journal_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=1000,
        )
        self.assertFalse(
            json.loads(conn.sent.decode())["valid"],
            "receipt without persisted completion must fail",
        )

    def test_assignment_retry_identical_is_idempotent(self):
        """Identical reassignment returns the same seal without a second row."""
        first = self._assign(peer_uid=1000)
        seals_before = [
            e
            for e in B.journal_get_entries(assignment_id="a-handler-001", db_path=self.db)
            if e["event_type"] == "assignment_sealed"
        ]
        second = self._assign(peer_uid=1000)
        seals_after = [
            e
            for e in B.journal_get_entries(assignment_id="a-handler-001", db_path=self.db)
            if e["event_type"] == "assignment_sealed"
        ]
        self.assertEqual(second["signature"], first["signature"], "identical retry must return same seal")
        self.assertEqual(len(seals_after), len(seals_before), "identical retry must not append")

    def test_assignment_conflict_rejected_atomically(self):
        """Same assignment ID with a different container is refused; old seal kept."""
        self._assign(peer_uid=1000)
        other = dict(_ASSIGNMENT)
        other["container_name"] = "c-evil-container"
        conn = _FakeConn(
            json.dumps({"type": "assign_task", "assignment_data": other}).encode(),
            uid=1000,
        )
        B.handle_broker_connection(
            conn,
            self.priv_pem,
            B.journal_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=1000,
        )
        resp = json.loads(conn.sent.decode())
        self.assertIsNone(resp.get("assignment"), "conflicting retry must return no assignment")
        self.assertEqual(resp.get("error"), "assignment_conflict")
        seals = [
            e
            for e in B.journal_get_entries(assignment_id="a-handler-001", db_path=self.db)
            if e["event_type"] == "assignment_sealed"
        ]
        self.assertEqual(len(seals), 1, "conflict must not overwrite the original seal")
        self.assertEqual(
            seals[0]["payload"]["container_name"],
            "c-handler-001",
            "original seal must be preserved",
        )

    def test_bound_completion_accepted(self):
        """Full bindings end to end: pinned ID, repo/branch, reaped host."""
        self._assign(peer_uid=1000)
        done = self._complete_terminal()
        self.assertTrue(done["success"] and done["trusted"], f"bound completion failed: {done}")
        self.assertIn("receipt_blob", done)
        self.assertIn("receipt_signature", done)
        self.assertTrue(
            B.verify_receipt(
                done["receipt_blob"],
                done["receipt_signature"],
                "a-handler-001",
                1000,
                pinned_public_key_pem=self.pub_pem,
                journal_db=self.db,
                peer_uid=1000,
            ),
            "returned receipt envelope must verify",
        )

    def test_unpinned_seal_completion_rejected(self):
        """A seal without a pinned full ID can never complete (legacy seals
        fail closed under the binding cross-checks)."""
        data = dict(_ASSIGNMENT)
        del data["container_id"]
        conn = _FakeConn(json.dumps({"type": "assign_task", "assignment_data": data}).encode(), uid=1000)
        B.handle_broker_connection(
            conn,
            self.priv_pem,
            B.journal_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=1000,
        )
        resp = json.loads(conn.sent.decode())
        self.assertIsNotNone(resp.get("assignment"), f"assign failed: {resp}")
        docker, host, pub, _ = _terminal_observers("c-handler-001")
        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp2["success"], "unpinned seal must not complete")
        self.assertFalse(resp2.get("trusted", True))

    def test_evidence_full_id_mismatch_rejected(self):
        """Observed full ID differing from the pinned seal ID is rejected."""
        self._assign(peer_uid=1000)
        docker, host, pub, _ = _terminal_observers(
            "c-handler-001",
            full_id="f" * 64,
        )
        resp = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp["success"], "mismatched full ID must not complete")
        self.assertFalse(resp.get("trusted", True))

    def test_resolver_pins_id_at_discovery(self):
        """A name-only assignment gains its pin via the discovery resolver;
        an unresolvable name stays unpinned and cannot complete."""
        data = dict(_ASSIGNMENT)
        del data["container_id"]
        conn = _FakeConn(json.dumps({"type": "assign_task", "assignment_data": data}).encode(), uid=1000)
        B.handle_broker_connection(
            conn,
            self.priv_pem,
            B.journal_append,
            journal_db=self.db,
            keys_dir=self.keys_dir,
            peer_uid=1000,
            resolve_container_id_fn=lambda _name: FULL_W,
        )
        resp = json.loads(conn.sent.decode())
        self.assertIsNotNone(resp.get("assignment"), f"assign failed: {resp}")
        self.assertEqual(resp["assignment"]["container_id"], FULL_W)
        fence_token = resp["assignment"]["fence_token"]
        docker, host, pub, _ = _terminal_observers("c-handler-001")
        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertTrue(resp2["success"] and resp2["trusted"], f"resolved pin failed: {resp2}")

    def test_fence_race_concurrent_start(self):
        """Concurrent start attempts with same assignment_id: only first wins,
        second must get assignment_conflict (not a new fence token)."""
        # First assignment succeeds with fence token
        resp1 = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", resp1)
        fence1 = resp1["assignment"]["fence_token"]

        # Second assignment with SAME assignment_id but different container
        # must be rejected at seal time (conflict), not get a new fence token
        other = dict(_ASSIGNMENT)
        other["container_name"] = "c-evil-container"
        resp2 = self._handle(
            {"type": "assign_task", "assignment_data": other},
            peer_uid=1000,
        )
        self.assertIsNone(resp2.get("assignment"), "conflicting retry must return no assignment")
        self.assertEqual(resp2.get("error"), "assignment_conflict")

        # Journal should have only ONE fence_start for this assignment_id
        entries = B.journal_get_entries(assignment_id="a-handler-001", db_path=self.db)
        fence_starts = [e for e in entries if e.get("event_type") == "fence_start"]
        self.assertEqual(len(fence_starts), 1, "only one fence_start per assignment_id")

    def test_fence_race_concurrent_completion(self):
        """Two concurrent completion attempts with same fence_token:
        only first succeeds; second must fail fence verification."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        fence_token = assign_resp["assignment"]["fence_token"]
        docker, host, pub, _ = _terminal_observers("c-handler-001")

        # First completion succeeds
        resp1 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertTrue(resp1["success"] and resp1["trusted"])

        # Second completion with SAME fence_token must fail
        # (fence_stop already recorded, pair complete, but fence_check should
        # detect no NEW start between stop and check — or we can just require
        # fence_token is single-use)
        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-2",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=_terminal_observers("c-handler-001")[:3],
        )
        # Should fail because fence is already "closed" or token reused
        self.assertFalse(resp2["success"], "fence token reuse must fail")

    def test_fence_missing_start_fails_verification(self):
        """If only fence_stop exists (no fence_start), _check_fence returns False."""
        # Directly insert a fence_stop without fence_start
        import sqlite3
        import json

        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO broker_journal (assignment_id, event_type, payload, signature, verified) "
            "VALUES (?, 'fence_stop', ?, '{}', 0)",
            ("a-handler-001", json.dumps({"token": "nonexistent-token"}, sort_keys=True)),
        )
        conn.commit()
        conn.close()

        # _check_fence should return False
        self.assertFalse(B._check_fence("a-handler-001", self.db, "nonexistent-token"))

    def test_fence_missing_stop_fails_verification(self):
        """If only fence_start exists (no fence_stop), _check_fence returns False."""
        import sqlite3
        import json

        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO broker_journal (assignment_id, event_type, payload, signature, verified) "
            "VALUES (?, 'fence_start', ?, '{}', 0)",
            ("a-handler-001", json.dumps({"token": "nonexistent-token"}, sort_keys=True)),
        )
        conn.commit()
        conn.close()

        self.assertFalse(B._check_fence("a-handler-001", self.db, "nonexistent-token"))

    def test_fence_token_mismatch_fails_verification(self):
        """If start and stop tokens don't match, _check_fence returns False."""
        import sqlite3
        import json

        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO broker_journal (assignment_id, event_type, payload, signature, verified) "
            "VALUES (?, 'fence_start', ?, '{}', 0)",
            ("a-handler-001", json.dumps({"token": "token-A"}, sort_keys=True)),
        )
        conn.execute(
            "INSERT INTO broker_journal (assignment_id, event_type, payload, signature, verified) "
            "VALUES (?, 'fence_stop', ?, '{}', 0)",
            ("a-handler-001", json.dumps({"token": "token-B"}, sort_keys=True)),
        )
        conn.commit()
        conn.close()

        self.assertFalse(B._check_fence("a-handler-001", self.db, "token-A"))
        self.assertFalse(B._check_fence("a-handler-001", self.db, "token-B"))

    def test_trusted_containment_docker_labels_bound(self):
        """Docker observer must receive sealed assignment identity, not caller ID.
        Verifies the docker_observe closure binds the correct container_id."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        fence_token = assign_resp["assignment"]["fence_token"]

        captured = {}

        def docker_observe(cid, aid):
            captured["cid"] = cid
            captured["aid"] = aid
            return {
                "id": "c-handler-001",
                "full_id": FULL_W,
                "state": "stopped",
                "restart_disabled": True,
                "labels_match": True,
            }

        def host_observe(cg, aid):
            return {"cgroup_empty": True, "service": "stopped", "reaped": True}

        def pub_observe(aid):
            return {"settled": True, "repo": "o/r", "branch": "main"}

        response = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker_observe, host_observe, pub_observe),
        )
        self.assertTrue(response.get("trusted"))
        # Observer must receive sealed assignment identity
        self.assertEqual(captured["cid"], "c-handler-001", "docker must receive sealed container_name")
        self.assertEqual(captured["aid"], "a-handler-001", "docker must receive sealed assignment_id")

    def test_trusted_containment_host_cgroup_bound(self):
        """Host observer must receive sealed cgroup, not caller-supplied cgroup."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        fence_token = assign_resp["assignment"]["fence_token"]

        captured = {}

        def host_observe(cg, aid):
            captured["cg"] = cg
            captured["aid"] = aid
            return {"cgroup_empty": True, "service": "stopped", "reaped": True}

        def docker_observe(cid, aid):
            return {
                "id": "c-handler-001",
                "full_id": FULL_W,
                "state": "stopped",
                "restart_disabled": True,
                "labels_match": True,
            }

        def pub_observe(aid):
            return {"settled": True, "repo": "o/r", "branch": "main"}

        response = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker_observe, host_observe, pub_observe),
        )
        self.assertTrue(response.get("trusted"))
        self.assertEqual(captured["cg"], "host-opencode-runner", "host must receive sealed cgroup")
        self.assertEqual(captured["aid"], "a-handler-001", "host must receive sealed assignment_id")

    def test_integrated_host_exercise(self):
        """Integrated exercise with real disposable host resources.

        This test requires:
        - BROKER_SERVICE_UNIT: systemd service unit for the runner
        - BROKER_CGROUP_PATH: cgroup path for the runner
        - Docker daemon accessible

        Skips gracefully if environment not configured.
        """
        import os

        if not all(k in os.environ for k in ("BROKER_SERVICE_UNIT", "BROKER_CGROUP_PATH")):
            self.skipTest("Live host exercise requires BROKER_SERVICE_UNIT and BROKER_CGROUP_PATH")

        # Use live observers
        docker, host, pub = B._provision_observers(self.db)
        if docker is None or host is None or pub is None:
            self.skipTest("Live observers not fully provisioned")

        # Create assignment with real fence token
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp)
        fence_token = assign_resp["assignment"]["fence_token"]

        # Complete with live observers - this exercises the real host/docker/publication path
        response = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        # With live observers, completion should be trusted
        self.assertTrue(response.get("trusted"), f"Integrated host exercise failed: {response}")
        self.assertIn("receipt_blob", response)
        self.assertIn("receipt_signature", response)

        # Verify the receipt is valid
        self.assertTrue(
            B.verify_receipt(
                response["receipt_blob"],
                response["receipt_signature"],
                "a-handler-001",
                1000,
                pinned_public_key_pem=self.pub_pem,
                journal_db=self.db,
                peer_uid=1000,
            ),
            "Integrated exercise receipt must verify",
        )

def test_fence_atomic_consumption_sequential(self):
        """Sequential test verifying atomic fence token consumption.
        
        Two sequential completions with the same fence token:
        first succeeds (trusted), second fails with fence_token_consumed.
        This verifies the atomic consumption logic without SQLite locking
        issues that affect truly concurrent tests in this environment."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp)
        fence_token = assign_resp["assignment"]["fence_token"]

        docker, host, pub, _ = _terminal_observers("c-handler-001")

        # First completion succeeds
        resp1 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertTrue(resp1["success"] and resp1["trusted"])

        # Second completion with same token fails
        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-2",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp2["success"])
        self.assertEqual(resp2.get("error"), "fence_token_consumed")

def test_fence_untrusted_then_trusted_sequential(self):
        """Sequential test: untrusted completion doesn't consume token,
        subsequent trusted completion succeeds."""
        assign_resp = self._handle(
            {"type": "assign_task", "assignment_data": dict(_ASSIGNMENT)},
            peer_uid=1000,
        )
        self.assertIn("assignment", assign_resp)
        fence_token = assign_resp["assignment"]["fence_token"]

        docker, host, pub, _ = _terminal_observers("c-handler-001")

        # First: untrusted (running) - should fail but NOT consume token
        resp1 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-1",
                "success": True,
                "details": {
                    "docker_state": "running",
                    "stop_observation": "not stopped",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertFalse(resp1["success"])
        self.assertFalse(resp1["trusted"])
        self.assertNotEqual(resp1.get("error"), "fence_token_consumed")

        # Second: trusted (stopped) - should succeed and consume token
        resp2 = self._handle(
            {
                "type": "complete_assignment",
                "assignment_id": "a-handler-001",
                "runner_id": "r-2",
                "success": True,
                "details": {
                    "docker_state": "stopped",
                    "stop_observation": "verified",
                    "container_id": "c-handler-001",
                    "fence_token": fence_token,
                },
            },
            observers=(docker, host, pub),
        )
        self.assertTrue(resp2["success"] and resp2["trusted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
