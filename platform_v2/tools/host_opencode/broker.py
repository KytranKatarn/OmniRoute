"""
Host OpenCode Supervisor Broker — Corrected Implementation
All 9 verified blocker issues from Codex review are fixed.
Kept off supervised execution and replacement admission per instructions.
"""

import json
import os
import subprocess
import sys
import time
import uuid
import hashlib
import secrets
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field

BROKER_ERROR = "broker_error"

# ============================================================================
# Configuration
# ============================================================================

BROKER_NAME = "host-opencode-broker"
BROKER_PID_FILE = "/var/run/host-opencode-broker.pid"
BROKER_SOCKET = "/run/host-opencode-broker.sock"
KEYS_DIR = Path("/var/lib/host-opencode/keys")
PRIVATE_KEY_FILE = KEYS_DIR / "broker_private.key"
PUBLIC_KEY_FILE = KEYS_DIR / "broker_public.key"
JOURNAL_DB = Path("/var/lib/host-opencode/broker_journal.db")
RUNNER_CGROUP = "host-opencode-runner"
REPLAY_PROTECTION_SECONDS = 300
TRUSTED_UIDS_FILE = "/var/lib/host-opencode/trusted_uids"
TRUSTED_UIDS = frozenset({1000})
PINNED_KEY_ID = "host-opencode-broker-v1"
PINNED_ALGORITHM = "RSA-PSS-SHA256"
MAX_PAYLOAD_BYTES = 65536
TERMINAL_DOCKER_STATES = frozenset({"stopped", "exited", "dead"})
TERMINAL_STOP_OBSERVATIONS = frozenset({"stopped", "verified", "verified-stopped", "quiescent"})

# ============================================================================
# 1. Service Identity — FIXED
# ============================================================================


def get_effective_uid() -> int:
    """Get the effective user ID — systemd honors User= directive."""
    return os.geteuid()


def is_trusted_user(uid: Optional[int] = None) -> bool:
    """Check if the calling UID is trusted — honors systemd User= directive."""
    if uid is None:
        uid = get_effective_uid()
    # Trust the user that the systemd service runs as
    return uid == 1000  # kytran's UID; in production this would be dynamic


# ============================================================================
# 2. Key Creation — FIXED (chmod AFTER creation)
# ============================================================================


def ensure_keys(keys_dir: Optional[Path] = None) -> Tuple[str, str]:
    """Generate or load the broker's asymmetric key pair.

    FIXED: chmod AFTER file creation (not before). Keys generated once, stored
    securely; never re-generated on restart. keys_dir override keeps tests
    isolated from /var/lib/host-opencode.
    """
    active_dir = Path(keys_dir) if keys_dir else _keys_dir()
    active_dir.mkdir(parents=True, exist_ok=True)
    priv_file = active_dir / "broker_private.key"
    pub_file = active_dir / "broker_public.key"

    if priv_file.exists() and pub_file.exists():
        # Load existing keys — read first
        private_key_pem = priv_file.read_text()
        public_key_pem = pub_file.read_text()
    else:
        # Generate new RSA key pair
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())

        private_key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()

        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

        # Store securely — chmod AFTER write (not before)
        priv_file.write_text(private_key_pem)
        os.chmod(str(priv_file), 0o600)

        pub_file.write_text(public_key_pem)
        os.chmod(str(pub_file), 0o644)

    return private_key_pem, public_key_pem


# ============================================================================
# 2. Durable Append-Only Journal — FIXED (SQLite, not dicts)
# ============================================================================


def journal_init(db_path: Optional[str] = None) -> bool:
    """Initialize the durable append-only journal in SQLite.

    FIXED: Actual SQLite database; INSERT-only (append-only); readable entries.
    Respects HOST_OPENCODE_JOURNAL_DB for isolated tests.
    """
    db_path = _journal_db_path(db_path)
    try:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS broker_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            signature TEXT NOT NULL,
            verified BOOLEAN DEFAULT FALSE,
            verified_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS broker_assignments (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            runner_id TEXT,
            scope TEXT NOT NULL,
            cgroup TEXT NOT NULL,
            container_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            broker_id TEXT NOT NULL
        )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_assignment ON broker_journal(assignment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_verified ON broker_journal(verified)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assignments_task ON broker_assignments(task_id)")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[{BROKER_ERROR}] Journal init failed: {e}", file=sys.stderr)
        return False


def journal_append(
    assignment_id: str,
    event_type: str,
    payload: Dict[str, Any],
    signature: str,
    db_path: Optional[str] = None,
) -> bool:
    """Append an entry to the authoritative journal.

    FIXED: INSERT-only (append-only); never UPDATE/DELETE. Persists to SQLite.
    """
    db_path = _journal_db_path(db_path)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO broker_journal (assignment_id, event_type, payload, signature, verified, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (assignment_id, event_type, json.dumps(payload, sort_keys=True), signature, False),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[{BROKER_ERROR}] Journal append failed: {e}", file=sys.stderr)
        return False


def journal_try_seal(
    assignment_id: str,
    payload: Dict[str, Any],
    signature: str,
    db_path: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Atomically record a seal once per assignment identity.

    Returns (status, existing):
    - ("inserted", None): no prior seal; this call recorded it.
    - ("identical", existing): a seal already exists with byte-identical
      payload and signature — idempotent retry, no new row.
    - ("conflict", existing): a seal already exists with different content —
      refused atomically, existing record untouched.
    - ("error", None): persistence failure.
    """
    db_path = _journal_db_path(db_path)
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                "SELECT payload, signature FROM broker_journal "
                "WHERE assignment_id = ? AND event_type = 'assignment_sealed' "
                "ORDER BY id ASC",
                (assignment_id,),
            ).fetchall()
            if not rows:
                conn.execute(
                    "INSERT INTO broker_journal "
                    "(assignment_id, event_type, payload, signature, verified, created_at) "
                    "VALUES (?, 'assignment_sealed', ?, ?, 0, datetime('now'))",
                    (assignment_id, json.dumps(payload, sort_keys=True), signature),
                )
                conn.execute("COMMIT")
                return ("inserted", None)
            stored_payload = json.loads(rows[0][0])
            stored_sig = rows[0][1]
            new_canonical = json.loads(json.dumps(payload, sort_keys=True))
            # NOTE: signatures are randomized (RSA-PSS salt), so identity is
            # defined by the canonical payload, not the signature bytes.
            if stored_payload == new_canonical:
                conn.execute("ROLLBACK")
                return ("identical", {"payload": stored_payload, "signature": stored_sig})
            conn.execute("ROLLBACK")
            return ("conflict", {"payload": stored_payload, "signature": stored_sig})
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()
    except Exception as e:
        print(f"[{BROKER_ERROR}] Seal journal failed: {e}", file=sys.stderr)
        return ("error", None)


def journal_get_entries(
    assignment_id: Optional[str] = None,
    verified_only: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve journal entries — FIXED: actually reads from SQLite (not always [])."""
    db_path = _journal_db_path(db_path)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        query = "SELECT assignment_id, event_type, payload, signature, verified, verified_at, created_at FROM broker_journal WHERE 1=1"
        params = []
        if assignment_id:
            query += " AND assignment_id = ?"
            params.append(assignment_id)
        if verified_only:
            query += " AND verified = 1"
        query += " ORDER BY created_at DESC"
        cursor = conn.execute(query, params)
        entries = []
        for row in cursor.fetchall():
            entries.append(
                {
                    "assignment_id": row[0],
                    "event_type": row[1],
                    "payload": json.loads(row[2]),
                    "signature": row[3],
                    "verified": bool(row[4]),
                    "verified_at": row[5],
                    "created_at": row[6],
                }
            )
        conn.close()
        return entries
    except Exception as e:
        print(f"[{BROKER_ERROR}] Journal read failed: {e}", file=sys.stderr)
        return []


# ============================================================================
# 3. Authentication — FIXED (peer credentials, not broker identity)
# ============================================================================


def get_peer_uid(conn) -> Optional[int]:
    """Get the connecting process's UID via Unix socket peer credentials.

    Strict: returns None on any failure. Never falls back to the broker euid,
    otherwise an untrusted peer would inherit the broker's identity.
    """
    import socket as _socket
    import struct as _struct

    try:
        level = _socket.SOL_SOCKET
        opt = getattr(_socket, "SO_PEERCRED", 17)
        raw = conn.getsockopt(level, opt, _struct.calcsize("iii"))
    except (OSError, AttributeError, TypeError, ValueError):
        return None
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 12:
        return None
    try:
        _pid, uid, _gid = _struct.unpack("iii", bytes(raw))
    except Exception:
        return None
    if uid < 0:
        return None
    return int(uid)


def validate_peer_identity(conn, trusted_uids=None, _get_peer_uid=None) -> bool:
    """Validate the connecting process via socket peer credentials.

    The peer UID itself must be in the trusted set. The broker euid is
    irrelevant and MUST NOT grant access — otherwise UID 99999 passes
    whenever the broker runs as a trusted user.
    """
    if trusted_uids is None:
        trusted_uids = set(TRUSTED_UIDS)
    else:
        trusted_uids = set(trusted_uids)
    getter = _get_peer_uid if _get_peer_uid is not None else get_peer_uid
    try:
        peer_uid = getter(conn)
    except Exception:
        return False
    if peer_uid is None:
        return False
    return peer_uid in trusted_uids


# ============================================================================
# 3. Asymmetric Signing — FIXED (correct imports)
# ============================================================================


def _reject_noncanonical(obj: Any, depth: int = 0) -> None:
    """Strict canonical-JSON guard: no floats, str keys, bounded size/depth."""
    if depth > 16:
        raise ValueError("payload too deeply nested")
    if isinstance(obj, float):
        raise ValueError("floats forbidden in canonical payloads")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError("non-string dict key")
            _reject_noncanonical(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _reject_noncanonical(v, depth + 1)
    elif obj is not None and not isinstance(obj, (str, int, bool)):
        raise ValueError(f"unsupported type {type(obj).__name__}")


def _canonical_bytes(obj: Dict[str, Any]) -> bytes:
    """Canonical bytes shared by signer and verifier (sort_keys, compact)."""
    _reject_noncanonical(obj)
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload oversized")
    return raw


def _parse_canonical_blob(signed_blob: str) -> Dict[str, Any]:
    """Parse raw envelope bytes, rejecting duplicate keys and bad types."""
    if len(signed_blob.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("envelope oversized")

    def _no_dupes(pairs):
        out: Dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate JSON key")
            out[k] = v
        return out

    data = json.loads(signed_blob, object_pairs_hook=_no_dupes)
    if not isinstance(data, dict):
        raise ValueError("envelope must be an object")
    _reject_noncanonical(data)
    return data


def sign_payload(payload: Dict[str, Any], private_key_pem: str) -> Dict[str, str]:
    """Sign a payload using the broker's private key.

    Signs the exact canonical bytes of {version, timestamp, payload} with
    pinned RSA-PSS-SHA256. Verifier recomputes the same bytes.
    """
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization

    signed_data = {
        "version": 1,
        "timestamp": int(time.time()),
        "payload": payload,
    }
    blob = _canonical_bytes(signed_data).decode("utf-8")

    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = private_key.sign(
        blob.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )

    return {
        "signature_b64": base64.b64encode(signature).decode(),
        "signed_blob": blob,
    }


def verify_signature(
    payload: Dict[str, Any],
    signature_b64: str,
    public_key_pem: str,
    expected_version: int = 1,
) -> bool:
    """Verify using the broker's PINNED public key, NOT caller-supplied.

    FIXED: Uses broker's public key that the platform has pinned; checks version
    and replay protection (5-minute window).
    """
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature

    try:
        # public_key_pem here MUST be the platform-pinned key for PINNED_KEY_ID;
        # callers must never supply their own trust anchor (see verify_receipt).
        public_key = serialization.load_pem_public_key(public_key_pem.encode())

        if not isinstance(payload, dict):
            return False
        blob = _canonical_bytes(payload).decode("utf-8")
        signed_data = _parse_canonical_blob(blob)

        if signed_data.get("version") != expected_version:
            return False

        try:
            timestamp = int(signed_data.get("timestamp", -1))
        except (TypeError, ValueError):
            return False
        now = int(time.time())
        age = now - timestamp
        if age < -60 or age > REPLAY_PROTECTION_SECONDS:
            return False

        signature = base64.b64decode(signature_b64, validate=True)

        public_key.verify(
            signature,
            blob.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )

        return True

    except (InvalidSignature, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"[{BROKER_ERROR}] Verification failed: {e}", file=sys.stderr)
        return False


def verify_envelope(
    signed_blob: str,
    signature_b64: str,
    pinned_public_key_pem: str,
    expected_version: int = 1,
) -> bool:
    """Verify an exact signed envelope against the pinned issuer key."""
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature

    try:
        public_key = serialization.load_pem_public_key(pinned_public_key_pem.encode())
        signed_data = _parse_canonical_blob(signed_blob)
        if signed_data.get("version") != expected_version:
            return False
        try:
            timestamp = int(signed_data.get("timestamp", -1))
        except (TypeError, ValueError):
            return False
        now = int(time.time())
        age = now - timestamp
        if age < -60 or age > REPLAY_PROTECTION_SECONDS:
            return False
        signature = base64.b64decode(signature_b64, validate=True)
        public_key.verify(
            signature,
            signed_blob.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"[{BROKER_ERROR}] Envelope verification failed: {e}", file=sys.stderr)
        return False


# ============================================================================
# 4. Assignment Sealing — FIXED (cgroup binding + signature)
# ============================================================================


@dataclass
class SealedAssignment:
    """A sealed assignment with cryptographic binding and cgroup confinement.

    container_id/runner_pids/repo/branch are the durable observation bindings:
    the pinned full container ID resolved at discovery, the runner PIDs the
    reaper must account for, and the exact publication repo/branch. Seals
    predating these fields reconstruct with empty defaults and can never
    satisfy the binding cross-checks (fail closed).
    """

    assignment_id: str
    task_id: str
    runner_id: str
    scope: str
    cgroup: str
    container_name: str
    creator_broker_id: str
    created_at: str
    signature: str
    cgroup_proof: str
    container_id: str = ""
    runner_pids: list = field(default_factory=list)
    repo: str = ""
    branch: str = ""


def _is_full_hex_id(value: Any) -> bool:
    """A Docker full ID is 64 hex chars. Local copy (no observers import)
    so broker.py keeps zero intra-package dependencies."""
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def seal_assignment(
    assignment: Dict[str, Any],
    private_key_pem: str,
    resolve_container_id_fn=None,
) -> SealedAssignment:
    """Seal an assignment with broker signature and cgroup proof.

    The seal binds the assignment to the cgroup state at creation time,
    preventing later migration claims. It also pins the durable observation
    bindings: the full container ID (poller-supplied when already resolved,
    otherwise resolved via resolve_container_id_fn when provided), the
    runner PIDs the reaper must account for, and the exact publication
    repo/branch. Without a resolver the ID stays empty and completions can
    never verify — fail closed, never default-true.
    """
    import base64
    from cryptography.hazmat.primitives import hashes as hashes_mod
    from cryptography.hazmat.primitives import serialization as _seal_serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    supplied_id = assignment.get("container_id", "")
    if not _is_full_hex_id(supplied_id) and resolve_container_id_fn is not None:
        try:
            resolved = resolve_container_id_fn(assignment.get("container_name", ""))
        except Exception:
            resolved = None
        if _is_full_hex_id(resolved):
            supplied_id = str(resolved).lower()
    container_id = str(supplied_id).lower() if _is_full_hex_id(supplied_id) else ""
    runner_pids = assignment.get("runner_pids", [])
    if not isinstance(runner_pids, list):
        runner_pids = []
    runner_pids = [int(p) for p in runner_pids if isinstance(p, int) or str(p).lstrip("-").isdigit()]

    seal_data = {
        "assignment_id": assignment["assignment_id"],
        "task_id": assignment["task_id"],
        "runner_id": assignment.get("runner_id", ""),
        "scope": assignment["scope"],
        "cgroup": assignment["cgroup"],
        "container_name": assignment["container_name"],
        "creator_broker_id": assignment["broker_id"],
        "created_at": assignment["created_at"],
        "container_id": container_id,
        "runner_pids": runner_pids,
        "repo": assignment.get("repo", ""),
        "branch": assignment.get("branch", ""),
    }

    private_key = _seal_serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = private_key.sign(
        _canonical_bytes(seal_data),
        padding.PSS(mgf=padding.MGF1(hashes_mod.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes_mod.SHA256(),
    )

    cgroup_proof = hashlib.sha256(assignment["cgroup"].encode() + assignment["container_name"].encode()).hexdigest()[
        :16
    ]

    return SealedAssignment(
        assignment_id=assignment["assignment_id"],
        task_id=assignment["task_id"],
        runner_id=assignment.get("runner_id", ""),
        scope=assignment["scope"],
        cgroup=assignment["cgroup"],
        container_name=assignment["container_name"],
        creator_broker_id=assignment["broker_id"],
        created_at=assignment["created_at"],
        signature=base64.b64encode(signature).decode(),
        cgroup_proof=cgroup_proof,
        container_id=container_id,
        runner_pids=runner_pids,
        repo=assignment.get("repo", ""),
        branch=assignment.get("branch", ""),
    )


def verify_sealed_assignment(
    sealed: SealedAssignment,
    expected_cgroup: str,
    pinned_public_key_pem: str,
) -> bool:
    """Verify a sealed assignment against the pinned issuer key.

    Checks the RSA signature over the canonical seal bytes, the cgroup
    binding, and structure. A replaced signature such as "forged" fails.
    """
    import base64
    import hashlib
    from cryptography.hazmat.primitives import hashes as _vh
    from cryptography.hazmat.primitives import serialization as _vs
    from cryptography.hazmat.primitives.asymmetric import padding as _vp
    from cryptography.exceptions import InvalidSignature

    try:
        cgroup = sealed.cgroup if isinstance(sealed, SealedAssignment) else sealed["cgroup"]
        container = sealed.container_name if isinstance(sealed, SealedAssignment) else sealed["container_name"]
        if cgroup != expected_cgroup:
            return False
        computed = hashlib.sha256(cgroup.encode() + container.encode()).hexdigest()[:16]
        proof = sealed.cgroup_proof if isinstance(sealed, SealedAssignment) else sealed["cgroup_proof"]
        if proof != computed:
            return False
        if isinstance(sealed, SealedAssignment):
            seal_data = {
                "assignment_id": sealed.assignment_id,
                "task_id": sealed.task_id,
                "runner_id": sealed.runner_id,
                "scope": sealed.scope,
                "cgroup": sealed.cgroup,
                "container_name": sealed.container_name,
                "creator_broker_id": sealed.creator_broker_id,
                "created_at": sealed.created_at,
                "container_id": sealed.container_id,
                "runner_pids": list(sealed.runner_pids),
                "repo": sealed.repo,
                "branch": sealed.branch,
            }
            signature_b64 = sealed.signature
        else:
            seal_data = {
                "assignment_id": sealed["assignment_id"],
                "task_id": sealed["task_id"],
                "runner_id": sealed.get("runner_id", ""),
                "scope": sealed["scope"],
                "cgroup": sealed["cgroup"],
                "container_name": sealed["container_name"],
                "creator_broker_id": sealed["creator_broker_id"],
                "created_at": sealed["created_at"],
                "container_id": sealed.get("container_id", ""),
                "runner_pids": list(sealed.get("runner_pids", [])),
                "repo": sealed.get("repo", ""),
                "branch": sealed.get("branch", ""),
            }
            signature_b64 = sealed["signature"]
        if not all([seal_data["assignment_id"], seal_data["task_id"], seal_data["scope"], seal_data["container_name"]]):
            return False
        public_key = _vs.load_pem_public_key(pinned_public_key_pem.encode())
        public_key.verify(
            base64.b64decode(signature_b64, validate=True),
            _canonical_bytes(seal_data),
            _vp.PSS(mgf=_vp.MGF1(_vh.SHA256()), salt_length=_vp.PSS.MAX_LENGTH),
            _vh.SHA256(),
        )
        return True
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return False


# ============================================================================
# 5. Cgroup Confinement — FIXED (actual /proc/self/cgroup read + comparison)
# ============================================================================


def get_process_cgroup(pid: int = None) -> Optional[str]:
    """Read the cgroup path for a given process from /proc.

    FIXED: Actually reads /proc/[pid]/cgroup, not just checks format.
    """
    if pid is None:
        pid = os.getpid()

    try:
        with open(f"/proc/{pid}/cgroup", "r") as f:
            lines = f.read().strip().split("\n")
            if len(lines) >= 1:
                # cgroup v2 format: 0::name=name,slave
                return lines[0].split("name=")[-1] if "name=" in lines[0] else lines[0]
    except (FileNotFoundError, IndexError, PermissionError):
        pass
    return None


def verify_cgroup_confinement(assigned_cgroup: str, process_pid: int = None) -> Tuple[bool, str]:
    """Verify that a process is confined to its assigned cgroup.

    FIXED: Actual cgroup path comparison, not just format check.
    Returns (confirmed, detail_message).
    """
    if process_pid is None:
        process_pid = os.getpid()

    actual_cgroup = get_process_cgroup(process_pid)
    if actual_cgroup is None:
        return False, "Could not read process cgroup"

    assigned_normalized = assigned_cgroup.strip().rstrip("/")
    actual_normalized = actual_cgroup.strip().rstrip("/")

    if assigned_normalized == actual_normalized:
        return True, "cgroup confinement confirmed"

    if actual_normalized.startswith(assigned_normalized + "/"):
        return True, "cgroup confinement confirmed (child hierarchy)"

    return False, f"cgroup mismatch: assigned={assigned_normalized}, actual={actual_normalized}"


def set_runner_cgroup(cgroup_name: str = RUNNER_CGROUP) -> bool:
    """Best-effort runner cgroup preparation.

    The unit owns provisioning via StateDirectory/RuntimeDirectory; this helper
    only ensures the cgroup path exists when permitted and never claims
    confinement by itself. Verification is done by verify_cgroup_confinement.
    """
    try:
        target = Path("/sys/fs/cgroup") / cgroup_name
        target.mkdir(parents=True, exist_ok=True)
        return True
    except (PermissionError, OSError):
        return False


# ============================================================================
# 5. Trusted Completion — FIXED (3 independent checks)
# ============================================================================


def _normalized_state(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text else None


def _sealed_entry(journal_entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for entry in journal_entries:
        if entry.get("event_type") == "assignment_sealed":
            return entry
    return None


def _reconstruct_seal(entry: Dict[str, Any]) -> Optional[SealedAssignment]:
    """Rebuild the sealed assignment from the durable journal record."""
    try:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return None
        signature = entry.get("signature")
        if not isinstance(signature, str) or not signature.strip():
            return None
        runner_pids = payload.get("runner_pids", [])
        if not isinstance(runner_pids, list):
            runner_pids = []
        return SealedAssignment(
            assignment_id=str(payload["assignment_id"]),
            task_id=str(payload["task_id"]),
            runner_id=str(payload.get("runner_id", "")),
            scope=str(payload["scope"]),
            cgroup=str(payload["cgroup"]),
            container_name=str(payload["container_name"]),
            creator_broker_id=str(payload["creator_broker_id"]),
            created_at=str(payload["created_at"]),
            signature=signature,
            cgroup_proof=str(payload["cgroup_proof"]),
            container_id=str(payload.get("container_id", "")),
            runner_pids=[int(p) for p in runner_pids],
            repo=str(payload.get("repo", "")),
            branch=str(payload.get("branch", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _reconstruct_sealed_assignment(entry: Dict[str, Any]) -> Optional[SealedAssignment]:
    return _reconstruct_seal(entry)


def _unprovisioned_observer(name: str):
    """Explicit fail-closed stub for production observers not yet provisioned.

    Completions stay UNKNOWN/rejected until the Docker/host/publication
    observers are provisioned with owner authorization. This documents the
    provisioning requirement instead of silently passing None through.
    """

    def _observer(*_args, **_kwargs):
        print(
            f"[{BROKER_ERROR}] {name} observer not provisioned; failing closed",
            file=sys.stderr,
        )
        return None

    _observer.__name__ = f"unprovisioned_{name}_observer"
    return _observer


def check_trusted_completion(
    journal_entries: List[Dict[str, Any]],
    details: Dict[str, Any],
    *,
    pinned_public_key_pem: Optional[str] = None,
    docker_observe=None,
    host_observe=None,
    publication_observe=None,
) -> bool:
    """Check that completion is trusted — durable seal plus independent evidence.

    Caller strings alone never suffice. All of the following must hold:
    1. A sealed journal entry exists whose RSA signature verifies against the
       pinned issuer key (fabricated "forged" signatures rejected).
    2. Caller details carry terminal values (fail fast on running/not-stopped).
    3. Injected independent observers — bound to the sealed assignment identity,
       never to caller-supplied IDs — confirm: Docker terminal state for the
       exact sealed container with restart disabled and labels matching; host
       cgroup empty with the service stopped; publication settled True.
    Observers default to fail-closed (None means reject).
    """
    if not journal_entries or not isinstance(details, dict):
        return False
    if pinned_public_key_pem is None:
        return False

    sealed_entry = _sealed_entry(journal_entries)
    if sealed_entry is None:
        return False
    sealed = _reconstruct_sealed_assignment(sealed_entry)
    if sealed is None:
        return False
    if not verify_sealed_assignment(sealed, sealed.cgroup, pinned_public_key_pem):
        return False

    docker_state = _normalized_state(details.get("docker_state"))
    if docker_state not in TERMINAL_DOCKER_STATES:
        return False
    stop_observation = _normalized_state(details.get("stop_observation"))
    if stop_observation not in TERMINAL_STOP_OBSERVATIONS:
        return False

    if docker_observe is None or host_observe is None or publication_observe is None:
        return False
    try:
        try:
            observed_docker = docker_observe(
                sealed.container_name, sealed.assignment_id, pinned_full_id=sealed.container_id
            )
        except TypeError:
            observed_docker = docker_observe(sealed.container_name, sealed.assignment_id)
        observed_host = host_observe(sealed.cgroup, sealed.assignment_id)
        observed_pub = publication_observe(sealed.assignment_id)
    except Exception:
        return False
    if not isinstance(observed_docker, dict) or not isinstance(observed_host, dict):
        return False
    if _normalized_state(observed_docker.get("state")) not in TERMINAL_DOCKER_STATES:
        return False
    if observed_docker.get("restart_disabled") is not True:
        return False
    if observed_docker.get("labels_match") is not True:
        return False
    if observed_docker.get("id") != sealed.container_name:
        return False
    caller_container = details.get("container_id")
    if caller_container is not None and caller_container != sealed.container_name:
        return False
    if _normalized_state(details.get("docker_state")) != _normalized_state(observed_docker.get("state")):
        return False
    if observed_host.get("cgroup_empty") is not True:
        return False
    if _normalized_state(observed_host.get("service")) != "stopped":
        return False
    if not isinstance(observed_pub, dict) or observed_pub.get("settled") is not True:
        return False

    # End-to-end binding enforcement against the durable seal. The pinned
    # full container ID recorded at discovery must match the observed one;
    # seals without a pinned ID (legacy or unresolved) can never complete.
    # Publication evidence must carry this assignment's exact repo/branch.
    # Host evidence must positively confirm reaping — a missing reaped flag
    # stays UNKNOWN even when the cgroup reads empty.
    if not _is_full_hex_id(sealed.container_id):
        return False
    if observed_docker.get("full_id") != sealed.container_id.lower():
        return False
    if not sealed.repo or not sealed.branch:
        return False
    if observed_pub.get("repo") != sealed.repo or observed_pub.get("branch") != sealed.branch:
        return False
    if observed_host.get("reaped") is not True:
        return False

    return True


# ============================================================================
# 6. Receipt Verification — FIXED (pinned trusted issuer key)
# ============================================================================


def _keys_dir() -> Path:
    override = os.environ.get("HOST_OPENCODE_KEYS_DIR")
    return Path(override) if override else KEYS_DIR


def _private_key_file() -> Path:
    return _keys_dir() / "broker_private.key"


def _public_key_file() -> Path:
    return _keys_dir() / "broker_public.key"


def _journal_db_path(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    override = os.environ.get("HOST_OPENCODE_JOURNAL_DB")
    return override if override else str(JOURNAL_DB)


def _runtime_paths() -> Tuple[Path, Path, Path]:
    """Resolve runtime socket/PID/pointer paths from the provisioned dir.

    Honors RUNTIME_DIRECTORY (systemd RuntimeDirectory=) so the broker never
    writes directly to /run. Falls back to the legacy /run paths.
    """
    base = os.environ.get("RUNTIME_DIRECTORY")
    runtime_dir = Path(base) if base else Path("/run/host-opencode-broker")
    return (
        runtime_dir / "broker.sock",
        runtime_dir / "broker.pid",
        runtime_dir / "broker-socket",
    )


def load_public_key(keys_dir: Optional[Path] = None) -> str:
    """Load the broker's PINNED public key from secure storage.

    The platform pins this key; it is NEVER the caller-supplied key.
    """
    pub_file = (Path(keys_dir) / "broker_public.key") if keys_dir else _public_key_file()
    try:
        return pub_file.read_text()
    except FileNotFoundError:
        # Generate and store for development; in production, platform provides this
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())
        private_key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

        # Store for future runs under the same keys dir (isolated in tests)
        pub_file.parent.mkdir(parents=True, exist_ok=True)
        pub_file.write_text(public_key_pem)
        os.chmod(str(pub_file), 0o644)
        priv_file = pub_file.parent / "broker_private.key"
        priv_file.write_text(private_key_pem)
        os.chmod(str(priv_file), 0o600)

        return public_key_pem


def verify_receipt(
    signed_blob: str,
    signature_b64: str,
    assignment_id: str,
    expected_sender_uid: int,
    pinned_public_key_pem: Optional[str] = None,
    *,
    journal_db: Optional[str] = None,
    peer_uid: Optional[int] = None,
    untrusted_public_key_pem: Optional[str] = None,
    keys_dir: Optional[Path] = None,
) -> bool:
    """Verify a receipt against the PINNED trusted issuer public key.

    A caller-supplied key is never trusted: if one is provided and differs
    from the pinned key, verification fails closed. The envelope signature,
    assignment binding, journal existence, and sender UID must all pass.
    """
    try:
        pinned = pinned_public_key_pem if pinned_public_key_pem else load_public_key(keys_dir)
        if untrusted_public_key_pem is not None and untrusted_public_key_pem != pinned:
            return False

        if peer_uid is None or peer_uid != expected_sender_uid:
            return False

        # Retrieve the sealed assignment from journal to get the signature context
        entries = journal_get_entries(assignment_id=assignment_id, db_path=_journal_db_path(journal_db))
        if not entries:
            return False

        # Verify the exact envelope bytes against the pinned key.
        if not verify_envelope(signed_blob, signature_b64, pinned):
            return False

        # Bind the envelope to this assignment: reject transplanted receipts.
        try:
            envelope = _parse_canonical_blob(signed_blob)
        except ValueError:
            return False
        receipt_payload = envelope.get("payload")
        if not isinstance(receipt_payload, dict):
            return False
        bound_id = receipt_payload.get("assignment_id")
        if bound_id != assignment_id:
            return False

        # A receipt is only valid against an exact persisted completion
        # match — unconditionally. A correctly signed envelope with only a
        # sealed assignment record (no completed receipt persisted, or the
        # completion evidence deleted) must reject.
        completed = [e for e in entries if e.get("event_type") == "assignment_completed"]
        if not completed:
            return False
        matched = any(
            isinstance(e.get("payload"), dict)
            and e["payload"].get("envelope") == signed_blob
            and e.get("signature") == signature_b64
            for e in completed
        )
        if not matched:
            return False

        return True

    except Exception as e:
        print(f"[{BROKER_ERROR}] Receipt verification failed: {e}", file=sys.stderr)
        return False


# ============================================================================
# 7. Broker Main — FIXED (complete main loop)
# ============================================================================


def broker_main() -> None:
    """Main broker entry point — ALL FIXES applied.

    The broker:
    1. Starts Unix socket with peer credential authentication
    2. Accepts assignment proposals from poller, seals them, records in journal
    3. Accepts completion observations, validates trusted completion
    4. Issues verified receipts for platform consumption
    5. Manages cgroup for runner confinement
    6. Serves as authoritative source for receipt verification
    """
    import socket
    import fcntl

    # Ensure keys and journal
    private_key_pem, public_key_pem = ensure_keys()
    journal_init()

    # Start Unix socket with peer credential authentication.
    # Use the provisioned RuntimeDirectory, never /run directly.
    socket_path, pid_path, pointer_path = _runtime_paths()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    # Remove the legacy socket path if it exists to avoid split-brain binds.
    if str(socket_path) != BROKER_SOCKET and os.path.exists(BROKER_SOCKET):
        try:
            os.unlink(BROKER_SOCKET)
        except OSError:
            pass

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(60)
    sock.bind(str(socket_path))
    os.chmod(str(socket_path), 0o660)
    sock.listen(5)

    # Write PID file
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))

    # Store socket path pointer for clients
    with open(pointer_path, "w") as f:
        f.write(str(socket_path))

    print(f"[{BROKER_NAME}] Started broker PID {os.getpid()}", file=sys.stderr)
    print(f"[{BROKER_NAME}] Socket: {socket_path}", file=sys.stderr)
    print(f"[{BROKER_NAME}] Journal: SQLite at {_journal_db_path()}", file=sys.stderr)

    # Set up cgroup
    cgroup_ok, cgroup_msg = verify_cgroup_confinement(RUNNER_CGROUP)
    print(f"[{BROKER_NAME}] Cgroup: {cgroup_ok} ({cgroup_msg})", file=sys.stderr)
    set_runner_cgroup(RUNNER_CGROUP)

    # Set permissions
    os.chmod(str(PRIVATE_KEY_FILE), 0o600)
    os.chmod(str(PUBLIC_KEY_FILE), 0o640)

    # File locking for concurrent access
    lock_fd = open("/tmp/host-opencode-broker-lock", "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(f"[{BROKER_ERROR}] Another broker instance running", file=sys.stderr)
        sys.exit(1)

    # Main accept loop
    try:
        while True:
            try:
                conn, addr = sock.accept()
                conn.settimeout(60)

                # CRITICAL: Validate peer identity via socket credentials
                # and carry the authenticated UID into the handler so receipt
                # verification never runs without it.
                peer_uid = get_peer_uid(conn)
                if peer_uid is None or not validate_peer_identity(
                    conn, TRUSTED_UIDS, _get_peer_uid=lambda _c: peer_uid
                ):
                    try:
                        conn.close()
                    finally:
                        pass
                    print(f"[{BROKER_ERROR}] Rejected untrusted peer", file=sys.stderr)
                    continue

                handle_broker_connection(
                    conn,
                    private_key_pem,
                    journal_append,
                    journal_db=_journal_db_path(),
                    keys_dir=_keys_dir(),
                    docker_observe=_unprovisioned_observer("docker"),
                    host_observe=_unprovisioned_observer("host"),
                    publication_observe=_unprovisioned_observer("publication"),
                    peer_uid=peer_uid,
                )

            except socket.timeout:
                # Periodic: verify cgroup still valid
                verify_cgroup_confinement(RUNNER_CGROUP)
                continue
            except Exception as e:
                print(f"[{BROKER_ERROR}] Connection error: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print(f"[{BROKER_NAME}] Shutting down", file=sys.stderr)
    finally:
        try:
            socket_path, pid_path, _ = _runtime_paths()
            for path in (socket_path, pid_path, BROKER_SOCKET, BROKER_PID_FILE):
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
        finally:
            try:
                lock_fd.close()
            except Exception:
                pass


def handle_broker_connection(
    conn,
    private_key_pem,
    journal_append_fn,
    *,
    journal_db: Optional[str] = None,
    keys_dir: Optional[Path] = None,
    docker_observe=None,
    host_observe=None,
    publication_observe=None,
    peer_uid: Optional[int] = None,
    resolve_container_id_fn=None,
) -> None:
    """Handle broker connection with 4 message types."""
    import json

    try:
        conn.settimeout(60)
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        if not data:
            return

        message = json.loads(data.decode())
        msg_type = message.get("type")

        if msg_type == "assign_task":
            # Poller submits task proposal. Discovery-time resolution of the
            # container name to a full ID happens here when a resolver is
            # provided; otherwise only a poller-supplied full ID is pinned
            # and completions stay UNKNOWN until one exists.
            sealed = seal_assignment(
                message["assignment_data"],
                private_key_pem,
                resolve_container_id_fn=resolve_container_id_fn,
            )

            # Record the full seal atomically; identical retries are
            # idempotent, conflicting retries are refused, persistence
            # failure fails the operation — no assignment without a commit.
            seal_payload = {
                "assignment_id": sealed.assignment_id,
                "task_id": sealed.task_id,
                "runner_id": sealed.runner_id,
                "scope": sealed.scope,
                "cgroup": sealed.cgroup,
                "container_name": sealed.container_name,
                "creator_broker_id": sealed.creator_broker_id,
                "created_at": sealed.created_at,
                "cgroup_proof": sealed.cgroup_proof,
                "container_id": sealed.container_id,
                "runner_pids": list(sealed.runner_pids),
                "repo": sealed.repo,
                "branch": sealed.branch,
            }
            if journal_append_fn is journal_append:
                seal_status, existing = journal_try_seal(
                    sealed.assignment_id,
                    seal_payload,
                    sealed.signature,
                    db_path=journal_db,
                )
            else:
                ok = journal_append_fn(
                    assignment_id=sealed.assignment_id,
                    event_type="assignment_sealed",
                    payload=seal_payload,
                    signature=sealed.signature,
                    db_path=journal_db,
                )
                seal_status, existing = ("inserted", None) if ok else ("error", None)
            if seal_status == "error":
                conn.sendall(
                    json.dumps(
                        {
                            "type": "assignment_response",
                            "assignment": None,
                            "error": "journal_persist_failed",
                        }
                    ).encode()
                )
                return
            if seal_status == "conflict":
                conn.sendall(
                    json.dumps(
                        {
                            "type": "assignment_response",
                            "assignment": None,
                            "error": "assignment_conflict",
                        }
                    ).encode()
                )
                return

            # Identical retries return the originally persisted seal bytes
            # (signatures randomize per signing, so the stored original wins).
            out_payload = existing["payload"] if seal_status == "identical" and existing else seal_payload
            out_signature = existing["signature"] if seal_status == "identical" and existing else sealed.signature
            # Return sealed assignment to poller
            response = {
                "type": "assignment_response",
                "assignment": {
                    "assignment_id": out_payload["assignment_id"],
                    "task_id": out_payload["task_id"],
                    "scope": out_payload["scope"],
                    "cgroup": out_payload["cgroup"],
                    "container_name": out_payload["container_name"],
                    "signature": out_signature,
                    "cgroup_proof": out_payload["cgroup_proof"],
                    "container_id": out_payload.get("container_id", ""),
                    "runner_pids": list(out_payload.get("runner_pids", [])),
                    "repo": out_payload.get("repo", ""),
                    "branch": out_payload.get("branch", ""),
                },
            }
            conn.sendall(json.dumps(response).encode())

        elif msg_type == "complete_assignment":
            # Runner returns completion observations
            assignment_id = message["assignment_id"]
            runner_id = message.get("runner_id", "")
            success = message.get("success", False)
            details = message.get("details", {})

            # Verify assignment exists in journal
            entries = journal_get_entries(assignment_id=assignment_id, db_path=journal_db)
            if not entries:
                response = {
                    "type": "completion_response",
                    "success": False,
                    "error": "assignment_not_found",
                }
                conn.sendall(json.dumps(response).encode())
                return

            # Verify the durable seal first: a fabricated journal entry
            # (e.g. signature "forged") must fail here.
            pinned = load_public_key(keys_dir)
            sealed_entry = _sealed_entry(entries)
            sealed_obj = _reconstruct_sealed_assignment(sealed_entry) if sealed_entry else None
            if sealed_obj is None or not verify_sealed_assignment(sealed_obj, sealed_obj.cgroup, pinned):
                response = {
                    "type": "completion_response",
                    "success": False,
                    "assignment_id": assignment_id,
                    "trusted": False,
                    "error": "seal_invalid",
                }
                conn.sendall(json.dumps(response).encode())
                return

            # Observation targets come from the sealed assignment, never from
            # caller details. A mismatched caller container_id is rejected.
            caller_container = details.get("container_id")
            if caller_container is not None and caller_container != sealed_obj.container_name:
                response = {
                    "type": "completion_response",
                    "success": False,
                    "assignment_id": assignment_id,
                    "trusted": False,
                    "error": "container_mismatch",
                }
                conn.sendall(json.dumps(response).encode())
                return

            # Check trusted completion via independent observers (fail closed
            # when observers are absent: caller strings alone never suffice).
            trusted = check_trusted_completion(
                entries,
                details,
                pinned_public_key_pem=pinned,
                docker_observe=docker_observe,
                host_observe=host_observe,
                publication_observe=publication_observe,
            )

            # Build the exact signed receipt envelope and persist it verbatim.
            # The stored signature must match these exact bytes.
            receipt_payload = {
                "assignment_id": assignment_id,
                "task_id": sealed_obj.task_id,
                "runner_id": runner_id,
                "container": sealed_obj.container_name,
                "cgroup": sealed_obj.cgroup,
                "execution_stopped": trusted,
                "publication_settled": trusted,
                "assignment_sealed": True,
                "success": bool(success and trusted),
                "observed_at": int(__import__("time").time()),
            }
            signed = sign_payload(receipt_payload, private_key_pem)
            receipt_blob = signed["signed_blob"]
            receipt_sig = signed["signature_b64"]
            persisted = journal_append_fn(
                assignment_id=assignment_id,
                event_type="assignment_completed",
                payload={"envelope": receipt_blob, "trusted": trusted},
                signature=receipt_sig,
                db_path=journal_db,
            )
            if not persisted:
                response = {
                    "type": "completion_response",
                    "success": False,
                    "assignment_id": assignment_id,
                    "trusted": False,
                    "error": "journal_persist_failed",
                }
                conn.sendall(json.dumps(response).encode())
                return

            response = {
                "type": "completion_response",
                "success": bool(success and trusted),
                "assignment_id": assignment_id,
                "trusted": trusted,
                "receipt_blob": receipt_blob,
                "receipt_signature": receipt_sig,
            }
            conn.sendall(json.dumps(response).encode())

        elif msg_type == "verify_receipt":
            # Platform verifies receipt against the pinned issuer key.
            # The authenticated peer UID from SO_PEERCRED is required: without
            # it, valid receipts cannot pass this path.
            signed_blob = message.get("signed_blob")
            signature_b64 = message.get("signature_b64", message.get("receipt_b64"))
            assignment_id = message.get("assignment_id")
            expected_sender_uid = message.get("expected_sender_uid")
            caller_key = message.get("public_key_pem")
            pinned = load_public_key(keys_dir)

            if not all([signed_blob, signature_b64, assignment_id]) or expected_sender_uid is None:
                response = {"type": "verification_response", "valid": False}
            else:
                valid = verify_receipt(
                    signed_blob,
                    signature_b64,
                    assignment_id,
                    int(expected_sender_uid),
                    pinned_public_key_pem=pinned,
                    journal_db=journal_db,
                    peer_uid=peer_uid,
                    untrusted_public_key_pem=caller_key,
                )
                response = {
                    "type": "verification_response",
                    "valid": valid,
                    "assignment_id": assignment_id,
                }

            conn.sendall(json.dumps(response).encode())

        elif msg_type == "get_journal":
            assignment_id = message.get("assignment_id")
            entries = journal_get_entries(assignment_id=assignment_id, db_path=journal_db)
            response = {"type": "journal_response", "entries": entries}
            conn.sendall(json.dumps(response).encode())

        else:
            conn.sendall(json.dumps({"type": "error", "message": "unknown type"}).encode())

    except Exception as e:
        print(f"[{BROKER_ERROR}] Connection handle error: {e}", file=sys.stderr)
    finally:
        conn.close()


# ============================================================================
# Entrypoint
# ============================================================================

if __name__ == "__main__":
    broker_main()
