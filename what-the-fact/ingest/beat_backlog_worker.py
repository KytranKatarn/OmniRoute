"""beat_backlog_worker.py — backfill wtf.articles.beat via classify_beat hub task.

Fetches articles without a beat tag (newest first) and classifies them into one of
10 Canadian news beats: climate, crime, economy, education, foreign-policy, healthcare,
housing, immigration, indigenous, parliament.

Runs inside the wtf-ingest cycle as part of the parallel backlog worker pool.
Each cycle processes up to _MAX_PER_RUN articles then yields back to the pool.
Articles are processed newest → oldest so recently-ingested articles (the ones
users are actually reading) get tagged first.

Default OFF — set WTF_BEAT_BACKLOG_ENABLED=true to activate.
"""
import logging
import os
import time

from sqlalchemy import text

from .ai_dispatcher import analyze_with_status

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_BEAT_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_BEAT_BACKLOG_BATCH_SIZE", "10"))
# Throughput fix (audit 2026-07-14, #4897): sleep LOWERED 5s → 2s (faster cadence)
# and per-run cap RAISED 50 → 150 (more articles per cycle). At the old defaults the
# worker could tag at most ~110/day against ~1,100 new articles/day, so beat
# coverage mathematically never caught up (cohorts flat at 8-27%).
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_BEAT_BACKLOG_DISPATCH_SLEEP_SEC", "2"))
_MAX_PER_RUN = int(os.environ.get("WTF_BEAT_BACKLOG_MAX_PER_RUN", "150"))
# Bail out of the run after this many CONSECUTIVE dispatch failures (hub down /
# cold model) instead of terminally poisoning each failed article as 'none'.
_MAX_CONSEC_FAILURES = int(os.environ.get("WTF_BEAT_BACKLOG_MAX_CONSEC_FAILURES", "5"))
# Wall-clock budget per run — a full 150-200 article run paced at the hub's
# per-task interval (~5s) takes ~15-25 min; yield to the main loop after this.
_MAX_RUN_SECS = int(os.environ.get("WTF_BEAT_BACKLOG_MAX_RUN_SECS", "1500"))
# Per-article attempts when the hub answers rate_limited: honor its retry_after
# hint (clamped 1..30s) and try again — the OLD behaviour abandoned the ENTIRE
# run on the first rate-limit, capping throughput at a handful of articles per
# 30-60 min cycle (audit 2026-07-14: hub interval is 5s; the worker's 1s cadence
# tripped it instantly and then quit).
_MAX_RATE_LIMIT_ATTEMPTS = int(os.environ.get("WTF_BEAT_BACKLOG_RATE_LIMIT_ATTEMPTS", "4"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})

VALID_BEATS = frozenset({
    "arts-culture", "business", "climate", "crime",
    "economy", "education", "foreign-policy", "healthcare",
    "housing", "immigration", "indigenous", "justice",
    "labour", "municipal", "parliament", "science-tech",
    "sports", "transportation",
})

__name__ = "beat_backlog_worker"


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT a.id, a.title, LEFT(a.body, 1500) AS body,
                       s.slug AS source_slug
                FROM {schema}.articles a
                JOIN {schema}.sources s ON s.id = a.source_id
                WHERE a.beat IS NULL
                ORDER BY a.published_at DESC NULLS LAST
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def _persist(engine, schema: str, article_id: int, beat: str | None) -> None:
    """Write the beat (or 'none' sentinel) so this article is not re-fetched next cycle."""
    # Use 'none' as terminal sentinel for articles that don't fit any beat.
    # NULL means unprocessed; 'none' means processed but no beat matched.
    value = beat if beat in VALID_BEATS else "none"
    with engine.begin() as c:
        c.execute(
            text(f"UPDATE wtf.articles SET beat = :beat WHERE id = :id"),
            {"beat": value, "id": article_id},
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    if not _ENABLED:
        return {"processed": 0, "tagged": 0, "stopped": "disabled"}

    if schema not in _ALLOWED_SCHEMAS:
        logger.warning("beat_backlog_worker: disallowed schema %r — skipping", schema)
        return {"processed": 0, "tagged": 0, "stopped": "bad_schema"}

    processed = 0
    tagged = 0
    rate_limited = 0
    failed = 0
    consec_failures = 0
    deadline = time.monotonic() + _MAX_RUN_SECS

    while processed < _MAX_PER_RUN:
        if time.monotonic() > deadline:
            logger.info(
                "beat_backlog_worker: run deadline %ds reached — yielding "
                "(processed=%d tagged=%d)", _MAX_RUN_SECS, processed, tagged,
            )
            return {"processed": processed, "tagged": tagged, "failed": failed,
                    "rate_limited": rate_limited, "stopped": "run_deadline"}
        remaining = min(_BATCH_SIZE, _MAX_PER_RUN - processed)
        batch = _fetch_batch(engine, schema, remaining)
        if not batch:
            break

        for row in batch:
            if time.monotonic() > deadline:
                return {"processed": processed, "tagged": tagged, "failed": failed,
                        "rate_limited": rate_limited, "stopped": "run_deadline"}

            # Dispatch with rate-limit pacing: honor the hub's retry_after hint
            # (the hub's per-task interval is ~5s; genuine saturation — the
            # welfare in-flight cap — persists across attempts and we yield).
            result = {"result": None, "status": "failed"}
            for _attempt in range(_MAX_RATE_LIMIT_ATTEMPTS):
                result = analyze_with_status(
                    task="classify_beat",
                    article_id=row["id"],
                    title=row["title"] or "",
                    body=row["body"] or "",
                    source_slug=row["source_slug"] or "",
                )
                if result["status"] != "rate_limited":
                    break
                rate_limited += 1
                wait = max(1, min(int(result.get("retry_after") or 5), 30))
                if time.monotonic() + wait > deadline:
                    return {"processed": processed, "tagged": tagged, "failed": failed,
                            "rate_limited": rate_limited, "stopped": "run_deadline"}
                time.sleep(wait)

            if result["status"] == "rate_limited":
                # Still limited after honoring retry_after N times — the hub is
                # genuinely saturated (in-flight cap). Yield until next cycle.
                logger.info(
                    "beat_backlog_worker: hub saturated after %d paced attempts "
                    "(processed=%d) — yielding this cycle",
                    _MAX_RATE_LIMIT_ATTEMPTS, processed,
                )
                return {
                    "processed": processed,
                    "tagged": tagged,
                    "failed": failed,
                    "rate_limited": rate_limited,
                    "stopped": "rate_limited",
                }

            if result["status"] == "ok" and result.get("result"):
                raw = result["result"]
                beat = None
                if isinstance(raw, dict):
                    beat = (raw.get("beat") or "").strip().lower()
                    if beat not in VALID_BEATS:
                        beat = None
                # _persist writes the beat, or the terminal 'none' sentinel for a
                # GENUINE classified-but-no-match — the only case 'none' is correct.
                _persist(engine, schema, row["id"], beat)
                consec_failures = 0
                if beat:
                    tagged += 1
                    logger.debug(
                        "beat_backlog_worker: article %d → %s", row["id"], beat
                    )
                else:
                    logger.debug(
                        "beat_backlog_worker: article %d → none (no match)", row["id"]
                    )
            else:
                # Transient dispatch failure (hub down / cold model / timeout) —
                # leave the row NULL so it is retried on a later cycle. The old
                # behaviour terminally marked failures 'none', permanently
                # mis-filing articles during every dispatch-churn window
                # (1,547 contaminated in the week of the 2026-07-14 audit).
                failed += 1
                consec_failures += 1
                logger.debug(
                    "beat_backlog_worker: article %d dispatch failed — will retry",
                    row["id"],
                )
                if consec_failures >= _MAX_CONSEC_FAILURES:
                    logger.warning(
                        "beat_backlog_worker: %d consecutive failures — yielding "
                        "this cycle (processed=%d tagged=%d failed=%d)",
                        consec_failures, processed, tagged, failed,
                    )
                    return {
                        "processed": processed,
                        "tagged": tagged,
                        "failed": failed,
                        "rate_limited": rate_limited,
                        "stopped": "consecutive_failures",
                    }

            processed += 1
            time.sleep(_DISPATCH_SLEEP_SEC)

    logger.info(
        "beat_backlog_worker: %d processed, %d tagged this run",
        processed, tagged,
    )
    return {"processed": processed, "tagged": tagged, "rate_limited": rate_limited}
