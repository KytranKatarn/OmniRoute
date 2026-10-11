"""Diagnostic consumer for the current broker envelope, never recovery authority.

The broker's current version=1 is NOT the complete trusted-stop v1 contract.
No result from this module can authorize replacement or certify containment.
Trust pins and expected assignment come from reviewed configuration/server state,
never the receipt, task metadata, browser, or broker response being verified.
"""

import base64
from dataclasses import dataclass
import hashlib
import json
import time

MAX_BLOB_BYTES = 65536


@dataclass(frozen=True)
class IssuerPin:
    issuer_id: str
    key_id: str
    public_key_pem: str
    revoked: bool = False


@dataclass(frozen=True)
class ExpectedAssignment:
    assignment_id: str
    task_id: str
    container: str
    cgroup: str
    runner_id: str


@dataclass(frozen=True)
class ReceiptObservation:
    evidence_verified: bool
    code: str

    @property
    def recovery_eligible(self) -> bool:
        return False

    @property
    def stop_confirmed(self) -> bool:
        return False


def _bounded_value(value, depth=0):
    if depth > 16:
        raise ValueError("depth")
    if isinstance(value, dict):
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("key")
            _bounded_value(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _bounded_value(child, depth + 1)
    elif value is not None and type(value) not in (str, int, bool):
        raise ValueError("type")


def canonical_bytes(value) -> bytes:
    _bounded_value(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_BLOB_BYTES:
        raise ValueError("size")
    return encoded


def strict_json(raw: bytes, *, limit=MAX_BLOB_BYTES):
    if type(raw) is not bytes or len(raw) > limit:
        raise ValueError("size")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    _bounded_value(value)
    return value


def _signature_valid(raw, signature, pem):
    # Optional at runtime: absent crypto support fails closed, never downloads.
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    if type(signature) is not str or len(signature) > 2048:
        return False
    try:
        key = serialization.load_pem_public_key(pem.encode("ascii"))
    except UnsupportedAlgorithm:
        return False
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 4096:
        return False
    try:
        key.verify(
            base64.b64decode(signature, validate=True),
            raw,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return False
    return True


def verify_current_receipt(
    blob: str,
    signature: str,
    *,
    pin: IssuerPin,
    expected: ExpectedAssignment,
    journal_entries: list,
    now: int = None,
) -> ReceiptObservation:
    """Check current exact bytes, pinned signature, assignment, and journal match.

    Journal entries must be fetched fresh from the authenticated broker. This
    verifies diagnostic evidence only; missing full-contract fields and host
    provisioning prevent a trusted stop/recovery decision even on success.
    """

    def reject(code):
        return ReceiptObservation(False, code)

    try:
        if pin.revoked is not False or not pin.issuer_id or not pin.key_id:
            return reject("issuer_untrusted")
        if type(blob) is not str:
            return reject("envelope_invalid")
        raw = blob.encode("utf-8")
        envelope = strict_json(raw)
        if not isinstance(envelope, dict) or set(envelope) != {
            "version",
            "timestamp",
            "payload",
        }:
            return reject("envelope_invalid")
        if canonical_bytes(envelope) != raw:
            return reject("encoding_noncanonical")
        if type(envelope["version"]) is not int or envelope["version"] != 1:
            return reject("version_unsupported")
        timestamp = envelope["timestamp"]
        current = int(time.time()) if now is None else now
        if type(timestamp) is not int or not -60 <= current - timestamp <= 300:
            return reject("receipt_stale")
        if not _signature_valid(raw, signature, pin.public_key_pem):
            return reject("signature_invalid")
        payload = envelope["payload"]
        fields = {
            "assignment_id",
            "task_id",
            "runner_id",
            "container",
            "cgroup",
            "execution_stopped",
            "publication_settled",
            "assignment_sealed",
            "success",
            "observed_at",
        }
        if not isinstance(payload, dict) or set(payload) != fields:
            return reject("payload_invalid")
        for key in (
            "execution_stopped",
            "publication_settled",
            "assignment_sealed",
            "success",
        ):
            if type(payload[key]) is not bool:
                return reject("payload_invalid")
        if type(payload["observed_at"]) is not int or not 0 <= timestamp - payload["observed_at"] <= 60:
            return reject("observation_invalid")
        for field, value in (
            ("assignment_id", expected.assignment_id),
            ("task_id", expected.task_id),
            ("container", expected.container),
            ("cgroup", expected.cgroup),
            ("runner_id", expected.runner_id),
        ):
            if type(value) is not str or not value or type(payload[field]) is not str or payload[field] != value:
                return reject("assignment_mismatch")
        if type(journal_entries) is not list or len(journal_entries) > 256:
            return reject("journal_invalid")
        if any(
            not isinstance(entry, dict) or entry.get("assignment_id") != expected.assignment_id
            for entry in journal_entries
        ):
            return reject("journal_invalid")
        seals = [e for e in journal_entries if e.get("event_type") == "assignment_sealed"]
        if len(seals) != 1:
            return reject("seal_missing_or_conflicting")
        seal = seals[0].get("payload")
        seal_fields = {
            "assignment_id",
            "task_id",
            "runner_id",
            "scope",
            "cgroup",
            "container_name",
            "creator_broker_id",
            "created_at",
            "cgroup_proof",
        }
        if not isinstance(seal, dict) or set(seal) != seal_fields or any(type(v) is not str for v in seal.values()):
            return reject("seal_invalid")
        if (
            seal["assignment_id"] != expected.assignment_id
            or seal["task_id"] != expected.task_id
            or seal["container_name"] != expected.container
            or seal["cgroup"] != expected.cgroup
            or seal["creator_broker_id"] != pin.issuer_id
            or (seal["runner_id"] and seal["runner_id"] != expected.runner_id)
        ):
            return reject("seal_mismatch")
        proof = hashlib.sha256((seal["cgroup"] + seal["container_name"]).encode()).hexdigest()[:16]
        if seal["cgroup_proof"] != proof:
            return reject("seal_invalid")
        signed_seal = {k: v for k, v in seal.items() if k != "cgroup_proof"}
        if not _signature_valid(canonical_bytes(signed_seal), seals[0].get("signature"), pin.public_key_pem):
            return reject("seal_invalid")
        matching = [
            entry
            for entry in journal_entries
            if entry.get("event_type") == "assignment_completed"
            and isinstance(entry.get("payload"), dict)
            and entry["payload"].get("envelope") == blob
            and entry.get("signature") == signature
        ]
        if not matching:
            return reject("completion_missing")
        terminal = payload["execution_stopped"] and payload["publication_settled"] and payload["assignment_sealed"]
        if any(type(e["payload"].get("trusted")) is not bool or e["payload"]["trusted"] != terminal for e in matching):
            return reject("completion_inconsistent")
        return ReceiptObservation(True, "terminal_diagnostic_only" if terminal else "execution_unknown")
    except ImportError:
        return reject("crypto_unavailable")
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        OverflowError,
    ):
        return reject("evidence_invalid")
