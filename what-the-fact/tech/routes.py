import os
import threading
import time
import requests
from collections import defaultdict
from flask import Blueprint, current_app, render_template, session, abort, redirect, url_for
from sqlalchemy import create_engine, text

# stdlib-only, unit-testable without Flask (#5791)
from .analyze_guard import ALREADY_RUNNING, AT_CAPACITY, AnalyzeGuard

bp = Blueprint("wtf_tech", __name__)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


def _creed_api_url() -> str:
    """Return the C.R.E.E.D. API base URL from env — never exposed to browser JS (KB #267314)."""
    return os.environ.get("CREED_API_URL", "https://creed.kytranempowerment.com")


@bp.get("/")
def index():
    """Homepage with live stats (#3352)."""
    S = _schema()
    stats = {"sources": 46, "articles": 22000, "beats": 18, "articles_today": 222}
    try:
        with _db().connect() as c:
            row = c.execute(
                text(f"""
                    SELECT
                        (SELECT COUNT(*) FROM {S}.sources) AS sources,
                        (SELECT COUNT(*) FROM {S}.articles) AS articles,
                        (SELECT COUNT(DISTINCT beat) FROM {S}.articles WHERE beat IS NOT NULL) AS beats,
                        (SELECT COUNT(*) FROM {S}.articles
                         WHERE published_at >= NOW() - INTERVAL '1 day') AS articles_today
                """)
            ).fetchone()
            if row:
                stats = {
                    "sources": int(row.sources or 46),
                    "articles": int(row.articles or 22000),
                    "beats": int(row.beats or 18),
                    "articles_today": int(row.articles_today or 222),
                }
    except Exception:
        pass  # use fallback values
    return render_template("index.html", stats=stats)


@bp.get("/transparency")
def methodology():
    """Public methodology / radical transparency page."""
    S = _schema()
    with _db().connect() as c:
        stats = c.execute(text(f"""
            SELECT
                COUNT(*) AS total_articles,
                COUNT(*) FILTER (WHERE ai_analyzed = TRUE) AS ai_analyzed,
                COUNT(*) FILTER (WHERE province_code IS NOT NULL) AS geolocated,
                (SELECT COUNT(*) FROM {S}.sources) AS total_sources
            FROM {S}.articles
            WHERE published_at >= NOW() - INTERVAL '7 days'
        """)).fetchone()
    return render_template("methodology.html", stats=stats)


@bp.get("/transparency/<int:article_id>")
def transparency(article_id: int):
    """Per-article audit dashboard (#1881 SP4) — every signal we computed about
    this article, with timestamps + agent attribution where available."""
    S = _schema()
    with _db().begin() as c:
        art = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, a.ingested_at, a.body,
                   a.province_code, a.country_code, a.geo_scope,
                   a.analysis_tier, a.tier1_at, a.tier2_at, a.cluster_id,
                   a.ai_analyzed, a.ai_analyzed_at,
                   a.bias_v2_score, a.bias_v2_label, a.bias_v2_confidence,
                   a.bias_v2_model, a.bias_v2_computed_at,
                   a.bias_ensemble_score, a.bias_ensemble_band,
                   s.slug AS source_slug, s.name AS source_name,
                   s.bias_lean AS source_bias_lean,
                   s.owner_name, s.owner_type,
                   b.band, b.score, b.rationale, b.heuristic_version,
                   b.trigger_phrases, b.computed_at AS bias_computed_at,
                   b.confidence AS bias_confidence
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
        if not art:
            abort(404)
        fc = c.execute(text(f"""
            SELECT claim, verdict, evidence, checker, checked_at
            FROM {S}.fact_checks
            WHERE article_id = :id
              AND checker != 'GoogleFCT:none'
            ORDER BY id
        """), {"id": article_id}).mappings().all()
        cluster = None
        if art.get("cluster_id"):
            cluster = c.execute(text(f"""
                SELECT id, representative_title, article_count, created_at
                FROM {S}.story_clusters WHERE id = :cid
            """), {"cid": art["cluster_id"]}).mappings().first()
        trail = c.execute(text(f"""
            SELECT event_type, payload, created_at FROM {S}.audit_trail
            WHERE article_id = :id ORDER BY created_at
        """), {"id": article_id}).mappings().all()
    # ── C.R.E.E.D. governance block (#3368) — server-side only, never exposed to JS ──
    creed_score = None
    try:
        resp = requests.get(
            f"{_creed_api_url()}/api/v1/scores",
            timeout=3,
        )
        if resp.ok:
            creed_score = resp.json()
    except Exception:
        pass  # graceful degradation — template renders "audit pending"

    return render_template(
        "transparency.html",
        a=art,
        fact_checks=[dict(r) for r in fc],
        cluster=dict(cluster) if cluster else None,
        trail=trail,
        creed_score=creed_score,
    )


@bp.get("/api/v1/creed-badge")
def creed_badge():
    """Server-side proxy for C.R.E.E.D. compliance SVG badge (#3352).
    CREED_API_URL is NEVER exposed to browser JS — all fetching happens here (KB #267314).
    """
    from flask import Response

    _FALLBACK_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20">'
        '<rect width="120" height="20" rx="3" fill="#555"/>'
        '<rect x="75" width="45" height="20" rx="3" fill="#9f9f9f"/>'
        '<text x="8" y="14" font-family="DejaVu Sans,sans-serif" font-size="11" fill="#fff">'
        "C.R.E.E.D.</text>"
        '<text x="78" y="14" font-family="DejaVu Sans,sans-serif" font-size="11" fill="#fff">'
        "N/A</text>"
        "</svg>"
    )
    try:
        resp = requests.get(
            f"{_creed_api_url()}/api/v1/badge/overall",
            timeout=3,
        )
        if resp.ok and "svg" in resp.headers.get("Content-Type", ""):
            return Response(resp.content, mimetype="image/svg+xml")
    except Exception:
        pass
    return Response(_FALLBACK_SVG, mimetype="image/svg+xml")


@bp.get("/api")
def api_hub():
    """Developer hub (#1882 SP4) — endpoint catalog + curl examples."""
    return render_template("api_hub.html")


@bp.get("/dashboard")
def dashboard():
    if "kytran_user" not in session:
        return redirect(url_for("kytran_login", next="/dashboard"))
    return render_template("dashboard.html", user=session["kytran_user"])


@bp.get("/api/v1/map-data")
def map_data():
    """Province-level + world news stats for map toggle (last 24h)."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        rows = c.execute(text(f"""
            SELECT
                a.province_code,
                COUNT(*) AS cnt,
                AVG(bs.score) AS avg_score,
                MODE() WITHIN GROUP (ORDER BY s.slug) AS top_outlet
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            LEFT JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.published_at >= NOW() - INTERVAL '24 hours'
              AND a.province_code IS NOT NULL
            GROUP BY a.province_code
        """)).fetchall()

        national_cnt = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.articles
            WHERE published_at >= NOW() - INTERVAL '24 hours'
              AND geo_scope = 'national'
        """)).scalar() or 0

        intl_rows = c.execute(text(f"""
            SELECT a.country_code, COUNT(*) AS cnt,
                   AVG(a.lat) AS avg_lat, AVG(a.lng) AS avg_lng,
                   AVG(bs.score) AS avg_score
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            WHERE a.published_at >= NOW() - INTERVAL '24 hours'
              AND a.geo_scope = 'international'
              AND a.country_code IS NOT NULL
              AND a.lat IS NOT NULL
            GROUP BY a.country_code
            ORDER BY cnt DESC
        """)).fetchall()

    def _band(score):
        if score is None: return "center"
        s = float(score)
        if s < -0.6: return "left"
        if s < -0.2: return "center-left"
        if s < 0.2:  return "center"
        if s < 0.6:  return "center-right"
        return "right"

    provinces = {}
    for row in rows:
        pc = row.province_code
        if pc:
            provinces[pc] = {
                "articles": int(row.cnt),
                "avg_bias": round(float(row.avg_score or 0), 3),
                "band": _band(row.avg_score),
                "dominant_outlet": row.top_outlet or "",
            }

    countries = []
    for row in intl_rows:
        if row.avg_lat and row.avg_lng:
            countries.append({
                "code": row.country_code,
                "lat": round(float(row.avg_lat), 4),
                "lng": round(float(row.avg_lng), 4),
                "articles": int(row.cnt),
                "band": _band(row.avg_score),
            })

    return jsonify({
        "provinces": provinces,
        "national": {"articles": int(national_cnt)},
        "countries": countries,
    })


@bp.get("/api/v1/agent-activity")
def agent_activity():
    """AI agent analysis events. ?limit=N (default 10, max 200)."""
    from flask import jsonify, request
    S = _schema()
    try:
        limit = min(int(request.args.get("limit", 10)), 200)
    except ValueError:
        limit = 10
    per = max(limit // 2, 5)
    with _db().connect() as c:
        bias_rows = c.execute(text(f"""
            SELECT 'B.I.A.S.' AS agent, a.id AS article_id, a.title,
                   bs.band AS result, bs.computed_at AS ts, s.name AS source_name
            FROM {S}.bias_scores bs
            JOIN {S}.articles a ON a.id = bs.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            ORDER BY bs.computed_at DESC LIMIT :per
        """), {"per": per}).fetchall()

        fact_rows = c.execute(text(f"""
            SELECT 'V.E.R.I.F.Y.' AS agent, a.id AS article_id, a.title,
                   fc.overall_verdict AS result, fc.checked_at AS ts,
                   s.name AS source_name
            FROM {S}.fact_checks fc
            JOIN {S}.articles a ON a.id = fc.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            ORDER BY fc.checked_at DESC LIMIT :per
        """), {"per": per}).fetchall()

        director_rows = c.execute(text(f"""
            SELECT 'F.A.C.T.' AS agent, a.id AS article_id, a.title,
                   'ingested' AS result, at.created_at AS ts, s.name AS source_name
            FROM {S}.audit_trail at
            JOIN {S}.articles a ON a.id = at.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE at.event_type = 'ingested'
            ORDER BY at.created_at DESC LIMIT :per
        """), {"per": per}).fetchall()

        local_rows = c.execute(text(f"""
            SELECT 'L.O.C.A.L.' AS agent, a.id AS article_id, a.title,
                   a.province_code AS result, at.created_at AS ts, s.name AS source_name
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            JOIN {S}.audit_trail at ON at.article_id = a.id
            WHERE a.province_code IS NOT NULL AND at.event_type = 'ingested'
            ORDER BY at.created_at DESC LIMIT :per
        """), {"per": per}).fetchall()

        draft_rows = c.execute(text(f"""
            SELECT 'D.R.A.F.T.' AS agent, NULL AS article_id,
                   sc.representative_title AS title,
                   'summarized' AS result, su.created_at AS ts, NULL AS source_name
            FROM {S}.summaries su
            JOIN {S}.story_clusters sc ON sc.id = su.cluster_id
            ORDER BY su.created_at DESC LIMIT :per
        """), {"per": per}).fetchall()

        ink_rows = c.execute(text(f"""
            SELECT 'I.N.K.' AS agent, NULL AS article_id,
                   representative_title AS title,
                   CONCAT(article_count::text, ' articles') AS result,
                   created_at AS ts, NULL AS source_name
            FROM {S}.story_clusters
            ORDER BY created_at DESC LIMIT :per
        """), {"per": per}).fetchall()

    all_rows = list(bias_rows) + list(fact_rows) + list(director_rows) + list(local_rows) + list(draft_rows) + list(ink_rows)
    events = [
        {"agent": r.agent, "article_id": r.article_id, "title": (r.title or "")[:120],
         "result": r.result or "", "source": r.source_name or "",
         "ts": r.ts.isoformat() if r.ts else None}
        for r in all_rows
    ]
    events.sort(key=lambda x: x["ts"] or "", reverse=True)
    return jsonify({"events": events[:limit]})


@bp.get("/api/v1/articles/geo")
def articles_geo():
    """Articles with lat/lng for map pins (last 24h, max 500)."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.province_code,
                   a.lat, a.lng,
                   bs.band AS bias_band,
                   s.name AS source_name,
                   a.ai_analyzed
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            LEFT JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.published_at >= NOW() - INTERVAL '24 hours'
              AND a.lat IS NOT NULL
              AND a.lng IS NOT NULL
            ORDER BY a.published_at DESC
            LIMIT 500
        """)).fetchall()
    return jsonify({"articles": [
        {
            "id": r.id,
            "title": r.title,
            "province_code": r.province_code,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "bias_band": r.bias_band or "center",
            "source_name": r.source_name,
            "ai_analyzed": bool(r.ai_analyzed),
        }
        for r in rows
    ]})


@bp.get("/api/v1/articles/<int:article_id>")
def get_article(article_id: int):
    """Single article with full bias signals (heuristic, LLM tier-1, ML v2, ensemble)."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, a.province_code,
                   a.country_code, a.geo_scope, a.ai_analyzed, a.analysis_tier,
                   a.bias_v2_score, a.bias_v2_label, a.bias_v2_confidence,
                   a.bias_v2_model, a.bias_v2_computed_at,
                   a.bias_ensemble_score, a.bias_ensemble_band,
                   s.name AS source_name, s.bias_lean AS source_bias_lean,
                   b.band AS heuristic_band, b.score AS heuristic_score,
                   b.heuristic_version, b.confidence AS llm_confidence,
                   b.computed_at AS bias_computed_at
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        from flask import abort
        abort(404)
    r = dict(row)
    bias_signals = {
        "heuristic": {
            "band": r.get("heuristic_band"),
            "score": float(r["heuristic_score"]) if r.get("heuristic_score") is not None else None,
            "version": r.get("heuristic_version"),
            "computed_at": r["bias_computed_at"].isoformat() if r.get("bias_computed_at") else None,
        },
        "ml_v2": {
            "label": r.get("bias_v2_label"),
            "score": float(r["bias_v2_score"]) if r.get("bias_v2_score") is not None else None,
            "confidence": float(r["bias_v2_confidence"]) if r.get("bias_v2_confidence") is not None else None,
            "model": r.get("bias_v2_model"),
            "computed_at": r["bias_v2_computed_at"].isoformat() if r.get("bias_v2_computed_at") else None,
        },
        "ensemble": {
            "band": r.get("bias_ensemble_band"),
            "score": float(r["bias_ensemble_score"]) if r.get("bias_ensemble_score") is not None else None,
        },
    }
    return jsonify({
        "id": r["id"],
        "title": r["title"],
        "url": r["url"],
        "published_at": r["published_at"].isoformat() if r.get("published_at") else None,
        "source": r["source_name"],
        "source_bias_lean": r["source_bias_lean"],
        "province_code": r["province_code"],
        "country_code": r["country_code"],
        "geo_scope": r["geo_scope"],
        "ai_analyzed": bool(r.get("ai_analyzed")),
        "analysis_tier": r.get("analysis_tier"),
        "bias_signals": bias_signals,
    })


_VALID_BANDS = frozenset({"left", "center-left", "center", "center-right", "right"})


# Bias parsing — mirrors ingest/bias_parse.py (#6243). tech/ ships as its own
# container with no import path into ingest/, so it cannot share the module; what
# it MUST NOT do is drift. Any change goes in ingest/bias_parse.py first.
#
# THE BUG: `float(bias.get("score") or 0.0)` collapsed a MISSING score, an explicit
# JSON null, and a real 0.0 into the same number, while keeping the model's band —
# producing rows like band='right', score=0.0, rationale=''. 34,275 rows carried
# that fabricated zero; 3,629 were publicly labelled `right` on a score of zero.
# Measured: across 745 sampled rows the model returned a literal 0 **zero** times,
# and in 400 it explicitly said "score": null.
def _score_or_none(raw):
    """Coerce a model score to float, or None when ABSENT. Never uses truthiness:
    0.0 and "0" are real measurements and must survive."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return max(-1.0, min(1.0, float(raw)))
    if isinstance(raw, str):
        text_val = raw.strip()
        if not text_val:
            return None
        try:
            return max(-1.0, min(1.0, float(text_val)))
        except ValueError:
            return None
    return None


def _parse_llm_bias(bias):
    """LLM bias section -> usable reading, or None to leave the heuristic alone.

    None when the model supplied no score: a band without a score is a partial
    parse, not a measurement.
    """
    if not isinstance(bias, dict):
        return None
    score = _score_or_none(bias.get("score"))
    if score is None:
        return None
    band = str(bias.get("band") or "").strip().lower()
    if band not in _VALID_BANDS:
        band = "center"
    confidence = bias.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    triggers = bias.get("trigger_phrases")
    if not isinstance(triggers, list):
        triggers = []
    return {
        "band": band,
        "score": score,
        "rationale": (bias.get("rationale") or "").strip(),
        "confidence": confidence,
        "trigger_phrases": triggers,
    }
# Verdict vocabulary — mirrors ingest/verdicts.py (#6242). tech/ ships as its own
# container with no import path into ingest/, so it cannot share the module; what it
# MUST NOT do is drift. Any change here goes in verdicts.py first.
#   per-claim: true | mostly_true | mixed | false | unverified   (CHECK-enforced)
_CLAIM_ALIASES = {
    "verified": "true",
    "unverifiable": "unverified",
    "disputed": "mixed",
    "mostly_false": "false",
    "descriptive_reporting": "unverified",
}


def canonical_claim(value) -> str:
    """Model output -> a valid per-claim verdict; unknown becomes 'unverified'."""
    v = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v in {"true", "mostly_true", "mixed", "false", "unverified"}:
        return v
    return _CLAIM_ALIASES.get(v, "unverified")


#   per-article: verified | mostly_true | mixed | disputed | unverifiable |
#                descriptive_reporting          (CHECK-enforced, migration 060)
#
# `descriptive_reporting` was ABSENT from the old _OVERALL_MAP, so a legitimate
# rubric value fell through .get() and was silently rewritten to `unverifiable`
# — "we tried and could not verify" instead of "this article makes no checkable
# claim". Two different statements, on a public accountability page.
_OVERALL_ALIASES = {
    "unverified": "unverifiable",  # per-CLAIM vocabulary in the per-ARTICLE column
    "true": "verified",
    "false": "disputed",
    "mostly_false": "disputed",
    "verified_facts": "verified",
    "most_factual": "mostly_true",
    "factual_reporting": "descriptive_reporting",
    "descriptive": "descriptive_reporting",
    "no_claims": "descriptive_reporting",
}


def canonical_overall(value) -> str:
    """Model output -> a valid overall_verdict.

    Mirrors ingest/verdicts.canonical_overall with ONE deliberate difference:
    that one returns None for an unrecognised label (honest absence), this one
    keeps tech/'s long-standing `unverifiable` fallback. Changing that default
    is a product decision, not a refactor — it is left alone on purpose.
    """
    v = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v in {"verified", "mostly_true", "mixed", "disputed",
             "unverifiable", "descriptive_reporting"}:
        return v
    return _OVERALL_ALIASES.get(v, "unverifiable")


def _persist_on_demand(article_id: int, results: dict, schema: str) -> None:
    """Write Deep Dive results to DB so the page reload shows LLM values.

    Two independent transactions:
    - Phase 1 (best-effort): persist bias_scores + fact_checks from LLM results.
    - Phase 2 (always): mark ai_analyzed=true so the button disappears on reload.
      Runs even if phase 1 fails — prevents infinite re-run loops.
    """
    import json as _json
    import logging as _log

    _logger = _log.getLogger("wtf-tech")

    # ── Phase 1: bias + fact_checks (best-effort) ────────────────────────
    try:
        with _db().begin() as c:
            # `reading is None` => the model returned NO score. Writing one would
            # fabricate a measurement (see _parse_llm_bias), so the bias write is
            # SKIPPED and the heuristic row — deterministic and inspectable — is
            # left intact. Deliberately a plain conditional, NOT an early return
            # or raise: the fact_checks writes below share this transaction and
            # must still run.
            reading = _parse_llm_bias(results.get("bias"))
            if reading is None:
                _logger.info(
                    "deep-dive bias skipped for article %s — model returned no score",
                    article_id,
                )
            else:
                bias_params = {
                    "aid": article_id,
                    "band": reading["band"],
                    "score": reading["score"],
                    "rationale": reading["rationale"],
                    "tp": _json.dumps(reading["trigger_phrases"]),
                    "confidence": reading["confidence"],
                }
                updated = c.execute(
                    text(f"""
                        UPDATE {schema}.bias_scores
                        SET band = :band, score = :score, rationale = :rationale,
                            analyzed_by = 'llm_v1', trigger_phrases = CAST(:tp AS JSONB),
                            confidence = :confidence, computed_at = NOW()
                        WHERE article_id = :aid
                    """),
                    bias_params,
                )
                if updated.rowcount == 0:
                    c.execute(
                        text(f"""
                            INSERT INTO {schema}.bias_scores
                                (article_id, band, score, heuristic_version, rationale,
                                 analyzed_by, trigger_phrases, confidence)
                            VALUES (:aid, :band, :score, 'llm_v1', :rationale,
                                    'llm_v1', CAST(:tp AS JSONB), :confidence)
                            ON CONFLICT (article_id) DO UPDATE
                              SET band=EXCLUDED.band, score=EXCLUDED.score,
                                  rationale=EXCLUDED.rationale, analyzed_by=EXCLUDED.analyzed_by,
                                  trigger_phrases=EXCLUDED.trigger_phrases,
                                  confidence=EXCLUDED.confidence, computed_at=NOW()
                        """),
                        bias_params,
                    )

            fc = results.get("factcheck") or {}
            claims = fc.get("claims") or []
            overall = canonical_overall(fc.get("overall_verdict"))
            claims_json = _json.dumps(claims)
            c.execute(
                text(f"DELETE FROM {schema}.fact_checks WHERE article_id = :aid"),
                {"aid": article_id},
            )
            if claims:
                for cl in claims:
                    ct = (cl.get("text") or "").strip()[:2000]
                    if not ct:
                        continue
                    vr = canonical_claim(cl.get("verdict"))
                    ev = (cl.get("reasoning") or cl.get("evidence") or "").strip()[:4000]
                    c.execute(
                        text(f"""
                            INSERT INTO {schema}.fact_checks
                                (article_id, claim, verdict, evidence, checker,
                                 analyzed_by, claims, overall_verdict, analysis_tier)
                            VALUES (:aid, :claim, :verdict, :ev, 'fact_v1',
                                    'llm_v1', CAST(:claims AS JSONB), :overall, 'on_demand')
                        """),
                        {"aid": article_id, "claim": ct, "verdict": vr,
                         "ev": ev, "claims": claims_json, "overall": overall},
                    )
            else:
                c.execute(
                    text(f"""
                        INSERT INTO {schema}.fact_checks
                            (article_id, claim, verdict, evidence, checker,
                             analyzed_by, claims, overall_verdict, analysis_tier)
                        -- :overall, NOT a hardcoded 'unverifiable'. The prompt
                        -- instructs the model to answer `descriptive_reporting`
                        -- for a claim-free article (market summary, sports score,
                        -- wire copy); writing a literal here THREW THAT AWAY and
                        -- asserted "we tried to verify and could not" instead.
                        VALUES (:aid, 'No verifiable claims detected.', 'unverified', '',
                                'fact_v1', 'llm_v1', '[]'::JSONB, :overall, 'on_demand')
                    """),
                    {"aid": article_id, "overall": overall},
                )
    except Exception as exc:
        _logger.exception(
            "[WTF persist_on_demand] phase1 bias/factcheck article=%s failed: %s",
            article_id, exc,
        )

    # ── Phase 2: mark analyzed — always commits independently ─────────────
    # analysis_tier='quick_v1+full' triggers the full-byline template branch.
    try:
        with _db().begin() as c:
            c.execute(
                text(f"""
                    UPDATE {schema}.articles
                    SET ai_analyzed = true, ai_analyzed_at = NOW(),
                        analysis_tier = 'quick_v1+full'
                    WHERE id = :aid
                """),
                {"aid": article_id},
            )
    except Exception as exc:
        _logger.exception(
            "[WTF persist_on_demand] phase2 mark_analyzed article=%s failed: %s",
            article_id, exc,
        )


def _analyze_bg(article_id: int, title: str, body: str, schema: str,
                hub_url: str, hub_token: str, source_slug: str = "") -> None:
    """Background thread: dispatch bias+factcheck+geo to hub and persist results.
    Safe to call from a daemon thread — uses only module-level objects.
    """
    import logging as _logging
    _bg_logger = _logging.getLogger("wtf-tech")
    results = {}
    for task in ("bias", "factcheck", "geo"):
        try:
            resp = requests.post(
                f"{hub_url}/tools/wtf-hub/api/analyze",
                json={"task": task, "article_id": article_id,
                      "title": title, "body": body, "source_slug": source_slug},
                headers={"Authorization": f"Bearer {hub_token}"},
                timeout=120,
            )
            data = resp.json()
            if data.get("ok") and data.get("result"):
                results[task] = data["result"]
            else:
                _bg_logger.warning(
                    "[WTF analyze] task=%s article_id=%s hub returned not-ok: %s",
                    task, article_id, data.get("error", "no result"),
                )
        except Exception as exc:
            _bg_logger.warning("[WTF analyze] task=%s article_id=%s failed: %s",
                               task, article_id, exc)
    if not results:
        # All hub tasks failed (models cold or hub unreachable).
        # Skip persist entirely so ai_analyzed stays false — user can retry.
        _bg_logger.warning(
            "[WTF analyze] article=%s — all tasks failed, skipping persist (will retry on next Deep Dive click)",
            article_id,
        )
        return
    _persist_on_demand(article_id, results, schema)


@bp.get("/api/v1/articles/<int:article_id>/analyze/status")
def analyze_status(article_id: int):
    """Poll endpoint — returns done=true once ai_analyzed is set."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        done = c.execute(
            text(f"SELECT ai_analyzed FROM {S}.articles WHERE id = :id"),
            {"id": article_id},
        ).scalar()
    return jsonify({"ok": True, "done": bool(done)})


@bp.post("/api/v1/articles/<int:article_id>/analyze")
def analyze_article(article_id: int):
    """On-demand AI analysis — async. Spawns background thread, returns immediately.

    Cache hit (ai_analyzed=true): returns done=true instantly.
    Cache miss: starts background dispatch thread, returns queued=true.
    Browser polls GET /api/v1/articles/<id>/analyze/status until done=true.
    """
    import threading
    from flask import jsonify
    HUB_URL = os.environ.get("WTF_HUB_URL", "")
    HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
    if not HUB_URL or not HUB_TOKEN:
        return jsonify({"ok": False, "error": "hub not configured"}), 503

    S = _schema()
    with _db().connect() as c:
        article = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.ai_analyzed, a.analysis_tier,
                   COALESCE(s.slug, '') AS source_slug
            FROM {S}.articles a
            LEFT JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.id = :id
        """), {"id": article_id}).fetchone()

    if not article:
        return jsonify({"ok": False, "error": "article not found"}), 404

    if article.ai_analyzed:
        return jsonify({"ok": True, "done": True, "cached": True,
                        "article_id": article_id, "tier": article.analysis_tier})

    # Reserve a slot BEFORE spawning. Three outcomes:
    #   already_running -> a thread is already analysing this article; the caller
    #                      gets the same "queued" answer and polls the same status.
    #                      Costs nothing extra to serve, so it is never refused.
    #   at_capacity     -> refuse honestly with Retry-After rather than accept work
    #                      that will not complete.
    #   accepted        -> we own the slot and MUST release it.
    slot = _analyze_guard.try_acquire(article_id)
    if slot == ALREADY_RUNNING:
        return jsonify({"ok": True, "queued": True, "done": False,
                        "already_running": True, "article_id": article_id})
    if slot == AT_CAPACITY:
        resp = jsonify({"ok": False, "error": "analysis_at_capacity",
                        "retry_after": 30, "article_id": article_id,
                        "in_flight": _analyze_guard.in_flight()})
        resp.status_code = 503
        resp.headers["Retry-After"] = "30"
        return resp

    def _run_and_release():
        # try/finally is load-bearing. _analyze_bg guards each of its three tasks
        # individually but has NO top-level handler, so an exception outside that
        # loop (e.g. the persist step) would kill the thread and, without this,
        # leak the slot permanently. Enough leaks and the endpoint wedges closed.
        try:
            _analyze_bg(article_id, article.title or "", article.body or "",
                        S, HUB_URL, HUB_TOKEN,
                        source_slug=article.source_slug or "")
        finally:
            _analyze_guard.release(article_id)

    threading.Thread(target=_run_and_release, daemon=True).start()

    return jsonify({"ok": True, "queued": True, "done": False, "article_id": article_id})


# ---------------------------------------------------------------------------
# Bounded concurrency + in-flight dedup for on-demand analysis (#5791)
# ---------------------------------------------------------------------------
# analyze_article used to spawn a daemon thread per POST with no cap, no dedup and
# no semaphore. PR #2687 bounded the TRIGGER at the consumer edge (5/hour); this
# bounds the WORK, which a caller reaching tech directly is still not limited by.
# PER-WORKER: Dockerfile.tech runs --workers 2, so effective_cap divides the
# advertised aggregate down to what ONE process may actually run at once.
_ANALYZE_MAX = int(os.environ.get("WTF_ANALYZE_MAX_CONCURRENT", "6"))
_ANALYZE_WORKERS = int(os.environ.get("WTF_TECH_GUNICORN_WORKERS", "2"))
_analyze_guard = AnalyzeGuard(max_concurrent=_ANALYZE_MAX, workers=_ANALYZE_WORKERS)


# ---------------------------------------------------------------------------
# In-memory rate limiter for /api/v1/score
# ---------------------------------------------------------------------------
_score_calls: dict[str, list[float]] = defaultdict(list)
_score_lock = threading.Lock()
_SCORE_LIMIT = 5       # requests per day per IP
_SCORE_WINDOW = 86400  # 24 hours in seconds


def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate-limited. Thread-safe."""
    now = time.time()
    with _score_lock:
        _score_calls[ip] = [t for t in _score_calls[ip] if now - t < _SCORE_WINDOW]
        if len(_score_calls[ip]) >= _SCORE_LIMIT:
            return False
        _score_calls[ip].append(now)
        return True


@bp.post("/api/v1/score")
def score():
    """Live article scorer — rate-limited at 5 req/day per IP.

    Request JSON: { "text": "article body here" }
    Response: { "ok": true, "bias": {...}, "factcheck": {...}, "geo": {...}, "processing_ms": N }
    """
    from flask import jsonify, request as freq

    HUB_URL = os.environ.get("WTF_HUB_URL", "")
    HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
    if not HUB_URL or not HUB_TOKEN:
        return jsonify({"ok": False, "error": "scorer not available"}), 503

    client_ip = freq.headers.get("X-Forwarded-For", freq.remote_addr or "unknown").split(",")[0].strip()
    if not _check_rate_limit(client_ip):
        return jsonify({
            "ok": False,
            "error": "Rate limit exceeded. 5 free scores per day per IP.",
            "limit": _SCORE_LIMIT,
            "window_hours": 24,
        }), 429

    data = freq.get_json(force=True, silent=True) or {}
    text_body = (data.get("text") or "")[:5000]
    if not text_body:
        return jsonify({"ok": False, "error": "text is required"}), 400

    hub_timeout = int(os.environ.get("WTF_HUB_TIMEOUT", "10"))
    start = time.time()
    results = {}
    for task in ("bias", "factcheck", "geo"):
        try:
            resp = requests.post(
                f"{HUB_URL}/tools/wtf-hub/api/analyze",
                json={"task": task, "article_id": 0, "title": "", "body": text_body},
                headers={"Authorization": f"Bearer {HUB_TOKEN}"},
                timeout=hub_timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            if d.get("ok"):
                results[task] = d.get("result")
        except Exception as exc:
            current_app.logger.warning("[WTF score] task=%s failed: %s", task, exc)

    processing_ms = int((time.time() - start) * 1000)
    return jsonify({
        "ok": True,
        "bias": results.get("bias"),
        "factcheck": results.get("factcheck"),
        "geo": results.get("geo"),
        "analyzed_by": "BIAS_LLM + VERIFY_LLM + LOCAL_LLM",
        "processing_ms": processing_ms,
    })


@bp.post("/api/v1/flag")
def flag_score():
    """User error-flagging endpoint — writes to wtf.score_flags.

    Request JSON: { "article_id": 123, "flag_type": "bias_wrong", "reason": "..." }
    Response: { "ok": true, "message": "Flag received. Thank you." }
    """
    from flask import jsonify, request as freq

    data = freq.get_json(force=True, silent=True) or {}
    article_id = data.get("article_id")
    flag_type = data.get("flag_type", "other")
    reason = (data.get("reason") or "")[:500]
    client_ip = freq.headers.get("X-Forwarded-For", freq.remote_addr or "unknown").split(",")[0].strip()

    valid_flag_types = {"bias_wrong", "fact_wrong", "geo_wrong", "other"}
    if flag_type not in valid_flag_types:
        flag_type = "other"

    S = _schema()
    try:
        with _db().begin() as c:
            c.execute(text(f"""
                INSERT INTO {S}.score_flags (article_id, user_ip, flag_type, reason)
                VALUES (:aid, :ip, :ft, :r)
            """), {
                "aid": article_id if isinstance(article_id, int) else None,
                "ip": client_ip[:45],
                "ft": flag_type,
                "r": reason or None,
            })
    except Exception as exc:
        bp.logger.error("[WTF flag] DB write failed: %s", exc)
        return jsonify({"ok": False, "error": "flag could not be saved"}), 500

    return jsonify({"ok": True, "message": "Flag received. Thank you for helping improve WTF."})


@bp.get("/score")
def score_page():
    from flask import render_template as _rt
    return _rt("score.html")
