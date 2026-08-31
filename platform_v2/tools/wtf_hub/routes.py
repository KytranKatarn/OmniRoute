"""WTF Hub routes — internal API for wtf-ingest to dispatch to News & Media agents."""

from __future__ import annotations

import json
import logging
import os
import re
import time


def _parse_llm_json(text: str) -> dict:
    """Parse a model's JSON response, tolerating markdown code fences and
    surrounding prose. Local models frequently wrap output in ```json fences
    despite 'Return ONLY valid JSON' — a bare json.loads then fails and the
    verdict is lost as {'raw': ...} (756 null verdicts/7d before this fix).
    Raises ValueError when no JSON object can be extracted."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # The regex only LOCATES a fenced block — json.loads still does the actual
    # parsing, so malformed content inside a fence raises like any bad JSON.
    # Unexpected shapes that defeat this layer fall through to the outermost-
    # brace slice below, and a total miss raises — which the call sites catch
    # and degrade to {'raw': ...}, i.e. the exact pre-fix behaviour. Brittleness
    # is bounded: this function can only ever RECOVER verdicts, never lose one.
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no JSON object found in model response")


from flask import jsonify, render_template, request
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
    "classify_beat": None,
    "factcheck_relevance": None,
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
    if not _AGENT_IDS["classify_beat"]:
        # Beat classification is News & Media work (#4702 Part B): the
        # beat_classification capability routes to the News beat specialist
        # P.U.B.L.I.S.H. (qwen2.5:1.5b) via DHQ skill-first selection — not the
        # generic Analytics `classify`. No model_override: the agent's small model
        # drives it and warm-path fleet routing distributes across nodes (mirrors
        # L.O.C.A.L./geo). This id is only the existence guard + response label;
        # the dispatcher still picks the real agent by capability.
        _AGENT_IDS["classify_beat"] = _get_agent_id("P.U.B.L.I.S.H.")
    if not _AGENT_IDS["factcheck_relevance"]:
        # #2137 relevance gate — existence guard + label only; capability routing
        # (beat_classification) picks the real small-model News agent.
        _AGENT_IDS["factcheck_relevance"] = _get_agent_id("P.U.B.L.I.S.H.")


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
    if task not in ("bias", "factcheck", "geo", "deep_analysis", "classify_beat", "factcheck_relevance"):
        return jsonify({"ok": False, "error": f"unknown task: {task}"}), 400

    title = (data.get("title") or "")[:200]
    body = (data.get("body") or "")[:3000]
    source_slug = (data.get("source_slug") or "")[:100]

    if not title and not body:
        return jsonify({"ok": False, "error": "title or body required"}), 400

    _resolve_agents()

    prompts = {
        "bias": (
            f"You are a Canadian political bias analyst. Score this article's political framing on the Canadian spectrum.\n\n"
            f"Source outlet: {source_slug}\nHeadline: {title}\nBody excerpt: {body[:2500]}\n\n"
            "Canadian political spectrum context:\n"
            "- LEFT: NDP, Green, labour unions, Indigenous rights, anti-corporate\n"
            "- CENTER-LEFT: Liberal Party, CBC framing, progressive but establishment\n"
            "- CENTER: Factual/neutral reporting, no clear partisan framing\n"
            "- CENTER-RIGHT: Conservative-friendly, fiscal conservatism, business-focus\n"
            "- RIGHT: Conservative Party base, Postmedia editorial line, anti-government\n\n"
            "Score thresholds: left < -0.6 | center-left -0.6 to -0.2 | center -0.2 to 0.2 | center-right 0.2 to 0.6 | right > 0.6\n\n"
            'Return ONLY valid JSON: {"score": float, "band": string, "rationale": string, "trigger_phrases": [string], "confidence": float}\n\n'
            "IMPORTANT: If article is clearly from a left-leaning or right-leaning outlet, reflect that in your score. "
            "Avoid defaulting to 0.0 — make a decision even if uncertain."
        ),
        "factcheck": (
            f"You are a Canadian fact-checker. Extract and verify specific factual claims from this article.\n\n"
            f"Title: {title}\nBody: {body[:2000]}\n\n"
            "ONLY extract FACTUAL ASSERTIONS (statistics, historical events, attributed quotes, study results, government actions).\n"
            "SKIP opinions, predictions, descriptions of ongoing events, and editorial commentary.\n\n"
            "For each factual claim, assign a verdict:\n"
            "- verified: the claim matches established facts you know (dates, office-holders, published statistics, settled events)\n"
            "- mostly_true: the claim is clearly attributed to a NAMED source (official, document, dataset, study) and is internally consistent — this is the CORRECT verdict for well-sourced reporting; do NOT mark attributed claims unverifiable\n"
            "- mixed: partially supported, or substantial claims lack attribution/context\n"
            "- disputed: available evidence or the article itself contradicts the claim\n"
            "- unverifiable: the claim has NO attribution and no way to assess it — use this SPARINGLY, only when nothing ties the claim to any source\n\n"
            "overall_verdict MUST be exactly one of: verified | mostly_true | mixed | disputed | unverifiable | descriptive_reporting\n"
            "Derive it from the claims: most claims verified/mostly_true -> mostly_true (or verified when all are); "
            "substantial unattributed claims -> mixed; any contradiction -> disputed; nothing attributable at all -> unverifiable.\n\n"
            "IMPORTANT: If the article contains NO specific factual assertions "
            "(e.g., market summary, breaking dispatch, sports score, weather report, wire copy):\n"
            '  Return: {"claims": [], "overall_verdict": "descriptive_reporting", "confidence": 0.9}\n\n'
            'Return ONLY valid JSON: {"claims": [{"text": str, "verdict": str, "reasoning": str, "confidence": float}], '
            '"overall_verdict": string, "confidence": float}'
        ),
        "geo": (
            f"Extract the PRIMARY geographic location this news article is ABOUT.\n\n"
            f"Title: {title}\nBody: {body[:2000]}\n\n"
            "Rules:\n"
            "  - Identify WHERE the story is happening, not where it is merely mentioned.\n"
            "  - If article mentions multiple locations, pick the MAIN one the story is about.\n"
            "  - If primarily Canadian, set country_code='CA' AND province_code (e.g. 'ON', 'QC').\n"
            "  - If primarily another country, set country_code (ISO 3166-1 alpha-2: 'US', 'GB', 'FR'...) "
            "and leave province_code null.\n"
            "  - geo_scope: 'national' (Canada-wide), 'provincial', 'municipal', or 'international' (non-Canada).\n"
            "  - If confidence < 0.5 or truly unclear, return all-null with geo_scope='international'.\n\n"
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
        "classify_beat": (
            f"Classify this Canadian news article into exactly one beat topic.\n\n"
            f"Valid beats: arts-culture, business, climate, crime, economy, education, "
            f"foreign-policy, healthcare, housing, immigration, indigenous, justice, "
            f"labour, municipal, parliament, science-tech, sports, transportation\n"
            f'Use "none" if no beat fits.\n\n'
            f"Title: {title}\nBody: {body[:1000]}\n\n"
            'Return ONLY valid JSON: {"beat": "healthcare"}'
        ),
        # #2137 relevance gate: a third-party fact-check (from Google FCTAPI) is
        # keyword-matched to an article by title, so it often surfaces a review of
        # a DIFFERENT claim that merely shares a name. `title` is the article
        # headline; `body` carries the partner claim text. Decide if the
        # fact-check actually assesses a claim THIS article makes/reports.
        "factcheck_relevance": (
            f"A third-party fact-check was matched to a news article by keyword. "
            f"Decide whether the fact-check actually assesses a specific claim that "
            f"THIS article makes or reports on — not merely a claim about the same "
            f"person, place, or topic.\n\n"
            f"ARTICLE HEADLINE: {title}\n"
            f"FACT-CHECK CLAIM: {body[:600]}\n\n"
            "Relevant ONLY if the fact-check addresses substantially the same event "
            "or assertion as the article. Sharing a name (e.g. a politician) or a "
            "broad topic is NOT enough.\n"
            'Return ONLY valid JSON: {"relevant": true or false, "confidence": 0.0-1.0}'
        ),
    }

    agent_names = {
        "bias": "B.I.A.S.",
        "factcheck": "V.E.R.I.F.Y.",
        "geo": "L.O.C.A.L.",
        "deep_analysis": "V.E.R.I.F.Y.",
        "classify_beat": "P.U.B.L.I.S.H.",
        "factcheck_relevance": "P.U.B.L.I.S.H.",
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
        "classify_beat": "beat_classification",  # News & Media — P.U.B.L.I.S.H. (qwen2.5:1.5b, fleet-distributed), #4702 Part B
        # #2137: a binary yes/no relevance judgment — reuse the small-model News
        # route (P.U.B.L.I.S.H., qwen2.5:1.5b) rather than the heavy fact_check
        # model. The capability is routing plumbing; the prompt does the work.
        "factcheck_relevance": "beat_classification",
    }

    # Backpressure (#4536): if this capability's dispatch pipe is already saturated with
    # in-flight bridge_jobs, defer instead of piling another 240s-timeout onto the
    # contended hub GPU. Reuses the existing rate_limited response shape so the remote WTF
    # ingest backs off with no change — and we return BEFORE dispatch, so no bridge_jobs
    # row (and no failure) is created. Fail-open.
    try:
        from services.welfare_governance_service import in_flight_over_cap

        if in_flight_over_cap(capabilities[task]):
            logger.info("[WTFHub] in-flight cap reached for task=%s — deferring", task)
            return jsonify(
                {
                    "ok": True,
                    "result": None,
                    "rate_limited": True,
                    "retry_after": _ANALYZE_INTERVAL or 60,
                }
            )
    except Exception:
        logger.warning("[WTFHub] in-flight check failed for task=%s; proceeding", task, exc_info=True)

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        # L.O.C.A.L. agent has model=qwen2.5:1.5b set in agents table — DHQ
        # fleet routing distributes across hub + Starship nodes automatically.
        # No model_override needed; let the dispatcher select the best available node.
        result = dispatch(
            capability=capabilities[task],
            prompt=prompts[task],
            module_id="wtf_hub",
            json_mode=True,
            # #4343 P1b: WTF factcheck/bias/geo is the primary batch GPU-stream surge — low
            # priority so it yields the interactive reserved stream + sorts behind interactive
            # work in the cold-load queue. Still batch-lane (reserve applies); never dropped.
            priority="low",
        )
        if result.success:
            try:
                parsed = _parse_llm_json(result.response)
            except Exception:
                parsed = {"raw": result.response}
            # ⚠️ REPORT THE AGENT THAT ACTUALLY RAN IT, not the nominal one.
            # `agent_names` is a hardcoded task->agent map (bias_analysis->B.I.A.S.,
            # fact_check->V.E.R.I.F.Y., ...). But dispatch() selects by CAPABILITY and
            # K.I.N. welfare-gating routes around a busy agent — by design. Measured
            # over 7 days, V.E.R.I.F.Y. performed only 19% of fact_checks; P.R.O.O.F.,
            # E.C.H.O., V.E.T., A.X.I.O.M., C.O.N.D.U.I.T., T.A.L.O.N. and R.A.N.G.E.R.
            # did the rest — and every one of them was reported to the caller, and
            # published on what-the-fact.com/activity, as "V.E.R.I.F.Y.".
            # The map stays only as a fallback for a result with no agent_name.
            return jsonify(
                {
                    "ok": True,
                    "result": parsed,
                    "agent": getattr(result, "agent_name", None) or agent_names[task],
                }
            )
        else:
            return jsonify({"ok": False, "error": result.error or "dispatch failed"}), 500
    except Exception as exc:
        logger.exception("[WTFHub] dispatch failed for task=%s", task)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ───────────────────────────────────────────────────────────────────────────
# Agent dispatch stats (#2956) — per-agent aggregations from task_execution_log
# ───────────────────────────────────────────────────────────────────────────


@wtf_hub_bp.route("/api/agent-stats", methods=["GET"])
def agent_stats():
    """Per-agent dispatch stats over last 24h for WTF traffic.

    Powers the consumer activity-page dispatch-path subtitle (#2956).
    Subset of task_execution_log filtered to module_source IN wtf_hub/wtf_hub_quick/
    wtf-ingest/wtf-tech/wtf_dhq_* for News & Media agents (incl. F.A.C.T. orchestration).

    Returns {agent_name: {count, success_rate, avg_ms, last_model, last_node}}.
    """
    if not _auth_ok(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT
                    tel.agent_name,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE tel.success) AS successes,
                    ROUND(AVG(tel.duration_ms))::int AS avg_ms,
                    MODE() WITHIN GROUP (ORDER BY tel.model_used) AS top_model,
                    MAX(CASE WHEN rn.node_id IS NULL OR rn.node_id = 'archie-starbase'
                             THEN 'Starbase - A.R.C.H.I.E.' ELSE rn.node_name END) AS last_node
                FROM task_execution_log tel
                LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                  AND tel.module_source IN (
                      'wtf_hub', 'wtf_hub_quick', 'wtf-ingest', 'wtf-tech',
                      'wtf_dhq_llm', 'wtf_dhq_geo', 'wtf_dhq_factcheck', 'wtf_dhq_scout',
                      'wtf_dhq_geo_backlog', 'wtf_dhq_llm_backlog'
                  )
                  AND tel.agent_name IS NOT NULL
                GROUP BY tel.agent_name
                ORDER BY total DESC
                """
            )
            rows = cur.fetchall()
        stats = {}
        for r in rows:
            d = dict(r)
            total = int(d.get("total") or 0)
            successes = int(d.get("successes") or 0)
            stats[d["agent_name"]] = {
                "count": total,
                "success_rate": round(successes / total, 3) if total else None,
                "avg_ms": d.get("avg_ms"),
                "top_model": d.get("top_model"),
                "last_node": d.get("last_node"),
            }
        return jsonify({"ok": True, "agents": stats, "generated_at": time.time()})
    except Exception as exc:
        logger.exception("[WTFHub] agent_stats failed")
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


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
            # #4343 P1b: WTF quick-classify is batch ingest work — low priority.
            priority="low",
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
            parsed = _parse_llm_json(result.response)
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


@wtf_hub_bp.route("/api/cross-watch/search", methods=["GET"])
def cross_watch_search():
    """#3128 — Unified search across WTF articles + Gov Watch tenders.

    Query params:
      q      str  required, min 3 chars
      limit  int  default 10, max 50 — per product (not total)
      days   int  default 90 — WTF article look-back window

    Returns combined results sorted by date desc, each tagged with
    product (wtf | gov_watch) and type (article | tender).
    No auth required — read-only public data.
    """
    import os
    import psycopg2
    import psycopg2.extras

    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 10)), 50)
    days = min(int(request.args.get("days", 90)), 365)

    if len(q) < 3:
        return jsonify({"ok": False, "error": "q must be at least 3 characters"}), 400

    pattern = f"%{q}%"
    results = []

    # ── Gov Watch tenders (archie DB, gov_watch schema) ──────────────────────
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, title, department, deadline, status, url,
                       value_min, value_max, LEFT(description, 300) AS snippet
                FROM gov_watch.tenders
                WHERE (title ILIKE %s OR description ILIKE %s)
                ORDER BY posted_at DESC NULLS LAST
                LIMIT %s
                """,
                (pattern, pattern, limit),
            )
            for row in cur.fetchall():
                results.append(
                    {
                        "product": "gov_watch",
                        "type": "tender",
                        "id": row["id"],
                        "title": row["title"],
                        "date": row["deadline"].isoformat() if row["deadline"] else None,
                        "url": row["url"],
                        "meta": {
                            "department": row["department"],
                            "status": row["status"],
                            "value_min": float(row["value_min"]) if row["value_min"] else None,
                            "value_max": float(row["value_max"]) if row["value_max"] else None,
                            "snippet": row["snippet"],
                        },
                    }
                )
    except Exception as exc:
        logger.warning("[CrossWatch] gov_watch query failed: %s", exc)

    # ── WTF articles (separate wtf DB) ────────────────────────────────────────
    try:
        wtf_conn = psycopg2.connect(
            host="archie_database",
            port=5432,
            dbname="wtf",
            user="wtfuser",
            password=os.getenv("WTF_DB_PASSWORD", ""),
            options="-c search_path=wtf",
        )
        try:
            with wtf_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT a.id, a.title, a.url, a.published_at,
                           s.name AS source_name, s.slug AS source_slug,
                           b.band AS bias_band, LEFT(a.body, 300) AS snippet
                    FROM wtf.articles a
                    JOIN wtf.sources s ON s.id = a.source_id
                    LEFT JOIN wtf.bias_scores b ON b.article_id = a.id
                    WHERE (a.title ILIKE %s OR a.body ILIKE %s)
                      AND a.published_at > NOW() - INTERVAL '1 day' * %s
                    ORDER BY a.published_at DESC
                    LIMIT %s
                    """,
                    (pattern, pattern, days, limit),
                )
                for row in cur.fetchall():
                    results.append(
                        {
                            "product": "wtf",
                            "type": "article",
                            "id": row["id"],
                            "title": row["title"],
                            "date": row["published_at"].isoformat() if row["published_at"] else None,
                            "url": row["url"],
                            "meta": {
                                "source": row["source_name"],
                                "source_slug": row["source_slug"],
                                "bias_band": row["bias_band"],
                                "snippet": row["snippet"],
                            },
                        }
                    )
        finally:
            wtf_conn.close()
    except Exception as exc:
        logger.warning("[CrossWatch] wtf query failed: %s", exc)

    results.sort(key=lambda r: r.get("date") or "", reverse=True)

    return jsonify(
        {
            "ok": True,
            "query": q,
            "total": len(results),
            "products_searched": ["wtf", "gov_watch"],
            "results": results[:limit],
        }
    )
