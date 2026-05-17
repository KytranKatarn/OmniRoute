"""factcheck_backlog_worker.py — fill V.E.R.I.F.Y. fact-check gap (5,557 articles).

Reads articles missing a fact_check row, dispatches the wtf-hub 'factcheck' task,
inserts result into wtf.fact_checks. Default OFF — set WTF_FACTCHECK_BACKLOG_ENABLED=true.

Distinct from llm_analysis_backlog_worker:
  - This fills wtf.fact_checks (the V.E.R.I.F.Y. agent's own table)
  - llm_analysis_backlog_worker fills wtf.llm_analyses (combined deep-analysis cache)
  - Both can run together; they target different storage and different prompts.
"""
import json
import logging
import os
import time

from sqlalchemy import text

from . import ai_dispatcher

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_FACTCHECK_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_FACTCHECK_BACKLOG_BATCH_SIZE", "25"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_FACTCHECK_BACKLOG_DISPATCH_SLEEP_SEC", "5"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_FACTCHECK_BACKLOG_MAX_AGE_DAYS", "7"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_FACTCHECK_BACKLOG_MAX_RUNS_PER_NIGHT", "200"))

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
                  AND NOT EXISTS (
                      SELECT 1 FROM {schema}.fact_checks f WHERE f.article_id = a.id
                  )
                ORDER BY a.published_at DESC
                LIMIT :limit
            """),
            {"max_age_days": _MAX_AGE_DAYS, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def _persist(engine, schema: str, article_id: int, result: dict) -> None:
    """Persist fact-check result. Matches existing wtf.fact_checks schema —
    one row per article holding the full claims JSON + overall verdict."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(
            text(f"""
                INSERT INTO {schema}.fact_checks (article_id, claims_json, overall_verdict, confidence, created_at)
                VALUES (:article_id, CAST(:claims AS JSONB), :verdict, :confidence, NOW())
                ON CONFLICT (article_id) DO NOTHING
            """),
            {
                "article_id": article_id,
                "claims": json.dumps(result.get("claims", [])),
                "verdict": result.get("overall_verdict", "unverifiable"),
                "confidence": result.get("confidence", 0.0),
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
                task="factcheck",
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
                    logger.exception("[factcheck_backlog] article=%s persist failed: %s", article["id"], exc)
            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "failed": failed, "stopped": "max_runs"}
