"""scout_body_backlog_worker.py — rescue article bodies via S.C.O.U.T. browser fleet.

Google News RSS fallbacks (toronto_star, la_presse, the_tyee, bnn_bloomberg)
return ~150-char snippets, not full bodies. This worker dispatches S.C.O.U.T.
(agent #364, archie_scraper Playwright container) to fetch the actual article
URL and extract the full body, then re-enqueues the article for LLM analysis.

Per Kytran 2026-05-17: do NOT build parallel scraping infra. S.C.O.U.T. owns
browser fetch via DHQ. This worker is a thin dispatch + persist layer.

Default OFF — set WTF_SCOUT_BODY_BACKLOG_ENABLED=true to activate.

Env:
    WTF_SCOUT_BODY_BACKLOG_ENABLED       false   master switch
    WTF_HUB_URL                          http://100.64.0.4:3000  mesh, never public
    CLUSTER_PROXY_KEY                    (required)  X-Scout-Key header
    WTF_SCOUT_BODY_BATCH_SIZE            10      articles per fetch_batch call
    WTF_SCOUT_BODY_MAX_RUNS_PER_NIGHT    50      hard cap per cycle
    WTF_SCOUT_BODY_POLL_MAX_SEC          90      give up on a single job after this
    WTF_SCOUT_BODY_POLL_INTERVAL_SEC     5       poll cadence
    WTF_SCOUT_BODY_MIN_BODY_CHARS        300     articles below this length are eligible
    WTF_SCOUT_BODY_MIN_RESCUE_CHARS      400     rescued body must beat this to commit
    WTF_SCOUT_BODY_DISPATCH_SLEEP_SEC    2       sleep between dispatches (politeness)

Eligible sources (Google-News fallback only):
    toronto_star, la_presse, the_tyee, bnn_bloomberg

Hard limits: failed/timeout articles are NOT auto-retried — they stay in
wtf.scout_body_jobs and need manual reset (UPDATE status='pending' or DELETE).
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_SCOUT_BODY_BACKLOG_ENABLED", "false").lower() == "true"
_HUB_URL = os.environ.get("WTF_HUB_URL", "http://100.64.0.4:3000").rstrip("/")
_SCOUT_KEY = os.environ.get("CLUSTER_PROXY_KEY", "")
_BATCH_SIZE = int(os.environ.get("WTF_SCOUT_BODY_BATCH_SIZE", "10"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_SCOUT_BODY_MAX_RUNS_PER_NIGHT", "50"))
_POLL_MAX_SEC = int(os.environ.get("WTF_SCOUT_BODY_POLL_MAX_SEC", "90"))
_POLL_INTERVAL_SEC = int(os.environ.get("WTF_SCOUT_BODY_POLL_INTERVAL_SEC", "5"))
_MIN_BODY_CHARS = int(os.environ.get("WTF_SCOUT_BODY_MIN_BODY_CHARS", "300"))
_MIN_RESCUE_CHARS = int(os.environ.get("WTF_SCOUT_BODY_MIN_RESCUE_CHARS", "400"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_SCOUT_BODY_DISPATCH_SLEEP_SEC", "2"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})

# Sources that route through Google News RSS — bodies are snippets, not full text.
# Keep aligned with what's in ingest/sources/*.py using news.google.com/rss/search.
_GOOGLE_NEWS_SOURCES = (
    "toronto_star",
    "la_presse",
    "the_tyee",
    "bnn_bloomberg",
)

# CSS selector chain covering most Canadian news templates. S.C.O.U.T. extracts
# each independently — the worker picks whichever returns the longest text.
_SELECTORS = {
    "article_tag": "article",
    "schema_body": "[itemprop='articleBody']",
    "article_body_class": ".article-body, .article__body, .articleBody",
    "story_body_class": ".story-body, .story__body, .StoryBodyCompanionColumn",
    "main_content": "main",
}


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    """Pull articles eligible for body rescue: short body, Google-News source, untried."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT a.id, a.url, a.title, s.slug AS source_slug, LENGTH(a.body) AS body_len
                FROM {schema}.articles a
                JOIN {schema}.sources s ON s.id = a.source_id
                WHERE s.slug = ANY(:sources)
                  AND LENGTH(a.body) < :min_chars
                  AND NOT EXISTS (
                      SELECT 1 FROM {schema}.scout_body_jobs j WHERE j.article_id = a.id
                  )
                ORDER BY a.ingested_at DESC
                LIMIT :limit
            """),
            {
                "sources": list(_GOOGLE_NEWS_SOURCES),
                "min_chars": _MIN_BODY_CHARS,
                "limit": limit,
            },
        ).mappings().all()
    return [dict(r) for r in rows]


def _dispatch_scout(url: str) -> tuple[int | None, str | None]:
    """POST to DHQ scout cli-dispatch. Returns (scout_job_id, error)."""
    if not _SCOUT_KEY:
        return None, "CLUSTER_PROXY_KEY env not set"
    payload = json.dumps({
        "job_type": "web_scrape",
        "target_url": url,
        "params": {"selectors": _SELECTORS, "max_items": 1},
    }).encode()
    req = urllib.request.Request(f"{_HUB_URL}/tools/department-hq/api/scout/cli-dispatch", data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Scout-Key", _SCOUT_KEY)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read())
        job_id = body.get("job_id")
        if job_id is None:
            return None, f"no job_id in response: {body!r}"
        return int(job_id), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _poll_scout(job_id: int) -> tuple[dict | None, str | None]:
    """Poll scout cli-status until done or timeout. Returns (job_row, error)."""
    deadline = time.time() + _POLL_MAX_SEC
    while time.time() < deadline:
        req = urllib.request.Request(f"{_HUB_URL}/tools/department-hq/api/scout/cli-status/{job_id}")
        req.add_header("X-Scout-Key", _SCOUT_KEY)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                row = json.loads(r.read())
            status = (row.get("status") or "").lower()
            if status in ("pending", "running", "queued"):
                time.sleep(_POLL_INTERVAL_SEC)
                continue
            return row, None
        except Exception as e:
            return None, f"poll {type(e).__name__}: {e}"
    return None, "timeout"


def _pick_longest_body(data: dict) -> str:
    """data is {selector_field: [str, ...]} — return the longest single string."""
    best = ""
    for v in (data or {}).values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and len(item) > len(best):
                    best = item
        elif isinstance(v, str) and len(v) > len(best):
            best = v
    return best.strip()


def _persist_success(engine, schema: str, article_id: int, scout_job_id: int,
                     body_before: int, new_body: str) -> None:
    """Update article body, clear ai_analyzed flags, log success."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist_success: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(
            text(f"""
                UPDATE {schema}.articles
                SET body = :body,
                    ai_analyzed = false,
                    ai_analyzed_at = NULL
                WHERE id = :aid
            """),
            {"body": new_body, "aid": article_id},
        )
        c.execute(
            text(f"""
                INSERT INTO {schema}.scout_body_jobs
                    (article_id, scout_job_id, status, body_before, body_after, completed_at)
                VALUES (:aid, :jid, 'completed', :before, :after, NOW())
            """),
            {"aid": article_id, "jid": scout_job_id,
             "before": body_before, "after": len(new_body)},
        )


def _persist_failure(engine, schema: str, article_id: int,
                     scout_job_id: int | None, body_before: int,
                     status: str, error: str) -> None:
    """Record failed/timeout/short-rescue so the article isn't tried again next cycle."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist_failure: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(
            text(f"""
                INSERT INTO {schema}.scout_body_jobs
                    (article_id, scout_job_id, status, body_before, error, completed_at)
                VALUES (:aid, :jid, :status, :before, :err, NOW())
            """),
            {"aid": article_id, "jid": scout_job_id, "status": status,
             "before": body_before, "err": error[:500]},
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    """Main entry — called once per ingest cycle from run.py."""
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "stopped": "disabled"}
    if not _SCOUT_KEY:
        return {"processed": 0, "failed": 0, "stopped": "missing_cluster_proxy_key"}

    processed = 0
    failed = 0
    while processed + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "failed": failed, "stopped": "no_backlog"}

        for article in batch:
            if processed + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "failed": failed, "stopped": "max_runs"}

            aid = article["id"]
            url = article["url"]
            body_before = article["body_len"] or 0

            scout_job_id, err = _dispatch_scout(url)
            if scout_job_id is None:
                _persist_failure(engine, schema, aid, None, body_before, "failed", err or "dispatch failed")
                failed += 1
                logger.warning("[scout_body] article=%s dispatch failed: %s", aid, err)
                time.sleep(_DISPATCH_SLEEP_SEC)
                continue

            job_row, poll_err = _poll_scout(scout_job_id)
            if job_row is None:
                _persist_failure(engine, schema, aid, scout_job_id, body_before,
                                 "timeout" if poll_err == "timeout" else "failed",
                                 poll_err or "poll failed")
                failed += 1
                logger.warning("[scout_body] article=%s scout_job=%s poll: %s", aid, scout_job_id, poll_err)
                time.sleep(_DISPATCH_SLEEP_SEC)
                continue

            new_body = _pick_longest_body(job_row.get("data") or {})
            if len(new_body) < _MIN_RESCUE_CHARS or len(new_body) <= body_before:
                _persist_failure(engine, schema, aid, scout_job_id, body_before,
                                 "failed",
                                 f"rescued body too short ({len(new_body)} chars, needed > {body_before} and >= {_MIN_RESCUE_CHARS})")
                failed += 1
                logger.info("[scout_body] article=%s scout_job=%s rescued only %d chars — skipped",
                            aid, scout_job_id, len(new_body))
                time.sleep(_DISPATCH_SLEEP_SEC)
                continue

            try:
                _persist_success(engine, schema, aid, scout_job_id, body_before, new_body)
                processed += 1
                logger.info("[scout_body] article=%s scout_job=%s rescued %d → %d chars",
                            aid, scout_job_id, body_before, len(new_body))
            except Exception as exc:
                failed += 1
                logger.exception("[scout_body] article=%s persist failed: %s", aid, exc)

            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "failed": failed, "stopped": "max_runs"}
