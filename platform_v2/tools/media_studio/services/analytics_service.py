"""Analytics service — realtime stats, trend snapshots, cost estimation for Media Studio."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real-time functions
# ---------------------------------------------------------------------------


def get_realtime_stats(
    owner_type: Optional[str] = None,
    owner_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict:
    """Quick counts from live tables.

    Scoped optionally by owner_type/owner_id and date range.
    Returns generation_count, edit_count, batch_count, active_pipelines, storage_bytes.
    """
    scope_parts = []
    scope_vals = []

    if owner_type is not None:
        scope_parts.append("owner_type = %s")
        scope_vals.append(owner_type)
    if owner_id is not None:
        scope_parts.append("owner_id = %s")
        scope_vals.append(owner_id)

    date_parts = []
    date_vals = []
    if date_from is not None:
        date_parts.append("created_at >= %s")
        date_vals.append(date_from)
    if date_to is not None:
        date_parts.append("created_at <= %s")
        date_vals.append(date_to)

    def _where(extra_parts=None):
        parts = list(scope_parts) + list(date_parts)
        if extra_parts:
            parts.extend(extra_parts)
        if parts:
            return "WHERE " + " AND ".join(parts)
        return ""

    def _vals(extra_vals=None):
        v = list(scope_vals) + list(date_vals)
        if extra_vals:
            v.extend(extra_vals)
        return v

    try:
        with get_db_cursor() as (conn, cur):
            # Generation count (media_library, not deleted)
            cur.execute(
                f"SELECT COUNT(*) FROM media_library {_where(['is_deleted = false'])}",
                _vals(),
            )
            generation_count = cur.fetchone()[0]

            # Edit count
            edit_completed = "status = 'completed'"
            cur.execute(
                f"SELECT COUNT(*) FROM media_edits {_where([edit_completed])}",
                _vals(),
            )
            edit_count = cur.fetchone()[0]

            # Batch count
            cur.execute(
                f"SELECT COUNT(*) FROM media_batches {_where()}",
                _vals(),
            )
            batch_count = cur.fetchone()[0]

            # Active pipelines — no owner scope on pipeline executions
            pip_parts = []
            pip_vals = []
            if date_from is not None:
                pip_parts.append("created_at >= %s")
                pip_vals.append(date_from)
            if date_to is not None:
                pip_parts.append("created_at <= %s")
                pip_vals.append(date_to)
            pip_parts.append("status = 'running'")
            pip_where = "WHERE " + " AND ".join(pip_parts) if pip_parts else ""
            cur.execute(
                f"SELECT COUNT(*) FROM media_pipeline_executions {pip_where}",
                pip_vals,
            )
            active_pipelines = cur.fetchone()[0]

        storage_bytes = generation_count * 2 * 1024 * 1024  # 2 MB estimate per item

        return {
            "generation_count": generation_count,
            "edit_count": edit_count,
            "batch_count": batch_count,
            "active_pipelines": active_pipelines,
            "storage_bytes": storage_bytes,
        }
    except Exception:
        logger.exception("get_realtime_stats failed")
        return {
            "generation_count": 0,
            "edit_count": 0,
            "batch_count": 0,
            "active_pipelines": 0,
            "storage_bytes": 0,
        }


def get_recent_activity(
    owner_type: Optional[str] = None,
    owner_id: Optional[int] = None,
    limit: int = 20,
) -> List[Dict]:
    """Last N rows from media_library with model, media_type, created_at."""
    parts = ["is_deleted = false"]
    vals: list = []
    if owner_type is not None:
        parts.append("owner_type = %s")
        vals.append(owner_type)
    if owner_id is not None:
        parts.append("owner_id = %s")
        vals.append(owner_id)

    where = "WHERE " + " AND ".join(parts)
    vals.append(limit)

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""
                SELECT id, model, media_type, owner_type, owner_id, created_at
                FROM media_library
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                vals,
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "model": r[1],
                    "media_type": r[2],
                    "owner_type": r[3],
                    "owner_id": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]
    except Exception:
        logger.exception("get_recent_activity failed")
        return []


# ---------------------------------------------------------------------------
# Pre-computed snapshot readers
# ---------------------------------------------------------------------------


def _snapshot_where(
    period_type: str,
    scope_type: str,
    scope_id: int,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
):
    """Build WHERE clause + values for snapshot queries."""
    parts = ["period_type = %s", "scope_type = %s", "scope_id = %s"]
    vals: list = [period_type, scope_type, scope_id]
    if date_from is not None:
        parts.append("period_start >= %s")
        vals.append(date_from)
    if date_to is not None:
        parts.append("period_end <= %s")
        vals.append(date_to)
    return "WHERE " + " AND ".join(parts), vals


def get_trend_data(
    period_type: str,
    scope_type: str = "global",
    scope_id: int = 0,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> List[Dict]:
    """SELECT trend snapshots for range. Returns [{period_start, metrics}, ...]."""
    where, vals = _snapshot_where(period_type, scope_type, scope_id, date_from, date_to)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""
                SELECT period_start, metrics
                FROM media_analytics_snapshots
                {where}
                ORDER BY period_start ASC
                """,
                vals,
            )
            return [
                {
                    "period_start": r[0].isoformat() if r[0] else None,
                    "metrics": r[1],
                }
                for r in cur.fetchall()
            ]
    except Exception:
        logger.exception("get_trend_data failed")
        return []


def get_model_breakdown(
    scope_type: str = "global",
    scope_id: int = 0,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict:
    """Aggregate by_model and by_edit_type from snapshot metrics."""
    where, vals = _snapshot_where("hourly", scope_type, scope_id, date_from, date_to)
    by_model: Dict[str, int] = {}
    by_edit_type: Dict[str, int] = {}
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"SELECT metrics FROM media_analytics_snapshots {where}",
                vals,
            )
            for (metrics,) in cur.fetchall():
                if not metrics:
                    continue
                for k, v in (metrics.get("by_model") or {}).items():
                    by_model[k] = by_model.get(k, 0) + v
                for k, v in (metrics.get("by_edit_type") or {}).items():
                    by_edit_type[k] = by_edit_type.get(k, 0) + v
    except Exception:
        logger.exception("get_model_breakdown failed")
    return {"by_model": by_model, "by_edit_type": by_edit_type}


def get_cost_summary(
    scope_type: str = "global",
    scope_id: int = 0,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    mode: str = "fixed",
) -> Dict:
    """Sum cost_fixed or cost_vram_time from snapshots. Also per-model cost breakdown."""
    where, vals = _snapshot_where("hourly", scope_type, scope_id, date_from, date_to)
    cost_key = "cost_fixed" if mode == "fixed" else "cost_vram_time"
    total = 0.0
    by_model_counts: Dict[str, int] = {}

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"SELECT metrics FROM media_analytics_snapshots {where}",
                vals,
            )
            for (metrics,) in cur.fetchall():
                if not metrics:
                    continue
                total += float(metrics.get(cost_key) or 0)
                for k, v in (metrics.get("by_model") or {}).items():
                    by_model_counts[k] = by_model_counts.get(k, 0) + v

            # Load cost rates for per-model breakdown
            cur.execute("SELECT model_name, cost_per_generation FROM media_cost_rates")
            rates = {r[0]: float(r[1]) for r in cur.fetchall()}

        by_model_cost = {model: count * rates.get(model, 0.0) for model, count in by_model_counts.items()}
        return {"total": total, "by_model": by_model_cost, "mode": mode}
    except Exception:
        logger.exception("get_cost_summary failed")
        return {"total": 0.0, "by_model": {}, "mode": mode}


def get_agent_vs_user(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict:
    """Sum metrics from snapshots scoped by user vs agent."""
    result = {"user": {}, "agent": {}}
    for scope_type in ("user", "agent"):
        parts = ["period_type = 'hourly'", "scope_type = %s"]
        vals: list = [scope_type]
        if date_from is not None:
            parts.append("period_start >= %s")
            vals.append(date_from)
        if date_to is not None:
            parts.append("period_end <= %s")
            vals.append(date_to)
        where = "WHERE " + " AND ".join(parts)
        totals: Dict[str, float] = {}
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    f"SELECT metrics FROM media_analytics_snapshots {where}",
                    vals,
                )
                for (metrics,) in cur.fetchall():
                    if not metrics:
                        continue
                    for k, v in metrics.items():
                        if isinstance(v, (int, float)):
                            totals[k] = totals.get(k, 0.0) + float(v)
        except Exception:
            logger.exception("get_agent_vs_user failed for scope_type=%s", scope_type)
        result[scope_type] = totals
    return result


def get_template_stats(
    scope_type: str = "global",
    scope_id: int = 0,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict:
    """Sum template_runs and avg template_success_rate from snapshots."""
    where, vals = _snapshot_where("hourly", scope_type, scope_id, date_from, date_to)
    total_runs = 0
    success_rates = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"SELECT metrics FROM media_analytics_snapshots {where}",
                vals,
            )
            for (metrics,) in cur.fetchall():
                if not metrics:
                    continue
                total_runs += int(metrics.get("template_runs") or 0)
                rate = metrics.get("template_success_rate")
                if rate is not None:
                    success_rates.append(float(rate))
    except Exception:
        logger.exception("get_template_stats failed")

    avg_rate = sum(success_rates) / len(success_rates) if success_rates else 0.0
    return {"template_runs": total_runs, "template_success_rate": avg_rate}


# ---------------------------------------------------------------------------
# Admin functions
# ---------------------------------------------------------------------------


def get_cost_rates() -> List[Dict]:
    """SELECT all rows from media_cost_rates ORDER BY model_name."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT model_name, cost_per_generation, vram_gb_per_sec " "FROM media_cost_rates ORDER BY model_name"
            )
            return [
                {
                    "model_name": r[0],
                    "cost_per_generation": float(r[1]) if r[1] is not None else None,
                    "vram_gb_per_sec": float(r[2]) if r[2] is not None else None,
                }
                for r in cur.fetchall()
            ]
    except Exception:
        logger.exception("get_cost_rates failed")
        return []


def update_cost_rate(
    model_name: str,
    cost_per_generation: Optional[float] = None,
    vram_gb_per_sec: Optional[float] = None,
) -> Dict:
    """UPSERT a cost rate row. Returns {"success": True}."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO media_cost_rates (model_name, cost_per_generation, vram_gb_per_sec)
                VALUES (%s, %s, %s)
                ON CONFLICT (model_name) DO UPDATE
                    SET cost_per_generation = COALESCE(EXCLUDED.cost_per_generation, media_cost_rates.cost_per_generation),
                        vram_gb_per_sec     = COALESCE(EXCLUDED.vram_gb_per_sec,     media_cost_rates.vram_gb_per_sec)
                """,
                (model_name, cost_per_generation, vram_gb_per_sec),
            )
        return {"success": True}
    except Exception:
        logger.exception("update_cost_rate failed for model=%s", model_name)
        return {"success": False, "error": "db error"}


# ---------------------------------------------------------------------------
# Aggregation — called by APScheduler
# ---------------------------------------------------------------------------

_PERIOD_DURATIONS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


def compute_snapshot(period_type: str = "hourly") -> int:
    """Compute and UPSERT analytics snapshots for the last completed period.

    Returns the number of snapshot rows written.
    """
    now = datetime.now(timezone.utc)
    delta = _PERIOD_DURATIONS.get(period_type, timedelta(hours=1))

    # Round down to the last complete period boundary
    if period_type == "hourly":
        period_end = now.replace(minute=0, second=0, microsecond=0)
    elif period_type == "daily":
        period_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period_type == "weekly":
        # Monday-aligned
        period_end = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        period_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    period_start = period_end - delta
    written = 0

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # --- generation counts per owner ---
            cur.execute(
                """
                SELECT owner_type, owner_id, COUNT(*) as cnt
                FROM media_library
                WHERE is_deleted = false
                  AND created_at >= %s AND created_at < %s
                GROUP BY owner_type, owner_id
                """,
                (period_start, period_end),
            )
            owner_counts = cur.fetchall()  # [(owner_type, owner_id, cnt), ...]

            # --- global generation count ---
            total_generations = sum(r[2] for r in owner_counts)

            # --- model breakdown (global) ---
            cur.execute(
                """
                SELECT model, COUNT(*) FROM media_library
                WHERE is_deleted = false
                  AND created_at >= %s AND created_at < %s
                GROUP BY model
                """,
                (period_start, period_end),
            )
            by_model = {r[0]: r[1] for r in cur.fetchall() if r[0]}

            # --- media_type breakdown (global) ---
            cur.execute(
                """
                SELECT media_type, COUNT(*) FROM media_library
                WHERE is_deleted = false
                  AND created_at >= %s AND created_at < %s
                GROUP BY media_type
                """,
                (period_start, period_end),
            )
            by_media_type = {r[0]: r[1] for r in cur.fetchall() if r[0]}

            # --- edit counts + edit_type breakdown ---
            cur.execute(
                """
                SELECT COUNT(*), edit_type FROM media_edits
                WHERE status = 'completed'
                  AND created_at >= %s AND created_at < %s
                GROUP BY edit_type
                """,
                (period_start, period_end),
            )
            edit_rows = cur.fetchall()
            total_edits = sum(r[0] for r in edit_rows)
            by_edit_type = {r[1]: r[0] for r in edit_rows if r[1]}

            # --- batch count ---
            cur.execute(
                "SELECT COUNT(*) FROM media_batches WHERE created_at >= %s AND created_at < %s",
                (period_start, period_end),
            )
            batch_count = cur.fetchone()[0]

            # --- template runs + success rate ---
            cur.execute(
                """
                SELECT COUNT(*),
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)
                FROM media_pipeline_executions
                WHERE created_at >= %s AND created_at < %s
                """,
                (period_start, period_end),
            )
            pip_row = cur.fetchone()
            template_runs = pip_row[0] or 0
            template_success = pip_row[1] or 0
            template_success_rate = float(template_success) / float(template_runs) if template_runs else 0.0

            # --- queue success/failure rate ---
            cur.execute(
                """
                SELECT
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),
                    COUNT(*)
                FROM media_generation_queue
                WHERE created_at >= %s AND created_at < %s
                """,
                (period_start, period_end),
            )
            q_row = cur.fetchone()
            q_total = q_row[2] or 0
            q_success = q_row[0] or 0
            q_failed = q_row[1] or 0
            queue_success_rate = float(q_success) / float(q_total) if q_total else 0.0
            queue_failure_rate = float(q_failed) / float(q_total) if q_total else 0.0

            # --- cost rates ---
            cur.execute("SELECT model_name, cost_per_generation, vram_gb_per_sec FROM media_cost_rates")
            rate_rows = cur.fetchall()
            cost_rates = {r[0]: {"fixed": float(r[1] or 0), "vram": float(r[2] or 0)} for r in rate_rows}

            cost_fixed = sum(by_model.get(m, 0) * rate_rates["fixed"] for m, rate_rates in cost_rates.items())
            cost_vram_time = sum(by_model.get(m, 0) * rate_rates["vram"] for m, rate_rates in cost_rates.items())

            # --- build global metrics ---
            global_metrics = {
                "generation_count": total_generations,
                "edit_count": total_edits,
                "batch_count": batch_count,
                "template_runs": template_runs,
                "template_success_rate": template_success_rate,
                "queue_success_rate": queue_success_rate,
                "queue_failure_rate": queue_failure_rate,
                "by_model": by_model,
                "by_media_type": by_media_type,
                "by_edit_type": by_edit_type,
                "cost_fixed": cost_fixed,
                "cost_vram_time": cost_vram_time,
            }

            # UPSERT global snapshot
            cur.execute(
                """
                INSERT INTO media_analytics_snapshots
                    (period_type, period_start, period_end, scope_type, scope_id, metrics)
                VALUES (%s, %s, %s, 'global', 0, %s)
                ON CONFLICT (period_type, period_start, scope_type, scope_id)
                DO UPDATE SET metrics = EXCLUDED.metrics, period_end = EXCLUDED.period_end
                """,
                (
                    period_type,
                    period_start,
                    period_end,
                    psycopg2.extras.Json(global_metrics),
                ),
            )
            written += 1

            # --- per-owner snapshots ---
            for owner_type, owner_id, gen_cnt in owner_counts:
                owner_metrics = {
                    "generation_count": gen_cnt,
                    "cost_fixed": gen_cnt * sum(r["fixed"] for r in cost_rates.values()) / max(len(cost_rates), 1),
                    "cost_vram_time": gen_cnt * sum(r["vram"] for r in cost_rates.values()) / max(len(cost_rates), 1),
                }
                cur.execute(
                    """
                    INSERT INTO media_analytics_snapshots
                        (period_type, period_start, period_end, scope_type, scope_id, metrics)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (period_type, period_start, scope_type, scope_id)
                    DO UPDATE SET metrics = EXCLUDED.metrics, period_end = EXCLUDED.period_end
                    """,
                    (
                        period_type,
                        period_start,
                        period_end,
                        owner_type,
                        owner_id,
                        psycopg2.extras.Json(owner_metrics),
                    ),
                )
                written += 1

    except Exception:
        logger.exception("compute_snapshot failed for period_type=%s", period_type)

    logger.info("compute_snapshot(%s): wrote %d snapshots", period_type, written)
    return written
