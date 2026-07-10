"""Chronicle LinkedIn source (slice 07) — Terry's stored LinkedIn corpus -> Chronicle.

Reads the already-stored LinkedIn tables for the target account (Terry, account_key='terry',
agent_platform_accounts.id=2, browser_agent_id=377) and lands them via ingest_source
(source_kind='linkedin'). Authored content (posts, comment replies, engagement comments) is tagged
from_addr='Terry Caetano' so the later voice corpus can filter to authored items; inbound comments
carry the external author. Timestamps + engaged links preserved (link appended into body_text —
mailbox_emails has no link column). All local DB reads; no external API / LLM / DHQ.
"""

import logging

from services.chronicle_ingest import ingest_source

logger = logging.getLogger(__name__)

TERRY = "Terry Caetano"


def _norm_key(text):
    return " ".join((text or "").lower().split())[:200]


def _with_link(body, url, label="Source"):
    body = (body or "").strip()
    return f"{body}\n\n{label}: {url}".strip() if url else body


def _subject(text, fallback):
    t = " ".join((text or "").split())
    return t[:80] or fallback


def _g(row, key):
    return row[key] if isinstance(row, dict) else None  # rows are RealDictRow; keep simple


# ---- pure row -> item mappers ----
def _map_post(row, source, url=None):
    content = _g(row, "content") or ""
    return {
        "message_id": f"li:{source}:{_g(row, 'id')}",
        "folder": "linkedin/posts",
        "from_addr": TERRY,
        "subject": _subject(content, "LinkedIn post"),
        "body_text": _with_link(content, url, "LinkedIn"),
        "sent_at": _g(row, "sent_at"),
        "has_attachments": False,
    }


def _map_inbound_comment(row):
    return {
        "message_id": f"li:comment:in:{_g(row, 'id')}",
        "folder": "linkedin/comments_inbound",
        "from_addr": _g(row, "author") or "LinkedIn user",
        "subject": _subject(_g(row, "body"), "Comment on Terry's post"),
        "body_text": _with_link(_g(row, "body"), _g(row, "comment_url"), "On"),
        "sent_at": _g(row, "first_seen_at"),
        "has_attachments": False,
    }


def _map_reply(row):
    return {
        "message_id": f"li:comment:reply:{_g(row, 'id')}",
        "folder": "linkedin/comments_reply",
        "from_addr": TERRY,
        "in_reply_to": _g(row, "comment_urn"),
        "subject": _subject(_g(row, "draft_reply"), "Reply"),
        "body_text": _with_link(_g(row, "draft_reply"), _g(row, "comment_url"), "On"),
        "sent_at": _g(row, "last_seen_at") or _g(row, "first_seen_at"),
        "has_attachments": False,
    }


def _map_engagement(row):
    return {
        "message_id": f"li:engage:{_g(row, 'id')}",
        "folder": "linkedin/engagement",
        "from_addr": TERRY,
        "subject": _subject(_g(row, "comment_text"), "Engagement comment"),
        "body_text": _with_link(_g(row, "comment_text"), _g(row, "url"), "On"),
        "sent_at": _g(row, "sent_at"),
        "has_attachments": False,
    }


# ---- DB fetchers (raw rows; monkeypatched in tests) ----
def _fetch_post_log(account_key):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, content, post_url, posted_at AS sent_at FROM linkedin_post_log "
            "WHERE post_type=%s AND content IS NOT NULL ORDER BY posted_at NULLS LAST",
            (account_key,),
        )
        return cur.fetchall()


def _fetch_calendar(account_key):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, content, COALESCE(posted_at, scheduled_at, created_at) AS sent_at "
            "FROM agent_content_posts WHERE post_type=%s AND content IS NOT NULL",
            (account_key,),
        )
        return cur.fetchall()


def _fetch_drafts(account_key):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, action_data->>'content' AS content, "
            "COALESCE(executed_at, created_at) AS sent_at FROM autonomy_approval_queue "
            "WHERE action_type='linkedin_post' AND action_data->>'post_type'=%s "
            "AND action_data->>'content' IS NOT NULL",
            (account_key,),
        )
        return cur.fetchall()


def _fetch_comments(account_key):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, author, body, draft_reply, comment_url, comment_urn, "
            "first_seen_at, last_seen_at FROM linkedin_comments WHERE account=%s",
            (account_key,),
        )
        return cur.fetchall()


def _fetch_engagement(agent_id):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, comment_text, COALESCE(comment_url, post_urn) AS url, "
            "COALESCE(executed_at, created_at) AS sent_at FROM linkedin_engagement_ledger "
            "WHERE acting_agent_id=%s AND comment_text IS NOT NULL AND comment_text <> ''",
            (agent_id,),
        )
        return cur.fetchall()


def run_linkedin_ingest(account_key="terry", account_id=2, agent_id=377, owner_id=4):
    """Read Terry's LinkedIn corpus from 5 tables, map to items (content-dedup the overlapping
    post tables), and land them via ingest_source(source_kind='linkedin'). Returns a summary."""
    items = []
    seen = set()

    # Authored posts — priority log -> calendar -> draft; content-hash dedup across the three.
    for row in _fetch_post_log(account_key):
        key = _norm_key(_g(row, "content"))
        if key and key not in seen:
            seen.add(key)
            items.append(_map_post(row, "post:log", _g(row, "post_url")))
    for row in _fetch_calendar(account_key):
        key = _norm_key(_g(row, "content"))
        if key and key not in seen:
            seen.add(key)
            items.append(_map_post(row, "post:cal"))
    for row in _fetch_drafts(account_key):
        key = _norm_key(_g(row, "content"))
        if key and key not in seen:
            seen.add(key)
            items.append(_map_post(row, "post:draft"))

    # Comments: inbound (external author) always; Terry's reply when draft_reply present.
    for row in _fetch_comments(account_key):
        if _g(row, "body"):
            items.append(_map_inbound_comment(row))
        if _g(row, "draft_reply"):
            items.append(_map_reply(row))

    # Engagement comments (authored).
    for row in _fetch_engagement(agent_id):
        items.append(_map_engagement(row))

    if not items:
        return {"import_id": None, "inserted": 0, "skipped": 0, "items": 0}
    res = ingest_source(
        "linkedin",
        account_id,
        items,
        owner_id=owner_id,
        is_live=True,
        title=f"linkedin: {account_key}",
    )
    return {**res, "items": len(items)}
