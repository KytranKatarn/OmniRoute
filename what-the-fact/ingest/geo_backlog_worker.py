"""geo_backlog_worker.py — fill L.O.C.A.L. geo gap.

Reads articles with no geo info (province_code IS NULL AND city IS NULL AND
geo_scope='national'), routes through geocoder.extract_geo() which combines
the L.O.C.A.L. agent with a regex heuristic fallback. Writes
province_code/city/lat/lng/country_code/geo_scope back onto the row.

Articles where neither path finds a Canadian location are now stamped
geo_scope='unmappable' (terminal) instead of staying at 'national' — that
fixes the re-fetch loop documented in #2959. Future global expansion (#2960
Phase B) will set country_code for non-Canadian articles via prompt update
on the hub side.

Default OFF — set WTF_GEO_BACKLOG_ENABLED=true.
"""
import logging
import os
import time

from sqlalchemy import text

from .geocoder import extract_geo

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_GEO_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_GEO_BACKLOG_BATCH_SIZE", "50"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_GEO_BACKLOG_DISPATCH_SLEEP_SEC", "3"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_GEO_BACKLOG_MAX_AGE_DAYS", "7"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_GEO_BACKLOG_MAX_RUNS_PER_NIGHT", "500"))
# Hard wall-clock cap — prevents geo from blocking the main ingest loop forever
# when L.O.C.A.L. agent is slow/unavailable. Default 10 min.
_MAX_DURATION_SECS = int(os.environ.get("WTF_GEO_BACKLOG_MAX_DURATION_SECS", "600"))

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
    """Always advance geo_scope OFF 'national' so the next cycle won't re-fetch.

    Even an 'unmappable' write is progress — it tells the worker we tried.
    Per #2959, the COALESCE that preserved 'national' on a NULL result is
    exactly what kept re-dispatching the same articles forever.
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    with engine.begin() as c:
        # Phase C (#2943): mark geo as Tier-1 work. extract_geo() is heuristic-
        # fallback (always returns a terminal scope) so it's effectively
        # quick_v1 by design. International Tier-2 upgrade is #2960 Phase B,
        # a separate task.
        # Don't downgrade analysis_tier if some other worker already promoted
        # this row to quick_v1+full — only stamp 'quick_v1' on rows still in
        # 'pending' state.
        c.execute(
            text(f"""
                UPDATE {schema}.articles
                SET province_code = :pc,
                    city          = :city,
                    lat           = :lat,
                    lng           = :lng,
                    country_code  = :country,
                    geo_scope     = :geo_scope,
                    -- migration 073 (#6263): stamp on EVERY write, including an
                    -- 'unmappable' one. Both outcomes remove the article from the
                    -- pending set (province_code IS NULL AND geo_scope <>
                    -- 'unmappable'), so both are L.O.C.A.L. finishing its work.
                    -- Counting only successes would understate the drain rate and
                    -- reproduce the too-optimistic ETA this replaces.
                    geo_processed_at = NOW(),
                    analysis_tier = CASE
                        WHEN analysis_tier = 'pending' THEN 'quick_v1'
                        ELSE analysis_tier
                    END,
                    tier1_at = COALESCE(tier1_at, NOW())
                WHERE id = :article_id
            """),
            {
                "article_id": article_id,
                "pc": result.get("province_code"),
                "city": result.get("city"),
                "lat": result.get("lat"),
                "lng": result.get("lng"),
                "country": result.get("country_code"),
                "geo_scope": result.get("geo_scope") or "unmappable",
            },
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "stopped": "disabled"}

    deadline = time.monotonic() + _MAX_DURATION_SECS
    processed = 0
    unmapped = 0
    failed = 0
    while processed + unmapped + failed < _MAX_RUNS_PER_NIGHT:
        if time.monotonic() > deadline:
            logger.warning(
                "[geo_backlog] max_duration %ds reached — yielding to main loop",
                _MAX_DURATION_SECS,
            )
            return {"processed": processed, "unmapped": unmapped, "failed": failed,
                    "stopped": "max_duration"}
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "unmapped": unmapped, "failed": failed,
                    "stopped": "no_backlog"}

        for article in batch:
            if processed + unmapped + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "unmapped": unmapped, "failed": failed,
                        "stopped": "max_runs"}
            if time.monotonic() > deadline:
                logger.warning(
                    "[geo_backlog] max_duration %ds reached mid-batch — yielding",
                    _MAX_DURATION_SECS,
                )
                return {"processed": processed, "unmapped": unmapped, "failed": failed,
                        "stopped": "max_duration"}

            # extract_geo() always returns a dict — terminal geo_scope is its contract.
            result = extract_geo(article["id"], article["title"] or "", article["body"] or "")
            try:
                _persist(engine, schema, article["id"], result)
                if result.get("geo_scope") == "unmappable":
                    unmapped += 1
                else:
                    processed += 1
            except Exception as exc:
                failed += 1
                logger.exception("[geo_backlog] article=%s persist failed: %s", article["id"], exc)
            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "unmapped": unmapped, "failed": failed,
            "stopped": "max_runs"}
