import datetime
import json
import os
import time
import urllib.request

from flask import Blueprint, render_template, abort, Response

from sqlalchemy import create_engine, text
from .auth import is_subscriber

bp = Blueprint("wtf", __name__)
_engine = None
_PLATFORM = "https://platform.kytranempowerment.com"

# Sources known to restrict RSS to snippet-only (paywalled originals).
_PAYWALLED_SOURCES = frozenset({
    "montreal_gazette", "national_post", "financial_post", "vancouver_sun",
    "calgary_herald", "edmonton_journal", "ottawa_citizen", "toronto_star",
    "globe_mail", "journal_de_montreal", "le_devoir", "la_presse",
    "le_soleil", "le_quotidien",
})

# Portrait cache — fetches live URLs from platform /api/public/directory
# so agent portraits update automatically when approved without a code change.
_PORTRAIT_CACHE: dict = {}
_PORTRAIT_CACHE_TTL = 3600  # 1 hour

# Agent dispatch-stats cache (#2956) — fetches per-agent path data from
# hub WTF Hub mesh endpoint. 60s TTL keeps the activity page snappy while
# absorbing hub latency. Falls back to empty dict on any error so the page
# always renders.
_AGENT_STATS_CACHE: dict = {}
_AGENT_STATS_CACHE_TTL = 60


def _fetch_agent_stats() -> dict:
    """Return {agent_name: {count, success_rate, avg_ms, top_model, last_node}}.

    Calls hub /tools/wtf-hub/api/agent-stats via mesh (WTF_HUB_URL). 60s cache.
    Returns {} on any error — caller renders without dispatch subtitle if empty.
    """
    now = time.time()
    if _AGENT_STATS_CACHE.get("ts", 0) + _AGENT_STATS_CACHE_TTL > now:
        return _AGENT_STATS_CACHE.get("data", {})
    hub_url = os.environ.get("WTF_HUB_URL", "")
    hub_token = os.environ.get("WTF_HUB_TOKEN", "")
    if not hub_url or not hub_token:
        return {}
    try:
        req = urllib.request.Request(
            f"{hub_url}/tools/wtf-hub/api/agent-stats",
            headers={
                "Authorization": f"Bearer {hub_token}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        agents = data.get("agents") or {} if data.get("ok") else {}
        _AGENT_STATS_CACHE["ts"] = now
        _AGENT_STATS_CACHE["data"] = agents
        return agents
    except Exception:
        # Fail-open: stale cache is better than no data; empty if we never got it
        return _AGENT_STATS_CACHE.get("data", {})


def _get_portrait_lookup() -> dict:
    """Return {display_name: portrait_url} from platform directory. Cached 1h."""
    now = time.time()
    if _PORTRAIT_CACHE.get("ts", 0) + _PORTRAIT_CACHE_TTL > now:
        return _PORTRAIT_CACHE.get("data", {})
    try:
        req = urllib.request.Request(
            f"{_PLATFORM}/api/public/directory",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        lookup = {
            a["display_name"]: a.get("avatar_thumb_url") or a.get("avatar_url")
            for a in data.get("agents", [])
            if a.get("display_name") and (a.get("avatar_thumb_url") or a.get("avatar_url"))
        }
        _PORTRAIT_CACHE["data"] = lookup
        _PORTRAIT_CACHE["ts"] = now
        return lookup
    except Exception:
        return _PORTRAIT_CACHE.get("data", {})


def _db():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _schema():
    return os.environ.get("WTF_SCHEMA", "wtf")


TEAM_AGENTS = [
    {
        "name": "F.A.C.T.",
        "full": "Factual Analysis, Credibility & Transparency",
        "role": "Director & Orchestrator",
        "model": "gemma3:12b",
        "description": "F.A.C.T. leads every ingest cycle — selecting the stories most worth investigating deeply, coordinating the team, and ensuring coverage is fair and complete.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/c78a58f0-ee5.png",
        "accent_colour": "#dc2626",
    },
    {
        "name": "B.I.A.S.",
        "full": "Balanced Information Analysis & Scoring",
        "role": "Bias Analyst",
        "model": "gemma2:9b",
        "description": "B.I.A.S. reads every priority article and scores it on the political spectrum, surfacing the trigger phrases and framing choices that reveal editorial perspective.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/05821aee-a2e.png",
        "accent_colour": "#f59e0b",
    },
    {
        "name": "V.E.R.I.F.Y.",
        "full": "Verification, Evidence Review & Integrity",
        "role": "Fact-Checker",
        "model": "gemma2:9b",
        "description": "V.E.R.I.F.Y. extracts verifiable claims from each article and assigns a verdict — verified, mixed, disputed, or unverifiable — with reasoning.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/5d0d0525-a4e.png",
        "accent_colour": "#10b981",
    },
    {
        "name": "L.O.C.A.L.",
        "full": "Local Observer, Coverage & Area Liaison",
        "role": "Geographic Intelligence Analyst",
        "model": "llama3.2:3b",
        "description": "L.O.C.A.L. maps every story to a Canadian province, tracks coverage gaps across regions, and identifies news deserts where communities go unheard.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-29/7810b5ae-31f.png",
        "accent_colour": "#3b82f6",
    },
    {
        "name": "I.N.K.",
        "full": "Investigative News & Knowledge",
        "role": "News Investigator",
        "model": "dolphin3",
        "description": "I.N.K. will detect investigative story threads across article clusters — finding the through-line when the same story unfolds across days and outlets.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/9e1efa5f-5a7.png",
        "accent_colour": "#6b7280",
    },
    {
        "name": "D.R.A.F.T.",
        "full": "Data Reduction & Factual Translation",
        "role": "Staff Writer",
        "model": "dolphin3",
        "description": "D.R.A.F.T. will generate WTF editorial summaries — translating dense news cycles into plain-language explainers.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/70bc27b1-ede.png",
        "accent_colour": "#6b7280",
    },
    {
        "name": "P.U.B.L.I.S.H.",
        "full": "Publish & Unified Broadcasting",
        "role": "Broadcast Editor",
        "model": "mistral:7b",
        "description": "P.U.B.L.I.S.H. will push top stories to social media and newsletter subscribers, bringing AI journalism to where Canadians actually consume news.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/e7149ec2-f73.png",
        "accent_colour": "#6b7280",
    },
    {
        "name": "A.U.R.O.R.A.",
        "full": "Atmospheric & Universal Resource for Observation, Research & Analysis",
        "role": "Weather Intelligence",
        "model": "qwen2.5:7b",
        "description": "Environment Canada + NASA EarthData + NOAA. Weather intelligence integrated into every story — because in Canada, the weather IS the news.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-30/7b1193b5-868.png",
        "accent_colour": "#7c3aed",
    },
]


@bp.get("/api/stats")
def api_stats():
    from flask import jsonify
    S = _schema()
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM {S}.sources) AS sources,
              (SELECT COUNT(*) FROM {S}.articles) AS articles,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed=true) AS llm_analyzed,
              (SELECT COUNT(*) FROM {S}.bias_scores) AS bias_scored,
              (SELECT COUNT(*) FROM {S}.story_clusters) AS clusters
        """)).mappings().first()
    return jsonify(dict(row))


@bp.get("/join")
def join():
    S = _schema()
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
        total_articles = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.articles")
        ).scalar() or 0
    return render_template("connect.html", source_count=source_count,
                           total_articles=total_articles)


@bp.get("/news")
def news():
    from flask import request as _req
    S = _schema()
    PAGE_SIZE = 50
    page = max(1, int(_req.args.get("page", 1)))
    VALID_BANDS = {"all", "left", "center-left", "center", "center-right", "right"}
    VALID_PROVINCES = {"all", "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
    band_filter = _req.args.get("band", "all")
    province_filter = (_req.args.get("province") or "all").upper()
    if band_filter not in VALID_BANDS:
        band_filter = "all"
    if province_filter not in VALID_PROVINCES:
        province_filter = "all"
    offset = (page - 1) * PAGE_SIZE

    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
        band_params = {}
        where_clauses = []
        if band_filter != "all":
            where_clauses.append("b.band = :band")
            band_params["band"] = band_filter
        if province_filter != "all":
            where_clauses.append("a.province_code = :province")
            band_params["province"] = province_filter
        band_where = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""
        total = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 {band_where}
        """), band_params).scalar() or 0
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band, a.ai_analyzed, a.province_code,
                   a.cluster_id, sc.article_count AS cluster_size,
                   (SELECT STRING_AGG(m.name, ', ' ORDER BY m.name)
                    FROM {S}.article_mp_tags t
                    JOIN parliament.mps m ON m.id = t.mp_id
                    WHERE t.article_id = a.id) AS mp_mentions
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
            WHERE 1=1 {band_where}
            ORDER BY a.published_at DESC
            LIMIT {PAGE_SIZE} OFFSET {offset}
        """), band_params).mappings().all()

        sources = c.execute(text(f"""
            SELECT s.name, s.url, s.bias_lean,
                   obs.avg_score, obs.band AS bias_band,
                   COUNT(a.id) AS article_count
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN {S}.articles a ON a.source_id = s.id
            GROUP BY s.id, s.name, s.url, s.bias_lean, obs.avg_score, obs.band
            ORDER BY COUNT(a.id) DESC
        """)).mappings().all()

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render_template("news.html", articles=rows, source_count=source_count,
                           total=total, page=page, total_pages=total_pages,
                           page_size=PAGE_SIZE, band_filter=band_filter,
                           province_filter=province_filter,
                           sources=[dict(s) for s in sources],
                           is_subscriber=is_subscriber())


@bp.get("/activity")
def activity():
    from flask import request as _req
    S = _schema()
    PAGE_SIZE = 100
    page = max(1, int(_req.args.get("page", 1)))
    agent_filter = _req.args.get("agent", "all")
    offset = (page - 1) * PAGE_SIZE

    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
        stats = c.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM {S}.articles) AS total_articles,
              (SELECT COUNT(*) FROM {S}.bias_scores) AS bias_scored,
              (SELECT COUNT(*) FROM {S}.fact_checks) AS fact_checked,
              (SELECT COUNT(DISTINCT article_id) FROM {S}.fact_checks) AS fact_checked_articles,
              (SELECT COUNT(*) FROM {S}.articles WHERE province_code IS NOT NULL) AS geo_mapped,
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested') AS fact_ingested,
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested' AND created_at > NOW() - INTERVAL '24 hours') AS articles_24h,
              (SELECT COUNT(*) FROM {S}.bias_scores WHERE computed_at > NOW() - INTERVAL '24 hours') AS bias_24h,
              (SELECT COUNT(DISTINCT article_id) FROM {S}.fact_checks WHERE checked_at > NOW() - INTERVAL '24 hours') AS verify_24h,
              (SELECT COUNT(*) FROM {S}.summaries WHERE created_at > NOW() - INTERVAL '24 hours') AS draft_24h,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE created_at > NOW() - INTERVAL '24 hours') AS ink_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed_at > NOW() - INTERVAL '24 hours') AS llm_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed_at > NOW() - INTERVAL '1 hour') AS llm_analyzed_1h,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count = 1) AS cluster_singletons,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count BETWEEN 2 AND 3) AS cluster_small,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count BETWEEN 4 AND 9) AS cluster_medium,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count >= 10) AS cluster_large,
              (SELECT COUNT(*) FROM {S}.summaries) AS draft_summarized,
              (SELECT COUNT(*) FROM {S}.story_clusters) AS ink_clustered,
              (SELECT COUNT(*) FROM {S}.articles WHERE cluster_id IS NOT NULL) AS ink_articles_clustered,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed=true) AS llm_analyzed,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier='pending') AS tier_pending,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier='quick_v1') AS tier_quick_v1,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier='quick_v1+full') AS tier_quick_v1_full,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier IN ('quick_v1_failed', 'quick_v1_failed+full', 'quick_v1+failed')) AS tier_quick_v1_failed,
              (SELECT COUNT(*) FROM {S}.articles WHERE tier2_pending=true) AS tier2_pending_count,
              -- Pipeline health counters (#2955) — surfaces skipped/backlog
              -- alongside the done/failed split workers already log to stdout.
              (SELECT COUNT(*) FROM {S}.failed_ingest
                 WHERE created_at > NOW() - INTERVAL '24 hours') AS failed_ingest_24h,
              (SELECT COUNT(*) FROM {S}.failed_ingest) AS failed_ingest_total,
              (SELECT COUNT(*) FROM {S}.articles
                 WHERE province_code IS NULL AND geo_scope != 'unmappable') AS geo_pending,
              (SELECT COUNT(*) FROM {S}.articles WHERE NOT ai_analyzed) AS llm_pending,
              (SELECT COUNT(*) FROM {S}.scout_body_jobs WHERE status='failed') AS scout_body_failed,
              (SELECT COUNT(*) FROM {S}.scout_body_jobs
                 WHERE status='completed' AND completed_at > NOW() - INTERVAL '24 hours') AS scout_body_done_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE geo_scope = 'unmappable') AS geo_unmappable,
              (SELECT COUNT(*) FROM {S}.articles
                 WHERE geo_scope = 'unmappable' AND published_at > NOW() - INTERVAL '24 hours') AS geo_unmappable_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE bias_v2_score IS NOT NULL) AS bias_v2_scored,
              (SELECT COUNT(*) FROM {S}.articles WHERE tier2_failures > 0) AS tier2_failed
        """)).mappings().first()

        # Build unified event query per agent type, then union + paginate
        agent_queries = {
            "F.A.C.T.": f"""
                SELECT 'F.A.C.T.' AS agent, a.id AS article_id, a.title AS title,
                       'ingested' AS result, at.created_at AS ts, s.name AS source
                FROM {S}.audit_trail at
                JOIN {S}.articles a ON a.id = at.article_id
                JOIN {S}.sources s ON s.id = a.source_id
                WHERE at.event_type = 'ingested'""",
            "B.I.A.S.": f"""
                SELECT 'B.I.A.S.' AS agent, a.id AS article_id, a.title AS title,
                       bs.band AS result, bs.computed_at AS ts, s.name AS source
                FROM {S}.bias_scores bs
                JOIN {S}.articles a ON a.id = bs.article_id
                JOIN {S}.sources s ON s.id = a.source_id""",
            "V.E.R.I.F.Y.": f"""
                SELECT 'V.E.R.I.F.Y.' AS agent, a.id AS article_id, a.title AS title,
                       fc.overall_verdict AS result, fc.checked_at AS ts, s.name AS source
                FROM {S}.fact_checks fc
                JOIN {S}.articles a ON a.id = fc.article_id
                JOIN {S}.sources s ON s.id = a.source_id""",
            "L.O.C.A.L.": f"""
                SELECT 'L.O.C.A.L.' AS agent, a.id AS article_id, a.title AS title,
                       a.province_code AS result, at.created_at AS ts, s.name AS source
                FROM {S}.articles a
                JOIN {S}.sources s ON s.id = a.source_id
                JOIN {S}.audit_trail at ON at.article_id = a.id AND at.event_type = 'ingested'
                WHERE a.province_code IS NOT NULL""",
            "D.R.A.F.T.": f"""
                SELECT 'D.R.A.F.T.' AS agent, NULL AS article_id,
                       sc.representative_title AS title,
                       'summarized' AS result, su.created_at AS ts, NULL AS source
                FROM {S}.summaries su
                JOIN {S}.story_clusters sc ON sc.id = su.cluster_id""",
            "I.N.K.": f"""
                SELECT 'I.N.K.' AS agent, NULL AS article_id,
                       representative_title AS title,
                       CONCAT(article_count::text, ' articles') AS result,
                       created_at AS ts, NULL AS source
                FROM {S}.story_clusters""",
        }

        if agent_filter != "all" and agent_filter in agent_queries:
            selected = {agent_filter: agent_queries[agent_filter]}
        else:
            selected = agent_queries

        union_sql = " UNION ALL ".join(f"({q})" for q in selected.values())
        total = c.execute(text(f"SELECT COUNT(*) FROM ({union_sql}) x")).scalar() or 0

        rows = c.execute(text(f"""
            SELECT * FROM ({union_sql}) x
            ORDER BY ts DESC NULLS LAST
            LIMIT {PAGE_SIZE} OFFSET {offset}
        """)).fetchall()

        def _daily(sql: str) -> list:
            today = datetime.date.today()
            by_date = {r[0]: int(r[1] or 0) for r in c.execute(text(sql)).fetchall()}
            return [by_date.get(today - datetime.timedelta(days=i), 0) for i in range(6, -1, -1)]

        sparklines = {
            "F.A.C.T.": _daily(f"""
                SELECT created_at::date AS d, COUNT(*) FROM {S}.audit_trail
                WHERE event_type='ingested' AND created_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY 1
            """),
            "B.I.A.S.": _daily(f"""
                SELECT computed_at::date AS d, COUNT(*) FROM {S}.bias_scores
                WHERE computed_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY 1
            """),
            "V.E.R.I.F.Y.": _daily(f"""
                SELECT checked_at::date AS d, COUNT(DISTINCT article_id) FROM {S}.fact_checks
                WHERE checked_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY 1
            """),
            "D.R.A.F.T.": _daily(f"""
                SELECT created_at::date AS d, COUNT(*) FROM {S}.summaries
                WHERE created_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY 1
            """),
            "I.N.K.": _daily(f"""
                SELECT created_at::date AS d, COUNT(*) FROM {S}.story_clusters
                WHERE created_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY 1
            """),
            "LLM Analyzed": _daily(f"""
                SELECT ai_analyzed_at::date AS d, COUNT(*) FROM {S}.articles
                WHERE ai_analyzed_at > CURRENT_DATE - INTERVAL '7 days'
                GROUP BY 1
            """),
            # L.O.C.A.L. omitted — no timestamp on province_code being set.
        }

        source_health_rows = c.execute(text(f"""
            SELECT
                s.slug,
                s.bias_lean,
                s.owner_name,
                s.owner_type,
                COUNT(a.id) AS articles_total,
                COUNT(a.id) FILTER (WHERE a.published_at > NOW() - INTERVAL '7 days') AS articles_7d,
                COUNT(a.id) FILTER (WHERE LENGTH(a.body) >= 100) AS articles_with_body,
                MAX(a.published_at)::date AS last_article
            FROM {S}.sources s
            LEFT JOIN {S}.articles a ON a.source_id = s.id
            GROUP BY s.id, s.slug, s.bias_lean, s.owner_name, s.owner_type
            ORDER BY articles_7d DESC NULLS LAST, articles_total DESC NULLS LAST
        """)).mappings().all()

    source_health = []
    for r in source_health_rows:
        owner = r["owner_name"] or "Unknown"
        ownership_type = r["owner_type"] or "unknown"
        total = r["articles_total"] or 0
        recent = r["articles_7d"] or 0
        with_body = r["articles_with_body"] or 0
        if total == 0:
            status = "dead"
        elif recent == 0:
            status = "stalled"
        else:
            status = "active"
        source_health.append({
            "slug": r["slug"],
            "bias_lean": r["bias_lean"] or "?",
            "owner": owner,
            "ownership_type": ownership_type,
            "articles_total": total,
            "articles_7d": recent,
            "body_pct": int(with_body / total * 100) if total else 0,
            "last_article": r["last_article"].isoformat() if r["last_article"] else "—",
            "status": status,
        })

    events = [
        {"agent": r[0], "article_id": r[1], "title": (r[2] or "")[:120],
         "result": r[3] or "", "source": r[5] or "",
         "ts": r[4].isoformat() if r[4] else None}
        for r in rows
    ]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return render_template("activity.html", events=events, source_count=source_count,
                           total=total, page=page, total_pages=total_pages,
                           page_size=PAGE_SIZE, agent_filter=agent_filter,
                           stats=dict(stats), source_health=source_health,
                           sparklines=sparklines,
                           agent_stats=_fetch_agent_stats(),
                           is_subscriber=is_subscriber())


@bp.get("/team")
def team():
    S = _schema()
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
    portrait_lookup = _get_portrait_lookup()
    agents = []
    for agent in TEAM_AGENTS:
        a = dict(agent)
        live_url = portrait_lookup.get(agent["name"])
        if live_url:
            a["portrait_url"] = live_url
        agents.append(a)
    return render_template("team.html", agents=agents, source_count=source_count)


@bp.get("/")
def index():
    S = _schema()
    wtf_tech_url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band,
                   a.ai_analyzed, a.province_code,
                   a.cluster_id, sc.article_count AS cluster_size,
                   (SELECT STRING_AGG(m.name, ', ' ORDER BY m.name)
                    FROM {S}.article_mp_tags t
                    JOIN parliament.mps m ON m.id = t.mp_id
                    WHERE t.article_id = a.id) AS mp_mentions
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
            ORDER BY a.published_at DESC LIMIT 50
        """)).mappings().all()
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
    return render_template("index.html", articles=rows, wtf_tech_url=wtf_tech_url,
                           source_count=source_count, is_subscriber=is_subscriber())


# ───────────────────────────────────────────────────────────────────────────
# Server-side proxy routes — browser JS must never call wtf-tech directly
# (mixed content: page is HTTPS, wtf-tech is an internal Docker hostname)
# ───────────────────────────────────────────────────────────────────────────
def _proxy_tech(path: str, method: str = "GET", body: bytes = None, timeout: int = 30) -> Response:
    url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech") + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Response(resp.read(), content_type="application/json")
    except Exception as exc:
        return Response(json.dumps({"error": str(exc)}), status=502, content_type="application/json")


@bp.get("/api/proxy/map-data")
def proxy_map_data():
    return _proxy_tech("/api/v1/map-data")


@bp.get("/api/proxy/agent-activity")
def proxy_agent_activity():
    return _proxy_tech("/api/v1/agent-activity")


@bp.get("/api/proxy/articles/geo")
def proxy_articles_geo():
    return _proxy_tech("/api/v1/articles/geo")


@bp.post("/api/proxy/articles/<int:article_id>/analyze")
def proxy_article_analyze(article_id: int):
    # Returns instantly (queued=true) — background thread handles the hub call
    return _proxy_tech(f"/api/v1/articles/{article_id}/analyze", method="POST", body=b"{}", timeout=10)


@bp.get("/api/proxy/articles/<int:article_id>/analyze/status")
def proxy_article_analyze_status(article_id: int):
    return _proxy_tech(f"/api/v1/articles/{article_id}/analyze/status")


@bp.post("/api/proxy/articles/<int:article_id>/flag")
def proxy_article_flag(article_id: int):
    import json as _json
    from flask import request as _req
    body = _req.get_json(silent=True) or {}
    payload = _json.dumps({
        "article_id": article_id,
        "flag_type": (body.get("flag_type") or "bias_wrong")[:32],
        "reason": (body.get("reason") or "")[:500],
    }).encode()
    return _proxy_tech("/api/v1/flag", method="POST", body=payload)


@bp.get("/article/<int:article_id>")
def article(article_id: int):
    import json as _json
    S = _schema()
    wtf_tech_url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at,
                   a.ai_analyzed, a.ai_analyzed_at, a.province_code, a.cluster_id,
                   a.analysis_tier, a.tier2_pending,
                   a.bias_v2_score, a.bias_v2_label,
                   a.bias_ensemble_score, a.bias_ensemble_band,
                   s.name AS source_name, s.slug AS source_slug,
                   s.owner_name, s.owner_type, s.bias_lean AS source_bias_lean,
                   s.country AS source_country,
                   b.band AS bias_band, b.score AS bias_score,
                   b.rationale AS bias_rationale, b.trigger_phrases,
                   b.confidence AS bias_confidence, b.analyzed_by AS bias_analyzed_by,
                   obs.avg_score AS outlet_avg_score, obs.band AS outlet_rolling_band,
                   (SELECT COUNT(*) FROM {S}.articles a2
                    WHERE a2.source_id = a.source_id) AS outlet_article_count,
                   fc.overall_verdict, fc.claims AS fact_check_claims,
                   fc.analyzed_by AS fc_analyzed_by
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = a.source_id
            LEFT JOIN {S}.fact_checks fc
                ON fc.article_id = a.id AND fc.checker NOT LIKE 'GoogleFCT%%'
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        abort(404)
    # GoogleFCT partner fact-checks — free to all users (third-party public verdicts)
    with _db().begin() as c:
        gfct_rows = c.execute(text(f"""
            SELECT claim, verdict, evidence, checker
            FROM {S}.fact_checks
            WHERE article_id = :id
              AND checker LIKE 'GoogleFCT%%'
              AND checker != 'GoogleFCT:none'
            ORDER BY checked_at DESC
            LIMIT 5
        """), {"id": article_id}).mappings().all()
    google_fact_checks = [dict(r) for r in gfct_rows]
    # Normalise JSONB fields — driver may return str or list
    a = dict(row)
    for field in ("trigger_phrases", "fact_check_claims"):
        val = a.get(field)
        if isinstance(val, str):
            try:
                a[field] = _json.loads(val)
            except Exception:
                a[field] = []
        elif val is None:
            a[field] = []

    # Server-side paywall — redact premium fields for non-subscribers
    # bias_band is free (teaser); rationale + trigger_phrases + fact_check data are paid
    subscribed = is_subscriber()
    if not subscribed:
        a["bias_rationale"] = None
        a["trigger_phrases"] = []
        a["fact_check_claims"] = []

    # #2914 reading-history log — only for signed-in users.
    # UPSERT advances view_count + last_view_at; first row sets first_view_at.
    user_email = _user_email()
    if user_email:
        try:
            with _db().begin() as c:
                c.execute(text(f"""
                    INSERT INTO {S}.user_article_views (user_email, article_id, view_count)
                    VALUES (:email, :id, 1)
                    ON CONFLICT (user_email, article_id) DO UPDATE
                      SET view_count = {S}.user_article_views.view_count + 1,
                          last_view_at = NOW()
                """), {"email": user_email, "id": article_id})
        except Exception:
            # Don't break article rendering on logging failure
            pass

    is_paywalled = (a.get("source_slug") or "") in _PAYWALLED_SOURCES
    is_limited_body = len(a.get("body") or "") < 150

    # Reading time — 200 wpm average
    word_count = len((a.get("body") or "").split())
    reading_time_min = max(1, round(word_count / 200))

    # Article type — detect opinion/editorial from title prefix
    _OPINION_PREFIXES = ("letters:", "opinion:", "editorial:", "comment:",
                         "commentary:", "analysis:", "column:", "perspective:",
                         "review:", "op-ed:")
    title_lower = (a.get("title") or "").lower()
    article_type = "opinion" if any(title_lower.startswith(p) for p in _OPINION_PREFIXES) else "news"

    # Outlet comparison — other articles in the same cluster (#3069)
    cluster_articles = []
    if a.get("cluster_id"):
        with _db().begin() as c:
            siblings = c.execute(text(f"""
                SELECT a2.id, a2.title, a2.url, a2.published_at,
                       s2.name AS source_name, s2.slug AS source_slug,
                       b2.band AS bias_band, b2.score AS bias_score
                FROM {S}.articles a2
                JOIN {S}.sources s2 ON s2.id = a2.source_id
                LEFT JOIN {S}.bias_scores b2 ON b2.article_id = a2.id
                WHERE a2.cluster_id = :cid AND a2.id != :aid
                ORDER BY a2.published_at DESC
                LIMIT 10
            """), {"cid": a["cluster_id"], "aid": article_id}).mappings().all()
        cluster_articles = [dict(r) for r in siblings]

    # Outlet sparkline — daily avg bias score for the past 7 days
    sparkline = []
    try:
        with _db().begin() as c:
            sp_rows = c.execute(text(f"""
                SELECT bs.computed_at::date AS d,
                       AVG(bs.score)::float AS avg_score,
                       MODE() WITHIN GROUP (ORDER BY bs.band) AS modal_band
                FROM {S}.bias_scores bs
                JOIN {S}.articles a2 ON a2.id = bs.article_id
                WHERE a2.source_id = (SELECT source_id FROM {S}.articles WHERE id = :aid)
                  AND bs.computed_at > NOW() - INTERVAL '7 days'
                GROUP BY 1 ORDER BY 1
            """), {"aid": article_id}).fetchall()
        sparkline = [{"score": round(float(r[1]), 3), "band": r[2] or "center"} for r in sp_rows]
    except Exception:
        pass

    return render_template("article.html", a=a, wtf_tech_url=wtf_tech_url,
                           is_subscriber=subscribed,
                           is_paywalled=is_paywalled,
                           is_limited_body=is_limited_body,
                           google_fact_checks=google_fact_checks,
                           cluster_articles=cluster_articles,
                           reading_time_min=reading_time_min,
                           article_type=article_type,
                           sparkline=sparkline)


# ───────────────────────────────────────────────────────────────────────────
# Media Literacy Score (#2914) — personal reading-diet dashboard
# ───────────────────────────────────────────────────────────────────────────

# Bias band → numeric weight for distribution math. Symmetric around 0.
_BAND_WEIGHTS = {
    "left": -2,
    "center-left": -1,
    "center": 0,
    "center-right": 1,
    "right": 2,
}


@bp.get("/literacy")
def literacy_page():
    """Personal media-literacy dashboard. Subscriber-gated."""
    from flask import redirect
    email = _user_email()
    if not email:
        return redirect("/login?next=/literacy")
    if not is_subscriber():
        return redirect("/connect?gated=literacy")

    S = _schema()
    with _db().begin() as c:
        # Bias distribution of articles the user has viewed
        rows = c.execute(text(f"""
            SELECT COALESCE(b.band, 'unscored') AS band,
                   COUNT(DISTINCT v.article_id) AS articles,
                   SUM(v.view_count) AS views
            FROM {S}.user_article_views v
            LEFT JOIN {S}.bias_scores b ON b.article_id = v.article_id
            WHERE v.user_email = :email
            GROUP BY 1
            ORDER BY articles DESC
        """), {"email": email}).mappings().all()
        # Recent reads with bias for the activity strip
        recent = c.execute(text(f"""
            SELECT a.id, a.title, s.name AS source_name,
                   b.band, v.last_view_at
            FROM {S}.user_article_views v
            JOIN {S}.articles a ON a.id = v.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE v.user_email = :email
            ORDER BY v.last_view_at DESC
            LIMIT 20
        """), {"email": email}).mappings().all()

    # Compute Media Literacy Score
    # Strategy: 100 - skew, where skew is the |centroid| of bias weights.
    # Perfectly balanced reader -> 100. Reader who only consumes one extreme -> ~0.
    total_articles = 0
    weighted_sum = 0.0
    distribution = {b: 0 for b in _BAND_WEIGHTS}
    distribution["unscored"] = 0
    for r in rows:
        n = int(r["articles"] or 0)
        band = r["band"]
        distribution[band] = n
        if band in _BAND_WEIGHTS:
            total_articles += n
            weighted_sum += n * _BAND_WEIGHTS[band]
    if total_articles > 0:
        centroid = weighted_sum / total_articles  # range roughly -2..+2
        # |centroid| / 2 → 0..1 skew. 100 - 100 * skew → 0..100.
        skew_pct = abs(centroid) / 2.0
        score = max(0, min(100, int(round(100 * (1 - skew_pct)))))
    else:
        score = None

    return render_template("literacy.html",
                           user_email=email,
                           score=score,
                           total_scored=total_articles,
                           total_views=sum(int(r["views"] or 0) for r in rows),
                           distribution=distribution,
                           recent=[dict(r) for r in recent])


@bp.get("/account")
def account_page():
    """Subscription status page — shows tier, manage/subscribe CTA."""
    from flask import redirect
    email = _user_email()
    if not email:
        return redirect("/login?next=/account")
    subscribed = is_subscriber()
    tier = session.get("wtf_tier", "free")
    # Check local billing for Stripe customer ID (to show portal link)
    has_stripe = False
    try:
        from .db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT stripe_customer_id, status FROM billing_subscriptions"
            " WHERE LOWER(email) = LOWER(?)",
            (email,),
        ).fetchone()
        conn.close()
        has_stripe = bool(row and row[0])
        if row and row[1]:
            tier = row[1] if row[1] != "active" else tier
    except Exception:
        pass
    return render_template("account.html",
                           user_email=email,
                           tier=tier,
                           subscribed=subscribed,
                           has_stripe=has_stripe)


@bp.get("/sources")
def sources_list():
    """All tracked outlets sorted by article count."""
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT s.slug, s.name, s.url, s.bias_lean, s.owner_name, s.owner_type,
                   obs.avg_score, obs.band AS rolling_band,
                   COUNT(a.id) AS total_articles,
                   COUNT(a.id) FILTER (WHERE a.published_at > NOW() - INTERVAL '7 days') AS articles_7d
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN {S}.articles a ON a.source_id = s.id
            GROUP BY s.id, s.slug, s.name, s.url, s.bias_lean, s.owner_name, s.owner_type, obs.avg_score, obs.band
            ORDER BY COUNT(a.id) DESC
        """)).mappings().all()
    return render_template("sources.html", sources=[dict(r) for r in rows])


@bp.get("/source/<slug>")
def source_profile(slug: str):
    """Outlet bias profile page — SEO-indexable per source."""
    S = _schema()
    # Validate slug to prevent injection
    if not slug.replace("-", "").replace("_", "").isalnum():
        abort(404)
    with _db().begin() as c:
        src = c.execute(text(f"""
            SELECT s.id, s.slug, s.name, s.url, s.bias_lean, s.country,
                   s.language, s.owner_name, s.owner_type,
                   obs.avg_score, obs.band AS rolling_band,
                   COUNT(a.id) AS total_articles,
                   COUNT(a.id) FILTER (WHERE a.published_at > NOW() - INTERVAL '7 days') AS articles_7d
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN {S}.articles a ON a.source_id = s.id
            WHERE s.slug = :slug
            GROUP BY s.id, s.slug, s.name, s.url, s.bias_lean, s.country,
                     s.language, s.owner_name, s.owner_type, obs.avg_score, obs.band
        """), {"slug": slug}).mappings().first()
    if not src:
        abort(404)
    with _db().begin() as c:
        band_counts = c.execute(text(f"""
            SELECT COALESCE(b.band, 'unscored') AS band, COUNT(*) AS n
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.source_id = :sid
            GROUP BY 1 ORDER BY 2 DESC
        """), {"sid": src["id"]}).mappings().all()
        recent = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, b.band, b.score
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.source_id = :sid
            ORDER BY a.published_at DESC LIMIT 20
        """), {"sid": src["id"]}).mappings().all()
    return render_template("source.html",
                           src=dict(src),
                           band_counts=[dict(r) for r in band_counts],
                           recent=[dict(r) for r in recent],
                           is_subscriber=is_subscriber())


@bp.post("/api/clusters/<int:cluster_id>/frame")
def frame_cluster(cluster_id: int):
    """Generate + cache an AI framing comparison for a story cluster.

    Builds a synthetic prompt from the cluster's article headlines + excerpts,
    dispatches to the hub's WTF Hub analyze endpoint (task=summarize), stores
    the result in story_clusters.framing_summary.
    """
    import json as _json
    from flask import jsonify
    S = _schema()
    HUB_URL = os.environ.get("WTF_HUB_URL", "")
    HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
    if not HUB_URL or not HUB_TOKEN:
        return jsonify({"ok": False, "error": "hub not configured"}), 503

    with _db().begin() as c:
        cluster = c.execute(text(f"""
            SELECT id, representative_title, framing_summary, framing_generated_at
            FROM {S}.story_clusters WHERE id = :id
        """), {"id": cluster_id}).mappings().first()
    if not cluster:
        return jsonify({"ok": False, "error": "cluster not found"}), 404
    if cluster["framing_summary"]:
        return jsonify({"ok": True, "summary": cluster["framing_summary"], "cached": True})

    with _db().begin() as c:
        articles = c.execute(text(f"""
            SELECT a.title, LEFT(a.body, 350) AS excerpt,
                   s.name AS source_name, s.bias_lean
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.cluster_id = :cid AND a.title IS NOT NULL
            ORDER BY a.published_at ASC LIMIT 8
        """), {"cid": cluster_id}).mappings().all()
    if not articles:
        return jsonify({"ok": False, "error": "no articles"}), 404

    lines = [
        "The following news articles all cover the same story but come from different outlets. "
        "In 2-3 sentences, describe how different outlets framed this story — note differences "
        "in emphasis, language, what was highlighted or omitted, and any apparent editorial lean.\n"
    ]
    for a in articles:
        lean = f" [{a['bias_lean']}]" if a.get("bias_lean") else ""
        lines.append(f"SOURCE: {a['source_name']}{lean}")
        lines.append(f"HEADLINE: {a['title']}")
        if a.get("excerpt"):
            lines.append(f"EXCERPT: {(a['excerpt'] or '')[:250]}")
        lines.append("")
    body = "\n".join(lines)
    title = f"Outlet framing comparison: {cluster['representative_title']}"

    try:
        payload = _json.dumps({
            "task": "summarize", "article_id": 0,
            "title": title, "body": body,
        }).encode()
        req_obj = urllib.request.Request(
            f"{HUB_URL}/tools/wtf-hub/api/analyze",
            data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {HUB_TOKEN}"},
        )
        with urllib.request.urlopen(req_obj, timeout=90) as resp:
            data = _json.loads(resp.read())

        result = data.get("result") if data.get("ok") else None
        summary = None
        if isinstance(result, dict):
            summary = result.get("summary") or result.get("text") or result.get("brief")
        elif isinstance(result, str):
            summary = result

        if not summary:
            return jsonify({"ok": False, "error": "no summary from hub"}), 500

        summary = summary.strip()[:2000]
        with _db().begin() as c:
            c.execute(text(f"""
                UPDATE {S}.story_clusters
                SET framing_summary = :s, framing_generated_at = NOW()
                WHERE id = :id
            """), {"s": summary, "id": cluster_id})

        return jsonify({"ok": True, "summary": summary, "cached": False})

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500


@bp.get("/cluster/<int:cluster_id>")
def cluster_comparison(cluster_id: int):
    """Side-by-side outlet comparison for a story cluster (#3069)."""
    S = _schema()
    with _db().begin() as c:
        meta = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.created_at, sc.framing_summary, sc.framing_generated_at
            FROM {S}.story_clusters sc
            WHERE sc.id = :cid
        """), {"cid": cluster_id}).mappings().first()
    if not meta:
        abort(404)
    with _db().begin() as c:
        articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   LEFT(a.body, 400) AS excerpt,
                   s.name AS source_name, s.slug AS source_slug, s.bias_lean,
                   b.band AS bias_band, b.score AS bias_score,
                   b.rationale AS bias_rationale, b.analyzed_by,
                   fc.overall_verdict, fc.analyzed_by AS fc_analyzed_by
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.fact_checks fc
                ON fc.article_id = a.id AND fc.checker NOT LIKE 'GoogleFCT%%'
            WHERE a.cluster_id = :cid
            ORDER BY a.published_at ASC
        """), {"cid": cluster_id}).mappings().all()
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
    return render_template("cluster.html",
                           cluster=dict(meta),
                           articles=[dict(r) for r in articles],
                           source_count=source_count,
                           is_subscriber=is_subscriber(),
                           framing_summary=dict(meta).get("framing_summary"))


_OPENPARL_BASE = "https://openparliament.ca"
_PARTY_COLOURS = {
    "conservative": "#3b82f6",
    "liberal": "#d71920",
    "ndp": "#f37021",
    "bloc": "#89cff0",
    "green": "#3d9b35",
    "independent": "#888888",
    "people": "#6a0dad",
}


def _party_colour(party: str) -> str:
    """Fuzzy party → colour lookup — insensitive to accents and exact casing."""
    key = (party or "").lower()
    for fragment, colour in _PARTY_COLOURS.items():
        if fragment in key:
            return colour
    return "#6b7280"


@bp.get("/parliament/officers")
def officers_of_parliament():
    """Officers of Parliament — 8 independent accountability watchdogs."""
    with _db().begin() as c:
        officers = c.execute(text("""
            SELECT slug, title, short_title, current_holder, appointed_at,
                   mandate_summary, website_url, report_url, report_title,
                   report_date, cross_links
            FROM parliament.officers
            WHERE is_active = true
            ORDER BY id
        """)).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("officers.html",
                           officers=[dict(o) for o in officers],
                           source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/crtc")
def crtc_decisions():
    """CRTC rulings — broadcasting, telecom, compliance decisions."""
    from flask import request as _req
    dtype = _req.args.get("type", "all")
    with _db().begin() as c:
        query = """
            SELECT decision_number, decision_year, subject, scope,
                   description, decision_type, decision_url, wtf_source_slug
            FROM legal_watch.crtc_decisions
            {}
            ORDER BY decision_number DESC
            LIMIT 200
        """.format("WHERE decision_type = :dtype" if dtype != "all" else "")
        params = {"dtype": dtype} if dtype != "all" else {}
        rows = c.execute(text(query), params).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("crtc.html",
                           decisions=[dict(r) for r in rows],
                           dtype=dtype,
                           source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/ethics")
def ethics_rulings():
    """Ethics Commissioner investigation reports."""
    with _db().begin() as c:
        rows = c.execute(text("""
            SELECT e.report_name, e.subject_name, e.ruling_date,
                   e.report_type, e.report_url, e.mp_slug,
                   m.name AS mp_name
            FROM legal_watch.ethics_rulings e
            LEFT JOIN parliament.mps m ON m.slug = e.mp_slug
            ORDER BY e.ruling_date DESC
        """)).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("ethics.html",
                           rulings=[dict(r) for r in rows],
                           source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/gic")
def gic_appointments():
    """Governor in Council appointments — patronage tracking via Orders-in-Council."""
    from flask import request as _req
    dept = _req.args.get("dept", "all")
    with _db().begin() as c:
        query = """
            SELECT pc_number, oic_date, department, subject, precis,
                   oic_url, appointee_name, organization
            FROM gov_watch.gic_appointments
            {}
            ORDER BY oic_date DESC, pc_number DESC
            LIMIT 200
        """.format("WHERE department ILIKE :dept" if dept != "all" else "")
        params = {"dept": f"%{dept}%"} if dept != "all" else {}
        rows = c.execute(text(query), params).mappings().all()
        depts = c.execute(text("""
            SELECT DISTINCT department FROM gov_watch.gic_appointments
            WHERE department IS NOT NULL ORDER BY department
        """)).scalars().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("gic.html",
                           appointments=[dict(r) for r in rows],
                           depts=list(depts),
                           dept=dept,
                           source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/rates")
def boc_rates():
    """Bank of Canada overnight rate decisions."""
    with _db().begin() as c:
        current = c.execute(text("""
            SELECT rate_pct, decision_date
            FROM market_watch.boc_rate_decisions
            ORDER BY decision_date DESC LIMIT 1
        """)).mappings().first()
        decisions = c.execute(text("""
            SELECT decision_date, rate_pct, change_bps
            FROM market_watch.boc_rate_decisions
            WHERE ABS(change_bps) >= 10 OR change_bps IS NULL
            ORDER BY decision_date DESC
            LIMIT 60
        """)).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("rates.html",
                           current=dict(current) if current else {},
                           decisions=[dict(r) for r in decisions],
                           source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/owners")
def owners_listing():
    """Media ownership transparency — who owns which outlets and their bias profile."""
    S = _schema()
    with _db().begin() as c:
        # Owners grouped with their outlets and bias data
        owner_rows = c.execute(text(f"""
            SELECT
                s.owner_name,
                s.owner_type,
                COUNT(s.id)                              AS outlet_count,
                ARRAY_AGG(
                    json_build_object(
                        'name', s.name,
                        'slug', s.slug,
                        'url',  s.url,
                        'bias_lean', s.bias_lean,
                        'avg_score', ROUND(obs.avg_score::numeric, 2)
                    ) ORDER BY s.name
                )                                        AS outlets,
                ROUND(AVG(obs.avg_score)::numeric, 2)    AS avg_bias,
                MIN(s.bias_lean)                         AS sample_lean
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            WHERE s.owner_name IS NOT NULL
            GROUP BY s.owner_name, s.owner_type
            ORDER BY outlet_count DESC, s.owner_name
        """)).mappings().all()

        # Sources without owner attribution
        unattributed = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.sources WHERE owner_name IS NULL
        """)).scalar() or 0

        source_count = c.execute(text(f"SELECT COUNT(*) FROM {S}.sources")).scalar() or 0

    owners = [dict(r) for r in owner_rows]
    return render_template("owners.html", owners=owners, unattributed=unattributed,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.get("/mps")
def mps_listing():
    """All MPs with optional party/province filter."""
    from flask import request as _req
    S = _schema()
    party_filter = (_req.args.get("party") or "all").strip()
    province_filter = (_req.args.get("province") or "all").strip().upper()

    with _db().begin() as c:
        rows = c.execute(text("""
            SELECT m.slug, m.name, m.party, m.riding_name, m.province_code,
                   m.photo_url, m.twitter, m.cabinet_role,
                   COUNT(v.id) AS vote_count,
                   (SELECT COUNT(*) FROM wtf.article_mp_tags t WHERE t.mp_id = m.id) AS mention_count
            FROM parliament.mps m
            LEFT JOIN parliament.mp_votes v ON v.mp_id = m.id
            WHERE m.is_current = true
              AND (:party = 'all' OR m.party = :party)
              AND (:province = 'ALL' OR m.province_code = :province)
            GROUP BY m.id
            ORDER BY m.party, m.name
        """), {"party": party_filter, "province": province_filter}).mappings().all()
        parties = c.execute(text(
            "SELECT DISTINCT party FROM parliament.mps WHERE is_current=true AND party IS NOT NULL ORDER BY party"
        )).scalars().all()
        provinces = c.execute(text(
            "SELECT DISTINCT province_code FROM parliament.mps WHERE is_current=true AND province_code IS NOT NULL ORDER BY province_code"
        )).scalars().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {S}.sources")).scalar() or 0
        senators = c.execute(text("""
            SELECT slug, name, given_name, family_name, caucus, province, photo_url, profile_url, appointed_at
            FROM parliament.senators WHERE is_current = true ORDER BY caucus, name
        """)).mappings().all()

    senators_list = [dict(s) for s in senators]

    mps = []
    for r in rows:
        mp = dict(r)
        if mp.get("photo_url") and not mp["photo_url"].startswith("http"):
            mp["photo_url"] = _OPENPARL_BASE + mp["photo_url"]
        mp["party_colour"] = _party_colour(mp.get("party") or "")
        mps.append(mp)

    return render_template("mps.html", mps=mps, parties=list(parties),
                           provinces=list(provinces), party_filter=party_filter,
                           province_filter=province_filter, source_count=source_count,
                           senators=senators_list)


@bp.get("/senator/<slug>")
def senator_profile(slug: str):
    """Individual senator profile — caucus, province, appointment, bio, committees."""
    if not slug.replace("-", "").replace("_", "").isalnum():
        abort(404)
    _CAUCUS_COLOURS = {
        "C": "#3b82f6", "ISG": "#cc0000", "CSG": "#059669",
        "PSG": "#7c3aed", "GRO": "#b45309", "Non-affiliated": "#888888",
    }
    _CAUCUS_LABELS = {
        "C": "Conservative", "ISG": "Independent Senators Group",
        "CSG": "Canadian Senators Group", "PSG": "Progressive Senate Group",
        "GRO": "Government Representative Office", "Non-affiliated": "Non-affiliated",
    }
    with _db().begin() as c:
        row = c.execute(text("""
            SELECT id, slug, name, given_name, family_name, caucus, province,
                   photo_url, profile_url, appointed_at, date_of_birth,
                   appointed_by, biography, office_phone, office_email,
                   twitter_handle, linkedin_url, website_url
            FROM parliament.senators WHERE slug = :slug AND is_current = true
        """), {"slug": slug}).mappings().first()
        if not row:
            abort(404)
        senator = dict(row)
        # Fetch committees
        committee_rows = c.execute(text("""
            SELECT committee_abbr, committee_name, role
            FROM parliament.senator_committees
            WHERE senator_id = :sid AND is_current = true
            ORDER BY role DESC, committee_name
        """), {"sid": senator["id"]}).mappings().all()
        senator["committees"] = [dict(r) for r in committee_rows]
        # Fetch recent votes
        vote_rows = c.execute(text("""
            SELECT sv.vote_date, sv.title, sv.bill_number, sv.result,
                   sv.yea_total, sv.nay_total, sv.abstention_total,
                   snv.ballot
            FROM parliament.senator_votes snv
            JOIN parliament.senate_votes sv ON sv.id = snv.vote_id
            WHERE snv.senator_id = :sid
            ORDER BY sv.vote_date DESC
            LIMIT 30
        """), {"sid": senator["id"]}).mappings().all()
        senator["votes"] = [dict(r) for r in vote_rows]

    senator["caucus_colour"] = _CAUCUS_COLOURS.get(senator.get("caucus") or "", "#888888")
    senator["caucus_label"] = _CAUCUS_LABELS.get(senator.get("caucus") or "", senator.get("caucus") or "")

    # Computed date fields
    today = datetime.date.today()
    dob = senator.get("date_of_birth")
    if dob:
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        retirement = datetime.date(dob.year + 75, dob.month, dob.day)
        days_left = (retirement - today).days
        years_left = days_left // 365
        senator["age"] = age
        senator["retirement_date"] = retirement
        senator["years_until_retirement"] = years_left
        senator["retirement_date_str"] = retirement.strftime("%B %-d, %Y")
    appt = senator.get("appointed_at")
    if appt:
        if hasattr(appt, "date"):
            appt = appt.date()
        years_in = today.year - appt.year - ((today.month, today.day) < (appt.month, appt.day))
        senator["years_in_senate"] = years_in

    source_count = 0
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("senator.html", senator=senator, source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/mp/<slug>")
def mp_profile(slug: str):
    """Individual MP profile — votes, party, riding, articles mentioning them."""
    if not slug.replace("-", "").replace("_", "").isalnum():
        abort(404)
    S = _schema()
    with _db().begin() as c:
        mp_row = c.execute(text("""
            SELECT id, slug, name, party, riding_name, province_code,
                   photo_url, twitter, email, parl_mp_id, openparl_url, fetched_at,
                   cabinet_role
            FROM parliament.mps WHERE slug = :slug AND is_current = true
        """), {"slug": slug}).mappings().first()
    if not mp_row:
        abort(404)
    mp = dict(mp_row)
    if mp.get("photo_url") and not mp["photo_url"].startswith("http"):
        mp["photo_url"] = _OPENPARL_BASE + mp["photo_url"]
    mp["party_colour"] = _PARTY_COLOURS.get(mp.get("party") or "", "#6b7280")

    with _db().begin() as c:
        # Recent votes
        votes = c.execute(text("""
            SELECT b.description_en, b.bill_number, b.vote_date, b.result,
                   b.yea_total, b.nay_total, b.session, b.vote_number, v.ballot
            FROM parliament.mp_votes v
            JOIN parliament.bills b ON b.id = v.bill_id
            WHERE v.mp_id = :mp_id
            ORDER BY b.vote_date DESC
            LIMIT 30
        """), {"mp_id": mp["id"]}).mappings().all()

        # Vote summary
        vote_stats = c.execute(text("""
            SELECT ballot, COUNT(*) AS cnt
            FROM parliament.mp_votes WHERE mp_id = :mp_id
            GROUP BY ballot
        """), {"mp_id": mp["id"]}).mappings().all()

        # Articles mentioning this MP
        articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source_name, s.slug AS source_slug,
                   bs.band AS bias_band
            FROM wtf.article_mp_tags t
            JOIN {S}.articles a ON a.id = t.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            WHERE t.mp_id = :mp_id
            ORDER BY a.published_at DESC
            LIMIT 15
        """), {"mp_id": mp["id"]}).mappings().all()

        source_count = c.execute(text(f"SELECT COUNT(*) FROM {S}.sources")).scalar() or 0

    stats = {r["ballot"]: r["cnt"] for r in vote_stats}
    total_votes = sum(stats.values())

    # Accountability data — best-effort (tables may not exist on first run)
    lobbying_contacts = []
    expense_periods = []
    disclosures = []
    promises = []
    try:
        with _db().begin() as c:
            lobbying_contacts = c.execute(text("""
                SELECT lc.lobbyist_last, lc.lobbyist_first, lc.client_org,
                       lc.communication_date, lc.comlog_id
                FROM parliament.lobbyist_contacts lc
                WHERE lc.mp_id = :mp_id
                ORDER BY lc.communication_date DESC
                LIMIT 25
            """), {"mp_id": mp["id"]}).mappings().all()

            expense_periods = c.execute(text("""
                SELECT period, travel_cad, hospitality_cad, contracts_cad,
                       salaries_cad, total_cad
                FROM parliament.mp_expenses
                WHERE mp_id = :mp_id
                ORDER BY period DESC
                LIMIT 12
            """), {"mp_id": mp["id"]}).mappings().all()

            disclosures = c.execute(text("""
                SELECT disclosure_year, disclosure_type, disclosure_url
                FROM parliament.mp_disclosures
                WHERE mp_id = :mp_id
                ORDER BY disclosure_year DESC
                LIMIT 10
            """), {"mp_id": mp["id"]}).mappings().all()

            promises = c.execute(text("""
                SELECT promise_text, source_url, published_at, status
                FROM parliament.mp_promises
                WHERE mp_id = :mp_id
                ORDER BY published_at DESC
                LIMIT 15
            """), {"mp_id": mp["id"]}).mappings().all()
    except Exception:
        pass  # accountability tables may not exist yet

    # Donor data from Elections Canada (parliament.ec_contributions)
    riding_donor_totals = []
    top_named_donors = []
    try:
        riding = mp.get("riding_name") or ""
        # EC uses "--" (double dash), parliament.mps uses "—" (em dash) — normalize
        riding_ec = riding.replace("—", "--").replace("–", "--")
        with _db().begin() as c:
            riding_donor_totals = c.execute(text("""
                SELECT electoral_event, political_entity,
                       COUNT(*) AS donation_count,
                       SUM(monetary_amount) AS total_raised,
                       COUNT(DISTINCT contributor_name)
                           FILTER (WHERE contributor_name NOT ILIKE '%200 or less%'
                                     AND contributor_name NOT ILIKE '%ou moins%') AS named_donors
                FROM parliament.ec_contributions
                WHERE electoral_district ILIKE :riding
                  AND monetary_amount > 0
                GROUP BY electoral_event, political_entity
                ORDER BY electoral_event DESC, total_raised DESC
                LIMIT 12
            """), {"riding": riding_ec}).mappings().all()

            top_named_donors = c.execute(text("""
                SELECT contributor_name, contributor_city, contributor_province,
                       SUM(monetary_amount) AS total_given,
                       COUNT(*) AS num_contributions,
                       MAX(electoral_event) AS latest_event
                FROM parliament.ec_contributions
                WHERE electoral_district ILIKE :riding
                  AND monetary_amount >= 200
                  AND contributor_name NOT ILIKE '%200 or less%'
                  AND contributor_name NOT ILIKE '%ou moins%'
                  AND contributor_name != ''
                GROUP BY contributor_name, contributor_city, contributor_province
                ORDER BY total_given DESC
                LIMIT 20
            """), {"riding": riding_ec}).mappings().all()
    except Exception:
        pass  # ec_contributions might not be populated yet

    return render_template("mp.html", mp=mp,
                           votes=[dict(r) for r in votes],
                           articles=[dict(r) for r in articles],
                           stats=stats, total_votes=total_votes,
                           source_count=source_count,
                           riding_donor_totals=[dict(r) for r in riding_donor_totals],
                           top_named_donors=[dict(r) for r in top_named_donors],
                           lobbying_contacts=[dict(r) for r in lobbying_contacts],
                           expense_periods=[dict(r) for r in expense_periods],
                           disclosures=[dict(r) for r in disclosures],
                           promises=[dict(r) for r in promises],
                           is_subscriber=is_subscriber())


@bp.route("/score", methods=["GET", "POST"])
def score_url():
    """Subscriber-gated: paste any article text for instant AI analysis."""
    from flask import request as _req, redirect
    subscribed = is_subscriber()
    if not _user_email():
        return redirect("/login?next=/score")
    result = None
    error = None
    article_text = ""
    if _req.method == "POST":
        if not subscribed:
            return redirect("/join?gated=score")
        article_text = (_req.form.get("text") or "").strip()[:5000]
        article_title = (_req.form.get("title") or "").strip()[:200]
        if len(article_text) < 100:
            error = "Please paste at least 100 characters of article text."
        else:
            wtf_tech_url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
            hub_token = os.environ.get("WTF_HUB_TOKEN", "")
            try:
                import json as _json
                payload = _json.dumps({"text": article_text, "title": article_title}).encode()
                headers = {"Content-Type": "application/json"}
                if hub_token:
                    headers["Authorization"] = f"Bearer {hub_token}"
                req_obj = urllib.request.Request(
                    f"{wtf_tech_url}/api/v1/score",
                    data=payload, method="POST", headers=headers
                )
                with urllib.request.urlopen(req_obj, timeout=int(os.environ.get("WTF_HUB_TIMEOUT", "90"))) as resp:
                    result = _json.loads(resp.read())
            except Exception as exc:
                error = f"Analysis failed — try again in a moment. ({str(exc)[:120]})"
    S = _schema()
    source_count = 0
    try:
        with _db().begin() as c:
            source_count = c.execute(text(f"SELECT COUNT(*) FROM {S}.sources")).scalar() or 0
    except Exception:
        pass
    return render_template("score.html", subscribed=subscribed, result=result,
                           error=error, article_text=article_text, source_count=source_count)


@bp.get("/search")
def search():
    """Full-text article search using Postgres tsvector."""
    from flask import request as _req
    S = _schema()
    q = (_req.args.get("q") or "").strip()[:200]
    results = []
    if q:
        with _db().begin() as c:
            source_count = c.execute(text(f"SELECT COUNT(*) FROM {S}.sources")).scalar() or 0
            rows = c.execute(text(f"""
                SELECT a.id, a.title, a.url, a.published_at,
                       s.name AS source, s.slug AS source_slug, b.band,
                       ts_rank(to_tsvector('english', COALESCE(a.title,'') || ' ' || COALESCE(a.body,'')),
                               plainto_tsquery('english', :q)) AS rank
                FROM {S}.articles a
                JOIN {S}.sources s ON s.id = a.source_id
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                WHERE to_tsvector('english', COALESCE(a.title,'') || ' ' || COALESCE(a.body,''))
                      @@ plainto_tsquery('english', :q)
                ORDER BY rank DESC, a.published_at DESC
                LIMIT 50
            """), {"q": q}).mappings().all()
        results = [dict(r) for r in rows]
    else:
        source_count = 0
    return render_template("search.html", q=q, results=results,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.get("/robots.txt")
def robots_txt():
    from flask import Response
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /account\n"
        "Disallow: /alerts\n"
        "Disallow: /literacy\n"
        "Disallow: /auth/\n"
        "Disallow: /billing/\n"
        "Sitemap: https://what-the-fact.com/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap_xml():
    """Dynamic XML sitemap — static pages + most recent 5,000 articles."""
    from flask import Response
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT id, published_at
            FROM {S}.articles
            ORDER BY published_at DESC
            LIMIT 5000
        """)).fetchall()

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    static_pages = ["/", "/sources", "/map", "/team", "/join", "/activity", "/news"]
    for path in static_pages:
        lines.append(f"  <url><loc>https://what-the-fact.com{path}</loc></url>")
    # Source profile pages
    with _db().begin() as c:
        src_rows = c.execute(text(f"SELECT slug FROM {S}.sources ORDER BY slug")).fetchall()
    for sr in src_rows:
        lines.append(
            f"  <url><loc>https://what-the-fact.com/source/{sr[0]}</loc>"
            "<changefreq>weekly</changefreq></url>"
        )
    for row in rows:
        art_id = row[0]
        lastmod = row[1].strftime("%Y-%m-%d") if row[1] else ""
        lastmod_tag = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        lines.append(
            f"  <url><loc>https://what-the-fact.com/article/{art_id}</loc>"
            f"{lastmod_tag}<changefreq>monthly</changefreq></url>"
        )
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")


@bp.route("/api/health")
def health():
    from datetime import datetime, timezone
    from flask import jsonify
    return jsonify({"status": "ok", "product": "what-the-fact", "timestamp": datetime.now(timezone.utc).isoformat()})


# ───────────────────────────────────────────────────────────────────────────
# Public API v1 (#2915) — RESTful read endpoints for researchers + civic tech
# ───────────────────────────────────────────────────────────────────────────

# In-memory IP token bucket. 60 requests / 60-second rolling window per IP.
# Resets when the container restarts. Sufficient for the read-only public API
# without dragging Redis in — first abuser hits 429 long before they DoS us.
_API_RATE_BUCKETS: dict = {}  # ip → [timestamps]
_API_RATE_LIMIT = int(os.environ.get("WTF_API_V1_RATE_LIMIT", "60"))
_API_RATE_WINDOW_SEC = 60


def _api_rate_ok(ip: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    now = time.time()
    bucket = _API_RATE_BUCKETS.setdefault(ip, [])
    cutoff = now - _API_RATE_WINDOW_SEC
    # Drop expired
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= _API_RATE_LIMIT:
        oldest = bucket[0]
        retry = int(_API_RATE_WINDOW_SEC - (now - oldest)) + 1
        return False, max(1, retry)
    bucket.append(now)
    return True, 0


def _api_cors_response(payload, status: int = 200):
    """Wrap a JSON payload with permissive CORS so research/civic-tech callers
    can hit the v1 API from any origin. Read-only endpoints only."""
    from flask import jsonify, make_response
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["X-WTF-API-Version"] = "v1"
    return resp


def _api_rate_check():
    """Returns 429 response if rate-limited, else None to proceed."""
    from flask import request as _req
    ip = _req.headers.get("X-Forwarded-For", "").split(",")[0].strip() or _req.remote_addr or "unknown"
    ok, retry = _api_rate_ok(ip)
    if not ok:
        resp = _api_cors_response({
            "ok": False, "error": "rate_limited",
            "retry_after": retry,
            "limit": _API_RATE_LIMIT,
            "window_seconds": _API_RATE_WINDOW_SEC,
        }, status=429)
        resp.headers["Retry-After"] = str(retry)
        return resp
    return None


@bp.get("/api/v1")
def api_v1_index():
    """Public API v1 docs page (HTML for humans + JSON via Accept: app/json)."""
    from flask import request as _req
    spec = {
        "ok": True,
        "version": "v1",
        "endpoints": [
            {"path": "/api/v1/articles", "params": "source, bias, province, country, since (ISO), limit (max 100), offset"},
            {"path": "/api/v1/sources", "params": "—"},
            {"path": "/api/v1/bias-distribution", "params": "since (ISO, default 7d ago)"},
            {"path": "/api/v1/map-data", "params": "— (7d window, 500-pin cap)"},
        ],
        "rate_limit": {"limit": _API_RATE_LIMIT, "window_seconds": _API_RATE_WINDOW_SEC,
                       "scope": "per-ip rolling window"},
        "cors": "Access-Control-Allow-Origin: *",
        "license": "WTF data is sourced from public RSS feeds. Cite individual articles per their publisher's terms. Aggregate bias scores are CC-BY-NC.",
    }
    if "application/json" in (_req.headers.get("Accept") or ""):
        return _api_cors_response(spec)
    # Plain-text fallback for browsers — keep it simple, no template
    lines = [
        "What The Fact — Public API v1", "=" * 40, "",
        f"Rate limit: {_API_RATE_LIMIT} requests / {_API_RATE_WINDOW_SEC}s per IP",
        "CORS: enabled, all origins", "",
        "Endpoints:",
    ]
    for ep in spec["endpoints"]:
        lines.append(f"  GET {ep['path']}")
        lines.append(f"      params: {ep['params']}")
    lines.append("")
    lines.append("License: " + spec["license"])
    from flask import Response
    return Response("\n".join(lines), mimetype="text/plain")


@bp.get("/api/v1/articles")
def api_v1_articles():
    """List articles with filters. Excludes body (use /article/<id> for full content)."""
    from flask import request as _req
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err

    source = (_req.args.get("source") or "").strip()[:80]
    bias = (_req.args.get("bias") or "").strip()[:20]
    province = (_req.args.get("province") or "").strip().upper()[:2]
    country = (_req.args.get("country") or "").strip().upper()[:2]
    since = (_req.args.get("since") or "").strip()[:25]  # ISO 8601 stub
    try:
        limit = min(100, max(1, int(_req.args.get("limit", 50))))
        offset = max(0, int(_req.args.get("offset", 0)))
    except (TypeError, ValueError):
        return _api_cors_response({"ok": False, "error": "invalid_limit_or_offset"}, status=400)

    S = _schema()
    where = ["1=1"]
    params = {"limit": limit, "offset": offset}
    if source:
        where.append("s.slug = :source"); params["source"] = source
    if bias:
        where.append("b.band = :bias"); params["bias"] = bias
    if province:
        where.append("a.province_code = :province"); params["province"] = province
    if country:
        where.append("a.country_code = :country"); params["country"] = country
    if since:
        where.append("a.published_at >= :since::timestamp"); params["since"] = since
    where_clause = " AND ".join(where)

    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, a.province_code,
                   a.country_code, a.geo_scope, a.analysis_tier,
                   s.slug AS source_slug, s.name AS source_name,
                   s.bias_lean AS source_bias_lean,
                   b.band AS bias_band, b.score AS bias_score
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE {where_clause}
            ORDER BY a.published_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    return _api_cors_response({
        "ok": True,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "articles": [
            {
                "id": r["id"],
                "title": r["title"],
                "url": r["url"],
                "published_at": r["published_at"].isoformat() if r.get("published_at") else None,
                "source": {"slug": r["source_slug"], "name": r["source_name"],
                           "bias_lean": r["source_bias_lean"]},
                "bias": {"band": r["bias_band"],
                         "score": float(r["bias_score"]) if r["bias_score"] is not None else None},
                "geo": {"province_code": r["province_code"],
                        "country_code": r["country_code"],
                        "scope": r["geo_scope"]},
                "analysis_tier": r["analysis_tier"],
            }
            for r in rows
        ],
    })


@bp.get("/api/v1/sources")
def api_v1_sources():
    """List all WTF sources."""
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT slug, name, url, country, language,
                   bias_lean, owner_name, owner_type
            FROM {S}.sources
            ORDER BY name
        """)).mappings().all()
    return _api_cors_response({
        "ok": True,
        "count": len(rows),
        "sources": [dict(r) for r in rows],
    })


@bp.get("/api/v1/bias-distribution")
def api_v1_bias_distribution():
    """Aggregate bias counts grouped by source. Defaults to last 7d."""
    from flask import request as _req
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err
    since = (_req.args.get("since") or "").strip()[:25]
    S = _schema()
    floor_clause = ":since::timestamp" if since else "NOW() - INTERVAL '7 days'"
    params = {}
    if since:
        params["since"] = since
    with _db().begin() as c:
        overall = c.execute(text(f"""
            SELECT COALESCE(b.band, 'unscored') AS band, COUNT(*) AS n
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.published_at > {floor_clause}
            GROUP BY 1 ORDER BY 2 DESC
        """), params).mappings().all()
        by_source = c.execute(text(f"""
            SELECT s.slug, s.bias_lean,
                   COUNT(*) AS articles,
                   COUNT(*) FILTER (WHERE b.band IS NOT NULL) AS scored,
                   AVG(b.score)::numeric(5,3) AS avg_score
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.published_at > {floor_clause}
            GROUP BY s.slug, s.bias_lean
            ORDER BY articles DESC
        """), params).mappings().all()
    return _api_cors_response({
        "ok": True,
        "window": since or "7d",
        "overall": [dict(r) for r in overall],
        "by_source": [
            {"slug": r["slug"], "bias_lean": r["bias_lean"],
             "articles": int(r["articles"]), "scored": int(r["scored"]),
             "avg_score": float(r["avg_score"]) if r["avg_score"] is not None else None}
            for r in by_source
        ],
    })


# ───────────────────────────────────────────────────────────────────────────
# Blindspot Feed (#3006) — Stories covered by very few outlets
# ───────────────────────────────────────────────────────────────────────────


@bp.get("/blindspot")
def blindspot_page():
    """Dedicated Blindspot Feed page."""
    return render_template("blindspot.html",
                           source_count=46,
                           is_subscriber=is_subscriber())


@bp.get("/api/v1/blindspot")
def api_v1_blindspot():
    """#3006 — Underreported stories: clusters with low coverage_gap_score.

    A blindspot = a story covered by only 1–2 outlets while the rest of the
    press stays silent. coverage_gap_score ≤ 0.15 means <15 % of tracked
    outlets published on this cluster.

    Query params:
      limit         int   default 20   max 100
      days          int   default 7    look-back window
      max_gap_score float default 0.15 coverage threshold
    """
    from flask import request as _req
    limit = min(int(_req.args.get("limit", 20)), 100)
    days = min(int(_req.args.get("days", 7)), 90)
    max_gap = float(_req.args.get("max_gap_score", 0.15))
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
    return _api_cors_response({
        "ok": True,
        "days": days,
        "max_gap_score": max_gap,
        "blindspots": [{
            "id": r["id"],
            "title": r["representative_title"],
            "article_count": r["article_count"],
            "source_count": r["source_count"],
            "coverage_gap_score": round(float(r["coverage_gap_score"] or 0), 3),
            "certainty_label": r["certainty_label"],
            "earliest": r["earliest_published_at"].isoformat() if r["earliest_published_at"] else None,
            "latest": r["latest_published_at"].isoformat() if r["latest_published_at"] else None,
            "headline": r["headline"],
            "brief": r["brief"],
        } for r in rows],
    })


# ───────────────────────────────────────────────────────────────────────────
# FR/EN Divergence Alert (#3003) — Different stories in French vs English
# ───────────────────────────────────────────────────────────────────────────


@bp.get("/divergence")
def divergence_page():
    """French-English coverage divergence page."""
    return render_template("divergence.html",
                           source_count=46,
                           is_subscriber=is_subscriber())


@bp.get("/api/v1/divergence")
def api_v1_divergence():
    """#3003 — Clusters where French and English outlets tell a different story.

    Three divergence types:
    - en_only: story exists in English press but not French
    - fr_only: story exists in French press but not English
    - bias_gap: both cover it, but avg bias scores differ significantly

    Query params:
      limit          int   default 20   max 100
      days           int   default 30   look-back window
      min_divergence float default 0.1  minimum |en_score - fr_score|
    """
    from flask import request as _req
    limit = min(int(_req.args.get("limit", 20)), 100)
    days = min(int(_req.args.get("days", 30)), 90)
    min_div = float(_req.args.get("min_divergence", 0.1))
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            WITH cluster_lang AS (
                SELECT
                    a.cluster_id,
                    COUNT(*)         FILTER (WHERE s.language = 'en') AS en_count,
                    COUNT(*)         FILTER (WHERE s.language = 'fr') AS fr_count,
                    AVG(b.score)     FILTER (WHERE s.language = 'en') AS en_avg_score,
                    AVG(b.score)     FILTER (WHERE s.language = 'fr') AS fr_avg_score
                FROM {S}.articles a
                JOIN {S}.sources s ON s.id = a.source_id
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                WHERE a.cluster_id IS NOT NULL
                  AND a.published_at >= NOW() - INTERVAL '1 day' * :days
                GROUP BY a.cluster_id
            )
            SELECT
                cl.cluster_id           AS id,
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
                )::numeric, 3)          AS divergence_score,
                (cl.fr_count = 0)       AS en_only,
                (cl.en_count = 0)       AS fr_only
            FROM cluster_lang cl
            JOIN {S}.story_clusters sc ON sc.id = cl.cluster_id
            WHERE (cl.en_count > 0 OR cl.fr_count > 0)
              AND ABS(COALESCE(cl.en_avg_score, 0) - COALESCE(cl.fr_avg_score, 0)) >= :min_div
            ORDER BY divergence_score DESC, sc.latest_published_at DESC
            LIMIT :n
        """), {"days": days, "min_div": min_div, "n": limit}).mappings().all()
    return _api_cors_response({
        "ok": True,
        "days": days,
        "min_divergence": min_div,
        "divergence": [{
            "id": r["id"],
            "title": r["representative_title"],
            "article_count": r["article_count"],
            "certainty_label": r["certainty_label"],
            "latest": r["latest_published_at"].isoformat() if r["latest_published_at"] else None,
            "en_count": r["en_count"],
            "fr_count": r["fr_count"],
            "en_avg_score": float(r["en_avg_score"]) if r["en_avg_score"] is not None else None,
            "fr_avg_score": float(r["fr_avg_score"]) if r["fr_avg_score"] is not None else None,
            "divergence_score": round(float(r["divergence_score"]), 3),
            "en_only": bool(r["en_only"]),
            "fr_only": bool(r["fr_only"]),
        } for r in rows],
    })


# ───────────────────────────────────────────────────────────────────────────
# Map page (#2961) — Leaflet map of articles pinned by lat/lng
# ───────────────────────────────────────────────────────────────────────────


@bp.get("/map")
def map_page():
    """Public map view — articles pinned globally by their lat/lng."""
    return render_template("map.html", source_count=46, is_subscriber=is_subscriber())


@bp.get("/api/v1/map-data")
def api_map_data():
    """JSON pin data for /map. Aggregates by (lat, lng) cluster to avoid
    1,700+ stacked dots at province centroids. Returns up to 3 sample
    article titles + a total count per pin.
    """
    from flask import jsonify
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT
                ROUND(a.lat::numeric, 2) AS lat,
                ROUND(a.lng::numeric, 2) AS lng,
                COALESCE(a.country_code, '??') AS country_code,
                COALESCE(a.province_code, '') AS province_code,
                COUNT(*) AS article_count,
                (ARRAY_AGG(a.id ORDER BY a.published_at DESC))[1:3] AS sample_ids,
                (ARRAY_AGG(a.title ORDER BY a.published_at DESC))[1:3] AS sample_titles,
                (ARRAY_AGG(s.name ORDER BY a.published_at DESC))[1:3] AS sample_sources,
                MAX(a.published_at) AS latest
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.lat IS NOT NULL AND a.lng IS NOT NULL
              AND a.published_at > NOW() - INTERVAL '7 days'
            GROUP BY 1, 2, 3, 4
            ORDER BY article_count DESC
            LIMIT 500
        """)).mappings().all()
    pins = []
    for r in rows:
        pins.append({
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "country_code": r["country_code"],
            "province_code": r["province_code"],
            "article_count": int(r["article_count"]),
            "samples": [
                {"id": sid, "title": (title or "")[:120], "source": src or ""}
                for sid, title, src in zip(
                    r["sample_ids"] or [],
                    r["sample_titles"] or [],
                    r["sample_sources"] or [],
                )
            ],
            "latest": r["latest"].isoformat() if r["latest"] else None,
        })
    return jsonify({"ok": True, "pins": pins, "window_days": 7})


# ───────────────────────────────────────────────────────────────────────────
# Custom alerts (#2913) — subscriber-gated keyword/topic tracking
# ───────────────────────────────────────────────────────────────────────────


def _user_email() -> str | None:
    """Return the signed-in user's WTF email or None."""
    from flask import session
    return session.get("wtf_email") or None


@bp.get("/alerts")
def alerts_page():
    """Subscriber-only — list user's alerts + form to add new ones."""
    from flask import session, redirect
    email = _user_email()
    if not email:
        return redirect("/login?next=/alerts")
    if not is_subscriber():
        return redirect("/connect?gated=alerts")
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT id, keyword, source_slug, bias_band, province_code,
                   active, created_at, last_sent_at, sent_count
            FROM {S}.user_alerts
            WHERE user_email = :email
            ORDER BY created_at DESC
        """), {"email": email}).mappings().all()
        sources = c.execute(text(f"""
            SELECT slug, name, bias_lean FROM {S}.sources
            ORDER BY name
        """)).mappings().all()
    return render_template("alerts.html",
                           alerts=[dict(r) for r in rows],
                           sources=[dict(s) for s in sources],
                           user_email=email)


@bp.post("/alerts")
def alerts_create():
    """Create a new alert rule. Subscriber-gated."""
    from flask import request as _req, redirect
    if not _user_email() or not is_subscriber():
        return redirect("/login?next=/alerts")
    email = _user_email()
    keyword = (_req.form.get("keyword") or "").strip()[:120]
    if not keyword:
        return redirect("/alerts?error=keyword_required")
    source_slug = (_req.form.get("source_slug") or "").strip()[:80] or None
    bias_band = (_req.form.get("bias_band") or "").strip()[:20] or None
    province_code = (_req.form.get("province_code") or "").strip().upper()[:2] or None
    S = _schema()
    try:
        with _db().begin() as c:
            c.execute(text(f"""
                INSERT INTO {S}.user_alerts
                    (user_email, keyword, source_slug, bias_band, province_code)
                VALUES (:email, :kw, :src, :bias, :prov)
                ON CONFLICT (user_email, keyword, source_slug, bias_band, province_code)
                  DO UPDATE SET active = TRUE
            """), {"email": email, "kw": keyword, "src": source_slug,
                   "bias": bias_band, "prov": province_code})
    except Exception:
        return redirect("/alerts?error=db")
    return redirect("/alerts?added=1")


@bp.post("/alerts/<int:alert_id>/delete")
def alerts_delete(alert_id: int):
    """Remove an alert (subscriber-gated, must own the row)."""
    from flask import redirect
    email = _user_email()
    if not email or not is_subscriber():
        return redirect("/login?next=/alerts")
    S = _schema()
    with _db().begin() as c:
        c.execute(text(f"""
            DELETE FROM {S}.user_alerts
            WHERE id = :id AND user_email = :email
        """), {"id": alert_id, "email": email})
    return redirect("/alerts?deleted=1")


@bp.post("/api/upgrade-tier2/<int:article_id>")
def upgrade_tier2(article_id: int):
    """Phase D (#2943): force a Tier-2 upgrade on a Tier-1-only article.

    Subscriber-gated. Dispatches 'deep_analysis' via hub WTF Hub. On success,
    upgrades wtf.bias_scores + wtf.fact_checks rows and stamps analysis_tier =
    'quick_v1+full' on wtf.articles. Returns the new analysis sections.

    Synchronous: hub call can take up to 90s for cold qwen2.5:7b. Client UI
    already shows "this may take up to 90 seconds" wait state.
    """
    import json as _json
    from flask import jsonify
    if not is_subscriber():
        return jsonify({"ok": False, "error": "subscriber_required"}), 402

    S = _schema()
    hub_url = os.environ.get("WTF_HUB_URL", "")
    hub_token = os.environ.get("WTF_HUB_TOKEN", "")
    if not hub_url or not hub_token:
        return jsonify({"ok": False, "error": "hub_not_configured"}), 503

    # Fetch article context
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.analysis_tier, s.slug AS source_slug
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if row["analysis_tier"] == "quick_v1+full":
        return jsonify({"ok": True, "result": "already_upgraded"})

    # Dispatch to hub
    try:
        import requests as _req
        resp = _req.post(
            f"{hub_url}/tools/wtf-hub/api/analyze",
            json={
                "task": "deep_analysis",
                "article_id": article_id,
                "title": row["title"] or "",
                "body": (row["body"] or "")[:3000],
                "source_slug": row["source_slug"] or "",
            },
            headers={
                "Authorization": f"Bearer {hub_token}",
                "Content-Type": "application/json",
            },
            timeout=int(os.environ.get("WTF_HUB_TIMEOUT", "90")),
        )
        resp.raise_for_status()
        data = resp.json()
    except _req.Timeout:
        return jsonify({"ok": False, "error": "hub_timeout"}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": f"dispatch_failed: {str(exc)[:200]}"}), 502

    if not data.get("ok"):
        return jsonify({"ok": False, "error": data.get("error") or "hub_rejected"}), 502
    if data.get("rate_limited"):
        return jsonify({"ok": False, "error": "hub_rate_limited", "retry_after": data.get("retry_after")}), 429

    result = data.get("result") or {}
    bias_summary = result.get("bias_summary") or {}
    claims = result.get("key_claims") or []

    # Persist the upgrade. wtf.bias_scores + wtf.fact_checks rows may already
    # exist from Tier-1 (synthesized). UPDATE in place — single transaction.
    with _db().begin() as c:
        # Bias upgrade — fill rationale + trigger_phrases + score
        c.execute(text(f"""
            UPDATE {S}.bias_scores
            SET band = COALESCE(:band, band),
                score = COALESCE(:score, score),
                rationale = :rationale,
                trigger_phrases = CAST(:trig AS JSONB),
                confidence = COALESCE(:conf, confidence)
            WHERE article_id = :id
        """), {
            "id": article_id,
            "band": bias_summary.get("band"),
            "score": bias_summary.get("score"),
            "rationale": bias_summary.get("rationale"),
            "trig": _json.dumps(bias_summary.get("trigger_phrases") or []),
            "conf": bias_summary.get("confidence"),
        })

        # Fact-check upgrade — replace synthesized rows with real verdicts.
        # Delete existing rows then insert fresh ones (claim list shape changes).
        c.execute(text(f"DELETE FROM {S}.fact_checks WHERE article_id = :id"),
                  {"id": article_id})
        for cl in claims:
            verdict_raw = (cl.get("verdict") or "unverifiable").strip().lower()
            verdict = {
                "verified": "true", "true": "true",
                "mostly true": "mostly_true", "mostly_true": "mostly_true",
                "mixed": "mixed", "partly true": "mixed", "disputed": "mixed",
                "false": "false", "misleading": "false",
                "unverifiable": "unverified", "unverified": "unverified",
            }.get(verdict_raw, "unverified")
            c.execute(text(f"""
                INSERT INTO {S}.fact_checks
                    (article_id, claim, verdict, evidence, checker, analyzed_by)
                VALUES (:id, :claim, :verdict, :evidence, 'V.E.R.I.F.Y.', 'V.E.R.I.F.Y.')
            """), {
                "id": article_id,
                "claim": (cl.get("text") or "(claim text missing)")[:500],
                "verdict": verdict,
                "evidence": (cl.get("reasoning") or "")[:1000],
            })

        # Tier marker
        c.execute(text(f"""
            UPDATE {S}.articles
            SET analysis_tier = 'quick_v1+full',
                tier2_at = NOW(),
                tier2_pending = FALSE
            WHERE id = :id
        """), {"id": article_id})

    return jsonify({
        "ok": True,
        "analysis_tier": "quick_v1+full",
        "bias_summary": bias_summary,
        "claims_count": len(claims),
    })
