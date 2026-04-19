"""Business logic for the DHQ Hiring Queue.

Spec: docs/superpowers/specs/2026-04-19-dhq-hiring-queue-design.md
Task: #2102 on Project #261.

Public functions:
- get_shortlist(capability, limit=3) -> list[dict]
- propose_for_gap(capability, gap_reason, ...) -> int | None
- approve_candidate(hire_id, chosen_agent_id, decided_by_user_id, notes) -> dict
- reject_candidate(hire_id, decided_by_user_id, notes) -> dict
- expire_stale_proposals(max_age_days=14) -> int
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import requests

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Module constants
MIN_PROFICIENCY = 3
DEFAULT_SHORTLIST_LIMIT = 3
DEFAULT_EXPIRY_DAYS = 14


def _fetch_shortlist_rows(capability: str, limit: int) -> list[dict[str, Any]]:
    """Query the DB for decommissioned candidates. Separated for ease of mocking.

    Note: agents.model is used directly as primary_model — there is no
    separate agent_models table in this schema.
    """
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT
                a.id                   AS agent_id,
                a.display_name         AS display_name,
                s.proficiency_level    AS proficiency_level,
                a.department           AS department,
                -- agents has no decommissioned_at column; updated_at is
                -- the nearest stand-in (shift_state transitions update the row).
                a.updated_at           AS decommissioned_at,
                COALESCE(a.model, '')  AS primary_model
            FROM agents a
            JOIN agent_skills s ON s.agent_id = a.id AND s.skill_name = %s
            WHERE a.shift_state = 'decommissioned'
              AND s.proficiency_level >= %s
            ORDER BY s.proficiency_level DESC, a.updated_at DESC NULLS LAST
            LIMIT %s
            """,
            (capability, MIN_PROFICIENCY, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_shortlist(capability: str, limit: int = DEFAULT_SHORTLIST_LIMIT) -> list[dict[str, Any]]:
    """Return up to `limit` decommissioned agents with `capability` proficiency >= 3.

    Ranked by proficiency DESC then most-recently-decommissioned DESC
    (updated_at is used as a stand-in for decommissioned_at, since the
    agents table has no dedicated column).
    """
    # Slice defensively in case a caller (or test mock) returns more than `limit`.
    # The real SQL query already applies LIMIT, so this is a no-op in production.
    return _fetch_shortlist_rows(capability, limit)[:limit]


def propose_for_gap(
    *,
    capability: str,
    gap_reason: str,
    shortlist: list[dict[str, Any]],
    narrative: Optional[str] = None,
    gap_alert_id: Optional[int] = None,
    proposed_by_agent_id: Optional[int] = None,
) -> Optional[int]:
    """Insert a pending hiring_candidates row. Returns new id, or None on dedup.

    Empty shortlist is silently skipped (no row inserted, returns None).
    """
    if not shortlist:
        logger.info("propose_for_gap skipping empty shortlist for %s", capability)
        return None

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id FROM hiring_candidates " "WHERE capability = %s AND status = 'pending' LIMIT 1",
            (capability,),
        )
        if cur.fetchone():
            logger.info("propose_for_gap dedup hit for %s", capability)
            return None

        cur.execute(
            """
            INSERT INTO hiring_candidates (
                capability, gap_reason, gap_alert_id, narrative,
                shortlist, proposed_by_agent_id
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (
                capability,
                gap_reason,
                gap_alert_id,
                narrative,
                json.dumps(shortlist, default=str),
                proposed_by_agent_id,
            ),
        )
        row = cur.fetchone()
        return row["id"] if isinstance(row, dict) else row[0]


def _verify_model_available(model: str, hub_host: Optional[str] = None) -> tuple[bool, str]:
    """GET /api/tags on hub; return (ok, message). 5s timeout, any failure = not ok."""
    if not model:
        return True, "no_model_configured_skip"
    host = hub_host or os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
    try:
        r = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        names = {m.get("name", "").split(":")[0] for m in r.json().get("models", [])}
        stem = model.split(":")[0]
        if stem not in names:
            return False, f"Model {model!r} not present on {host}"
        return True, "ok"
    except Exception as e:
        return False, f"Ollama unreachable: {e}"


def _transition_agent(agent_id: int, new_state: str, reason: str) -> None:
    """Wrapper around agent_service.transition_shift_state for ease of mocking."""
    from services.agent_service import transition_shift_state

    transition_shift_state(agent_id, new_state, reason=reason)


def _audit(
    action: str,
    user_id: int,
    subject_agent_id: Optional[int],
    details: dict[str, Any],
) -> None:
    """Write one governance_audit_log row. Best-effort — logs warning on failure.

    Schema uses: event_type (NOT NULL), event_category, agent_id, user_id,
    action, details, timestamp.
    """
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                    (event_type, event_category, action, user_id, agent_id,
                     details, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                """,
                (
                    action,
                    "agent_lifecycle",
                    action,
                    user_id,
                    subject_agent_id,
                    json.dumps(details, default=str),
                ),
            )
    except Exception as e:
        logger.warning("governance_audit_log write failed: %s", e)


def approve_candidate(
    *,
    hire_id: int,
    chosen_agent_id: int,
    decided_by_user_id: int,
    notes: str = "",
) -> dict[str, Any]:
    """Approve a hiring candidate. See spec §'Approve flow'.

    Returns {"ok": bool, "reason": str, "agent_id": int | None, "message": str?}.
    """
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, status, shortlist FROM hiring_candidates WHERE id = %s",
            (hire_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "reason": "not_found", "agent_id": None}
        status = row["status"] if isinstance(row, dict) else row[1]
        shortlist = row["shortlist"] if isinstance(row, dict) else row[2]
        if status != "pending":
            return {"ok": False, "reason": "already_decided", "agent_id": None}

        entries = shortlist if isinstance(shortlist, list) else json.loads(shortlist)
        match = next((e for e in entries if e.get("agent_id") == chosen_agent_id), None)
        if match is None:
            return {"ok": False, "reason": "candidate_not_in_shortlist", "agent_id": None}

        model = match.get("primary_model", "")
        ok, msg = _verify_model_available(model)
        if not ok:
            cur.execute(
                "UPDATE hiring_candidates "
                "SET precheck_status = %s, precheck_message = %s "
                "WHERE id = %s AND status = 'pending'",
                (
                    "model_missing" if "not present" in msg.lower() else "ollama_unreachable",
                    msg,
                    hire_id,
                ),
            )
            return {
                "ok": False,
                "reason": "model_missing",
                "agent_id": None,
                "message": msg,
            }

        try:
            _transition_agent(chosen_agent_id, "active", "hired_via_queue")
        except Exception as e:
            logger.exception("transition_shift_state failed for agent %s", chosen_agent_id)
            return {
                "ok": False,
                "reason": "transition_failed",
                "agent_id": None,
                "message": str(e),
            }

        cur.execute(
            """
            UPDATE hiring_candidates
               SET status = 'approved',
                   chosen_agent_id = %s,
                   decided_by_user_id = %s,
                   decided_at = NOW(),
                   decision_notes = %s,
                   precheck_status = 'ok',
                   precheck_message = NULL
             WHERE id = %s AND status = 'pending'
             RETURNING id
            """,
            (chosen_agent_id, decided_by_user_id, notes, hire_id),
        )
        if cur.fetchone() is None:
            return {"ok": False, "reason": "race_lost", "agent_id": chosen_agent_id}

    _audit(
        "hire_reactivation_approved",
        decided_by_user_id,
        chosen_agent_id,
        {"hire_id": hire_id, "notes": notes},
    )
    return {"ok": True, "reason": "approved", "agent_id": chosen_agent_id}


def reject_candidate(
    *,
    hire_id: int,
    decided_by_user_id: int,
    notes: str = "",
) -> dict[str, Any]:
    """Reject a hiring candidate. See spec §'Reject flow'."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, status FROM hiring_candidates WHERE id = %s",
            (hire_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        status = row["status"] if isinstance(row, dict) else row[1]
        if status != "pending":
            return {"ok": False, "reason": "already_decided"}

        cur.execute(
            """
            UPDATE hiring_candidates
               SET status = 'rejected',
                   decided_by_user_id = %s,
                   decided_at = NOW(),
                   decision_notes = %s
             WHERE id = %s AND status = 'pending'
             RETURNING id
            """,
            (decided_by_user_id, notes, hire_id),
        )
        if cur.fetchone() is None:
            return {"ok": False, "reason": "race_lost"}

    _audit(
        "hire_reactivation_rejected",
        decided_by_user_id,
        None,
        {"hire_id": hire_id, "notes": notes},
    )
    return {"ok": True, "reason": "rejected"}


def expire_stale_proposals(max_age_days: int = DEFAULT_EXPIRY_DAYS) -> int:
    """Flip pending rows older than max_age_days to 'expired'. Returns affected count."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE hiring_candidates
               SET status = 'expired'
             WHERE status = 'pending'
               AND proposed_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (max_age_days,),
        )
        return cur.rowcount
