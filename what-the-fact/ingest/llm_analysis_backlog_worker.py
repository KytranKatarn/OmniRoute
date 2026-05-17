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

from . import ai_dispatcher, tier_router  # noqa: F401 — ai_dispatcher kept for any remaining single-tier callers

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
                SELECT a.id, a.title, a.body, s.slug AS source_slug,
                       s.bias_lean AS source_bias_lean,
                       COALESCE(sc.article_count, 0) AS cluster_size
                FROM {schema}.articles a
                JOIN {schema}.sources s ON s.id = a.source_id
                LEFT JOIN {schema}.story_clusters sc ON sc.id = a.cluster_id
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


def _persist(engine, schema: str, article_id: int, sections: dict, tier_meta: dict) -> None:
    """Persist analysis JSONB + update wtf.articles tier-tracking columns.

    tier_meta shape from tier_router.analyze_tiered():
      analysis_tier: 'quick_v1' | 'quick_v1+full' | 'quick_v1_failed+full' | ...
      tier1_ok: bool
      tier2_ran: bool
      tier2_status: 'ok' | 'rate_limited' | 'failed' | 'skipped'
      tier2_pending: bool (optional)
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    analysis_tier = tier_meta.get("analysis_tier") or "pending"
    tier1_ok = bool(tier_meta.get("tier1_ok"))
    tier2_ran = bool(tier_meta.get("tier2_ran"))
    tier2_status = tier_meta.get("tier2_status") or "skipped"
    tier2_pending = bool(tier_meta.get("tier2_pending"))
    failed_delta = 1 if (tier2_ran and tier2_status not in ("ok", "skipped")) else 0
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
                SET ai_analyzed = true,
                    ai_analyzed_at = NOW(),
                    analysis_tier = :analysis_tier,
                    tier1_at = CASE WHEN :tier1_ok THEN NOW() ELSE tier1_at END,
                    tier2_at = CASE WHEN :tier2_ok THEN NOW() ELSE tier2_at END,
                    tier2_pending = :tier2_pending,
                    tier2_failures = COALESCE(tier2_failures, 0) + :failed_delta
                WHERE id = :article_id
            """),
            {
                "article_id": article_id,
                "analysis_tier": analysis_tier,
                "tier1_ok": tier1_ok,
                "tier2_ok": tier2_ran and tier2_status == "ok",
                "tier2_pending": tier2_pending,
                "failed_delta": failed_delta,
            },
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    """Process one shift of LLM analysis backlog. Returns {processed, failed, skipped, stopped}."""
    if not _ENABLED:
        return {"processed": 0, "rate_limited": 0, "failed": 0, "skipped": 0, "stopped": "disabled"}

    processed = 0
    rate_limited = 0
    failed = 0
    skipped = 0
    while processed + rate_limited + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "rate_limited": rate_limited,
                    "failed": failed, "skipped": skipped, "stopped": "no_backlog"}

        for article in batch:
            if processed + rate_limited + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "rate_limited": rate_limited,
                        "failed": failed, "skipped": skipped, "stopped": "max_runs"}

            outcome = tier_router.analyze_tiered(
                article_id=article["id"],
                title=article["title"],
                body=article["body"],
                source_slug=article["source_slug"] or "",
                source_bias_lean=article.get("source_bias_lean") or "",
                cluster_size=int(article.get("cluster_size") or 0),
            )
            status = outcome["status"]
            tier_meta = outcome.get("tier_meta") or {}

            if status == "rate_limited":
                # Per #2944 — transient, retry next cycle without burning a 'failed' slot.
                rate_limited += 1
            elif status == "failed":
                failed += 1
                logger.warning(
                    "[llm_backlog] article=%s dispatch failed (analysis_tier=%s)",
                    article["id"],
                    tier_meta.get("analysis_tier", "pending"),
                )
            else:
                try:
                    _persist(engine, schema, article["id"], outcome["result"], tier_meta)
                    processed += 1
                    logger.info(
                        "[llm_backlog] article=%s persisted tier=%s gate=%s tier2=%s",
                        article["id"],
                        tier_meta.get("analysis_tier"),
                        tier_meta.get("gate_reason"),
                        tier_meta.get("tier2_status"),
                    )
                except Exception as exc:
                    failed += 1
                    logger.exception("[llm_backlog] article=%s persist failed: %s", article["id"], exc)

            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "rate_limited": rate_limited,
            "failed": failed, "skipped": skipped, "stopped": "max_runs"}
