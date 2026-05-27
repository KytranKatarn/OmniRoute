"""Human Agent Provisioning Service.

Creates COLLABORATOR-role user accounts for the 21 human agent mailboxes
so they can log in to the Email HQ and see their department's mailboxes.

Usage (inside archie_platform container):
    python3 -c "
    import sys; sys.path.insert(0, '/app')
    from services.human_agent_provisioning import provision_all_human_agents
    results = provision_all_human_agents()
    for r in results:
        status = 'CREATED' if r['created'] else 'EXISTS'
        print(f\"{r['email']} ({r['department']}) — {status} — pw: {r.get('temp_password', 'n/a')}\")
    "
"""

from __future__ import annotations

import logging
import secrets

from database import get_db_cursor
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)


def provision_human_agent(name: str, email: str, department: str) -> dict:
    """Create a COLLABORATOR user account for a human agent.

    Idempotent: ON CONFLICT (email) DO NOTHING — safe to re-run.

    Returns a dict with:
        user_id      — None if account already existed
        username     — derived from name (e.g. "Priya Krishna" → "priya.krishna")
        email
        department
        temp_password — only set when created=True; caller must save it
        created      — True if a new row was inserted
    """
    temp_password = secrets.token_urlsafe(12)
    pw_hash = generate_password_hash(temp_password)
    username = name.lower().replace(" ", ".")

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO users (
                    username, email, password_hash, role,
                    agent_department, must_change_password, created_at, updated_at
                )
                VALUES (%s, %s, %s, 'COLLABORATOR', %s, TRUE, NOW(), NOW())
                ON CONFLICT (email) DO NOTHING
                RETURNING id
                """,
                (username, email, pw_hash, department),
            )
            row = cur.fetchone()
    except Exception:
        logger.exception("provision_human_agent failed for %s (%s)", email, department)
        return {
            "user_id": None,
            "username": username,
            "email": email,
            "department": department,
            "created": False,
            "error": "DB error — check logs",
        }

    created = row is not None
    result: dict = {
        "user_id": row["id"] if row else None,
        "username": username,
        "email": email,
        "department": department,
        "created": created,
    }
    if created:
        result["temp_password"] = temp_password
    return result


def provision_all_human_agents() -> list[dict]:
    """Discover all human_agent mailboxes and provision COLLABORATOR accounts.

    Reads from email_mailboxes (mailbox_type='human_agent', active=TRUE)
    and calls provision_human_agent() for each one.

    Returns a list of result dicts (one per mailbox).
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT em.display_name, em.address AS email, em.department,
                   a.department AS agent_department
            FROM email_mailboxes em
            LEFT JOIN agents a ON a.id = em.owner_agent_id
            WHERE em.mailbox_type = 'human_agent' AND em.active = TRUE
            ORDER BY em.display_name
            """
        )
        agents = [dict(r) for r in cur.fetchall()]

    results = []
    for agent in agents:
        # Prefer the denormalised department column (migration 406); fall back
        # to the agents table join if the column hasn't been backfilled yet.
        department = agent.get("department") or agent.get("agent_department") or "Unassigned"
        result = provision_human_agent(
            name=agent["display_name"],
            email=agent["email"],
            department=department,
        )
        results.append(result)
        if result["created"]:
            logger.info("Provisioned human agent account: %s (%s)", agent["email"], department)
        else:
            logger.debug("Human agent account already exists: %s", agent["email"])

    created_count = sum(1 for r in results if r.get("created"))
    logger.info(
        "provision_all_human_agents complete: %d created, %d already existed",
        created_count,
        len(results) - created_count,
    )
    return results
