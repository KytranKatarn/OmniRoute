"""
Isolated regression tests for the Host OpenCode broker.

Proves the four Codex-verified failures are rejected:
  1. untrusted peers (mocked UID 99999 rejected even when broker euid trusted)
  2. forged receipts (tampered payload or wrong key rejected)
  3. missing assignments (completion for nonexistent assignment rejected)
  4. caller-supplied stop claims (running / not stopped rejected)

Plus a positive control proving valid terminal evidence is accepted.

Isolation: tmp dirs via env overrides (HOST_OPENCODE_KEYS_DIR,
HOST_OPENCODE_JOURNAL_DB); no writes to /var/lib/host-opencode; no network;
no platform DB. Run with: python3 platform_v2/tests/test_broker_fixes.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "host_opencode"))

import broker as B


def _make_keys(tmpdir):
    """Fast 2048-bit test keypair written to an isolated keys dir."""
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
    """Fake Unix socket returning controlled SO_PEERCRED bytes."""

    def __init__(self, uid=None, fail=False):
        import struct as _struct

        self._uid = uid
        self._fail = fail
        self._struct = _struct

    def getsockopt(self, level, opt, buflen):
        if self._fail or self._uid is None:
            raise OSError("no peercred")
        return self._struct.pack("iii", 1234, int(self._uid), 100)


class BrokerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "journal.db")
        self.assertTrue(B.journal_init(self.db))

    def test_untrusted_peer_rejected(self):
        """UID 99999 is rejected even though the broker itself runs trusted."""
        conn = _FakeConn(uid=99999)
        self.assertFalse(
            B.validate_peer_identity(conn, {1000}, _get_peer_uid=B.get_peer_uid),
            "untrusted peer UID 99999 must be rejected",
        )
        trusted = _FakeConn(uid=1000)
        self.assertTrue(
            B.validate_peer_identity(trusted, {1000}, _get_peer_uid=B.get_peer_uid),
            "trusted peer UID must be accepted",
        )
        broken = _FakeConn(uid=None, fail=True)
        self.assertFalse(
            B.validate_peer_identity(broken, {1000}, _get_peer_uid=B.get_peer_uid),
            "unreadable peer credentials must fail closed",
        )

    def test_forged_receipt_rejected(self):
        """Tampered payloads and wrong keys are rejected against the pinned key."""
        keys_dir, priv_pem, pub_pem = _make_keys(self.tmp.name)
        B.journal_append("a-forged", "assignment_sealed", {"x": 1}, "sig", db_path=self.db)

        good = B.sign_payload({"assignment_id": "a-forged", "stop": "stopped"}, priv_pem)
        self.assertTrue(
            B.verify_receipt(
                good["signed_blob"],
                good["signature_b64"],
                "a-forged",
                1000,
                pinned_public_key_pem=pub_pem,
                journal_db=self.db,
                peer_uid=1000,
            ),
            "valid pinned receipt must verify",
        )
        # Wrong key (attacker-supplied trust anchor) rejected.
        self.assertFalse(
            B.verify_receipt(
                good["signed_blob"],
                good["signature_b64"],
                "a-forged",
                1000,
                pinned_public_key_pem=_other_public_key(),
                journal_db=self.db,
                peer_uid=1000,
            ),
            "receipt verified against wrong key must fail",
        )
        # Caller-supplied key differing from pinned key rejected.
        self.assertFalse(
            B.verify_receipt(
                good["signed_blob"],
                good["signature_b64"],
                "a-forged",
                1000,
                pinned_public_key_pem=pub_pem,
                journal_db=self.db,
                peer_uid=1000,
                untrusted_public_key_pem=_other_public_key(),
            ),
            "caller-supplied substitute key must fail",
        )
        # Tampered envelope bytes rejected.
        tampered = good["signed_blob"].replace("stopped", "running")
        self.assertFalse(
            B.verify_receipt(
                tampered,
                good["signature_b64"],
                "a-forged",
                1000,
                pinned_public_key_pem=pub_pem,
                journal_db=self.db,
                peer_uid=1000,
            ),
            "tampered payload must fail",
        )
        # Transplant onto another assignment rejected.
        self.assertFalse(
            B.verify_receipt(
                good["signed_blob"],
                good["signature_b64"],
                "a-other",
                1000,
                pinned_public_key_pem=pub_pem,
                journal_db=self.db,
                peer_uid=1000,
            ),
            "transplanted receipt must fail",
        )
        # Wrong sender UID rejected.
        self.assertFalse(
            B.verify_receipt(
                good["signed_blob"],
                good["signature_b64"],
                "a-forged",
                1000,
                pinned_public_key_pem=pub_pem,
                journal_db=self.db,
                peer_uid=99999,
            ),
            "wrong sender UID must fail",
        )

    def test_missing_assignment_rejected(self):
        """Completion for a nonexistent assignment is rejected."""
        self.assertFalse(
            B.check_trusted_completion([], {"docker_state": "stopped", "stop_observation": "verified"}),
            "empty journal must not complete",
        )
        B.journal_append("a-real", "assignment_sealed", {"t": 1}, "sig", db_path=self.db)
        self.assertEqual(
            B.journal_get_entries(assignment_id="a-nope", db_path=self.db),
            [],
            "unknown assignment must have no journal entries",
        )

    def test_caller_supplied_stop_claims_rejected(self):
        """docker_state=running + stop_observation=not stopped is rejected."""
        B.journal_append("a-stop", "assignment_sealed", {"t": 1}, "sig", db_path=self.db)
        entries = B.journal_get_entries(assignment_id="a-stop", db_path=self.db)
        self.assertFalse(
            B.check_trusted_completion(entries, {"docker_state": "running", "stop_observation": "not stopped"}),
            "forged running/not-stopped claims must be rejected",
        )
        self.assertFalse(
            B.check_trusted_completion(entries, {}),
            "missing observations must be rejected",
        )
        self.assertTrue(
            B.check_trusted_completion(entries, {"docker_state": "stopped", "stop_observation": "verified"}),
            "explicit terminal evidence must be accepted",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
