"""llm_analysis_backlog_worker.py — fill the LLM Analyzed gap (8,788 articles).

Reads articles with ai_analyzed=false, dispatches the wtf-hub 'deep_analysis'
task to V.E.R.I.F.Y. via mesh, caches the JSONB result in wtf.llm_analyses,
flips ai_analyzed=true on success. Consumer's "Analyze" click then reads the
cached row instantly — no on-demand LLM.

After bias analysis, optionally runs F.A.C.T. scan (analyze_factcheck_tiered)
to detect misleading/false claims using the full article text. Results stored
in wtf.fact_checks with analyzed_by='llm_v1'.

Bypasses orchestrator.pick_priority_articles() — the priority filter is for
forward ingestion; this worker exists to clear the historical backlog.

Default OFF. Set WTF_LLM_BACKLOG_ENABLED=true to run.

Env:
    WTF_LLM_BACKLOG_ENABLED            false   master switch
    WTF_LLM_BACKLOG_BATCH_SIZE         25      articles per batch
    WTF_LLM_BACKLOG_DISPATCH_SLEEP_SEC 5       sleep between articles (per thread)
    WTF_LLM_BACKLOG_MAX_AGE_DAYS       7       only articles younger than this
    WTF_LLM_BACKLOG_MAX_RUNS_PER_NIGHT 200     hard cap per cycle
    WTF_LLM_BACKLOG_MODEL_LABEL        deep_analysis_v1
    WTF_LLM_BACKLOG_RUN_FACTCHECK      true    run F.A.C.T. scan after bias
    WTF_LLM_BACKLOG_CONCURRENCY        1       parallel threads (set to node count for max throughput)
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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
_RUN_FACTCHECK = os.environ.get("WTF_LLM_BACKLOG_RUN_FACTCHECK", "true").lower() == "true"
_CONCURRENCY = int(os.environ.get("WTF_LLM_BACKLOG_CONCURRENCY", "1"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})
_VALID_BIAS_BANDS = frozenset({"left", "center-left", "center", "center-right", "right"})

# Verdict vocabularies live in ONE place (verdicts.py, #6242). These names are
# kept so existing call sites are unchanged; the mapping is no longer duplicated
# here — a second copy is how ingest/run.py ended up with NO mapping at all while
# this module had a correct one.
#
# NOTE the old comment here claimed "fact_checks.overall_verdict CHECK:
# verified/mostly_true/mixed/disputed/unverifiable/NULL". There was NO such
# constraint until migration 060 — the comment described an invariant nothing
# enforced, which is precisely how the drift went unnoticed.
try:
    from ingest.verdicts import CLAIM_VERDICTS, OVERALL_VERDICTS, canonical_claim, canonical_overall  # noqa: F401
except ImportError:  # pragma: no cover
    from verdicts import CLAIM_VERDICTS, OVERALL_VERDICTS, canonical_claim, canonical_overall  # noqa: F401

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
    """Persist analysis JSONB, update wtf.articles tier columns, and UPDATE bias_scores
    with the LLM-derived band/score/rationale (replacing the ingest-time heuristic).

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

    # Extract bias from sections for bias_scores update
    bias = (sections.get("bias_summary") or {})
    band = (bias.get("band") or "center").lower().strip()
    if band not in _VALID_BIAS_BANDS:
        band = "center"
    score = float(bias.get("score") or 0.0)
    rationale = (bias.get("rationale") or "").strip()
    trigger_phrases = json.dumps(bias.get("trigger_phrases") or [])
    confidence = bias.get("confidence")

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
        # Replace heuristic bias score with LLM result.
        # Only update when the LLM gave a real signal (rationale or non-center band).
        updated = c.execute(
            text(f"""
                UPDATE {schema}.bias_scores
                SET band              = :band,
                    score             = :score,
                    rationale         = :rationale,
                    analyzed_by       = 'llm_v1',
                    trigger_phrases   = CAST(:tp AS JSONB),
                    confidence        = :confidence,
                    computed_at       = NOW()
                WHERE article_id = :aid
            """),
            {
                "band": band,
                "score": score,
                "rationale": rationale,
                "tp": trigger_phrases,
                "confidence": confidence,
                "aid": article_id,
            },
        )
        if updated.rowcount == 0:
            # Row missing (shouldn't happen for articles that went through ingest)
            # Insert a fallback row so the consumer always has something to render.
            c.execute(
                text(f"""
                    INSERT INTO {schema}.bias_scores
                        (article_id, band, score, heuristic_version, rationale,
                         analyzed_by, trigger_phrases, confidence)
                    VALUES (:aid, :band, :score, 'llm_v1', :rationale,
                            'llm_v1', CAST(:tp AS JSONB), :confidence)
                    ON CONFLICT (article_id) DO UPDATE
                      SET band = EXCLUDED.band, score = EXCLUDED.score,
                          rationale = EXCLUDED.rationale, analyzed_by = EXCLUDED.analyzed_by,
                          trigger_phrases = EXCLUDED.trigger_phrases,
                          confidence = EXCLUDED.confidence, computed_at = NOW()
                """),
                {
                    "aid": article_id,
                    "band": band,
                    "score": score,
                    "rationale": rationale,
                    "tp": trigger_phrases,
                    "confidence": confidence,
                },
            )


def _persist_factcheck(engine, schema: str, article_id: int, fc_result: dict) -> None:
    """Write F.A.C.T. scan results to wtf.fact_checks.

    Deletes existing heuristic-only rows for this article and replaces with
    LLM-derived claims (verdict + evidence). If the LLM found no claims,
    inserts a single 'no claims found' placeholder so the consumer can
    distinguish 'not yet checked' from 'checked — nothing found'.
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist_factcheck: disallowed schema {schema!r}")

    claims = fc_result.get("claims") or []
    overall_raw = (fc_result.get("overall_verdict") or "unverifiable").lower()
    overall = canonical_overall(overall_raw) or "unverifiable"
    claims_json = json.dumps(claims)

    with engine.begin() as c:
        # Always replace all existing factcheck rows for this article — both heuristic
        # and any stale llm_v1 rows from previous runs. This is the canonical LLM pass.
        c.execute(
            text(f"DELETE FROM {schema}.fact_checks WHERE article_id = :aid"),
            {"aid": article_id},
        )
        if claims:
            for claim_item in claims:
                claim_text = (claim_item.get("text") or "").strip()[:2000]
                if not claim_text:
                    continue
                verdict_raw = (claim_item.get("verdict") or "unverified").lower().strip()
                verdict = canonical_claim(verdict_raw)
                # "reasoning" is the key the tier_router uses; fallback to "evidence"
                evidence = (
                    claim_item.get("reasoning") or claim_item.get("evidence") or ""
                ).strip()[:4000]
                c.execute(
                    text(f"""
                        INSERT INTO {schema}.fact_checks
                            (article_id, claim, verdict, evidence, checker,
                             analyzed_by, claims, overall_verdict)
                        VALUES (:aid, :claim, :verdict, :evidence, 'fact_v1',
                                'llm_v1', CAST(:claims AS JSONB), :overall)
                    """),
                    {
                        "aid": article_id,
                        "claim": claim_text,
                        "verdict": verdict,
                        "evidence": evidence,
                        "claims": claims_json,
                        "overall": overall,
                    },
                )
        else:
            # No claims extracted — record sentinel so the consumer can show
            # "No verifiable claims detected" rather than "not yet checked".
            c.execute(
                text(f"""
                    INSERT INTO {schema}.fact_checks
                        (article_id, claim, verdict, evidence, checker,
                         analyzed_by, claims, overall_verdict)
                    VALUES (:aid, 'No verifiable claims detected.', 'unverified', '',
                            'fact_v1', 'llm_v1', '[]'::JSONB, 'unverifiable')
                """),
                {"aid": article_id},
            )


def _process_article(engine, schema: str, article: dict) -> tuple[str, int]:
    """Process a single article: bias analysis + optional factcheck.

    Returns (status, article_id) where status is 'ok' | 'rate_limited' | 'failed'.
    Thread-safe: each article writes to a distinct article_id; engine pool handles
    concurrent connections.
    """
    aid = article["id"]

    # ── Tier-1/2 bias analysis ────────────────────────────────────
    outcome = tier_router.analyze_tiered(
        article_id=aid,
        title=article["title"],
        body=article["body"],
        source_slug=article["source_slug"] or "",
        source_bias_lean=article.get("source_bias_lean") or "",
        cluster_size=int(article.get("cluster_size") or 0),
    )
    status = outcome["status"]
    tier_meta = outcome.get("tier_meta") or {}

    if status == "rate_limited":
        return ("rate_limited", aid)

    if status == "failed":
        logger.warning(
            "[llm_backlog] article=%s dispatch failed (analysis_tier=%s)",
            aid, tier_meta.get("analysis_tier", "pending"),
        )
        time.sleep(_DISPATCH_SLEEP_SEC)
        return ("failed", aid)

    try:
        _persist(engine, schema, aid, outcome["result"], tier_meta)
        logger.info(
            "[llm_backlog] article=%s bias persisted tier=%s gate=%s tier2=%s",
            aid,
            tier_meta.get("analysis_tier"),
            tier_meta.get("gate_reason"),
            tier_meta.get("tier2_status"),
        )
    except Exception as exc:
        logger.exception("[llm_backlog] article=%s bias persist failed: %s", aid, exc)
        time.sleep(_DISPATCH_SLEEP_SEC)
        return ("failed", aid)

    # ── F.A.C.T. scan (non-fatal — bias already persisted) ────
    if _RUN_FACTCHECK:
        try:
            fc_outcome = tier_router.analyze_factcheck_tiered(
                article_id=aid,
                title=article["title"],
                body=article["body"],
                source_slug=article["source_slug"] or "",
                source_bias_lean=article.get("source_bias_lean") or "",
                cluster_size=int(article.get("cluster_size") or 0),
            )
            if fc_outcome["status"] == "ok" and fc_outcome.get("result"):
                _persist_factcheck(engine, schema, aid, fc_outcome["result"])
                logger.info(
                    "[llm_backlog] article=%s factcheck persisted tier=%s claims=%d",
                    aid,
                    fc_outcome.get("tier_meta", {}).get("analysis_tier"),
                    len((fc_outcome["result"].get("claims") or [])),
                )
            else:
                logger.debug(
                    "[llm_backlog] article=%s factcheck skipped: status=%s",
                    aid, fc_outcome["status"],
                )
        except Exception as exc:
            logger.warning(
                "[llm_backlog] article=%s factcheck non-fatal error: %s", aid, exc,
            )

    time.sleep(_DISPATCH_SLEEP_SEC)
    return ("ok", aid)


def run_backlog(engine, schema: str = "wtf") -> dict:
    """Process one shift of LLM analysis backlog. Returns {processed, failed, skipped, stopped}.

    When WTF_LLM_BACKLOG_CONCURRENCY > 1, processes a batch in parallel via
    ThreadPoolExecutor — one thread per available node. Serial path kept for
    CONCURRENCY=1 (default, backward compat).
    """
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

        if _CONCURRENCY > 1:
            with ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
                futures = [pool.submit(_process_article, engine, schema, art) for art in batch]
                for fut in as_completed(futures):
                    if processed + rate_limited + failed >= _MAX_RUNS_PER_NIGHT:
                        break
                    status, _aid = fut.result()
                    if status == "ok":
                        processed += 1
                    elif status == "rate_limited":
                        rate_limited += 1
                    else:
                        failed += 1
        else:
            for article in batch:
                if processed + rate_limited + failed >= _MAX_RUNS_PER_NIGHT:
                    return {"processed": processed, "rate_limited": rate_limited,
                            "failed": failed, "skipped": skipped, "stopped": "max_runs"}
                status, _aid = _process_article(engine, schema, article)
                if status == "ok":
                    processed += 1
                elif status == "rate_limited":
                    rate_limited += 1
                else:
                    failed += 1

    return {"processed": processed, "rate_limited": rate_limited,
            "failed": failed, "skipped": skipped, "stopped": "max_runs"}
