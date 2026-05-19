import os
from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text

api = Blueprint("wtf_api", __name__, url_prefix="/api/v1")
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


@api.get("/articles")
def list_articles():
    limit = min(int(request.args.get("limit", 50)), 200)
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, s.name AS source,
                   b.band, b.score
            FROM {S}.articles a JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            ORDER BY a.published_at DESC LIMIT :n
        """), {"n": limit}).mappings().all()
    return jsonify({"articles": [{
        "id": r["id"], "title": r["title"], "url": r["url"],
        "published_at": r["published_at"].isoformat(), "source": r["source"],
        "bias": {"band": r["band"], "score": r["score"]} if r["band"] else None,
    } for r in rows]})


@api.get("/articles/<int:article_id>")
def get_article(article_id: int):
    S = _schema()
    with _db().begin() as c:
        r = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at, s.name AS source,
                   b.band, b.score, b.rationale, b.heuristic_version
            FROM {S}.articles a JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not r:
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        "id": r["id"], "title": r["title"], "body": r["body"], "url": r["url"],
        "published_at": r["published_at"].isoformat(), "source": r["source"],
        "bias": {"band": r["band"], "score": r["score"], "rationale": r["rationale"],
                 "heuristic_version": r["heuristic_version"]} if r["band"] else None,
    })


@api.get("/articles/<int:article_id>/audit")
def get_audit(article_id: int):
    S = _schema()
    with _db().begin() as c:
        exists = c.execute(text(f"SELECT 1 FROM {S}.articles WHERE id=:id"), {"id": article_id}).scalar()
        if not exists:
            return jsonify({"error": "not_found"}), 404
        rows = c.execute(text(f"""
            SELECT event_type, payload, created_at FROM {S}.audit_trail
            WHERE article_id = :id ORDER BY created_at
        """), {"id": article_id}).mappings().all()
    return jsonify({"events": [{
        "event_type": r["event_type"], "payload": r["payload"],
        "at": r["created_at"].isoformat(),
    } for r in rows]})


@api.get("/clusters")
def list_clusters():
    """List recent story clusters with their summaries."""
    limit = min(int(request.args.get("limit", 20)), 100)
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.earliest_published_at, sc.latest_published_at,
                   sm.headline, sm.brief
            FROM {S}.story_clusters sc
            LEFT JOIN {S}.summaries sm ON sm.cluster_id = sc.id
            ORDER BY sc.latest_published_at DESC LIMIT :n
        """), {"n": limit}).mappings().all()
    return jsonify({"clusters": [{
        "id": r["id"],
        "representative_title": r["representative_title"],
        "article_count": r["article_count"],
        "earliest_published_at": r["earliest_published_at"].isoformat(),
        "latest_published_at": r["latest_published_at"].isoformat(),
        "summary": {"headline": r["headline"], "brief": r["brief"]} if r["headline"] else None,
    } for r in rows]})


@api.get("/clusters/<int:cluster_id>")
def get_cluster(cluster_id: int):
    """Get a story cluster with full summary and article list."""
    S = _schema()
    with _db().begin() as c:
        sc = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.earliest_published_at, sc.latest_published_at,
                   sm.headline, sm.brief, sm.full_text, sm.summarizer, sm.article_ids
            FROM {S}.story_clusters sc
            LEFT JOIN {S}.summaries sm ON sm.cluster_id = sc.id
            WHERE sc.id = :id
        """), {"id": cluster_id}).mappings().first()
        if not sc:
            return jsonify({"error": "not_found"}), 404
        articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, s.name AS source, b.band
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.cluster_id = :cid
            ORDER BY a.published_at DESC
        """), {"cid": cluster_id}).mappings().all()
    return jsonify({
        "id": sc["id"],
        "representative_title": sc["representative_title"],
        "article_count": sc["article_count"],
        "earliest_published_at": sc["earliest_published_at"].isoformat(),
        "latest_published_at": sc["latest_published_at"].isoformat(),
        "summary": {
            "headline": sc["headline"],
            "brief": sc["brief"],
            "full_text": sc["full_text"],
            "summarizer": sc["summarizer"],
        } if sc["headline"] else None,
        "articles": [{
            "id": r["id"], "title": r["title"], "url": r["url"],
            "published_at": r["published_at"].isoformat(),
            "source": r["source"],
            "bias_band": r["band"],
        } for r in articles],
    })


@api.get("/sources")
def list_sources():
    """List all registered sources with rolling outlet bias scores."""
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT s.id, s.slug, s.name, s.url, s.rss_feed, s.bias_lean,
                   s.country, s.language,
                   ob.avg_score, ob.band AS computed_band, ob.article_count,
                   ob.computed_at
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores ob ON ob.source_id = s.id
            ORDER BY s.name
        """)).mappings().all()
    return jsonify({"sources": [{
        "id": r["id"], "slug": r["slug"], "name": r["name"],
        "url": r["url"], "rss_feed": r["rss_feed"],
        "seeded_bias_lean": r["bias_lean"],
        "computed_bias": {
            "band": r["computed_band"],
            "avg_score": r["avg_score"],
            "article_count": r["article_count"],
            "computed_at": r["computed_at"].isoformat() if r["computed_at"] else None,
        } if r["computed_band"] else None,
    } for r in rows]})


@api.get("/articles/<int:article_id>/fact-checks")
def get_fact_checks(article_id: int):
    """Get fact-check claims + verdicts for an article."""
    S = _schema()
    with _db().begin() as c:
        exists = c.execute(text(f"SELECT 1 FROM {S}.articles WHERE id=:id"), {"id": article_id}).scalar()
        if not exists:
            return jsonify({"error": "not_found"}), 404
        rows = c.execute(text(f"""
            SELECT id, claim, verdict, evidence, checker, checked_at
            FROM {S}.fact_checks
            WHERE article_id = :id
            ORDER BY checked_at
        """), {"id": article_id}).mappings().all()
    return jsonify({"article_id": article_id, "fact_checks": [{
        "id": r["id"], "claim": r["claim"], "verdict": r["verdict"],
        "evidence": r["evidence"], "checker": r["checker"],
        "checked_at": r["checked_at"].isoformat(),
    } for r in rows]})


@api.post("/articles/<int:article_id>/analyze")
def analyze_article(article_id: int):
    """Deep Dive — dispatch V.E.R.I.F.Y. deep_analysis and persist result.

    Checks wtf.llm_analyses cache first (returns instantly if hit).
    On cache miss: calls hub /api/analyze, saves to llm_analyses + fact_checks,
    marks article ai_analyzed=true.
    """
    import json as _json
    import os as _os
    import urllib.error
    import urllib.parse
    import urllib.request

    S = _schema()

    # 1. Cache check — return immediately if already analyzed
    with _db().begin() as c:
        cached = c.execute(text(f"""
            SELECT sections_json, model
            FROM {S}.llm_analyses
            WHERE article_id = :id AND completed_at IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
        """), {"id": article_id}).mappings().first()
    if cached:
        claims = (cached["sections_json"] or {}).get("key_claims", [])
        return jsonify({"ok": True, "claims_count": len(claims), "cached": True,
                        "analysis_tier": "full"})

    # 2. Fetch article for dispatch
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, s.slug AS source_slug
            FROM {S}.articles a JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404

    # 3. Dispatch to hub V.E.R.I.F.Y. via /api/analyze
    hub_url = _os.environ.get("WTF_HUB_URL", "http://100.64.0.4:3000")
    hub_token = _os.environ.get("WTF_HUB_TOKEN", "")
    payload = _json.dumps({
        "task": "deep_analysis",
        "article_id": article_id,
        "title": (row["title"] or "")[:200],
        "body": (row["body"] or "")[:3000],
        "source_slug": row["source_slug"] or "",
    }).encode()
    req = urllib.request.Request(
        f"{hub_url}/tools/wtf-hub/api/analyze",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {hub_token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            hub_result = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"hub {e.code}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    if hub_result.get("rate_limited"):
        return jsonify({"ok": True, "rate_limited": True,
                        "retry_after": hub_result.get("retry_after", 30),
                        "claims_count": 0, "analysis_tier": "full"})

    if not hub_result.get("ok"):
        return jsonify({"ok": False, "error": hub_result.get("error", "dispatch failed")}), 500

    sections = hub_result.get("result") or {}
    model = hub_result.get("agent", "V.E.R.I.F.Y.")
    claims = sections.get("key_claims", []) if isinstance(sections, dict) else []

    # 4. Persist — llm_analyses (full result) + fact_checks (claims) + mark article
    with _db().begin() as c:
        c.execute(text(f"""
            INSERT INTO {S}.llm_analyses (article_id, sections_json, model, completed_at)
            VALUES (:aid, :sj::jsonb, :model, NOW())
            ON CONFLICT (article_id, model) DO UPDATE
                SET sections_json = EXCLUDED.sections_json,
                    completed_at  = NOW()
        """), {"aid": article_id, "sj": _json.dumps(sections), "model": model})

        # Map free-form verdict to the CHECK constraint values
        _verdict_map = {
            "verified": "true", "true": "true", "mostly true": "mostly_true",
            "mixed": "mixed", "disputed": "false", "false": "false",
        }
        raw_verdict = (sections.get("bias_summary", {}).get("band") or "unverified").lower() if isinstance(sections, dict) else "unverified"
        verdict_val = _verdict_map.get(raw_verdict, "unverified")
        editorial = (sections.get("editorial_take") or "")[:1000] if isinstance(sections, dict) else ""
        # Only insert if no existing deep-dive row for this article+checker
        existing = c.execute(text(f"""
            SELECT id FROM {S}.fact_checks WHERE article_id = :aid AND analyzed_by = :by LIMIT 1
        """), {"aid": article_id, "by": model}).scalar()
        if not existing:
            c.execute(text(f"""
                INSERT INTO {S}.fact_checks
                    (article_id, claim, verdict, evidence, checker,
                     overall_verdict, claims, analyzed_by, checked_at)
                VALUES (:aid, 'Deep Dive Analysis', :verdict, :evidence, :checker,
                        :overall, :claims::jsonb, :by, NOW())
            """), {"aid": article_id, "verdict": verdict_val, "evidence": editorial,
                   "checker": model, "overall": raw_verdict,
                   "claims": _json.dumps(claims), "by": model})

        c.execute(text(f"""
            UPDATE {S}.articles
            SET ai_analyzed = true, ai_analyzed_at = NOW()
            WHERE id = :id
        """), {"id": article_id})

    return jsonify({"ok": True, "claims_count": len(claims), "analysis_tier": "full"})
