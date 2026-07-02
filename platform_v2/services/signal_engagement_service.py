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
    """Stable dedup key — the COMMENT urn when the link is a ?commentUrn= deep-link
    (so a comment-like keys on the comment, not its parent post), else the post's
    activity urn. Falls back to the trimmed permalink."""
    from urllib.parse import unquote

    cm = re.search(r"urn:li:comment:\(activity:\d+,\d+\)", unquote(post_url or ""))
    if cm:
        return cm.group(0)
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


def record_executed(post_url: str, agent_id: int, action: str, success: bool) -> None:
    """S7-P1-4b: after the Telegram approval fires, flip the ledger row executed/failed and,
    on success, bump the acting agent's daily action counter. Best-effort (never breaks the
    approval executor). `post_url` may be a permalink or a urn — normalised internally."""
    urn = _post_urn_from(post_url)
    if not urn:
        return
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE linkedin_engagement_ledger SET status=%s, executed_at=NOW() "
                "WHERE post_urn=%s AND acting_agent_id=%s AND action=%s",
                ("executed" if success else "failed", urn, agent_id, action),
            )
            if success:
                cur.execute(
                    "UPDATE agent_platform_accounts "
                    "SET active_count_today = COALESCE(active_count_today, 0) + 1, last_action_at = NOW() "
                    "WHERE browser_agent_id=%s",
                    (agent_id,),
                )
    except Exception as e:
        logger.warning("engagement ledger accounting failed (%s/%s): %s", agent_id, action, e)


def reset_daily_engagement_budgets() -> dict:
    """S7-P1-4b: zero every agent's active_count_today (run daily 00:05 ET) and abandon stale
    'pending' ledger rows (>3 days, never approved). Idempotent."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE agent_platform_accounts SET active_count_today=0, last_action_at=NULL "
            "WHERE COALESCE(active_count_today,0) <> 0 OR last_action_at IS NOT NULL"
        )
        reset_n = cur.rowcount
        cur.execute(
            "UPDATE linkedin_engagement_ledger SET status='abandoned' "
            "WHERE status='pending' AND created_at < NOW() - INTERVAL '3 days'"
        )
        abandoned = cur.rowcount
    logger.info("[engagement] daily budget reset: %s agents, %s stale orphans abandoned", reset_n, abandoned)
    return {"reset_agents": reset_n, "abandoned_orphans": abandoned}


def engagement_state_by_agent() -> list:
    """S7-P1-4b: per can_engage account {account_key, voice_key, daily_action_budget,
    active_count_today, last_action_at} — drives the DHQ engagement UI (S7-P6.5b)."""
    from database import get_db_cursor

    out = []
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            "SELECT account_key, browser_agent_id, voice_key, daily_action_budget, "
            "       COALESCE(active_count_today,0) AS active_count_today, last_action_at "
            "FROM agent_platform_accounts WHERE COALESCE(can_engage, true) ORDER BY account_key"
        )
        for r in cur.fetchall():
            row = (
                dict(r)
                if isinstance(r, dict)
                else {
                    "account_key": r[0],
                    "browser_agent_id": r[1],
                    "voice_key": r[2],
                    "daily_action_budget": r[3],
                    "active_count_today": r[4],
                    "last_action_at": r[5],
                }
            )
            if row.get("last_action_at") is not None:
                row["last_action_at"] = str(row["last_action_at"])
            out.append(row)
    return out


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
    # approval_id=None = the approval was dedup-skipped upstream: record NOTHING, else an
    # orphan 'pending' ledger row blocks re-proposing forever.
    if approval_id:
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
    # Skip when the approval was dedup-skipped (approval_id=None) — see propose_like.
    if approval_id:
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_conn, _cur):
                _record_pending(_cur, post_urn, aid, "comment", approval_id=approval_id, comment_text=comment)
        except Exception as _le:
            logger.warning("engagement ledger record (comment) failed: %s", _le)
    return approval_id


def propose_comment_like(
    comment_url: str,
    comment_author: str = "",
    comment_contains: str = "",
    account: str = "personal",
    agent_id: int = None,
    requested_by: str = "S.I.G.N.A.L. cross-boost",
) -> int:
    """Queue an approval-gated LIKE on a specific comment (cross-boost). Returns the
    approval id. ``comment_url`` should be a ?commentUrn= deep-link (KB #274178)."""
    comment_url = (comment_url or "").strip()
    if not comment_url:
        raise ValueError("comment_url is required")
    aid = agent_id or signal_accounts.browser_id_for(account)
    urn = _post_urn_from(comment_url)  # comment urn (dedup keys on the comment itself)
    approval_id = _request_approval(
        "linkedin_comment_like",
        {
            "comment_url": comment_url,
            "comment_author": comment_author,
            "comment_contains": (comment_contains or "")[:120],
            "browser_agent_id": aid,
            "account": account,
            "post_urn": urn,
        },
        reason=f"👍 Approve LIKE on {comment_author or 'a'}'s comment (as {account}): {comment_url}",
        requested_by=requested_by,
    )
    if approval_id:
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_conn, _cur):
                _record_pending(_cur, urn, aid, "comment_like", approval_id=approval_id)
        except Exception as _le:
            logger.warning("engagement ledger record (comment_like) failed: %s", _le)
    return approval_id


# ---------------------------------------------------------------------------
# Cross-account boosting — Terry ↔ Kytran like each other's posts + comments
# ---------------------------------------------------------------------------

# post_type of OUR published post → the account that boosts it (owner 2026-07-02:
# "Terry can like Kytran posts / comments and vice versa"). The company/creed pages
# are Kytran-authored, so Terry boosts those too.
_CROSS_BOOST_MAP = {
    "terry": "personal",
    "personal": "terry",
    "company": "terry",
    "creed": "terry",
}

# Author-name needle (on comments captured under OUR posts, linkedin_comments) →
# the OTHER identity that likes it.
_OWN_COMMENT_AUTHORS = {
    "kytran katarn": "terry",
    "terry caetano": "personal",
}


def run_cross_boost(days: int = 7, max_per_account: int = 2, dry_run: bool = False) -> dict:
    """Propose cross-account likes on OUR OWN fresh content — no scraping needed:
    posts come from linkedin_post_log, comments (with ?commentUrn= deep-links) from
    linkedin_comments. Every action is a Tier-2 Telegram approval.

    OWN-CONTENT CARVE-OUT: the fleet-wide `_post_engaged_by_other` dedup is
    deliberately NOT applied here — multiple own identities boosting our own content
    is the point. Per-agent `_already_engaged` dedup still applies, as does the
    per-run cap (``max_per_account``)."""
    from database import get_db_cursor

    out = {
        "proposed": 0,
        "posts": [],
        "comments": [],
        "skipped": {"dup": 0, "cap": 0, "no_account": 0},
        "dry_run": dry_run,
    }
    counts: dict = {}

    with get_db_cursor() as (_conn, cur):
        # can_engage boosting identities keyed by account_key.
        cur.execute(
            "SELECT account_key, browser_agent_id FROM agent_platform_accounts WHERE COALESCE(can_engage, false)"
        )
        boosters = {}
        for r in cur.fetchall():
            k = r["account_key"] if isinstance(r, dict) else r[0]
            v = r["browser_agent_id"] if isinstance(r, dict) else r[1]
            boosters[k] = v

        # a) Our fresh POSTS → the other identity likes them.
        cur.execute(
            "SELECT post_type, post_url FROM linkedin_post_log "
            "WHERE status='posted' AND COALESCE(post_url,'') <> '' "
            "  AND posted_at > NOW() - make_interval(days => %s) "
            "ORDER BY posted_at DESC LIMIT 40",
            (int(days),),
        )
        post_rows = [(r["post_type"], r["post_url"]) if isinstance(r, dict) else (r[0], r[1]) for r in cur.fetchall()]

        # b) OUR identities' comments captured under our posts (deep-links on hand).
        cur.execute(
            "SELECT comment_url, author, body FROM linkedin_comments "
            "WHERE COALESCE(comment_url,'') <> '' "
            "  AND last_seen_at > NOW() - make_interval(days => %s) "
            "ORDER BY last_seen_at DESC LIMIT 60",
            (int(days),),
        )
        comment_rows = [
            (r["comment_url"], r["author"], r["body"]) if isinstance(r, dict) else (r[0], r[1], r[2])
            for r in cur.fetchall()
        ]

        plan = []  # (kind, booster_key, aid, url, author, body_snippet)
        for post_type, post_url in post_rows:
            if post_url.startswith("/"):  # linkedin_post_log holds some relative URLs
                post_url = "https://www.linkedin.com" + post_url
            booster = _CROSS_BOOST_MAP.get((post_type or "").lower())
            if not booster or booster not in boosters:
                out["skipped"]["no_account"] += 1
                continue
            aid = boosters[booster]
            if counts.get(booster, 0) >= max_per_account:
                out["skipped"]["cap"] += 1
                continue
            urn = _post_urn_from(post_url)
            if _already_engaged(cur, urn, aid, "like"):
                out["skipped"]["dup"] += 1
                continue
            counts[booster] = counts.get(booster, 0) + 1
            plan.append(("post_like", booster, aid, post_url, "", ""))

        ccounts: dict = {}
        for comment_url, author, body in comment_rows:
            a_low = (author or "").lower()
            booster = next((b for needle, b in _OWN_COMMENT_AUTHORS.items() if needle in a_low), None)
            if not booster or booster not in boosters:
                continue
            aid = boosters[booster]
            if ccounts.get(booster, 0) >= max_per_account:
                out["skipped"]["cap"] += 1
                continue
            urn = _post_urn_from(comment_url)
            if _already_engaged(cur, urn, aid, "comment_like"):
                out["skipped"]["dup"] += 1
                continue
            ccounts[booster] = ccounts.get(booster, 0) + 1
            plan.append(("comment_like", booster, aid, comment_url, author, (body or "")[:60]))

    for kind, booster, aid, url, author, snippet in plan:
        entry = {"as": booster, "url": url}
        try:
            if kind == "post_like":
                if not dry_run:
                    entry["approval_id"] = propose_like(
                        url, account=booster, agent_id=aid, requested_by="S.I.G.N.A.L. cross-boost"
                    )
                out["posts"].append(entry)
            else:
                entry["comment_author"] = author
                if not dry_run:
                    entry["approval_id"] = propose_comment_like(
                        url, comment_author=author, comment_contains=snippet, account=booster, agent_id=aid
                    )
                out["comments"].append(entry)
            if not dry_run:
                out["proposed"] += 1
        except Exception as e:
            logger.warning("cross-boost proposal failed for %s: %s", url, e)
    return out


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


# ── S.I.G.N.A.L. engagement comment drafting — voice + factual grounding (cont-113) ──
# Full owner-approved guide: KB #277108. LinkedIn's comment cap is ~1250 chars.
_COMMENT_MAX_CHARS = 1200

# Real, checkable facts the model MAY cite. Anti-hallucination rule: cite ONLY these
# (or the live WTF headlines injected at runtime) — otherwise ask a genuine question.
_ENGAGEMENT_STACK_FACTS = (
    "GROUNDING FACTS (all real/checkable — you may cite these; otherwise ask a "
    "question. NEVER invent facts, numbers, names or events):\n"
    "- We run a LOCAL-SOVEREIGN AI cluster: inference on Canadian-owned hardware first, "
    "cloud escalation-only; civic data never leaves our own infrastructure.\n"
    "- Watch Series: Gov Watch (CanadaBuys/PSPC procurement), Legal Watch "
    "(CanLII/Canada Gazette/SCC), Civic Watch (municipal), Market Watch (SEDAR+), "
    "What The Fact (46 Canadian news sources, bias scoring + fact-check). Unified by a "
    "Shared Entity Graph tracing Money->MP->Vote->Policy->Contract->Market->Coverage->Public.\n"
    "- C.R.E.E.D.: we publish a live PUBLIC transparency score on our OWN AI "
    "(accountability/fairness/privacy/safety/transparency), with grades + badges.\n"
    "- For anything not yet shipped, say 'building toward' rather than claiming it exists."
)

_ENGAGEMENT_RULES = (
    "You are writing ONE LinkedIn comment as a peer builder — not a broadcaster or "
    "salesperson.\nRULES:\n"
    "- Engage the ACTUAL content of the post. If you only have a short snippet, ask "
    "about a specific instead of asserting what the post says.\n"
    "- LEAD with Terry's grounded perspective: contribute ONE concrete, checkable point "
    "from our own experience/stack (see facts below) that genuinely bears on their post — "
    "speak as someone who builds this ('we've found...', 'in building X we hit...'), not a "
    "curious bystander — THEN optionally add a sharp follow-up question. Only fall back to a "
    "pure question when nothing grounded honestly fits. Never fabricate anything.\n"
    "- Describe our approach/capability ONLY in the general terms given in the facts below. "
    "NEVER claim a specific analysis, study, result, or example ('we analyzed X and found Y') "
    "that is not literally in those facts — if the post's topic is outside our lane "
    "(partisan politics, breaking hard news), ask a genuine question instead of stretching.\n"
    "- Do NOT sign the comment. No emoji spam, no hashtag stuffing, no sales pitch or CTA.\n"
    "- Do NOT open with flattery ('Great point', 'Interesting', 'Well said', 'Great post'). "
    "Lead with the substance. Plain, specific, professional, additive — advance the "
    "conversation, never flatter.\n"
    f"- Length: up to {_COMMENT_MAX_CHARS} characters, but substance over length "
    "(a tight 400-char comment beats a padded one)."
)

# Engagement-comment drafting deserves a capable local model. HARDWARE CEILING: the hub's
# ModelService only warm-boots models that fit the 8GB GPU (Quadro M4000); anything bigger
# (gemma3:12b/phi4:14b/qwen2.5:14b/mistral-small:24b — all >8GB VRAM) is refused on the
# synchronous path (bakeoff 2026-07-01). qwen2.5:7b fits the GPU, loads in ~25s, and with
# the grounded prompt nudge hits near-target quality — the practical best here. Tunable via
# a platform_setting later; local-only (cloud escalation stays off).
_DEFAULT_DRAFT_MODEL = "qwen2.5:7b"

# Style references (owner-approved 2026-07-01; full guide KB #277108).
_ENGAGEMENT_FEWSHOT = (
    "STYLE REFERENCES (post -> good comment):\n"
    "POST: \"Canada's new AI strategy emphasizes domestic data centres and sovereign AI "
    'capacity..."\n'
    "COMMENT: The data-centre capacity piece matters, but the part I'd push on is where "
    "inference actually runs and who can audit it. We've been building civic-intelligence "
    "tools on a local-first cluster — Canadian-owned hardware first, cloud only on "
    "escalation — so the data never leaves our own infrastructure. The harder problem "
    "isn't compute, it's trust: we publish a live transparency score on our own AI so the "
    "sovereignty claim is checkable. Does the paper get into auditability and governance, "
    "or mostly the capacity side?\n"
    "---\n"
    "POST: \"We're hiring a Cyber-Lead-In-Residence; our approach to cybersecurity isn't "
    'just about technology..."\n'
    "COMMENT: 'Beyond technology' is the right framing — for civic data the threat model "
    "is as much about residency and public trust as intrusion. A lot of the real risk "
    "isn't a breach; it's sensitive public-interest data on infrastructure nobody in "
    "Canada controls or can audit. Curious whether the role is scoped to security "
    "engineering, or also the governance/residency side — that second half is where a lot "
    "of civic-tech orgs are thin."
)

# ── Per-account persona packs (Phase 5) — resolved from the registry voice_key ──
# Terry = peer civic-tech builder (KB #277108). Kytran = founder brand-marketing voice
# (owner direction 2026-07-01: "business marketing, trying to reach brand and promote").
_KYTRAN_MARKETING_RULES = (
    "You are writing ONE LinkedIn comment as a founder building brand awareness — "
    "generous with insight, never hard-selling.\nRULES:\n"
    "- Engage the ACTUAL content of the post. If you only have a short snippet, ask "
    "about a specific instead of asserting what the post says.\n"
    "- LEAD with a concrete, checkable point from what we've built (see facts below) that "
    "genuinely bears on their post — speak as the founder ('we build...', 'when we shipped "
    "X we found...') — THEN optionally add a sharp follow-up question. Only fall back to a "
    "pure question when nothing grounded honestly fits. Never fabricate anything.\n"
    "- Describe our products ONLY in the general terms given in the facts below. NEVER "
    "claim a specific analysis, study, result, or metric not literally in those facts — if "
    "the post's topic is outside our lane (partisan politics, breaking hard news), ask a "
    "genuine question instead of stretching.\n"
    "- AT MOST ONE product mention per comment, and only when genuinely relevant. A natural "
    "pointer ('we publish it publicly at creed-ai.org') is fine; a hard sell is NOT — no "
    "'DM me', no 'book a call', no pricing, no engagement bait.\n"
    "- MOST posts will NOT warrant a product mention. If the post is about something we "
    "don't build (a certification, a tool review, a hiring post, general career advice), "
    "do NOT force one in — a genuinely curious, specific question with ZERO product talk "
    "is the right comment there.\n"
    "- Do NOT sign the comment. No emoji spam, no hashtag stuffing.\n"
    "- Do NOT open with flattery ('Great point', 'Interesting', 'Well said', 'Great post'). "
    "Lead with the substance.\n"
    f"- Length: up to {_COMMENT_MAX_CHARS} characters, but substance over length."
)

_KYTRAN_MARKETING_FEWSHOT = (
    "STYLE REFERENCES (post -> good comment):\n"
    "POST: \"Small businesses want AI but don't know where to start — most pilots die in "
    'month two..."\n'
    "COMMENT: The month-two die-off usually happens because the pilot was a chatbot bolted "
    "on, not a worker wired into real operations. We build AI staff for exactly this — "
    "agents that take a defined role inside the client's existing tools, with a human "
    "approval gate so trust builds before autonomy does. The biggest adoption unlock we've "
    "seen: start with one narrow, measurable job, not a platform. What's the failure "
    "pattern you see most — wrong use case, or wrong expectations?\n"
    "---\n"
    "POST: \"Trust in AI is falling; companies say 'responsible AI' but nobody can verify "
    'it..."\n'
    "COMMENT: Verification is the whole game — 'responsible' claims without receipts are "
    "just marketing. We took the uncomfortable route and publish a live transparency score "
    "on our own AI (accountability, fairness, privacy, safety, transparency), graded "
    "continuously rather than audited once a year — public at creed-ai.org. It keeps us "
    "honest and it's checkable by anyone. I'd like to see scoring like this become table "
    "stakes for anyone selling AI.\n"
    "---\n"
    "POST: \"The CCNA is still the gold standard for getting into networking — here's how "
    "I'd study for it in 2026...\"\n"
    "(note: an off-lane post — the right comment has NO product mention, just genuine "
    "curiosity)\n"
    "COMMENT: The fundamentals argument holds up — subnetting and routing intuition "
    "transfer to everything from cloud networking to self-hosted infrastructure. Curious "
    "whether you'd still start people on the full CCNA track today, or go labs-first and "
    "let the cert follow once the muscle memory exists?"
)

_KYTRAN_BRAND_FACTS = (
    "\nBRAND FACTS (all real — same never-fabricate rule applies):\n"
    "- We build commissioned 'AI staff' for businesses — agent teams with human approval "
    "gates; public intake at platform.kytranempowerment.com/commission.\n"
    "- Kytran Business Suite (business.kytranempowerment.com) is our SMB operations suite.\n"
    "- The Watch Series products are live (gov/legal/civic/market.kytranempowerment.com, "
    "what-the-fact.com); C.R.E.E.D.'s live AI transparency score is public at creed-ai.org.\n"
)

_PERSONAS = {
    "terry": {
        "persona": (
            "Terry Caetano — Canadian civic-tech builder/journalist behind the Watch "
            "Series + What The Fact; sovereign, ethical civic-intelligence AI."
        ),
        "rules": None,  # resolved to the module defaults in _persona_pack()
        "fewshot": None,
        "extra_facts": "",
    },
    "kytran_marketing": {
        "persona": (
            "Kytran Katarn — Founder & CEO, Kytran Empowerment Inc.: sovereign Canadian "
            "civic-intelligence AI (A.R.C.H.I.E. platform, the Watch Series, What The "
            "Fact, C.R.E.E.D., Kytran Business Suite). Brand voice: confident builder "
            "promoting what we actually ship."
        ),
        "rules": _KYTRAN_MARKETING_RULES,
        "fewshot": _KYTRAN_MARKETING_FEWSHOT,
        "extra_facts": _KYTRAN_BRAND_FACTS,
    },
}


def _persona_pack(voice: str = None) -> dict:
    """Resolve a registry ``voice_key`` to its persona pack {persona, rules, fewshot,
    extra_facts}. Unknown non-empty voice_key = raw custom persona line over the default
    (Terry) rules/few-shot; empty/None = Terry."""
    if voice and voice in _PERSONAS:
        pack = dict(_PERSONAS[voice])
    elif voice:
        pack = {"persona": voice, "rules": None, "fewshot": None, "extra_facts": ""}
    else:
        pack = dict(_PERSONAS["terry"])
    pack["rules"] = pack.get("rules") or _ENGAGEMENT_RULES
    pack["fewshot"] = pack.get("fewshot") or _ENGAGEMENT_FEWSHOT
    return pack


_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def _draft_is_sane(text: str) -> bool:
    """Reject degenerate drafts BEFORE they reach the approval queue: the EN
    engagement voice must never contain CJK — qwen code-switches under pressure
    and once leaked its meta-instructions in Chinese mid-comment (approval #1827,
    2026-07-02). A sub-80-char draft is a truncation/refusal artifact."""
    if not text or len(text) < 80:
        return False
    if _CJK_RE.search(text):
        return False
    return True


_SIGNATURE_RE = re.compile(
    r"\n+\s*(?:[-–—]{1,2}\s*)?(?:best|regards|cheers|sincerely|thanks|thank you)[,!.\s]*$"
    r"|\n+\s*[-–—]{1,2}\s*(?:terry(?:\s+caetano)?|kytran(?:\s+katarn)?)\s*$",
    re.IGNORECASE,
)


def _strip_comment_signature(text: str) -> str:
    """Defense-in-depth: strip an accidental sign-off / name signature the model
    sometimes appends (the old drafts signed every comment 'Kytran Katarn')."""
    prev = None
    while text and text != prev:
        prev = text
        text = _SIGNATURE_RE.sub("", text).rstrip()
    return text


def _draft_comment(snippet: str, author: str = "the author", voice: str = None, model: str = None) -> str:
    """Draft a Terry-voiced, factually-grounded LinkedIn comment via S.I.G.N.A.L.
    dispatch. '' on any failure. Voice + grounding + guards per KB #277108.
    Routes to a capable local model (``model`` or ``_DEFAULT_DRAFT_MODEL``); local-only.

    ``voice`` (S7-P1-4a): the acting account's registry voice_key, resolved via
    _persona_pack() — 'terry' (peer civic-tech, KB #277108) | 'kytran_marketing'
    (founder brand voice, Phase 5) | any other non-empty value = raw custom persona
    line over the default rules/few-shot | empty = Terry."""
    from services.welfare_governance_service import pool_over_budget_by_skill

    # Welfare gate (ADR-002): skip engagement-comment drafting when the social_content
    # pool has no 24h token-budget headroom. Fail-open. '' is the caller's skip signal.
    if pool_over_budget_by_skill("social_content", "welfare:signal:pool_pause_ratio"):
        logger.info(
            "[signal-engagement] comment drafting deferred — social_content pool over "
            "24h token budget (welfare-gated, ADR-002)"
        )
        return ""

    try:
        from services.cluster_dispatch import queued_dispatch_text

        pack = _persona_pack(voice)
        # Live topical grounding (fail-open): recent REAL WTF headlines.
        wtf_block = ""
        try:
            from services.signal_calendar_service import _wtf_recent_headlines

            wtf = _wtf_recent_headlines(4)
            if wtf:
                wtf_block = f"\nRecent REAL What The Fact headlines you may reference:\n{wtf}\n"
        except Exception:  # noqa: BLE001 — grounding is optional
            pass

        prompt = (
            f"Persona: {pack['persona']}\n\n"
            f"{pack['rules']}\n\n"
            f"{_ENGAGEMENT_STACK_FACTS}{pack['extra_facts']}{wtf_block}\n\n"
            f"{pack['fewshot']}\n\n"
            f"Now write ONE comment replying to this post by {author}. "
            f"Output ONLY the comment text — no preamble, no quotes, no sign-off.\n\n"
            f"POST: {(snippet or '')[:800]}"
        )
        # Queue-aware dispatch (KB #276153): a cold model gets QUEUED, not failed —
        # queued_dispatch_text polls dispatch_pending_queue through the cold load
        # instead of silently dropping the draft like a bare dispatch() would.
        raw = queued_dispatch_text(
            "social_content",
            prompt,
            module_id="signal_engagement",
            local_only=True,
            model_override=(model or _DEFAULT_DRAFT_MODEL),
            poll_timeout_s=300,
        )
        if raw:
            text = raw.strip().strip('"').strip()
            text = _strip_comment_signature(text)
            if not _draft_is_sane(text):
                logger.warning(
                    "[signal-engagement] draft failed sanity guard (CJK/too-short) — skipped: %r", text[:120]
                )
                return ""
            return text[:_COMMENT_MAX_CHARS]
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
                        "snippet": (p.get("snippet") or "")[:500],
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
            # Preview the drafted comment without creating approvals (Phase 0/4 samples).
            if include_comments:
                c["draft_comment"] = _draft_comment(
                    c.get("snippet", ""), c.get("author", "") or "the author", voice=voice
                )
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
