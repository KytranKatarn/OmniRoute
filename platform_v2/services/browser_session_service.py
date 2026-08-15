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


def record_probe(agent_id: int, platform: str, ok: bool, reason: str = None, logged_out: bool = False) -> None:
    """Stamp a health-probe result (#3708 phase 2, hardened #4372, precedence fixed #5627).

    Outcomes, evaluated in THIS ORDER — the order is the whole point:

    • logged_out=True      → status='stale', REGARDLESS of ok. A POSITIVE logged-out signal
      (the skill landed on a login/authwall — skill_runner surfaces result['logged_out']) is
      the ONLY trustworthy "this profile is dead" signal, and 'stale' is the ONLY thing that
      gates the calendar.
    • ok=True              → status='active', last_probe_ok=TRUE (clears reason). Idempotent,
      so a profile that latched 'stale' on a past transient recovers on the next good probe.
    • ok=False, transient  → a timeout / lock-busy / generic probe error is NOT proof of
      logout. Stamp last_probe_at + reason but KEEP the last-good status + last_probe_ok, so
      a momentary blip can no longer false-gate posting for a profile whose cookies are valid
      (this was the #4372 false-negative that paused the whole calendar).

    ⚠️ #5627 — WHY logged_out IS CHECKED FIRST. A READ skill reports success when it reads
    *a* page; if that page IS the login wall it returns BOTH success=True AND logged_out=True.
    Measured live on agent 342: `linkedin_feed` → {'success': True, 'logged_out': True}. Under
    the old `if ok:` -first ordering the weaker signal won, the branch below became dead code
    for the only case that actually occurs in production, and a logged-out profile was
    re-stamped 'active' on every probe AND every keep-warm. `_linkedin_profile_healthy()` then
    read 'active', the #1831 release guard never fired, and posts were released into a dead
    profile — the exact pile-up #1831 exists to prevent (5 failed posts on 2026-08-15).
    A more specific signal must always outrank a more general one."""
    with get_db_cursor(commit=True) as (_conn, cur):
        if logged_out:
            cur.execute(
                """UPDATE browser_sessions
                      SET last_probe_at = NOW(), last_probe_ok = FALSE,
                          status = 'stale',
                          last_failure_reason = %s, updated_at = NOW()
                    WHERE agent_id = %s AND platform = %s""",
                (reason or "logged out", agent_id, platform),
            )
        elif ok:
            cur.execute(
                """UPDATE browser_sessions
                      SET last_probe_at = NOW(), last_probe_ok = TRUE,
                          status = 'active',
                          last_failure_reason = NULL, updated_at = NOW()
                    WHERE agent_id = %s AND platform = %s""",
                (agent_id, platform),
            )
        else:
            cur.execute(
                """UPDATE browser_sessions
                      SET last_probe_at = NOW(),
                          last_failure_reason = %s, updated_at = NOW()
                    WHERE agent_id = %s AND platform = %s""",
                (reason or "transient probe failure", agent_id, platform),
            )


def is_known_logged_out(agent_id: int, platform: str) -> bool:
    """True ONLY when we POSITIVELY know this profile is logged out (#5627).

    Fail-OPEN by design (no row / unknown status / any error → False): a health-read bug
    must never block posting. This is the mirror of signal_calendar_service.
    _linkedin_profile_healthy(), exposed here so the agent_loop executor — the single
    choke point all six linkedin_post producers funnel through — can gate without
    importing platform-module internals.
    """
    try:
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute(
                "SELECT status FROM browser_sessions WHERE agent_id = %s AND platform = %s LIMIT 1",
                (agent_id, platform),
            )
            row = cur.fetchone()
            if not row:
                return False
            status = (row["status"] if isinstance(row, dict) else row[0]) or ""
            return status == "stale"
    except Exception as exc:
        logger.debug("is_known_logged_out failed (fail-open False): %s", exc)
        return False


def list_active_sessions() -> list:
    """(agent_id, platform) for every active session — drives the probe job."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT agent_id, platform FROM browser_sessions WHERE status = 'active'")
        return [(r["agent_id"], r["platform"]) for r in cur.fetchall()]


def list_sessions_for_probe() -> list:
    """(agent_id, platform) for every ACTIVE or STALE session. Stale rows are INCLUDED
    so a recovered profile re-probes and flips back to active (record_probe ok=True →
    active). Without re-probing stale rows, a session that once went stale would latch
    stale forever and never recover (#4372)."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT agent_id, platform FROM browser_sessions WHERE status IN ('active', 'stale')")
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


# ── Egress preference (#4007) ──────────────────────────────────────────
# Which country/outpost a session's authenticated fetches egress through.
# NULL/'hub'/'auto' = hub direct. Stored value is a remote_nodes.node_name.
# Resolution is preference-not-pin (the scraper falls back to hub).

_HUB_EGRESS = {None, "", "hub", "auto"}


def get_session_egress(agent_id: int, platform: str) -> Optional[str]:
    """Return the session's egress_pref, or None (= hub direct)."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT egress_pref FROM browser_sessions WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )
        row = cur.fetchone()
    pref = row["egress_pref"] if row else None
    return None if pref in _HUB_EGRESS else pref


def set_session_egress(agent_id: int, platform: str, pref: Optional[str]) -> bool:
    """Set (or clear, when pref is hub/auto/None) the session's egress
    preference. Returns False if no session row matched."""
    value = None if (pref or "").strip().lower() in _HUB_EGRESS else pref.strip()
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE browser_sessions
                  SET egress_pref = %s, updated_at = NOW()
                WHERE agent_id = %s AND platform = %s""",
            (value, agent_id, platform),
        )
        return cur.rowcount > 0
