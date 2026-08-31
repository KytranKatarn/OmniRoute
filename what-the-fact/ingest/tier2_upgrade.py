"""Tier-2 (Deep Dive) upgrade — ONE implementation, two callers.

WHY THIS MODULE EXISTS
`POST /api/upgrade-tier2/<id>` ran the full analysis SYNCHRONOUSLY when a
subscriber clicked Deep Dive: "hub call can take up to 90s for cold qwen2.5:7b",
holding a gunicorn worker on a 512MB / 4-worker container. Measured 2026-08-31,
45,332 articles were `quick_v1` only — every one of them a 90s live cluster scan
waiting for the first paying reader to open it. That is both a poor paid
experience and the exact worker-saturation shape that served 502s for 30 minutes
on 2026-08-30 (KB #299315).

The fix is to PRE-COMPUTE the upgrade off the request path
(`tier2_precompute_worker`). But the route must keep working for anything not yet
pre-computed, so both need the same persist logic — and a second copy of it is
how `queued_dispatch_text` ended up with two divergent implementations. One
function, two callers.

⚠️ `tier2_pending` WAS A QUEUE NOTHING DRAINED. It is written by
factcheck_backlog_worker, llm_analysis_backlog_worker and tier_router (which sets
it True whenever Tier-2 is rate-limited), and before this module the ONLY readers
were two display COUNTs in consumer/routes.py. 8,056 articles sat flagged
"qualified for deep review, awaiting Tier-2 dispatch" with no consumer — the same
declared-but-never-applied shape as the gdrive retention tier that had a policy
and no pruner.
"""

import json as _json
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import text

log = logging.getLogger(__name__)

# Verdict vocabulary is CONSTRAINED downstream — an unmapped value must land on
# 'unverified', never pass through raw.
_VERDICT_MAP = {
    "verified": "true",
    "true": "true",
    "mostly true": "mostly_true",
    "mostly_true": "mostly_true",
    "mixed": "mixed",
    "partly true": "mixed",
    "disputed": "mixed",
    "false": "false",
    "misleading": "false",
    "unverifiable": "unverified",
    "unverified": "unverified",
}


def hub_config() -> tuple:
    """(url, token, timeout). Absent config is a SKIP, never a crash."""
    return (
        os.environ.get("WTF_HUB_URL", ""),
        os.environ.get("WTF_HUB_TOKEN", ""),
        int(os.environ.get("WTF_HUB_TIMEOUT", "90")),
    )


def fetch_article(conn, schema: str, article_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        text(
            f"""
            SELECT a.id, a.title, a.body, a.analysis_tier, s.slug AS source_slug
              FROM {schema}.articles a
              JOIN {schema}.sources s ON s.id = a.source_id
             WHERE a.suppressed_reason IS NULL AND a.id = :id
            """
        ),
        {"id": article_id},
    ).mappings().first()
    return dict(row) if row else None


def request_deep_analysis(article: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the hub for the deep analysis. NEVER raises.

    Returns {"status": ok|rate_limited|timeout|error, ...}. A `rate_limited`
    result carries `retry_after` and MUST be honoured by the caller rather than
    abandoned — a worker that drops the item on a 429 silently stops draining
    (wtf.md: "analyze callers MUST honor retry_after").
    """
    hub_url, hub_token, timeout = hub_config()
    if not hub_url or not hub_token:
        return {"status": "error", "error": "hub_not_configured"}
    try:
        import requests as _req

        resp = _req.post(
            f"{hub_url}/tools/wtf-hub/api/analyze",
            json={
                "task": "deep_analysis",
                "article_id": article["id"],
                "title": article.get("title") or "",
                "body": (article.get("body") or "")[:3000],
                "source_slug": article.get("source_slug") or "",
            },
            headers={
                "Authorization": f"Bearer {hub_token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # includes Timeout — the caller decides what to do
        name = type(exc).__name__
        return {
            "status": "timeout" if "Timeout" in name else "error",
            "error": f"{name}: {str(exc)[:200]}",
        }

    if data.get("rate_limited"):
        return {"status": "rate_limited", "retry_after": data.get("retry_after")}
    if not data.get("ok"):
        return {"status": "error", "error": data.get("error") or "hub_rejected"}
    return {
        "status": "ok",
        "result": data.get("result") or {},
        # The agent that ACTUALLY ran it. The hub used to return a hardcoded
        # task->agent map; it now returns DispatchResult.agent_name, so this is
        # the real performer (P.R.O.O.F., E.C.H.O., V.E.T., ...) rather than the
        # nominal V.E.R.I.F.Y. Persisted below so attribution survives.
        "agent": data.get("agent") or "",
    }


def persist_upgrade(conn, schema: str, article_id: int, payload: Dict[str, Any]) -> int:
    """Write the upgrade in ONE transaction. Returns the claim count.

    The caller owns the transaction so a worker can batch and a route can keep
    its request-scoped one.
    """
    result = payload.get("result") or {}
    bias = result.get("bias_summary") or {}
    claims = result.get("key_claims") or []
    agent = (payload.get("agent") or "").strip() or "V.E.R.I.F.Y."

    conn.execute(
        text(
            f"""
            UPDATE {schema}.bias_scores
               SET band = COALESCE(:band, band),
                   score = COALESCE(:score, score),
                   rationale = :rationale,
                   trigger_phrases = CAST(:trig AS JSONB),
                   confidence = COALESCE(:conf, confidence)
             WHERE article_id = :id
            """
        ),
        {
            "id": article_id,
            "band": bias.get("band"),
            "score": bias.get("score"),
            "rationale": bias.get("rationale"),
            "trig": _json.dumps(bias.get("trigger_phrases") or []),
            "conf": bias.get("confidence"),
        },
    )

    # Tier-1 synthesized rows are replaced wholesale — the claim list shape
    # changes between tiers, so an in-place update would leave orphans.
    conn.execute(
        text(f"DELETE FROM {schema}.fact_checks WHERE article_id = :id"),
        {"id": article_id},
    )
    for cl in claims:
        verdict_raw = (cl.get("verdict") or "unverifiable").strip().lower()
        conn.execute(
            text(
                f"""
                INSERT INTO {schema}.fact_checks
                    (article_id, claim, verdict, evidence, checker, analyzed_by)
                VALUES (:id, :claim, :verdict, :evidence, :checker, :analyzed_by)
                """
            ),
            {
                "id": article_id,
                "claim": (cl.get("text") or "(claim text missing)")[:500],
                "verdict": _VERDICT_MAP.get(verdict_raw, "unverified"),
                "evidence": (cl.get("reasoning") or "")[:1000],
                "checker": agent,
                "analyzed_by": agent,
            },
        )

    conn.execute(
        text(
            f"""
            UPDATE {schema}.articles
               SET analysis_tier = 'quick_v1+full',
                   tier2_at = NOW(),
                   tier2_pending = FALSE
             WHERE id = :id
            """
        ),
        {"id": article_id},
    )
    return len(claims)


def upgrade_article(engine, schema: str, article_id: int) -> Dict[str, Any]:
    """Full upgrade for one article. NEVER raises.

    Returns {"status": upgraded|already|not_found|rate_limited|timeout|error, ...}.
    `already` is a success for the caller's purposes — the Deep Dive is present.
    """
    try:
        with engine.begin() as conn:
            article = fetch_article(conn, schema, article_id)
        if not article:
            return {"status": "not_found"}
        if article.get("analysis_tier") == "quick_v1+full":
            return {"status": "already"}

        payload = request_deep_analysis(article)
        if payload["status"] != "ok":
            return payload

        with engine.begin() as conn:
            n = persist_upgrade(conn, schema, article_id, payload)
        return {
            "status": "upgraded",
            "claims": n,
            "agent": payload.get("agent") or "",
            "bias_summary": (payload.get("result") or {}).get("bias_summary") or {},
        }
    except Exception as exc:
        log.warning("tier2 upgrade failed for article=%s: %s", article_id, exc)
        return {"status": "error", "error": str(exc)[:200]}
