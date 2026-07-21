"""
Backup Restore Service — owned by W.A.R.D.E.N.
Two-stage safe restore: sandbox first (P.R.O.B.E. QA), then production promote.
All restore operations dispatched through Department HQ delegate_task queue.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import threading
from typing import Any

from psycopg2.extras import Json

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Sandbox restore targets the disposable staging Postgres (NEVER prod). Both
# archie_platform and archie_scheduler carry the docker socket, so the
# delegate_task_worker can docker-exec these wherever it runs. (#4050)
STAGING_DB_CONTAINER = "archie_staging_db"
STAGING_APP_CONTAINER = "archie_staging"
SANDBOX_URL = "http://192.168.1.200:3003"
HOST_BACKUP_ROOT = "/mnt/data2/backups"  # mounted read-only inside archie_staging_db

# Tables a restore MUST repopulate for the result to count as usable. Deliberately spans
# the different owners — knowledge, agents, projects/tasks, repair, telemetry, auth — so a
# per-table COPY failure cannot hide behind one healthy table. `unified_tasks` is here
# because it is precisely what a 2026-07-20 restore silently lost (0 rows vs 4,273) while
# reporting qa_passed, when knowledge_base alone was the check.
# Names are interpolated into SQL: keep this list a hard-coded literal, never user input.
_VERIFY_TABLES = (
    "knowledge_base",
    "agents",
    "unified_projects",
    "unified_tasks",
    "improvement_proposals",
    "users",
    "backup_log",
    "task_execution_log",
)


def get_restore_status(backup_id: int) -> dict[str, Any]:
    """Return current restore session status for a backup, or no_session if none exists."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id FROM backup_log WHERE id = %s", (backup_id,))
        if not cur.fetchone():
            return {"success": False, "error": "backup_not_found"}
        cur.execute(
            "SELECT * FROM module_restore_sessions WHERE backup_id = %s ORDER BY created_at DESC LIMIT 1",
            (backup_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": True, "session": None, "status": "no_session"}
        session = dict(row)
        if session.get("created_at"):
            session["created_at"] = session["created_at"].isoformat()
        if session.get("updated_at"):
            session["updated_at"] = session["updated_at"].isoformat()
        return {"success": True, "session": session, "status": session["status"]}


def initiate_sandbox_restore(backup_id: int, triggered_by: str = "user") -> dict[str, Any]:
    """
    Start a sandbox restore session for the given backup_id.
    Creates a module_restore_sessions row and delegates to W.A.R.D.E.N. via dispatch.
    Returns immediately with session_id (async operation).
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id, file_path, backup_type FROM backup_log WHERE id = %s", (backup_id,))
        backup = cur.fetchone()
        if not backup:
            return {"success": False, "error": "backup_not_found"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO module_restore_sessions (backup_id, status, triggered_by)
               VALUES (%s, 'pending', %s) RETURNING id""",
            (backup_id, triggered_by),
        )
        session_id = cur.fetchone()["id"]

    # Delegate to W.A.R.D.E.N. via Department HQ
    try:
        from services.delegation_service import delegate_task

        delegate_task(
            capability="restore_sandbox",
            reason=f"Sandbox restore for backup #{backup_id} (session #{session_id})",
            args={"backup_id": backup_id, "session_id": session_id},
            delegation_source="automation",
        )
    except Exception as e:
        logger.warning("Could not delegate restore_sandbox task: %s", e)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE module_restore_sessions SET status='failed', updated_at=NOW() WHERE id=%s",
                (session_id,),
            )
        return {"success": False, "error": f"delegation_failed: {e}"}

    return {"success": True, "session_id": session_id, "status": "pending"}


def promote_to_production(session_id: int, triggered_by: str = "user") -> dict[str, Any]:
    """
    Promote a QA-verified sandbox restore to production.
    Only allowed when session status = 'qa_passed'.
    Delegates to W.A.R.D.E.N. via Department HQ.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, backup_id, status FROM module_restore_sessions WHERE id = %s",
            (session_id,),
        )
        session = cur.fetchone()
        if not session:
            return {"success": False, "error": "session_not_found"}
        if session["status"] != "qa_passed":
            return {
                "success": False,
                "error": f"cannot_promote: session status is '{session['status']}', must be 'qa_passed'",
            }

    try:
        from services.delegation_service import delegate_task

        delegate_task(
            capability="restore_production",
            reason=f"Promote session #{session_id} (backup #{session['backup_id']}) to production",
            args={"session_id": session_id, "backup_id": session["backup_id"]},
            delegation_source="automation",
        )
    except Exception as e:
        return {"success": False, "error": f"delegation_failed: {e}"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE module_restore_sessions SET status='promoting', updated_at=NOW() WHERE id=%s",
            (session_id,),
        )
    return {"success": True, "session_id": session_id, "status": "promoting"}


# ---------------------------------------------------------------------------
# Real restore workers (#4050) — invoked via the delegation known-tool path.
# restore_sandbox actually restores into the disposable staging DB; promote
# stays host-gated (ADR-001 — the platform can't DROP+restore its own live DB).
# ---------------------------------------------------------------------------

_SESSION_COLS = {"status", "sandbox_schema", "sandbox_url", "qa_run_id", "qa_passed", "qa_total", "qa_failures"}


def _set_session(session_id: int, **fields: Any) -> None:
    """Update whitelisted module_restore_sessions columns + updated_at."""
    sets, vals = [], []
    for key, value in fields.items():
        if key not in _SESSION_COLS:
            continue
        sets.append(f"{key} = %s")
        vals.append(Json(value) if key == "qa_failures" else value)
    if not sets:
        return
    vals.append(session_id)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE module_restore_sessions SET {', '.join(sets)}, updated_at=NOW() WHERE id = %s",
            vals,
        )


def _resolve_backup_dir(backup_id: int) -> str | None:
    """Resolve a backup_log id to its host run dir under HOST_BACKUP_ROOT.

    backup_log has one row per (component, tier); reconstruct the primary
    /mnt/data2/backups/<name> path (mounted inside archie_staging_db) from the basename.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT file_path FROM backup_log WHERE id = %s", (backup_id,))
        row = cur.fetchone()
    if not row or not row.get("file_path"):
        return None
    name = os.path.basename(str(row["file_path"]).rstrip("/"))
    return f"{HOST_BACKUP_ROOT}/{name}" if name else None


def _docker(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


# psql ERRORs that must NOT fail an otherwise-good restore. If the gate cries wolf it gets
# ignored, which is exactly how this class of defect survives.
#   * `unrecognized configuration parameter` — the image ships pg_dump 17 while the server is
#     16, so every plain dump carries SETs (transaction_timeout) that a 16 server rejects.
#   * `already exists` — restoring into a sandbox that was not dropped first.
# Deliberately a SMALL allowlist: syntax errors, `invalid input syntax for type`, and
# constraint failures are REAL and must still fail the restore (they are what #5080 was).
_BENIGN_RESTORE_ERROR = re.compile(r"unrecognized configuration parameter|already exists", re.I)


def count_real_restore_errors(stderr: str) -> int:
    """Count psql ERROR lines that indicate an actually-broken restore."""
    return len([ln for ln in re.findall(r"^ERROR:.*$", stderr or "", re.M) if not _BENIGN_RESTORE_ERROR.search(ln)])


def _run_sandbox_restore_thread(backup_id: int, session_id: int, run_dir: str) -> None:
    """Restore the archie dump into the disposable staging DB; drive the session state machine."""
    import glob

    name = os.path.basename(run_dir.rstrip("/"))
    # TWO backup formats exist and this path used to accept only one (#5036):
    #   nightly host cron -> <backup>/database/archie_<ts>.dump  (pg_dump -Fc  -> pg_restore)
    #   UI / programmatic -> <backup>/database.sql.gz            (plain SQL gz -> psql)
    # It globbed ONLY the .dump and, on a miss, reported "(primary copy pruned?)". So every
    # backup a user created from the Backups tab failed the "🧪 Test in Sandbox" button with an
    # error naming the WRONG CAUSE — nothing had been pruned, the format simply was not handled.
    # That is very likely why module_restore_sessions sat empty: the button could only ever work
    # on a nightly-cron backup. Accept both formats, and when neither is present say so plainly.
    # The worker sees backups at /backups (BACKUP_DIR mount); the staging DB sees them at run_dir.
    worker_dumps = sorted(glob.glob(f"/backups/{name}/database/archie_*.dump"))
    if worker_dumps:
        dump_kind = "custom"
        staging_dump = f"{run_dir}/database/{os.path.basename(worker_dumps[-1])}"
    elif os.path.exists(f"/backups/{name}/database.sql.gz"):
        dump_kind = "sqlgz"
        staging_dump = f"{run_dir}/database.sql.gz"
    else:
        _set_session(
            session_id,
            status="failed",
            qa_failures=[
                {
                    "error": (
                        f"backup '{name}' contains no restorable database artifact. Expected "
                        f"either database/archie_<ts>.dump (nightly cron format) or "
                        f"database.sql.gz (UI/programmatic format); neither is present. "
                        f"This is a missing/incomplete artifact, not a pruning problem."
                    )
                }
            ],
        )
        return

    try:
        _set_session(session_id, status="qa_running")
        # Stop the staging app so nothing holds the staging 'archie' DB open during DROP.
        _docker(["stop", STAGING_APP_CONTAINER], timeout=60)
        try:
            _docker(
                [
                    "exec",
                    STAGING_DB_CONTAINER,
                    "psql",
                    "-U",
                    "archie",
                    "-d",
                    "template1",
                    "-c",
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname='archie' AND pid<>pg_backend_pid();",
                ],
                timeout=60,
            )
            drop = _docker(
                [
                    "exec",
                    STAGING_DB_CONTAINER,
                    "psql",
                    "-U",
                    "archie",
                    "-d",
                    "template1",
                    "-c",
                    "DROP DATABASE IF EXISTS archie;",
                ],
                timeout=120,
            )
            if drop.returncode != 0:
                _set_session(
                    session_id,
                    status="failed",
                    qa_failures=[{"error": f"DROP DATABASE failed: {(drop.stderr or '').strip()[:300]}"}],
                )
                return
            _docker(
                [
                    "exec",
                    STAGING_DB_CONTAINER,
                    "psql",
                    "-U",
                    "archie",
                    "-d",
                    "template1",
                    "-c",
                    "CREATE DATABASE archie;",
                ],
                timeout=120,
            )
            # pg_restore exits nonzero on benign warnings (roles/HNSW) — judge by the verify
            # query, not the exit code. That instinct is right, but the STDERR still has to be
            # read: on a COPY failure pg_restore leaves that table EMPTY, prints
            # "errors ignored on restore: N", and carries on. A 2026-07-20 restore lost the
            # whole of public.unified_tasks (0 rows vs 4,273) that way and still reported
            # qa_passed, because the only check was knowledge_base > 0 — one table out of 720.
            if dump_kind == "custom":
                restore_proc = _docker(
                    [
                        "exec",
                        STAGING_DB_CONTAINER,
                        "pg_restore",
                        "-U",
                        "archie",
                        "-d",
                        "archie",
                        "--no-owner",
                        "--no-privileges",
                        staging_dump,
                    ],
                    timeout=1800,
                )
            else:
                # Plain SQL stream. shlex.quote because run-dir names embed '#', ':' and '[]'
                # taken from proposal titles (and, pre-#2379, '/').
                restore_proc = _docker(
                    [
                        "exec",
                        STAGING_DB_CONTAINER,
                        "sh",
                        "-c",
                        f"gunzip -c {shlex.quote(staging_dump)} | psql -U archie -d archie -v ON_ERROR_STOP=0",
                    ],
                    timeout=1800,
                )
            restore_err = (restore_proc.stderr or "") + (restore_proc.stdout or "")
            ignored = 0
            if dump_kind == "custom":
                m = re.search(r"errors ignored on restore:\s*(\d+)", restore_err)
                if m:
                    ignored = int(m.group(1))
            else:
                # psql prints no summary line. With ON_ERROR_STOP=0 it keeps going and exits 0,
                # so — exactly like pg_restore — it can leave a table EMPTY and still look clean.
                # Count the ERROR: lines so the same "errors OR empty table => failure" gate below
                # applies to both formats.
                #
                # Two families of ERROR are expected and must NOT fail an otherwise-good restore,
                # or the gate cries wolf and gets ignored — which is how these defects survive:
                #   * `unrecognized configuration parameter` — the image ships pg_dump 17 while
                #     the server is 16, so the dump carries SETs (transaction_timeout) that a 16
                #     server rejects. Emitted on EVERY dump; nothing is lost.
                #   * `already exists` — restoring into a sandbox that was not dropped first.
                # Anything else (syntax errors, invalid input for type, constraint failures) is a
                # real defect and still counts. This is deliberately a SMALL allowlist.
                ignored = count_real_restore_errors(restore_err)
            # Keep the actual COPY/constraint lines — "N errors" alone does not say WHICH table
            # was lost, and that is the only detail anyone needs at 3am.
            err_lines = [ln for ln in restore_err.splitlines() if "error" in ln.lower()][:20]

            # Verify a SET of tables, not one. A restore that drops a table is exactly the
            # failure this rehearsal exists to catch, so an empty critical table is a FAILURE
            # even when pg_restore reported nothing.
            verify = _docker(
                [
                    "exec",
                    STAGING_DB_CONTAINER,
                    "psql",
                    "-U",
                    "archie",
                    "-d",
                    "archie",
                    "-tAc",
                    "SELECT string_agg(t || '=' || c, ',') FROM ("
                    + " UNION ALL ".join(f"SELECT '{t}' AS t, count(*)::text AS c FROM {t}" for t in _VERIFY_TABLES)
                    + ") v;",
                ],
                timeout=120,
            )
            counts_raw = (verify.stdout or "").strip()
            counts = dict(p.split("=", 1) for p in counts_raw.split(",") if "=" in p)
            empty = sorted(t for t, c in counts.items() if not c.isdigit() or int(c) <= 0)
            rows = counts.get("knowledge_base", "")

            if empty or ignored:
                _set_session(
                    session_id,
                    status="failed",
                    qa_failures=[
                        {
                            "empty_tables": empty,
                            "pg_restore_errors_ignored": ignored,
                            "error_lines": err_lines,
                            "counts": counts_raw[:500],
                        }
                    ],
                )
                logger.error(
                    "sandbox restore INCOMPLETE — session=%s empty=%s pg_restore_errors=%s",
                    session_id,
                    empty,
                    ignored,
                )
                return
        finally:
            # Always bring the staging app back (reconnects to the fresh DB).
            _docker(["start", STAGING_APP_CONTAINER], timeout=90)

        if not rows.isdigit() or int(rows) <= 0:
            _set_session(
                session_id,
                status="failed",
                qa_failures=[{"error": f"verify failed — knowledge_base count={rows!r}"}],
            )
            return

        _set_session(
            session_id,
            status="qa_passed",
            qa_passed=1,
            qa_total=1,
            sandbox_url=SANDBOX_URL,
            sandbox_schema=f"archie@staging ({rows} rows)",
        )
        logger.info("sandbox restore OK — session=%s backup=%s rows=%s", session_id, backup_id, rows)
    except Exception as exc:  # noqa: BLE001 — record any failure on the session row
        logger.exception("sandbox restore failed — session=%s", session_id)
        _set_session(session_id, status="failed", qa_failures=[{"error": str(exc)[:500]}])


def run_sandbox_restore(backup_id: int | None = None, session_id: int | None = None, **_: Any) -> dict[str, Any]:
    """Known-tool handler for capability 'restore_sandbox' — restore into the disposable staging DB.

    Spawns a daemon thread (restore is multi-minute) and returns immediately; the UI polls
    /api/restore/status. NEVER touches prod. (#4050)
    """
    if not backup_id or not session_id:
        return {"success": False, "summary": "restore_sandbox: backup_id and session_id required"}
    run_dir = _resolve_backup_dir(int(backup_id))
    if not run_dir:
        _set_session(int(session_id), status="failed", qa_failures=[{"error": f"backup_log #{backup_id} not found"}])
        return {"success": False, "summary": f"restore_sandbox: backup #{backup_id} not found"}
    threading.Thread(
        target=_run_sandbox_restore_thread,
        args=(int(backup_id), int(session_id), run_dir),
        daemon=True,
        name=f"sandbox-restore-{session_id}",
    ).start()
    return {
        "success": True,
        "summary": f"sandbox restore started — session {session_id}, backup {backup_id} ({run_dir})",
    }


def run_production_restore(session_id: int | None = None, backup_id: int | None = None, **_: Any) -> dict[str, Any]:
    """Known-tool handler for capability 'restore_production' — PROMOTE is host-gated (ADR-001).

    The platform cannot DROP+restore its own live DB in-process. Instead of silently doing
    nothing, surface the exact gated host command and free the session from 'promoting'.
    (#4050 / runbook KB #272184)
    """
    if not session_id or not backup_id:
        return {"success": False, "summary": "restore_production: session_id and backup_id required"}
    run_dir = _resolve_backup_dir(int(backup_id))
    if not run_dir:
        return {"success": False, "summary": f"restore_production: backup #{backup_id} not found"}
    from tools.backup_manager._shared import _host_restore_command

    cmd = _host_restore_command(run_dir, db="all", force=True)
    # Don't leave the row stuck in 'promoting' — promote is a deliberate manual host action.
    _set_session(
        int(session_id),
        status="qa_passed",
        qa_failures=[{"info": "promote is host-gated (ADR-001)", "host_command": cmd, "kb": "#272184"}],
    )
    return {
        "success": True,
        "summary": f"Promote is host-gated (ADR-001). Run on the hub: DR_CONFIRM=RESTORE-NOW {cmd}",
        "result": {"requires_host_restore": True, "host_command": cmd, "kb": "#272184"},
    }
