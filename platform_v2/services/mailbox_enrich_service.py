"""mailbox_enrich_service.py — Mailbox Story Extractor Phase 2 enrichment (LOCAL-ONLY).

Per extracted email, a LOCAL fleet LLM (capability='analyze', dispatched local_only=True)
extracts: a 1-line summary, topic, category, an ADVISORY sensitivity tag, sentiment, an
optional dated event, and the people/orgs/projects/topics involved. Results land in
mailbox_email_facts / mailbox_entities / mailbox_email_entities.

PRIVACY (hard invariant): EVERY dispatch passes local_only=True — gov/secret mailbox content
never reaches a cloud model. The platform is also escalation_mode='local_only' (KB #269301);
local_only=True is the explicit per-call no-cloud guard on top of that. Sensitivity tags are
ADVISORY only (surfaced for human confirmation, never auto-acted on).

Run by the scheduled mailbox_enrich_worker (tools/department_hq/jobs.py) — welfare-gated,
rate-limited, resumable. Never call this on the web thread for a whole import.
"""

import json
import logging
import re

from database import get_db_cursor


def _ensure_import_paths():
    """department_dispatcher internally does `from db import ...`, which resolves from the
    ai_bridge package dir — add /app plus wherever ai_bridge resolves so the dispatcher import
    works outside the app boot path (scheduler sidecar, bare exec). KB #272154."""
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
except Exception:  # pragma: no cover - import-path guard; resolved lazily in enrich_one
    dispatch = None

logger = logging.getLogger(__name__)

CAPABILITY = "analyze"
MODULE_ID = "mailbox_story"
_BODY_CAP = 4000  # chars of body sent to the model per email
_SUBJECT_CAP = 300
_VALID_ENTITY_TYPES = {"person", "org", "project", "topic"}
_VALID_SENSITIVITY = {"normal", "gov", "secret", "personal"}
_VALID_SENTIMENT = {"positive", "neutral", "negative"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SYSTEM_PROMPT = (
    "You are a precise intelligence analyst reading ONE email from a mailbox under review. "
    "Extract only what is explicitly supported by the text. Do not speculate. "
    "Sensitivity is an ADVISORY guess for a human to confirm, never a directive. "
    "Respond with ONLY a single valid JSON object, no prose, no code fences."
)


def _build_prompt(row):
    subject = (row.get("subject") or "")[:_SUBJECT_CAP]
    body = (row.get("body_text") or "")[:_BODY_CAP]
    hdr = (
        f"From: {row.get('from_addr') or ''}\n"
        f"To: {row.get('to_addrs') or ''}\n"
        f"Cc: {row.get('cc_addrs') or ''}\n"
        f"Date: {row.get('sent_at') or ''}\n"
        f"Subject: {subject}\n"
    )
    return (
        "Analyze this email and return ONLY this JSON shape:\n"
        "{\n"
        '  "summary": "one factual sentence",\n'
        '  "topic": "short topic phrase",\n'
        '  "category": "one of: procurement, finance, legal, hr, operations, '
        'security, personal, scheduling, other",\n'
        '  "sensitivity": "one of: normal, gov, secret, personal",\n'
        '  "sentiment": "one of: positive, neutral, negative",\n'
        '  "event": {"date": "YYYY-MM-DD or null", "title": "short or null"},\n'
        '  "entities": [{"name": "...", "type": "person|org|project|topic", '
        '"role": "sender|recipient|mentioned"}]\n'
        "}\n\n"
        "EMAIL:\n" + hdr + "\n" + body
    )


def _coerce(data):
    """Validate/clamp the model JSON into our schema. Never raises."""
    if not isinstance(data, dict):
        return None
    out = {
        "summary": (str(data.get("summary") or "")).strip()[:1000] or None,
        "topic": (str(data.get("topic") or "")).strip()[:200] or None,
        "category": (str(data.get("category") or "")).strip().lower()[:60] or None,
        "sentiment": None,
        "sensitivity": "normal",
        "event_date": None,
        "event_title": None,
        "entities": [],
    }
    sent = (str(data.get("sentiment") or "")).strip().lower()
    out["sentiment"] = sent if sent in _VALID_SENTIMENT else None
    sens = (str(data.get("sensitivity") or "")).strip().lower()
    out["sensitivity"] = sens if sens in _VALID_SENSITIVITY else "normal"

    ev = data.get("event")
    if isinstance(ev, dict):
        d = str(ev.get("date") or "").strip()
        out["event_date"] = d if _DATE_RE.match(d) else None
        out["event_title"] = (str(ev.get("title") or "").strip()[:300]) or None

    ents = data.get("entities")
    if isinstance(ents, list):
        seen = set()
        for e in ents[:40]:
            if not isinstance(e, dict):
                continue
            name = (str(e.get("name") or "").strip())[:200]
            etype = str(e.get("type") or "").strip().lower()
            if not name or etype not in _VALID_ENTITY_TYPES:
                continue
            norm = re.sub(r"\s+", " ", name).strip().lower()
            key = (etype, norm)
            if not norm or key in seen:
                continue
            seen.add(key)
            role = (str(e.get("role") or "").strip().lower())[:40] or None
            out["entities"].append({"name": name, "type": etype, "norm": norm, "role": role})
    return out


def enrich_one(row):
    """Enrich a single mailbox_emails row. Returns True on success, False on failure.
    Marks the email enrich_status='done' (success) or 'error' (dispatch/parse failure)."""
    email_id = row["id"]
    import_id = row["import_id"]
    try:
        _dispatch = dispatch
        if _dispatch is None:
            _ensure_import_paths()
            from tools.department_hq.services.department_dispatcher import dispatch as _dispatch
        result = _dispatch(
            capability=CAPABILITY,
            prompt=_build_prompt(row),
            module_id=MODULE_ID,
            system_prompt=SYSTEM_PROMPT,
            json_mode=True,
            local_only=True,  # HARD no-cloud guard — gov/secret content stays local
        )
    except Exception:
        logger.exception("mailbox enrich dispatch failed email=%s", email_id)
        return None  # transient — leave 'pending', retry next cycle

    if result is None or not getattr(result, "success", False):
        # Model cold/queued or no local agent ready — NOT an error; leave pending to retry.
        return None

    data = result.response
    if isinstance(data, str):
        try:
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", data.strip(), flags=re.MULTILINE))
        except Exception:
            data = None

    fact = _coerce(data)
    if fact is None or not (fact["summary"] or fact["entities"]):
        _set_status(email_id, "error")  # genuine unparseable/empty model output
        return False

    model_used = getattr(result, "model", None) or getattr(result, "model_used", None)

    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO mailbox_email_facts
                    (email_id, summary, topic, category, sensitivity, sentiment,
                     event_date, event_title, model_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email_id) DO UPDATE SET
                    summary=EXCLUDED.summary, topic=EXCLUDED.topic, category=EXCLUDED.category,
                    sensitivity=EXCLUDED.sensitivity, sentiment=EXCLUDED.sentiment,
                    event_date=EXCLUDED.event_date, event_title=EXCLUDED.event_title,
                    model_used=EXCLUDED.model_used
                """,
                (
                    email_id,
                    fact["summary"],
                    fact["topic"],
                    fact["category"],
                    fact["sensitivity"],
                    fact["sentiment"],
                    fact["event_date"],
                    fact["event_title"],
                    model_used,
                ),
            )
            for ent in fact["entities"]:
                cur.execute(
                    """
                    INSERT INTO mailbox_entities (import_id, name, entity_type, normalized_name, mention_count)
                    VALUES (%s, %s, %s, %s, 1)
                    ON CONFLICT (import_id, entity_type, normalized_name) DO UPDATE
                        SET mention_count = mailbox_entities.mention_count + 1
                    RETURNING id
                    """,
                    (import_id, ent["name"], ent["type"], ent["norm"]),
                )
                entity_id = cur.fetchone()["id"]
                cur.execute(
                    """
                    INSERT INTO mailbox_email_entities (email_id, entity_id, role)
                    VALUES (%s, %s, %s) ON CONFLICT (email_id, entity_id) DO NOTHING
                    """,
                    (email_id, entity_id, ent["role"]),
                )
            cur.execute("UPDATE mailbox_emails SET enrich_status='done' WHERE id=%s", (email_id,))
        return True
    except Exception:
        logger.exception("mailbox enrich persist failed email=%s", email_id)
        _set_status(email_id, "error")
        return False


def _set_status(email_id, status):
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("UPDATE mailbox_emails SET enrich_status=%s WHERE id=%s", (status, email_id))
    except Exception:
        logger.exception("could not set enrich_status=%s for email %s", status, email_id)


def _finalize_imports(import_ids):
    """Flip an import to 'done' once it has no pending emails left (and >0 emails)."""
    if not import_ids:
        return
    with get_db_cursor(commit=True) as (_conn, cur):
        for iid in import_ids:
            cur.execute(
                """
                UPDATE mailbox_imports SET status='done'
                WHERE id=%s AND status IN ('extracted', 'enriching')
                  AND NOT EXISTS (
                      SELECT 1 FROM mailbox_emails
                      WHERE import_id=%s AND enrich_status='pending'
                  )
                """,
                (iid, iid),
            )


def run_enrich_cycle(max_emails=20, batch=10):
    """Claim pending emails from extracted/enriching imports and enrich them local-only.
    Returns {'processed', 'failed', 'imports'}. Resumable: re-claims by enrich_status='pending'."""
    processed = failed = 0
    touched = set()
    while processed + failed < max_emails:
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                SELECT e.id, e.import_id, e.from_addr, e.to_addrs, e.cc_addrs,
                       e.sent_at, e.subject, e.body_text
                FROM mailbox_emails e
                JOIN mailbox_imports i ON i.id = e.import_id
                WHERE e.enrich_status='pending'
                  AND i.status IN ('extracted', 'enriching')
                ORDER BY e.import_id, e.id
                LIMIT %s
                """,
                (min(batch, max_emails - (processed + failed)),),
            )
            rows = cur.fetchall() or []
        if not rows:
            break
        # Mark the parent imports 'enriching' so the UI reflects in-progress state.
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE mailbox_imports SET status='enriching' " "WHERE id = ANY(%s) AND status='extracted'",
                (list({r["import_id"] for r in rows}),),
            )
        deferred = False
        for row in rows:
            touched.add(row["import_id"])
            r = enrich_one(row)
            if r is True:
                processed += 1
            elif r is False:
                failed += 1
            else:  # None — model cold/queued; stop the cycle, leave the rest 'pending'
                deferred = True
                break
        if deferred:
            break
    _finalize_imports(touched)
    if processed or failed:
        logger.info("mailbox enrich cycle: processed=%d failed=%d imports=%d", processed, failed, len(touched))
    return {"processed": processed, "failed": failed, "imports": len(touched)}
