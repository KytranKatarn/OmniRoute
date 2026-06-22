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

# ── S7-P1-4a: fleet-safe engagement ledger + per-agent budget / voice / similarity ──
_SIMILARITY_THRESHOLD = 0.8


def _post_urn_from(post_url: str) -> str:
    """Stable dedup key for a post — its activity urn, so the same post dedups regardless
    of URL form. Falls back to the trimmed permalink."""
    m = _ACTIVITY_RE.search(post_url or "")
    if m:
        return f"urn:li:activity:{m.group(1) or m.group(2)}"
    return (post_url or "").split("?")[0].strip()


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _jaccard(a: str, b: str) -> float:
    """Token-set Jaccard overlap of two comments (0..1)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _already_engaged(cur, post_urn: str, agent_id: int, action: str) -> bool:
    """True if THIS agent already has a ledger row for (post, action) — the global,
    fleet-safe dedup that replaces the per-account autonomy_approval_queue check."""
    cur.execute(
        "SELECT 1 FROM linkedin_engagement_ledger " "WHERE post_urn=%s AND acting_agent_id=%s AND action=%s LIMIT 1",
        (post_urn, agent_id, action),
    )
    return cur.fetchone() is not None


def _post_engaged_by_other(cur, post_urn: str, action: str, agent_id: int) -> bool:
    """True if a DIFFERENT fleet agent already engaged this post with this action — keeps
    the fleet from piling more than one like/comment on a single post."""
    cur.execute(
        "SELECT 1 FROM linkedin_engagement_ledger " "WHERE post_urn=%s AND action=%s AND acting_agent_id <> %s LIMIT 1",
        (post_urn, action, agent_id),
    )
    return cur.fetchone() is not None


def _max_similarity_on_post(cur, post_urn: str, comment: str) -> float:
    """Max Jaccard overlap of `comment` vs every comment already in the ledger for this
    post — anti-spam so the fleet never posts near-duplicate comments under one post."""
    cur.execute(
        "SELECT comment_text FROM linkedin_engagement_ledger "
        "WHERE post_urn=%s AND action='comment' AND comment_text IS NOT NULL",
        (post_urn,),
    )
    best = 0.0
    for row in cur.fetchall():
        other = row["comment_text"] if isinstance(row, dict) else row[0]
        best = max(best, _jaccard(comment, other))
    return best


def _record_pending(cur, post_urn, agent_id, action, approval_id=None, comment_text=None, similarity=None) -> bool:
    """Insert a 'pending' ledger row (UNIQUE-deduped). Returns True if newly recorded."""
    cur.execute(
        """INSERT INTO linkedin_engagement_ledger
               (post_urn, acting_agent_id, action, status, approval_id, comment_text, similarity_score)
           VALUES (%s, %s, %s, 'pending', %s, %s, %s)
           ON CONFLICT (post_urn, acting_agent_id, action) DO NOTHING""",
        (post_urn, agent_id, action, approval_id, comment_text, similarity),
    )
    return cur.rowcount > 0


def _bool_setting(cur, key: str, default: bool = False) -> bool:
    cur.execute("SELECT value FROM platform_settings WHERE key=%s", (key,))
    r = cur.fetchone()
    raw = (r["value"] if isinstance(r, dict) else r[0]) if r else None
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("true", "1", "on", "yes")


def _monitor_agent_ids(cur) -> list:
    """Agents the engagement monitor acts as (default [342]). JSON list in
    platform_settings signal:engagement_monitor_agent_ids."""
    import json as _json

    cur.execute("SELECT value FROM platform_settings WHERE key=%s", ("signal:engagement_monitor_agent_ids",))
    r = cur.fetchone()
    raw = (r["value"] if isinstance(r, dict) else r[0]) if r else None
    try:
        val = _json.loads(raw) if isinstance(raw, str) else raw
        ids = [int(x) for x in val] if isinstance(val, list) else []
        return ids or [342]
    except Exception:
        return [342]


def _engagement_account(cur, agent_id: int) -> dict:
    """The can_engage registry account driven by this browser agent — voice / budget /
    targets / today's counters. {} if none."""
    cur.execute(
        """SELECT account_key, voice_key, engagement_targets, daily_action_budget,
                  active_count_today, last_action_at
           FROM agent_platform_accounts
           WHERE browser_agent_id=%s AND COALESCE(can_engage, true)
           ORDER BY (role='major_author') DESC NULLS LAST LIMIT 1""",
        (agent_id,),
    )
    r = cur.fetchone()
    if not r:
        return {}
    return (
        dict(r)
        if isinstance(r, dict)
        else {
            "account_key": r[0],
            "voice_key": r[1],
            "engagement_targets": r[2],
            "daily_action_budget": r[3],
            "active_count_today": r[4],
            "last_action_at": r[5],
        }
    )


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
    post_urn = _post_urn_from(post_url)
    approval_id = _request_approval(
        "linkedin_like",
        {
            "post_url": post_url,
            "reaction": reaction,
            "browser_agent_id": aid,
            "account": account,
            "post_urn": post_urn,
        },
        reason=f"👍 Approve {reaction} on {post_url} (as {account})",
        requested_by=requested_by,
    )
    # S7-P1-4a: record the engagement in the global ledger (fleet-safe dedup; 4b flips it
    # to executed/failed on the approval outcome). Best-effort — never block the proposal.
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, _cur):
            _record_pending(_cur, post_urn, aid, "like", approval_id=approval_id)
    except Exception as _le:
        logger.warning("engagement ledger record (like) failed: %s", _le)
    return approval_id


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
    post_urn = _post_urn_from(post_url)
    approval_id = _request_approval(
        "linkedin_comment",
        {
            "post_url": post_url,
            "comment": comment,
            "browser_agent_id": aid,
            "account": account,
            "post_urn": post_urn,
        },
        reason=f"💬 Approve comment on {post_url} (as {account}):\n\n{comment[:500]}",
        requested_by=requested_by,
    )
    # S7-P1-4a: record the comment (text kept for the fleet anti-spam similarity gate).
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, _cur):
            _record_pending(_cur, post_urn, aid, "comment", approval_id=approval_id, comment_text=comment)
    except Exception as _le:
        logger.warning("engagement ledger record (comment) failed: %s", _le)
    return approval_id


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


def _draft_comment(snippet: str, author: str = "the author", voice: str = None) -> str:
    """Draft a short on-brand comment via S.I.G.N.A.L. dispatch. '' on any failure.

    ``voice`` (S7-P1-4a): the acting account's registry voice_key, so each fleet agent
    comments in a distinct persona (anti-spam diversity)."""
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

        voice_line = f"Voice/persona: {voice}\n" if voice else ""
        prompt = (
            f"{voice_line}"
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


def _get_targets(account: str = None) -> list:
    """Engagement target profile/company URLs. S7-P1-4a: an account's registry
    ``engagement_targets`` override (if set) wins; else the global platform_settings
    'signal:engagement:targets' (JSON list of LinkedIn /in/ or /company/ URLs). Empty
    list → the profiles source proposes nothing."""
    import json as _json

    from database import get_db_cursor

    def _as_list(raw):
        if not raw:
            return []
        val = _json.loads(raw) if isinstance(raw, str) else raw
        return [str(t).strip() for t in val if str(t).strip()] if isinstance(val, list) else []

    try:
        with get_db_cursor() as (conn, cur):
            if account:
                cur.execute(
                    "SELECT engagement_targets FROM agent_platform_accounts WHERE account_key = %s",
                    (account,),
                )
                arow = cur.fetchone()
                araw = (arow["engagement_targets"] if isinstance(arow, dict) else arow[0]) if arow else None
                override = _as_list(araw)
                if override:
                    return override
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s",
                ("signal:engagement:targets",),
            )
            row = cur.fetchone()
        raw = (row["value"] if isinstance(row, dict) else row[0]) if row else None
        return _as_list(raw)
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
    from database import get_db_cursor

    aid = signal_accounts.browser_id_for(account)
    if source == "auto":
        # Prefer genuine outreach (target profiles) when configured; else fall back
        # to notifications (your-own-post activity). feed stays opt-in (withheld).
        source = "profiles" if _get_targets(account) else "notifications"
    if source == "feed":
        raw = _candidates_from_feed(account, limit)
    elif source == "notifications":
        raw = _candidates_from_notifications(account, limit)
    elif source == "profiles":
        raw = _candidates_from_profiles(account, _get_targets(account), per_target=1, limit=limit)
    else:
        raise ValueError("source must be 'notifications', 'profiles', or 'feed'")

    # Per-agent daily budget + voice from the registry; similarity gate flag (S7-P1-4a).
    with get_db_cursor() as (_conn, cur):
        acct = _engagement_account(cur, aid)
        budget = int(acct.get("daily_action_budget") or 5) if acct else 5
        voice = acct.get("voice_key") if acct else None
        cur.execute(
            "SELECT COUNT(*) AS n FROM linkedin_engagement_ledger "
            "WHERE acting_agent_id=%s AND created_at >= "
            "(date_trunc('day', NOW() AT TIME ZONE 'America/Toronto') AT TIME ZONE 'America/Toronto')",
            (aid,),
        )
        r = cur.fetchone()
        used_today = int((r["n"] if isinstance(r, dict) else r[0]) or 0)
        sim_gate = _bool_setting(cur, "signal:comment_similarity_gate_enabled", False)
    remaining = max(0, budget - used_today)

    candidates: list = []
    proposed = 0
    skipped = {"dup": 0, "budget": 0, "similar": 0}
    seen: set = set()
    for c in raw:
        if len(candidates) >= max_per_run:
            break
        if not dry_run and remaining <= 0:
            skipped["budget"] += 1
            break
        url = c["post_url"]
        urn = _post_urn_from(url)
        if url in seen:
            continue
        seen.add(url)
        # Fleet-safe dedup: this agent OR any other already engaged this post.
        with get_db_cursor() as (_conn, cur):
            if _already_engaged(cur, urn, aid, "like") or _post_engaged_by_other(cur, urn, "like", aid):
                skipped["dup"] += 1
                continue
        candidates.append(c)
        if dry_run:
            continue
        try:
            c["like_approval_id"] = propose_like(
                url, account=account, agent_id=aid, requested_by="S.I.G.N.A.L. engagement monitor"
            )
            proposed += 1
            remaining -= 1
        except Exception as e:
            logger.warning("engagement monitor: propose_like failed for %s: %s", url, e)
            continue
        if include_comments and remaining > 0:
            draft = _draft_comment(c.get("snippet", ""), c.get("author", "") or "the author", voice=voice)
            if draft:
                if sim_gate:
                    with get_db_cursor() as (_conn, cur):
                        sim = _max_similarity_on_post(cur, urn, draft)
                    if sim > _SIMILARITY_THRESHOLD:
                        skipped["similar"] += 1
                        logger.info(
                            "[engagement] comment on %s skipped — too similar (%.2f) to a fleet comment", urn, sim
                        )
                        continue
                try:
                    c["comment_approval_id"] = propose_comment(
                        url, draft, account=account, agent_id=aid, requested_by="S.I.G.N.A.L. engagement monitor"
                    )
                    proposed += 1
                    remaining -= 1
                except Exception as e:
                    logger.warning("engagement monitor: propose_comment failed for %s: %s", url, e)
    return {
        "account": account,
        "agent_id": aid,
        "source": source,
        "raw_candidates": len(raw),
        "candidates": candidates,
        "proposed": proposed,
        "budget": budget,
        "used_today": used_today,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def run_fleet_engagement_monitor(**kwargs) -> dict:
    """S7-P1-4a fleet driver: run the per-account monitor for every agent in
    platform_settings signal:engagement_monitor_agent_ids (default [342]), each with its
    own registry voice + daily budget. The scheduled signal_engagement_monitor job (OFF by
    default) calls this; Telegram approval stays the only execution path."""
    from database import get_db_cursor

    agent_accounts = {}
    with get_db_cursor() as (_conn, cur):
        agent_ids = _monitor_agent_ids(cur)
        for _aid in agent_ids:
            acct = _engagement_account(cur, _aid)
            if acct and acct.get("account_key"):
                agent_accounts[_aid] = acct["account_key"]
    results = {}
    for _aid, _acct_key in agent_accounts.items():
        try:
            results[_acct_key] = run_engagement_monitor(account=_acct_key, **kwargs)
        except Exception as e:
            logger.warning("fleet engagement monitor failed for %s: %s", _acct_key, e)
            results[_acct_key] = {"error": str(e)}
    return {"agents": agent_ids, "by_account": results}
