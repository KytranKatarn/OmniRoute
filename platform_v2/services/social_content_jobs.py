"""Social content generation jobs — weekly schedule + platform event triggers.

Registered by app.py. All generation routes through S.I.G.N.A.L. via
/api/signal/dispatch (ADR-518).

Tenant context: Kytran Empowerment = tenant_9908, accounts linkedin=1 twitter=2.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# S.I.G.N.A.L. dispatch
_SIGNAL_URL = "http://localhost:3000/api/signal/dispatch"
_DRAFT_NOTIFY_URL = "http://localhost:3000/api/signal/draft-notify"
_API_KEY = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")

# Kytran Empowerment tenant
_KYTRAN_TENANT_ID = int(os.getenv("KBS_KYTRAN_TENANT_ID", "9908"))
_LINKEDIN_ACCOUNT_ID = int(os.getenv("KBS_KYTRAN_LINKEDIN_ID", "1"))
_TWITTER_ACCOUNT_ID = int(os.getenv("KBS_KYTRAN_TWITTER_ID", "2"))

_WEEKLY_TOPICS = [
    "A.R.C.H.I.E. platform update — what we shipped this week",
    "The power of AI-managed social media for small businesses",
    "Why your business needs an AI COO",
    "KBS — business management reimagined with AI",
    "Building a smarter business with autonomous AI agents",
]


def _dispatch_content(topic: str, platform: str, tone: str = "professional") -> str | None:
    """Call S.I.G.N.A.L. dispatch, return generated content or None on failure."""
    payload = json.dumps(
        {
            "capability": "social_content",
            "prompt": f"Write a social media post about: {topic}",
            "platform": platform,
            "tone": tone,
        }
    ).encode()
    try:
        req = urllib.request.Request(
            _SIGNAL_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {_API_KEY}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data.get("response", "").strip() or None
    except Exception as exc:
        logger.warning("social_content_jobs: dispatch failed for %r: %s", topic, exc)
        return None


def _save_draft(content: str, account_id: int, tenant_id: int) -> int | None:
    """INSERT a draft post into the tenant schema, return post id."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(f"SET search_path TO tenant_{tenant_id}, public")
            cur.execute(
                """INSERT INTO social_posts (account_id, content, status, created_at, updated_at)
                   VALUES (%s, %s, 'draft', NOW(), NOW()) RETURNING id""",
                (account_id, content),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as exc:
        logger.error("social_content_jobs: _save_draft failed: %s", exc)
        return None


def _notify_telegram(content: str, platform: str, account_name: str, draft_id: int, tenant_id: int) -> None:
    """Fire-and-forget Telegram notification for a draft."""
    payload = json.dumps(
        {
            "content": content,
            "platform": platform,
            "account_name": account_name,
            "draft_id": draft_id,
            "tenant_id": tenant_id,
        }
    ).encode()
    try:
        req = urllib.request.Request(
            _DRAFT_NOTIFY_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {_API_KEY}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as _:
            pass
    except Exception as exc:
        logger.warning("social_content_jobs: Telegram notify failed: %s", exc)


def generate_weekly_content() -> None:
    """Generate weekly content queue — runs Monday 08:00.

    Creates 3 LinkedIn + 2 Twitter drafts from rotating topic list and sends
    each to Telegram for Kytran's approval.
    """
    logger.info("[SocialJobs] Weekly content generation starting")

    topics = _WEEKLY_TOPICS
    now = datetime.now(timezone.utc)
    week_index = now.isocalendar()[1] % len(topics)
    selected = topics[week_index : week_index + 3] + topics[: max(0, week_index + 3 - len(topics))]
    selected = selected[:3]

    tasks = [
        (selected[0], "linkedin", _LINKEDIN_ACCOUNT_ID, "Kytran Katarn", "professional"),
        (selected[1], "linkedin", _LINKEDIN_ACCOUNT_ID, "Kytran Katarn", "bold"),
        (selected[2], "linkedin", _LINKEDIN_ACCOUNT_ID, "Kytran Katarn", "casual"),
        (selected[0], "twitter", _TWITTER_ACCOUNT_ID, "Kytran", "bold"),
        (selected[1], "twitter", _TWITTER_ACCOUNT_ID, "Kytran", "casual"),
    ]

    drafted = 0
    for topic, platform, account_id, account_name, tone in tasks:
        content = _dispatch_content(topic, platform, tone)
        if not content:
            continue
        draft_id = _save_draft(content, account_id, _KYTRAN_TENANT_ID)
        if draft_id:
            _notify_telegram(content, platform, account_name, draft_id, _KYTRAN_TENANT_ID)
            drafted += 1

    logger.info("[SocialJobs] Weekly content done — %d drafts queued", drafted)


def generate_event_draft(topic: str, platform: str = "both", tone: str = "professional") -> None:
    """Generate a draft triggered by a platform event (PR merge, milestone, etc.).

    Called by event listeners in app.py.
    """
    logger.info("[SocialJobs] Event-triggered draft: %r on %s", topic, platform)

    platforms = ["linkedin", "twitter"] if platform == "both" else [platform]
    account_map = {"linkedin": (_LINKEDIN_ACCOUNT_ID, "Kytran Katarn"), "twitter": (_TWITTER_ACCOUNT_ID, "Kytran")}

    for plat in platforms:
        content = _dispatch_content(topic, plat, tone)
        if not content:
            continue
        account_id, account_name = account_map[plat]
        draft_id = _save_draft(content, account_id, _KYTRAN_TENANT_ID)
        if draft_id:
            _notify_telegram(content, plat, account_name, draft_id, _KYTRAN_TENANT_ID)


_KBS_URL = os.getenv("KBS_APP_URL", "http://kbs_app:8090")
# #6657: the KBS bearer gets its own name; falls back to the comms token until KBS reads KBS_SERVICE_TOKEN.
_COMMS_TOKEN = os.getenv("KBS_SERVICE_TOKEN") or os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")


def _call_kbs_maintenance(endpoint: str) -> dict:
    """POST to a KBS maintenance endpoint with service token auth."""
    import json as _json

    url = f"{_KBS_URL}{endpoint}"
    try:
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {_COMMS_TOKEN}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _json.loads(resp.read())
    except Exception as exc:
        logger.warning("[SocialJobs] KBS %s failed: %s", endpoint, exc)
        return {}


def refresh_social_tokens() -> None:
    """Refresh expiring OAuth tokens for all tenants — runs every 90 minutes."""
    logger.info("[SocialJobs] Token refresh starting")
    # KBS plugins are registered at /plugins/{slug}
    result = _call_kbs_maintenance("/plugins/social-media/api/social/refresh-tokens")
    logger.info(
        "[SocialJobs] Token refresh done — refreshed=%s errors=%s", result.get("refreshed", 0), result.get("errors", 0)
    )


def publish_scheduled_posts() -> None:
    """Publish due scheduled posts — runs every 5 minutes."""
    result = _call_kbs_maintenance("/plugins/social-media/api/social/publish-scheduled")
    published = result.get("published", 0)
    if published:
        logger.info("[SocialJobs] Scheduled publisher: %d posts published", published)


def register_social_content_jobs(scheduler) -> None:
    """Register all social content jobs with APScheduler."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler.add_job(
        generate_weekly_content,
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0, jitter=300, timezone="America/Toronto"),
        id="signal_weekly_content",
        name="Agent Loop: S.I.G.N.A.L. Weekly Content Queue",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        refresh_social_tokens,
        trigger=IntervalTrigger(minutes=90),
        id="social_token_refresh",
        name="Agent Loop: Social Token Refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        publish_scheduled_posts,
        trigger=IntervalTrigger(minutes=5),
        id="social_publish_scheduled",
        name="Agent Loop: Social Scheduled Publisher",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("[SocialJobs] Registered: weekly content + token refresh (90m) + scheduled publisher (5m)")
