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
    """#3005 — Articles with optional riding-level geo and source filters.

    Query params:
      limit     int   default 50, max 200
      province  str   e.g. ON, QC — filters by province_code from L.O.C.A.L.
      city      str   e.g. Ottawa — case-insensitive substring on city field
      geo_scope str   national | provincial | municipal | international
      source    str   source slug
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    province   = request.args.get("province", "").upper().strip() or None
    city       = request.args.get("city", "").strip() or None
    geo_scope  = request.args.get("geo_scope", "").strip() or None
    source_slug = request.args.get("source", "").strip() or None

    geo_filters = []
    params: dict = {"n": limit}
    if province:
        geo_filters.append("a.province_code = :province")
        params["province"] = province
    if city:
        geo_filters.append("a.city ILIKE :city")
        params["city"] = f"%{city}%"
    if geo_scope:
        geo_filters.append("a.geo_scope = :geo_scope")
        params["geo_scope"] = geo_scope
    if source_slug:
        geo_filters.append("s.slug = :source_slug")
        params["source_slug"] = source_slug
    where_extra = ("AND " + " AND ".join(geo_filters)) if geo_filters else ""

    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, s.slug AS source_slug,
                   a.province_code, a.city, a.geo_scope,
                   b.band, b.score
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 {where_extra}
            ORDER BY a.published_at DESC LIMIT :n
        """), params).mappings().all()
    return jsonify({"articles": [{
        "id": r["id"], "title": r["title"], "url": r["url"],
        "published_at": r["published_at"].isoformat(),
        "source": r["source"], "source_slug": r["source_slug"],
        "geo": {
            "province_code": r["province_code"],
            "city": r["city"],
            "geo_scope": r["geo_scope"],
        } if r["province_code"] or r["city"] else None,
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
                   sc.source_count, sc.coverage_gap_score, sc.certainty_label,
                   sm.headline, sm.brief
            FROM {S}.story_clusters sc
            LEFT JOIN {S}.summaries sm ON sm.cluster_id = sc.id
            ORDER BY sc.latest_published_at DESC LIMIT :n
        """), {"n": limit}).mappings().all()
    return jsonify({"clusters": [{
        "id": r["id"],
        "representative_title": r["representative_title"],
        "article_count": r["article_count"],
        "source_count": r["source_count"],
        "coverage_gap_score": r["coverage_gap_score"],
        "certainty_label": r["certainty_label"],
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
                   sc.source_count, sc.coverage_gap_score, sc.certainty_label,
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
        "source_count": sc["source_count"],
        "coverage_gap_score": sc["coverage_gap_score"],
        "certainty_label": sc["certainty_label"],
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
    """#3127 — Sources with CRTC ownership + rolling bias scores.

    Query params:
      owner_type  str  filter by: public | corporate | independent | non_profit
      language    str  filter by: en | fr
    """
    S = _schema()
    owner_type = request.args.get("owner_type")
    language = request.args.get("language")
    filters = []
    params: dict = {}
    if owner_type:
        filters.append("s.owner_type = :owner_type")
        params["owner_type"] = owner_type
    if language:
        filters.append("s.language = :language")
        params["language"] = language
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT s.id, s.slug, s.name, s.url, s.rss_feed, s.bias_lean,
                   s.country, s.language, s.owner_name, s.owner_type,
                   ob.avg_score, ob.band AS computed_band, ob.article_count,
                   ob.computed_at
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores ob ON ob.source_id = s.id
            {where}
            ORDER BY s.owner_type, s.name
        """), params).mappings().all()
    return jsonify({"sources": [{
        "id": r["id"], "slug": r["slug"], "name": r["name"],
        "url": r["url"], "language": r["language"],
        "ownership": {
            "owner_name": r["owner_name"],
            "owner_type": r["owner_type"],
        },
        "seeded_bias_lean": r["bias_lean"],
        "computed_bias": {
            "band": r["computed_band"],
            "avg_score": r["avg_score"],
            "article_count": r["article_count"],
            "computed_at": r["computed_at"].isoformat() if r["computed_at"] else None,
        } if r["computed_band"] else None,
    } for r in rows]})


@api.get("/blindspots")
def blindspot_feed():
    """#3006 — Stories covered by very few outlets (underreported / ignored).

    A blindspot is a cluster with low coverage_gap_score and >= 2 articles,
    published within the look-back window.

    Query params:
      limit         int   default 20   max 100
      days          int   default 7    look-back window
      max_gap_score float default 0.15 coverage threshold (0.15 = <15% of outlets)
    """
    limit = min(int(request.args.get("limit", 20)), 100)
    days = min(int(request.args.get("days", 7)), 90)
    max_gap = float(request.args.get("max_gap_score", 0.15))
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.source_count, sc.coverage_gap_score, sc.certainty_label,
                   sc.earliest_published_at, sc.latest_published_at,
                   sm.headline, sm.brief
            FROM {S}.story_clusters sc
            LEFT JOIN {S}.summaries sm ON sm.cluster_id = sc.id
            WHERE sc.coverage_gap_score > 0
              AND sc.coverage_gap_score <= :max_gap
              AND sc.article_count >= 2
              AND sc.latest_published_at >= NOW() - INTERVAL '1 day' * :days
            ORDER BY sc.coverage_gap_score ASC, sc.latest_published_at DESC
            LIMIT :n
        """), {"max_gap": max_gap, "days": days, "n": limit}).mappings().all()
    return jsonify({
        "days": days,
        "max_gap_score": max_gap,
        "blindspots": [{
            "id": r["id"],
            "representative_title": r["representative_title"],
            "article_count": r["article_count"],
            "source_count": r["source_count"],
            "coverage_gap_score": r["coverage_gap_score"],
            "certainty_label": r["certainty_label"],
            "earliest_published_at": r["earliest_published_at"].isoformat(),
            "latest_published_at": r["latest_published_at"].isoformat(),
            "summary": {"headline": r["headline"], "brief": r["brief"]} if r["headline"] else None,
        } for r in rows],
    })


@api.get("/divergence")
def coverage_divergence():
    """#3003 — French vs English coverage divergence per story cluster.

    Returns clusters where French and English outlets tell a different story —
    either by bias score gap or by one language not covering the story at all.

    Query params:
      limit          int   default 20
      days           int   default 30  look-back window
      min_divergence float default 0.1 minimum |en_avg_score - fr_avg_score|
    """
    limit = min(int(request.args.get("limit", 20)), 100)
    days = min(int(request.args.get("days", 30)), 90)
    min_div = float(request.args.get("min_divergence", 0.1))
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            WITH cluster_lang AS (
                SELECT
                    a.cluster_id,
                    COUNT(*)             FILTER (WHERE s.language = 'en') AS en_count,
                    COUNT(*)             FILTER (WHERE s.language = 'fr') AS fr_count,
                    AVG(b.score)         FILTER (WHERE s.language = 'en') AS en_avg_score,
                    AVG(b.score)         FILTER (WHERE s.language = 'fr') AS fr_avg_score
                FROM {S}.articles a
                JOIN {S}.sources s ON s.id = a.source_id
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                WHERE a.cluster_id IS NOT NULL
                  AND a.published_at >= NOW() - INTERVAL '1 day' * :days
                GROUP BY a.cluster_id
            )
            SELECT
                cl.cluster_id        AS id,
                sc.representative_title,
                sc.article_count,
                sc.certainty_label,
                sc.latest_published_at,
                cl.en_count,
                cl.fr_count,
                ROUND(cl.en_avg_score::numeric, 3) AS en_avg_score,
                ROUND(cl.fr_avg_score::numeric, 3) AS fr_avg_score,
                ROUND(ABS(
                    COALESCE(cl.en_avg_score, 0) - COALESCE(cl.fr_avg_score, 0)
                )::numeric, 3)       AS divergence_score,
                (cl.fr_count = 0)    AS en_only,
                (cl.en_count = 0)    AS fr_only
            FROM cluster_lang cl
            JOIN {S}.story_clusters sc ON sc.id = cl.cluster_id
            WHERE (cl.en_count > 0 OR cl.fr_count > 0)
              AND ABS(COALESCE(cl.en_avg_score, 0) - COALESCE(cl.fr_avg_score, 0)) >= :min_div
            ORDER BY divergence_score DESC, sc.latest_published_at DESC
            LIMIT :n
        """), {"days": days, "min_div": min_div, "n": limit}).mappings().all()
    return jsonify({
        "days": days,
        "min_divergence": min_div,
        "divergence": [{
            "id": r["id"],
            "representative_title": r["representative_title"],
            "article_count": r["article_count"],
            "certainty_label": r["certainty_label"],
            "latest_published_at": r["latest_published_at"].isoformat(),
            "en_count": r["en_count"],
            "fr_count": r["fr_count"],
            "en_avg_score": float(r["en_avg_score"]) if r["en_avg_score"] is not None else None,
            "fr_avg_score": float(r["fr_avg_score"]) if r["fr_avg_score"] is not None else None,
            "divergence_score": float(r["divergence_score"]),
            "en_only": bool(r["en_only"]),
            "fr_only": bool(r["fr_only"]),
        } for r in rows],
    })


@api.get("/sources/<slug>/bias-drift")
def source_bias_drift(slug: str):
    """Bias drift history for a source — daily snapshots over the last N days.

    Query params:
      days  (int, default 90) — look-back window
    """
    days = min(int(request.args.get("days", 90)), 365)
    S = _schema()
    with _db().begin() as c:
        source = c.execute(
            text(f"SELECT id, name, slug FROM {S}.sources WHERE slug = :slug"),
            {"slug": slug},
        ).mappings().first()
        if not source:
            return jsonify({"error": "source not found"}), 404

        rows = c.execute(text(f"""
            SELECT snapshot_date, avg_score, band, article_count, window_days
            FROM {S}.outlet_bias_history
            WHERE source_id = :sid
              AND snapshot_date >= CURRENT_DATE - :days
            ORDER BY snapshot_date ASC
        """), {"sid": source["id"], "days": days}).mappings().all()

    return jsonify({
        "source": {"id": source["id"], "slug": source["slug"], "name": source["name"]},
        "days_requested": days,
        "snapshots": [{
            "date": r["snapshot_date"].isoformat(),
            "avg_score": r["avg_score"],
            "band": r["band"],
            "article_count": r["article_count"],
            "window_days": r["window_days"],
        } for r in rows],
    })


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


# WTF News & Media agent roster — mirrors consumer TEAM_AGENTS (name/role/model
# are curated, stable facts). Each "activity" entry maps the agent to the wtf
# pipeline table that records its per-article output, so articles_processed_7d /
# last_active come straight from the data. Agents whose work isn't logged in the
# wtf schema (social distribution, weather) report null activity. Kept here (not
# fetched from the hub) so this public endpoint stays up even when the hub is busy.
WTF_AGENTS = [
    {"name": "F.A.C.T.", "full": "Factual Analysis, Credibility & Transparency",
     "role": "Director & Orchestrator", "model": "gemma3:12b",
     "activity": {"table": "audit_trail", "ts": "created_at", "where": "event_type = 'ingested'"}},
    {"name": "B.I.A.S.", "full": "Balanced Information Analysis & Scoring",
     "role": "Bias Analyst", "model": "gemma2:9b",
     "activity": {"table": "bias_scores", "ts": "computed_at", "where": None}},
    {"name": "V.E.R.I.F.Y.", "full": "Verification, Evidence Review & Integrity",
     "role": "Fact-Checker", "model": "gemma2:9b",
     "activity": {"table": "fact_checks", "ts": "checked_at", "where": None}},
    {"name": "L.O.C.A.L.", "full": "Local Observer, Coverage & Area Liaison",
     "role": "Geographic Intelligence Analyst", "model": "llama3.2:3b",
     "activity": {"table": "articles", "ts": "ai_analyzed_at", "where": "province_code IS NOT NULL"}},
    {"name": "I.N.K.", "full": "Investigative News & Knowledge",
     "role": "News Investigator", "model": "dolphin3",
     "activity": {"table": "story_clusters", "ts": "created_at", "where": None}},
    {"name": "D.R.A.F.T.", "full": "Data Reduction & Factual Translation",
     "role": "Staff Writer", "model": "dolphin3",
     "activity": {"table": "summaries", "ts": "created_at", "where": None}},
    {"name": "P.U.B.L.I.S.H.", "full": "Publish & Unified Broadcasting",
     "role": "Broadcast Editor", "model": "mistral:7b", "activity": None},
    {"name": "A.U.R.O.R.A.",
     "full": "Atmospheric & Universal Resource for Observation, Research & Analysis",
     "role": "Weather Intelligence", "model": "qwen2.5:7b", "activity": None},
]


@api.get("/agents")
def list_agents():
    """#3367 — WTF News & Media AI agents: roster + 7-day activity stats.

    Returns each agent's name/acronym, role, model, is_active, plus live
    pipeline activity: articles_processed_7d (count in the last 7 days) and
    last_active (most recent output, all-time). Agents whose output isn't
    recorded in the wtf schema (P.U.B.L.I.S.H. distribution, A.U.R.O.R.A.
    weather) report null activity. No auth; CORS-open (handled app-wide).
    """
    S = _schema()
    out = []
    with _db().begin() as c:
        for ag in WTF_AGENTS:
            processed = None
            last_active = None
            act = ag.get("activity")
            if act:
                where = f"AND {act['where']}" if act.get("where") else ""
                try:
                    row = c.execute(text(f"""
                        SELECT
                            COUNT(*) FILTER (
                                WHERE {act['ts']} >= NOW() - INTERVAL '7 days'
                            ) AS n7,
                            MAX({act['ts']}) AS last_ts
                        FROM {S}.{act['table']}
                        WHERE 1=1 {where}
                    """)).mappings().first()
                    processed = int(row["n7"]) if row and row["n7"] is not None else 0
                    last_active = (
                        row["last_ts"].isoformat() if row and row["last_ts"] else None
                    )
                except Exception:
                    # A schema drift on one table must not fail the whole roster.
                    processed = None
                    last_active = None
            out.append({
                "name": ag["name"],
                "acronym": ag["name"],
                "full_name": ag["full"],
                "role": ag["role"],
                "model": ag["model"],
                "is_active": True,
                "articles_processed_7d": processed,
                "last_active": last_active,
            })
    return jsonify({"agents": out, "count": len(out)})
