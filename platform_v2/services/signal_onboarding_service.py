"""S.I.G.N.A.L. account onboarding state machine (S7-P6.5a).

A new LinkedIn account walks a FORWARD-ONLY state machine on its agent_platform_accounts
row before it may post/engage:

    created -> business_email_set -> credentials_stored -> profile_logged_in
            -> company_joined -> skills_enabled -> active

The two OWNER-GATED steps cannot be auto-advanced — they need a human:
  * profile_logged_in  — the one-time noVNC headed login (S.C.O.U.T. session flow)
  * company_joined     — the owner supplies a phone + 2FA to join the company page

This module owns the state + the (forward-only) transition rules; the DHQ Accounts panel
(S7-P6.5b) drives it. Dormant until platform_settings signal:onboarding_enabled (default
off); the 4 live accounts were backfilled to 'active' by migration 444, so the state column
never strands a live poster.
"""

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Forward-only order.
STATES = [
    "created",
    "business_email_set",
    "credentials_stored",
    "profile_logged_in",
    "company_joined",
    "skills_enabled",
    "active",
]
_INDEX = {s: i for i, s in enumerate(STATES)}

# Steps that require an explicit owner action (never auto-advanced by code).
OWNER_GATED = {"profile_logged_in", "company_joined"}


def is_enabled() -> bool:
    """signal:onboarding_enabled (default off). The state machine is inert until flipped."""
    try:
        with get_db_cursor() as (_c, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key=%s", ("signal:onboarding_enabled",))
            r = cur.fetchone()
        raw = (r["value"] if isinstance(r, dict) else r[0]) if r else None
        return str(raw or "").strip().lower() in ("true", "1", "on", "yes")
    except Exception:
        return False


def state_for(account_key: str):
    """Current onboarding_state, or None if the account does not exist."""
    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT onboarding_state FROM agent_platform_accounts WHERE account_key=%s", (account_key,))
        r = cur.fetchone()
    if not r:
        return None
    return (r["onboarding_state"] if isinstance(r, dict) else r[0]) or "created"


def can_transition(frm: str, to: str) -> bool:
    """Forward-only: `to` must be a strictly LATER state than `frm` (forward skips allowed,
    backward never)."""
    if frm not in _INDEX or to not in _INDEX:
        return False
    return _INDEX[to] > _INDEX[frm]


def validate_business_email(email: str) -> bool:
    """A loose business-email shape check (real verification is the email-code step)."""
    import re

    email = (email or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False
    # Reject the common free providers — supporting accounts use a business email.
    free = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com"}
    return email.rsplit("@", 1)[-1].lower() not in free


def _valid_phone(phone: str) -> bool:
    """A plausible E.164-ish phone for the owner-gate 2FA: optional leading +, 7-15 digits
    once separators are stripped. (The owner supplies it; this catches typos early so a
    malformed number never silently breaks the company-join 2FA step.)"""
    import re

    digits = re.sub(r"[\s().\-]", "", phone or "")
    return bool(re.match(r"^\+?\d{7,15}$", digits))


def _encrypt_phone(phone: str) -> str:
    """Encrypt the owner-gate phone with the same Fernet key the browser session vault uses.
    No key configured (dev) → store as-is."""
    try:
        import os

        from cryptography.fernet import Fernet

        key = os.getenv("BROWSER_ENCRYPTION_KEY", "")
        if not key:
            return phone
        return Fernet(key.encode() if isinstance(key, str) else key).encrypt(phone.encode()).decode()
    except Exception as e:
        logger.warning("owner-gate phone encrypt failed (storing plain): %s", e)
        return phone


def transition(account_key: str, to_state: str, owner_gate_phone: str = None, actor: str = "claude") -> dict:
    """Forward-only transition of an account's onboarding_state. Returns
    {ok, state, from} or {ok:False, error}. Audit-logged."""
    cur_state = state_for(account_key)
    if cur_state is None:
        return {"ok": False, "error": f"no account '{account_key}'"}
    if to_state not in _INDEX:
        return {"ok": False, "error": f"unknown state '{to_state}'"}
    if not can_transition(cur_state, to_state):
        return {"ok": False, "error": f"illegal transition {cur_state} -> {to_state} (forward-only)"}
    if owner_gate_phone is not None:
        owner_gate_phone = str(owner_gate_phone).strip() or None
        if owner_gate_phone and not _valid_phone(owner_gate_phone):
            return {"ok": False, "error": "owner_gate_phone must be a valid phone (E.164-ish: optional +, 7-15 digits)"}
    if to_state == "company_joined" and not owner_gate_phone and not _has_owner_phone(account_key):
        return {"ok": False, "error": "company_joined requires an owner-gate phone (2FA)"}

    sets, params = ["onboarding_state = %s"], [to_state]
    if owner_gate_phone:
        sets.append("owner_gate_phone = %s")
        params.append(_encrypt_phone(owner_gate_phone))
    if to_state == "active":
        sets.append("onboarded_at = NOW()")
    params.append(account_key)

    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute(f"UPDATE agent_platform_accounts SET {', '.join(sets)} WHERE account_key=%s", params)

    # Invalidate the resolver cache so can_post/can_engage reads see the new state.
    try:
        from services import signal_accounts

        signal_accounts.invalidate()
    except Exception:
        pass
    logger.info("[onboarding] %s: %s -> %s (by %s)", account_key, cur_state, to_state, actor)
    return {"ok": True, "state": to_state, "from": cur_state}


def _has_owner_phone(account_key: str) -> bool:
    with get_db_cursor() as (_c, cur):
        cur.execute(
            "SELECT 1 FROM agent_platform_accounts WHERE account_key=%s AND owner_gate_phone IS NOT NULL",
            (account_key,),
        )
        return cur.fetchone() is not None


def onboarding_overview() -> list:
    """All accounts with their onboarding state + whether the next step is owner-gated —
    drives the DHQ Accounts panel (S7-P6.5b). Phone contents NEVER leave the server."""
    out = []
    with get_db_cursor() as (_c, cur):
        cur.execute(
            "SELECT account_key, role, onboarding_state, "
            "       (owner_gate_phone IS NOT NULL) AS has_owner_phone, onboarded_at "
            "FROM agent_platform_accounts ORDER BY account_key"
        )
        for r in cur.fetchall():
            row = (
                dict(r)
                if isinstance(r, dict)
                else {
                    "account_key": r[0],
                    "role": r[1],
                    "onboarding_state": r[2],
                    "has_owner_phone": r[3],
                    "onboarded_at": r[4],
                }
            )
            state = row.get("onboarding_state") or "created"
            idx = _INDEX.get(state, 0)
            row["next_state"] = STATES[idx + 1] if idx + 1 < len(STATES) else None
            row["next_owner_gated"] = row["next_state"] in OWNER_GATED
            if row.get("onboarded_at") is not None:
                row["onboarded_at"] = str(row["onboarded_at"])
            out.append(row)
    return out
