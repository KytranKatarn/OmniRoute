"""Agent lifecycle: create with side effects, and soft decommission.

Decommission is NEW code. `agent_service.deactivate_agent()` does not exist —
CLAUDE.md listed it for a long time, but no deactivate/decommission/retire
function was ever written. Agents are retired by setting shift_state.
"""

from database import get_db_cursor
from services.agent_service import create_agent, get_agent, update_agent


def _skills_of(agent_id):
    """Skill names this agent holds."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT skill_name FROM agent_skills WHERE agent_id = %s", (agent_id,))
        return [r["skill_name"] for r in cur.fetchall()]


def _other_active_holders(skill_name, agent_id):
    """How many OTHER non-decommissioned agents hold this skill."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT COUNT(*) AS n
                 FROM agent_skills s
                 JOIN agents a ON a.id = s.agent_id
                WHERE s.skill_name = %s
                  AND s.agent_id <> %s
                  AND a.status = 'active'
                  AND a.shift_state <> 'decommissioned'""",
            (skill_name, agent_id),
        )
        row = cur.fetchone()
        return row["n"] if row else 0


def decommission_precheck(agent_id):
    """What would break if this agent were retired.

    Warnings are advisory, never blocking: the owner may legitimately retire a
    sole holder. What is NOT acceptable is doing it silently.
    """
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    warnings = []
    orphaned = [s for s in _skills_of(agent_id) if _other_active_holders(s, agent_id) == 0]
    if orphaned:
        warnings.append(
            {
                "kind": "sole_skill_holder",
                "message": (
                    "This agent is the ONLY active holder of %d skill(s). Retiring it "
                    "leaves those capabilities with no candidate: %s" % (len(orphaned), ", ".join(orphaned))
                ),
                "skills": orphaned,
            }
        )
    if agent.get("is_department_ai"):
        warnings.append(
            {
                "kind": "department_director",
                "message": (
                    "This agent is the director of %s — the department loses its "
                    "default routing target." % agent.get("department")
                ),
                "skills": [],
            }
        )
    return {"agent": agent, "warnings": warnings, "blocking": False}


def decommission_agent(agent_id, acknowledge_warnings=False):
    """Retire an agent by SHIFT STATE change only — no destructive SQL, ever.

    Refuses when the precheck raised warnings and the caller has not
    acknowledged them — the operator must see what breaks before it breaks.
    """
    pre = decommission_precheck(agent_id)
    warnings = pre["warnings"]
    if warnings and not acknowledge_warnings:
        return {
            "ok": False,
            "agent_id": agent_id,
            "previous": pre["agent"].get("shift_state"),
            "warnings": warnings,
            "refused": "unacknowledged_warnings",
        }
    previous = pre["agent"].get("shift_state")
    update_agent(agent_id, shift_state="decommissioned")
    return {"ok": True, "agent_id": agent_id, "previous": previous, "warnings": warnings, "refused": None}


DEFAULT_TOKEN_LIMIT_PER_DAY = 50000


def _add_skill(agent_id, skill_name, proficiency_level=1, skill_category="general"):
    """Insert or update one skill. Columns are skill_name / skill_category /
    proficiency_level — NOT category / level."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_id, skill_name)
               DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level,
                             skill_category   = EXCLUDED.skill_category,
                             updated_at       = now()""",
            (agent_id, skill_name, skill_category, proficiency_level),
        )


def _ensure_budget(agent_id, token_limit_per_day=DEFAULT_TOKEN_LIMIT_PER_DAY):
    """Without a budget row, welfare gating and the K.I.N. over-budget checks
    have nothing to read for this agent."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_budgets (agent_id, token_limit_per_day)
               VALUES (%s, %s) ON CONFLICT (agent_id) DO NOTHING""",
            (agent_id, token_limit_per_day),
        )


def _provision_mailbox(agent_id, fields):
    """Provision this agent's email mailbox and return a detail string ONLY when
    Stalwart provisioning has genuinely completed — never on row existence alone.

    VERIFIED (not guessed): tools.email_manager.agent_mailbox_service.ensure_agent_mailbox
    is an AI-capable path — its _TYPE_MAP maps worker_type='ai' to mailbox_type='ai_agent',
    not just 'internal'/'human_agent'. services.agent_service.create_agent() ALREADY
    calls it unconditionally for every worker_type as part of the agent step (PR #2596,
    "new agents get a mailbox automatically") — but it swallows the result into a log
    warning only, so create_agent_full's caller never sees whether it worked.

    ensure_agent_mailbox's own ok=True does NOT mean mail works: it early-returns on
    ROW EXISTENCE via two SELECTs (by address, by owner_agent_id) BEFORE any INSERT,
    and only runs the Stalwart create_mailbox() step on the fresh-insert path. So if a
    prior call inserted the email_mailboxes row (provisioned=FALSE) and then failed at
    the Stalwart step, calling it again just hits the owner_agent_id early-return and
    reports ok/'exists' again — a false positive for a mailbox that still cannot send
    or receive mail. We verify the DB's own `provisioned` boolean ourselves before
    reporting success, and calling ensure_agent_mailbox again is otherwise safe: on the
    genuinely-provisioned path it is a real no-op (its own docstring: "called twice for
    the same agent, the second call is a no-op").
    """
    from tools.email_manager.agent_mailbox_service import ensure_agent_mailbox

    result = ensure_agent_mailbox(
        agent_id=agent_id,
        name=fields["name"],
        department=fields.get("department"),
        worker_type=fields.get("worker_type", "internal"),
        first_name=fields.get("first_name"),
        last_name=fields.get("last_name"),
    )
    if not result.get("ok"):
        raise RuntimeError("mailbox %s for %s: %s" % (result.get("status", "error"), result.get("address"), result))

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT provisioned FROM email_mailboxes WHERE owner_agent_id = %s", (agent_id,))
        row = cur.fetchone()

    if not row or not row["provisioned"]:
        raise RuntimeError(
            "mailbox row exists for agent #%s (%s) but Stalwart provisioning did not "
            "complete — mail will not work for this agent until it is retried" % (agent_id, result.get("address"))
        )
    return "%s: %s" % (result.get("status"), result.get("address"))


def _queue_portrait(agent_id):
    """QUEUE a portrait. Never wait for it.

    generate_canonical already goes through media_generation_queue (ADR-005) and
    returns a queue_id. ComfyUI parks itself (state=exited) to free VRAM for
    Ollama — that is its correct resting state, so a cold start is normal and a
    portrait failure must never fail the agent creation.
    """
    from tools.media_studio.services.portrait_service import generate_canonical

    res = generate_canonical(agent_id) or {}
    if not res.get("queue_id"):
        raise RuntimeError(res.get("error") or "portrait was not queued (no queue_id returned)")
    return "queued (queue_id %s)" % res["queue_id"]


def create_agent_full(fields, skills, side_effects):
    """Create an agent and its side effects, reporting EACH outcome.

    A side-effect failure never rolls back the agent row: the agent exists and
    the failure is retryable. Reporting a bare success would hide it.

    `skills` and `side_effects` are normalized to their expected types BEFORE
    the agent is ever created. Without this, a truthy non-dict `side_effects`
    (e.g. a string) survives the route's `data.get("side_effects") or {}` and
    reaches `side_effects.get("budget")` below — OUTSIDE any try, AFTER the
    agent row and skills are already committed — raising AttributeError that
    propagates to the route's bare except -> 500. The agent then EXISTS in the
    DB while the caller is told it failed and never learns the id (an orphaned
    agent reported as a failure). Normalizing here makes the post-INSERT region
    structurally incapable of raising on envelope shape.
    """
    if not isinstance(side_effects, dict):
        side_effects = {}
    if not isinstance(skills, list):
        skills = []

    results = []
    if not skills:
        return {
            "ok": False,
            "agent_id": None,
            "results": [
                {
                    "step": "validate",
                    "ok": False,
                    "detail": "At least one skill is required — an agent with no skills is "
                    "structurally undispatchable.",
                }
            ],
        }

    try:
        agent_id = create_agent(
            fields["name"],
            fields["display_name"],
            fields["department"],
            fields["model"],
            **{k: v for k, v in fields.items() if k not in ("name", "display_name", "department", "model")},
        )
        results.append({"step": "agent", "ok": True, "detail": "agent id %s" % agent_id})
    except Exception as e:
        return {"ok": False, "agent_id": None, "results": [{"step": "agent", "ok": False, "detail": str(e)}]}

    try:
        for s in skills:
            _add_skill(agent_id, s["skill_name"], s.get("proficiency_level", 1), s.get("skill_category", "general"))
        results.append({"step": "skills", "ok": True, "detail": "%d skill(s)" % len(skills)})
    except Exception as e:
        results.append({"step": "skills", "ok": False, "detail": str(e)})

    if side_effects.get("budget"):
        try:
            _ensure_budget(agent_id)
            results.append({"step": "budget", "ok": True, "detail": "budget row created"})
        except Exception as e:
            results.append({"step": "budget", "ok": False, "detail": str(e)})

    if side_effects.get("portrait"):
        try:
            results.append({"step": "portrait", "ok": True, "detail": _queue_portrait(agent_id)})
        except Exception as e:
            results.append({"step": "portrait", "ok": False, "detail": str(e)})

    if side_effects.get("mailbox"):
        try:
            detail = _provision_mailbox(agent_id, fields)
            results.append({"step": "mailbox", "ok": True, "detail": detail})
        except Exception as e:
            results.append({"step": "mailbox", "ok": False, "detail": str(e)})

    return {"ok": True, "agent_id": agent_id, "results": results}
