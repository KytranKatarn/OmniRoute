"""Agent Service — THE single authority for all agent operations.

No other file should INSERT/UPDATE/DELETE on agents, agent_skills,
agent_emotional_state, agent_identity, or node_agents directly.
All mutations go through this service.

Import:
    from services.agent_service import (
        get_agent, list_agents, create_agent, update_agent, delete_agent,
        activate, barracks, deploy_to_node, return_from_node,
        get_org_chart, get_department_summary,
    )
"""

import json
import logging
import os
from typing import Dict
from database import get_db_cursor

logger = logging.getLogger(__name__)

DEPARTMENT_FLOOR_MAP = {
    "Executive Office": "BRIDGE",
    "Operations & Infrastructure": "OPERATIONS",
    "Logistics & Supply Chain": "OPERATIONS",
    "Finance & Accounting": "OPERATIONS",
    "Engineering & Technology": "ENGINEERING",
    "Security & Compliance": "ENGINEERING",
    "Research & Development": "ENGINEERING",
    "Creative & Design": "CREATIVE",
    "Marketing & Communications": "CREATIVE",
    "Documentation & Knowledge": "CREATIVE",
    "News & Media": "CREATIVE",
    "Customer Success & Support": "SERVICES",
    "Human Resources & Culture": "SERVICES",
    "Medical & Wellness": "SERVICES",
    "Legal & Regulatory": "SERVICES",
    "Diplomatic & External Relations": "SERVICES",
    "Analytics & Intelligence": "SERVICES",
}

VALID_SHIFT_STATES = (
    "active",
    "deployed",
    "barracked",
    "off_duty",
    "winding_down",
    "cooldown",
    # TERMINAL state. Omitted until 2026-08-15 (#5643) even though the rest of the
    # module already treated it as real: 79 agents were already sitting in it,
    # ``update_agent`` has an explicit ``shift_state == "decommissioned"`` branch
    # (which was UNREACHABLE — the validator above it rejected the value first),
    # and ``reactivate_agent`` refuses any agent whose current state is not
    # ``decommissioned``. Net effect: the platform could REACTIVATE a decommissioned
    # agent but had no supported way to DECOMMISSION one.
    #
    # The failure was silent in both directions: ``transition_shift_state`` RETURNS
    # {"success": False} rather than raising, so a caller that ignores the return
    # value sees nothing at all. That is how 5 agents were "retired" with no error
    # and no state change. Callers MUST check the returned dict.
    #
    # ``decommissioned`` is deliberately NOT part of the rotation-log state set in
    # ``transition_shift_state`` (rotation_log's CHECK constraint allows only
    # active/winding_down/cooldown/off_duty) — retirement closes the open rotation
    # entry without opening a new one, which is correct for a terminal state.
    "decommissioned",
)


def normalized_agent_name(name) -> str:
    """Fold an agent name to its comparison key: lowercase, dots removed.

    Dots ARE the platform's naming convention for AI agents (``F.O.R.G.E.``),
    so a literal string comparison treats ``A.T.L.A.S.`` and ``Atlas`` as two
    different agents. They are not — they are the same name, and creating both
    produces a twin that any name-based lookup can resolve to the wrong row.

    Deliberately narrow: case + dots ONLY (#5272). It does NOT strip spaces,
    hyphens or underscores, because those genuinely distinguish names
    (``Wei Chen`` vs ``WeiChen`` are plausibly different people) and
    over-normalizing would reject legitimate hires — a worse failure than the
    one being fixed, since a false rejection blocks the roster while a twin only
    risks a misresolve.

    Mirrors the diagnostic SQL exactly:
        replace(lower(name), '.', '')
    """
    return str(name or "").lower().replace(".", "")


def find_name_collision(cur, name):
    """Return the existing agent row whose name collides with ``name``, else None.

    Compares on :func:`normalized_agent_name`, so it catches BOTH an exact
    literal match and a dots/case twin. Searches every ``shift_state``
    (including ``decommissioned``) — a retired agent still owns its name, and
    the caller should reach for ``propose_reactivation`` rather than minting a
    duplicate.

    ``cur`` is an injected cursor so both the write path and the proposal path
    share one definition of "already taken" — see the note on ``create_agent``
    about why this must not live in a single caller.
    """
    cur.execute(
        """SELECT id, name, shift_state
             FROM agents
            WHERE replace(lower(name), '.', '') = %s
            ORDER BY id
            LIMIT 1""",
        (normalized_agent_name(name),),
    )
    return cur.fetchone()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def get_agent(agent_id):
    """Get full agent profile by ID. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT a.*,
                      aes.stress_level, aes.energy_level, aes.current_mood, aes.mood_intensity
               FROM agents a
               LEFT JOIN agent_emotional_state aes ON aes.agent_id = a.id
               WHERE a.id = %s""",
            (agent_id,),
        )
        return dict(cur.fetchone()) if cur.rowcount else None


def get_agent_by_name(name):
    """Get agent by code name. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM agents WHERE name = %s", (name,))
        return dict(cur.fetchone()) if cur.rowcount else None


def list_agents(
    department=None,
    floor=None,
    shift_state=None,
    skill=None,
    search=None,
    is_department_ai=None,
    status="active",
    limit=200,
):
    """List agents with optional filters. Returns list of dicts.

    status defaults to 'active' so decommissioned/inactive agents don't leak
    into Roster / Org Chart / dispatch call sites. Pass status=None to opt
    out (e.g. admin audit tooling that needs the full history).
    """
    conditions = []
    params = []

    if status is not None:
        conditions.append("a.status = %s")
        params.append(status)
    if department:
        conditions.append("a.department = %s")
        params.append(department)
    if floor:
        conditions.append("a.floor = %s")
        params.append(floor)
    if shift_state:
        conditions.append("a.shift_state = %s")
        params.append(shift_state)
    if is_department_ai is not None:
        conditions.append("a.is_department_ai = %s")
        params.append(is_department_ai)
    if search:
        conditions.append("(a.name ILIKE %s OR a.display_name ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""SELECT a.id, a.name, a.display_name, a.department, a.floor,
                       a.model, a.status, a.shift_state, a.is_department_ai,
                       a.temperature, a.max_tokens, a.system_prompt,
                       a.capabilities, a.metadata, a.title, a.avatar_url,
                       a.acronym, a.acronym_expansion, a.bio, a.worker_type,
                       a.updated_at
                FROM agents a {where}
                ORDER BY a.floor, a.department, a.is_department_ai DESC, a.name
                LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def list_agents_public(department=None, search=None, is_department_ai=None, agent_type=None, limit=200):
    """List agents with public-facing fields for the Employee Directory.

    Returns fields needed for public display: name, email, phone, bio, etc.
    Search matches name, display_name, title, and department.
    """
    conditions = ["a.status = 'active'"]
    params = []

    if department and department != "all":
        conditions.append("a.department = %s")
        params.append(department)
    if is_department_ai is not None:
        conditions.append("a.is_department_ai = %s")
        params.append(is_department_ai)
    if agent_type == "ai":
        conditions.append("a.worker_type IN ('internal', 'contract')")
    elif agent_type == "human":
        conditions.append("a.worker_type = 'human'")
    if search:
        conditions.append(
            "(a.first_name ILIKE %s OR a.last_name ILIKE %s" " OR a.title ILIKE %s OR a.department ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 4)

    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""SELECT a.id, a.name, a.first_name, a.last_name,
                       COALESCE(a.first_name || ' ' || a.last_name, a.name) as full_name,
                       a.email, a.phone, a.title, a.department, a.pronouns, a.bio,
                       a.avatar_url, a.tier, a.is_department_ai,
                       CASE WHEN a.worker_type IN ('internal','contract')
                            THEN 'AI' ELSE 'Human' END as employee_type,
                       a.worker_type, a.capabilities
                FROM agents a {where}
                ORDER BY a.department, a.first_name
                LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def create_agent(name, display_name, department, model, **kwargs):
    """Create a new agent. Returns agent_id.

    Required: name, display_name, department, model
    Optional kwargs: system_prompt, temperature, max_tokens, capabilities,
                     is_department_ai, shift_state, tier, worker_type,
                     allow_duplicate_name (default False)

    NAME-COLLISION GUARD (#5272) lives HERE, at the single-writer choke point,
    not only in ``propose_hire``. Before this, the duplicate check existed in
    ``propose_hire`` alone — so every other caller of ``create_agent``
    (``_create_agent_from_approval``, and any future one) minted duplicates with
    no check whatsoever, literal or normalized. That is the same per-caller
    gating shape as the #5194 merge-governance hole: a rule enforced in one
    caller is not enforced at all. Fails CLOSED — an unresolvable check raises
    rather than creating the row.

    ``allow_duplicate_name=True`` is the deliberate escape hatch for a genuinely
    distinct identity that happens to normalize onto an existing name — e.g.
    agent #376 ``Codex`` (the Codex CLI contract identity) legitimately coexists
    with #146 ``C.O.D.E.X.``. It must be passed explicitly and is logged loudly,
    so a twin can only ever be created on purpose.
    """
    floor = DEPARTMENT_FLOOR_MAP.get(department, "SERVICES")
    shift_state = kwargs.get("shift_state", "barracked")
    allow_duplicate_name = bool(kwargs.get("allow_duplicate_name", False))

    if department not in DEPARTMENT_FLOOR_MAP:
        raise ValueError(f"Invalid department: {department}")
    if shift_state not in VALID_SHIFT_STATES:
        raise ValueError(f"Invalid shift_state: {shift_state}")
    if not str(name or "").strip():
        raise ValueError("name is required")

    with get_db_cursor(commit=True) as (conn, cur):
        if not allow_duplicate_name:
            clash = find_name_collision(cur, name)
            if clash:
                raise ValueError(
                    f"Agent name {name!r} collides with existing agent "
                    f"#{clash['id']} {clash['name']!r} (shift_state="
                    f"{clash['shift_state']!r}). Names are compared with dots and "
                    f"case removed, so {name!r} and {clash['name']!r} are the same "
                    f"name. Use reactivation if this is the right agent, pick a "
                    f"different name, or pass allow_duplicate_name=True if this is "
                    f"deliberately a separate identity."
                )
        elif find_name_collision(cur, name):
            logger.warning(
                "create_agent: minting DELIBERATE duplicate name %r "
                "(allow_duplicate_name=True) — this creates a name twin",
                name,
            )

        cur.execute(
            """INSERT INTO agents
               (name, display_name, department, floor, model, shift_state,
                system_prompt, temperature, max_tokens, capabilities,
                is_department_ai, tier, worker_type, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
               RETURNING id""",
            (
                name,
                display_name,
                department,
                floor,
                model,
                shift_state,
                kwargs.get("system_prompt", ""),
                kwargs.get("temperature", 0.7),
                kwargs.get("max_tokens", 2048),
                json.dumps(kwargs.get("capabilities", {})),
                kwargs.get("is_department_ai", False),
                kwargs.get("tier", 3),
                kwargs.get("worker_type", "internal"),
            ),
        )
        agent_id = cur.fetchone()["id"]

        # Create initial emotional state
        cur.execute(
            """INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level, current_mood, mood_intensity)
               VALUES (%s, 0.1, 0.9, 'neutral', 0.5)""",
            (agent_id,),
        )

    logger.info("Created agent #%d: %s (%s) in %s", agent_id, name, display_name, department)

    # Give the new hire a mailbox (#5640). Done HERE, at the single-writer choke
    # point, so it covers every caller — the same reasoning as the name-collision
    # guard above. Before this, agent creation never made an email_mailboxes row
    # and no provisioning endpoint could self-heal it (they only provision rows
    # that already exist), so 84 working agents had no mail at all.
    # Best-effort by design: a mail outage must never block hiring.
    try:
        from tools.email_manager.agent_mailbox_service import ensure_agent_mailbox

        result = ensure_agent_mailbox(
            agent_id=agent_id,
            name=name,
            department=department,
            worker_type=kwargs.get("worker_type", "internal"),
            first_name=kwargs.get("first_name"),
            last_name=kwargs.get("last_name"),
        )
        if not result.get("ok"):
            logger.warning(
                "Agent #%d created but mailbox not provisioned (%s) — run "
                "/api/email/mailboxes/provision-all-agents to retry",
                agent_id,
                result.get("status"),
            )
    except Exception as exc:
        logger.warning("Agent #%d created but mailbox step failed: %s", agent_id, exc)

    return agent_id


def update_agent(agent_id, **fields):
    """Update agent fields. Auto-derives floor if department changes.

    Returns True on success, False if agent not found.
    """
    if not fields:
        return True

    # Auto-derive floor when department changes
    if "department" in fields:
        dept = fields["department"]
        if dept not in DEPARTMENT_FLOOR_MAP:
            raise ValueError(f"Invalid department: {dept}")
        fields["floor"] = DEPARTMENT_FLOOR_MAP[dept]

    if "shift_state" in fields and fields["shift_state"] not in VALID_SHIFT_STATES:
        raise ValueError(f"Invalid shift_state: {fields['shift_state']}")

    # Sync status with shift_state so portrait tab and other status filters stay consistent
    if "shift_state" in fields and "status" not in fields:
        fields["status"] = "decommissioned" if fields["shift_state"] == "decommissioned" else "active"

    # Build dynamic UPDATE
    set_clauses = []
    params = []
    for key, val in fields.items():
        if key in ("capabilities", "metadata", "permissions") and isinstance(val, (dict, list)):
            set_clauses.append(f"{key} = %s::jsonb")
            params.append(json.dumps(val))
        else:
            set_clauses.append(f"{key} = %s")
            params.append(val)

    set_clauses.append("updated_at = NOW()")
    params.append(agent_id)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = %s RETURNING id",
            params,
        )
        updated = cur.fetchone() is not None

    if updated:
        logger.info("Updated agent #%d: %s", agent_id, list(fields.keys()))

        # Sync Modelfile when system_prompt changes
        if "system_prompt" in fields and fields["system_prompt"]:
            try:
                from tools.department_hq.services.modelfile_sync import export_modelfile

                # Fetch agent name and model (may have been updated in same call)
                with get_db_cursor() as (conn, cur):
                    cur.execute("SELECT name, model FROM agents WHERE id = %s", (agent_id,))
                    row = cur.fetchone()
                if row:
                    agent_name = row["name"]
                    model = fields.get("model") or row["model"] or ""
                    if model:
                        export_modelfile(agent_name, model, fields["system_prompt"])
            except Exception as e:
                logger.warning("Modelfile sync failed for agent #%d: %s", agent_id, e)

        # Propagate name/display_name renames to fleet node replicas so they
        # don't go stale. A renamed hub agent otherwise leaves its node_agents
        # replicas under the OLD name, which then surfaces as a phantom agent
        # in the ARMADA dispatch-traffic feed (KB #271886).
        if "name" in fields or "display_name" in fields:
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "SELECT name, display_name FROM agents WHERE id = %s",
                        (agent_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        cur.execute(
                            "UPDATE node_agents SET name = %s, display_name = %s, "
                            "updated_at = NOW() WHERE hub_agent_id = %s",
                            (row["name"], row["display_name"] or row["name"], agent_id),
                        )
            except Exception as e:
                logger.warning(
                    "node_agents rename propagation failed for agent #%d: %s",
                    agent_id,
                    e,
                )

    return updated


def delete_agent(agent_id, hard=False):
    """Delete agent. Soft-delete by default (status=inactive, shift_state=off_duty)."""
    if hard:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
        logger.warning("Hard-deleted agent #%d", agent_id)
    else:
        update_agent(agent_id, status="inactive", shift_state="off_duty")
        logger.info("Soft-deleted agent #%d", agent_id)


def increment_usage(agent_id, tier=None):
    """Atomically increment this month's usage counters on the agents row.

    Called by ai_bridge.smart_router after every LLM execution so the
    counter lives inside the canonical single-writer path for the
    agents table (Project #241 Track C.3).

    - ``total_tasks_this_month`` is incremented by 1
    - ``opus_usage_this_month`` is incremented by 1 IFF ``tier == 'opus'``
    - An ``agent_activity_events`` row is inserted for mini-consciousness tracking
    """
    if not agent_id:
        return
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE agents SET
                total_tasks_this_month = COALESCE(total_tasks_this_month, 0) + 1,
                opus_usage_this_month = CASE
                    WHEN %s = 'opus'
                    THEN COALESCE(opus_usage_this_month, 0) + 1
                    ELSE COALESCE(opus_usage_this_month, 0)
                END,
                updated_at = NOW()
               WHERE id = %s""",
            (tier, agent_id),
        )
        cur.execute(
            "INSERT INTO agent_activity_events (event_type, agent_id, data) VALUES (%s, %s, %s::jsonb)",
            ("dispatch", agent_id, json.dumps({"tier": tier})),
        )


def update_performance_metrics(agent_id, success: bool):
    """Atomically recompute performance metrics on the agents row.

    Called by ai_bridge.bridge_dispatcher after a task completes so the
    aggregate SQL lives inside the canonical single-writer module
    (Project #241 Track C.3).

    Uses subqueries over task_execution_log to recompute:
      - total_tasks_completed (incremented iff success=True)
      - success_rate = AVG(success) rounded to 2 decimals
      - performance_score = weighted combo of success rate, volume, latency
    """
    if not agent_id:
        return
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE agents SET
                total_tasks_completed = total_tasks_completed + CASE WHEN %s THEN 1 ELSE 0 END,
                success_rate = (
                    SELECT ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 2)
                    FROM task_execution_log WHERE agent_id = %s
                ),
                performance_score = (
                    SELECT ROUND(
                        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 60 +
                        LEAST(COUNT(*)::numeric / 100, 1.0) * 25 +
                        CASE WHEN AVG(duration_ms) < 30000 THEN 15
                             WHEN AVG(duration_ms) < 60000 THEN 10
                             ELSE 5 END,
                        2
                    )
                    FROM task_execution_log WHERE agent_id = %s
                ),
                updated_at = NOW()
               WHERE id = %s""",
            (success, agent_id, agent_id, agent_id),
        )


# ---------------------------------------------------------------------------
# Shift Lifecycle
# ---------------------------------------------------------------------------


def activate(agent_id):
    """Set agent to active duty."""
    return update_agent(agent_id, shift_state="active")


def barracks(agent_id):
    """Return agent to barracks (reserve)."""
    return update_agent(agent_id, shift_state="barracked")


def wind_down(agent_id):
    """Begin wind-down cycle."""
    return update_agent(agent_id, shift_state="winding_down")


def cooldown(agent_id):
    """Put agent in cooldown."""
    return update_agent(agent_id, shift_state="cooldown")


# ---------------------------------------------------------------------------
# Reactivation — Project #272 Phase 1 / Task #2107 (reframed).
# Decommissioned agents retain their skill rows and can be re-staffed
# instead of hiring new. All reactivations must go through the Tier-2
# approval queue — agents/callers never flip the state directly.
# ---------------------------------------------------------------------------


def reactivate_agent(agent_id, reason="manual reactivation"):
    """Reactivate a decommissioned agent by flipping shift_state to barracked.

    Gated upstream — the canonical entry point is the ``reactivate_agent``
    action_type consumer in agent_loop, which only runs after Kytran
    approves the proposal. Do NOT call this directly from user-facing code.

    Returns dict with success + metadata or success=False + error.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id, name, display_name, department, shift_state " "FROM agents WHERE id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Agent {agent_id} not found"}
        current = row["shift_state"]
        if current != "decommissioned":
            return {
                "success": False,
                "error": (
                    f"Agent {agent_id} ({row['name']}) is not decommissioned " f"(current shift_state={current!r})"
                ),
            }

        # #5829: was a RAW UPDATE, which left no rotation row — the bench had no
        # provenance and no age, so nobody could tell why an agent was on it or
        # for how long. Now goes through the logged transition (migration 472
        # made 'barracked' recordable). Landing on the BENCH rather than active
        # is deliberate and unchanged: a reactivated agent should not silently
        # start taking work.
        _log_res = transition_shift_state(
            agent_id,
            "barracked",
            reason=f"reactivated: {reason}",
            changed_by="agent_service.reactivate_agent",
        )
        if not _log_res.get("success"):
            # Fall back to the direct write rather than leave the agent stuck in
            # 'decommissioned' — reactivation must not fail on a logging problem.
            logger.warning(
                "[agent_service] reactivate %s: logged transition failed (%s) — writing directly",
                agent_id,
                _log_res.get("error"),
            )
            cur.execute(
                "UPDATE agents SET shift_state = 'barracked', updated_at = NOW() WHERE id = %s",
                (agent_id,),
            )
        logger.info(f"[agent_service] Reactivated agent {agent_id} ({row['name']}): {reason}")
        return {
            "success": True,
            "agent_id": row["id"],
            "name": row["name"],
            "display_name": row["display_name"],
            "department": row["department"],
            "previous_state": "decommissioned",
            "new_state": "barracked",
            "reason": reason,
        }


def find_reactivation_candidates(capability, department=None, top_n=5):
    """Rank decommissioned agents by skill match for a given capability.

    Matches ``skill_name`` via ILIKE substring, with proficiency + exact /
    category match boosting the score. Returns up to ``top_n`` candidates.

    Score formula: ``match_weight * proficiency_level``, where
    ``match_weight`` is 10 (exact skill_name), 7 (skill_category match),
    or 5 (substring match). Ordered high-score first, with
    ``department`` tiebreak when requested.
    """
    if not capability or not isinstance(capability, str):
        return []
    if top_n <= 0 or top_n > 50:
        top_n = 5

    department_tiebreak_sql = "CASE WHEN a.department = %(dept)s THEN 0 ELSE 1 END," if department else ""
    params = {"cap": capability, "top_n": top_n}
    if department:
        params["dept"] = department

    # Stem expansion — English verb/noun forms differ by a small suffix
    # ("translate" vs "Translation"). Drop the last 2 chars when the
    # capability is long enough, so "translate" → "translat" matches
    # "Translation", "French Translation", "gh:document-translation".
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""
            SELECT a.id, a.name, a.display_name, a.department, a.model,
                   a.worker_type,
                   s.skill_name, s.skill_category, s.proficiency_level,
                   (CASE WHEN lower(s.skill_name) = lower(%(cap)s) THEN 10
                         WHEN lower(s.skill_category) = lower(%(cap)s) THEN 7
                         WHEN lower(s.skill_name) LIKE '%%'
                                                || lower(%(cap)s) || '%%' THEN 5
                         WHEN length(%(cap)s) >= 6
                              AND lower(s.skill_name) LIKE '%%'
                                  || lower(substring(%(cap)s from 1
                                                     for length(%(cap)s) - 2))
                                  || '%%' THEN 4
                         ELSE 1
                    END) * s.proficiency_level AS match_score
            FROM agents a
            JOIN agent_skills s ON s.agent_id = a.id
            WHERE a.shift_state = 'decommissioned'
              AND (
                  lower(s.skill_name) LIKE '%%' || lower(%(cap)s) || '%%'
                  OR lower(s.skill_category) = lower(%(cap)s)
                  OR (length(%(cap)s) >= 6
                      AND lower(s.skill_name) LIKE '%%'
                          || lower(substring(%(cap)s from 1
                                             for length(%(cap)s) - 2))
                          || '%%')
              )
            ORDER BY {department_tiebreak_sql}
                     match_score DESC,
                     s.proficiency_level DESC
            LIMIT %(top_n)s
            """,
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def propose_reactivation(agent_id, reason, requested_by="mcp_client"):
    """Submit a reactivation proposal to the Tier-2 approval queue.

    Validates the agent exists and is decommissioned, then delegates to
    ``agent_loop.request_approval`` with ``action_type='reactivate_agent'``.
    The approval consumer at ``_execute_approved_action`` calls
    :func:`reactivate_agent` after Kytran approves via Telegram / the
    Dept HQ hiring queue (task #2102).

    Returns ``{"success": True, "approval_id": int, "agent": {...}}`` on
    success, or ``{"success": False, "error": str}`` when the agent isn't
    eligible or the approval submission fails.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, name, display_name, department, model, shift_state " "FROM agents WHERE id = %s",
            (agent_id,),
        )
        agent = cur.fetchone()
    if not agent:
        return {"success": False, "error": f"Agent {agent_id} not found"}
    if agent["shift_state"] != "decommissioned":
        return {
            "success": False,
            "error": (f"Agent {agent['name']} is not decommissioned " f"(shift_state={agent['shift_state']!r})"),
        }

    # Defer the import to avoid a module-load cycle — agent_loop imports
    # agent_service during boot.
    try:
        sys_path_append = "/mnt/archie_brain"
        import sys as _sys

        if sys_path_append not in _sys.path:
            _sys.path.insert(0, sys_path_append)
        from ai_bridge.agent_loop import request_approval
    except Exception as exc:
        return {"success": False, "error": f"request_approval import failed: {exc}"}

    action_data = {
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "department": agent["department"],
        "model": agent["model"],
        "reason": reason,
    }
    approval_reason = (
        f"Reactivate {agent['display_name'] or agent['name']} " f"({agent['department']}, {agent['model']}): {reason}"
    )
    approval_id = request_approval(
        action_type="reactivate_agent",
        action_data=action_data,
        reason=approval_reason,
        requested_by=requested_by,
        tier=2,
    )
    if not approval_id:
        return {
            "success": False,
            "error": "request_approval returned None (likely dedup collision)",
        }
    return {
        "success": True,
        "approval_id": approval_id,
        "agent": dict(agent),
    }


def propose_hire(
    name,
    display_name,
    department,
    model,
    capability,
    reason,
    requested_by="mcp_client",
    suggested_skills=None,
):
    """Submit a new-agent creation proposal to the Tier-2 approval queue.

    Parallel to :func:`propose_reactivation`, but for net-new agents rather
    than decommissioned ones. Validates the inputs, guards against name
    collisions with existing agents (active, barracked, or decommissioned),
    and delegates to ``agent_loop.request_approval`` with
    ``action_type='create_agent'``. The approval consumer at
    ``_execute_approved_action`` (agent_loop.py:2822) calls
    ``BridgeDispatcher._create_agent_from_approval`` which in turn calls
    :func:`create_agent` (single-writer path for agents table).

    Rule: NO new-agent creation without explicit Kytran approval — this tool
    only files the proposal. This keeps Project #272 Phase 1 gating intact.

    Returns ``{"success": True, "approval_id": int, "proposed": {...}}`` on
    success, or ``{"success": False, "error": str}`` on validation failure
    / approval-queue dedup collision.
    """
    # Basic arg validation
    for field_name, field_value in (
        ("name", name),
        ("display_name", display_name),
        ("department", department),
        ("model", model),
        ("capability", capability),
        ("reason", reason),
    ):
        if not field_value or not str(field_value).strip():
            return {"success": False, "error": f"{field_name} is required"}
    if department not in DEPARTMENT_FLOOR_MAP:
        return {
            "success": False,
            "error": f"Invalid department: {department!r}. Valid: {sorted(DEPARTMENT_FLOOR_MAP.keys())}",
        }

    # Name-collision guard — block duplicates across every shift_state so a
    # propose_hire on a decommissioned agent's old name doesn't race the
    # reactivation path.
    #
    # Compares on the NORMALIZED name (#5272): the literal comparison this
    # replaced let 'A.T.L.A.S.' sail past the existing agent #17 'Atlas', and
    # two more twins (A.T.L.A.S. #430, H.A.V.E.N. #431) were minted after the
    # hole was first reported — 10 twins now exist, not the 8 originally counted.
    # This is the early, friendly check; create_agent enforces the same rule at
    # the write itself so a proposal filed before this fix still cannot land a
    # duplicate.
    with get_db_cursor() as (conn, cur):
        existing = find_name_collision(cur, name)
    if existing:
        # Fall back to `name` when the row has no 'name' key: a guard whose job is
        # to BLOCK must never crash with a KeyError instead of returning its error,
        # and an indistinguishable row is treated as the exact-match (stricter) case.
        existing_name = existing.get("name") or name
        exact = existing_name == name
        how = "already exists" if exact else f"collides with {existing_name!r}"
        why = "" if exact else " Names are compared with dots and case removed, so these are the same name."
        return {
            "success": False,
            "error": (
                f"Agent name {name!r} {how} (agent #{existing['id']}, "
                f"shift_state={existing['shift_state']!r}).{why} Use propose_reactivation "
                f"if this is the right agent, or pick a different name."
            ),
        }

    # Defer the import to avoid a module-load cycle — agent_loop imports
    # agent_service during boot.
    try:
        sys_path_append = "/mnt/archie_brain"
        import sys as _sys

        if sys_path_append not in _sys.path:
            _sys.path.insert(0, sys_path_append)
        from ai_bridge.agent_loop import request_approval
    except Exception as exc:
        return {"success": False, "error": f"request_approval import failed: {exc}"}

    skills = suggested_skills or [capability]
    # action_data must match the shape consumed by
    # BridgeDispatcher._create_agent_from_approval (department_dispatcher.py:3930).
    action_data = {
        "suggested_name": name,
        "display_name": display_name,
        "department": department,
        "suggested_model": model,
        "capability": capability,
        "suggested_skills": skills,
        "reason": reason,
    }
    approval_reason = f"Hire {display_name} ({department}, {model}): {reason}"
    approval_id = request_approval(
        action_type="create_agent",
        action_data=action_data,
        reason=approval_reason,
        requested_by=requested_by,
        tier=2,
    )
    if not approval_id:
        return {
            "success": False,
            "error": "request_approval returned None (likely dedup collision — a hiring proposal with the same name may already be pending)",
        }
    return {
        "success": True,
        "approval_id": approval_id,
        "proposed": {
            "name": name,
            "display_name": display_name,
            "department": department,
            "model": model,
            "capability": capability,
            "skills": skills,
        },
    }


def deploy_to_node(agent_id, node_id):
    """Deploy agent to a remote node."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Get agent info
        cur.execute(
            "SELECT name, display_name, department, model FROM agents WHERE id = %s",
            (agent_id,),
        )
        agent = cur.fetchone()
        if not agent:
            return False

        # Update shift state
        cur.execute(
            "UPDATE agents SET shift_state = 'deployed' WHERE id = %s",
            (agent_id,),
        )

        # Create or reactivate node_agent
        cur.execute(
            """INSERT INTO node_agents (hub_agent_id, node_id, name, display_name, department, model, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'active')
               ON CONFLICT (hub_agent_id, node_id)
               DO UPDATE SET status = 'active', department = EXCLUDED.department,
                             name = EXCLUDED.name, display_name = EXCLUDED.display_name""",
            (
                agent_id,
                node_id,
                agent["name"],
                agent["display_name"] or agent["name"],
                agent["department"],
                agent["model"],
            ),
        )

    logger.info("Deployed agent #%d to node #%d", agent_id, node_id)
    return True


def return_from_node(agent_id):
    """Return agent from node to barracks."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE agents SET shift_state = 'barracked' WHERE id = %s AND shift_state = 'deployed'",
            (agent_id,),
        )
        cur.execute(
            "UPDATE node_agents SET status = 'inactive' WHERE hub_agent_id = %s AND status = 'active'",
            (agent_id,),
        )
    logger.info("Returned agent #%d from node to barracks", agent_id)
    return True


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def get_skills(agent_id):
    """Get agent's skills with levels. Returns list of dicts."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT skill_name, skill_category, proficiency_level FROM agent_skills WHERE agent_id = %s ORDER BY proficiency_level DESC",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def add_skill(agent_id, skill_name, level=1, category="general"):
    """Add or update a skill for an agent."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, skill_category)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level""",
            (agent_id, skill_name, level, category),
        )
    logger.info("Agent #%d skill %s set to level %d", agent_id, skill_name, level)


def update_skill_from_benchmark(agent_id, skill_name, score):
    """Update skill level from benchmark score (0.0-1.0). Auto-levels 1-5."""
    level = max(1, min(5, int(score * 5) + 1))
    add_skill(agent_id, skill_name, level=level, category="benchmarked")


def match_capability(capability):
    """Find agents who have a matching skill, ranked by level. Returns list of (agent_id, level)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.model,
                      a.shift_state, s.proficiency_level
               FROM agent_skills s
               JOIN agents a ON a.id = s.agent_id
               WHERE s.skill_name = %s AND a.status = 'active'
               ORDER BY s.proficiency_level DESC, a.is_department_ai DESC""",
            (capability,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Welfare
# ---------------------------------------------------------------------------


def get_welfare(agent_id):
    """Get agent's current emotional state. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT stress_level, energy_level, current_mood, mood_intensity
               FROM agent_emotional_state WHERE agent_id = %s
               ORDER BY id DESC LIMIT 1""",
            (agent_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_welfare(agent_id, stress=None, energy=None, mood=None, mood_intensity=None):
    """Update agent welfare metrics."""
    updates = {}
    if stress is not None:
        updates["stress_level"] = max(0.0, min(0.9, stress))
    if energy is not None:
        updates["energy_level"] = max(0.0, min(1.0, energy))
    if mood is not None:
        updates["current_mood"] = mood
    if mood_intensity is not None:
        updates["mood_intensity"] = max(0.0, min(1.0, mood_intensity))

    if not updates:
        return

    set_clauses = [f"{k} = %s" for k in updates]
    params = list(updates.values()) + [agent_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE agent_emotional_state SET {', '.join(set_clauses)} WHERE agent_id = %s",
            params,
        )


def check_welfare_threshold(agent_id):
    """Check if agent is healthy enough to work. Returns (ok: bool, reason: str)."""
    welfare = get_welfare(agent_id)
    if not welfare:
        return True, "no welfare data"

    stress = float(welfare.get("stress_level", 0))
    energy = float(welfare.get("energy_level", 1))

    if stress >= 0.8:
        return False, f"stress too high ({stress:.2f})"
    if energy <= 0.2:
        return False, f"energy too low ({energy:.2f})"
    return True, "healthy"


def recover_idle(agent_id, energy_boost=0.2, stress_reduction=0.15):
    """Recover an idle agent's welfare."""
    welfare = get_welfare(agent_id)
    if not welfare:
        return

    new_energy = min(1.0, float(welfare.get("energy_level", 0.5)) + energy_boost)
    new_stress = max(0.0, float(welfare.get("stress_level", 0.5)) - stress_reduction)
    update_welfare(agent_id, stress=new_stress, energy=new_energy)


# ---------------------------------------------------------------------------
# Org Chart & Department Summary
# ---------------------------------------------------------------------------


def get_org_chart():
    """Get full org chart: floors -> departments -> agents."""
    agents = list_agents(limit=500)
    floors = {}

    for agent in agents:
        floor = agent["floor"]
        dept = agent["department"]
        if floor not in floors:
            floors[floor] = {}
        if dept not in floors[floor]:
            floors[floor][dept] = {"director": None, "staff": []}

        # Canonical rule: one director per department. If the slot is already
        # filled and another agent is also flagged is_department_ai (data
        # drift), we keep the first winner as director and push the rest into
        # staff — never silently drop an agent from the org chart.
        if agent.get("is_department_ai") and floors[floor][dept]["director"] is None:
            floors[floor][dept]["director"] = agent
        else:
            floors[floor][dept]["staff"].append(agent)

    return floors


def get_department_summary():
    """Get per-department agent counts and health."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT department, floor,
                      COUNT(*) as total,
                      COUNT(*) FILTER (WHERE shift_state = 'active') as active,
                      COUNT(*) FILTER (WHERE shift_state = 'deployed') as deployed,
                      COUNT(*) FILTER (WHERE shift_state = 'barracked') as barracked,
                      COUNT(*) FILTER (WHERE is_department_ai = true) as directors
               FROM agents
               WHERE status = 'active'
               GROUP BY department, floor
               ORDER BY floor, department"""
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def get_performance(agent_id, period_days=7):
    """Get agent performance metrics for a period."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT COUNT(*) FILTER (WHERE status = 'completed') as jobs_completed,
                      COUNT(*) FILTER (WHERE status = 'failed') as jobs_failed,
                      AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_seconds
               FROM bridge_jobs
               WHERE agent_name = (SELECT name FROM agents WHERE id = %s)
                 AND created_at > NOW() - INTERVAL '%s days'""",
            (agent_id, period_days),
        )
        row = cur.fetchone()
        if not row:
            return {
                "jobs_completed": 0,
                "jobs_failed": 0,
                "avg_response_ms": 0,
                "success_rate": 0,
            }

        completed = row["jobs_completed"] or 0
        failed = row["jobs_failed"] or 0
        total = completed + failed
        return {
            "jobs_completed": completed,
            "jobs_failed": failed,
            "avg_response_ms": int((row["avg_seconds"] or 0) * 1000),
            "success_rate": round(completed / total * 100, 1) if total > 0 else 100,
        }


# ---------------------------------------------------------------------------
# Hardware-Aware Recommendations
# ---------------------------------------------------------------------------


def get_agents_for_hardware(gpu_vram_gb, ram_gb):
    """Return agents whose models fit the given hardware, ranked by benchmark score."""
    # Rough model size estimates (can be refined with actual data)
    agents = list_agents(shift_state="active")
    compatible = []

    for agent in agents:
        model = agent.get("model", "")
        # Estimate VRAM need from model name
        if "1.5b" in model or "3b" in model:
            vram_need = 2.0
        elif "7b" in model:
            vram_need = 5.0
        elif "12b" in model or "14b" in model:
            vram_need = 10.0
        elif "16b" in model:
            vram_need = 12.0
        elif ":cloud" in model:
            vram_need = 0  # cloud models don't need local VRAM
        else:
            vram_need = 5.0  # default estimate

        if vram_need <= gpu_vram_gb or vram_need <= ram_gb * 0.8:
            agent["estimated_vram_gb"] = vram_need
            compatible.append(agent)

    return sorted(compatible, key=lambda a: a.get("is_department_ai", False), reverse=True)


def recommend_node_deployment(node_id):
    """Recommend agents for a specific node based on its hardware."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT gpu_vram_gb, ram_gb, gpu_model FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        node = cur.fetchone()

    if not node:
        return []

    return get_agents_for_hardware(
        gpu_vram_gb=float(node.get("gpu_vram_gb") or 0),
        ram_gb=float(node.get("ram_gb") or 0),
    )


# ---------------------------------------------------------------------------
# Identity & Portraits
# ---------------------------------------------------------------------------


def get_identity(agent_id):
    """Get agent identity details (bio, gender, ethnicity, appearance, portrait_prompt)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, name, display_name, department, floor, is_department_ai,
                      bio, gender, ethnicity, age_range, appearance_notes, portrait_prompt,
                      model, system_prompt, avatar_url, email
               FROM agents WHERE id = %s""",
            (agent_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_identity(agent_id, **fields):
    """Update agent identity fields (bio, gender, ethnicity, age_range, appearance_notes, portrait_prompt)."""
    allowed = {
        "bio",
        "gender",
        "ethnicity",
        "age_range",
        "appearance_notes",
        "portrait_prompt",
        "email",
    }
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return False
    return update_agent(agent_id, **filtered)


def get_portraits(agent_id):
    """Get all portraits for an agent."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, canonical_image_path as image_path, prompt, style, is_primary, generation_status, created_at as generated_at
               FROM agent_portraits WHERE agent_id = %s
               ORDER BY is_primary DESC, created_at DESC""",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def add_portrait(agent_id, prompt, style="professional", negative_prompt=""):
    """Add a portrait entry and trigger generation via Media Studio pipeline.

    Inserts metadata row, then dispatches to portrait_service.generate_canonical()
    which queues the job through the Bridge dispatcher for GPU-aware routing.
    Returns portrait_id.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_portraits (agent_id, prompt, negative_prompt, style, generation_status, is_primary)
               VALUES (%s, %s, %s, %s, 'queued', false) RETURNING id""",
            (agent_id, prompt, negative_prompt, style),
        )
        portrait_id = cur.fetchone()["id"]

    # Trigger actual image generation through Media Studio's portrait service
    try:
        from tools.media_studio.services.portrait_service import generate_canonical

        result = generate_canonical(agent_id, prompt_override=prompt)
        if result.get("error"):
            logger.warning(
                "Portrait generation failed for agent %s: %s",
                agent_id,
                result["error"],
            )
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE agent_portraits SET generation_status = 'failed' WHERE id = %s",
                    (portrait_id,),
                )
        else:
            logger.info(
                "Portrait generation queued for agent %s (portrait %s)",
                agent_id,
                portrait_id,
            )
    except Exception as e:
        logger.warning("Could not trigger portrait generation for agent %s: %s", agent_id, e)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE agent_portraits SET generation_status = 'failed' WHERE id = %s",
                (portrait_id,),
            )

    return portrait_id


def set_primary_portrait(agent_id, portrait_id):
    """Set a portrait as the primary (unsets any existing primary)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE agent_portraits SET is_primary = false WHERE agent_id = %s",
            (agent_id,),
        )
        cur.execute(
            "UPDATE agent_portraits SET is_primary = true WHERE id = %s AND agent_id = %s",
            (portrait_id, agent_id),
        )


def _get_skin_tone_hint(ethnicity):
    """Map ethnicity to explicit skin tone and feature descriptors for portrait prompts.

    Diffusion models weight earlier tokens more heavily, so placing explicit
    skin-tone and feature descriptors at the front of the prompt prevents
    whitewashing of non-white agents.
    """
    if not ethnicity:
        return ""

    skin_tone_hints = {
        "african": "dark brown skin, African features",
        "nigerian": "dark brown skin, West African features",
        "ethiopian": "medium-dark brown skin, East African features",
        "korean": "East Asian features, light golden skin tone",
        "japanese": "East Asian features, fair skin with warm undertones",
        "chinese": "East Asian features",
        "indian": "South Asian features, brown skin",
        "punjabi": "South Asian features, wheat-toned skin",
        "iranian": "Middle Eastern features, olive skin tone",
        "arab": "Middle Eastern features, olive to tan skin",
        "mexican": "Latin American features, warm brown skin",
        "brazilian": "Latin American features",
        "indigenous": "Indigenous features, warm brown skin",
        "jamaican": "dark brown skin, Caribbean features",
        "filipino": "Southeast Asian features, warm tan skin",
        "vietnamese": "Southeast Asian features, light olive skin",
        "thai": "Southeast Asian features, warm golden skin",
        "turkish": "Mediterranean features, olive skin",
        "somali": "dark brown skin, East African features",
        "haitian": "dark brown skin, Caribbean features",
        "dominican": "mixed features, warm brown skin",
        "colombian": "Latin American features",
        "peruvian": "Indigenous Latin American features, warm brown skin",
        "moroccan": "North African features, olive to brown skin",
        "egyptian": "North African features, olive to tan skin",
        "pakistani": "South Asian features, brown skin",
        "bengali": "South Asian features, brown skin",
        "trinidadian": "Caribbean features, brown skin",
        "eastern european": "Eastern European features, fair skin",
    }

    eth_lower = ethnicity.lower()
    for key, hint in skin_tone_hints.items():
        if key in eth_lower:
            return hint

    # Fallback: use the raw ethnicity string so it still appears in the prompt
    return ethnicity


def _is_non_white(ethnicity):
    """Return True if the agent's ethnicity is not white/European/Caucasian."""
    if not ethnicity:
        return False
    eth_lower = ethnicity.lower()
    white_markers = ("white", "european", "caucasian")
    return not any(m in eth_lower for m in white_markers)


def generate_portrait_prompt(agent_id):
    """Auto-generate a portrait prompt from agent identity data. Returns (prompt, negative).

    Ethnicity and skin-tone descriptors are placed FIRST in the prompt because
    diffusion models (SDXL/SD) weight earlier tokens more heavily.  For
    non-white agents an anti-whitewashing clause is appended to the negative
    prompt.
    """
    identity = get_identity(agent_id)
    if not identity:
        return "", ""

    is_director = identity.get("is_department_ai", False)
    gender = identity.get("gender") or "person"
    ethnicity = identity.get("ethnicity") or ""
    age = identity.get("age_range") or "30s"
    appearance = identity.get("appearance_notes") or ""

    skin_hint = _get_skin_tone_hint(ethnicity)
    appearance_suffix = f", {appearance}" if appearance else ""

    if is_director:
        prompt = (
            f"{skin_hint}, {gender} in their {age}, "
            f"professional corporate portrait photo of a department leader, "
            f"wearing sleek futuristic corporate attire, "
            f"subtle AI android features: slightly too-perfect skin, faint digital iris pattern, "
            f"confident authoritative expression, studio lighting, "
            f"high resolution{appearance_suffix}"
        )
    else:
        prompt = (
            f"{skin_hint}, {gender} in their {age}, "
            f"professional corporate portrait photo, "
            f"wearing smart business attire, natural expression, confident pose, "
            f"studio lighting, neutral background, "
            f"high resolution{appearance_suffix}"
        )

    negative = "cartoon, anime, illustration, painting, deformed, ugly, " "blurry, low quality, watermark, text, logo"
    if _is_non_white(ethnicity):
        negative += ", pale white skin, European features, light skin"

    return prompt, negative


def get_photo_gallery(agent_id):
    """Get agent's photo gallery."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, image_path, caption, category, generated_at
               FROM agent_photo_gallery WHERE agent_id = %s
               ORDER BY created_at DESC""",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Budget reset (Phase 1 — Agent Lifecycle Coordination)
# ---------------------------------------------------------------------------

COOLDOWN_STRESS_THRESHOLD = 0.85
COOLDOWN_ENERGY_THRESHOLD = 0.15


def reset_budgets():
    """Zero out all agent budget counters. Called daily by job_service.

    Returns dict with reset_count.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE agent_budgets
            SET current_task_count = 0,
                tokens_used_today = 0,
                token_reset_at = NOW()
            WHERE current_task_count > 0 OR tokens_used_today > 0
        """
        )
        count = cur.rowcount
    logger.info("[BudgetReset] Reset %d agent budgets", count)
    return {"reset_count": count}


def transition_cleared_cooldowns():
    """Transition cooldown agents back to active if their budgets are clear
    and their welfare is acceptable.

    Only transitions agents where:
    - shift_state = 'cooldown'
    - status = 'active' (not deactivated)
    - current_task_count = 0 (budget was reset)
    - stress < COOLDOWN_STRESS_THRESHOLD or energy > COOLDOWN_ENERGY_THRESHOLD

    Returns dict with transitioned_count and agent names.
    """
    transitioned = []
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.department,
                   COALESCE(ab.current_task_count, 0) AS task_count,
                   COALESCE(es.stress_level, 0.0) AS stress,
                   COALESCE(es.energy_level, 0.8) AS energy
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            WHERE a.shift_state = 'cooldown'
              AND a.status = 'active'
              AND COALESCE(ab.current_task_count, 0) = 0
        """
        )
        candidates = cur.fetchall()

        for agent in candidates:
            if agent["stress"] >= COOLDOWN_STRESS_THRESHOLD and agent["energy"] <= COOLDOWN_ENERGY_THRESHOLD:
                logger.info(
                    "[BudgetReset] Skipping %s — stress=%.2f energy=%.2f",
                    agent["name"],
                    agent["stress"],
                    agent["energy"],
                )
                continue

            cur.execute(
                "UPDATE agents SET shift_state = 'active' WHERE id = %s",
                (agent["id"],),
            )
            # Reset stress/energy — without this, welfare check re-fires winding_down
            # immediately after recovery since stress threshold is only 0.70
            cur.execute(
                """UPDATE agent_emotional_state
                      SET stress_level = 0.20, energy_level = 0.80,
                          current_mood = 'focused', timestamp = NOW()
                    WHERE agent_id = %s""",
                (agent["id"],),
            )

            # Log the rotation
            cur.execute(
                """
                INSERT INTO agent_rotation_log
                    (agent_id, shift_state, reason, started_at)
                VALUES (%s, 'active', 'budget_reset_recovery', NOW())
            """,
                (agent["id"],),
            )

            transitioned.append(agent["name"])
            logger.info("[BudgetReset] %s -> active (budget cleared)", agent["name"])

    logger.info(
        "[BudgetReset] Transitioned %d agents: %s",
        len(transitioned),
        ", ".join(transitioned) if transitioned else "none",
    )
    return {"transitioned_count": len(transitioned), "agents": transitioned}


# ---------------------------------------------------------------------------
# Phase 2 — Lifecycle constants
# ---------------------------------------------------------------------------

WINDING_DOWN_BUDGET_PCT = 0.80
WINDING_DOWN_STRESS = 0.70
COOLDOWN_BUDGET_PCT = 0.95
COOLDOWN_STRESS = 0.85
WINDING_DOWN_SCORE_PENALTY = 0.30


# ---------------------------------------------------------------------------
# Phase 2 — Lifecycle functions
# ---------------------------------------------------------------------------


def transition_shift_state(agent_id, new_state, reason="manual", changed_by="system"):
    """Transition an agent to a new shift state with full rotation logging.

    Validates the new state, closes the previous rotation log entry,
    inserts a new one, and updates the agent record. If transitioning
    to cooldown, attempts to find a replacement in the same department.

    Returns dict with success, agent_name, new_state, and optional replacement.
    """
    if new_state not in VALID_SHIFT_STATES:
        return {"success": False, "error": f"Invalid shift state: {new_state}"}

    # rotation_log CHECK states. 'barracked' added by migration 472 (#5829):
    # it was previously UNRECORDABLE, so every bench in the platform's history
    # left no audit row — which made a deliberate bench indistinguishable from an
    # accident. Four agents were found working while flagged barracked with no
    # rotation row and no rest cycle; there was literally no evidence to consult.
    # 'decommissioned' stays out on purpose: a terminal lifecycle state, not a shift.
    ROTATION_LOG_STATES = ("active", "winding_down", "cooldown", "off_duty", "barracked")

    replacement = None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id, name, department, shift_state FROM agents WHERE id = %s",
            (agent_id,),
        )
        agent = cur.fetchone()
        if not agent:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        agent_name = agent["name"]
        department = agent["department"]
        old_state = agent["shift_state"]

        # Close previous open rotation log entry
        cur.execute(
            """
            UPDATE agent_rotation_log
            SET ended_at = NOW()
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )

        # Insert new rotation log entry (only if state is valid for rotation_log)
        if new_state in ROTATION_LOG_STATES:
            cur.execute(
                """
                INSERT INTO agent_rotation_log
                    (agent_id, shift_state, reason, started_at)
                VALUES (%s, %s, %s, NOW())
            """,
                (agent_id, new_state, reason),
            )

        # Update the agent's shift_state. Bump updated_at too (bug #5155): without
        # it the single-writer left the row's timestamp stale, so a woken/transitioned
        # agent showed a frozen "last updated" in the K.I.N. tab (V.I.S.A.G.E. read
        # 8 days old right after being woken to active). The reaper's raw SQL already
        # sets updated_at=NOW(); this makes the canonical writer consistent.
        cur.execute(
            "UPDATE agents SET shift_state = %s, updated_at = NOW() WHERE id = %s",
            (new_state, agent_id),
        )

        # Audit the transition for the K.I.N. shift calendar (Part C). The reaper
        # restore-to-active writes in jobs.py bypass this fn, but those rest→active
        # cycles are reconstructable from agent_rest_cycles.ended_at — so this chokepoint
        # captures the deliberate transitions (cooldown / off_duty / barracked / manual).
        cur.execute(
            """
            INSERT INTO shift_state_history (agent_id, from_state, to_state, reason, changed_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (agent_id, old_state, new_state, reason, changed_by),
        )

        logger.info("[Lifecycle] %s -> %s (reason=%s)", agent_name, new_state, reason)

        # If entering cooldown, try to find a replacement
        if new_state == "cooldown":
            replacement = find_replacement(agent_id, department, _cur=cur)

    return {
        "success": True,
        "agent_name": agent_name,
        "new_state": new_state,
        "replacement": replacement,
    }


def find_replacement(agent_id, department, _cur=None):
    """Find and activate a replacement agent from the same department.

    Looks for barracked or off_duty agents, scores them by average
    proficiency from agent_skills, and activates the best candidate.

    Accepts an optional cursor ``_cur`` for transaction sharing.
    Returns dict with id/name/score of the activated replacement, or None.
    """

    def _do(cur):
        cur.execute(
            """
            SELECT a.id, a.name,
                   COALESCE(AVG(sk.proficiency_level), 0) AS avg_prof
            FROM agents a
            LEFT JOIN agent_skills sk ON sk.agent_id = a.id
            WHERE a.department = %s
              AND a.id != %s
              AND a.shift_state IN ('barracked', 'off_duty')
              AND a.status = 'active'
            GROUP BY a.id, a.name
            ORDER BY avg_prof DESC
            LIMIT 1
        """,
            (department, agent_id),
        )
        candidate = cur.fetchone()
        if not candidate:
            return None

        # Activate the replacement
        cur.execute(
            "UPDATE agents SET shift_state = 'active' WHERE id = %s",
            (candidate["id"],),
        )
        cur.execute(
            """
            INSERT INTO agent_rotation_log
                (agent_id, shift_state, replaced_by, reason, started_at)
            VALUES (%s, 'active', NULL, 'replacement_activation', NOW())
        """,
            (candidate["id"],),
        )

        logger.info(
            "[Lifecycle] Replacement found: %s (score=%.2f) for department=%s",
            candidate["name"],
            float(candidate["avg_prof"]),
            department,
        )
        return {
            "id": candidate["id"],
            "name": candidate["name"],
            "score": float(candidate["avg_prof"]),
        }

    if _cur is not None:
        return _do(_cur)

    with get_db_cursor(commit=True) as (conn, cur):
        return _do(cur)


def increment_budget(agent_id, tokens_used=0):
    """Increment an agent's daily budget counters.

    If ``token_reset_at`` has passed, resets counters first and sets
    count to 1. Otherwise increments the existing row (upsert pattern
    using the unique constraint on agent_id).

    Returns dict with success, task_count, and tokens_used_today.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        # Check if reset is needed
        cur.execute(
            "SELECT token_reset_at FROM agent_budgets WHERE agent_id = %s",
            (agent_id,),
        )
        existing = cur.fetchone()

        if existing and existing["token_reset_at"] is not None:
            from datetime import datetime

            if existing["token_reset_at"] <= datetime.now():
                # Reset and start fresh
                cur.execute(
                    """
                    UPDATE agent_budgets
                    SET current_task_count = 1,
                        tokens_used_today = %s,
                        token_reset_at = NOW() + INTERVAL '1 day',
                        updated_at = NOW()
                    WHERE agent_id = %s
                """,
                    (tokens_used, agent_id),
                )
                cur.execute(
                    "SELECT current_task_count, tokens_used_today FROM agent_budgets WHERE agent_id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
                return {
                    "success": True,
                    "task_count": row["current_task_count"],
                    "tokens_used_today": row["tokens_used_today"],
                }

        # Upsert: increment or insert
        cur.execute(
            """
            INSERT INTO agent_budgets (agent_id, current_task_count, tokens_used_today, token_reset_at)
            VALUES (%s, 1, %s, NOW() + INTERVAL '1 day')
            ON CONFLICT (agent_id) DO UPDATE SET
                current_task_count = agent_budgets.current_task_count + 1,
                tokens_used_today = agent_budgets.tokens_used_today + %s,
                updated_at = NOW()
        """,
            (agent_id, tokens_used, tokens_used),
        )

        cur.execute(
            "SELECT current_task_count, tokens_used_today FROM agent_budgets WHERE agent_id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
        return {
            "success": True,
            "task_count": row["current_task_count"],
            "tokens_used_today": row["tokens_used_today"],
        }


def decrement_budget(agent_id):
    """Atomically decrement agent_budgets.current_task_count, clamped at zero.

    Mirrors increment_budget and must be called on every job completion/failure/
    cancel so the counter stays honest. Without this pair, the counter drifts
    upward forever and eventually exceeds task_queue_limit, silently blocking
    the agent from dispatch (see task #2100).

    Only decrements current_task_count — tokens_used_today is cumulative-daily
    and is cleared by reset_budgets() on its own schedule.
    """
    if not agent_id:
        return {"success": False, "reason": "no agent_id"}
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE agent_budgets
               SET current_task_count = GREATEST(0, COALESCE(current_task_count, 0) - 1),
                   updated_at = NOW()
               WHERE agent_id = %s
               RETURNING current_task_count""",
            (agent_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"success": False, "reason": "no budget row for agent"}
        return {"success": True, "task_count": row["current_task_count"]}


def reconcile_task_counters():
    """Sync agent_budgets.current_task_count to actual bridge_jobs in-flight count.

    Safety net for the decrement path: catches any drift from missed
    complete_job() calls, crashed workers, or legacy code paths. Run hourly
    via agent_loop. Returns a dict of agent names → drift corrected.
    """
    corrected: dict = {}
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            WITH real_inflight AS (
                SELECT agent_name, COUNT(*) AS actual
                FROM bridge_jobs
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                GROUP BY agent_name
            )
            UPDATE agent_budgets ab
            SET current_task_count = COALESCE(r.actual, 0),
                updated_at = NOW()
            FROM agents a
            LEFT JOIN real_inflight r ON r.agent_name = a.name
            WHERE ab.agent_id = a.id
              AND ab.current_task_count <> COALESCE(r.actual, 0)
            RETURNING a.name,
                      ab.current_task_count AS new_count,
                      (ab.current_task_count - COALESCE(
                          (SELECT actual FROM real_inflight WHERE agent_name = a.name), 0
                      )) AS drift_corrected
            """
        )
        for row in cur.fetchall():
            corrected[row["name"]] = {
                "new_count": row["new_count"],
                "drift_corrected": row["drift_corrected"],
            }
    if corrected:
        logger.warning(
            "[BudgetReconcile] corrected drift on %d agents: %s",
            len(corrected),
            ", ".join(f"{n}({d['drift_corrected']:+d})" for n, d in corrected.items()),
        )
    return corrected


def update_welfare_after_task(agent_id, success=True, hours_on_duty=None, is_resting=None, token_util=None):
    """Update an agent's emotional state based on recent task performance.

    Queries the 1-hour rolling window of task executions to calculate
    token-load-based stress, energy, and mood, PLUS the C.R.E.E.D. hours-on-duty
    fatigue term and the token-budget overwork term — all via the one shared
    ``welfare_load`` formula. Respects DB CHECK constraints (stress <= 0.9,
    energy >= 0.1).

    KB #270628 convergence: hours_on_duty is now part of THIS writer too, so the
    K.I.N. decay refresh (which calls this for every agent) no longer strips the
    hours term that hr_tracker set — the two writers agree, no staleness gate needed.

    Args:
        hours_on_duty: REAL wall-clock compute hours today; ``None`` → fetched here
            for this one agent (interval-union). The decay-refresh loop passes a
            precomputed value to avoid one full-fleet query per agent.
        is_resting: active-rest flag; ``None`` → queried here.
        token_util: tokens_24h / daily_budget (C.R.E.E.D. accounting Fix #C);
            ``None`` → computed here from a cheap agent-scoped 24h SUM against
            the already-fetched ``token_limit_per_day`` (0.0 if no budget is
            configured — "unknown" is safe/no-op, never inflates stress). The
            K.I.N. decay refresh does not pass this explicitly, so it is computed
            fresh on every recompute — this is what makes an idle-but-over-budget
            agent's stress honest even when it isn't actively completing tasks.

    Returns dict with success, stress, energy, and mood.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        # Get 1-hour rolling window stats. FIX-1 (KB #270619): include real TOKENS +
        # DURATION so fatigue tracks compute load, not raw dispatch COUNT. The old
        # COUNT(*)/20 utilization benched agents for doing many cheap calls.
        cur.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(tokens_used), 0) AS toks,
                   COALESCE(SUM(duration_ms), 0) AS dur_ms,
                   SUM(CASE WHEN success = false THEN 1 ELSE 0 END) AS failures
            FROM task_execution_log
            WHERE agent_id = %s
              AND created_at >= NOW() - INTERVAL '1 hour'
        """,
            (agent_id,),
        )
        stats = cur.fetchone()
        total = stats["total"] or 0
        failures = stats["failures"] or 0

        # Daily token budget for this agent (compute_token_load falls back if missing).
        cur.execute(
            "SELECT token_limit_per_day FROM agent_budgets WHERE agent_id = %s",
            (agent_id,),
        )
        _budget = cur.fetchone()
        token_limit = _budget["token_limit_per_day"] if _budget else None

        # Token-based load replaces the action-count utilization. ONE shared formula.
        from services.welfare_load import compute_token_load, stress_energy_from_load

        load = compute_token_load(stats["toks"], stats["dur_ms"], token_limit)
        failure_rate = (failures / total) if total > 0 else 0.0

        # Token-budget overwork term (C.R.E.E.D. accounting Fix #C). token_util =
        # tokens_24h / daily_budget; None (not passed) → compute here from a cheap
        # agent-scoped 24h SUM. 0.0 (no budget configured) is the safe "unknown" no-op.
        if token_util is None:
            if token_limit and float(token_limit) > 0:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(tokens_used), 0) AS tokens_24h
                    FROM task_execution_log
                    WHERE agent_id = %s
                      AND created_at >= NOW() - INTERVAL '24 hours'
                    """,
                    (agent_id,),
                )
                _tok24 = cur.fetchone()
                tokens_24h = (_tok24["tokens_24h"] if _tok24 else 0) or 0
                token_util = float(tokens_24h) / float(max(token_limit, 1))
            else:
                token_util = 0.0

        # Hours-on-duty fatigue + rest recovery (KB #270628 convergence). Computed
        # here when not supplied so per-task welfare carries the C.R.E.E.D. 12h axis;
        # the K.I.N. decay refresh passes precomputed values (avoids a fleet scan/agent).
        if hours_on_duty is None:
            try:
                from services.agent_load_service import real_compute_hours_today

                _hrec = real_compute_hours_today(cur, agent_id=agent_id).get(agent_id)
                hours_on_duty = _hrec["hours"] if _hrec else 0.0
            except Exception:
                hours_on_duty = 0.0
        if is_resting is None:
            cur.execute(
                """
                SELECT 1 FROM agent_rest_cycles
                WHERE agent_id = %s AND started_at <= NOW()
                  AND (ended_at IS NULL OR ended_at > NOW())
                LIMIT 1
                """,
                (agent_id,),
            )
            is_resting = cur.fetchone() is not None

        stress, energy = stress_energy_from_load(load, failures, total, hours_on_duty, is_resting, token_util)

        # Mood state machine (extended per LLM Ecosystem Redesign spec Section 9) —
        # 'utilization' is now token-based 'load'.
        if stress > 0.7:
            mood = "exhausted"  # high stress → winding_down territory
        elif stress > 0.5:
            mood = "tense"  # elevated stress → strained
        elif failure_rate > 0.5:
            mood = "frustrated"
        elif failure_rate > 0.2:
            mood = "concerned"
        elif total == 0:
            mood = "relaxed"  # no tasks, no stress → idle/resting
        elif load > 0.8:
            mood = "focused"  # high token throughput, manageable stress
        else:
            mood = "productive"

        # Preserve state-machine history before DELETE+INSERT wipes it.
        # previous_mood = the mood we are transitioning out of (whether or
        # not the new mood is different). mood_duration_minutes = how long
        # the agent held that previous mood. Observers use this pair to
        # reason about agent trajectories (e.g., "exhausted for 3 hours
        # then crashed to relaxed = just got relieved").
        cur.execute(
            """
            SELECT current_mood, timestamp
            FROM agent_emotional_state
            WHERE agent_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (agent_id,),
        )
        prior = cur.fetchone()
        prev_mood = None
        duration_minutes = None
        if prior:
            prev_mood = prior["current_mood"]
            if prior["timestamp"]:
                from datetime import datetime, timezone

                # agent_emotional_state.timestamp is TIMESTAMP (not TIMESTAMPTZ) —
                # psycopg2 returns it naive. Coerce to UTC-aware before subtracting
                # from datetime.now(timezone.utc) or we hit
                # "can't subtract offset-naive and offset-aware datetimes".
                # Storage convention is already UTC (timezone.md); the column type
                # is a migration debt to fix separately.
                prior_ts = prior["timestamp"]
                if prior_ts.tzinfo is None:
                    prior_ts = prior_ts.replace(tzinfo=timezone.utc)
                duration_minutes = max(
                    int((datetime.now(timezone.utc) - prior_ts).total_seconds() / 60),
                    0,
                )

        # DELETE + INSERT (no unique constraint on agent_id)
        cur.execute(
            "DELETE FROM agent_emotional_state WHERE agent_id = %s",
            (agent_id,),
        )
        cur.execute(
            """
            INSERT INTO agent_emotional_state
                (agent_id, current_mood, stress_level, energy_level,
                 trigger_event, previous_mood, mood_duration_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                agent_id,
                mood,
                min(max(float(stress), 0.0), 0.9),  # hard clamp — DB check requires <= 0.9
                min(max(float(energy), 0.1), 1.0),  # hard clamp — DB check requires >= 0.1
                "post_task_welfare_update",
                prev_mood,
                duration_minutes,
            ),
        )

        logger.info(
            "[Welfare] Agent %s: stress=%.2f energy=%.2f mood=%s (tasks=%d failures=%d)",
            agent_id,
            stress,
            energy,
            mood,
            total,
            failures,
        )

        return {
            "success": True,
            "stress": stress,
            "energy": energy,
            "mood": mood,
        }


def get_department_welfare_summary():
    """Aggregate welfare metrics per department for K.I.N. monitoring.

    Returns list of dicts: {department, avg_stress, avg_energy, agents_at_risk,
    total_agents, dominant_mood}. Ordered by avg_stress descending.

    Note: ``agent_emotional_state`` is a historical time-series (~63k rows
    for 131 agents). We reduce to latest-per-agent via ``DISTINCT ON``
    before joining — otherwise the join fans out and breaks the counts.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                WITH latest_aes AS (
                    SELECT DISTINCT ON (agent_id)
                           agent_id, current_mood, stress_level, energy_level
                    FROM agent_emotional_state
                    ORDER BY agent_id, timestamp DESC
                )
                SELECT a.department,
                       ROUND(AVG(COALESCE(aes.stress_level, 0.2))::numeric, 2) AS avg_stress,
                       ROUND(AVG(COALESCE(aes.energy_level, 0.8))::numeric, 2) AS avg_energy,
                       COUNT(*) FILTER (WHERE aes.stress_level > 0.7) AS agents_at_risk,
                       COUNT(*) AS total_agents,
                       MODE() WITHIN GROUP (ORDER BY COALESCE(aes.current_mood, 'idle')) AS dominant_mood
                FROM agents a
                LEFT JOIN latest_aes aes ON a.id = aes.agent_id
                WHERE a.worker_type = 'ai' AND a.shift_state = 'active'
                GROUP BY a.department
                ORDER BY avg_stress DESC
            """
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Department welfare summary failed: {e}")
        return []


# ---------------------------------------------------------------------------
# K.I.N. holistic digest — welfare + budget utilization.
# Project #272 Phase 1 / Task #2106. Closes Pillar 4 (surfaces) for K.I.N. —
# the budget data has been in ``agent_budgets`` all along, but no digest
# consumed it. The agent-loop job ``kin_welfare_digest`` and the MCP tool
# ``mcp__archie__get_welfare_digest`` both compose onto this function.
# ---------------------------------------------------------------------------


# ── Canonical 24h rolling token source (SHARED — do not duplicate) ────────────
# THE single definition of "per-agent token use over the last 24h" for ALL
# welfare reads: the dispatch throttle (get_welfare_cache), the K.I.N. digest
# department rollup (_get_department_budget_rollup) and the per-agent outliers
# (_get_agent_welfare_outliers). They MUST share this so they can never drift
# back to the since-midnight agent_budgets.tokens_used_today column, which
# resets at local midnight and made a 2x-over-budget agent read as healthy right
# after midnight (KB mistake #272470 / ADR-004 / #4090).
#
# Identity is resolved by agent_id OR by name (CLI-suffix-stripped) because ~48%
# of fleet-dispatched task_execution_log rows logged a NULL agent_id; a plain
# GROUP BY agent_id undercounts real usage and the throttle never fires. Yields
# rows of (aid, tokens_24h); wrap as "(<subquery>) tk ON tk.aid = a.id".
_TOKENS_24H_SUBQUERY = """
    SELECT COALESCE(t.agent_id, a2.id) AS aid, SUM(t.tokens_used) AS tokens_24h
    FROM task_execution_log t
    LEFT JOIN agents a2
           ON a2.name = split_part(t.agent_name, ' (CLI)', 1)
    WHERE t.created_at > NOW() - INTERVAL '24 hours'
      AND COALESCE(t.agent_id, a2.id) IS NOT NULL
    GROUP BY COALESCE(t.agent_id, a2.id)
""".strip()


def get_agent_tokens_24h(cur=None) -> Dict[int, int]:
    """Per-agent rolling-24h token usage from task_execution_log.

    THE shared 24h token source — see ``_TOKENS_24H_SUBQUERY``. Returns
    ``{agent_id: tokens_used_last_24h}`` (agents with no 24h rows are absent).
    Pass an open cursor to share a transaction; opens (and closes) its own
    otherwise. Never raises — returns ``{}`` on error so welfare reads degrade
    to "no usage" rather than blow up.
    """

    def _run(c):
        c.execute(f"SELECT aid, tokens_24h FROM ({_TOKENS_24H_SUBQUERY}) tk")
        return {row["aid"]: int(row["tokens_24h"] or 0) for row in c.fetchall()}

    try:
        if cur is not None:
            return _run(cur)
        with get_db_cursor() as (conn, c):
            return _run(c)
    except Exception as e:
        logger.error("get_agent_tokens_24h failed: %s", e)
        return {}


def _get_department_budget_rollup():
    """Return {department: {avg_token_usage_pct, agents_over_budget, agents_starving}}.

    Token usage is the 24h ROLLING window (shared ``_TOKENS_24H_SUBQUERY``), NOT
    the since-midnight ``agent_budgets.tokens_used_today`` column — so this rollup
    matches the dispatch throttle + K.I.N. tab (#272470 / #4130).

    * ``over_budget``: agent whose 24h rolling token use > 90% of its daily limit.
    * ``starving``: agent in ``shift_state='active'`` with zero tokens in the last
      24h AND zero current tasks — the dispatcher isn't sending it work.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""
                SELECT a.department,
                       ROUND(AVG(
                           CASE WHEN COALESCE(ab.token_limit_per_day, 0) > 0
                                THEN COALESCE(tk.tokens_24h, 0)::float
                                     / ab.token_limit_per_day::float
                                ELSE 0
                           END
                       )::numeric, 3) AS avg_token_usage_pct,
                       COUNT(*) FILTER (
                           WHERE COALESCE(ab.token_limit_per_day, 0) > 0
                             AND COALESCE(tk.tokens_24h, 0)::float
                                 / ab.token_limit_per_day::float > 0.9
                       ) AS agents_over_budget,
                       COUNT(*) FILTER (
                           WHERE a.shift_state = 'active'
                             AND COALESCE(tk.tokens_24h, 0) = 0
                             AND COALESCE(ab.current_task_count, 0) = 0
                       ) AS agents_starving
                FROM agents a
                LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
                LEFT JOIN ({_TOKENS_24H_SUBQUERY}) tk ON tk.aid = a.id
                WHERE a.worker_type = 'ai' AND a.status = 'active'
                GROUP BY a.department
                """
            )
            return {row["department"]: dict(row) for row in cur.fetchall()}
    except Exception as e:
        logger.error(f"Department budget rollup failed: {e}")
        return {}


# How recently an agent must have executed a task to count as "working" rather than
# starving (#5376). 7 days is deliberately generous: the flag exists to find agents
# NOTHING routes to, and a specialist that runs weekly is not a routing gap. Tightening
# this re-introduces false positives, which is the failure being fixed — an alarm that
# cries wolf gets ignored and buries the real signal.
_STARVING_RECENT_DAYS = float(os.getenv("KIN_STARVING_RECENT_DAYS", "7"))


def _get_agent_welfare_outliers(over_budget_threshold: float = 0.90):
    """Return per-agent outlier flags: over_budget, starving_idle, starving_no_llm.

    Flag types:
    - ``over_budget``     — 24h rolling token use > 90% of daily limit (shared
                           ``_TOKENS_24H_SUBQUERY``, NOT since-midnight; #4130)
    - ``starving_idle``   — active, zero tokens, zero tasks, and the AGENT has not
                           executed a task within ``_STARVING_RECENT_DAYS`` (or has
                           never executed one) → a real routing gap
    - ``starving_no_llm`` — active, zero tokens, zero tasks, BUT the AGENT executed a
                           task recently → it is working without burning tokens
                           (0-token telemetry/marker rows), expected, no action

    ⚠️ THE DISCRIMINATOR IS PER-AGENT, NOT PER-DEPARTMENT (#5376). It used to be
    ``has_loop_activity`` — whether the agent's DEPARTMENT logged a successful
    autonomy_loop_log row in 24h — which says nothing about the agent. Measured
    2026-08-02, that produced 25 flags of which 19 had run within 9 days, and it was
    INVERTED on the two cases that matter:
        A.R.C.H.I.E.  101,828 runs, ran today  -> starving_no_llm
        F.A.C.T.       17,538 runs, ran today  -> starving_idle ("routing gap")
        L.E.D.G.E.R.        0 runs, EVER       -> starving_no_llm ("expected, ignore")
    The busiest agent on the platform was reported as starving while the only genuinely
    never-dispatched one was filed as expected noise. A watchdog that is ~76% false
    positive gets ignored, and the real signal dies inside it (same shape as #5278).

    The flag VOCABULARY is deliberately unchanged. These strings are a policy key, not
    just display text: ``welfare_load.kin_action_allowed`` refuses actions per flag and
    is FAIL-OPEN on unknown flags, so a new flag name would silently become
    unconstrained and let K.I.N. act freely on it. ``creed_routes`` also filters on
    ``starving_no_llm``. Fixing the POPULATION rather than the names keeps every
    consumer correct.

    Each flag also includes a ``stress_trend`` (rising/stable/recovering) derived from
    comparing today's stress to the 7-day rolling average, plus ``runs_ever`` and
    ``last_run_days`` so the digest can show WHY an agent was flagged.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""
                WITH latest_aes AS (
                    SELECT DISTINCT ON (agent_id) agent_id, stress_level
                    FROM agent_emotional_state
                    ORDER BY agent_id, timestamp DESC
                ),
                stress_7d AS (
                    SELECT agent_id, AVG(stress_level) AS avg_stress_7d
                    FROM agent_emotional_state
                    WHERE timestamp > NOW() - INTERVAL '7d'
                    GROUP BY agent_id
                ),
                agent_exec AS (
                    -- Per-AGENT execution history (#5376). Identity is resolved the
                    -- same NULL-safe way as _TOKENS_24H_SUBQUERY — ~48% of
                    -- fleet-dispatched rows log a NULL agent_id, and a plain
                    -- GROUP BY agent_id would report a busy agent as never-used,
                    -- i.e. it would manufacture the very false positive this fixes.
                    SELECT COALESCE(t.agent_id, a2.id) AS aid,
                           COUNT(*)          AS runs_ever,
                           MAX(t.created_at) AS last_run
                    FROM task_execution_log t
                    LEFT JOIN agents a2
                           ON a2.name = split_part(t.agent_name, ' (CLI)', 1)
                    WHERE COALESCE(t.agent_id, a2.id) IS NOT NULL
                    GROUP BY COALESCE(t.agent_id, a2.id)
                )
                SELECT a.id, a.name, a.display_name, a.department, a.shift_state,
                       COALESCE(tk.tokens_24h, 0)           AS tokens_used_today,
                       COALESCE(ab.token_limit_per_day, 0)  AS token_limit_per_day,
                       COALESCE(ab.current_task_count, 0)   AS current_task_count,
                       COALESCE(aes.stress_level, 0.2)      AS stress_level,
                       COALESCE(s7.avg_stress_7d, 0.2)      AS stress_7d_avg,
                       COALESCE(ae.runs_ever, 0)            AS runs_ever,
                       -- age in DAYS computed in SQL: agent_emotional_state.timestamp
                       -- is timestamp WITHOUT time zone on this schema and mixing it
                       -- with an aware now() in Python raises (KB #283579).
                       EXTRACT(EPOCH FROM (NOW() - ae.last_run)) / 86400.0
                                                            AS last_run_days
                FROM agents a
                LEFT JOIN agent_budgets ab      ON a.id = ab.agent_id
                LEFT JOIN latest_aes aes        ON a.id = aes.agent_id
                LEFT JOIN stress_7d s7          ON s7.agent_id = a.id
                LEFT JOIN agent_exec ae         ON ae.aid = a.id
                LEFT JOIN ({_TOKENS_24H_SUBQUERY}) tk ON tk.aid = a.id
                WHERE a.worker_type = 'ai' AND a.status = 'active'
                """
            )
            flags = []
            for row in cur.fetchall():
                r = dict(row)
                stress_now = float(r["stress_level"])
                stress_7d = float(r["stress_7d_avg"])
                if stress_now > stress_7d + 0.15:
                    stress_trend = "rising"
                elif stress_now < stress_7d - 0.15:
                    stress_trend = "recovering"
                else:
                    stress_trend = "stable"

                limit = r["token_limit_per_day"] or 0
                if limit > 0:
                    pct = r["tokens_used_today"] / limit
                    if pct > over_budget_threshold:
                        flags.append(
                            {
                                "agent_id": r["id"],
                                "name": r["name"],
                                "display_name": r.get("display_name"),
                                "department": r["department"],
                                "flag": "over_budget",
                                "token_usage_pct": round(pct, 3),
                                "stress_level": stress_now,
                                "stress_trend": stress_trend,
                            }
                        )
                        continue
                if r["shift_state"] == "active" and r["tokens_used_today"] == 0 and r["current_task_count"] == 0:
                    # PER-AGENT discriminator (#5376). last_run_days is NULL when the
                    # agent has never executed anything — that is the strongest possible
                    # starving signal, so it must fall on the ACTIONABLE side. Guard the
                    # None explicitly: `None < x` raises in py3 and `not None` would have
                    # silently classed a never-used agent as recent.
                    _runs = int(r.get("runs_ever") or 0)
                    _age_d = r.get("last_run_days")
                    _worked_recently = _runs > 0 and _age_d is not None and float(_age_d) <= _STARVING_RECENT_DAYS
                    flag = "starving_no_llm" if _worked_recently else "starving_idle"
                    flags.append(
                        {
                            "agent_id": r["id"],
                            "name": r["name"],
                            "display_name": r.get("display_name"),
                            "department": r["department"],
                            "flag": flag,
                            "token_usage_pct": 0.0,
                            "stress_level": stress_now,
                            "stress_trend": stress_trend,
                            "runs_ever": _runs,
                            "last_run_days": (None if _age_d is None else round(float(_age_d), 1)),
                        }
                    )
            return flags
    except Exception as e:
        logger.error(f"Agent outlier flags query failed: {e}")
        return []


def _get_agent_work_summary() -> dict:
    """Return basic work session stats for K.I.N. digest."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT
                    COUNT(*) FILTER (WHERE status = 'active')                                       AS active_sessions,
                    COUNT(*) FILTER (WHERE status = 'completed'
                                       AND completed_at > NOW() - INTERVAL '24 hours')              AS completed_today,
                    COUNT(DISTINCT agent_id) FILTER (WHERE status = 'active' AND agent_id IS NOT NULL) AS agents_working
                FROM work_sessions"""
            )
            row = cur.fetchone()
            if row:
                return {
                    "active_sessions": int(row["active_sessions"] or 0),
                    "completed_today": int(row["completed_today"] or 0),
                    "agents_working": int(row["agents_working"] or 0),
                }
    except Exception as e:
        logger.warning("_get_agent_work_summary failed: %s", e)
    return {"active_sessions": 0, "completed_today": 0, "agents_working": 0}


def _write_welfare_snapshots(per_agent_flags: list) -> None:
    """Upsert today's welfare snapshot row for each flagged agent (migration 155)."""
    if not per_agent_flags:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for flag in per_agent_flags:
                cur.execute(
                    """
                    INSERT INTO agent_welfare_snapshots
                        (agent_id, snapshot_date, flag, avg_stress, created_at)
                    VALUES (%s, CURRENT_DATE, %s, %s, NOW())
                    ON CONFLICT (agent_id, snapshot_date) DO UPDATE SET
                        flag       = EXCLUDED.flag,
                        avg_stress = EXCLUDED.avg_stress
                    """,
                    (flag["agent_id"], flag["flag"], flag.get("stress_level")),
                )
    except Exception as e:
        logger.warning("_write_welfare_snapshots failed: %s", e)


def _get_digest_severity_thresholds():
    """Return ``(error_over_budget, error_at_risk)`` for the K.I.N. digest (#5177).

    Tunable live via ``platform_settings`` ``welfare:digest:error_over_budget`` /
    ``welfare:digest:error_at_risk`` — no deploy needed. The over-budget default is
    deliberately ABOVE the observed baseline (6-16 agents/day over the 13 days to
    2026-07-25) so ``error`` means "worse than any day in the last two weeks"
    rather than "it is Tuesday". Sub-threshold counts still raise ``warning``, so
    nothing is hidden. Never raises — falls back to the defaults on any error.

    FOLLOW-UP: the better signal is SUSTAINED per-agent overage (the same agent over
    budget N days running), which ``agent_welfare_snapshots`` can already support.
    That distinguishes "busy fleet" from "one agent is being ground down"; this
    function only stops the daily false alarm.
    """
    defaults = (20, 5)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT key, value FROM platform_settings
                 WHERE key IN ('welfare:digest:error_over_budget',
                               'welfare:digest:error_at_risk')
                """
            )
            rows = {r["key"]: r["value"] for r in cur.fetchall()}
        over = int(rows.get("welfare:digest:error_over_budget") or defaults[0])
        risk = int(rows.get("welfare:digest:error_at_risk") or defaults[1])
        return (over, risk)
    except (TypeError, ValueError, KeyError) as exc:
        logger.warning("digest severity thresholds unreadable (%s); using defaults", exc)
        return defaults
    except Exception:
        logger.warning("digest severity thresholds query failed; using defaults", exc_info=True)
        return defaults


def get_kin_welfare_digest(
    stress_threshold: float = 0.7,
    over_budget_threshold: float = 0.90,
    starving_warning: int = 3,
):
    """K.I.N. holistic digest — welfare + budget utilization.

    Composes ``get_department_welfare_summary()`` (stress / mood) with
    per-department budget aggregation and per-agent outlier flags. Drives
    the scheduled ``kin_welfare_digest`` job in agent_loop and the MCP
    tool ``get_welfare_digest``.

    Severity rollup:
      * ``error``   — ≥3 agents over budget OR ≥5 at welfare risk
      * ``warning`` — any agent over budget / at welfare risk, or
                      ≥``starving_warning`` starving agents
      * ``info``    — otherwise
    """
    from datetime import datetime, timezone

    department_rollup = get_department_welfare_summary()
    budget_by_dept = _get_department_budget_rollup()

    for dept in department_rollup:
        budget = budget_by_dept.get(dept["department"], {}) or {}
        dept["avg_token_usage_pct"] = float(budget.get("avg_token_usage_pct") or 0)
        dept["agents_over_budget"] = int(budget.get("agents_over_budget") or 0)
        dept["agents_starving"] = int(budget.get("agents_starving") or 0)

    per_agent_flags = _get_agent_welfare_outliers(over_budget_threshold)

    total_over_budget = sum(d["agents_over_budget"] for d in department_rollup)
    total_at_risk = sum(int(d.get("agents_at_risk") or 0) for d in department_rollup)

    # Refined starving breakdown: truly idle vs LLM-free scheduled workers
    starving_idle = [f for f in per_agent_flags if f["flag"] == "starving_idle"]
    starving_no_llm = [f for f in per_agent_flags if f["flag"] == "starving_no_llm"]
    total_starving = len(starving_idle) + len(starving_no_llm)  # legacy total
    total_starving_idle = len(starving_idle)

    stress_rising = [f for f in per_agent_flags if f.get("stress_trend") == "rising"]

    # Severity thresholds are tunable via platform_settings (#5177). The previous
    # hardcoded "error at >= 3 over budget" fired EVERY day for 13 consecutive days
    # (2026-07-12 .. 07-25, 6-16 over budget, never once below 6) because a busy
    # agent is over 90% of its budget BY CONSTRUCTION: token_limit_per_day is
    # p90(30d) x 1.3 clamped to base x 2 (clamp_budget_to_band), so the ceiling
    # cannot grow past real demand. An alarm that never clears monitors nothing —
    # a genuine welfare emergency was indistinguishable from baseline.
    # NOTE: winding_down agents are deliberately still counted. They may have
    # genuinely overworked today; excluding them would hide real overwork.
    _err_over_budget, _err_at_risk = _get_digest_severity_thresholds()

    severity = "info"
    reasons = []
    if total_over_budget >= _err_over_budget:
        severity = "error"
        reasons.append(f"{total_over_budget} agents over budget")
    if total_at_risk >= _err_at_risk:
        severity = "error"
        reasons.append(f"{total_at_risk} agents at welfare risk (stress>0.7)")
    if severity != "error":
        if total_over_budget > 0:
            severity = "warning"
            reasons.append(f"{total_over_budget} agent(s) over budget")
        if total_at_risk > 0:
            severity = "warning"
            reasons.append(f"{total_at_risk} agent(s) at welfare risk")
        if total_starving_idle >= starving_warning:
            severity = "warning"
            reasons.append(f"{total_starving_idle} idle agents (dispatcher routing gap)")
        if starving_no_llm:
            reasons.append(f"{len(starving_no_llm)} LLM-free scheduled workers (expected, no action needed)")
    if stress_rising:
        rising_names = ", ".join(f["name"] for f in stress_rising[:3])
        if severity == "info":
            severity = "warning"
        reasons.append(f"{len(stress_rising)} agent(s) with rising stress: {rising_names}")

    # Persist daily snapshot for trend analysis
    _write_welfare_snapshots(per_agent_flags)

    # Work session activity (mini-consciousness layer)
    work_activity = _get_agent_work_summary()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "department_rollup": department_rollup,
        "per_agent_flags": per_agent_flags,
        "work_activity": work_activity,
        "summary_metrics": {
            "total_over_budget": total_over_budget,
            "total_starving": total_starving,
            "total_starving_idle": total_starving_idle,
            "total_starving_no_llm": len(starving_no_llm),
            "total_at_risk": total_at_risk,
            "stress_rising": len(stress_rising),
            "department_count": len(department_rollup),
            "per_agent_flag_count": len(per_agent_flags),
            "agents_working_now": work_activity["agents_working"],
        },
        "severity": severity,
        "reasons": reasons,
    }


def format_kin_digest_message(digest):
    """Render a compact K.I.N. digest message for Telegram / system_notifications."""
    metrics = digest["summary_metrics"]
    lines = [
        "K.I.N. — crew welfare & budget digest",
        f"Severity: *{digest['severity'].upper()}* · {metrics['per_agent_flag_count']} agent flag(s)",
        "",
        f"• over-budget agents: {metrics['total_over_budget']}",
        f"• idle agents (no dispatch): {metrics.get('total_starving_idle', metrics['total_starving'])}",
        f"• scheduled-job workers (LLM-free): {metrics.get('total_starving_no_llm', 0)}",
        f"• at welfare risk: {metrics['total_at_risk']}",
        f"• stress trend rising: {metrics.get('stress_rising', 0)}",
        f"• departments scanned: {metrics['department_count']}",
    ]
    if digest.get("reasons"):
        lines.append("")
        lines.append("Reasons:")
        for reason in digest["reasons"]:
            lines.append(f"  – {reason}")
    return "\n".join(lines)


def check_shift_transitions():
    """Check all active/winding_down agents and trigger shift transitions.

    Applies threshold logic:
    - 95%+ budget used OR stress >= COOLDOWN_STRESS -> cooldown
    - 80%+ budget used OR stress >= WINDING_DOWN_STRESS -> winding_down

    Calls transition_shift_state for each triggered transition.
    Returns dict with list of transitions made.
    """
    transitions = []
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.department, a.shift_state,
                   COALESCE(ab.current_task_count, 0) AS task_count,
                   COALESCE(ab.task_queue_limit, 100) AS task_limit,
                   COALESCE(es.stress_level, 0.2) AS stress
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            WHERE a.shift_state IN ('active', 'winding_down')
              AND a.status = 'active'
        """
        )
        agents = cur.fetchall()

    for agent in agents:
        task_limit = agent["task_limit"] if agent["task_limit"] > 0 else 100
        budget_pct = agent["task_count"] / task_limit
        stress = float(agent["stress"])

        if agent["shift_state"] == "active":
            if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
                result = transition_shift_state(agent["id"], "cooldown", "budget_or_stress_exceeded")
                if result.get("success"):
                    transitions.append(
                        {
                            "agent": agent["name"],
                            "from": "active",
                            "to": "cooldown",
                            "budget_pct": round(budget_pct, 2),
                            "stress": stress,
                        }
                    )
            elif budget_pct >= WINDING_DOWN_BUDGET_PCT or stress >= WINDING_DOWN_STRESS:
                result = transition_shift_state(agent["id"], "winding_down", "budget_or_stress_warning")
                if result.get("success"):
                    transitions.append(
                        {
                            "agent": agent["name"],
                            "from": "active",
                            "to": "winding_down",
                            "budget_pct": round(budget_pct, 2),
                            "stress": stress,
                        }
                    )

        elif agent["shift_state"] == "winding_down":
            if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
                result = transition_shift_state(agent["id"], "cooldown", "budget_or_stress_exceeded")
                if result.get("success"):
                    transitions.append(
                        {
                            "agent": agent["name"],
                            "from": "winding_down",
                            "to": "cooldown",
                            "budget_pct": round(budget_pct, 2),
                            "stress": stress,
                        }
                    )

    logger.info("[ShiftCheck] %d transitions triggered", len(transitions))
    return {"transitions": transitions}


# ---------------------------------------------------------------------------
# Caches for DepartmentCoordinator scoring
# ---------------------------------------------------------------------------


def get_agent_cache() -> Dict:
    """Return dict of {agent_name: agent_info} for all active agents.

    Used by department_coordinator for scoring and selection.
    """
    cache = {}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.name, a.display_name, a.department, a.floor,
                   a.model, a.image_model, a.status, a.shift_state,
                   a.is_department_ai, a.worker_type,
                   COALESCE(json_agg(
                       json_build_object('skill', s.skill_name, 'level', s.proficiency_level)
                   ) FILTER (WHERE s.id IS NOT NULL), '[]') AS skills_list,
                   COALESCE(json_agg(
                       json_build_object('capability', cs.capability, 'score', cs.score)
                   ) FILTER (WHERE cs.id IS NOT NULL), '[]') AS competency_list
            FROM agents a
            LEFT JOIN agent_skills s ON a.id = s.agent_id
            LEFT JOIN agent_competency_scores cs ON a.id = cs.agent_id
            -- org_id IS NULL = internal ARCHIE agent. Client-owned (AaaS) agents
            -- carry an org_id and MUST NOT enter internal dispatch candidate
            -- selection (migration 443 / Project #297). No-op for existing agents
            -- (all NULL today); guards against client-agent leakage.
            WHERE a.status = 'active' AND a.org_id IS NULL
            GROUP BY a.id
        """
        )
        for row in cur.fetchall():
            skills = {}
            for s in row["skills_list"] if isinstance(row["skills_list"], list) else []:
                if isinstance(s, dict) and s.get("skill"):
                    skills[s["skill"]] = s.get("level", 1)
            competency_scores = {}
            for c in row["competency_list"] if isinstance(row["competency_list"], list) else []:
                if isinstance(c, dict) and c.get("capability") is not None:
                    competency_scores[c["capability"]] = float(c["score"])
            cache[row["name"]] = {
                "id": row["id"],
                "name": row["name"],
                "display_name": row["display_name"],
                "department": row["department"],
                "floor": row["floor"],
                "model": row["model"],
                "image_model": row.get("image_model"),
                "status": row["status"],
                "shift_state": row["shift_state"],
                "is_department_ai": row["is_department_ai"],
                "worker_type": row["worker_type"],
                "skills": skills,
                "competency_scores": competency_scores,
            }
    return cache


def get_welfare_cache() -> Dict:
    """Return dict of {agent_id: welfare_info} for budget/stress scoring.

    Used by department_coordinator for agent scoring.
    """
    cache = {}
    with get_db_cursor() as (conn, cur):
        # Token use is a 24h ROLLING SUM of task_execution_log.tokens_used — NOT the
        # since-midnight agent_budgets.tokens_used_today column, which is unreliably
        # populated and resets at local midnight (a 2x-over-budget agent reads as
        # healthy right after midnight). This matches the K.I.N. tab + welfare
        # governance window so the dispatch throttle fires on real over-budget agents
        # (ADR-004 / #4090). Aggregate once (GROUP BY) rather than a per-agent
        # correlated subquery so the 30s cache refresh stays a single indexed scan.
        cur.execute(
            f"""
            SELECT a.id,
                   COALESCE(es.stress_level, 0.0) AS stress,
                   COALESCE(es.energy_level, 0.5) AS energy,
                   COALESCE(ab.current_task_count, 0) AS task_count,
                   COALESCE(ab.task_queue_limit, 10) AS task_limit,
                   COALESCE(tk.tokens_24h, 0) AS tokens_used,
                   COALESCE(ab.token_limit_per_day, 100000) AS token_limit
            FROM agents a
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            -- 24h rolling token use via the shared canonical source (#272470/#4090/#4130):
            -- resolves a NULL agent_id by name so fleet-dispatched work still counts.
            LEFT JOIN ({_TOKENS_24H_SUBQUERY}) tk ON tk.aid = a.id
            WHERE a.status = 'active'
        """
        )
        for row in cur.fetchall():
            task_limit = row["task_limit"] or 10
            token_limit = row["token_limit"] or 100000
            tokens_used = row["tokens_used"] or 0
            task_ratio = (row["task_count"] / task_limit) if task_limit > 0 else 0.0
            token_ratio = (tokens_used / token_limit) if token_limit > 0 else 0.0
            cache[row["id"]] = {
                "stress": float(row["stress"]),
                "energy": float(row["energy"]),
                "budget": {
                    "current_task_count": row["task_count"],
                    "task_queue_limit": task_limit,
                    # NOTE: now the 24h rolling token sum, not the since-midnight
                    # column. Key name kept for back-compat readers.
                    "tokens_used_today": tokens_used,
                    "token_limit_per_day": token_limit,
                    "task_ratio": task_ratio,
                    "token_ratio": token_ratio,
                    "utilization_pct": max(task_ratio, token_ratio),
                },
            }
    return cache


# ---------------------------------------------------------------------------
# Sibling-table ownership — agent_skills / agent_budgets / agent_creation_events
# ---------------------------------------------------------------------------


def init_budget(
    agent_id: int,
    token_limit: int = 100000,
    task_queue_limit: int = 10,
    can_create_sub_agents: bool = False,
    max_sub_agents: int = 0,
) -> None:
    """Seed initial agent_budgets row for a new agent. No-op if already exists."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_budgets
                   (agent_id, token_limit_per_day, task_queue_limit,
                    can_create_sub_agents, max_sub_agents)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (agent_id) DO NOTHING""",
            (
                agent_id,
                token_limit,
                task_queue_limit,
                can_create_sub_agents,
                max_sub_agents,
            ),
        )
    logger.info("Agent #%d budget initialized (queue_limit=%d)", agent_id, task_queue_limit)


def log_creation_event(
    child_agent_id: int,
    reason: str,
    source: str = "agent_service",
    capabilities: list = None,
    department: str = None,
    parent_agent_id: int = 2,
    approved: bool = True,
) -> int:
    """Insert an agent_creation_events record. Returns the new event ID."""
    import json as _json

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_creation_events
                   (parent_agent_id, child_agent_id, creation_reason,
                    creation_source, capabilities_requested, station_requested,
                    is_approved, approved_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
               RETURNING id""",
            (
                parent_agent_id,
                child_agent_id,
                reason,
                source,
                _json.dumps(capabilities or []),
                department,
                approved,
            ),
        )
        row = cur.fetchone()
        event_id = row["id"] if row else None
    logger.info(
        "Agent #%d creation event logged (source=%s, id=%s)",
        child_agent_id,
        source,
        event_id,
    )
    return event_id
