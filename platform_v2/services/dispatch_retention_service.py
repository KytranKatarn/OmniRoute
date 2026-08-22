"""Dispatch retention/prune — #4542.

Deletes OLD, TERMINAL rows from the two dispatch bookkeeping tables that grow
unbounded:

* ``bridge_jobs``            — job queue / durable-execution ledger
* ``dispatch_pending_queue`` — model-affinity cold-load queue (dpq)

As of 2026-06-28 ``bridge_jobs`` held 558k rows (89% terminal & >7d old) and dpq
held 104k. Both are read by live UIs (DISPATCH subtab, user dashboard) and that
unbounded history makes the history endpoints slow (~4s). This is pure DB
maintenance — NO LLM, NO dispatch — same family as ``reap_stale_pending_approvals``
and ``job_recovery_reaper``.

A table is pruned one of two ways (per its ``_TABLES`` spec):
  * STATUS-ALLOWLIST (bridge_jobs, dpq) — status-machine queues with in-flight
    rows; only rows in an explicit terminal set are deleted.
  * AGE-ONLY (``statuses=None``; e.g. ``autonomy_loop_log``) — append-only logs
    where every row is a finished historical record (no in-flight / pending /
    unprocessed concept), so retention is purely by age. ONLY use age-only for a
    genuinely append-only table — verify no reader treats a row as actionable.

SAFETY INVARIANTS (do not weaken):
  * ALLOWLIST, not denylist (status-machine tables). We only ever delete rows
    whose status is in an explicit terminal set. ``running`` / ``pending`` /
    ``pending_approval`` / ``interrupted`` (bridge_jobs) and ``queued`` /
    ``running`` / ``claimed`` (dpq) — and ANY new/unknown status — are NEVER
    touched.
  * Retention windows EXCEED the largest read window. The widest *bounded*
    reader of bridge_jobs is the 30-day user dashboard
    (``tools/.../user_profile/routes.py``); default keep is 45d. dpq's live
    readers only ever filter non-terminal rows; default keep is 30d.
  * FKs into bridge_jobs (``task_execution_log.job_id``,
    ``media_generation_queue.bridge_job_id``) are BOTH ``ON DELETE SET NULL`` —
    pruning never cascades or blocks.
  * Batched deletes (commit per batch) so the 558k table never sits under one
    long lock.
  * Fail-SAFE everywhere: any error logs and returns without partial damage; a
    config error falls back to safe defaults; ``enabled=false`` is a clean no-op.

Tunables (``platform_settings``, no deploy needed — see ``DEFAULTS``):
  retention:enabled                 -> bool   (default true)
  retention:bridge_jobs:keep_days   -> int    (default 45; <=0 skips that table)
  retention:dpq:keep_days           -> int    (default 30; <=0 skips that table)
  retention:batch_size              -> int    (default 5000)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# --- Terminal status allowlists (verified against live data 2026-06-28) -------
# bridge_jobs live statuses: completed, failed, cancelled, running.
# We additionally allow the other documented terminal states defensively.
TERMINAL_BRIDGE = (
    "completed",
    "failed",
    "cancelled",
    "error",
    "expired",
    "timeout",
    "rejected",
)
# dispatch_pending_queue live statuses: done, failed, expired.
TERMINAL_DPQ = (
    "done",
    "failed",
    "expired",
    "cancelled",
    "completed",
    "error",
)

# --- Defaults (overridable via platform_settings) -----------------------------
DEFAULTS = {
    "enabled": True,
    # 30d = the widest BOUNDED reader (the user dashboard's `created_at > NOW()-30d`,
    # strict `>`). Removing rows it already excludes is invisible to it, while
    # actually shrinking the table (the spike of recent volume is the bulk). #4542.
    "bridge_jobs_keep_days": 30,
    "dpq_keep_days": 30,
    # autonomy_loop_log is an append-only job-cycle log; widest reader window is
    # 7d (dispatch_routes 7-day history), so 14d = 2x buffer + prunes the bulk. #4542.
    "autonomy_loop_log_keep_days": 14,
    # governance_audit_log = HMAC-signed C.R.E.E.D. compliance audit trail. Owner
    # chose a GENEROUS 365d keep (preserve a full year of the signed trail; widest
    # reader is 30d). Prunes ~0 today (table <140d old) — bounds future growth. #4542.
    "governance_audit_log_keep_days": 365,
    # model_placement_log (#5273/#5917). 30d because the value of this table is
    # TREND — "how often did we CPU-demote this month" — not forensics on a single
    # load. Deliberately longer than autonomy_loop_log's 14d: a placement question
    # is usually asked AFTER a bad week, and #5903 took days to even formulate.
    # ⚠️ This key is MANDATORY once model_placement_log is in _TABLES: run_retention
    # indexes cfg[spec["keep_key"]] DIRECTLY, and the loop sits inside ONE outer
    # try/except — so a missing default is a KeyError that aborts retention for
    # EVERY table, not just this one. test_dispatch_retention pins the pairing.
    "model_placement_log_keep_days": 30,
    "batch_size": 5000,
}

# platform_settings key -> DEFAULTS key
_PS_KEYS = {
    "retention:enabled": "enabled",
    "retention:bridge_jobs:keep_days": "bridge_jobs_keep_days",
    "retention:dpq:keep_days": "dpq_keep_days",
    "retention:autonomy_loop_log:keep_days": "autonomy_loop_log_keep_days",
    "retention:governance_audit_log:keep_days": "governance_audit_log_keep_days",
    "retention:model_placement_log:keep_days": "model_placement_log_keep_days",
    "retention:batch_size": "batch_size",
}

# Table spec whitelist — names are MODULE CONSTANTS, never user input, so the
# f-string interpolation below is injection-safe.
_TABLES = {
    "bridge_jobs": {
        "age_col": "created_at",
        "statuses": TERMINAL_BRIDGE,
        "keep_key": "bridge_jobs_keep_days",
    },
    "dispatch_pending_queue": {
        "age_col": "queued_at",
        "statuses": TERMINAL_DPQ,
        "keep_key": "dpq_keep_days",
    },
    # Append-only job-cycle log → AGE-ONLY (statuses=None). Every row is a
    # finished cycle record; no in-flight rows to protect. idx_loop_log_created
    # exists, so the age filter is an index scan.
    "autonomy_loop_log": {
        "age_col": "created_at",
        "statuses": None,
        "keep_key": "autonomy_loop_log_keep_days",
    },
    # HMAC-signed C.R.E.E.D. audit trail. Schema-qualified (a duplicate empty
    # copy lives in `sandbox`; search_path resolves unqualified to public, but we
    # pin it explicitly). `timestamp` is a type keyword → quoted. idx exists. #4542.
    "public.governance_audit_log": {
        "age_col": '"timestamp"',
        "statuses": None,
        "keep_key": "governance_audit_log_keep_days",
    },
    # Placement observer (#5273/#5917). Append-only → AGE-ONLY: every row is a
    # completed GPU-vs-CPU decision, there is nothing in flight to protect.
    # idx_mpl_created (migration 473) makes the age filter an index scan.
    #
    # Registered here at birth ON PURPOSE. A table with a retention POLICY and no
    # PRUNER has shipped TWICE: the `vps` tier was declared for all 10 components
    # while the string "vps" appeared nowhere else in retention_prune.py, and
    # outpost-us hit 100% disk (#5616); the gdrive tier had RETENTION tuples that
    # main() never walked, and the 15 GB account filled for ~3 weeks (#5092).
    # Measured rate is modest (~75 rows/hour steady state), but "small today" is
    # not a reason to leave an append-only table unbounded.
    "model_placement_log": {
        "age_col": "created_at",
        "statuses": None,
        "keep_key": "model_placement_log_keep_days",
    },
}

_LAST_RUN_KEY = "retention:last_run"
_MAX_BATCHES = 10_000  # hard backstop against a runaway loop (5k * 10k = 50M rows)


def _parse_int(val, fallback):
    try:
        if val in (None, ""):
            return fallback
        return int(float(val))
    except (TypeError, ValueError):
        return fallback


def _parse_bool(val, fallback):
    if val in (None, ""):
        return fallback
    return str(val).strip().lower() in ("1", "true", "yes", "on", "enabled")


def _load_config(cur):
    """Merge ``platform_settings`` ``retention:*`` rows over ``DEFAULTS``. PURE-ish
    (only reads the cursor). Fail-safe: any error → DEFAULTS."""
    cfg = dict(DEFAULTS)
    try:
        cur.execute(
            "SELECT key, value FROM platform_settings WHERE key LIKE %s",
            ("retention:%",),
        )
        for row in cur.fetchall() or []:
            key = row["key"] if isinstance(row, dict) else row[0]
            value = row["value"] if isinstance(row, dict) else row[1]
            dkey = _PS_KEYS.get(key)
            if not dkey:
                continue
            if dkey == "enabled":
                cfg[dkey] = _parse_bool(value, DEFAULTS[dkey])
            else:
                cfg[dkey] = _parse_int(value, DEFAULTS[dkey])
    except Exception:
        logger.warning("[Retention] config load failed; using defaults", exc_info=True)
        return dict(DEFAULTS)
    return cfg


def prune_table(cur, conn, *, table, age_col, statuses, keep_days, batch_size, dry_run=False):
    """Delete terminal rows in ``table`` older than ``keep_days``, in batches.

    Returns the count deleted (or, for ``dry_run``, the count that WOULD be
    deleted). The status/age columns and table name are module constants — never
    user input — so the f-string is safe.

    ``statuses`` is a terminal allowlist (status-machine tables) OR ``None`` for an
    age-only prune of an append-only log (every row is historical).
    """
    keep_days = int(keep_days)
    if keep_days <= 0:
        return 0

    # Build the optional status guard. statuses=None → age-only (no status clause).
    if statuses is None:
        status_clause = ""
        status_params = ()
    else:
        status_clause = "status = ANY(%s) AND "
        status_params = (list(statuses),)

    if dry_run:
        cur.execute(
            f"""
            SELECT COUNT(*) AS n FROM {table}
            WHERE {status_clause}{age_col} < NOW() - make_interval(days => %s)
            """,
            (*status_params, keep_days),
        )
        row = cur.fetchone()
        return int((row["n"] if isinstance(row, dict) else row[0]) or 0)

    total = 0
    for _ in range(_MAX_BATCHES):
        cur.execute(
            f"""
            DELETE FROM {table}
            WHERE id IN (
                SELECT id FROM {table}
                WHERE {status_clause}{age_col} < NOW() - make_interval(days => %s)
                ORDER BY id
                LIMIT %s
            )
            """,
            (*status_params, keep_days, batch_size),
        )
        n = cur.rowcount or 0
        if conn is not None:
            conn.commit()
        total += n
        if n < batch_size:
            break
    else:
        logger.warning(
            "[Retention] %s hit MAX_BATCHES (%d) — stopping; rerun next cycle",
            table,
            _MAX_BATCHES,
        )
    return total


def _record_last_run(cur, result, dry_run, failed=None):
    """Stamp ``platform_settings[retention:last_run]`` for Autonomy-tab visibility.
    Fail-safe — a write error must never undo the prune.

    ``failed`` (#5920) is ADDITIVE: a ``{table: reason}`` map recorded alongside
    the existing ``deleted`` key, never inside it, so the stamp's established
    shape is unchanged for anything already reading it. A partial run must be
    distinguishable from a clean one AT THE STAMP — otherwise the only record
    that some tables never pruned lives in a log line nobody reads.
    """
    extra = {"failed": failed} if failed else {}
    try:
        from services.time_utils import now_utc

        payload = json.dumps({"at": now_utc().isoformat(), "dry_run": dry_run, "deleted": result, **extra})
    except Exception:
        payload = json.dumps({"dry_run": dry_run, "deleted": result, **extra})
    try:
        cur.execute(
            """
            INSERT INTO platform_settings (key, value, value_type, description, updated_at)
            VALUES (%s, %s, 'json', 'Last dispatch-retention prune run (#4542)', NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, value_type = 'json', updated_at = NOW()
            """,
            (_LAST_RUN_KEY, payload),
        )
    except Exception:
        logger.warning("[Retention] could not record last_run", exc_info=True)


def run_retention(dry_run=False):
    """Prune both dispatch tables per config. Opens its own DB cursor.

    Returns ``{"enabled": bool, "dry_run": bool, "deleted": {table: count}}``.
    Fail-safe: any unexpected error logs and returns ``enabled=None``.
    """
    try:
        from database import get_db_cursor
    except Exception:
        logger.exception("[Retention] cannot import get_db_cursor")
        return {"enabled": None, "deleted": {}}

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cfg = _load_config(cur)
            if not cfg["enabled"]:
                logger.info("[Retention] disabled via platform_settings; skipping")
                return {"enabled": False, "dry_run": dry_run, "deleted": {}}

            result = {}
            failed = {}
            for table, spec in _TABLES.items():
                # #5920 — PER-TABLE isolation. This loop used to sit bare inside the
                # single outer try/except, so ANY failure on ANY one table (a missing
                # DEFAULTS key -> KeyError, a renamed column, a lock timeout, a
                # permissions change) aborted the WHOLE run: every later table went
                # unpruned, `_record_last_run` never stamped, and the caller got
                # {"enabled": None, "deleted": {}} — which reads like "nothing needed
                # pruning" rather than "retention is broken".
                #
                # Same defect `run_backup.sh` had, and the same resolution (#5092):
                # one component's failure must not veto the rest; report a PARTIAL.
                try:
                    keep_days = cfg[spec["keep_key"]]
                    if keep_days is None or keep_days <= 0:
                        logger.info("[Retention] %s keep_days<=0 → skip", table)
                        result[table] = 0
                        continue
                    n = prune_table(
                        cur,
                        conn,
                        table=table,
                        age_col=spec["age_col"],
                        statuses=spec["statuses"],
                        keep_days=keep_days,
                        batch_size=cfg["batch_size"],
                        dry_run=dry_run,
                    )
                    result[table] = n
                    logger.info(
                        "[Retention] %s: %s %d row(s) (keep_days=%d, dry_run=%s)",
                        table,
                        "would delete" if dry_run else "deleted",
                        n,
                        keep_days,
                        dry_run,
                    )
                except Exception as exc:  # noqa: BLE001 — one table must not veto the rest
                    # Deliberately NOT recorded in `deleted`: a failed table showing 0
                    # would be indistinguishable from a table with nothing to prune,
                    # which is the reporting bug this fix exists to remove.
                    failed[table] = f"{type(exc).__name__}: {exc}"
                    logger.exception("[Retention] %s FAILED — continuing with the rest", table)
                    # A failed table may have left this transaction aborted; without a
                    # rollback every SUBSEQUENT table would die on
                    # "current transaction is aborted", turning isolation into a no-op.
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001
                        logger.warning("[Retention] rollback after %s failure did not succeed", table)
            # `result` is passed UNWRAPPED: _record_last_run already nests it under
            # "deleted". Passing a {"deleted":..., "failed":...} dict here would store
            # {"deleted": {"deleted": ...}} and silently change the stamp's shape for
            # whatever reads it.
            _record_last_run(cur, result, dry_run, failed=failed)
            if failed:
                logger.warning("[Retention] PARTIAL — %d table(s) failed: %s", len(failed), list(failed))
            return {
                "enabled": True,
                "dry_run": dry_run,
                "deleted": result,
                "failed": failed,
            }
    except Exception:
        logger.exception("[Retention] run_retention failed")
        return {"enabled": None, "dry_run": dry_run, "deleted": {}}
