import json
import os
import time
import urllib.request

from flask import Blueprint, render_template, abort
from sqlalchemy import create_engine, text
from .auth import is_subscriber

bp = Blueprint("wtf", __name__)
_engine = None
_PLATFORM = "https://platform.kytranempowerment.com"

# Portrait cache — fetches live URLs from platform /api/public/directory
# so agent portraits update automatically when approved without a code change.
_PORTRAIT_CACHE: dict = {}
_PORTRAIT_CACHE_TTL = 3600  # 1 hour


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
    band_filter = _req.args.get("band", "all")
    if band_filter not in VALID_BANDS:
        band_filter = "all"
    offset = (page - 1) * PAGE_SIZE

    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
        band_params = {}
        if band_filter == "all":
            band_where = ""
        else:
            band_where = "AND b.band = :band"
            band_params["band"] = band_filter
        total = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 {band_where}
        """), band_params).scalar() or 0
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band, a.ai_analyzed, a.province_code
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
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
              (SELECT COUNT(*) FROM {S}.articles WHERE province_code IS NOT NULL) AS geo_mapped,
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested') AS fact_ingested,
              (SELECT COUNT(*) FROM {S}.summaries) AS draft_summarized,
              (SELECT COUNT(*) FROM {S}.story_clusters) AS ink_clustered,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed=true) AS llm_analyzed
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
                           stats=dict(stats))


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
                   a.ai_analyzed,
                   a.province_code
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            ORDER BY a.published_at DESC LIMIT 50
        """)).mappings().all()
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
    return render_template("index.html", articles=rows, wtf_tech_url=wtf_tech_url,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.get("/article/<int:article_id>")
def article(article_id: int):
    import json as _json
    S = _schema()
    wtf_tech_url = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at,
                   a.ai_analyzed, a.province_code, a.cluster_id,
                   s.name AS source_name,
                   b.band AS bias_band, b.score AS bias_score,
                   b.rationale AS bias_rationale, b.trigger_phrases,
                   fc.overall_verdict, fc.claims AS fact_check_claims
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.fact_checks fc ON fc.article_id = a.id
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        abort(404)
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

    return render_template("article.html", a=a, wtf_tech_url=wtf_tech_url,
                           is_subscriber=subscribed)
