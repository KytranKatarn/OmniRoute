"""geo_backlog_worker.py — fill L.O.C.A.L. geo gap (5,774 articles).

Reads articles with no geo info (province_code IS NULL AND city IS NULL),
dispatches wtf-hub 'geo' task, writes lat/lng/province_code/city back onto
the articles row. Many articles have no detectable Canadian location (sports
columns, international news) — those get geo_scope='international' and stop
re-dispatching.

Default OFF — set WTF_GEO_BACKLOG_ENABLED=true.
"""
import logging
import os
import time

from sqlalchemy import text

from . import ai_dispatcher

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_GEO_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_GEO_BACKLOG_BATCH_SIZE", "50"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_GEO_BACKLOG_DISPATCH_SLEEP_SEC", "3"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_GEO_BACKLOG_MAX_AGE_DAYS", "7"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_GEO_BACKLOG_MAX_RUNS_PER_NIGHT", "500"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT a.id, a.title, a.body, s.slug AS source_slug
                FROM {schema}.articles a
                JOIN {schema}.sources s ON s.id = a.source_id
                WHERE a.published_at > NOW() - make_interval(days => :max_age_days)
                  AND a.province_code IS NULL
                  AND a.city IS NULL
                  AND a.geo_scope = 'national'
                ORDER BY a.published_at DESC
                LIMIT :limit
            """),
            {"max_age_days": _MAX_AGE_DAYS, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def _persist(engine, schema: str, article_id: int, result: dict) -> None:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(
            text(f"""
                UPDATE {schema}.articles
                SET province_code = :pc,
                    city          = :city,
                    lat           = :lat,
                    lng           = :lng,
                    geo_scope     = COALESCE(:geo_scope, geo_scope)
                WHERE id = :article_id
            """),
            {
                "article_id": article_id,
                "pc": result.get("province_code"),
                "city": result.get("city"),
                "lat": result.get("lat"),
                "lng": result.get("lng"),
                "geo_scope": result.get("geo_scope"),
            },
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

            result = ai_dispatcher.analyze(
                task="geo",
                article_id=article["id"],
                title=article["title"],
                body=article["body"],
                source_slug=article["source_slug"] or "",
            )
            if result is None:
                failed += 1
            else:
                try:
                    _persist(engine, schema, article["id"], result)
                    processed += 1
                except Exception as exc:
                    failed += 1
                    logger.exception("[geo_backlog] article=%s persist failed: %s", article["id"], exc)
            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "failed": failed, "stopped": "max_runs"}
