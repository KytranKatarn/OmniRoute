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
    """Back-compat shim. Delegates to services.ollama_availability.is_model_available
    but preserves hiring's 'skip on empty model' semantic so barracked agents without
    a configured model don't fail the approve path.
    """
    if not model:
        return True, "no_model_configured_skip"
    from .ollama_availability import is_model_available

    return is_model_available(model, hub_host=hub_host)


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


def _department_for_capability(capability: str) -> str:
    """Resolve a capability to its home department via the ONE canonical resolver
    in ``services.agent_name_generator`` (the same one ``agent_identity_builder``
    imports). Defaults to Engineering & Technology. Lazy import avoids a
    boot-time cycle.

    Bug #4982: this used to import ``CAPABILITY_DEPARTMENT_MAP`` from the
    NON-EXISTENT module ``tools.department_hq.services.department_coordinator``,
    so the import always raised and every net-new hire fell back to Engineering
    regardless of capability (the map actually lives in
    ``services.department_coordinator``). The suggest-name/display path already
    used the canonical resolver, so it showed the right department while the
    create path silently miscategorised the agent. Delegating to the shared
    resolver keeps the two copies from drifting apart again."""
    from services.agent_name_generator import (
        _department_for_capability as _canonical_department_for_capability,
    )

    return _canonical_department_for_capability(capability)


def _create_new_hire(
    cur,
    *,
    hire_id: int,
    capability: str,
    gap_reason: str,
    new_agent: dict[str, Any],
    decided_by_user_id: int,
    notes: str,
) -> dict[str, Any]:
    """Net-new branch of approve_candidate: create a brand-new agent for a
    `type:new_hire` shortlist entry (no existing agent to reactivate) using the
    agent_service single-writer primitives, grant the capability skill (so the
    agent is actually dispatchable), seed its budget, then mark the candidate
    approved. `cur` is the caller's open (commit=True) cursor."""
    name = (new_agent.get("name") or "").strip()
    if not name:
        return {"ok": False, "reason": "name_required", "agent_id": None}
    model = (new_agent.get("model") or "").strip()
    if not model:
        return {"ok": False, "reason": "model_required", "agent_id": None}
    display_name = (new_agent.get("display_name") or "").strip() or (
        f"{capability.replace('_', ' ').title()} Specialist"
    )
    expansion = (new_agent.get("expansion") or "").strip()
    title = (new_agent.get("title") or "").strip()
    department = _department_for_capability(capability)

    # Model must actually be servable (same precheck as reactivation).
    ok, msg = _verify_model_available(model)
    if not ok:
        cur.execute(
            "UPDATE hiring_candidates SET precheck_status = %s, precheck_message = %s "
            "WHERE id = %s AND status = 'pending'",
            (
                "model_missing" if "not present" in msg.lower() else "ollama_unreachable",
                msg,
                hire_id,
            ),
        )
        return {"ok": False, "reason": "model_missing", "agent_id": None, "message": msg}

    # Name-collision guard across every shift_state (mirrors propose_hire).
    cur.execute("SELECT id, shift_state FROM agents WHERE name = %s LIMIT 1", (name,))
    existing = cur.fetchone()
    if existing:
        eid = existing["id"] if isinstance(existing, dict) else existing[0]
        return {
            "ok": False,
            "reason": "name_exists",
            "agent_id": None,
            "message": f"Agent name {name!r} already exists (agent #{eid}).",
        }

    from services import agent_service, agent_identity_builder

    # Authoritative COMPLETE identity. Trust the reviewed Generate result when it
    # carries a rich prompt; otherwise (manual name / no Generate) build it
    # server-side so every hire is complete. existing_name keeps the reviewed name.
    ident = {
        "name": name,
        "expansion": expansion,
        "title": title,
        "bio": (new_agent.get("bio") or "").strip(),
        "personality": (new_agent.get("personality") or "").strip(),
        "system_prompt": (new_agent.get("system_prompt") or "").strip(),
        "portrait_prompt": (new_agent.get("portrait_prompt") or "").strip(),
    }
    # Consistency guard: a client may send a rich identity built for a DIFFERENT
    # name (e.g. the name was edited after Generate). _assemble_system_prompt always
    # begins "You are {name} (...)", so a consistent prompt contains the name. If it
    # doesn't, the cached identity is stale — discard it and rebuild for the real name.
    if ident["system_prompt"] and name not in ident["system_prompt"]:
        ident = {
            "name": name,
            "expansion": "",
            "title": "",
            "bio": "",
            "personality": "",
            "system_prompt": "",
            "portrait_prompt": "",
        }

    if len(ident["system_prompt"]) < agent_identity_builder.MIN_SYSTEM_PROMPT_CHARS:
        try:
            built = agent_identity_builder.build_identity(capability, department=department, existing_name=name)
            for k in ("expansion", "title", "bio", "personality", "system_prompt", "portrait_prompt"):
                if not ident.get(k):
                    ident[k] = built.get(k) or ""
            if len(ident["system_prompt"]) < agent_identity_builder.MIN_SYSTEM_PROMPT_CHARS:
                ident["system_prompt"] = built["system_prompt"]
        except Exception as _be:
            logger.warning("identity build fallback failed for %s: %s", name, _be)

    try:
        new_agent_id = agent_service.create_agent(
            name=name,
            display_name=(display_name or name),
            department=department,
            model=model,
            shift_state="active",
            # #4951: a net-new pool-saturation hire is an AI acronym specialist
            # joining an AI capability pool (its peers are all worker_type='ai'),
            # and the directory + dispatch AI-agent queries filter on
            # worker_type='ai' — so it must be 'ai', not create_agent's 'internal'
            # default (which would hide the agent from the AI roster/dispatch).
            worker_type="ai",
            tier=3,
            system_prompt=ident["system_prompt"]
            or f"You are {name}, a specialist in {capability} in the {department} department.",
        )
        # agent_skills is what dispatch selection matches on — without this the
        # new hire would never actually serve the capability it was hired for.
        agent_service.add_skill(new_agent_id, capability, level=3, category=capability)
        agent_service.init_budget(new_agent_id)
        try:
            agent_service.log_creation_event(
                child_agent_id=new_agent_id,
                reason=f"Hired via DHQ queue for '{capability}': {gap_reason}",
                source="hiring_queue",
                capabilities=[capability],
                department=department,
            )
        except Exception as _le:  # creation-event logging is best-effort
            logger.warning("log_creation_event failed for #%s: %s", new_agent_id, _le)
    except ValueError as ve:
        return {"ok": False, "reason": "create_rejected", "agent_id": None, "message": str(ve)}
    except Exception as e:
        logger.exception("net-new create_agent failed (hire_id=%s)", hire_id)
        return {"ok": False, "reason": "create_failed", "agent_id": None, "message": str(e)}

    # Enrich the row with the full identity (acronym, expansion, title, bio,
    # personality, portrait prompt) so the roster shows a complete agent, not
    # just a name (F.O.R.G.E./M.A.V.E.N. convention). Goes through the agents
    # single-writer (agent_service.update_agent) — never raw SQL (K.I.N.
    # guardrail). Best-effort: a hiccup must not fail an otherwise-successful hire.
    try:
        agent_service.update_agent(
            new_agent_id,
            acronym=name,
            acronym_expansion=ident["expansion"] or None,
            title=ident["title"] or None,
            bio=ident["bio"] or None,
            personality_prompt=ident["personality"] or None,
            portrait_prompt=ident["portrait_prompt"] or None,
        )
    except Exception as _ue:
        logger.warning("identity enrich failed for #%s: %s", new_agent_id, _ue)

    # Queue a representative sci-fi portrait (async, fail-open — never blocks the hire).
    if ident["portrait_prompt"]:
        try:
            agent_service.add_portrait(new_agent_id, ident["portrait_prompt"], style="sci-fi")
        except Exception as _pe:
            logger.warning("portrait enqueue failed for #%s: %s", new_agent_id, _pe)

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
        (new_agent_id, decided_by_user_id, notes, hire_id),
    )
    if cur.fetchone() is None:
        # Lost the race after creating — leave the agent active but flag it.
        logger.warning("net-new hire race lost after creating agent #%s", new_agent_id)
        return {"ok": True, "reason": "hired_race", "agent_id": new_agent_id}

    _audit(
        "hire_new_agent_approved",
        decided_by_user_id,
        new_agent_id,
        {"hire_id": hire_id, "capability": capability, "name": name, "model": model, "notes": notes},
    )
    return {"ok": True, "reason": "hired", "agent_id": new_agent_id}


def approve_candidate(
    *,
    hire_id: int,
    chosen_agent_id: Optional[int] = None,
    decided_by_user_id: int,
    notes: str = "",
    new_agent: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Approve a hiring candidate. See spec §'Approve flow'.

    Two modes:
    - reactivation: `chosen_agent_id` names an existing (decommissioned/barracked)
      agent from the shortlist → transition it to active.
    - net-new: `new_agent={name, model, display_name?}` for a `type:new_hire`
      shortlist entry (no agent to reactivate) → create a brand-new agent.

    Returns {"ok": bool, "reason": str, "agent_id": int | None, "message": str?}.
    """
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, status, shortlist, capability, gap_reason " "FROM hiring_candidates WHERE id = %s",
            (hire_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "reason": "not_found", "agent_id": None}
        status = row["status"] if isinstance(row, dict) else row[1]
        shortlist = row["shortlist"] if isinstance(row, dict) else row[2]
        capability = row["capability"] if isinstance(row, dict) else row[3]
        gap_reason = (row["gap_reason"] if isinstance(row, dict) else row[4]) or ""
        if status != "pending":
            return {"ok": False, "reason": "already_decided", "agent_id": None}

        entries = shortlist if isinstance(shortlist, list) else json.loads(shortlist)

        # Net-new branch: the chosen shortlist entry has no existing agent to
        # reactivate — create one instead. Guarded so a net-new payload can only
        # approve a candidate that actually offers a new_hire option.
        if new_agent is not None:
            if not any(e.get("type") == "new_hire" for e in entries):
                return {"ok": False, "reason": "not_a_new_hire_candidate", "agent_id": None}
            return _create_new_hire(
                cur,
                hire_id=hire_id,
                capability=capability,
                gap_reason=gap_reason,
                new_agent=new_agent,
                decided_by_user_id=decided_by_user_id,
                notes=notes,
            )

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
