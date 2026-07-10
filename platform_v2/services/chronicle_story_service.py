"""Chronicle per-entity story synthesis (slice 09) — LOCAL summarize, no cloud.

For each chronicle_entity with >=2 mentioning emails (across all its linked source occurrences —
email, LinkedIn, uploads), gathers a chronological digest and dispatches a LOCAL summarize model
(local_only=True, mirroring mailbox_story_service) to write a 2-4 sentence factual narrative arc into
chronicle_entity_story (upsert, one per entity). Resumable (skips entities that already have a story);
defers cleanly when the model is cold/queued (stories already written persist). Privacy: dispatch is
pinned local_only=True.
"""

import logging

from psycopg2.extras import Json

logger = logging.getLogger(__name__)

CAPABILITY = "summarize"
MODULE_ID = "chronicle"
SYSTEM_PROMPT = (
    "You are a factual biographer. From the chronological records provided, write a concise, "
    "accurate narrative arc. Use only what the records state — no speculation, no invented facts."
)
_MIN_EMAILS_PER_CLUSTER = 2
_MAX_LINES = 40


def _dispatch_fn():
    """Lazy import so tests can monkeypatch this to avoid a real dispatch."""
    from tools.department_hq.services.department_dispatcher import dispatch as fn

    return fn


def _build_prompt(name, entity_type, lines):
    return (
        f"Subject of the story: {name} ({entity_type}).\n"
        f"Chronological records involving this subject:\n" + "\n".join(lines) + "\n\n"
        "Write the 2-4 sentence factual narrative arc."
    )


def _scalar(row):
    if row is None:
        return None
    return row["id"] if isinstance(row, dict) else row[0]


def _fetch_candidates(owner_id, limit):
    """chronicle_entity (owner) with >= _MIN emails and NO story yet, most-connected first."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT ce.id, ce.canonical_name, ce.entity_type, "
            "count(DISTINCT mee.email_id) AS ecount "
            "FROM chronicle_entity ce "
            "JOIN chronicle_entity_link cel ON cel.chronicle_entity_id=ce.id "
            "JOIN mailbox_email_entities mee ON mee.entity_id=cel.mailbox_entity_id "
            "WHERE ce.owner_id IS NOT DISTINCT FROM %s "
            "AND NOT EXISTS (SELECT 1 FROM chronicle_entity_story s WHERE s.chronicle_entity_id=ce.id) "
            "GROUP BY ce.id, ce.canonical_name, ce.entity_type "
            "HAVING count(DISTINCT mee.email_id) >= %s "
            "ORDER BY count(DISTINCT mee.email_id) DESC LIMIT %s",
            (owner_id, _MIN_EMAILS_PER_CLUSTER, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def _fetch_entity_emails(chronicle_entity_id):
    """Chronological (sent_at, subject, body_text, source_kind) for an entity, <= _MAX_LINES."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT DISTINCT em.sent_at, em.subject, em.body_text, i.source_kind "
            "FROM chronicle_entity_link cel "
            "JOIN mailbox_email_entities mee ON mee.entity_id=cel.mailbox_entity_id "
            "JOIN mailbox_emails em ON em.id=mee.email_id "
            "JOIN mailbox_imports i ON i.id=em.import_id "
            "WHERE cel.chronicle_entity_id=%s ORDER BY em.sent_at NULLS LAST LIMIT %s",
            (chronicle_entity_id, _MAX_LINES),
        )
        return [dict(r) for r in cur.fetchall()]


def _write_story(entity_id, narrative, span_start, span_end, source_kinds, email_count, model_used):
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO chronicle_entity_story (chronicle_entity_id, narrative, span_start, span_end, "
            "source_kinds, email_count, model_used, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now()) "
            "ON CONFLICT (chronicle_entity_id) DO UPDATE SET narrative=EXCLUDED.narrative, "
            "span_start=EXCLUDED.span_start, span_end=EXCLUDED.span_end, "
            "source_kinds=EXCLUDED.source_kinds, email_count=EXCLUDED.email_count, "
            "model_used=EXCLUDED.model_used, updated_at=now()",
            (entity_id, narrative, span_start, span_end, Json(sorted(source_kinds)), email_count, model_used),
        )


def run_entity_stories(owner_id=4, limit=12):
    """Synthesize + upsert a story for up to `limit` not-yet-storied entities (>=2 emails).
    Returns {stories, deferred}. Defers (stops) cleanly if the local model is cold/queued."""
    written = 0
    for c in _fetch_candidates(owner_id, limit):
        emails = _fetch_entity_emails(c["id"])
        if len(emails) < _MIN_EMAILS_PER_CLUSTER:
            continue
        lines = []
        for e in emails:
            d = e["sent_at"].date().isoformat() if e.get("sent_at") else "????-??-??"
            lines.append(f"[{d}] {(e.get('subject') or '(no subject)')[:120]} — {(e.get('body_text') or '')[:200]}")
        prompt = _build_prompt(c["canonical_name"], c["entity_type"], lines)
        try:
            result = _dispatch_fn()(
                capability=CAPABILITY,
                prompt=prompt,
                module_id=MODULE_ID,
                system_prompt=SYSTEM_PROMPT,
                local_only=True,
            )
        except Exception:
            logger.exception("chronicle story dispatch failed entity=%s", c["id"])
            return {"stories": written, "deferred": True}

        if result is None or not getattr(result, "success", False):
            return {"stories": written, "deferred": True}  # model cold/queued — stop, keep what's written

        narrative = (result.response if isinstance(result.response, str) else str(result.response or "")).strip()[:4000]
        if not narrative:
            continue
        dates = [e["sent_at"] for e in emails if e.get("sent_at")]
        source_kinds = {e.get("source_kind") for e in emails if e.get("source_kind")}
        _write_story(
            c["id"],
            narrative,
            (min(dates) if dates else None),
            (max(dates) if dates else None),
            source_kinds,
            len(emails),
            getattr(result, "model", None),
        )
        written += 1
    return {"stories": written, "deferred": False}
