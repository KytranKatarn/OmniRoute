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

from . import ai_dispatcher, tier_router  # noqa: F401 — ai_dispatcher kept for any legacy callers

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_FACTCHECK_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_FACTCHECK_BACKLOG_BATCH_SIZE", "25"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_FACTCHECK_BACKLOG_DISPATCH_SLEEP_SEC", "5"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_FACTCHECK_BACKLOG_MAX_AGE_DAYS", "7"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_FACTCHECK_BACKLOG_MAX_RUNS_PER_NIGHT", "200"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})

# LLM returns verdicts per the wtf-hub prompt: verified|mixed|disputed|unverifiable
# wtf.fact_checks.verdict CHECK constraint allows: true|mostly_true|mixed|false|unverified
# Verdict vocabulary lives in verdicts.py — ONE definition (#6242). This file
# carried its own copy; FOUR copies existed and ingest/run.py had NONE.
try:
    from ingest.verdicts import canonical_claim, canonical_overall
except ImportError:  # pragma: no cover
    from verdicts import canonical_claim, canonical_overall


def _normalize_verdict(raw) -> str:
    """Per-CLAIM verdict. Thin wrapper kept so call sites are unchanged."""
    return canonical_claim(raw)


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


def _update_article_tier(engine, schema: str, article_id: int, tier_meta: dict) -> None:
    """Stamp wtf.articles tier columns after a factcheck tier-router run."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_update_article_tier: disallowed schema {schema!r}")
    analysis_tier = tier_meta.get("analysis_tier") or "pending"
    tier1_ok = bool(tier_meta.get("tier1_ok"))
    tier2_ran = bool(tier_meta.get("tier2_ran"))
    tier2_status = tier_meta.get("tier2_status") or "skipped"
    tier2_pending = bool(tier_meta.get("tier2_pending"))
    failed_delta = 1 if (tier2_ran and tier2_status not in ("ok", "skipped")) else 0
    with engine.begin() as c:
        c.execute(
            text(f"""
                UPDATE {schema}.articles
                SET analysis_tier = :analysis_tier,
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


def _persist(engine, schema: str, article_id: int, result: dict,
             analysis_tier: str | None = None) -> None:
    """Persist V.E.R.I.F.Y. fact-check result into wtf.fact_checks.

    `analysis_tier` records HOW the verdict was produced, on the row itself.
    ⚠️ `quick_v1` means TIER 1 ONLY — claims extracted but NEVER verified,
    with a SYNTHESIZED overall_verdict. Without this column such a row is
    indistinguishable from a real adjudication (~88,000 were).

    Schema reality: NOT NULL columns are (article_id, claim, verdict, evidence,
    checker, checked_at). Nullable JSONB columns (claims, overall_verdict) hold
    the aggregate. Matches the forward heuristic pipeline (one row per claim).

    If the LLM returned no claims, writes a single placeholder row so the
    article won't be re-fetched on the next cycle (NOT EXISTS filter).
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    claims = result.get("claims") or []
    # TWO columns, TWO vocabularies (#6242). `overall` previously used the
    # per-CLAIM normalizer and was written to BOTH `verdict` and `overall_verdict`,
    # so the per-article column received `unverified` — which migration 060's
    # constraint now correctly rejects.
    overall = canonical_overall(result.get("overall_verdict"))
    placeholder_verdict = canonical_claim(result.get("overall_verdict"))
    claims_json = json.dumps(claims)

    if not claims:
        rows = [{
            "claim": "(no factual claims extracted)",
            "verdict": placeholder_verdict,
            "evidence": "(model returned no claims for this article)",
        }]
    else:
        rows = []
        for cl in claims:
            rows.append({
                "claim": (cl.get("text") or "(claim text missing)")[:500],
                "verdict": _normalize_verdict(cl.get("verdict")),
                "evidence": (cl.get("reasoning") or "")[:1000],
            })

    with engine.begin() as c:
        for i, row in enumerate(rows):
            c.execute(
                text(f"""
                    INSERT INTO {schema}.fact_checks
                        (article_id, claim, verdict, evidence, checker,
                         analyzed_by, claims, overall_verdict, analysis_tier)
                    VALUES (:article_id, :claim, :verdict, :evidence,
                            'V.E.R.I.F.Y.', 'V.E.R.I.F.Y.',
                            CAST(:claims AS JSONB), :overall, :tier)
                """),
                {
                    "article_id": article_id,
                    "claim": row["claim"],
                    "verdict": row["verdict"],
                    "evidence": row["evidence"],
                    "claims": claims_json if i == 0 else None,
                    "overall": overall,
                    "tier": analysis_tier,
                },
            )


def run_backlog(engine, schema: str = "wtf") -> dict:
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "stopped": "disabled"}

    processed = 0
    rate_limited = 0
    failed = 0
    while processed + rate_limited + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "rate_limited": rate_limited,
                    "failed": failed, "stopped": "no_backlog"}

        for article in batch:
            if processed + rate_limited + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "rate_limited": rate_limited,
                        "failed": failed, "stopped": "max_runs"}

            outcome = tier_router.analyze_factcheck_tiered(
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
                # Skip persist; hub will be ready next cycle (#2944).
                rate_limited += 1
            elif status == "failed":
                failed += 1
                logger.warning(
                    "[factcheck_backlog] article=%s dispatch failed (tier=%s)",
                    article["id"],
                    tier_meta.get("analysis_tier", "pending"),
                )
            else:
                try:
                    _persist(engine, schema, article["id"], outcome["result"],
                             analysis_tier=tier_meta.get("analysis_tier"))
                    _update_article_tier(engine, schema, article["id"], tier_meta)
                    processed += 1
                    logger.info(
                        "[factcheck_backlog] article=%s persisted tier=%s gate=%s tier2=%s",
                        article["id"],
                        tier_meta.get("analysis_tier"),
                        tier_meta.get("gate_reason"),
                        tier_meta.get("tier2_status"),
                    )
                except Exception as exc:
                    failed += 1
                    logger.exception("[factcheck_backlog] article=%s persist failed: %s", article["id"], exc)
            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "rate_limited": rate_limited,
            "failed": failed, "stopped": "max_runs"}
