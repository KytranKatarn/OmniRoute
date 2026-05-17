"""llm_analysis_backlog_worker.py — fill the LLM Analyzed gap (8,788 articles).

Reads articles with ai_analyzed=false, dispatches the wtf-hub 'deep_analysis'
task to V.E.R.I.F.Y. via mesh, caches the JSONB result in wtf.llm_analyses,
flips ai_analyzed=true on success. Consumer's "Analyze" click then reads the
cached row instantly — no on-demand LLM.

Bypasses orchestrator.pick_priority_articles() — the priority filter is for
forward ingestion; this worker exists to clear the historical backlog.

Default OFF. Set WTF_LLM_BACKLOG_ENABLED=true to run.
"""
import json
import logging
import os
import time

from sqlalchemy import text

from . import ai_dispatcher

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_LLM_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_LLM_BACKLOG_BATCH_SIZE", "25"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_LLM_BACKLOG_DISPATCH_SLEEP_SEC", "5"))
_IDLE_SLEEP_SEC = float(os.environ.get("WTF_LLM_BACKLOG_IDLE_SLEEP_SEC", "300"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_LLM_BACKLOG_MAX_AGE_DAYS", "7"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_LLM_BACKLOG_MAX_RUNS_PER_NIGHT", "200"))
_MODEL_LABEL = os.environ.get("WTF_LLM_BACKLOG_MODEL_LABEL", "deep_analysis_v1")

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
                WHERE a.ai_analyzed = false
                  AND a.published_at > NOW() - make_interval(days => :max_age_days)
                  AND NOT EXISTS (
                      SELECT 1 FROM {schema}.llm_analyses la
                      WHERE la.article_id = a.id AND la.model = :model
                  )
                ORDER BY a.published_at DESC
                LIMIT :limit
            """),
            {"max_age_days": _MAX_AGE_DAYS, "model": _MODEL_LABEL, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def _persist(engine, schema: str, article_id: int, sections: dict) -> None:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(
            text(f"""
                INSERT INTO {schema}.llm_analyses (article_id, sections_json, model, completed_at)
                VALUES (:article_id, CAST(:sections AS JSONB), :model, NOW())
                ON CONFLICT (article_id, model) DO UPDATE
                  SET sections_json = EXCLUDED.sections_json,
                      completed_at = NOW()
            """),
            {"article_id": article_id, "sections": json.dumps(sections), "model": _MODEL_LABEL},
        )
        c.execute(
            text(f"""
                UPDATE {schema}.articles
                SET ai_analyzed = true, ai_analyzed_at = NOW()
                WHERE id = :article_id
            """),
            {"article_id": article_id},
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    """Process one shift of LLM analysis backlog. Returns {processed, failed, skipped, stopped}."""
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "skipped": 0, "stopped": "disabled"}

    processed = 0
    failed = 0
    skipped = 0
    while processed + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "failed": failed, "skipped": skipped, "stopped": "no_backlog"}

        for article in batch:
            if processed + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "failed": failed, "skipped": skipped, "stopped": "max_runs"}

            result = ai_dispatcher.analyze(
                task="deep_analysis",
                article_id=article["id"],
                title=article["title"],
                body=article["body"],
                source_slug=article["source_slug"] or "",
            )

            if result is None:
                failed += 1
                logger.warning("[llm_backlog] article=%s dispatch returned None", article["id"])
            else:
                try:
                    _persist(engine, schema, article["id"], result)
                    processed += 1
                except Exception as exc:
                    failed += 1
                    logger.exception("[llm_backlog] article=%s persist failed: %s", article["id"], exc)

            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "failed": failed, "skipped": skipped, "stopped": "max_runs"}
