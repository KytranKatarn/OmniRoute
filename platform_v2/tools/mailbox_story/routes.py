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


# ---- Chunked upload (DEFAULT path) ----------------------------------------------------------
# A GB-scale .pst sent as ONE request is rejected by the edge proxy (Hostinger openresty in
# front of Beacon caps the body size → instant failure for remote users). So the client splits
# the file into small chunks (~5MB, far under any proxy cap) and appends them here. Resumable:
# each chunk declares its X-Offset and the server only accepts it if it matches the current
# file size (so a retried/duplicate chunk is rejected with 409 + the expected offset).
_CHUNK_MAX = 32 * 1024 * 1024  # reject a single chunk larger than this (client uses ~5MB)


@mailbox_story_bp.route("/api/upload/init", methods=["POST"])
@admin_required
def upload_init():
    """Start a chunked upload — create the import row + empty target file. Returns import_id."""
    raw_name = request.headers.get("X-Filename") or "mailbox.pst"
    filename = secure_filename(raw_name) or "mailbox.pst"
    owner_id = getattr(current_user, "id", None)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """INSERT INTO mailbox_imports (owner_id, filename, stored_path, status)
               VALUES (%s, %s, %s, 'uploading') RETURNING id""",
            (owner_id, filename, "pending"),
        )
        import_id = cur.fetchone()["id"]
    target_dir = _import_dir(import_id)
    os.makedirs(target_dir, exist_ok=True)
    pst_path = os.path.join(target_dir, "source.pst")
    open(pst_path, "wb").close()  # truncate/create empty
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("UPDATE mailbox_imports SET stored_path=%s WHERE id=%s", (pst_path, import_id))
    return _json({"import_id": import_id, "filename": filename, "status": "uploading"})


@mailbox_story_bp.route("/api/upload/chunk/<int:import_id>", methods=["POST"])
@admin_required
def upload_chunk(import_id):
    """Append one chunk at X-Offset (must equal the current file size). Returns bytes received."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT status, stored_path FROM mailbox_imports WHERE id=%s", (import_id,))
        row = cur.fetchone()
    if not row:
        return _json({"error": "not found"}, status=404)
    if row["status"] != "uploading":
        return _json({"error": f"import not accepting chunks (status={row['status']})"}, status=409)
    pst_path = os.path.join(_import_dir(import_id), "source.pst")
    cur_size = os.path.getsize(pst_path) if os.path.exists(pst_path) else 0
    try:
        offset = int(request.headers.get("X-Offset", "0"))
    except (TypeError, ValueError):
        offset = -1
    if offset != cur_size:
        # Out-of-order / duplicate (retry) — tell the client where to resume.
        return _json({"error": "offset mismatch", "expected": cur_size}, status=409)
    data = request.get_data(cache=False)
    if len(data) > _CHUNK_MAX:
        return _json({"error": "chunk too large"}, status=413)
    with open(pst_path, "ab") as fh:
        fh.write(data)
    return _json({"received": cur_size + len(data)})


@mailbox_story_bp.route("/api/upload/complete/<int:import_id>", methods=["POST"])
@admin_required
def upload_complete(import_id):
    """Finalize a chunked upload → kick the extraction job."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT status FROM mailbox_imports WHERE id=%s", (import_id,))
        row = cur.fetchone()
    if not row:
        return _json({"error": "not found"}, status=404)
    if row["status"] != "uploading":
        return _json({"error": f"import not in uploading state (status={row['status']})"}, status=409)
    target_dir = _import_dir(import_id)
    pst_path = os.path.join(target_dir, "source.pst")
    eml_dir = os.path.join(target_dir, "eml")
    size = os.path.getsize(pst_path) if os.path.exists(pst_path) else 0
    if size == 0:
        shutil.rmtree(target_dir, ignore_errors=True)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("DELETE FROM mailbox_imports WHERE id=%s", (import_id,))
        return _json({"error": "no data received"}, status=400)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("UPDATE mailbox_imports SET status='uploaded' WHERE id=%s", (import_id,))
    threading.Thread(target=_run_extract, args=(import_id, pst_path, eml_dir), daemon=True).start()
    logger.info("mailbox import %s: chunked upload complete (%d bytes), extraction started", import_id, size)
    return _json({"import_id": import_id, "bytes": size, "status": "extracting"})


@mailbox_story_bp.route("/api/upload/abort/<int:import_id>", methods=["POST"])
@admin_required
def upload_abort(import_id):
    """Cancel an in-progress chunked upload — wipe the partial file + row."""
    shutil.rmtree(_import_dir(import_id), ignore_errors=True)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("DELETE FROM mailbox_imports WHERE id=%s AND status='uploading'", (import_id,))
    return _json({"aborted": import_id})


@mailbox_story_bp.route("/api/import-chat", methods=["POST"])
@admin_required
def import_chat():
    """Ingest a ChatGPT/Claude export (conversations.json or .zip) already on the hub into
    Mailbox Story — each chat message becomes a mailbox_emails row, then the existing
    enrichment + story workers process it via DHQ (local-only). Body: {path, filter?}.
    Runs in a background thread (parsing many conversations can take a moment)."""
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    title_filter = (body.get("filter") or "").strip() or None
    if not path:
        return _json({"error": "provide {path} to an export conversations.json or .zip on the hub"}, status=400)
    if not os.path.exists(path):
        return _json({"error": f"file not found on hub: {path}"}, status=404)

    def _bg():
        try:
            from services.mailbox_chat_service import ingest_export_file

            res = ingest_export_file(path, owner_id=getattr(current_user, "id", None), title_filter=title_filter)
            logger.info("chat import from %s: %d conversation(s) ingested", path, len(res))
        except Exception:
            logger.exception("chat import failed for %s", path)

    threading.Thread(target=_bg, daemon=True).start()
    return _json({"status": "importing", "path": path, "filter": title_filter})


@mailbox_story_bp.route("/api/capture-share", methods=["POST"])
@admin_required
def capture_share_route():
    """Autonomously capture a PUBLIC AI chat SHARE link (ChatGPT/Claude) via S.C.O.U.T.
    (server-side render through archie_scraper) into Mailbox Story — the transcript lands as
    mailbox_emails rows, then the existing enrichment + story workers process it via DHQ
    (local-only). Body: {url, title?}. NOTE: a share link is a frozen SNAPSHOT; for COMPLETE
    history use 'Import chat export'. Runs in a background thread (render + scroll takes time).
    """
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    title = (body.get("title") or "").strip() or None
    egress = (body.get("egress") or "").strip() or None  # node_name | 'rotate' (cluster egress)
    if not url.startswith(("http://", "https://")):
        return _json({"error": "provide a valid http(s) share URL in {url}"}, status=400)
    owner_id = getattr(current_user, "id", None)  # capture in request context, not in the thread

    def _bg():
        try:
            from services.mailbox_scout_capture import capture_share

            res = capture_share(url, owner_id=owner_id, title=title, egress=egress)
            if res.get("error"):
                logger.warning("share capture %s: %s", url, res["error"])
            else:
                logger.info("share capture %s -> import %s (%d msgs)", url, res.get("import_id"), res.get("messages"))
        except Exception:
            logger.exception("share capture failed for %s", url)

    threading.Thread(target=_bg, daemon=True).start()
    return _json({"status": "capturing", "url": url})


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
    folder = request.args.get("folder")  # None = all folders; '' = root; else a specific folder
    folder_sql = " AND e.folder = %s" if folder is not None else ""
    folder_args = (folder,) if folder is not None else ()
    filt_args = (*sens_args, *folder_args)
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS n FROM mailbox_emails e "
            "LEFT JOIN mailbox_email_facts f ON f.email_id = e.id "
            "WHERE e.import_id=%s" + sens_sql + folder_sql,
            (import_id, *filt_args),
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
            + folder_sql
            + """ ORDER BY e.sent_at DESC NULLS LAST, e.id DESC
               LIMIT %s OFFSET %s""",
            (import_id, *filt_args, limit, offset),
        )
        rows = cur.fetchall()
    return _json({"emails": rows, "total": total, "limit": limit, "offset": offset})


@mailbox_story_bp.route("/api/imports/<int:import_id>/folders")
@admin_required
def list_folders(import_id):
    """Folders present in the import with email counts (for the folder sidebar)."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT COALESCE(folder, '') AS folder, COUNT(*) AS n
               FROM mailbox_emails WHERE import_id=%s
               GROUP BY COALESCE(folder, '') ORDER BY n DESC, folder ASC""",
            (import_id,),
        )
        rows = cur.fetchall()
    return _json({"folders": rows})


@mailbox_story_bp.route("/api/imports/<int:import_id>/emails/<int:email_id>")
@admin_required
def get_email(import_id, email_id):
    """Full single email for the read pane — headers + body + enrichment facts."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT e.id, e.import_id, e.folder, e.message_id, e.in_reply_to,
                      e.from_addr, e.to_addrs, e.cc_addrs, e.sent_at, e.subject,
                      e.body_text, e.has_attachments, e.enrich_status,
                      f.summary, f.topic, f.category, f.sensitivity, f.sentiment,
                      f.event_date, f.event_title
               FROM mailbox_emails e
               LEFT JOIN mailbox_email_facts f ON f.email_id = e.id
               WHERE e.id=%s AND e.import_id=%s""",
            (email_id, import_id),
        )
        row = cur.fetchone()
    if not row:
        return _json({"error": "not found"}, status=404)
    return _json({"email": row})


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
