"""
Social Video Service — Queue & Template Logic
Core business logic for the Social Video Engine.
All DB access for social content goes through here.
"""

import json
import os
import random

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
        return [dict(row) for row in cur.fetchall()]


def get_template(template_id):
    """Return a single template dict by ID, or None if not found."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM social_content_templates WHERE id = %s", (template_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)


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
                %s, %s, 'draft', NOW(), NOW()
            )
            RETURNING *
            """,
            (
                content_type,
                prompt,
                caption,
                hashtags or [],
                target_platforms or [],
                agent_id,
                template_id,
                approval_tier,
                json.dumps(generation_params or {}),
                created_by,
                scheduled_at,
            ),
        )
        row = cur.fetchone()
        return dict(row)


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
        return [dict(row) for row in cur.fetchall()]


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
        return dict(row)


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
        return dict(row)


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
        return bool(row and row["auto_approved"])


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
        daily_spent = float(row["daily_spent"])
        monthly_spent = float(row["monthly_spent"])

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
        return cur.fetchone()["id"]


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
            WHERE shift_state = 'active' AND status = 'active'
            ORDER BY RANDOM()
            LIMIT 5
            """
        )
        candidates = [dict(row) for row in cur.fetchall()]

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
        status_counts = {row["status"]: row["count"] for row in cur.fetchall()}

        # Posted this week
        cur.execute(
            """
            SELECT COUNT(*) FROM social_content_queue
            WHERE posted_at >= NOW() - INTERVAL '7 days'
            """
        )
        posted_this_week = cur.fetchone()["count"]

        # Monthly cloud cost
        cur.execute(
            """
            SELECT COALESCE(SUM(cloud_cost), 0) AS monthly_cost
            FROM social_content_queue
            WHERE date_trunc('month', created_at) = date_trunc('month', NOW())
            """
        )
        monthly_cost = float(cur.fetchone()["monthly_cost"])

    return {
        "status_counts": status_counts,
        "posted_this_week": posted_this_week,
        "monthly_cost": monthly_cost,
    }


# ---------------------------------------------------------------------------
# AutoShorts social_video_queue (separate from social_content_queue)
# ---------------------------------------------------------------------------

from typing import Dict, List, Optional

_VALID_SVQ_STATUSES = ("draft", "rendering", "pending_approval", "scheduled", "posted", "failed")


def svq_list(status: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Return social_video_queue items ordered by creation date desc."""
    with get_db_cursor() as (conn, cur):
        if status:
            cur.execute(
                "SELECT * FROM social_video_queue WHERE status = %s " "ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM social_video_queue ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        result.append(d)
    return result


def svq_create(
    title: str,
    quote_text: str,
    media_ids: List[int],
    audio_mode: str,
    platform: str,
    scheduled_at: Optional[str],
    user_id: int,
    theme_id: Optional[int] = None,
) -> Dict:
    """Insert a new social_video_queue item. Status is 'scheduled' if scheduled_at set, else 'draft'."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO social_video_queue
               (title, quote_text, media_ids, audio_mode, platform,
                scheduled_at, status, created_by, theme_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, status, created_at""",
            (
                title,
                quote_text,
                media_ids,
                audio_mode,
                platform,
                scheduled_at,
                "scheduled" if scheduled_at else "draft",
                user_id,
                theme_id,
            ),
        )
        row = cur.fetchone()
    d = dict(row)
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d


def svq_update_status(item_id: int, status: str) -> bool:
    """Update social_video_queue item status. Returns False if invalid status or item not found."""
    if status not in _VALID_SVQ_STATUSES:
        return False
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE social_video_queue SET status = %s WHERE id = %s",
            (status, item_id),
        )
        return cur.rowcount > 0


def svq_get_renderable(limit: int = 3) -> list:
    """Return draft items with media_ids set, ready to render."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT * FROM social_video_queue
               WHERE status = 'draft' AND media_ids IS NOT NULL AND array_length(media_ids, 1) > 0
               ORDER BY created_at ASC LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def svq_start_render(item_id: int) -> bool:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE social_video_queue SET status = 'rendering' WHERE id = %s AND status = 'draft'",
            (item_id,),
        )
        return cur.rowcount > 0


def svq_finish_render(item_id: int, video_path: str, thumbnail_path: str) -> bool:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE social_video_queue
               SET status = 'pending_approval', video_path = %s, thumbnail_path = %s
               WHERE id = %s""",
            (video_path, thumbnail_path, item_id),
        )
        return cur.rowcount > 0


def svq_fail_render(item_id: int, error: str) -> bool:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE social_video_queue SET status = 'failed', error_message = %s WHERE id = %s",
            (error[:500], item_id),
        )
        return cur.rowcount > 0
