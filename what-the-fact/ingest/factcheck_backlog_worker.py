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

# LLM returns verdicts per the wtf-hub prompt: verified|mixed|disputed|unverifiable
# wtf.fact_checks.verdict CHECK constraint allows: true|mostly_true|mixed|false|unverified
_VERDICT_MAP = {
    "verified": "true",
    "true": "true",
    "mostly true": "mostly_true",
    "mostly_true": "mostly_true",
    "partly true": "mixed",
    "mixed": "mixed",
    "disputed": "mixed",
    "misleading": "false",
    "false": "false",
    "unverified": "unverified",
    "unverifiable": "unverified",
}


def _normalize_verdict(raw) -> str:
    return _VERDICT_MAP.get((raw or "").strip().lower(), "unverified")


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
    """Persist V.E.R.I.F.Y. fact-check result into wtf.fact_checks.

    Schema reality: NOT NULL columns are (article_id, claim, verdict, evidence,
    checker, checked_at). Nullable JSONB columns (claims, overall_verdict) hold
    the aggregate. Matches the forward heuristic pipeline (one row per claim).

    If the LLM returned no claims, writes a single placeholder row so the
    article won't be re-fetched on the next cycle (NOT EXISTS filter).
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    claims = result.get("claims") or []
    overall = _normalize_verdict(result.get("overall_verdict"))
    claims_json = json.dumps(claims)

    if not claims:
        rows = [{
            "claim": "(no factual claims extracted)",
            "verdict": overall,
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
                         analyzed_by, claims, overall_verdict)
                    VALUES (:article_id, :claim, :verdict, :evidence,
                            'V.E.R.I.F.Y.', 'V.E.R.I.F.Y.',
                            CAST(:claims AS JSONB), :overall)
                """),
                {
                    "article_id": article_id,
                    "claim": row["claim"],
                    "verdict": row["verdict"],
                    "evidence": row["evidence"],
                    "claims": claims_json if i == 0 else None,
                    "overall": overall,
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

            outcome = ai_dispatcher.analyze_with_status(
                task="factcheck",
                article_id=article["id"],
                title=article["title"],
                body=article["body"],
                source_slug=article["source_slug"] or "",
            )
            status = outcome["status"]
            if status == "rate_limited":
                # Skip persist; hub will be ready next cycle (#2944).
                rate_limited += 1
            elif status == "failed":
                failed += 1
            else:
                try:
                    _persist(engine, schema, article["id"], outcome["result"])
                    processed += 1
                except Exception as exc:
                    failed += 1
                    logger.exception("[factcheck_backlog] article=%s persist failed: %s", article["id"], exc)
            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "rate_limited": rate_limited,
            "failed": failed, "stopped": "max_runs"}
