"""
HMAC signing for governance_audit_log entries (task #3273).

Canonical payload: pipe-joined fields — NULL fields become empty string.
  {id}|{event_type}|{event_category}|{agent_id}|{user_id}|{action}
     |{target_table}|{target_id}|{outcome}|{timestamp_iso}

Key source: CREED_AUDIT_HMAC_KEY env var.
Graceful degradation: if key is not set, returns None — callers store NULL and
rows are counted as "unverified" (not "invalid") by the verify endpoint.
"""

import hashlib
import hmac
import os
from typing import Optional


def _get_key() -> Optional[bytes]:
    raw = os.environ.get("CREED_AUDIT_HMAC_KEY", "").strip()
    return raw.encode("utf-8") if raw else None


def sign_event(
    event_id: int,
    event_type: Optional[str],
    event_category: Optional[str],
    agent_id,
    user_id,
    action: Optional[str],
    target_table: Optional[str],
    target_id,
    outcome: Optional[str],
    timestamp_iso: str,
) -> Optional[str]:
    """Compute HMAC-SHA256 for a governance_audit_log row. Returns hex string or None."""
    key = _get_key()
    if not key:
        return None

    def s(v) -> str:
        return "" if v is None else str(v)

    parts = [
        s(event_id),
        s(event_type),
        s(event_category),
        s(agent_id),
        s(user_id),
        s(action),
        s(target_table),
        s(target_id),
        s(outcome),
        s(timestamp_iso),
    ]
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_event(row: dict) -> Optional[bool]:
    """
    Verify the HMAC of a row dict fetched from governance_audit_log.
    Returns True  = valid signature
            False = invalid signature (tampered)
            None  = no key configured or hmac_sig is NULL (unverified, not invalid)
    """
    stored_sig = row.get("hmac_sig")
    if not stored_sig:
        return None

    key = _get_key()
    if not key:
        return None

    ts = row.get("timestamp")
    timestamp_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")

    expected = sign_event(
        event_id=row.get("id"),
        event_type=row.get("event_type"),
        event_category=row.get("event_category"),
        agent_id=row.get("agent_id"),
        user_id=row.get("user_id"),
        action=row.get("action"),
        target_table=row.get("target_table"),
        target_id=row.get("target_id"),
        outcome=row.get("outcome"),
        timestamp_iso=timestamp_iso,
    )
    if expected is None:
        return None
    # Constant-time comparison prevents timing attacks
    return hmac.compare_digest(expected, stored_sig)
