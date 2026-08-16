"""LinkedIn comment monitor — READ scope of #3964 (S.I.G.N.A.L. reply integration).

Polls the comment threads on posts we care about (our published posts from
``linkedin_post_log`` plus any explicitly-watched URLs) via the READ-only
``linkedin_post_comments`` browser skill, and upserts new comments into
``linkedin_comments`` so a human (and, later, the WRITE scope: R.O.S.E.T.T.A.
drafting + Telegram approval + reply-send) can act on them.

Posts NOTHING. Does not trip the LinkedIn step-up wall (KB #272122).
The scheduled drain + draft/approve/send legs are deliberately OUT of this
read-scope module; see #3964 follow-ups.
"""

import hashlib
import logging
import re
from urllib.parse import unquote

from database import get_db_cursor
from services import browser_service, signal_accounts
from services.signal_content_sanitizer import clean_draft

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = 342  # kytranempowerment session (matches browser_service default)


def _dedup_key(comment: dict) -> str:
    urn = (comment.get("urn") or "").strip()
    if urn:
        return urn
    raw = f"{comment.get('author', '')}|{(comment.get('text') or '')[:80]}"
    return "h:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def ingest_post_comments(
    post_url: str, post_log_id=None, account: str = "kytran", agent_id: int = DEFAULT_AGENT_ID
) -> dict:
    """Scrape one post's comments and upsert. Returns {new, total, error?}."""
    if not post_url:
        return {"new": 0, "total": 0, "error": "empty post_url"}
    res = browser_service.linkedin_post_comments(post_url, agent_id=agent_id)
    if not res.get("success"):
        return {"new": 0, "total": 0, "error": res.get("error", "skill failed")}

    comments = res.get("comments", [])
    new = 0
    with get_db_cursor(commit=True) as (conn, cur):
        for c in comments:
            key = _dedup_key(c)
            cur.execute(
                """
                INSERT INTO linkedin_comments
                    (post_url, post_log_id, comment_urn, dedup_key, author,
                     author_headline, body, is_reply, commented_at, account)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_url, dedup_key) DO UPDATE
                    SET body = EXCLUDED.body,
                        author_headline = EXCLUDED.author_headline,
                        last_seen_at = NOW()
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    post_url,
                    post_log_id,
                    (c.get("urn") or None),
                    key,
                    c.get("author"),
                    c.get("headline"),
                    c.get("text"),
                    bool(c.get("is_reply")),
                    c.get("timestamp"),
                    account,
                ),
            )
            row = cur.fetchone()
            if row["inserted"] if isinstance(row, dict) else row[0]:
                new += 1
    logger.info("[CommentMonitor] %s: %d comments, %d new", post_url, len(comments), new)
    return {"new": new, "total": len(comments)}


def _parse_notif(text: str):
    """Best-effort (author, body) from a notification card's text."""
    t = re.sub(r"\bUnread notification\.\s*", "", text or "").strip()
    # Strip LinkedIn's a11y/screen-reader prefixes so the author is a clean
    # name ("Status is reachable Kytran Katarn" -> "Kytran Katarn").
    for prefix in ("status is reachable", "status is online", "status is offline", "unread notification."):
        low = t.lower().lstrip()
        if low.startswith(prefix):
            t = t.lstrip()[len(prefix) :].lstrip(" .")
    author = ""
    for verb in (" commented", " replied", " mentioned", " and "):
        if verb in t:
            author = t.split(verb, 1)[0].strip()
            break
    body = ""
    # GROUP posts notify as "commented on your post in <group name>." — consume
    # the group clause so it doesn't pollute the captured comment body (#4604,
    # verified live on the WTF group 2026-07-02).
    m = re.search(
        r"(?:commented on your post(?: in [^.:\n]{1,80})?|replied to your comment|in a comment)[:.]?\s*(.*)",
        t,
        re.S,
    )
    if m:
        body = m.group(1).strip()
    if not body and "\n" in t:
        body = t.split("\n", 1)[1].strip()
    return author[:200], body[:1000]


def ingest_comment_notifications(account: str = "kytran", agent_id: int = None, limit: int = 25) -> dict:
    """Source comments-to-reply-to from the NOTIFICATION bell — the only place a
    comment DEEP-LINK (?commentUrn=, field ``comment_url``) is available. A plain
    post permalink renders ZERO comments to the automated session (KB #274178), so
    the post_url scrape path yields nothing; notifications are the working source.
    Upserts rows carrying ``comment_url`` (what linkedin_comment_reply needs)."""
    aid = agent_id or signal_accounts.browser_id_for((account or "").lower())
    res = browser_service.run_skill_sync("linkedin_notifications", {"limit": limit}, agent_id=aid, timeout_s=120)
    if browser_service.is_rate_limited(res):
        # Bucket exhausted (S6-P1-7a) — not a failure; retry on the next 6h cycle.
        logger.info("[CommentMonitor] notifications rate_limited — skipped, retry next cycle")
        return {"new": 0, "total": 0, "rate_limited": True}
    if not res or not res.get("success"):
        return {"new": 0, "total": 0, "error": (res or {}).get("error", "skill failed")}

    cards = [
        n for n in (res.get("notifications") or []) if n.get("comment_url") and n.get("type") in ("comment", "mention")
    ]
    new = 0
    with get_db_cursor(commit=True) as (conn, cur):
        for n in cards:
            cu = n["comment_url"]
            dec = unquote(cu)
            mact = re.search(r"activity:(\d+)", dec)
            # GROUP-post comment URNs use comment:(groupPost:<groupId>-<postId>,<id>)
            # instead of comment:(activity:<id>,<id>) — verified live on the WTF
            # group 2026-07-02 (#4604). Accept both.
            mcid = re.search(r"comment:\((?:activity:\d+|groupPost:[\d-]+),(\d+)\)", dec)
            if not (mact and mcid):
                continue
            activity, cid = mact.group(1), mcid.group(1)
            post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity}/"
            comment_urn = f"urn:li:comment:(activity:{activity},{cid})"
            author, body = _parse_notif(n.get("full_text") or n.get("text", ""))
            is_reply = "replied" in (n.get("text", "") or "").lower()
            cur.execute(
                "SELECT id FROM linkedin_post_log WHERE post_url LIKE %s ORDER BY id DESC LIMIT 1",
                (f"%{activity}%",),
            )
            prow = cur.fetchone()
            post_log_id = (prow["id"] if isinstance(prow, dict) else prow[0]) if prow else None
            cur.execute(
                """
                INSERT INTO linkedin_comments
                    (post_url, post_log_id, comment_urn, comment_url, dedup_key, author,
                     author_headline, body, is_reply, commented_at, account)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_url, dedup_key) DO UPDATE
                    SET comment_url = EXCLUDED.comment_url,
                        body = COALESCE(NULLIF(EXCLUDED.body, ''), linkedin_comments.body),
                        author = COALESCE(NULLIF(EXCLUDED.author, ''), linkedin_comments.author),
                        last_seen_at = NOW()
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    post_url,
                    post_log_id,
                    comment_urn,
                    cu,
                    cid,
                    author or None,
                    None,
                    body or None,
                    is_reply,
                    n.get("timestamp"),
                    account,
                ),
            )
            row = cur.fetchone()
            if row["inserted"] if isinstance(row, dict) else row[0]:
                new += 1
    logger.info("[CommentMonitor] notif-ingest %s: %d comment cards, %d new", account, len(cards), new)
    return {"new": new, "total": len(cards)}


def watched_post_urls(limit: int = 25) -> list:
    """Seed list: distinct non-empty post_urls from recent linkedin_post_log."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, post_url FROM linkedin_post_log
            WHERE post_url IS NOT NULL AND post_url <> ''
            ORDER BY COALESCE(posted_at, created_at) DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [(r["id"], r["post_url"]) if isinstance(r, dict) else (r[0], r[1]) for r in cur.fetchall()]


def run_comment_monitor(extra_urls: list = None) -> dict:
    """Poll all watched posts + any extra_urls. Returns summary dict.

    NOTE: seeds from linkedin_post_log.post_url. Those are currently NULL for
    posts published before URL-capture lands (posting was step-up-blocked) —
    so until then this drains only explicitly-passed extra_urls (e.g. a thread
    we commented on). See #3964 follow-up: capture post_url on publish.
    """
    # Notification-sourced ingest — the WORKING source (carries comment_url).
    # Post-permalink scraping below renders 0 comments to automation (KB #274178).
    notif_new = 0
    errors = []
    for acct in ("kytran", "terry"):
        try:
            nr = ingest_comment_notifications(acct)
            notif_new += nr.get("new", 0)
            if nr.get("error"):
                errors.append({"account": acct, "error": nr["error"]})
        except Exception as e:  # never let one account abort the run
            errors.append({"account": acct, "error": str(e)})

    targets = {url: lid for lid, url in watched_post_urls()}
    for u in extra_urls or []:
        targets.setdefault(u, None)

    total_new = total_seen = posts = 0
    for url, log_id in targets.items():
        r = ingest_post_comments(url, post_log_id=log_id)
        if r.get("error"):
            errors.append({"url": url, "error": r["error"]})
            continue
        posts += 1
        total_new += r["new"]
        total_seen += r["total"]
    summary = {
        "posts_polled": posts,
        "comments_seen": total_seen,
        "new_comments": total_new + notif_new,
        "notif_new": notif_new,
        "errors": errors,
    }
    logger.info("[CommentMonitor] run complete: %s", summary)
    return summary


# ───────────────────────── WRITE leg (#3992) ─────────────────────────
# Comment → grounded draft → Telegram approval → reply (linkedin_comment
# skill, addressed to the author). Drafting only ever creates a Tier-2
# approval — a human tap is the only thing that publishes. Grounding v1 =
# original post + comment + account voice (Email-Vault contact context
# plugs in here when Vault Phase 2.4 retrieval ships).

_OWN_AUTHOR_MARKERS = ("kytran", "terry caetano", "creed ai", "c.r.e.e.d")

# Browser identity per account → services.signal_accounts registry (migration 440).

_COMMENT_CHAR_LIMIT = 1250  # LinkedIn comment hard limit

_FR_HINTS = (
    " le ",
    " la ",
    " les ",
    " des ",
    " une ",
    " est ",
    " être ",
    " avec ",
    " pour ",
    " merci",
    " bonjour",
    " très ",
    " c'est ",
    " ça ",
    " été ",
)


def _looks_french(text: str) -> bool:
    t = f" {(text or '').lower()} "
    return sum(1 for m in _FR_HINTS if m in t) >= 2


def _trim_reply(text: str, limit: int = _COMMENT_CHAR_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: dot + 1] if dot > limit // 2 else cut).strip()


def _set_reply_status(comment_id: int, status: str, draft: str = None) -> None:
    with get_db_cursor(commit=True) as (_conn, cur):
        if draft is not None:
            cur.execute(
                "UPDATE linkedin_comments SET reply_status=%s, draft_reply=%s, seen=TRUE WHERE id=%s",
                (status, draft, comment_id),
            )
        else:
            cur.execute(
                "UPDATE linkedin_comments SET reply_status=%s, seen=TRUE WHERE id=%s",
                (status, comment_id),
            )


def draft_comment_replies(limit: int = 5) -> dict:
    """Draft replies for top-level comments awaiting one and queue each as a
    Tier-2 'linkedin_comment_reply' approval (Telegram). FR comments get an
    EN draft routed through the translate capability (R.O.S.E.T.T.A. path,
    standing rule KB #272121). Cold model → comment stays 'none' and is
    retried next run."""
    from services.signal_calendar_service import _ensure_import_paths

    _ensure_import_paths()
    from ai_bridge.agent_loop import request_approval
    from signal_dispatch import _VOICE_HINTS
    from tools.department_hq.services.department_dispatcher import dispatch
    from services.welfare_governance_service import pool_over_budget_by_skill

    # Welfare gate (ADR-002): defer reply drafting when the social_post_draft pool has no
    # 24h token-budget headroom. Fail-open. Comments stay reply_status='none' and are
    # retried next cycle. Tunable via platform_settings welfare:signal:pool_pause_ratio.
    if pool_over_budget_by_skill("social_post_draft", "welfare:signal:pool_pause_ratio"):
        logger.info(
            "[CommentMonitor] reply drafting deferred — social_post_draft pool over "
            "24h token budget (welfare-gated, ADR-002)"
        )
        return {
            "candidates": 0,
            "drafted": 0,
            "notes": [{"note": "welfare-gated: social_post_draft pool over 24h budget"}],
        }

    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT c.id, c.post_url, c.comment_url, c.author, c.author_headline, c.body, c.account,
                      l.content AS post_content, l.post_type
               FROM linkedin_comments c
               LEFT JOIN linkedin_post_log l ON l.id = c.post_log_id
               WHERE c.reply_status = 'none' AND NOT c.is_reply
                 AND COALESCE(c.body, '') <> ''
               ORDER BY c.first_seen_at ASC
               LIMIT %s""",
            (limit,),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    drafted = 0
    notes = []
    for c in candidates:
        author = (c.get("author") or "").strip()
        if any(m in author.lower() for m in _OWN_AUTHOR_MARKERS):
            _set_reply_status(c["id"], "skipped_own")
            notes.append({"id": c["id"], "note": "own comment — skipped"})
            continue

        post_type = (c.get("post_type") or "personal").lower()
        voice = _VOICE_HINTS.get(post_type, _VOICE_HINTS["personal"])
        prompt = (
            f"Someone commented on our LinkedIn post. Write a short reply comment.\n\n"
            f"Our original post:\n{(c.get('post_content') or '(unavailable)')[:1200]}\n\n"
            f"Comment from {author or 'a reader'}"
            f"{(' (' + c.get('author_headline') + ')') if c.get('author_headline') else ''}:\n"
            f"{c['body'][:800]}\n\n"
            f"{voice}\n"
            f"Reply guidelines: address them naturally by first name, engage with their "
            f"specific point, be warm and substantive, under 120 words, NO hashtags, "
            f"never invent facts or commitments. Return ONLY the reply text."
        )
        result = dispatch(capability="social_post_draft", prompt=prompt, prefer_agent="S.I.G.N.A.L.")
        draft = (getattr(result, "response", "") or "").strip()
        if not draft:
            notes.append({"id": c["id"], "note": "model cold/queued — retry next run"})
            continue

        if _looks_french(c["body"]):
            tr = dispatch(
                capability="translate",
                prompt=(
                    "Translate this LinkedIn reply into natural Québécois French. "
                    f"Return ONLY the translation.\n\n{draft}"
                ),
            )
            fr = (getattr(tr, "response", "") or "").strip()
            if fr:
                draft = fr
            else:
                notes.append({"id": c["id"], "note": "FR translate cold — queued EN draft"})

        draft = _trim_reply(clean_draft(draft, kind="reply"))  # #4373 — strip model preamble

        # #5653 — the reply MUST go out as the identity whose notification bell received
        # the comment (Terry answers Terry's, Kytran answers Kytran's). Resolve strictly:
        # browser_id_for() would answer 342 (Kytran's personal profile) for an unknown or
        # empty account, which would publish under the WRONG NAME with no error. Skip the
        # comment instead — an unattributable reply is not worth a wrong-identity post.
        try:
            acting_agent_id = signal_accounts.require_browser_id(c.get("account") or "")
        except signal_accounts.UnknownAccountError as exc:
            logger.error(
                "[CommentMonitor] comment %s has unresolvable account %r — NOT drafting a reply: %s",
                c["id"],
                c.get("account"),
                exc,
            )
            notes.append({"id": c["id"], "note": f"skipped — unresolvable account {c.get('account')!r}"})
            continue

        approval_id = request_approval(
            action_type="linkedin_comment_reply",
            action_data={
                "comment_id": c["id"],
                "post_url": c["post_url"],
                "comment_url": c.get("comment_url"),
                "comment_author": author,
                "reply": draft,
                "browser_agent_id": acting_agent_id,
                "author": author,
                "post_type": post_type,
            },
            reason=(
                f"💬 Reply to {author or 'a reader'} on a {post_type} post:\n\n"
                f"Their comment:\n{c['body'][:400]}\n\n"
                f"Draft reply:\n{draft[:900]}"
            ),
            tier=2,
            requested_by="S.I.G.N.A.L. comment monitor",
            priority=6,
        )
        _set_reply_status(c["id"], "drafted", draft)
        drafted += 1
        logger.info(
            "[CommentMonitor] drafted reply for comment %s → approval %s",
            c["id"],
            approval_id,
        )
    return {"candidates": len(candidates), "drafted": drafted, "notes": notes}


def list_recent_comments(limit: int = 50, unseen_only: bool = False) -> list:
    """For the S.I.G.N.A.L. read surface."""
    where = "WHERE NOT seen" if unseen_only else ""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""
            SELECT id, post_url, author, author_headline, body, is_reply,
                   commented_at, account, seen, reply_status, draft_reply,
                   first_seen_at
            FROM linkedin_comments
            {where}
            ORDER BY first_seen_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) if isinstance(r, dict) else r for r in cur.fetchall()]
    # isoformat the timestamptz — raw psycopg2 datetimes can break jsonify
    # (KB #269068); this list only ever shipped empty before the WRITE leg.
    for r in rows:
        if isinstance(r, dict) and r.get("first_seen_at") is not None:
            r["first_seen_at"] = r["first_seen_at"].isoformat()
    return rows
