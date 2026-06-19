"""S.I.G.N.A.L. engagement proposals — queue approval-gated LinkedIn likes/comments.

Every engagement action (like / proactive comment) is PROPOSED here, not fired
directly: it creates an ``autonomy_approval_queue`` row (action_type
``linkedin_like`` / ``linkedin_comment``) which the triage consumer escalates to
Telegram with Approve/Deny buttons (#4325) and the approval executor fires only on
Approve (agent_loop._execute_approved_action). Nothing reaches LinkedIn without a
human tap.

Used by the manual trigger (POST /api/signal/engage) now; an auto engagement
monitor (Phase 2) can call the same helpers.
"""

import logging

logger = logging.getLogger(__name__)

# Which browser identity acts for each account. terry = its own session (377);
# personal/company/creed ride the Kytran 342 session (company/creed actor-switch
# only matters for POSTING — a like/comment is made as the logged-in identity).
_ACCOUNT_BROWSER_ID = {"personal": 342, "terry": 377, "company": 342, "creed": 342}

_VALID_REACTIONS = {"like", "celebrate", "support", "love", "insightful", "funny"}


def _request_approval(action_type: str, action_data: dict, reason: str, requested_by: str):
    """Enqueue a Tier-2 approval via the same path signal_calendar_service uses."""
    from services.signal_calendar_service import _ensure_import_paths

    _ensure_import_paths()
    from ai_bridge.agent_loop import request_approval

    return request_approval(
        action_type=action_type,
        action_data=action_data,
        reason=reason,
        tier=2,
        requested_by=requested_by,
        priority=6,
    )


def propose_like(
    post_url: str,
    account: str = "personal",
    reaction: str = "like",
    agent_id: int = None,
    requested_by: str = "S.I.G.N.A.L. engagement (manual)",
) -> int:
    """Queue an approval-gated reaction on a post. Returns the approval id."""
    post_url = (post_url or "").strip()
    if not post_url:
        raise ValueError("post_url is required")
    reaction = (reaction or "like").lower()
    if reaction not in _VALID_REACTIONS:
        raise ValueError(f"reaction must be one of {sorted(_VALID_REACTIONS)}")
    aid = agent_id or _ACCOUNT_BROWSER_ID.get(account, 342)
    return _request_approval(
        "linkedin_like",
        {"post_url": post_url, "reaction": reaction, "browser_agent_id": aid, "account": account},
        reason=f"👍 Approve {reaction} on {post_url} (as {account})",
        requested_by=requested_by,
    )


def propose_comment(
    post_url: str,
    comment: str,
    account: str = "personal",
    agent_id: int = None,
    requested_by: str = "S.I.G.N.A.L. engagement (manual)",
) -> int:
    """Queue an approval-gated proactive comment on a post. Returns the approval id."""
    post_url = (post_url or "").strip()
    comment = (comment or "").strip()
    if not post_url:
        raise ValueError("post_url is required")
    if not comment:
        raise ValueError("comment is required")
    aid = agent_id or _ACCOUNT_BROWSER_ID.get(account, 342)
    return _request_approval(
        "linkedin_comment",
        {"post_url": post_url, "comment": comment, "browser_agent_id": aid, "account": account},
        reason=f"💬 Approve comment on {post_url} (as {account}):\n\n{comment[:500]}",
        requested_by=requested_by,
    )


# ---------------------------------------------------------------------------
# Phase 2 — auto engagement monitor
# ---------------------------------------------------------------------------


def _already_proposed(post_url: str) -> bool:
    """True if a like/comment approval already exists for this post (any status).

    Dedup without a new table — reuses autonomy_approval_queue. Fail-CLOSED (treat
    as already-proposed on any error) so a glitch never spams duplicate approvals.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT 1 FROM autonomy_approval_queue
                   WHERE action_type IN ('linkedin_like', 'linkedin_comment')
                     AND action_data->>'post_url' = %s
                   LIMIT 1""",
                (post_url,),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.warning("engagement dedup check failed for %s: %s", post_url, e)
        return True


def _draft_comment(post: dict) -> str:
    """Draft a short on-brand comment for a feed post via S.I.G.N.A.L. dispatch.
    Returns '' on any failure (the like still goes through)."""
    try:
        from services.signal_calendar_service import _ensure_import_paths

        _ensure_import_paths()
        from tools.department_hq.services.department_dispatcher import dispatch

        author = post.get("author", "the author")
        content = (post.get("content") or "")[:500]
        prompt = (
            f"Write ONE short (max 200 chars), genuine, professional LinkedIn comment "
            f"replying to this post by {author}. No hashtags, no emoji spam, no sales "
            f"pitch — a thoughtful one-liner.\n\nPost: {content}"
        )
        res = dispatch(capability="social_content", prompt=prompt)
        if getattr(res, "success", False):
            text = (res.response or "").strip().strip('"')
            return text[:280]
    except Exception as e:
        logger.warning("engagement monitor: comment draft failed: %s", e)
    return ""


def run_engagement_monitor(
    account: str = "personal",
    feed_limit: int = 10,
    max_per_run: int = 3,
    include_comments: bool = False,
    dry_run: bool = False,
) -> dict:
    """Scan the feed and PROPOSE approval-gated engagements (Phase 2).

    Surfaces up to ``max_per_run`` candidate feed posts (skipping any already
    proposed) and enqueues a like — and, if ``include_comments``, a drafted comment
    — for each, all as Tier-2 Telegram approvals. The human Approve/Deny IS the
    relevance filter; this only surfaces candidates. ``dry_run=True`` returns the
    candidates WITHOUT creating any approvals (used for testing).
    """
    from services.browser_service import run_skill_sync

    agent_id = _ACCOUNT_BROWSER_ID.get(account, 342)
    feed = run_skill_sync("linkedin_feed", {"limit": feed_limit}, agent_id=agent_id, timeout_s=120)
    posts = (feed or {}).get("posts") or []
    candidates: list = []
    proposed = 0
    for p in posts:
        if len(candidates) >= max_per_run:
            break
        url = (p.get("post_url") or "").strip()
        if not url or "feed/update" not in url:
            continue
        if _already_proposed(url):
            continue
        cand = {
            "post_url": url,
            "author": p.get("author", ""),
            "snippet": (p.get("content") or "")[:120],
        }
        candidates.append(cand)
        if dry_run:
            continue
        try:
            cand["like_approval_id"] = propose_like(
                url, account=account, requested_by="S.I.G.N.A.L. engagement monitor"
            )
            proposed += 1
        except Exception as e:
            logger.warning("engagement monitor: propose_like failed for %s: %s", url, e)
            continue
        if include_comments:
            draft = _draft_comment(p)
            if draft:
                try:
                    cand["comment_approval_id"] = propose_comment(
                        url, draft, account=account, requested_by="S.I.G.N.A.L. engagement monitor"
                    )
                    proposed += 1
                except Exception as e:
                    logger.warning("engagement monitor: propose_comment failed for %s: %s", url, e)
    return {
        "feed_posts": len(posts),
        "candidates": candidates,
        "proposed": proposed,
        "dry_run": dry_run,
    }
