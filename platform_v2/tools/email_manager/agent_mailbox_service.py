"""Automatic mailbox provisioning for newly-created agents (#5640).

Why this exists
---------------
Agent creation never created an ``email_mailboxes`` row, and **every** provisioning
endpoint (``/provision``, ``/provision-all-agents``) only provisions rows that
ALREADY exist. So a new hire got no mailbox, and nothing downstream could ever
self-heal it: ``provision-all-agents`` selects ``WHERE provisioned = FALSE`` and
therefore reported success while creating nothing.

Measured 2026-08-15: 84 non-decommissioned agents had no mailbox at all, 45 of
them from a single hire wave on 2026-08-04. Every one had real dispatch history —
these were working agents, not junk rows.

This module is the missing step. ``ensure_agent_mailbox`` is called from
``agent_service.create_agent`` at the single-writer choke point, so it covers
every caller rather than one.

Design notes
------------
* **Best-effort, never fatal.** A mail outage must not block hiring an agent.
  Every failure path returns a dict and logs; it never raises into the caller.
* **Never steals an address.** If the derived address already belongs to a
  DIFFERENT agent, we skip and report ``collision`` rather than reassign it —
  silently repointing an existing mailbox would misroute real mail. ``Forge``
  (internal, id 21) vs ``F.O.R.G.E.`` (ai) is a live example of this collision.
* **Idempotent.** Called twice for the same agent, the second call is a no-op.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_DOMAIN = "kytranempowerment.com"

# mailbox_type by agent worker_type. 'local' is a legacy label that behaves
# exactly like 'internal' (2 agents: Compass, Sentry).
_TYPE_MAP = {
    "ai": "ai_agent",
    "internal": "human_agent",
    "local": "human_agent",
    "contractor": "human_agent",
}


def derive_address(name: str, first_name: str | None = None, last_name: str | None = None) -> str | None:
    """Derive the mailbox address for an agent, following existing conventions.

    AI acronym agents drop the dots (``W.A.R.D.E.N.`` -> ``warden@``); staff with
    a real human name use ``firstname.lastname@`` (matching the 21 collaborator
    mailboxes). Returns None when no usable local part can be formed.
    """
    if first_name and last_name:
        first = re.sub(r"[^a-z0-9]", "", first_name.lower())
        last = re.sub(r"[^a-z0-9]", "", last_name.lower())
        if first and last:
            return f"{first}.{last}@{_DOMAIN}"

    local = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return f"{local}@{_DOMAIN}" if local else None


def ensure_agent_mailbox(
    agent_id: int,
    name: str,
    department: str | None = None,
    worker_type: str = "internal",
    first_name: str | None = None,
    last_name: str | None = None,
    provision: bool = True,
) -> dict:
    """Create (and optionally provision) the mailbox for one agent.

    Returns ``{"ok": bool, "address": str|None, "status": str}`` where status is
    one of: ``created``, ``exists``, ``collision``, ``skipped``, ``error``.
    Never raises — mail problems must not break agent creation.
    """
    try:
        from database import get_db_cursor
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning("agent mailbox: cannot import database layer: %s", exc)
        return {"ok": False, "address": None, "status": "error"}

    address = derive_address(name, first_name, last_name)
    if not address:
        logger.warning("agent mailbox: agent #%s (%r) yields no usable address", agent_id, name)
        return {"ok": False, "address": None, "status": "skipped"}

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, owner_agent_id FROM email_mailboxes WHERE lower(address) = lower(%s)",
                (address,),
            )
            existing = cur.fetchone()
            if existing:
                owner = existing["owner_agent_id"]
                if owner == agent_id:
                    return {"ok": True, "address": address, "status": "exists"}
                # Belongs to someone else — never reassign, that misroutes mail.
                logger.warning(
                    "agent mailbox: %s already owned by agent #%s, not agent #%s — skipping",
                    address,
                    owner,
                    agent_id,
                )
                return {"ok": False, "address": address, "status": "collision"}

            cur.execute("SELECT 1 FROM email_mailboxes WHERE owner_agent_id = %s", (agent_id,))
            if cur.fetchone():
                return {"ok": True, "address": address, "status": "exists"}

        mailbox_type = _TYPE_MAP.get(worker_type, "human_agent")
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO email_mailboxes
                   (address, mailbox_type, owner_agent_id, display_name, department, provisioned, active)
                   VALUES (%s, %s, %s, %s, %s, FALSE, TRUE)
                   RETURNING id""",
                (address, mailbox_type, agent_id, name, department),
            )
            mailbox_id = cur.fetchone()["id"]
    except Exception as exc:
        logger.error("agent mailbox: DB step failed for agent #%s (%s): %s", agent_id, address, exc)
        return {"ok": False, "address": address, "status": "error"}

    if not provision:
        return {"ok": True, "address": address, "status": "created"}

    try:
        from .stalwart_service import create_mailbox

        result = create_mailbox(address, name)
        if result.get("ok"):
            from database import get_db_cursor as _cursor

            with _cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE email_mailboxes SET provisioned = TRUE, provisioned_at = NOW(),
                       imap_password = %s, updated_at = NOW() WHERE id = %s""",
                    (result.get("password"), mailbox_id),
                )
            logger.info("agent mailbox: provisioned %s for agent #%s", address, agent_id)
            return {"ok": True, "address": address, "status": "created"}

        # Row stays unprovisioned so /provision-all-agents can retry it later.
        logger.error(
            "agent mailbox: Stalwart provisioning failed for %s: %s",
            address,
            result.get("error"),
        )
        return {"ok": False, "address": address, "status": "error"}
    except Exception as exc:
        logger.error("agent mailbox: provisioning raised for %s: %s", address, exc)
        return {"ok": False, "address": address, "status": "error"}
