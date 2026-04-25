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
