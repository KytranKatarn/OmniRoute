"""S.I.G.N.A.L. content calendar — Phase 1: backfill + scheduled queue (#3989).

Calendar store = agent_content_posts (platform='linkedin', status='scheduled',
scheduled_at stored as naive UTC per platform convention). Account scoping
lives in post_type ('personal' | 'terry' | 'company' | 'creed'); the owning
identity row is agents.id 342 (Kytran) for personal/company/creed and 377
(Terry Caetano) for terry — the same identities the posting path uses.

Backfill gathers the failed linkedin_post_log backlog plus approved-but-unsent
creed marketing assets, dedupes by content hash (the ~40 failed rows are mostly
retry artifacts of the broken-session window), drops anything already posted /
pending approval / scheduled, and fans the unique remainder forward 1 post per
day per account at 09:00 America/Toronto. Forward-only: LinkedIn cannot
backdate. Release to the approval queue is Phase 2 — nothing here publishes.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from database import get_db_cursor

logger = logging.getLogger("platform.signal_calendar")

_LOCAL_TZ = ZoneInfo("America/Toronto")
RELEASE_HOUR_LOCAL = 9  # 09:00 ET, converted to UTC at insert

ACCOUNTS = ("personal", "terry", "company", "creed")

_POST_TYPE_TO_ACCOUNT = {
    "personal": "personal",
    "terry": "terry",
    "company": "company",
    "company_page": "company",
    "creed": "creed",
    "creed_ai": "creed",
}

_ACCOUNT_TO_POST_TYPES = {
    "personal": ("personal",),
    "terry": ("terry",),
    "company": ("company", "company_page"),
    "creed": ("creed", "creed_ai"),
}

_ACCOUNT_AGENT_ID = {"personal": 342, "terry": 377, "company": 342, "creed": 342}


def _fold(content: Optional[str], hashtags: Any) -> str:
    """Canonical post text: content with hashtags appended, stripped."""
    text = (content or "").strip()
    tags = [t for t in (hashtags or []) if t]
    if tags:
        text += "\n\n" + " ".join(f"#{str(t).lstrip('#')}" for t in tags)
    return text


def _hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def _seen_hashes(cur) -> set:
    """Content hashes that must NOT be scheduled again: already posted,
    already pending/approved in the queue, or already on the calendar."""
    seen = set()
    cur.execute("SELECT content, hashtags FROM linkedin_post_log WHERE status = 'posted'")
    for row in cur.fetchall():
        seen.add(_hash(_fold(row["content"], row["hashtags"])))
    cur.execute(
        """SELECT action_data FROM autonomy_approval_queue
           WHERE action_type = 'linkedin_post' AND status IN ('pending', 'approved')"""
    )
    for row in cur.fetchall():
        data = row["action_data"] or {}
        seen.add(_hash(_fold(data.get("content"), data.get("hashtags"))))
    cur.execute(
        """SELECT content FROM agent_content_posts
           WHERE platform = 'linkedin' AND status IN ('scheduled', 'released')"""
    )
    for row in cur.fetchall():
        seen.add(_hash(row["content"]))
    return seen


def _candidates(cur) -> List[Dict[str, Any]]:
    """Backlog candidates, newest first: failed post-log rows + approved
    unsent creed linkedin assets."""
    out: List[Dict[str, Any]] = []
    cur.execute(
        """SELECT content, hashtags, post_type, created_at
           FROM linkedin_post_log WHERE status = 'failed'
           ORDER BY created_at DESC"""
    )
    for row in cur.fetchall():
        account = _POST_TYPE_TO_ACCOUNT.get((row["post_type"] or "personal").lower())
        if account:
            out.append({"account": account, "text": _fold(row["content"], row["hashtags"])})
    cur.execute(
        """SELECT content FROM creed_marketing_assets
           WHERE approved = TRUE AND gen_status = 'done' AND channel = 'linkedin'
             AND content IS NOT NULL
           ORDER BY created_at DESC"""
    )
    for row in cur.fetchall():
        out.append({"account": "creed", "text": _fold(row["content"], None)})
    return out


def _next_slot_utc(cur, account: str) -> datetime:
    """First free calendar day for ``account``: the later of tomorrow and the
    day after its last scheduled slot, at 09:00 ET (returned as naive UTC)."""
    post_types = _ACCOUNT_TO_POST_TYPES[account]
    cur.execute(
        """SELECT MAX(scheduled_at) AS last FROM agent_content_posts
           WHERE platform = 'linkedin' AND status = 'scheduled'
             AND post_type = ANY(%s)""",
        (list(post_types),),
    )
    last = (cur.fetchone() or {}).get("last")
    today_local = datetime.now(_LOCAL_TZ).date()
    start_local = today_local + timedelta(days=1)
    if last is not None:
        last_local = last.replace(tzinfo=ZoneInfo("UTC")).astimezone(_LOCAL_TZ).date()
        start_local = max(start_local, last_local + timedelta(days=1))
    slot_local = datetime.combine(
        start_local, datetime.min.time().replace(hour=RELEASE_HOUR_LOCAL), tzinfo=_LOCAL_TZ
    )
    return slot_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def backfill_calendar() -> Dict[str, Any]:
    """One-shot: dedup the backlog and fan it onto each account's calendar,
    1/day starting tomorrow. Idempotent — re-runs only append genuinely new
    content after the account's last scheduled slot."""
    summary: Dict[str, Any] = {a: {"scheduled": 0, "skipped_dupe": 0} for a in ACCOUNTS}
    with get_db_cursor(commit=True) as (_conn, cur):
        seen = _seen_hashes(cur)
        slots = {a: _next_slot_utc(cur, a) for a in ACCOUNTS}
        for cand in _candidates(cur):
            account, text = cand["account"], cand["text"]
            if not text:
                continue
            h = _hash(text)
            if h in seen:
                summary[account]["skipped_dupe"] += 1
                continue
            seen.add(h)
            cur.execute(
                """INSERT INTO agent_content_posts
                       (agent_id, platform, content, post_type, status, scheduled_at)
                   VALUES (%s, 'linkedin', %s, %s, 'scheduled', %s)""",
                (
                    _ACCOUNT_AGENT_ID[account],
                    text,
                    _ACCOUNT_TO_POST_TYPES[account][0],
                    slots[account],
                ),
            )
            summary[account]["scheduled"] += 1
            slots[account] += timedelta(days=1)
    total = sum(v["scheduled"] for v in summary.values())
    logger.info("[signal-calendar] backfill scheduled %s post(s): %s", total, summary)
    return {"total_scheduled": total, "by_account": summary}


def get_scheduled(account: str, limit: int = 60) -> List[Dict[str, Any]]:
    """Scheduled (not yet released) calendar entries for one account."""
    post_types = _ACCOUNT_TO_POST_TYPES.get(account, (account,))
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id, content, post_type, status, scheduled_at, created_at
               FROM agent_content_posts
               WHERE platform = 'linkedin' AND status = 'scheduled'
                 AND post_type = ANY(%s)
               ORDER BY scheduled_at ASC
               LIMIT %s""",
            (list(post_types), limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k in ("scheduled_at", "created_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return rows


def cancel_scheduled(post_id: int) -> bool:
    """Cancel one scheduled entry (owner pruning stale backlog content)."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE agent_content_posts SET status = 'cancelled'
               WHERE id = %s AND status = 'scheduled'
               RETURNING id""",
            (post_id,),
        )
        return cur.fetchone() is not None


_ACCOUNT_LABEL = {
    "personal": "👤 Kytran Katarn",
    "terry": "👤 Terry Caetano",
    "company": "🏢 Kytran Empowerment Inc.",
    "creed": "⚖️ Creed-AI",
}

_ACCOUNT_BROWSER_ID = {"personal": 342, "terry": 377, "company": 342, "creed": 342}


def release_due_posts(max_per_account: int = 1) -> Dict[str, Any]:
    """Phase 2 (#3990): promote due scheduled posts into the linkedin_post
    approval queue (Telegram human gate — nothing publishes from here).

    At most ``max_per_account`` per run so an outage drains at the designed
    1/day cadence instead of bursting every overdue post into approvals.
    The existing content-keyed approval dedup still applies downstream.
    """
    import json as _json
    import sys

    sys.path.insert(0, "/app")
    from ai_bridge.agent_loop import request_approval
    from services.time_utils import now_utc

    now_naive_utc = now_utc().replace(tzinfo=None)
    summary: Dict[str, Any] = {a: 0 for a in ACCOUNTS}
    for account in ACCOUNTS:
        post_types = _ACCOUNT_TO_POST_TYPES[account]
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """SELECT id, content, post_type FROM agent_content_posts
                   WHERE platform = 'linkedin' AND status = 'scheduled'
                     AND post_type = ANY(%s) AND scheduled_at <= %s
                   ORDER BY scheduled_at ASC
                   LIMIT %s""",
                (list(post_types), now_naive_utc, max_per_account),
            )
            due = [dict(r) for r in cur.fetchall()]
            for row in due:
                approval_id = request_approval(
                    action_type="linkedin_post",
                    action_data={
                        "content": row["content"],
                        "hashtags": [],  # already folded into content at backfill
                        "post_type": row["post_type"],
                        "browser_agent_id": _ACCOUNT_BROWSER_ID[account],
                        "priority": 6,
                    },
                    reason=(
                        f"📅 {_ACCOUNT_LABEL[account]} scheduled post (calendar):\n\n"
                        f"{row['content'][:1500]}"
                    ),
                    tier=2,
                    requested_by="S.I.G.N.A.L. calendar (daily release)",
                    priority=6,
                )
                cur.execute(
                    """UPDATE agent_content_posts
                       SET status = 'released',
                           engagement_stats = engagement_stats || %s::jsonb
                       WHERE id = %s""",
                    (
                        _json.dumps(
                            {
                                "approval_id": approval_id,
                                "released_at": now_utc().isoformat(),
                            }
                        ),
                        row["id"],
                    ),
                )
                summary[account] += 1
                logger.info(
                    "[signal-calendar] released post %s (%s) → approval %s",
                    row["id"],
                    account,
                    approval_id,
                )
    total = sum(summary.values())
    return {"total_released": total, "by_account": summary}
