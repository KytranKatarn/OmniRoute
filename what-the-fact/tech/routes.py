import os
import requests
from flask import Blueprint, render_template, session, abort, redirect, url_for
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


@bp.get("/transparency/<int:article_id>")
def transparency(article_id: int):
    S = _schema()
    with _db().begin() as c:
        art = c.execute(text(f"""
            SELECT a.id, a.title, a.url, b.band, b.score, b.rationale, b.heuristic_version
            FROM {S}.articles a LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
        if not art:
            abort(404)
        trail = c.execute(text(f"""
            SELECT event_type, payload, created_at FROM {S}.audit_trail
            WHERE article_id = :id ORDER BY created_at
        """), {"id": article_id}).mappings().all()
    return render_template("transparency.html", a=art, trail=trail)


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
    """Last 10 AI agent analysis events for editorial desk feed."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        bias_rows = c.execute(text(f"""
            SELECT 'B.I.A.S.' AS agent, a.title, bs.band, bs.computed_at AS ts,
                   s.name AS source_name
            FROM {S}.bias_scores bs
            JOIN {S}.articles a ON a.id = bs.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE bs.analyzed_by = 'BIAS_LLM'
            ORDER BY bs.computed_at DESC LIMIT 5
        """)).fetchall()

        fact_rows = c.execute(text(f"""
            SELECT 'V.E.R.I.F.Y.' AS agent, a.title, fc.overall_verdict AS band,
                   fc.checked_at AS ts, s.name AS source_name
            FROM {S}.fact_checks fc
            JOIN {S}.articles a ON a.id = fc.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE fc.analyzed_by = 'VERIFY_LLM'
            ORDER BY fc.checked_at DESC LIMIT 5
        """)).fetchall()

    events = [
        {"agent": r.agent, "title": r.title[:80], "result": r.band or "",
         "source": r.source_name, "ts": r.ts.isoformat() if r.ts else None}
        for r in list(bias_rows) + list(fact_rows)
    ]
    events.sort(key=lambda x: x["ts"] or "", reverse=True)
    return jsonify({"events": events[:10]})


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
