"""Isolated consumer checks: no services, production keys, DB, or inference."""

import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import threading
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from services.codex_broker_client import (
    BrokerClient,
    BrokerUnavailable,
    MAX_RESPONSE_BYTES,
)
from services.codex_stop_receipts import (
    ExpectedAssignment,
    IssuerPin,
    canonical_bytes,
    verify_current_receipt,
)


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def sign(raw, private):
    return base64.b64encode(
        private.sign(
            raw,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    ).decode()


@pytest.fixture
def evidence(keys):
    private, public = keys
    expected = ExpectedAssignment("assignment-a", "41", "c" * 64, "/attempt-a", "runner-a")
    pin = IssuerPin("host-opencode-broker", "reviewed-key-v1", public)
    payload = {
        "assignment_id": expected.assignment_id,
        "task_id": expected.task_id,
        "runner_id": expected.runner_id,
        "container": expected.container,
        "cgroup": expected.cgroup,
        "execution_stopped": True,
        "publication_settled": True,
        "assignment_sealed": True,
        "success": True,
        "observed_at": 1000,
    }
    seal = {
        "assignment_id": expected.assignment_id,
        "task_id": expected.task_id,
        "runner_id": "",
        "scope": "codex",
        "cgroup": expected.cgroup,
        "container_name": expected.container,
        "creator_broker_id": pin.issuer_id,
        "created_at": "2026-10-11T00:00:00Z",
    }
    seal_signature = sign(canonical_bytes(seal), private)
    seal["cgroup_proof"] = hashlib.sha256((expected.cgroup + expected.container).encode()).hexdigest()[:16]
    envelope = {"version": 1, "timestamp": 1000, "payload": payload}
    blob = canonical_bytes(envelope).decode()
    signature = sign(blob.encode(), private)
    entries = [
        {
            "assignment_id": expected.assignment_id,
            "event_type": "assignment_sealed",
            "payload": seal,
            "signature": seal_signature,
        },
        {
            "assignment_id": expected.assignment_id,
            "event_type": "assignment_completed",
            "payload": {"envelope": blob, "trusted": True},
            "signature": signature,
        },
    ]
    return dict(
        blob=blob,
        signature=signature,
        pin=pin,
        expected=expected,
        journal_entries=entries,
        now=1000,
    )


def test_valid_evidence_never_authorizes_recovery(evidence):
    result = verify_current_receipt(**evidence)
    assert result.evidence_verified and result.code == "terminal_diagnostic_only"
    assert result.stop_confirmed is False and result.recovery_eligible is False


@pytest.mark.parametrize("field", ["assignment_id", "task_id", "container", "cgroup", "runner_id"])
def test_receipt_cannot_move_to_another_assignment(evidence, field):
    evidence["expected"] = replace(evidence["expected"], **{field: "different"})
    assert verify_current_receipt(**evidence).code == "assignment_mismatch"


@pytest.mark.parametrize(
    "mutation",
    [
        "deleted",
        "wrong_blob",
        "wrong_signature",
        "forged_seal",
        "duplicate_seal",
        "foreign_entry",
    ],
)
def test_journal_evidence_cannot_be_substituted(evidence, mutation):
    entries = evidence["journal_entries"]
    if mutation == "deleted":
        entries.pop()
    elif mutation == "wrong_blob":
        entries[1]["payload"]["envelope"] += " "
    elif mutation == "wrong_signature":
        entries[1]["signature"] = "forged"
    elif mutation == "forged_seal":
        entries[0]["signature"] = "forged"
    elif mutation == "duplicate_seal":
        entries.append(entries[0])
    else:
        entries[0]["assignment_id"] = "another-assignment"
    assert not verify_current_receipt(**evidence).evidence_verified


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean_version",
        "string_timestamp",
        "missing",
        "duplicate",
        "whitespace",
        "oversize",
        "float",
        "tampered",
    ],
)
def test_strict_envelope(evidence, keys, mutation):
    envelope = json.loads(evidence["blob"])
    if mutation == "boolean_version":
        envelope["version"] = True
    elif mutation == "string_timestamp":
        envelope["timestamp"] = "1000"
    elif mutation == "missing":
        del envelope["payload"]["execution_stopped"]
    elif mutation == "float":
        envelope["payload"]["observed_at"] = 1000.0
    elif mutation == "tampered":
        evidence["blob"] = evidence["blob"].replace('"success":true', '"success":false')
        assert not verify_current_receipt(**evidence).evidence_verified
        return
    if mutation == "duplicate":
        blob = evidence["blob"][:-1] + ',"version":1}'
    elif mutation == "whitespace":
        blob = json.dumps(envelope)
    elif mutation == "oversize":
        blob = " " * 65537
    else:
        blob = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    evidence["blob"] = blob
    evidence["signature"] = sign(blob.encode(), keys[0])
    assert not verify_current_receipt(**evidence).evidence_verified


@pytest.mark.parametrize("value", ["true", 1, None, {}, []])
def test_outcomes_are_strict_booleans(evidence, keys, value):
    envelope = json.loads(evidence["blob"])
    envelope["payload"]["execution_stopped"] = value
    evidence["blob"] = canonical_bytes(envelope).decode()
    evidence["signature"] = sign(evidence["blob"].encode(), keys[0])
    assert verify_current_receipt(**evidence).code == "payload_invalid"


@pytest.mark.parametrize("now", [1301, 939])
def test_stale_or_future_receipt_rejected(evidence, now):
    evidence["now"] = now
    assert verify_current_receipt(**evidence).code == "receipt_stale"


def test_revoked_pin_and_wrong_issuer_rejected(evidence):
    evidence["pin"] = replace(evidence["pin"], revoked=True)
    assert verify_current_receipt(**evidence).code == "issuer_untrusted"
    evidence["pin"] = replace(evidence["pin"], revoked=False, issuer_id="another-host")
    assert verify_current_receipt(**evidence).code == "seal_mismatch"


def test_wrong_signature_and_non_rsa_key_rejected(evidence):
    evidence["signature"] = "forged"
    assert not verify_current_receipt(**evidence).evidence_verified
    evidence["pin"] = replace(evidence["pin"], public_key_pem="malformed key")
    assert not verify_current_receipt(**evidence).evidence_verified


def test_unknown_receipt_is_visible_but_never_eligible(evidence, keys):
    envelope = json.loads(evidence["blob"])
    envelope["payload"].update(execution_stopped=False, publication_settled=False, success=False)
    evidence["blob"] = canonical_bytes(envelope).decode()
    evidence["signature"] = sign(evidence["blob"].encode(), keys[0])
    evidence["journal_entries"][1].update(
        signature=evidence["signature"],
        payload={"envelope": evidence["blob"], "trusted": False},
    )
    result = verify_current_receipt(**evidence)
    assert result.evidence_verified and result.code == "execution_unknown"
    assert not result.stop_confirmed and not result.recovery_eligible


def test_disabled_client_never_opens_socket(tmp_path, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(socket, "socket", factory)
    client = BrokerClient(str(tmp_path / "broker.sock"), os.getuid())
    with pytest.raises(BrokerUnavailable, match="broker_disabled"):
        client.journal("a")
    factory.assert_not_called()


def test_actual_unix_transport_half_closes_and_reads_one_assignment(tmp_path):
    path = str(tmp_path / "broker.sock")
    # Keep AF_UNIX path under its kernel limit regardless of pytest's base path.
    if len(path.encode()) >= 104:
        pytest.skip("temporary socket path exceeds AF_UNIX limit")
    tmp_path.chmod(0o700)
    requests, errors = [], []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(3)

        def serve():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(3)
                    data = b""
                    while True:
                        chunk = peer.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    requests.append(json.loads(data))
                    peer.sendall(b'{"type":"journal_response","entries":[]}')
            except Exception as exc:
                errors.append(type(exc).__name__)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            client = BrokerClient(path, os.getuid(), enabled=True)
            assert client.journal("assignment-a") == []
        finally:
            thread.join(timeout=4)
        assert not thread.is_alive() and not errors
    assert requests == [{"type": "get_journal", "assignment_id": "assignment-a"}]


@pytest.mark.parametrize("mutation", ["peer", "oversize", "duplicate", "timeout", "malformed", "too_many"])
def test_transport_failures_are_bounded_and_sanitized(tmp_path, monkeypatch, mutation):
    uid = os.getuid()
    info = Mock(st_mode=0o140600, st_uid=uid)
    parent = Mock(st_mode=0o040700, st_uid=uid)
    monkeypatch.setattr(Path, "lstat", lambda path: info if path.name == "broker.sock" else parent)
    conn = Mock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    conn.getsockopt.return_value = struct.pack("3i", 123, uid + (mutation == "peer"), 100)
    reply = b'{"type":"journal_response","entries":[]}'
    if mutation == "oversize":
        reply = b"x" * (MAX_RESPONSE_BYTES + 1)
    elif mutation == "duplicate":
        reply = b'{"type":"journal_response","entries":[],"entries":[]}'
    elif mutation == "malformed":
        reply = b"credential-looking-sensitive-data"
    elif mutation == "too_many":
        reply = json.dumps({"type": "journal_response", "entries": [{}] * 257}).encode()
    conn.recv.side_effect = [reply, b""]
    if mutation == "timeout":
        conn.recv.side_effect = socket.timeout("sensitive timeout details")
    monkeypatch.setattr(socket, "socket", Mock(return_value=conn))
    client = BrokerClient(str(tmp_path / "broker.sock"), uid, enabled=True)
    with pytest.raises(BrokerUnavailable) as caught:
        client.journal("assignment-a")
    assert "sensitive" not in str(caught.value)


def test_current_broker_completion_roundtrip(tmp_path, keys, monkeypatch):
    """Use the merged broker's actual assignment/completion/signing handlers."""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[1] / "tools/host_opencode/broker.py"
    spec = importlib.util.spec_from_file_location("consumer_fixture_broker", path)
    broker = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, broker)
    spec.loader.exec_module(broker)
    monkeypatch.setattr(broker.time, "time", lambda: 1000)
    private, public = keys
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setattr(broker, "load_public_key", lambda *_args: public)
    db = str(tmp_path / "journal.db")
    assert broker.journal_init(db)
    assignment = {
        "assignment_id": "assignment-a",
        "task_id": "41",
        "runner_id": "",
        "scope": "codex",
        "cgroup": "/attempt-a",
        "container_name": "c" * 64,
        "broker_id": "host-opencode-broker",
        "created_at": "2026-10-11T00:00:00Z",
    }

    def request(body, **kwargs):
        conn = Mock()
        conn.recv.side_effect = [json.dumps(body).encode(), b""]
        broker.handle_broker_connection(conn, pem, broker.journal_append, journal_db=db, **kwargs)
        return json.loads(conn.sendall.call_args.args[0])

    assert request({"type": "assign_task", "assignment_data": assignment})["assignment"]
    response = request(
        {
            "type": "complete_assignment",
            "assignment_id": "assignment-a",
            "runner_id": "runner-a",
            "success": True,
            "details": {
                "docker_state": "stopped",
                "stop_observation": "verified",
                "container_id": "c" * 64,
            },
        },
        docker_observe=lambda cid, aid: {
            "id": cid,
            "state": "stopped",
            "restart_disabled": True,
            "labels_match": True,
        },
        host_observe=lambda cg, aid: {"cgroup_empty": True, "service": "stopped"},
        publication_observe=lambda aid: {"settled": True},
    )
    assert response["trusted"] is True
    result = verify_current_receipt(
        response["receipt_blob"],
        response["receipt_signature"],
        pin=IssuerPin("host-opencode-broker", "reviewed-key-v1", public),
        expected=ExpectedAssignment("assignment-a", "41", "c" * 64, "/attempt-a", "runner-a"),
        journal_entries=broker.journal_get_entries("assignment-a", db_path=db),
        now=1000,
    )
    assert result.evidence_verified and not result.recovery_eligible and not result.stop_confirmed


def test_crypto_unavailable_fails_closed(evidence, monkeypatch):
    from services import codex_stop_receipts

    def unavailable(*args):
        raise ImportError("not installed")

    monkeypatch.setattr(codex_stop_receipts, "_signature_valid", unavailable)
    assert verify_current_receipt(**evidence).code == "crypto_unavailable"


def test_different_pinned_key_rejects_receipt(evidence):
    other = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    public = (
        other.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    evidence["pin"] = replace(evidence["pin"], public_key_pem=public)
    assert verify_current_receipt(**evidence).code == "signature_invalid"


def test_missing_socket_produces_unknown_observation(tmp_path, evidence):
    client = BrokerClient(str(tmp_path / "missing.sock"), os.getuid(), enabled=True)
    result = client.inspect_receipt(
        evidence["blob"],
        evidence["signature"],
        pin=evidence["pin"],
        expected=evidence["expected"],
    )
    assert not result.evidence_verified and not result.stop_confirmed and not result.recovery_eligible
