"""S.I.G.N.A.L. engagement proposals — queue approval-gated LinkedIn likes/comments.

Every engagement action (like / proactive comment) is PROPOSED here, not fired
directly: it creates an ``autonomy_approval_queue`` row (action_type
``linkedin_like`` / ``linkedin_comment``) which the triage consumer escalates to
Telegram with Approve/Deny buttons (#4325) and the approval executor fires only on
Approve (agent_loop._execute_approved_action). Nothing reaches LinkedIn without a
human tap.

Manual trigger: POST /api/signal/engage → propose_like/propose_comment.
Auto trigger: run_engagement_monitor() (scheduled job, OFF by default).

Candidate sources (Phase 2.5): the LinkedIn home FEED and CONTENT SEARCH are
withheld from the headless/automated session (KB mistake — both return 0 while
every other authenticated skill works), so the default source is NOTIFICATIONS,
which LinkedIn DOES serve to automation. ``feed`` remains selectable for when it
works (e.g. via S.C.O.U.T. authenticated_fetch later).
"""

import logging
import re

logger = logging.getLogger(__name__)

# Which browser identity acts for each account. terry = its own session (377);
# personal/company/creed ride the Kytran 342 session (company/creed actor-switch
# only matters for POSTING — a like/comment is made as the logged-in identity).
_ACCOUNT_BROWSER_ID = {"personal": 342, "terry": 377, "company": 342, "creed": 342}

_VALID_REACTIONS = {"like", "celebrate", "support", "love", "insightful", "funny"}

# Pulls an activity id out of any LinkedIn link form (post permalink, post-summary
# analytics link, /activity-<id> slug, etc.).
_ACTIVITY_RE = re.compile(r"urn:li:activity:(\d+)|activity[:%\-](\d+)")


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


def _draft_comment(snippet: str, author: str = "the author") -> str:
    """Draft a short on-brand comment via S.I.G.N.A.L. dispatch. '' on any failure."""
    try:
        from services.signal_calendar_service import _ensure_import_paths

        _ensure_import_paths()
        from tools.department_hq.services.department_dispatcher import dispatch

        prompt = (
            f"Write ONE short (max 200 chars), genuine, professional LinkedIn comment "
            f"replying to this post by {author}. No hashtags, no emoji spam, no sales "
            f"pitch — a thoughtful one-liner.\n\nPost: {(snippet or '')[:500]}"
        )
        res = dispatch(capability="social_content", prompt=prompt)
        if getattr(res, "success", False):
            return ((res.response or "").strip().strip('"'))[:280]
    except Exception as e:
        logger.warning("engagement monitor: comment draft failed: %s", e)
    return ""


def _permalink_from(link: str) -> str:
    """Convert any LinkedIn link that references a post into a post permalink, else ''."""
    if not link:
        return ""
    m = _ACTIVITY_RE.search(link)
    if m:
        aid = m.group(1) or m.group(2)
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/"
    if "feed/update" in link:
        return link.split("?")[0]
    return ""


def _candidates_from_feed(account: str, limit: int) -> list:
    """Candidate posts from the home feed. NOTE: LinkedIn withholds feed content
    from automation — this returns [] in the headless session (KB mistake)."""
    from services.browser_service import run_skill_sync

    agent_id = _ACCOUNT_BROWSER_ID.get(account, 342)
    feed = run_skill_sync("linkedin_feed", {"limit": limit}, agent_id=agent_id, timeout_s=120)
    out = []
    for p in (feed or {}).get("posts") or []:
        url = (p.get("post_url") or "").strip()
        if url and "feed/update" in url:
            out.append(
                {
                    "post_url": url,
                    "author": p.get("author", ""),
                    "snippet": (p.get("content") or "")[:120],
                    "source": "feed",
                }
            )
    return out


def _candidates_from_notifications(account: str, limit: int) -> list:
    """Candidate posts extracted from the notifications stream (served to automation).

    Each notification's ``link`` is heterogeneous (post / profile / company / jobs);
    only the ones carrying an activity id become post candidates.
    """
    from services.browser_service import run_skill_sync

    agent_id = _ACCOUNT_BROWSER_ID.get(account, 342)
    n = run_skill_sync("linkedin_notifications", {"limit": limit}, agent_id=agent_id, timeout_s=120)
    out = []
    for x in (n or {}).get("notifications") or []:
        url = _permalink_from(x.get("link") or "")
        if url:
            out.append(
                {
                    "post_url": url,
                    "author": "",
                    "snippet": (x.get("text") or "").strip()[:120],
                    "source": "notifications",
                }
            )
    return out


def run_engagement_monitor(
    account: str = "personal",
    source: str = "notifications",
    limit: int = 15,
    max_per_run: int = 3,
    include_comments: bool = False,
    dry_run: bool = False,
) -> dict:
    """Scan a candidate source and PROPOSE approval-gated engagements (Phase 2/2.5).

    ``source`` = 'notifications' (default — served to automation) | 'feed' (legacy;
    withheld from automation, usually empty). Surfaces up to ``max_per_run`` posts
    not already proposed and enqueues a like (+ optional drafted comment) for each
    as Tier-2 Telegram approvals; the human Approve/Deny IS the relevance filter.
    ``dry_run=True`` returns candidates WITHOUT creating approvals (for testing).
    """
    if source == "feed":
        raw = _candidates_from_feed(account, limit)
    elif source == "notifications":
        raw = _candidates_from_notifications(account, limit)
    else:
        raise ValueError("source must be 'notifications' or 'feed'")

    candidates: list = []
    proposed = 0
    seen: set = set()
    for c in raw:
        if len(candidates) >= max_per_run:
            break
        url = c["post_url"]
        if url in seen or _already_proposed(url):
            continue
        seen.add(url)
        candidates.append(c)
        if dry_run:
            continue
        try:
            c["like_approval_id"] = propose_like(url, account=account, requested_by="S.I.G.N.A.L. engagement monitor")
            proposed += 1
        except Exception as e:
            logger.warning("engagement monitor: propose_like failed for %s: %s", url, e)
            continue
        if include_comments:
            draft = _draft_comment(c.get("snippet", ""), c.get("author", "") or "the author")
            if draft:
                try:
                    c["comment_approval_id"] = propose_comment(
                        url, draft, account=account, requested_by="S.I.G.N.A.L. engagement monitor"
                    )
                    proposed += 1
                except Exception as e:
                    logger.warning("engagement monitor: propose_comment failed for %s: %s", url, e)
    return {
        "source": source,
        "raw_candidates": len(raw),
        "candidates": candidates,
        "proposed": proposed,
        "dry_run": dry_run,
    }
