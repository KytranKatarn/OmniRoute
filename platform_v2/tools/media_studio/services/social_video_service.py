"""
Social Video Service — Queue & Template Logic
Core business logic for the Social Video Engine.
All DB access for social content goes through here.
"""

import json
import os
import random
from datetime import datetime

from database import get_db_cursor

# Constants
AUTO_APPROVE_THRESHOLD = 3
SOCIAL_VIDEO_DAILY_BUDGET = float(os.getenv("SOCIAL_VIDEO_DAILY_BUDGET", "5.00"))
SOCIAL_VIDEO_MONTHLY_BUDGET = float(os.getenv("SOCIAL_VIDEO_MONTHLY_BUDGET", "50.00"))

# Content types that bypass auto-approval logic
_ALWAYS_MANUAL = {"employer_branding", "recruitment"}
_ALWAYS_AUTO = {"motivational"}


# ---------------------------------------------------------------------------
# Template operations
# ---------------------------------------------------------------------------


def get_templates(content_type=None, active_only=True):
    """Return list of dicts from social_content_templates with optional filters."""
    conditions = []
    params = []

    if active_only:
        conditions.append("is_active = true")
    if content_type:
        conditions.append("content_type = %s")
        params.append(content_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM social_content_templates {where} ORDER BY content_type, name"

    with get_db_cursor() as (conn, cur):
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_template(template_id):
    """Return a single template dict by ID, or None if not found."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM social_content_templates WHERE id = %s", (template_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


def render_template(template_id, variables):
    """
    Fetch template and replace {placeholder} tokens with values from variables dict.
    Returns dict with rendered prompt, caption, hashtags, video_params,
    style_directive, platforms, approval_tier.
    """
    template = get_template(template_id)
    if template is None:
        raise ValueError(f"Template {template_id} not found")

    def _replace(text):
        if not text:
            return text
        for key, value in variables.items():
            text = text.replace("{" + key + "}", str(value))
        return text

    return {
        "prompt": _replace(template.get("prompt_template", "")),
        "caption": _replace(template.get("caption_template", "")),
        "hashtags": template.get("hashtags", []),
        "video_params": template.get("video_params", {}),
        "style_directive": template.get("style_directive", ""),
        "platforms": template.get("platforms", []),
        "approval_tier": template.get("approval_tier", "manual"),
    }


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------


def create_queue_item(
    content_type,
    prompt,
    caption="",
    hashtags=None,
    target_platforms=None,
    agent_id=None,
    template_id=None,
    approval_tier="manual",
    generation_params=None,
    created_by="manual",
    scheduled_at=None,
):
    """INSERT a new item into social_content_queue, returning the created row as dict."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO social_content_queue (
                content_type, prompt, caption, hashtags, target_platforms,
                agent_id, template_id, approval_tier, generation_params,
                created_by, scheduled_at, status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, 'pending', NOW(), NOW()
            )
            RETURNING *
            """,
            (
                content_type,
                prompt,
                caption,
                json.dumps(hashtags or []),
                json.dumps(target_platforms or []),
                agent_id,
                template_id,
                approval_tier,
                json.dumps(generation_params or {}),
                created_by,
                scheduled_at,
            ),
        )
        row = cur.fetchone()
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


def get_queue_items(status=None, content_type=None, limit=50, offset=0):
    """Return list of queue items with agent display_name, newest first."""
    conditions = []
    params = []

    if status:
        conditions.append("q.status = %s")
        params.append(status)
    if content_type:
        conditions.append("q.content_type = %s")
        params.append(content_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    sql = f"""
        SELECT q.*, a.display_name AS agent_display_name
        FROM social_content_queue q
        LEFT JOIN agents a ON q.agent_id = a.id
        {where}
        ORDER BY q.created_at DESC
        LIMIT %s OFFSET %s
    """

    with get_db_cursor() as (conn, cur):
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_queue_item(item_id):
    """Return a single queue item with agent display_name, or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT q.*, a.display_name AS agent_display_name
            FROM social_content_queue q
            LEFT JOIN agents a ON q.agent_id = a.id
            WHERE q.id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


_ALLOWED_UPDATE_FIELDS = {
    "caption",
    "hashtags",
    "target_platforms",
    "status",
    "scheduled_at",
    "video_path",
    "thumbnail_path",
    "post_urls",
    "rejection_reason",
    "cloud_cost",
    "posted_at",
}


def update_queue_item(item_id, **kwargs):
    """
    Update whitelisted fields on a queue item.
    Auto-sets updated_at. Returns updated row dict, or None if not found / no valid fields.
    """
    fields = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not fields:
        return None

    set_clauses = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [item_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""
            UPDATE social_content_queue
            SET {set_clauses}, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            values,
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def approve_item(item_id):
    """Approve a queue item; increment approval count if agent_id is set."""
    item = update_queue_item(item_id, status="approved")
    if item and item.get("agent_id"):
        _increment_approval_count(item["agent_id"], item["content_type"])
    return item


def reject_item(item_id, reason=""):
    """Reject a queue item with an optional reason."""
    return update_queue_item(item_id, status="rejected", rejection_reason=reason)


def schedule_item(item_id, scheduled_at):
    """Mark a queue item as scheduled with a target datetime."""
    return update_queue_item(item_id, status="scheduled", scheduled_at=scheduled_at)


# ---------------------------------------------------------------------------
# Auto-approval
# ---------------------------------------------------------------------------


def _increment_approval_count(agent_id, content_type):
    """
    UPSERT into social_content_approvals.
    Sets auto_approved=true when count reaches AUTO_APPROVE_THRESHOLD.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO social_content_approvals (agent_id, content_type, approval_count, auto_approved)
            VALUES (%s, %s, 1, false)
            ON CONFLICT (agent_id, content_type) DO UPDATE
                SET approval_count = social_content_approvals.approval_count + 1,
                    updated_at = NOW()
            """,
            (agent_id, content_type),
        )
        # Flip auto_approved flag when threshold reached
        cur.execute(
            """
            UPDATE social_content_approvals
            SET auto_approved = true
            WHERE agent_id = %s AND content_type = %s
              AND approval_count >= %s
            """,
            (agent_id, content_type, AUTO_APPROVE_THRESHOLD),
        )


def should_auto_approve(agent_id, content_type):
    """
    Determine whether content should skip manual review.
    - employer_branding / recruitment → always False
    - motivational → always True
    - agent_moment → check social_content_approvals.auto_approved
    """
    if content_type in _ALWAYS_MANUAL:
        return False
    if content_type in _ALWAYS_AUTO:
        return True

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT auto_approved FROM social_content_approvals
            WHERE agent_id = %s AND content_type = %s
            """,
            (agent_id, content_type),
        )
        row = cur.fetchone()
        return bool(row and row[0])


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------


def check_budget():
    """
    Compare today's and this month's GPU spend against configured limits.
    Returns dict: daily_spent, monthly_spent, daily_remaining, monthly_remaining, can_generate.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT
                COALESCE(SUM(cost) FILTER (WHERE created_at::date = CURRENT_DATE), 0) AS daily_spent,
                COALESCE(SUM(cost) FILTER (WHERE date_trunc('month', created_at) = date_trunc('month', NOW())), 0) AS monthly_spent
            FROM cloud_gpu_usage
            """
        )
        row = cur.fetchone()
        daily_spent = float(row[0])
        monthly_spent = float(row[1])

    daily_remaining = max(0.0, SOCIAL_VIDEO_DAILY_BUDGET - daily_spent)
    monthly_remaining = max(0.0, SOCIAL_VIDEO_MONTHLY_BUDGET - monthly_spent)
    can_generate = daily_remaining > 0 and monthly_remaining > 0

    return {
        "daily_spent": daily_spent,
        "monthly_spent": monthly_spent,
        "daily_remaining": daily_remaining,
        "monthly_remaining": monthly_remaining,
        "can_generate": can_generate,
    }


def log_gpu_usage(provider, job_type, cost, gpu_seconds=None, metadata=None):
    """INSERT a cloud GPU usage record."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO cloud_gpu_usage (provider, job_type, cost, gpu_seconds, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (
                provider,
                job_type,
                cost,
                gpu_seconds,
                json.dumps(metadata or {}),
            ),
        )
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pick_agent_for_content(content_type):
    """
    Select a random active agent suitable for content generation.
    Returns a single agent dict, or None if no active agents found.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, name, display_name, department, personality, backstory, skill_category
            FROM agents
            WHERE shift_state = 'active' AND is_active = true
            ORDER BY RANDOM()
            LIMIT 5
            """
        )
        cols = [d.name for d in cur.description]
        candidates = [dict(zip(cols, row)) for row in cur.fetchall()]

    if not candidates:
        return None
    return random.choice(candidates)


def get_queue_stats():
    """
    Return summary stats:
      - status_counts: {status: count}
      - posted_this_week: int
      - monthly_cost: float
    """
    with get_db_cursor() as (conn, cur):
        # Status counts
        cur.execute("SELECT status, COUNT(*) FROM social_content_queue GROUP BY status")
        status_counts = {row[0]: row[1] for row in cur.fetchall()}

        # Posted this week
        cur.execute(
            """
            SELECT COUNT(*) FROM social_content_queue
            WHERE posted_at >= NOW() - INTERVAL '7 days'
            """
        )
        posted_this_week = cur.fetchone()[0]

        # Monthly cloud cost
        cur.execute(
            """
            SELECT COALESCE(SUM(cloud_cost), 0)
            FROM social_content_queue
            WHERE date_trunc('month', created_at) = date_trunc('month', NOW())
            """
        )
        monthly_cost = float(cur.fetchone()[0])

    return {
        "status_counts": status_counts,
        "posted_this_week": posted_this_week,
        "monthly_cost": monthly_cost,
    }
