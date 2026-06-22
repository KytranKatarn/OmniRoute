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

from services import signal_accounts

logger = logging.getLogger(__name__)

# Browser identity per account → services.signal_accounts registry (migration 440).

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
    aid = agent_id or signal_accounts.browser_id_for(account)
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
    aid = agent_id or signal_accounts.browser_id_for(account)
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
    from services.welfare_governance_service import pool_over_budget_by_skill

    # Welfare gate (ADR-002): skip engagement-comment drafting when the social_content
    # pool has no 24h token-budget headroom. Fail-open. '' is already the caller's skip
    # signal. Tunable via platform_settings welfare:signal:pool_pause_ratio (default 0.9).
    if pool_over_budget_by_skill("social_content", "welfare:signal:pool_pause_ratio"):
        logger.info(
            "[signal-engagement] comment drafting deferred — social_content pool over "
            "24h token budget (welfare-gated, ADR-002)"
        )
        return ""

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
    from services.browser_service import is_rate_limited, run_skill_sync

    agent_id = signal_accounts.browser_id_for(account)
    feed = run_skill_sync("linkedin_feed", {"limit": limit}, agent_id=agent_id, timeout_s=120)
    if is_rate_limited(feed):
        logger.info("[engagement] feed rate_limited for %s — skipped this cycle", account)
        return []
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
    from services.browser_service import is_rate_limited, run_skill_sync

    agent_id = signal_accounts.browser_id_for(account)
    n = run_skill_sync("linkedin_notifications", {"limit": limit}, agent_id=agent_id, timeout_s=120)
    if is_rate_limited(n):
        logger.info("[engagement] notifications rate_limited for %s — skipped this cycle", account)
        return []
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


def _get_targets() -> list:
    """Engagement target profile/company URLs from platform_settings
    (key 'signal:engagement:targets', JSON list of LinkedIn /in/ or /company/ URLs).
    Empty list if unset → the profiles source proposes nothing."""
    import json as _json

    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s",
                ("signal:engagement:targets",),
            )
            row = cur.fetchone()
        raw = (row["value"] if isinstance(row, dict) else row[0]) if row else None
        if not raw:
            return []
        val = _json.loads(raw) if isinstance(raw, str) else raw
        return [str(t).strip() for t in val if str(t).strip()] if isinstance(val, list) else []
    except Exception as e:
        logger.warning("engagement targets read failed: %s", e)
        return []


def get_targets() -> list:
    """Public accessor for the engagement target list."""
    return _get_targets()


def set_targets(targets: list) -> int:
    """Persist the engagement target profile/company URLs (platform_settings).
    Returns the count stored."""
    import json as _json

    from database import get_db_cursor

    clean = [str(t).strip() for t in (targets or []) if str(t).strip()]
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO platform_settings (key, value, value_type, description, updated_at)
               VALUES (%s, %s, 'json', %s, NOW())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
            (
                "signal:engagement:targets",
                _json.dumps(clean),
                "S.I.G.N.A.L. engagement target LinkedIn profile/company URLs",
            ),
        )
    return len(clean)


def _candidates_from_profiles(account: str, targets: list, per_target: int = 1, limit: int = 15) -> list:
    """Candidate posts from each target's recent activity (served to automation) —
    THE genuine outreach source: surfaces OTHERS' posts to (human-approved) engage."""
    from services.browser_service import is_rate_limited, run_skill_sync

    agent_id = signal_accounts.browser_id_for(account)
    out = []
    for t in targets or []:
        if len(out) >= limit:
            break
        try:
            r = run_skill_sync(
                "linkedin_recent_activity",
                {"profile_url": t, "limit": per_target},
                agent_id=agent_id,
                timeout_s=120,
            )
        except Exception as e:
            logger.warning("engagement monitor: recent_activity failed for %s: %s", t, e)
            continue
        if is_rate_limited(r):
            logger.info("[engagement] recent_activity rate_limited — skipping remaining targets")
            break
        for p in (r or {}).get("posts") or []:
            url = (p.get("post_url") or "").strip()
            if url:
                out.append(
                    {
                        "post_url": url,
                        "author": t,
                        "snippet": (p.get("snippet") or "")[:120],
                        "source": "profiles",
                    }
                )
    return out


def run_engagement_monitor(
    account: str = "personal",
    source: str = "auto",
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
    if source == "auto":
        # Prefer genuine outreach (target profiles) when configured; else fall back
        # to notifications (your-own-post activity). feed stays opt-in (withheld).
        source = "profiles" if _get_targets() else "notifications"
    if source == "feed":
        raw = _candidates_from_feed(account, limit)
    elif source == "notifications":
        raw = _candidates_from_notifications(account, limit)
    elif source == "profiles":
        raw = _candidates_from_profiles(account, _get_targets(), per_target=1, limit=limit)
    else:
        raise ValueError("source must be 'notifications', 'profiles', or 'feed'")

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
