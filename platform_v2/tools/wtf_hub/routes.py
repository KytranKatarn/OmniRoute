"""WTF Hub routes — internal API for wtf-ingest to dispatch to News & Media agents."""

from __future__ import annotations

import json
import logging
import os
import time

from flask import jsonify, render_template_string, request
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


def _auth_ok(req) -> bool:
    if not _HUB_TOKEN:
        return True
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {_HUB_TOKEN}"


@wtf_hub_bp.route("/")
@login_required
def index():
    """WTF Hub dashboard — orchestration status for what-the-fact.com pipeline."""
    return render_template_string(
        """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>WTF Hub — A.R.C.H.I.E.</title>
  <link rel="stylesheet" href="/static/css/base.css">
  <link rel="stylesheet" href="/static/css/lcars-frames.css">
  <style>
    body { background: #010409; color: #ccc; font-family: 'IBM Plex Mono', monospace; padding: 32px; }
    .wtf-card { background: #0d1117; border: 1px solid #1a2a3a; border-radius: 6px; padding: 16px; margin-bottom: 12px; }
    .wtf-label { color: #555; font-size: 0.6rem; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 6px; }
    .wtf-value { color: #60a5fa; font-size: 0.8rem; }
    .wtf-agent { display: inline-block; background: rgba(96,165,250,0.1); border: 1px solid rgba(96,165,250,0.3); color: #60a5fa; padding: 3px 8px; border-radius: 3px; font-size: 0.65rem; margin: 2px; }
  </style>
</head>
<body>
  <div style="max-width:800px;margin:0 auto;">
    <div style="font-family:'Orbitron',sans-serif;font-size:1.1rem;color:#60a5fa;letter-spacing:3px;margin-bottom:6px;">WTF HUB</div>
    <div style="color:#555;font-size:0.65rem;margin-bottom:24px;">What The Fact — AI orchestration surface · <a href="https://what-the-fact.com" target="_blank" style="color:#3b82f6;">what-the-fact.com</a></div>

    <div class="wtf-card">
      <div class="wtf-label">Pipeline Agents</div>
      <span class="wtf-agent">B.I.A.S. — Bias Analysis</span>
      <span class="wtf-agent">V.E.R.I.F.Y. — Fact Checking</span>
      <span class="wtf-agent">L.O.C.A.L. — Geo Extraction</span>
    </div>

    <div class="wtf-card">
      <div class="wtf-label">Dispatch Endpoint</div>
      <div class="wtf-value">POST /tools/wtf-hub/api/analyze</div>
      <div style="color:#555;font-size:0.62rem;margin-top:4px;">Called by wtf-ingest container on VPS (76.13.107.109) · Auth: WTF_HUB_TOKEN</div>
    </div>

    <div class="wtf-card">
      <div class="wtf-label">Task Types</div>
      <div style="font-size:0.65rem;color:#888;line-height:1.8;">
        <b style="color:#ccc;">bias</b> — Article bias score (-1 to 1) via B.I.A.S.<br>
        <b style="color:#ccc;">factcheck</b> — Claim verification via V.E.R.I.F.Y.<br>
        <b style="color:#ccc;">geo</b> — Canadian location extraction via L.O.C.A.L.
      </div>
    </div>

    <div class="wtf-card">
      <div class="wtf-label">Rate Limit</div>
      <div class="wtf-value">{{ interval }}s between dispatches per task type</div>
      <div style="color:#555;font-size:0.62rem;margin-top:4px;">Set WTF_ANALYZE_INTERVAL=0 to disable · Prevents VPS bursts from exhausting workers</div>
    </div>
  </div>
</body>
</html>
    """,
        interval=_ANALYZE_INTERVAL,
    )


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
    if task not in ("bias", "factcheck", "geo"):
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
            f"Extract the primary Canadian location from this news article.\n\n"
            f"Title: {title}\nBody: {body[:1000]}\n\n"
            'Return ONLY valid JSON: {"province_code": "ON" or null, "city": "Toronto" or null, '
            '"lat": float or null, "lng": float or null, '
            '"geo_scope": "national|provincial|municipal|international", "geo_confidence": 0.0-1.0}'
        ),
    }

    agent_names = {"bias": "B.I.A.S.", "factcheck": "V.E.R.I.F.Y.", "geo": "L.O.C.A.L."}
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
