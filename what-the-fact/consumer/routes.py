import datetime
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
                           agent_stats=_fetch_agent_stats())


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
                   a.analysis_tier, a.tier2_pending,
                   a.bias_v2_score, a.bias_v2_label,
                   a.bias_ensemble_score, a.bias_ensemble_band,
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

    return render_template("article.html", a=a, wtf_tech_url=wtf_tech_url,
                           is_subscriber=subscribed)


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
# Map page (#2961) — Leaflet map of articles pinned by lat/lng
# ───────────────────────────────────────────────────────────────────────────


@bp.get("/map")
def map_page():
    """Public map view — articles pinned globally by their lat/lng."""
    return render_template("map.html", source_count=46)


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
