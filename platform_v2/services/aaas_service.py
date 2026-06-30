"""Agent-as-a-Service (AaaS) — order lifecycle + concierge build worker.

Project #297. Backs migration 443 (aaas_orders + agents.org_id). Decisions:
ADR #869 (deliverable = hosted ARCHIE agent + API/KBS), ADR #870 (build params:
Accessible-SMB pricing, reuse worker_type='ai'+org_id, CONCIERGE build trigger).

This module owns the `aaas_orders` table (order CRUD + lifecycle transitions) and
the concierge `build_order()` pipeline that turns a paid order into a live, hosted,
org-isolated agent. All agent mutations go through `agent_service` (single-writer
guardrail) — never raw SQL on `agents` here.

Concierge model (ADR #870): payment parks an order at 'paid_build'; the owner
reviews the brief and explicitly calls build_order(). build_order REFUSES to run on
anything other than a 'paid_build' order — there is no auto-drain on a schedule.
"""

import logging

from database import get_db_cursor
from services import agent_service

logger = logging.getLogger(__name__)

# --- tier → build parameters (ADR #870, Accessible SMB) -----------------------
# amount/price live in billing_product_plans (migration 443); these drive the
# BUILD (model size, proficiency tier, daily token + queue budget) per tier.
TIER_MODEL = {
    "starter": "qwen2.5:1.5b",
    "pro": "qwen2.5:7b",
    "enterprise": "gemma3:12b",
}
TIER_LEVEL = {"starter": 1, "pro": 2, "enterprise": 2}
TIER_TOKEN_LIMIT = {"starter": 50_000, "pro": 150_000, "enterprise": 300_000}
TIER_QUEUE_LIMIT = {"starter": 20, "pro": 50, "enterprise": 100}

# Public-facing tier display metadata (design §9, ADR #870). Monthly price is read
# live from billing_product_plans (single source of truth, migration 443); build
# fee + channels live here since they are not columns on that table. enterprise
# build fee is a custom quote (None → "Custom"). Drives the commissioning page (#2474).
TIER_ORDER = ("starter", "pro", "enterprise")
_TIER_DISPLAY = {
    "starter": {
        "label": "Starter",
        "build_fee_cents": 49900,
        "monthly_fallback_cents": 4900,
        "channels": ["API access"],
        "blurb": "A focused assistant for one job — answered fast, hosted on ARCHIE.",
    },
    "pro": {
        "label": "Pro",
        "build_fee_cents": 149900,
        "monthly_fallback_cents": 14900,
        "channels": ["API access", "KBS embed", "Email mailbox"],
        "blurb": "A capable 7B agent with your knowledge base, embeddable in your site.",
    },
    "enterprise": {
        "label": "Enterprise",
        "build_fee_cents": None,  # custom quote
        "monthly_fallback_cents": 49900,
        "channels": ["All channels", "Custom knowledge base", "SLA"],
        "blurb": "A large custom agent, all delivery channels, and a service-level agreement.",
    },
}


def get_public_tiers():
    """Return ordered tier display data for the public commissioning page (#2474).

    Monthly amount is sourced live from billing_product_plans (product_id='aaas');
    falls back to the design literal if a row is missing. No auth — safe for public.
    """
    monthly = {}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT tier_name, amount_cents FROM billing_product_plans WHERE product_id = 'aaas'")
            for row in cur.fetchall():
                monthly[row["tier_name"]] = row["amount_cents"]
    except Exception:  # noqa: BLE001 — display must never 500 the public page
        logger.exception("get_public_tiers: billing_product_plans read failed; using fallbacks")

    tiers = []
    for key in TIER_ORDER:
        d = _TIER_DISPLAY[key]
        tiers.append(
            {
                "tier": key,
                "label": d["label"],
                "model": TIER_MODEL[key],
                "build_fee_cents": d["build_fee_cents"],
                "monthly_cents": monthly.get(key, d["monthly_fallback_cents"]),
                "channels": d["channels"],
                "blurb": d["blurb"],
                "token_limit": TIER_TOKEN_LIMIT[key],
            }
        )
    return tiers


# Client agents live in the internal department structure (for the skill/dispatch
# machinery) but are isolated by org_id. Most client bots are support-shaped;
# the brief can override with any valid department.
DEFAULT_DEPARTMENT = "Customer Success & Support"

# Lifecycle states -> their dedicated timestamp column (NULL = no dedicated column).
STATUS_TS_COLUMN = {
    "submitted": "submitted_at",
    "quoted": "quoted_at",
    "paid_build": "paid_build_at",
    "building": "building_at",
    "qa_review": "qa_review_at",
    "client_review": "client_review_at",
    "live": "live_at",
    "offboarded": "offboarded_at",
    # renewing / suspended / build_failed: status only, no timestamp column
}
VALID_STATUSES = set(STATUS_TS_COLUMN) | {"renewing", "suspended", "build_failed"}


# ---------------------------------------------------------------------------
# Order CRUD
# ---------------------------------------------------------------------------
def create_order(
    contact_email,
    *,
    tier="starter",
    brief=None,
    contact_name=None,
    company_name=None,
    org_id=None,
    build_fee_cents=None,
    monthly_cents=None,
    currency="CAD",
    status="submitted",
):
    """Create a commissioning order. Returns order_id.

    `brief` is the normalized agent brief (dict, stored as JSONB).
    """
    import json

    if tier not in TIER_MODEL:
        raise ValueError(f"Invalid tier: {tier}")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO aaas_orders
                   (org_id, contact_email, contact_name, company_name, tier,
                    brief, status, build_fee_cents, monthly_cents, currency)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
               RETURNING id""",
            (
                org_id,
                contact_email,
                contact_name,
                company_name,
                tier,
                json.dumps(brief or {}),
                status,
                build_fee_cents,
                monthly_cents,
                currency,
            ),
        )
        order_id = cur.fetchone()["id"]
    logger.info("AaaS order #%d created (tier=%s, email=%s)", order_id, tier, contact_email)
    return order_id


def get_order(order_id):
    """Return the order row as a dict, or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM aaas_orders WHERE id = %s", (order_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_orders(status=None, limit=50):
    """List orders, newest first, optionally filtered by status."""
    with get_db_cursor() as (conn, cur):
        if status:
            cur.execute(
                "SELECT * FROM aaas_orders WHERE status = %s ORDER BY id DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute("SELECT * FROM aaas_orders ORDER BY id DESC LIMIT %s", (limit,))
        return [dict(r) for r in cur.fetchall()]


def advance_status(order_id, status):
    """Set an order's status, stamping the matching *_at column on first entry.

    The timestamp column is COALESCE'd so re-entering a state keeps the original
    transition time. updated_at always refreshes.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    ts_col = STATUS_TS_COLUMN.get(status)
    with get_db_cursor(commit=True) as (conn, cur):
        if ts_col:
            cur.execute(
                f"""UPDATE aaas_orders
                       SET status = %s,
                           {ts_col} = COALESCE({ts_col}, now()),
                           updated_at = now()
                     WHERE id = %s""",
                (status, order_id),
            )
        else:
            cur.execute(
                "UPDATE aaas_orders SET status = %s, updated_at = now() WHERE id = %s",
                (status, order_id),
            )
    logger.info("AaaS order #%d -> %s", order_id, status)


def attach_built_agent(order_id, agent_id):
    """Link the built agent back onto its order."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE aaas_orders SET built_agent_id = %s, updated_at = now() WHERE id = %s",
            (agent_id, order_id),
        )


def _record_failure(order_id, message):
    """Mark an order build_failed and append the error to notes (non-destructive)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE aaas_orders
                   SET status = 'build_failed',
                       notes = COALESCE(notes || E'\\n', '') || %s,
                       updated_at = now()
                 WHERE id = %s""",
            (f"[build_failed] {message}"[:1000], order_id),
        )


# ---------------------------------------------------------------------------
# Brief normalization
# ---------------------------------------------------------------------------
def normalize_brief(raw, tier):
    """Resolve the raw client brief + tier into a concrete build spec.

    Fills model / proficiency tier / budget from the tier; validates department;
    derives skills from capabilities when skills aren't given explicitly.
    """
    raw = dict(raw or {})
    department = raw.get("department") or DEFAULT_DEPARTMENT
    if department not in agent_service.DEPARTMENT_FLOOR_MAP:
        department = DEFAULT_DEPARTMENT

    skills = raw.get("skills") or []
    capabilities = raw.get("capabilities") or [s.get("skill_name") for s in skills if s.get("skill_name")]
    if not skills:
        skills = [{"skill_name": c, "level": 4, "category": "client"} for c in capabilities]

    return {
        "agent_name": raw.get("agent_name"),
        "display_name": raw.get("display_name") or raw.get("agent_name"),
        "title": raw.get("title"),
        "acronym_expansion": raw.get("acronym_expansion"),
        "department": department,
        "model": TIER_MODEL[tier],
        "tier_level": TIER_LEVEL[tier],
        "system_prompt": raw.get("system_prompt") or "",
        "capabilities": capabilities,
        "skills": skills,
        "accent_color": raw.get("accent_color") or "#3b82f6",
        "token_limit": TIER_TOKEN_LIMIT[tier],
        "queue_limit": TIER_QUEUE_LIMIT[tier],
    }


# ---------------------------------------------------------------------------
# Concierge build worker
# ---------------------------------------------------------------------------
def build_order(order_id):
    """Concierge build: turn a 'paid_build' order into a live, org-isolated agent.

    Refuses any order not in 'paid_build' (ADR #870 — no auto-drain). Every agent
    mutation goes through agent_service (single-writer). Tenancy is MANDATORY: the
    order must carry an org_id, otherwise the built agent would have org_id=NULL and
    be treated as an INTERNAL agent (leak). On any failure the order is marked
    build_failed with the error recorded; a partially-built agent (if create
    succeeded) is still linked so the owner can inspect/clean it.

    Returns {"ok": bool, "agent_id": int|None, "status": str, "error": str|None}.
    Portrait + mailbox provisioning are deferred follow-ups (not blocking a usable
    hosted agent); creed_tenant is left NULL (CREED default) until per-client tenant
    registration is wired.
    """
    order = get_order(order_id)
    if not order:
        return {"ok": False, "agent_id": None, "status": None, "error": "order_not_found"}
    if order["status"] != "paid_build":
        return {
            "ok": False,
            "agent_id": None,
            "status": order["status"],
            "error": f"order not in paid_build (status={order['status']})",
        }
    if not order.get("org_id"):
        return {
            "ok": False,
            "agent_id": None,
            "status": order["status"],
            "error": "order has no org_id — tenancy is required for a client agent",
        }

    tier = order["tier"]
    brief = normalize_brief(order.get("brief") or {}, tier)
    if not brief.get("agent_name"):
        return {"ok": False, "agent_id": None, "status": order["status"], "error": "brief missing agent_name"}

    advance_status(order_id, "building")
    agent_id = None
    try:
        agent_id = agent_service.create_agent(
            name=brief["agent_name"],
            display_name=brief["display_name"],
            department=brief["department"],
            model=brief["model"],
            worker_type="ai",
            shift_state="active",
            system_prompt=brief["system_prompt"],
            capabilities={c: True for c in brief["capabilities"]},
            tier=brief["tier_level"],
            is_department_ai=False,
        )

        # Tenancy (MANDATORY) + persona. org_id isolates the agent from internal
        # dispatch (get_agent_cache filters org_id IS NULL).
        persona = {"org_id": order["org_id"]}
        if brief.get("title"):
            persona["title"] = brief["title"]
        if brief.get("acronym_expansion"):
            persona["acronym_expansion"] = brief["acronym_expansion"]
        agent_service.update_agent(agent_id, **persona)

        # Daily budget (create_agent does not make one).
        agent_service.init_budget(
            agent_id,
            token_limit=brief["token_limit"],
            task_queue_limit=brief["queue_limit"],
        )

        # Skills — dispatch/capability matching keys on agent_skills.skill_name.
        for skill in brief["skills"]:
            name = skill.get("skill_name")
            if name:
                agent_service.add_skill(
                    agent_id,
                    name,
                    level=int(skill.get("level", 4)),
                    category=skill.get("category", "client"),
                )

        attach_built_agent(order_id, agent_id)
        advance_status(order_id, "qa_review")
        logger.info("AaaS order #%d built agent #%d (%s)", order_id, agent_id, brief["agent_name"])
        return {"ok": True, "agent_id": agent_id, "status": "qa_review", "error": None}

    except Exception as exc:  # noqa: BLE001 — record + surface, never silently drop
        logger.exception("AaaS build failed for order #%s", order_id)
        if agent_id:
            try:
                attach_built_agent(order_id, agent_id)
            except Exception:  # noqa: BLE001
                pass
        _record_failure(order_id, str(exc))
        return {"ok": False, "agent_id": agent_id, "status": "build_failed", "error": str(exc)}
