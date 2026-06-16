"""mailbox_story_service.py — Mailbox Story Extractor Phase 3 (timeline + story synthesis).

Two outputs per fully-enriched import:
  * TIMELINE — deterministic: one mailbox_timeline_events row per enriched email, dated by its
    fact.event_date (else sent_at), carrying the summary + advisory sensitivity + entity ids.
  * STORIES  — per entity/project cluster, a LOCAL LLM (capability='summarize', local_only=True)
    writes the narrative arc of that person/org/project across the mailbox.

PRIVACY: story synthesis dispatch is pinned local_only=True (no cloud), same as Phase 2 enrichment.
Run by the scheduled mailbox_story_worker (jobs.py) once an import is 'done' (fully enriched),
or via the manual /api/imports/<id>/build-story kick. Rebuildable: wipes + rewrites per build.
"""

import logging

from database import get_db_cursor


def _ensure_import_paths():
    """department_dispatcher does `from db import ...` (resolves from the ai_bridge pkg dir);
    add /app + wherever ai_bridge resolves so the dispatcher import works outside the app boot
    path (scheduler sidecar, bare exec). KB #272154."""
    import importlib.util
    import sys

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    spec = importlib.util.find_spec("ai_bridge")
    if spec and spec.submodule_search_locations:
        pkg_dir = list(spec.submodule_search_locations)[0]
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)


try:
    _ensure_import_paths()
    from tools.department_hq.services.department_dispatcher import dispatch
except Exception:  # pragma: no cover - import-path guard; resolved lazily
    dispatch = None

logger = logging.getLogger(__name__)

CAPABILITY = "summarize"
MODULE_ID = "mailbox_story"
_MIN_EMAILS_PER_CLUSTER = 2  # an entity needs >=2 emails to be worth a "story arc"
_MAX_STORIES = 12
_MAX_LINES = 40  # chronological email lines fed to the synth prompt per cluster

SYSTEM_PROMPT = (
    "You are an intelligence analyst writing the factual story of one subject (a person, "
    "organisation, or project) as it appears across a mailbox. Use ONLY the supplied emails. "
    "Write 2-4 plain sentences describing the arc of events over time. No speculation, no preamble."
)


def _dispatch_fn():
    fn = dispatch
    if fn is None:
        _ensure_import_paths()
        from tools.department_hq.services.department_dispatcher import dispatch as fn
    return fn


def build_timeline(import_id):
    """Deterministically (re)build the timeline for an import from its enriched emails. Returns count."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM mailbox_timeline_events WHERE import_id=%s", (import_id,))
        cur.execute(
            """
            SELECT e.id, e.subject, e.sent_at, f.summary, f.event_date, f.event_title, f.sensitivity,
                   COALESCE(array_agg(me.entity_id) FILTER (WHERE me.entity_id IS NOT NULL), '{}') AS entity_ids
            FROM mailbox_emails e
            LEFT JOIN mailbox_email_facts f ON f.email_id = e.id
            LEFT JOIN mailbox_email_entities me ON me.email_id = e.id
            WHERE e.import_id = %s AND e.enrich_status = 'done'
            GROUP BY e.id, f.summary, f.event_date, f.event_title, f.sensitivity
            ORDER BY COALESCE(f.event_date, e.sent_at::date) NULLS LAST, e.id
            """,
            (import_id,),
        )
        rows = cur.fetchall()
        n = 0
        for r in rows:
            ev_date = r["event_date"] or (r["sent_at"].date() if r["sent_at"] else None)
            title = (r["event_title"] or r["subject"] or "(no subject)")[:300]
            cur.execute(
                """INSERT INTO mailbox_timeline_events
                       (import_id, event_date, title, description, sensitivity, email_id, entity_ids)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    import_id,
                    ev_date,
                    title,
                    (r["summary"] or "")[:1000],
                    r["sensitivity"],
                    r["id"],
                    list(r["entity_ids"]),
                ),
            )
            n += 1
    return n


def _clusters(import_id):
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT en.id, en.name, en.entity_type, en.mention_count,
                   COUNT(DISTINCT me.email_id) AS email_count
            FROM mailbox_entities en
            JOIN mailbox_email_entities me ON me.entity_id = en.id
            JOIN mailbox_emails e ON e.id = me.email_id AND e.enrich_status = 'done'
            WHERE en.import_id = %s
            GROUP BY en.id
            HAVING COUNT(DISTINCT me.email_id) >= %s
            ORDER BY en.mention_count DESC, email_count DESC
            LIMIT %s
            """,
            (import_id, _MIN_EMAILS_PER_CLUSTER, _MAX_STORIES),
        )
        return cur.fetchall()


def _cluster_emails(entity_id):
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """
            SELECT e.id, e.subject, e.sent_at, f.summary
            FROM mailbox_email_entities me
            JOIN mailbox_emails e ON e.id = me.email_id
            LEFT JOIN mailbox_email_facts f ON f.email_id = e.id
            WHERE me.entity_id = %s
            ORDER BY e.sent_at NULLS LAST, e.id
            LIMIT %s
            """,
            (entity_id, _MAX_LINES),
        )
        return cur.fetchall()


def build_stories(import_id):
    """(Re)build per-cluster stories via local-only synthesis.
    Returns {'stories': n, 'deferred': bool} — deferred=True means a model was cold (retry later)."""
    clusters = _clusters(import_id)
    if not clusters:
        # No multi-email entities — clear any stale stories and report none.
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("DELETE FROM mailbox_stories WHERE import_id=%s", (import_id,))
        return {"stories": 0, "deferred": False}

    written = 0
    for c in clusters:
        emails = _cluster_emails(c["id"])
        if not emails:
            continue
        lines = []
        for e in emails:
            d = e["sent_at"].date().isoformat() if e["sent_at"] else "????-??-??"
            lines.append(f"[{d}] {(e['subject'] or '(no subject)')[:120]} — {(e['summary'] or '')[:200]}")
        prompt = (
            f"Subject of the story: {c['name']} ({c['entity_type']}).\n"
            f"Chronological emails involving this subject:\n" + "\n".join(lines) + "\n\n"
            "Write the 2-4 sentence factual narrative arc."
        )
        try:
            result = _dispatch_fn()(
                capability=CAPABILITY,
                prompt=prompt,
                module_id=MODULE_ID,
                system_prompt=SYSTEM_PROMPT,
                local_only=True,  # HARD no-cloud guard
            )
        except Exception:
            logger.exception("mailbox story synth dispatch failed entity=%s", c["id"])
            return {"stories": written, "deferred": True}

        if result is None or not getattr(result, "success", False):
            # Model cold/queued — defer the rest; stories already written stay.
            return {"stories": written, "deferred": True}

        narrative = (result.response if isinstance(result.response, str) else str(result.response or "")).strip()[:4000]
        if not narrative:
            continue
        cluster_key = f"{c['entity_type']}:{c['name'].lower()}"[:300]
        model_used = getattr(result, "model", None)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO mailbox_stories
                    (import_id, cluster_key, title, narrative, span_start, span_end, email_count, model_used)
                SELECT %s, %s, %s, %s, MIN(e.sent_at), MAX(e.sent_at), COUNT(*), %s
                FROM mailbox_email_entities me JOIN mailbox_emails e ON e.id = me.email_id
                WHERE me.entity_id = %s
                ON CONFLICT (import_id, cluster_key) DO UPDATE SET
                    title=EXCLUDED.title, narrative=EXCLUDED.narrative, span_start=EXCLUDED.span_start,
                    span_end=EXCLUDED.span_end, email_count=EXCLUDED.email_count, model_used=EXCLUDED.model_used,
                    created_at=now()
                """,
                (import_id, cluster_key, c["name"][:300], narrative, model_used, c["id"]),
            )
        written += 1
    return {"stories": written, "deferred": False}


def build_import_story(import_id):
    """Build timeline + stories for one import. Stamps story_built_at only when synthesis fully
    completed (not deferred), so a cold-model run retries next cycle. Returns counts + 'stamped'."""
    events = build_timeline(import_id)
    s = build_stories(import_id)
    stamped = not s["deferred"]
    if stamped:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("UPDATE mailbox_imports SET story_built_at=now() WHERE id=%s", (import_id,))
    logger.info(
        "mailbox story build import=%s: timeline=%d stories=%d deferred=%s",
        import_id,
        events,
        s["stories"],
        s["deferred"],
    )
    return {"timeline_events": events, "stories": s["stories"], "deferred": s["deferred"], "stamped": stamped}


def run_story_cycle(max_imports=3):
    """Find fully-enriched imports with no story yet and build them (scheduled worker entry)."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id FROM mailbox_imports
               WHERE status='done' AND story_built_at IS NULL
               ORDER BY created_at LIMIT %s""",
            (max_imports,),
        )
        ids = [r["id"] for r in cur.fetchall()]
    built = 0
    for iid in ids:
        if build_import_story(iid).get("stamped"):
            built += 1
    if ids:
        logger.info("mailbox story cycle: imports=%d built=%d", len(ids), built)
    return {"imports": len(ids), "built": built}
