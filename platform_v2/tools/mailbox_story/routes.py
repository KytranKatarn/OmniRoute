"""Mailbox Story Extractor routes (Phase 1b).

Surface:
    GET  /tools/mailbox-story                         -> UI
    GET  /tools/mailbox-story/api/status              -> health
    POST /tools/mailbox-story/api/upload              -> stream a .pst to local disk + kick extract
    GET  /tools/mailbox-story/api/imports             -> list imports (status + counts)
    GET  /tools/mailbox-story/api/imports/<id>        -> one import (for live status poll)
    GET  /tools/mailbox-story/api/imports/<id>/emails -> paginated extracted-email table
    POST /tools/mailbox-story/api/imports/<id>/delete -> wipe file + rows (privacy retention)

PRIVACY: the .pst and extracted .eml live ONLY on local hub disk (/mnt/data2/mailbox_story/<id>/).
readpst is a local binary; nothing in this path touches the network. Enrichment (Phase 2) runs on
local-only fleet LLMs. Admin-gated (defense in depth: registry minimum_role=ADMIN + @admin_required).
"""

import json
import logging
import os
import shutil
import threading

from flask import Response, render_template, request
from flask_login import current_user
from werkzeug.utils import secure_filename

from database import get_db_cursor
from services.mailbox_extract_service import extract_pst

from . import admin_required, mailbox_story_bp

logger = logging.getLogger(__name__)

STORAGE_ROOT = "/mnt/data2/mailbox_story"
MAX_PST_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB — PSTs are large; this route only
_UPLOAD_CHUNK = 4 * 1024 * 1024  # 4 MB streamed writes


def _json(payload, status=200):
    """Serialize with default=str so psycopg2 datetimes don't break jsonify (KB #269068)."""
    return Response(json.dumps(payload, default=str), status=status, mimetype="application/json")


def _import_dir(import_id):
    return os.path.join(STORAGE_ROOT, str(import_id))


def _run_extract(import_id, pst_path, eml_dir):
    """Background extract. Always lands the import in a terminal status (extracted/error)."""
    try:
        extract_pst(import_id, pst_path, eml_dir)
    except Exception as exc:  # readpst timeout, walk error, etc. — never leave it stuck 'extracting'
        logger.exception("mailbox extract failed for import %s", import_id)
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "UPDATE mailbox_imports SET status='error', error=%s WHERE id=%s",
                    (str(exc)[:1000], import_id),
                )
        except Exception:
            logger.exception("could not mark import %s as error", import_id)


@mailbox_story_bp.route("/")
@admin_required
def index():
    return render_template("tools/mailbox_story.html")


@mailbox_story_bp.route("/api/status")
def status():
    """Health check (the module registry pings this)."""
    return _json({"status": "ok", "module": "mailbox_story", "phase": "1b"})


@mailbox_story_bp.route("/api/upload", methods=["POST"])
@admin_required
def upload():
    """Raw-stream a .pst to local disk, then kick the extraction job in the background.

    Client posts the raw .pst bytes as the request body with an X-Filename header (NOT multipart),
    so we bypass the global 16 MB form cap and stream GB-scale files straight to /mnt/data2.
    """
    # Lift the per-request body cap for this route only (global stays 16 MB everywhere else).
    request.max_content_length = MAX_PST_BYTES

    raw_name = request.headers.get("X-Filename") or "mailbox.pst"
    filename = secure_filename(raw_name) or "mailbox.pst"
    owner_id = getattr(current_user, "id", None)

    # Create the row first so the stored path can key on the import id.
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """INSERT INTO mailbox_imports (owner_id, filename, stored_path, status)
               VALUES (%s, %s, %s, 'uploaded') RETURNING id""",
            (owner_id, filename, "pending"),
        )
        import_id = cur.fetchone()["id"]

    target_dir = _import_dir(import_id)
    os.makedirs(target_dir, exist_ok=True)
    pst_path = os.path.join(target_dir, "source.pst")
    eml_dir = os.path.join(target_dir, "eml")

    written = 0
    try:
        with open(pst_path, "wb") as fh:
            while True:
                chunk = request.stream.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
    except Exception as exc:
        logger.exception("upload write failed for import %s", import_id)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE mailbox_imports SET status='error', error=%s WHERE id=%s",
                (f"upload failed: {exc}"[:1000], import_id),
            )
        return _json({"error": "upload failed"}, status=500)

    if written == 0:
        # Empty body — clean up the placeholder row + dir.
        shutil.rmtree(target_dir, ignore_errors=True)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("DELETE FROM mailbox_imports WHERE id=%s", (import_id,))
        return _json({"error": "no file received"}, status=400)

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("UPDATE mailbox_imports SET stored_path=%s WHERE id=%s", (pst_path, import_id))

    threading.Thread(target=_run_extract, args=(import_id, pst_path, eml_dir), daemon=True).start()
    logger.info("mailbox import %s: received %d bytes (%s), extraction started", import_id, written, filename)
    return _json({"import_id": import_id, "filename": filename, "bytes": written, "status": "extracting"})


@mailbox_story_bp.route("/api/imports")
@admin_required
def list_imports():
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id, filename, status, email_count, error, created_at
               FROM mailbox_imports ORDER BY created_at DESC LIMIT 200"""
        )
        rows = cur.fetchall()
    return _json({"imports": rows})


@mailbox_story_bp.route("/api/imports/<int:import_id>")
@admin_required
def get_import(import_id):
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id, filename, status, email_count, error, created_at, purge_at
               FROM mailbox_imports WHERE id=%s""",
            (import_id,),
        )
        row = cur.fetchone()
        if not row:
            return _json({"error": "not found"}, status=404)
        cur.execute(
            """SELECT enrich_status, COUNT(*) AS n FROM mailbox_emails
               WHERE import_id=%s GROUP BY enrich_status""",
            (import_id,),
        )
        counts = {r["enrich_status"]: r["n"] for r in cur.fetchall()}
    row = dict(row)
    row["enrich"] = {
        "done": counts.get("done", 0),
        "pending": counts.get("pending", 0),
        "error": counts.get("error", 0),
    }
    return _json({"import": row})


@mailbox_story_bp.route("/api/imports/<int:import_id>/emails")
@admin_required
def list_emails(import_id):
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 50, 0
    sens = (request.args.get("sensitivity") or "").strip().lower()
    sens_sql = " AND f.sensitivity = %s" if sens in ("normal", "gov", "secret", "personal") else ""
    sens_args = (sens,) if sens_sql else ()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS n FROM mailbox_emails e "
            "LEFT JOIN mailbox_email_facts f ON f.email_id = e.id "
            "WHERE e.import_id=%s" + sens_sql,
            (import_id, *sens_args),
        )
        total = cur.fetchone()["n"]
        cur.execute(
            """SELECT e.id, e.folder, e.from_addr, e.to_addrs, e.sent_at, e.subject,
                      e.has_attachments, e.enrich_status,
                      f.summary, f.topic, f.category, f.sensitivity
               FROM mailbox_emails e
               LEFT JOIN mailbox_email_facts f ON f.email_id = e.id
               WHERE e.import_id=%s"""
            + sens_sql
            + """ ORDER BY e.sent_at DESC NULLS LAST, e.id DESC
               LIMIT %s OFFSET %s""",
            (import_id, *sens_args, limit, offset),
        )
        rows = cur.fetchall()
    return _json({"emails": rows, "total": total, "limit": limit, "offset": offset})


@mailbox_story_bp.route("/api/imports/<int:import_id>/entities")
@admin_required
def list_entities(import_id):
    """Top entities for an import (people/orgs/projects/topics), most-mentioned first."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id, name, entity_type, mention_count
               FROM mailbox_entities WHERE import_id=%s
               ORDER BY mention_count DESC, name ASC LIMIT 200""",
            (import_id,),
        )
        rows = cur.fetchall()
    return _json({"entities": rows})


@mailbox_story_bp.route("/api/imports/<int:import_id>/enrich", methods=["POST"])
@admin_required
def kick_enrich(import_id):
    """Manually kick a local-only enrichment pass now (the scheduled worker also drains it).
    Runs in a background thread so the request returns immediately."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT status FROM mailbox_imports WHERE id=%s", (import_id,))
        row = cur.fetchone()
    if not row:
        return _json({"error": "not found"}, status=404)
    if row["status"] not in ("extracted", "enriching", "done"):
        return _json({"error": f"import not ready to enrich (status={row['status']})"}, status=409)

    def _bg():
        try:
            from services.mailbox_enrich_service import run_enrich_cycle

            # Drain this import's backlog in a few capped passes (worker also runs every 3 min).
            for _ in range(5):
                res = run_enrich_cycle(max_emails=20, batch=10)
                if not res.get("processed") and not res.get("failed"):
                    break
        except Exception:
            logger.exception("manual enrich kick failed for import %s", import_id)

    threading.Thread(target=_bg, daemon=True).start()
    return _json({"status": "enriching", "import_id": import_id})


@mailbox_story_bp.route("/api/imports/<int:import_id>/timeline")
@admin_required
def list_timeline(import_id):
    """Chronological timeline events (optional ?sensitivity= filter)."""
    sens = (request.args.get("sensitivity") or "").strip().lower()
    sens_sql = " AND sensitivity = %s" if sens in ("normal", "gov", "secret", "personal") else ""
    sens_args = (sens,) if sens_sql else ()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT id, event_date, title, description, sensitivity, email_id "
            "FROM mailbox_timeline_events WHERE import_id=%s"
            + sens_sql
            + " ORDER BY event_date NULLS LAST, id LIMIT 500",
            (import_id, *sens_args),
        )
        rows = cur.fetchall()
    return _json({"timeline": rows})


@mailbox_story_bp.route("/api/imports/<int:import_id>/stories")
@admin_required
def list_stories(import_id):
    """Per-cluster story narratives, biggest cluster first."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT id, cluster_key, title, narrative, span_start, span_end, email_count
               FROM mailbox_stories WHERE import_id=%s
               ORDER BY email_count DESC, id LIMIT 100""",
            (import_id,),
        )
        rows = cur.fetchall()
    return _json({"stories": rows})


@mailbox_story_bp.route("/api/imports/<int:import_id>/build-story", methods=["POST"])
@admin_required
def kick_build_story(import_id):
    """Manually (re)build the timeline + story narratives now (local-only). Background thread."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT status FROM mailbox_imports WHERE id=%s", (import_id,))
        row = cur.fetchone()
    if not row:
        return _json({"error": "not found"}, status=404)

    def _bg():
        try:
            from services.mailbox_story_service import build_import_story

            build_import_story(import_id)
        except Exception:
            logger.exception("manual story build failed for import %s", import_id)

    threading.Thread(target=_bg, daemon=True).start()
    return _json({"status": "building", "import_id": import_id})


@mailbox_story_bp.route("/api/imports/<int:import_id>/delete", methods=["POST"])
@admin_required
def delete_import(import_id):
    """Privacy retention: wipe the local files AND every DB row for this import."""
    shutil.rmtree(_import_dir(import_id), ignore_errors=True)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM mailbox_imports WHERE id=%s", (import_id,))  # CASCADE -> emails, grants
        deleted = cur.rowcount
    if not deleted:
        return _json({"error": "not found"}, status=404)
    logger.info("mailbox import %s deleted (files + rows)", import_id)
    return _json({"deleted": import_id})
