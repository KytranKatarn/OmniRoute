"""Browser session lifecycle service (Layer A Phase 1).

Single source of truth for browser_sessions row I/O + state encryption.
Replaces archie-browser/session_manager.py's on-disk JSON storage with
DB-backed encrypted blobs. Used by:
  - archie-browser/session_manager.load_session() via platform HTTP API
  - tools/department_hq/session_routes (cookie-paste endpoint, GET state)
  - (Phase 2) probe job
  - (Phase 3) reactive layer
  - (Phase 4) defer worker
  - (Phase 6) DHQ Connected Accounts tab
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# 32-byte AES-256 key. Must be present in env. The hex-encoded value is
# treated as the raw bytes per existing platform convention.
_KEY_HEX = os.getenv("BROWSER_ENCRYPTION_KEY", "")


def _key() -> bytes:
    if not _KEY_HEX:
        raise RuntimeError("BROWSER_ENCRYPTION_KEY env var not set")
    if len(_KEY_HEX) == 64:
        return bytes.fromhex(_KEY_HEX)
    # Permissive fallback — pad/truncate UTF-8 bytes to 32
    raw = _KEY_HEX.encode("utf-8")
    return (raw + b"\x00" * 32)[:32]


def encrypt_state(state: Dict[str, Any]) -> bytes:
    """Encrypt a Playwright storage_state dict to opaque bytes."""
    plaintext = json.dumps(state, ensure_ascii=False).encode("utf-8")
    aes = AESGCM(_key())
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # caller stores as one BYTEA column


def decrypt_state(blob: bytes) -> Dict[str, Any]:
    """Decrypt a previously-encrypted state blob."""
    nonce, ciphertext = blob[:12], blob[12:]
    aes = AESGCM(_key())
    plaintext = aes.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


from database import get_db_cursor  # noqa: E402 — after crypto primitives


def save_session(
    agent_id: int,
    platform: str,
    state: Dict[str, Any],
    status: str = "active",
) -> Dict[str, Any]:
    """Upsert a browser session row. Encrypts state, marks status."""
    encrypted = encrypt_state(state)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """INSERT INTO browser_sessions
                   (agent_id, platform, status, encrypted_state, last_used_at, updated_at)
               VALUES (%s, %s, %s, %s, NOW(), NOW())
               ON CONFLICT (agent_id, platform) DO UPDATE SET
                   status = EXCLUDED.status,
                   encrypted_state = EXCLUDED.encrypted_state,
                   last_used_at = NOW(),
                   last_failure_reason = NULL,
                   updated_at = NOW()
               RETURNING id""",
            (agent_id, platform, status, encrypted),
        )
        row = cur.fetchone()
    return {"success": True, "id": row["id"] if row else None}


def load_session(agent_id: int, platform: str) -> Optional[Dict[str, Any]]:
    """Load decrypted state for active session; return None otherwise.

    Bumps last_used_at on read so probe + DHQ visibility know it's in use.
    """
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """SELECT id, status, encrypted_state
                 FROM browser_sessions
                WHERE agent_id = %s AND platform = %s""",
            (agent_id, platform),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["status"] != "active":
            return None
        if not row["encrypted_state"]:
            return None
        cur.execute(
            "UPDATE browser_sessions SET last_used_at = NOW(), updated_at = NOW() WHERE id = %s",
            (row["id"],),
        )
    return decrypt_state(bytes(row["encrypted_state"]))


def record_probe(agent_id: int, platform: str, ok: bool, reason: str = None) -> None:
    """Stamp a health-probe result (#3708 phase 2). On failure also flips the
    session to 'stale' so skills stop trusting it; on success clears the
    failure reason without touching an already-imported active state."""
    with get_db_cursor(commit=True) as (_conn, cur):
        if ok:
            cur.execute(
                """UPDATE browser_sessions
                      SET last_probe_at = NOW(), last_probe_ok = TRUE,
                          last_failure_reason = NULL, updated_at = NOW()
                    WHERE agent_id = %s AND platform = %s""",
                (agent_id, platform),
            )
        else:
            cur.execute(
                """UPDATE browser_sessions
                      SET last_probe_at = NOW(), last_probe_ok = FALSE,
                          status = 'stale',
                          last_failure_reason = %s, updated_at = NOW()
                    WHERE agent_id = %s AND platform = %s""",
                (reason or "probe failed", agent_id, platform),
            )


def list_active_sessions() -> list:
    """(agent_id, platform) for every active session — drives the probe job."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT agent_id, platform FROM browser_sessions WHERE status = 'active'"
        )
        return [(r["agent_id"], r["platform"]) for r in cur.fetchall()]


def mark_stale(agent_id: int, platform: str, reason: str) -> None:
    """Mark a session as stale with a failure reason."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE browser_sessions
                  SET status = 'stale',
                      last_failure_reason = %s,
                      updated_at = NOW()
                WHERE agent_id = %s AND platform = %s""",
            (reason, agent_id, platform),
        )


def mark_active(agent_id: int, platform: str) -> None:
    """Mark a session as active and clear any failure reason."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE browser_sessions
                  SET status = 'active',
                      last_failure_reason = NULL,
                      updated_at = NOW()
                WHERE agent_id = %s AND platform = %s""",
            (agent_id, platform),
        )
