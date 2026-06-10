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

from database import get_db_cursor
from services import browser_service

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
    targets = {url: lid for lid, url in watched_post_urls()}
    for u in extra_urls or []:
        targets.setdefault(u, None)

    total_new = total_seen = posts = 0
    errors = []
    for url, log_id in targets.items():
        r = ingest_post_comments(url, post_log_id=log_id)
        if r.get("error"):
            errors.append({"url": url, "error": r["error"]})
            continue
        posts += 1
        total_new += r["new"]
        total_seen += r["total"]
    summary = {"posts_polled": posts, "comments_seen": total_seen, "new_comments": total_new, "errors": errors}
    logger.info("[CommentMonitor] run complete: %s", summary)
    return summary


def list_recent_comments(limit: int = 50, unseen_only: bool = False) -> list:
    """For the S.I.G.N.A.L. read surface."""
    where = "WHERE NOT seen" if unseen_only else ""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""
            SELECT id, post_url, author, author_headline, body, is_reply,
                   commented_at, account, seen, reply_status, first_seen_at
            FROM linkedin_comments
            {where}
            ORDER BY first_seen_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(r) if isinstance(r, dict) else r for r in rows]
