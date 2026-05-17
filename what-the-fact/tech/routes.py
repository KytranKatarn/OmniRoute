import os
import threading
import time
import requests
from collections import defaultdict
from flask import Blueprint, current_app, render_template, session, abort, redirect, url_for
from sqlalchemy import create_engine, text

bp = Blueprint("wtf_tech", __name__)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


@bp.get("/")
def index():
    return render_template("index.html")


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
            FROM {S}.fact_checks WHERE article_id = :id ORDER BY id
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
    return render_template(
        "transparency.html",
        a=art,
        fact_checks=[dict(r) for r in fc],
        cluster=dict(cluster) if cluster else None,
        trail=trail,
    )


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
    """Province-level news stats for Canada map (last 24h)."""
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

    return jsonify({"provinces": provinces})


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


@bp.post("/api/v1/articles/<int:article_id>/analyze")
def analyze_article(article_id: int):
    """On-demand AI analysis for an article not yet AI-analyzed."""
    from flask import jsonify
    HUB_URL = os.environ.get("WTF_HUB_URL", "")
    HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
    if not HUB_URL or not HUB_TOKEN:
        return jsonify({"ok": False, "error": "hub not configured"}), 503

    S = _schema()
    with _db().connect() as c:
        article = c.execute(text(f"""
            SELECT id, title, body FROM {S}.articles WHERE id = :id
        """), {"id": article_id}).fetchone()

    if not article:
        return jsonify({"ok": False, "error": "article not found"}), 404

    results = {}
    for task in ("bias", "factcheck", "geo"):
        try:
            resp = requests.post(
                f"{HUB_URL}/tools/wtf-hub/api/analyze",
                json={"task": task, "article_id": article_id,
                      "title": article.title or "", "body": article.body or ""},
                headers={"Authorization": f"Bearer {HUB_TOKEN}"},
                timeout=90,
            )
            data = resp.json()
            if data.get("ok"):
                results[task] = data.get("result")
        except Exception as exc:
            bp.logger.warning(
                "[WTF analyze] task=%s article_id=%s failed: %s", task, article_id, exc
            )

    return jsonify({"ok": True, "results": results, "article_id": article_id})


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
