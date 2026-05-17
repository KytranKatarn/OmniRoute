"""cluster_backlog_worker.py — fill I.N.K. clustering gap (2,153 articles).

Reads articles where cluster_id IS NULL, runs the existing Jaccard-similarity
clustering algorithm against the 24h window, assigns to an existing cluster
or creates a new one. CPU-only — no LLM, no hub round-trip.

Cheapest of the four backlog workers. Safe to enable first.

Default OFF — set WTF_CLUSTER_BACKLOG_ENABLED=true.
"""
import logging
import os
import time

from sqlalchemy import text

from .cluster import find_or_create_cluster

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_CLUSTER_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_CLUSTER_BACKLOG_BATCH_SIZE", "100"))
_LOOP_SLEEP_SEC = float(os.environ.get("WTF_CLUSTER_BACKLOG_LOOP_SLEEP_SEC", "0.05"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_CLUSTER_BACKLOG_MAX_AGE_DAYS", "30"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_CLUSTER_BACKLOG_MAX_RUNS_PER_NIGHT", "5000"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT id, title, published_at
                FROM {schema}.articles
                WHERE cluster_id IS NULL
                  AND published_at > NOW() - make_interval(days => :max_age_days)
                ORDER BY published_at DESC
                LIMIT :limit
            """),
            {"max_age_days": _MAX_AGE_DAYS, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def _assign(engine, schema: str, article_id: int, cluster_id: int) -> None:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_assign: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(
            text(f"UPDATE {schema}.articles SET cluster_id = :cid WHERE id = :aid"),
            {"cid": cluster_id, "aid": article_id},
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "stopped": "disabled"}

    processed = 0
    failed = 0
    while processed + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "failed": failed, "stopped": "no_backlog"}

        for article in batch:
            if processed + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "failed": failed, "stopped": "max_runs"}
            try:
                cid = find_or_create_cluster(
                    engine, article["id"], article["title"], article["published_at"]
                )
                _assign(engine, schema, article["id"], cid)
                processed += 1
            except Exception as exc:
                failed += 1
                logger.exception("[cluster_backlog] article=%s failed: %s", article["id"], exc)
            time.sleep(_LOOP_SLEEP_SEC)

    return {"processed": processed, "failed": failed, "stopped": "max_runs"}
