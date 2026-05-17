"""factcheck_partner_worker.py — Google Fact Check Tools API integration (#2137).

Queries FCTAPI for each AI-analyzed article, writes results to wtf.fact_checks
with checker='GoogleFCT:<publisher>' for attribution alongside V.E.R.I.F.Y.

Articles with no FCTAPI results get a sentinel row (checker='GoogleFCT:none')
so they are not re-queried every cycle.

Default OFF. Set WTF_FACTCHECK_PARTNER_ENABLED=true + WTF_FCTAPI_KEY=<key>.
Key: reuse GEMINI_API_KEY (same Google Cloud project, Fact Check Tools API must
be enabled at console.cloud.google.com).
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse
import urllib.request

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_FACTCHECK_PARTNER_ENABLED", "false").lower() == "true"
_API_KEY = os.environ.get("WTF_FCTAPI_KEY") or os.environ.get("GEMINI_API_KEY", "")
_BATCH_SIZE = int(os.environ.get("WTF_FCTAPI_BATCH_SIZE", "25"))
_MAX_PER_RUN = int(os.environ.get("WTF_FCTAPI_MAX_PER_RUN", "500"))
_SLEEP_SEC = float(os.environ.get("WTF_FCTAPI_SLEEP_SEC", "1"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_FCTAPI_MAX_AGE_DAYS", "30"))
_FCTAPI_BASE = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

_ALLOWED_SCHEMAS = frozenset({"wtf"})

# Maps free-text FCTAPI ratings to wtf.fact_checks CHECK constraint values.
# FCTAPI ratings are per-org free text — match by keyword, longest first.
_VERDICT_MAP = [
    ("mostly true",   "mostly_true"),
    ("mostly false",  "false"),
    ("half true",     "mixed"),
    ("half-true",     "mixed"),
    ("pants on fire", "false"),
    ("fabricated",    "false"),
    ("incorrect",     "false"),
    ("misleading",    "mixed"),
    ("mixture",       "mixed"),
    ("accurate",      "true"),
    ("correct",       "true"),
    ("true",          "true"),
    ("false",         "false"),
]


def _map_verdict(rating: str) -> str:
    """Map FCTAPI free-text rating to wtf.fact_checks verdict enum."""
    r = (rating or "").lower().strip()
    for keyword, verdict in _VERDICT_MAP:
        if keyword in r:
            return verdict
    return "unverified"


def _query_fctapi(title: str) -> list[dict]:
    """Query FCTAPI for claims matching article title.
    Returns list of {claim, verdict, evidence, publisher}.
    Returns [] on no results or API error.
    """
    if not _API_KEY:
        logger.warning("[fctapi] WTF_FCTAPI_KEY not set — skipping")
        return []
    params = urllib.parse.urlencode({
        "query": title[:200],
        "languageCode": "en",
        "pageSize": 5,
        "key": _API_KEY,
    })
    url = f"{_FCTAPI_BASE}?{params}"
    try:
        import json
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
    except Exception as exc:
        logger.warning("[fctapi] HTTP error: %s", exc)
        return []

    results = []
    for claim in (data.get("claims") or []):
        text_content = claim.get("text") or ""
        for review in (claim.get("claimReview") or []):
            publisher = (review.get("publisher") or {}).get("name") or "unknown"
            rating = review.get("textualRating") or ""
            review_url = review.get("url") or ""
            results.append({
                "claim": text_content[:500],
                "verdict": _map_verdict(rating),
                "evidence": review_url[:1000],
                "publisher": publisher[:50],
            })
    return results


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    """Articles that are AI-analyzed but have no GoogleFCT row yet."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title
            FROM {schema}.articles a
            WHERE a.ai_analyzed = TRUE
              AND a.published_at > NOW() - make_interval(days => :max_age_days)
              AND NOT EXISTS (
                  SELECT 1 FROM {schema}.fact_checks fc
                  WHERE fc.article_id = a.id
                    AND fc.checker LIKE 'GoogleFCT%'
              )
            ORDER BY a.published_at DESC
            LIMIT :limit
        """), {"max_age_days": _MAX_AGE_DAYS, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _persist(engine, schema: str, article_id: int, results: list[dict]) -> None:
    """Write FCTAPI results (or sentinel) to fact_checks."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    with engine.begin() as c:
        if not results:
            # Sentinel — marks article as checked, prevents re-query
            c.execute(text(f"""
                INSERT INTO {schema}.fact_checks
                    (article_id, claim, verdict, evidence, checker, checked_at, analyzed_by)
                VALUES (:article_id, '', 'unverified', '', 'GoogleFCT:none', NOW(), 'partner')
            """), {"article_id": article_id})
        else:
            for r in results:
                checker = f"GoogleFCT:{r['publisher']}"
                c.execute(text(f"""
                    INSERT INTO {schema}.fact_checks
                        (article_id, claim, verdict, evidence, checker, checked_at, analyzed_by)
                    VALUES (:article_id, :claim, :verdict, :evidence, :checker, NOW(), 'partner')
                """), {
                    "article_id": article_id,
                    "claim": r["claim"],
                    "verdict": r["verdict"],
                    "evidence": r["evidence"],
                    "checker": checker[:64],
                })


def run_partner_check(engine, schema: str = "wtf") -> dict:
    """One pass: fetch batch, query FCTAPI, persist results. Returns counters."""
    if not _ENABLED:
        return {"processed": 0, "matched": 0, "errors": 0, "stopped": "disabled"}
    if not _API_KEY:
        logger.warning("[fctapi] WTF_FCTAPI_KEY not configured — worker disabled")
        return {"processed": 0, "matched": 0, "errors": 0, "stopped": "no_api_key"}

    processed = 0
    matched = 0
    errors = 0

    while processed + errors < _MAX_PER_RUN:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "matched": matched,
                    "errors": errors, "stopped": "no_backlog"}

        for article in batch:
            if processed + errors >= _MAX_PER_RUN:
                return {"processed": processed, "matched": matched,
                        "errors": errors, "stopped": "max_runs"}
            try:
                results = _query_fctapi(article["title"] or "")
                _persist(engine, schema, article["id"], results)
                processed += 1
                if results:
                    matched += 1
                    logger.info("[fctapi] article=%s matched %d claim(s)", article["id"], len(results))
            except Exception as exc:
                errors += 1
                logger.exception("[fctapi] article=%s failed: %s", article["id"], exc)
            time.sleep(_SLEEP_SEC)

    return {"processed": processed, "matched": matched, "errors": errors, "stopped": "max_runs"}
