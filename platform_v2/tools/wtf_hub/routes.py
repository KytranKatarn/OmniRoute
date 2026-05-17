"""WTF Hub routes — internal API for wtf-ingest to dispatch to News & Media agents."""

from __future__ import annotations

import json
import logging
import os
import time

from flask import jsonify, render_template, render_template_string, request
from flask_login import login_required

from . import wtf_hub_bp

logger = logging.getLogger(__name__)

_HUB_TOKEN = os.getenv("WTF_HUB_TOKEN", "")
if not _HUB_TOKEN:
    logger.warning("[WTFHub] WTF_HUB_TOKEN not set — endpoint is unauthenticated (dev mode only)")

# Rate limit: minimum seconds between dispatches per task type.
# Prevents VPS ingest bursts from exhausting Gunicorn workers.
# Set WTF_ANALYZE_INTERVAL=0 to disable. Default: 5 minutes.
_ANALYZE_INTERVAL = int(os.getenv("WTF_ANALYZE_INTERVAL", "300"))
_last_dispatch: dict[str, float] = {}  # task_type → last dispatch unix timestamp

_AGENT_IDS: dict[str, int | None] = {
    "bias": None,
    "factcheck": None,
    "geo": None,
    "deep_analysis": None,
}


def _get_agent_id(name: str) -> int | None:
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT id FROM agents WHERE name = %s", (name,))
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as exc:
        logger.warning("[WTFHub] _get_agent_id(%s) failed: %s", name, exc)
        return None


def _resolve_agents() -> None:
    if not _AGENT_IDS["bias"]:
        _AGENT_IDS["bias"] = _get_agent_id("B.I.A.S.")
    if not _AGENT_IDS["factcheck"]:
        _AGENT_IDS["factcheck"] = _get_agent_id("V.E.R.I.F.Y.")
    if not _AGENT_IDS["geo"]:
        _AGENT_IDS["geo"] = _get_agent_id("L.O.C.A.L.")
    if not _AGENT_IDS["deep_analysis"]:
        # Deep-analysis combines bias + factcheck + geo + editorial take
        # in one LLM round-trip. V.E.R.I.F.Y. owns it (claims verification
        # is the load-bearing piece — the others are supporting context).
        _AGENT_IDS["deep_analysis"] = _get_agent_id("V.E.R.I.F.Y.")


def _auth_ok(req) -> bool:
    if not _HUB_TOKEN:
        return True
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {_HUB_TOKEN}"


@wtf_hub_bp.route("/")
@login_required
def index():
    """WTF Hub dashboard — orchestration status for what-the-fact.com pipeline."""
    return render_template("tools/wtf_hub.html", interval=_ANALYZE_INTERVAL)


@wtf_hub_bp.route("/api/analyze", methods=["POST"])
def analyze():
    """Dispatch a WTF analysis task to the appropriate News & Media agent.

    Auth: Authorization: Bearer <WTF_HUB_TOKEN>

    Request JSON:
      task        (str) — "bias" | "factcheck" | "geo"
      article_id  (int) — wtf article id
      title       (str) — article title
      body        (str) — article body (first 3000 chars used)
      source_slug (str) — e.g. "cbc_english"

    Response JSON:
      { "ok": true, "result": { ...agent output... } }
    """
    if not _auth_ok(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    task = data.get("task", "")
    if task not in ("bias", "factcheck", "geo", "deep_analysis"):
        return jsonify({"ok": False, "error": f"unknown task: {task}"}), 400

    title = (data.get("title") or "")[:200]
    body = (data.get("body") or "")[:3000]
    source_slug = (data.get("source_slug") or "")[:100]

    if not title and not body:
        return jsonify({"ok": False, "error": "title or body required"}), 400

    _resolve_agents()

    prompts = {
        "bias": (
            f"Analyze the bias of this Canadian news article.\n\n"
            f"Source: {source_slug}\nTitle: {title}\nBody: {body}\n\n"
            'Return ONLY valid JSON: {"score": float -1 to 1, "band": string, '
            '"rationale": string, "trigger_phrases": list[str], "confidence": float}'
        ),
        "factcheck": (
            f"Fact-check the claims in this Canadian news article.\n\n"
            f"Title: {title}\nBody: {body}\n\n"
            'Return ONLY valid JSON: {"claims": [{"text": str, "verdict": str, "reasoning": str}], '
            '"overall_verdict": string, "confidence": float}. '
            "Verdicts: verified | mixed | disputed | unverifiable"
        ),
        "geo": (
            f"Extract the primary geographic location this news article is about.\n\n"
            f"Title: {title}\nBody: {body[:1000]}\n\n"
            "Rules:\n"
            "  - If primarily Canadian, set country_code='CA' AND province_code (e.g. 'ON', 'QC').\n"
            "  - If primarily another country, set country_code (ISO 3166-1 alpha-2: 'US', 'GB', 'FR'...) "
            "and leave province_code null.\n"
            "  - geo_scope: 'national' (Canada-wide), 'provincial', 'municipal', or 'international' (non-Canada).\n"
            "  - If unclear, return all-null with geo_scope='international' and country_code=null.\n\n"
            'Return ONLY valid JSON: {"province_code": "ON" or null, "country_code": "CA"|"US"|... or null, '
            '"city": "Toronto" or null, "lat": float or null, "lng": float or null, '
            '"geo_scope": "national|provincial|municipal|international", "geo_confidence": 0.0-1.0}'
        ),
        "deep_analysis": (
            f"Provide a complete editorial review of this Canadian news article.\n\n"
            f"Source: {source_slug}\nTitle: {title}\nBody: {body}\n\n"
            "Return ONLY valid JSON with these top-level keys:\n"
            '  "bias_summary": {"score": float -1 to 1, "band": str, "rationale": str, '
            '"trigger_phrases": list[str], "confidence": float},\n'
            '  "key_claims": [{"text": str, "verdict": "verified|mixed|disputed|unverifiable", '
            '"reasoning": str}, ...],\n'
            '  "geo_entities": [{"name": str, "type": "city|province|country", '
            '"lat": float or null, "lng": float or null}, ...],\n'
            '  "editorial_take": str (1-3 sentence summary of importance + reliability),\n'
            '  "confidence": float 0.0-1.0\n'
        ),
    }

    agent_names = {
        "bias": "B.I.A.S.",
        "factcheck": "V.E.R.I.F.Y.",
        "geo": "L.O.C.A.L.",
        "deep_analysis": "V.E.R.I.F.Y.",
    }
    agent_name = agent_names[task]
    agent_id = _AGENT_IDS.get(task)
    if not agent_id:
        return jsonify({"ok": False, "error": f"agent not found for task: {task}"}), 503

    # Per-task rate limit — spread load across hardware capacity.
    if _ANALYZE_INTERVAL > 0:
        now = time.time()
        last = _last_dispatch.get(task, 0)
        elapsed = now - last
        if elapsed < _ANALYZE_INTERVAL:
            wait = int(_ANALYZE_INTERVAL - elapsed)
            logger.info("[WTFHub] rate-limited task=%s (retry in %ds)", task, wait)
            return jsonify({"ok": True, "result": None, "rate_limited": True, "retry_after": wait})
        _last_dispatch[task] = now

    capabilities = {
        "bias": "bias_analysis",
        "factcheck": "fact_check",
        "geo": "geo_extraction",
        "deep_analysis": "fact_check",  # routes to V.E.R.I.F.Y. — same agent, longer prompt
    }

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability=capabilities[task],
            prompt=prompts[task],
            module_id="wtf_hub",
            json_mode=True,
        )
        if result.success:
            try:
                parsed = json.loads(result.response)
            except Exception:
                parsed = {"raw": result.response}
            return jsonify({"ok": True, "result": parsed, "agent": agent_names[task]})
        else:
            return jsonify({"ok": False, "error": result.error or "dispatch failed"}), 500
    except Exception as exc:
        logger.exception("[WTFHub] dispatch failed for task=%s", task)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ───────────────────────────────────────────────────────────────────────────
# Phase A: Two-tier LLM (Task #2943) — quick capabilities
# ───────────────────────────────────────────────────────────────────────────


@wtf_hub_bp.route("/api/analyze-quick", methods=["POST"])
def analyze_quick():
    """Tier-1 dispatch — small/fast model for first-pass triage.

    Auth: Authorization: Bearer <WTF_HUB_TOKEN>

    Request JSON:
      task        (str) — "bias" | "factcheck" | "geo"
      article_id  (int) — wtf article id
      title       (str) — article title
      body        (str) — article body (first 2000 chars used — shorter than full tier)
      source_slug (str) — e.g. "cbc_english"
      prefer_node (str) — optional, e.g. "outpost_us_001"

    Response JSON (Tier-1 strict shape, see docs/two-tier-llm-design.md):
      { "ok": true, "result": {
          "tier": "quick_v1", "model": "qwen2.5:1.5b", "node": "...",
          "bias"|"claims"|"geo": ...,
          "gate_to_full": bool,
          "duration_ms": int
      }}

    Phase A: endpoint is wired but no caller in WTF ingest yet. Verify the
    DHQ path returns sub-8s responses for qwen2.5:1.5b before Phase B wires
    callers.
    """
    if not _auth_ok(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    task = data.get("task", "")
    if task not in ("bias", "factcheck", "geo"):
        return jsonify({"ok": False, "error": f"unknown task: {task}"}), 400

    title = (data.get("title") or "")[:200]
    body = (data.get("body") or "")[:2000]
    source_slug = (data.get("source_slug") or "")[:100]
    prefer_node = (data.get("prefer_node") or "").strip() or None

    if not title and not body:
        return jsonify({"ok": False, "error": "title or body required"}), 400

    # Tier-1 prompts — strict, short, single-shot JSON. No rationale, no verdict.
    quick_prompts = {
        "bias": (
            f"Classify the political bias of this article. Output ONLY one of "
            f"these five labels: left, center-left, center, center-right, right.\n\n"
            f"Source: {source_slug}\nTitle: {title}\nBody: {body[:1200]}\n\n"
            'Return ONLY valid JSON: {"band": "<one of 5>", "confidence": 0.0-1.0}'
        ),
        "factcheck": (
            f"Extract up to 3 factual claims from this article. No verdict, no reasoning.\n\n"
            f"Title: {title}\nBody: {body[:1500]}\n\n"
            'Return ONLY valid JSON: {"claims": ["claim text", ...]} (max 3, can be empty list)'
        ),
        "geo": (
            f"Identify the primary location this article is about.\n\n"
            f"Title: {title}\nBody: {body[:800]}\n\n"
            "Rules: if Canadian, set country_code='CA' AND province_code (e.g. 'ON'). "
            "If foreign, set country_code to ISO alpha-2 ('US','GB','FR'...) and "
            "leave province_code null. If unclear, both null.\n\n"
            'Return ONLY valid JSON: {"province_code": "ON"|"QC"|"BC"|"AB"|...|null, '
            '"country_code": "CA"|"US"|"GB"|... or null, "confidence": 0.0-1.0}'
        ),
    }

    capabilities = {
        "bias": "bias_quick",
        "factcheck": "factcheck_quick",
        "geo": "geo_quick",
    }

    started = time.time()
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        # Always pass capability + prompt explicitly so V.I.G.I.L.'s static
        # dispatch-signature guardrail can verify the call. context is fed
        # via **kwargs and may be empty.
        #
        # Pin Tier-1 to qwen2.5:1.5b. prefer_model was the wrong lever — it
        # only finds an agent that already runs that model and silently no-ops
        # if no roster match. model_override hard-pins the model regardless
        # of which agent the coordinator picks. Without this, factcheck_quick
        # routes to V.E.R.I.F.Y. and uses its 7b primary (4.7GB, ~5-15s)
        # instead of the cheap 1.5b model the tier is for.
        result = dispatch(
            capability=capabilities[task],
            prompt=quick_prompts[task],
            module_id="wtf_hub_quick",
            json_mode=True,
            model_override="qwen2.5:1.5b",
            context={"prefer_node": prefer_node} if prefer_node else {},
        )
        duration_ms = int((time.time() - started) * 1000)

        if not result.success:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": result.error or "dispatch failed",
                        "duration_ms": duration_ms,
                    }
                ),
                500,
            )

        try:
            parsed = json.loads(result.response)
        except Exception:
            parsed = {"raw": result.response}

        # Apply Tier-1 → Tier-2 gate (see design doc §gate)
        gate_to_full = False
        if task == "bias":
            band = (parsed.get("band") or "").lower()
            if band in ("left", "right"):
                gate_to_full = True
        elif task == "factcheck":
            claims = parsed.get("claims") or []
            if isinstance(claims, list) and len(claims) >= 3 and len(body) >= 1500:
                gate_to_full = True

        return jsonify(
            {
                "ok": True,
                "result": {
                    "tier": "quick_v1",
                    "model": getattr(result, "model_used", None) or "unknown",
                    "node": getattr(result, "node_name", None) or "hub",
                    **parsed,
                    "gate_to_full": gate_to_full,
                    "duration_ms": duration_ms,
                },
            }
        )
    except Exception as exc:
        logger.exception("[WTFHub] quick dispatch failed for task=%s", task)
        return jsonify({"ok": False, "error": str(exc)}), 500
