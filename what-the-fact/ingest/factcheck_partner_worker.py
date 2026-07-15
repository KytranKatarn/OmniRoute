"""factcheck_partner_worker.py — Google Fact Check Tools API integration (#2137).

Queries FCTAPI for each AI-analyzed article, writes results to wtf.fact_checks
with checker='GoogleFCT:<publisher>' for attribution alongside V.E.R.I.F.Y.

Articles with no FCTAPI results get a sentinel row (checker='GoogleFCT:none')
so they are not re-queried every cycle.

RELEVANCE GATE (#2137, 2026-07-15) — two stages, because FCTAPI keyword-matches
by title and readily returns a review of a DIFFERENT claim that merely shares a
name (a Snopes check of "Trump's Easter message" attached to a Strait-of-Hormuz
article). A false third-party verdict on a fact-checking site is worse than none.
  Stage 1 (deterministic, free): the candidate claim must share at least
    _MIN_DISTINCTIVE distinctive tokens with the article (not just a lone common
    name like "Trump"/"Canada"). Kills the pure name-collision junk with no LLM.
  Stage 2 (LLM judge): survivors are judged by the hub `factcheck_relevance`
    task (small News model) — "does this fact-check assess a claim THIS article
    makes?". Honors the hub's retry_after; if the hub is unavailable the article
    is DEFERRED (nothing persisted, retried next cycle) — never a shown-but-
    unjudged match.

Default OFF. Set WTF_FACTCHECK_PARTNER_ENABLED=true + WTF_FCTAPI_KEY=<key>.
Key: reuse GEMINI_API_KEY (same Google Cloud project, Fact Check Tools API must
be enabled at console.cloud.google.com).
"""
from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse
import urllib.request

from sqlalchemy import text

from .ai_dispatcher import analyze_with_status

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_FACTCHECK_PARTNER_ENABLED", "false").lower() == "true"
_API_KEY = os.environ.get("WTF_FCTAPI_KEY") or os.environ.get("GEMINI_API_KEY", "")
_BATCH_SIZE = int(os.environ.get("WTF_FCTAPI_BATCH_SIZE", "25"))
_MAX_PER_RUN = int(os.environ.get("WTF_FCTAPI_MAX_PER_RUN", "500"))
_SLEEP_SEC = float(os.environ.get("WTF_FCTAPI_SLEEP_SEC", "1"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_FCTAPI_MAX_AGE_DAYS", "30"))
_FCTAPI_BASE = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

# Relevance gate tunables.
_RELEVANCE_LLM = os.environ.get("WTF_FCTAPI_RELEVANCE_LLM", "true").lower() == "true"
# Stage 1 is a cheap junk filter (require >= this many distinctive shared tokens);
# stage 2 (the LLM) does the real precision judgment on survivors.
_MIN_DISTINCTIVE = int(os.environ.get("WTF_FCTAPI_MIN_DISTINCTIVE", "1"))
_MAX_RELEVANCE_ATTEMPTS = int(os.environ.get("WTF_FCTAPI_RELEVANCE_ATTEMPTS", "4"))

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

# Tokens ignored entirely when measuring overlap.
_STOPWORDS = frozenset(
    "the a an and or but of to in on at for with from by as is are was were be "
    "been being this that these those it its his her their our your they them he "
    "she we you not no do does did has have had will would can could may might "
    "about into over after before under more most than then out up off".split()
)
# Shared tokens that are NOT distinctive — a match on these alone is a name/topic
# collision, not evidence the fact-check is about the same story.
_COMMON = frozenset(
    "trump biden trudeau carney poilievre canada canadian us usa american america "
    "ottawa toronto quebec ontario says said say report reports reported new news "
    "government minister pm president prime state states world people year years "
    "day days claim claims video photo image post posts social media online "
    "official officials country countries national federal".split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9']{2,}")


def _map_verdict(rating: str) -> str:
    """Map FCTAPI free-text rating to wtf.fact_checks verdict enum."""
    r = (rating or "").lower().strip()
    for keyword, verdict in _VERDICT_MAP:
        if keyword in r:
            return verdict
    return "unverified"


def _tokens(s: str) -> set[str]:
    """Meaningful lowercase tokens of a string (>=3 chars, minus stopwords)."""
    return {t for t in _TOKEN_RE.findall((s or "").lower()) if t not in _STOPWORDS}


def _distinctive_overlap_ok(claim: str, article_text: str) -> bool:
    """Stage 1: keep only if the claim shares >= _MIN_DISTINCTIVE distinctive
    tokens with the article (shared tokens that are not lone common names)."""
    shared = _tokens(claim) & _tokens(article_text)
    distinctive = shared - _COMMON
    return len(distinctive) >= _MIN_DISTINCTIVE


def _llm_relevant(article_id: int, title: str, claim: str) -> bool | None:
    """Stage 2: hub judges whether the fact-check assesses a claim THIS article
    makes. Returns True (relevant), False (not relevant / unjudgeable → drop the
    candidate), or None (hub busy/unreachable → DEFER the whole article)."""
    for _attempt in range(_MAX_RELEVANCE_ATTEMPTS):
        res = analyze_with_status(
            task="factcheck_relevance",
            article_id=article_id,
            title=title or "",
            body=claim or "",       # the hub prompt reads `body` as the claim text
            source_slug="",
        )
        status = res.get("status")
        if status == "ok":
            result = res.get("result")
            if isinstance(result, dict) and "relevant" in result:
                return bool(result.get("relevant"))
            # Parsed but no verdict → don't show it, don't block the article.
            return False
        if status == "rate_limited":
            wait = max(1, min(int(res.get("retry_after") or 5), 30))
            time.sleep(wait)
            continue
        # Hard dispatch/network failure — transient; defer and retry next cycle.
        return None
    return None  # rate-limited past the attempt budget → defer


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
            SELECT a.id, a.title, LEFT(a.body, 1500) AS body
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


def _persist_sentinel(engine, schema: str, article_id: int) -> None:
    """Mark an article checked-with-no-relevant-match so it is not re-queried."""
    with engine.begin() as c:
        c.execute(text(f"""
            INSERT INTO {schema}.fact_checks
                (article_id, claim, verdict, evidence, checker, checked_at, analyzed_by)
            VALUES (:article_id, '', 'unverified', '', 'GoogleFCT:none', NOW(), 'partner')
        """), {"article_id": article_id})


def _persist(engine, schema: str, article_id: int, results: list[dict]) -> None:
    """Write relevance-gated FCTAPI matches to fact_checks."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    with engine.begin() as c:
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


def _gate_candidates(engine, article: dict) -> tuple[list[dict], bool]:
    """Run FCTAPI candidates through stage 1 + stage 2. Returns
    (kept_matches, deferred). deferred=True means the hub was unavailable and
    the article should be retried next cycle (persist nothing)."""
    candidates = _query_fctapi(article["title"] or "")
    if not candidates:
        return [], False
    article_text = f"{article.get('title') or ''} {article.get('body') or ''}"

    # Stage 1 — deterministic distinctive-overlap filter.
    survivors = [c for c in candidates if _distinctive_overlap_ok(c["claim"], article_text)]
    if not survivors:
        return [], False  # confidently no relevant match → sentinel upstream

    if not _RELEVANCE_LLM:
        return survivors, False  # stage-1-only mode (LLM judge disabled)

    # Stage 2 — LLM relevance judge on survivors.
    kept: list[dict] = []
    for c in survivors:
        verdict = _llm_relevant(article["id"], article["title"] or "", c["claim"])
        if verdict is None:
            return [], True  # hub busy — defer the whole article
        if verdict:
            kept.append(c)
    return kept, False


def run_partner_check(engine, schema: str = "wtf") -> dict:
    """One pass: fetch batch, query FCTAPI, relevance-gate, persist. Returns counters."""
    if not _ENABLED:
        return {"processed": 0, "matched": 0, "errors": 0, "stopped": "disabled"}
    if not _API_KEY:
        logger.warning("[fctapi] WTF_FCTAPI_KEY not configured — worker disabled")
        return {"processed": 0, "matched": 0, "errors": 0, "stopped": "no_api_key"}

    processed = 0
    matched = 0
    errors = 0
    deferred = 0

    while processed + errors < _MAX_PER_RUN:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "matched": matched, "errors": errors,
                    "deferred": deferred, "stopped": "no_backlog"}

        for article in batch:
            if processed + errors >= _MAX_PER_RUN:
                return {"processed": processed, "matched": matched, "errors": errors,
                        "deferred": deferred, "stopped": "max_runs"}
            try:
                kept, is_deferred = _gate_candidates(engine, article)
                if is_deferred:
                    # Hub saturated — yield the run; done articles stay persisted,
                    # this one is retried next cycle (no sentinel written).
                    deferred += 1
                    return {"processed": processed, "matched": matched, "errors": errors,
                            "deferred": deferred, "stopped": "deferred_llm"}
                if kept:
                    _persist(engine, schema, article["id"], kept)
                    matched += 1
                    logger.info("[fctapi] article=%s kept %d relevant match(es)",
                                article["id"], len(kept))
                else:
                    _persist_sentinel(engine, schema, article["id"])
                processed += 1
            except Exception as exc:
                errors += 1
                logger.exception("[fctapi] article=%s failed: %s", article["id"], exc)
            time.sleep(_SLEEP_SEC)

    return {"processed": processed, "matched": matched, "errors": errors,
            "deferred": deferred, "stopped": "max_runs"}
