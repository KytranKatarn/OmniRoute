"""Chronicle LinkedIn source (slice 07) — Terry's stored LinkedIn corpus -> Chronicle.

Reads the already-stored LinkedIn tables for the target account (Terry, account_key='terry',
agent_platform_accounts.id=2, browser_agent_id=377) and lands them via ingest_source
(source_kind='linkedin'). Authored content (posts, comment replies, engagement comments) is tagged
from_addr='Terry Caetano' so the later voice corpus can filter to authored items; inbound comments
carry the external author. Timestamps + engaged links preserved (link appended into body_text —
mailbox_emails has no link column).

`run_linkedin_ingest` is all local DB reads; no external API / LLM / DHQ.
`run_profile_ingest` (#5644) is the ONE exception: it drives the `linkedin_profile_view`
browser skill through the archie_browser sidecar to capture Terry's live profile
(headline / About / skills / experience) and lands it as a Chronicle item. Still no LLM.

WHY NO `linkedin_profile` TABLE (ADR-986): Chronicle is the corpus hub. A parallel
per-source profile store was started and discarded — the profile is just another
authored item in the one corpus, which is what makes it reachable by the entity
resolver, the story service and (Slice 10) the voice profile without new plumbing.
Snapshots are content-addressed, so an unchanged profile is skipped and a CHANGED
profile lands as a new dated snapshot — the history is the point for voice drift.
"""

import hashlib
import json
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


_PROFILE_SIG_KEYS = ("headline", "location", "about", "skills", "experience")


def _profile_signature(fields):
    """Stable content hash of the parts of a profile that carry voice.

    Excludes volatile chrome (follower counts, screenshot path, final_url) so a
    re-capture of an UNCHANGED profile produces the same message_id and is skipped
    by ingest_source. Sorting is deliberate for skills (LinkedIn reorders them by
    endorsement count) but NOT for experience, where order IS the meaning."""
    payload = {
        "headline": " ".join((fields.get("headline") or "").split()),
        "location": " ".join((fields.get("location") or "").split()),
        "about": " ".join((fields.get("about") or "").split()),
        "skills": sorted(s.strip() for s in (fields.get("skills") or []) if s and s.strip()),
        "experience": [e.strip() for e in (fields.get("experience") or []) if e and e.strip()],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _profile_body(fields, profile_url):
    """Render the captured profile as readable text — this is what a voice model reads."""
    parts = []
    if fields.get("headline"):
        parts.append(f"Headline: {fields['headline'].strip()}")
    if fields.get("location"):
        parts.append(f"Location: {fields['location'].strip()}")
    if fields.get("about"):
        parts.append(f"About:\n{fields['about'].strip()}")
    skills = [s.strip() for s in (fields.get("skills") or []) if s and s.strip()]
    if skills:
        parts.append("Skills:\n" + "\n".join(f"- {s}" for s in skills))
    # Raw ordered lines, NOT parsed entries — see the skill's docstring: a mis-parsed
    # experience entry is worse than an unparsed one.
    exp = [e.strip() for e in (fields.get("experience") or []) if e and e.strip()]
    if exp:
        parts.append("Experience:\n" + "\n".join(exp))
    return _with_link("\n\n".join(parts), profile_url, "Profile")


def _map_profile(fields, profile_url, captured_at=None):
    """Pure: captured profile fields -> a Chronicle item (content-addressed snapshot)."""
    sig = _profile_signature(fields)
    headline = " ".join((fields.get("headline") or "").split())
    return {
        "message_id": f"li:profile:{sig}",
        "folder": "linkedin/profile",
        "from_addr": TERRY,
        "subject": _subject(headline, "LinkedIn profile"),
        "body_text": _profile_body(fields, profile_url),
        "sent_at": captured_at,
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


def _fetch_profile_url(agent_id):
    """The agent's own LinkedIn URL from the registry — NEVER hardcoded, so a corrected
    URL is a data edit. Returns None when the agent has no row (migration 468 adds 377's)."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT profile_url FROM agent_social_profiles "
            "WHERE agent_id=%s AND platform='linkedin' AND COALESCE(is_active, TRUE) "
            "ORDER BY id LIMIT 1",
            (agent_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return (row["profile_url"] if isinstance(row, dict) else row[0]) or None


def _capture_profile(agent_id, profile_url):
    """Drive the linkedin_profile_view skill on the agent's OWN session. Separate
    function so tests monkeypatch it instead of touching the browser sidecar."""
    from services.browser_service import run_skill_sync

    return run_skill_sync(
        "linkedin_profile_view",
        {"profile_url": profile_url},
        agent_id=agent_id,
        timeout_s=180,
    )


def run_profile_ingest(account_key="terry", account_id=2, owner_id=4):
    """Capture the account's live LinkedIn profile and land it in Chronicle (#5644).

    Identity is resolved FAIL-LOUD via require_browser_id: browser_id_for defaults to
    342 (Kytran), and a silent default here would read the WRONG person's profile and
    file it as this account's authored voice corpus (ADR-028 — a path that cannot prove
    its identity must refuse, not guess).

    Returns a status dict. A failed/auth-walled capture ingests NOTHING and says so —
    an empty profile must never be written over a good snapshot.
    """
    from services.signal_accounts import require_browser_id

    agent_id = require_browser_id(account_key)  # raises UnknownAccountError

    profile_url = _fetch_profile_url(agent_id)
    if not profile_url:
        logger.warning("profile ingest: agent %s has no active linkedin row in agent_social_profiles", agent_id)
        return {"status": "no_profile_url", "agent_id": agent_id, "inserted": 0, "skipped": 0}

    res = _capture_profile(agent_id, profile_url) or {}
    if not res.get("success"):
        logger.warning(
            "profile ingest: capture failed for agent %s (%s)", agent_id, res.get("result") or "no reason given"
        )
        return {
            "status": "capture_failed",
            "agent_id": agent_id,
            "profile_url": profile_url,
            "reason": res.get("result") or res.get("error"),
            "inserted": 0,
            "skipped": 0,
        }

    item = _map_profile(res, profile_url)
    # A capture that "succeeded" but carries no voice-bearing text is not a snapshot.
    if not (res.get("about") or res.get("headline") or res.get("skills") or res.get("experience")):
        return {
            "status": "empty_profile",
            "agent_id": agent_id,
            "profile_url": profile_url,
            "strategy": res.get("strategy"),
            "inserted": 0,
            "skipped": 0,
        }

    out = ingest_source(
        "linkedin",
        account_id,
        [item],
        owner_id=owner_id,
        is_live=True,
        title=f"linkedin: {account_key}",
    )
    return {
        "status": "ok",
        "agent_id": agent_id,
        "profile_url": profile_url,
        "message_id": item["message_id"],
        "skills_count": len(res.get("skills") or []),
        "experience_count": len(res.get("experience") or []),
        # Surfaced so "0 skills" is self-explaining: 'none' means the selector found no
        # section at all, which is a break; 'anchor_id' with 0 means genuinely empty.
        "strategy": res.get("strategy"),
        **out,
    }


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
