import datetime
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from flask import (
    Blueprint, render_template, abort, Response, request, jsonify, session,
    redirect, url_for,
)

from sqlalchemy import create_engine, text
from . import rate_limit as _rate_limit  # shared bucket store (#5747/#5748)
from . import rate_policy as _rate_policy  # pure, stdlib-only decision logic
from .auth import is_subscriber

import logging

bp = Blueprint("wtf", __name__)

# Module logger. Error paths in the API-key routes (#2138) use this; before it
# existed the only logging here was an inline `import logging` at one call site.
logger = logging.getLogger(__name__)
_engine = None
_PLATFORM = "https://platform.kytranempowerment.com"

# Sources known to restrict RSS to snippet-only (paywalled originals, or
# Google-News-redirect outlets whose full body is never fetchable — #4377).
# Both render as a limited preview + "read full article at source".
_PAYWALLED_SOURCES = frozenset({
    "montreal_gazette", "national_post", "financial_post", "vancouver_sun",
    "calgary_herald", "edmonton_journal", "ottawa_citizen", "toronto_star",
    "globe_mail", "journal_de_montreal", "le_devoir", "la_presse",
    "le_soleil", "le_quotidien",
    "winnipeg_free_press", "cbc_english",  # #4377: RSS-only, no fetchable full body
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


# C.R.E.E.D. governance scan cache — 300s TTL (task #3358)
_CREED_SCAN_CACHE: dict = {}
_CREED_SCAN_CACHE_TTL = 300


def _fetch_creed_scan() -> dict | None:
    """Return WTF's OWN C.R.E.E.D. tenant score as a flat dict, or None on error.

    Repointed (#4898, ADR-011) from the Institute alias /api/v1/scores to the
    what-the-fact ORG tenant — 9 News & Media agents emit governance events to
    it, so this is the AI newsroom's own score, not the Institute's self-score.
    Calls CREED_API_URL (mesh value on VPS: http://100.64.0.4:8086) server-side
    so the internal URL is never exposed to browser JS (KB #267314).
    300s cache. Fail-open — returns None so templates skip the banner.
    """
    now = time.time()
    if _CREED_SCAN_CACHE.get("ts", 0) + _CREED_SCAN_CACHE_TTL > now:
        return _CREED_SCAN_CACHE.get("data")
    creed_url = os.environ.get("CREED_API_URL", "https://creed.kytranempowerment.com")
    try:
        req = urllib.request.Request(
            f"{creed_url}/api/v1/orgs/what-the-fact/scores",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read())
        data = {
            "overall": int(raw.get("overall") or 0),
            "grade": raw.get("grade") or "?",
            "event_count": int(raw.get("event_count") or 0),
            # per-pillar dicts: {score, grade, events, provisional, note}
            "by_category": raw.get("by_category") or {},
            # pillars with enough events (>=100) to count toward the overall
            "overall_categories": raw.get("overall_categories") or [],
            "freshness": raw.get("freshness") or {},
            "ok": True,
        }
        _CREED_SCAN_CACHE["ts"] = now
        _CREED_SCAN_CACHE["data"] = data
        return data
    except Exception:
        # Fail-open: governance banner simply won't render if C.R.E.E.D. is unreachable
        return _CREED_SCAN_CACHE.get("data")


_WELFARE_CACHE: dict = {}
_WELFARE_CACHE_TTL = 120  # 2 min — welfare is live data


def _swr(cache: dict, ttl: int, fetch_fn) -> dict:
    """Stale-while-revalidate for the module-level lookup caches (#5726):
    on TTL expiry serve the STALE data immediately and refresh in a daemon
    thread — a visitor never pays the hub round-trip (the welfare
    fleet-agents call measured 2.5s cold; with 4 workers × 2-min TTL that
    was up to 4 slow /team loads every 2 minutes). Only the first-ever
    request in a worker blocks. A failed refresh keeps the stale data and
    clears the flag so the next request retries."""
    now = time.time()
    if cache.get("ts", 0) + ttl > now:
        return cache.get("data", {})
    if cache.get("data") is not None:
        if not cache.get("refreshing"):
            cache["refreshing"] = True
            threading.Thread(target=_swr_refresh, args=(cache, fetch_fn),
                             daemon=True).start()
        return cache["data"]
    return _swr_refresh(cache, fetch_fn)


def _swr_refresh(cache: dict, fetch_fn) -> dict:
    try:
        data = fetch_fn()
        cache["data"] = data
        cache["ts"] = time.time()
        return data
    except Exception:
        return cache.get("data") or {}
    finally:
        cache["refreshing"] = False


def _fetch_welfare() -> dict:
    """One live fetch of the News & Media welfare lookup (raises on error —
    _swr_refresh handles fail-open)."""
    hub_url = os.environ.get("WTF_HUB_URL", "")
    if not hub_url:
        return {}
    headers = {"Accept": "application/json"}
    hub_token = os.environ.get("WTF_HUB_TOKEN", "")
    if hub_token:
        headers["Authorization"] = f"Bearer {hub_token}"
    req = urllib.request.Request(
        f"{hub_url}/tools/department-hq/api/creed/fleet-agents",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read())
    seen: set = set()
    lookup: dict = {}
    for node in (data.get("nodes") or []):
        for a in (node.get("agents") or []):
            if a.get("department") != "News & Media":
                continue
            uid = a.get("id") or a.get("display_name")
            if uid in seen:
                continue
            seen.add(uid)
            dname = a.get("display_name", "")
            if dname:
                lookup[dname] = {
                    "welfare_score": a.get("welfare_score"),
                    "stress": a.get("stress_level"),
                    "energy": a.get("energy_level"),
                    "shift_state": a.get("shift_state", ""),
                }
    return lookup


def _get_welfare_lookup() -> dict:
    """Return {display_name: {welfare_score, stress, energy, shift_state}} (#3355).

    Hub fleet-agents via mesh (WTF_HUB_URL), department='News & Media',
    deduped by agent id (fleet-agents lists each agent once PER NODE — the
    #3356 bug). 2-min TTL, stale-while-revalidate (#5726), fails open so
    /team always renders.
    """
    return _swr(_WELFARE_CACHE, _WELFARE_CACHE_TTL, _fetch_welfare)


def _fetch_portraits() -> dict:
    """One live fetch of the platform portrait directory (raises on error)."""
    req = urllib.request.Request(
        f"{_PLATFORM}/api/public/directory",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    return {
        a["display_name"]: a.get("avatar_thumb_url") or a.get("avatar_url")
        for a in data.get("agents", [])
        if a.get("display_name") and (a.get("avatar_thumb_url") or a.get("avatar_url"))
    }


def _get_portrait_lookup() -> dict:
    """Return {display_name: portrait_url} from the platform directory.
    1h TTL, stale-while-revalidate (#5726)."""
    return _swr(_PORTRAIT_CACHE, _PORTRAIT_CACHE_TTL, _fetch_portraits)


def _db():
    """The engine for this request.

    Delegates to dr_mode so a hub outage serves the read-only DR archive instead
    of a dead site (#6216). With WTF_DATABASE_URL_FALLBACK unset — the normal
    deployment — this is byte-for-byte today's behaviour: the primary engine,
    no probe, no added latency.
    """
    from consumer import dr_mode

    return dr_mode.get_engine()


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
        "description": "I.N.K. detects investigative story threads across article clusters — finding the through-line when the same story unfolds across days and outlets.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/9e1efa5f-5a7.png",
        "accent_colour": "#ec4899",
    },
    {
        "name": "D.R.A.F.T.",
        "full": "Data Reduction & Factual Translation",
        "role": "Staff Writer",
        "model": "dolphin3",
        "description": "D.R.A.F.T. generates WTF editorial summaries — translating dense news cycles into plain-language explainers.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/70bc27b1-ede.png",
        "accent_colour": "#06b6d4",
    },
    {
        "name": "P.U.B.L.I.S.H.",
        "full": "Publish & Unified Broadcasting",
        "role": "Broadcast Editor",
        "model": "mistral:7b",
        "description": "P.U.B.L.I.S.H. pushes top stories to social media and newsletter subscribers, bringing AI journalism to where Canadians actually consume news.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/e7149ec2-f73.png",
        "accent_colour": "#f97316",
    },
    {
        "name": "A.U.R.O.R.A.",
        "full": "Atmospheric & Universal Resource for Observation, Research & Analysis",
        "role": "Weather Intelligence",
        "model": "qwen2.5:7b",
        "description": "Tracks climate and severe-weather coverage across our Canadian news sources — because in Canada, the weather IS the news.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-30/7b1193b5-868.png",
        "accent_colour": "#7c3aed",
    },
]


@bp.get("/api/stats")
def api_stats():
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    from flask import jsonify
    S = _schema()
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM {S}.sources) AS sources,
              -- Count what the site SHOWS. These are published figures, and a
              -- suppressed row is one the site deliberately hides — counting it
              -- overstates the corpus by the exact number we chose not to serve
              -- (8,288 duplicate_refetch after #3036, plus migration 056's).
              (SELECT COUNT(*) FROM {S}.articles
                WHERE suppressed_reason IS NULL) AS articles,
              (SELECT COUNT(*) FROM {S}.articles
                WHERE ai_analyzed=true AND suppressed_reason IS NULL) AS llm_analyzed,
              -- ⚠️ Join the article to exclude suppressed ones. Counting bias_scores
              -- flat published MORE articles bias-scored (115,353) than articles
              -- exist (115,279) — impossible arithmetic, visible on the public API.
              (SELECT COUNT(*) FROM {S}.bias_scores b
                 JOIN {S}.articles a ON a.id = b.article_id
                WHERE a.suppressed_reason IS NULL) AS bias_scored,
              (SELECT COUNT(*) FROM {S}.story_clusters) AS clusters
        """)).mappings().first()
    return jsonify(dict(row))


@bp.get("/join")
def join():
    S = _schema()
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
        total_articles = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.articles")
        ).scalar() or 0
    return render_template("connect.html", source_count=source_count,
                           total_articles=total_articles)


VALID_BEATS = {
    "all", "sports", "municipal", "business", "healthcare", "science-tech",
    "transportation", "arts-culture", "crime", "education", "indigenous",
    "foreign-policy", "climate", "economy", "parliament", "justice",
    "immigration", "housing", "labour",
}
BEAT_META = [
    ("all",            "All Beats",      ""),
    ("sports",         "⚽ Sports",       "#f59e0b"),
    ("municipal",      "🏙 Municipal",    "#60a5fa"),
    ("business",       "💼 Business",     "#34d399"),
    ("healthcare",     "🏥 Health",       "#f472b6"),
    ("science-tech",   "🔬 Sci-Tech",     "#a78bfa"),
    ("transportation", "🚌 Transit",      "#94a3b8"),
    ("arts-culture",   "🎭 Arts",         "#fb923c"),
    ("crime",          "🚨 Crime",        "#ef4444"),
    ("education",      "📚 Education",    "#38bdf8"),
    ("indigenous",     "🪶 Indigenous",   "#86efac"),
    ("foreign-policy", "🌍 Foreign",      "#fbbf24"),
    ("climate",        "🌱 Climate",      "#4ade80"),
    ("economy",        "📈 Economy",      "#f97316"),
    ("parliament",     "🏛 Parliament",   "#818cf8"),
    ("justice",        "⚖️ Justice",     "#c084fc"),
    ("immigration",    "🛂 Immigration",  "#67e8f9"),
    ("housing",        "🏠 Housing",      "#fcd34d"),
    ("labour",         "⚒️ Labour",      "#a3e635"),
]
VALID_SCOPES = {"all", "national", "provincial", "international"}


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
    beat_filter = _req.args.get("beat", "all")
    scope_filter = _req.args.get("scope", "all")
    riding_filter = (_req.args.get("riding") or "all").strip()
    if band_filter not in VALID_BANDS:
        band_filter = "all"
    if province_filter not in VALID_PROVINCES:
        province_filter = "all"
    if beat_filter not in VALID_BEATS:
        beat_filter = "all"
    if scope_filter not in VALID_SCOPES:
        scope_filter = "all"
    offset = (page - 1) * PAGE_SIZE

    if not _news_rate_ok(_client_ip()):
        return Response("Too many requests — slow down.", 429, {"Retry-After": "30"})

    # Faceted-crawl guard: crawlers walking /news?band=…&province=…&page=N
    # permutations defeat both defenses above — each permutation is a unique
    # cache key (always a miss → full DB query) and bot fleets spread across
    # IPs stay under the per-IP limiter (GPTBot was 91% of traffic on
    # 2026-08-18). Compliant bots are told via robots.txt (Disallow: /news?);
    # this shared bucket bounds the remainder. Clean /news is never throttled.
    if _req.args and _is_crawler_ua(_req.headers.get("User-Agent", "")):
        if not _crawler_facet_rate_ok():
            return Response("Faceted /news is rate-limited for crawlers — see /robots.txt.",
                            429, {"Retry-After": "300"})

    # UA-BLIND ceiling. The guard above only fires for a SELF-DECLARED crawler,
    # so a fleet presenting browser UAs walked straight past it on 2026-08-30 and
    # wedged all 4 workers (~378 faceted req/min). This one asks only "is this a
    # faceted request?", which is what actually costs a DB query.
    if _req.args and not _facet_any_rate_ok():
        return Response("Faceted /news is busy — retry shortly, or browse /news unfiltered.",
                        429, {"Retry-After": "60"})

    _ck = (band_filter, province_filter, beat_filter, scope_filter, riding_filter, page)
    _cached = _news_cache_get(_ck)
    if _cached is not None:
        source_count, total, rows, sources, ridings = _cached
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return render_template("news.html", articles=rows, source_count=source_count,
                               total=total, page=page, total_pages=total_pages,
                               page_size=PAGE_SIZE, band_filter=band_filter,
                               province_filter=province_filter,
                               beat_filter=beat_filter, scope_filter=scope_filter,
                               riding_filter=riding_filter, ridings=ridings,
                               beat_meta=BEAT_META, sources=sources,
                               is_subscriber=is_subscriber())

    with _db().begin() as c:
        # JIT compilation alone cost 3.5s on this route's big query (its
        # correlated-subquery cost estimate keeps JIT triggered even after
        # the rewrite below). Transaction-scoped, read-only-safe. #5719
        c.execute(text("SET LOCAL jit = off"))
        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
        params = {}
        where_clauses = []
        if band_filter != "all":
            where_clauses.append("b.band = :band")
            params["band"] = band_filter
        if province_filter != "all":
            where_clauses.append("a.province_code = :province")
            params["province"] = province_filter
        if beat_filter != "all":
            where_clauses.append("a.beat = :beat")
            params["beat"] = beat_filter
        if scope_filter != "all":
            where_clauses.append("a.geo_scope = :scope")
            params["scope"] = scope_filter
        if riding_filter != "all":
            where_clauses.append(
                "EXISTS (SELECT 1 FROM wtf.article_mp_tags t"
                " JOIN parliament.mps m ON m.id = t.mp_id"
                " WHERE t.article_id = a.id AND m.riding_name = :riding)"
            )
            params["riding"] = riding_filter
        band_where = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""
        total = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL {band_where}
        """), params).scalar() or 0
        # #5719 rewrite — the old form joined fact_checks/decorations across
        # the WHOLE table before ranking: the newest-per-cluster subquery ran
        # 107,885× (planner can't push the LIMIT below the WindowAgg), and the
        # unindexed fact_checks fan-out both cost ~500ms AND duplicated
        # articles on the page (86k articles carry >1 non-GoogleFCT check —
        # a 50-row page measurably returned 104 rows). Now: pick the top-300
        # FIRST via a backward ix_articles_published_at walk (~360 rows
        # visited), rank just those, and decorate ONLY the final page. The
        # src_rank semantics are identical: any same-source article newer
        # than a top-300 member is itself in the top-300. The fc LATERAL
        # LIMIT 1 yields exactly one row per article (newest check wins).
        rows = c.execute(text(f"""
            WITH top_recent AS MATERIALIZED (
                SELECT a.id, a.title, a.url, a.published_at,
                       a.source_id, b.band, a.ai_analyzed, a.province_code,
                       a.beat, a.geo_scope, a.cluster_id
                FROM {S}.articles a
                JOIN {S}.sources s ON s.id = a.source_id
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                WHERE 1=1 AND a.suppressed_reason IS NULL {band_where}
                AND (a.cluster_id IS NULL OR a.id = (
                    SELECT a2.id FROM {S}.articles a2
                    WHERE a2.cluster_id = a.cluster_id
                    ORDER BY a2.published_at DESC LIMIT 1
                ))
                ORDER BY a.published_at DESC, a.id DESC
                LIMIT {PAGE_SIZE * 6}
            ),
            ranked AS (
                SELECT tr.*,
                       ROW_NUMBER() OVER (PARTITION BY tr.source_id
                                          ORDER BY tr.published_at DESC,
                                                   tr.id DESC) AS src_rank
                FROM top_recent tr
            ),
            page AS (
                SELECT * FROM ranked
                WHERE src_rank <= {max(PAGE_SIZE // 4, 3)}
                ORDER BY published_at DESC, id DESC
                LIMIT {PAGE_SIZE} OFFSET {offset}
            )
            SELECT p.id, p.title, p.url, p.published_at,
                   s.name AS source, p.source_id, p.band, p.ai_analyzed,
                   p.province_code, p.beat, p.geo_scope,
                   p.cluster_id, sc.article_count AS cluster_size,
                   fc.overall_verdict,
                   (SELECT STRING_AGG(m.name, ', ' ORDER BY m.name)
                    FROM {S}.article_mp_tags tg
                    JOIN parliament.mps m ON m.id = tg.mp_id
                    WHERE tg.article_id = p.id) AS mp_mentions,
                   p.src_rank
            FROM page p
            JOIN {S}.sources s ON s.id = p.source_id
            LEFT JOIN {S}.story_clusters sc ON sc.id = p.cluster_id
            LEFT JOIN LATERAL (
                SELECT fc2.overall_verdict
                FROM {S}.fact_checks fc2
                WHERE fc2.article_id = p.id
                  AND fc2.checker NOT LIKE 'GoogleFCT%%'
                ORDER BY fc2.id DESC
                LIMIT 1
            ) fc ON true
            ORDER BY p.published_at DESC, p.id DESC
        """), params).mappings().all()

        # Pre-aggregate per-source counts instead of grouping 107k wide
        # joined rows — measured 305ms → 66ms (#5719).
        sources = c.execute(text(f"""
            SELECT s.name, s.url, s.bias_lean,
                   obs.avg_score, obs.band AS bias_band,
                   COALESCE(ac.article_count, 0) AS article_count
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN (
                SELECT source_id, COUNT(*) AS article_count
                FROM {S}.articles GROUP BY source_id
            ) ac ON ac.source_id = s.id
            ORDER BY COALESCE(ac.article_count, 0) DESC
        """)).mappings().all()

        # Ridings that have at least one tagged article — for filter dropdown
        riding_rows = c.execute(text(f"""
            SELECT m.riding_name, m.province_code, COUNT(t.article_id) AS article_count
            FROM parliament.mps m
            JOIN {S}.article_mp_tags t ON t.mp_id = m.id
            WHERE m.riding_name IS NOT NULL AND m.is_current = true
            GROUP BY m.riding_name, m.province_code
            HAVING COUNT(t.article_id) >= 5
            ORDER BY COUNT(t.article_id) DESC
            LIMIT 80
        """)).mappings().all()
        ridings = [dict(r) for r in riding_rows]

    sources = [dict(s) for s in sources]
    _news_cache_set(_ck, (source_count, total, rows, sources, ridings))
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render_template("news.html", articles=rows, source_count=source_count,
                           total=total, page=page, total_pages=total_pages,
                           page_size=PAGE_SIZE, band_filter=band_filter,
                           province_filter=province_filter,
                           beat_filter=beat_filter, scope_filter=scope_filter,
                           riding_filter=riding_filter, ridings=ridings,
                           beat_meta=BEAT_META, sources=sources,
                           is_subscriber=is_subscriber())


from .aurora_map import (  # pure, DB-free (see module docstring)
    _aurora_map_payload,
    _aurora_city_payload,
)
from .aurora_verify import (  # pure, DB-free (see module docstring)
    verification_payload as _verification_payload,
)


@bp.get("/weather")
def weather():
    """A.U.R.O.R.A. — Weather & Climate Intelligence page.

    Two independent things live here:

    1. Climate + science-tech beat articles FROM OUR NEWS SOURCES.
    2. Environmental measurements we genuinely ingest — currently CWFIS only
       (fire-weather stations, satellite hotspots, fire perimeters). Every
       source name on the page is rendered by LOOPING wtf.aurora_layer_status,
       never hardcoded, because until 2026-08-18 this page advertised
       "Environment Canada + NASA EarthData + NOAA" while holding no weather
       data at all (KB #290491). We still ingest none of those three.

    ⚠️ The two CWFIS layers are COMPLEMENTARY, not overlapping, and the map
    depends on that being handled honestly. Measured 2026-08-18:
      stations  — QC 101, ON 92, NS 67, NF 60, NB 21, NU 18, PE 6, AB 1
                  and ZERO in BC, SK, MB, YT, NT
      hotspots  — NT 6488, BC 748, YT 387, AB 114, MB 29, ON 6, SK 2, QC 1
                  and ZERO in NS, NF, NB, PE, NU
    So a single-metric choropleth is a lie in one direction or the other. The
    map switches layers and greys "no data for this layer" explicitly — a
    province with no stations must never render as if it measured zero.
    """
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band, a.province_code, a.beat,
                   a.cluster_id, sc.article_count AS cluster_size
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
            WHERE a.suppressed_reason IS NULL AND a.beat IN ('climate', 'science-tech')
            ORDER BY a.published_at DESC
            LIMIT 60
        """)).mappings().all()

        climate_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'climate'"
        )).scalar() or 0
        sci_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'science-tech'"
        )).scalar() or 0
        # base.html's nav renders "LIVE · {{ source_count }} SOURCES". This page
        # was a standalone document until 2026-08-18 and never supplied it, so
        # inheriting the shell without this would render "LIVE · 0 SOURCES".
        # Same definition every other page uses: distinct sources seen in 48h.
        source_count = c.execute(text(
            f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s "
            f"JOIN {S}.articles a ON a.source_id = s.id "
            f"AND a.ingested_at > NOW() - INTERVAL '48 hours'"
        )).scalar() or 0

        # A.U.R.O.R.A. environmental layers (project #393). Every panel below is
        # rendered from these rows, and the provenance strip LOOPS
        # aurora_layer_status — no source name is hardcoded in the template.
        # That is deliberate: the false "Environment Canada + NASA EarthData +
        # NOAA" claim removed from this page on 2026-08-18 lived in prose that
        # no query could contradict (KB #290491).
        # is_stale is computed from the layer's OWN declared threshold, never a
        # blanket window. Migration 055 added stale_after_hours (city_obs 3h,
        # city_forecast 12h, fire 48h) precisely because a fixed 48h let a
        # 40-hour-old "current condition" render as fresh on an HOURLY layer —
        # and until now nothing read the column, so that fix never took effect.
        layers = c.execute(text("""
            SELECT layer_key, layer_label, issuing_body, dataset_id, source_url,
                   data_latest, last_pull, record_count, stale_after_hours,
                   (last_pull IS NULL
                    OR last_pull < now()
                       - make_interval(hours => COALESCE(stale_after_hours, 48))
                   ) AS is_stale
            FROM wtf.aurora_layer_status ORDER BY layer_key
        """)).mappings().all()
        fire_provinces = c.execute(text("""
            SELECT prov, sum(hotspot_count) AS hotspots, max(max_fwi) AS max_fwi,
                   max(obs_date) AS obs_date
            FROM wtf.aurora_fire_hotspot_daily
            WHERE obs_date > CURRENT_DATE - 3
            GROUP BY prov ORDER BY sum(hotspot_count) DESC
        """)).mappings().all()
        fire_summary = c.execute(text("""
            SELECT snapshot_date, perimeter_count, total_area, max_area, earliest_start
            FROM wtf.aurora_fire_perimeters ORDER BY snapshot_date DESC LIMIT 1
        """)).mappings().first()
        windiest = c.execute(text("""
            SELECT station_name, prov, wind_speed_kmh, wind_gust_kmh, wind_dir_deg,
                   temp_c, rel_humidity, fwi, rep_date
            FROM wtf.aurora_firewx_obs
            WHERE rep_date = (SELECT max(rep_date) FROM wtf.aurora_firewx_obs)
              AND wind_speed_kmh IS NOT NULL
            ORDER BY wind_speed_kmh DESC LIMIT 12
        """)).mappings().all()

        # Every station at the latest reporting time, for the map. Rounded on
        # the way out — full float precision is ~40% of the payload and the
        # instruments do not justify it.
        station_rows = c.execute(text("""
            SELECT station_name, prov, lat, lon, temp_c, rel_humidity,
                   wind_speed_kmh, wind_gust_kmh, fwi
            FROM wtf.aurora_firewx_obs
            WHERE rep_date = (SELECT max(rep_date) FROM wtf.aurora_firewx_obs)
              AND lat IS NOT NULL AND lon IS NOT NULL
        """)).mappings().all()

        # Per-province station aggregate — the OTHER choropleth metric. Kept in
        # SQL rather than derived in JS so the map and any future export agree.
        station_provinces = c.execute(text("""
            SELECT prov, count(*) AS stations,
                   avg(temp_c) AS avg_temp, max(temp_c) AS max_temp,
                   min(temp_c) AS min_temp, max(wind_speed_kmh) AS max_wind,
                   max(fwi) AS max_fwi, avg(rel_humidity) AS avg_rh
            FROM wtf.aurora_firewx_obs
            WHERE rep_date = (SELECT max(rep_date) FROM wtf.aurora_firewx_obs)
            GROUP BY prov
        """)).mappings().all()

        obs_time = c.execute(text(
            "SELECT max(rep_date) FROM wtf.aurora_firewx_obs")).scalar()

        # Phase 2 — city current conditions. LATERAL to the newest observation
        # per city so a city that stopped reporting keeps its card (with an
        # honest age) instead of silently vanishing from the page.
        city_rows = c.execute(text("""
            SELECT s.site_code, s.name_en, s.display_name, s.source_prov,
                   s.lat, s.lon, s.last_obs_status,
                   o.observed_utc, o.temp_c, o.condition_text, o.rel_humidity_pct,
                   o.wind_speed_kmh, o.wind_is_calm, o.wind_gust_kmh, o.wind_dir,
                   o.humidex, o.pressure_kpa,
                   EXTRACT(EPOCH FROM (now() - o.observed_utc))/60 AS age_min
            FROM wtf.aurora_city_site s
            LEFT JOIN LATERAL (
                SELECT * FROM wtf.aurora_city_obs x
                WHERE x.site_code = s.site_code
                ORDER BY x.observed_utc DESC LIMIT 1
            ) o ON true
            WHERE s.is_city
            ORDER BY s.sort_order, s.name_en
        """)).mappings().all()

        # Newest forecast ISSUE per city — issued_utc is a real key, so this
        # picks one coherent issue rather than mixing periods across issues.
        forecast_rows = c.execute(text("""
            SELECT f.site_code, f.period_index, f.period_label,
                   f.temp_high_c, f.temp_low_c, f.pop_pct,
                   f.abbrev_summary, f.text_summary
            FROM wtf.aurora_city_forecast f
            JOIN (SELECT site_code, max(issued_utc) AS latest
                  FROM wtf.aurora_city_forecast GROUP BY site_code) m
              ON m.site_code = f.site_code AND m.latest = f.issued_utc
            ORDER BY f.site_code, f.period_index
        """)).mappings().all()

    map_payload = _aurora_map_payload(station_rows, station_provinces,
                                      fire_provinces, obs_time)
    city_payload = _aurora_city_payload(city_rows, forecast_rows)

    # One definition of "current", read from the registry rather than restated in
    # JS. Fallback matches the view's city_obs value so behaviour is unchanged if
    # the row is ever missing.
    _city_stale_min = 180
    for _l in layers:
        if _l["layer_key"] == "city_obs" and _l["stale_after_hours"]:
            _city_stale_min = int(_l["stale_after_hours"]) * 60
            break

    return render_template("weather.html",
                           city_stale_min=_city_stale_min,
                           articles=rows,
                           climate_count=climate_count,
                           sci_count=sci_count,
                           source_count=source_count,
                           layers=[dict(r) for r in layers],
                           fire_provinces=[dict(r) for r in fire_provinces],
                           fire_summary=dict(fire_summary) if fire_summary else None,
                           windiest=[dict(r) for r in windiest],
                           aurora_map=map_payload,
                           aurora_cities=city_payload,
                           obs_time=obs_time,
                           is_subscriber=is_subscriber())


@bp.get("/weather/accuracy")
def weather_accuracy():
    """A.U.R.O.R.A. — how accurate the forecast actually turned out to be.

    We already store every published daily high alongside the moment it was
    issued, and we observe the stations hourly. Joining the two lets us say
    something nobody else publishes for Canada: how far off the forecast was,
    per city, per lead time.

    Two things this route is careful about, both of which would otherwise
    flatter the numbers:

    * Only EVEN period_index rows carry a daytime high (odd ones are nights),
      so joining without that filter silently compares a high against a
      low and manufactures a large fake error.
    * The observed high is the MAX of the station's readings for that day. A
      day we did not observe produces no row at all — the aggregation in
      `aurora_verify` skips it rather than scoring it as a perfect forecast.

    All arithmetic lives in `consumer.aurora_verify`, which is stdlib-only so
    its guard tests can never silently skip (KB #290497).
    """
    S = _schema()
    with _db().connect() as c:
        pairs = c.execute(text(f"""
            WITH fc AS (
                SELECT site_code,
                       (period_index / 2) AS lead_days,
                       temp_high_c AS forecast_c,
                       ((issued_utc AT TIME ZONE 'UTC')::date
                        + (period_index / 2)) AS target_day
                  FROM {S}.aurora_city_forecast
                 WHERE temp_high_c IS NOT NULL
                   AND period_index % 2 = 0
            ),
            ob AS (
                SELECT site_code,
                       (observed_utc AT TIME ZONE 'UTC')::date AS obs_day,
                       max(temp_c) AS observed_c,
                       max(station_name) AS station_name
                  FROM {S}.aurora_city_obs
                 WHERE temp_c IS NOT NULL
                 GROUP BY 1, 2
            )
            SELECT fc.site_code, fc.lead_days, fc.forecast_c,
                   ob.observed_c,
                   COALESCE(s.display_name, s.name_en, ob.station_name) AS city,
                   s.source_prov AS province, fc.target_day
              FROM fc
              JOIN ob ON ob.site_code = fc.site_code
                     AND ob.obs_day  = fc.target_day
              LEFT JOIN {S}.aurora_city_site s ON s.site_code = fc.site_code
             WHERE fc.target_day < CURRENT_DATE
        """)).mappings().all()

    payload = _verification_payload([dict(r) for r in pairs])
    return render_template("forecast_accuracy.html",
                           verification=payload,
                           is_subscriber=is_subscriber())


@bp.get("/economy")
def economy():
    """M.A.R.K.E.T. — Economy & Markets Intelligence page.

    Aggregates economy + business + foreign-policy beat articles and
    surfaces them alongside Market Watch context.
    """
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band, a.province_code, a.beat,
                   a.cluster_id, sc.article_count AS cluster_size
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
            WHERE a.suppressed_reason IS NULL AND a.beat IN ('economy', 'business', 'foreign-policy')
            ORDER BY a.published_at DESC
            LIMIT 60
        """)).mappings().all()

        economy_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'economy'"
        )).scalar() or 0
        business_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'business'"
        )).scalar() or 0
        foreign_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'foreign-policy'"
        )).scalar() or 0

    return render_template("economy.html",
                           articles=rows,
                           economy_count=economy_count,
                           business_count=business_count,
                           foreign_count=foreign_count,
                           is_subscriber=is_subscriber())


@bp.get("/municipal")
def municipal():
    """L.O.C.A.L. — Municipal & Local Government news layer.

    Aggregates the 'municipal' beat (city hall, council, local government,
    civic affairs) across all outlets, with an optional ?city= filter.
    Public — no paywall (consistent with /weather and /economy).
    """
    S = _schema()
    active_city = (request.args.get("city") or "").strip()
    with _db().begin() as c:
        params = {}
        city_clause = ""
        if active_city:
            city_clause = " AND a.city = :city"
            params["city"] = active_city
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source, b.band, a.province_code, a.city,
                   a.cluster_id, sc.article_count AS cluster_size
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
            WHERE a.suppressed_reason IS NULL AND a.beat = 'municipal'{city_clause}
            ORDER BY a.published_at DESC
            LIMIT 60
        """), params).mappings().all()

        total = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'municipal'"
        )).scalar() or 0

        # City facets — only cities with real coverage (>=2) to keep the
        # filter honest while municipal geo-tagging is still expanding.
        cities = c.execute(text(f"""
            SELECT a.city, COUNT(*) AS n
            FROM {S}.articles a
            WHERE a.beat = 'municipal' AND a.city IS NOT NULL AND a.city <> ''
            GROUP BY a.city
            HAVING COUNT(*) >= 2
            ORDER BY n DESC
            LIMIT 15
        """)).mappings().all()

    return render_template("municipal.html",
                           articles=rows,
                           cities=cities,
                           active_city=active_city,
                           total=total,
                           is_subscriber=is_subscriber())


# /activity stats bundle cache — every block on the page except the paginated
# event feed is identical for all visitors but was recomputed per request:
# ~40 whole-table COUNTs (articles 108k / fact_checks 357k / audit_trail 214k)
# + analytics + sparklines + source-health measured 20-36s per page view.
# One shared snapshot, 5-min TTL (per gunicorn worker); the event feed stays
# per-request but each union branch is pre-sorted + capped (#5725).
_ACTIVITY_CACHE: dict = {}  # 'bundle' -> (expiry, dict) | ('total', filter) -> (expiry, int)
_ACTIVITY_CACHE_TTL = int(os.environ.get("WTF_ACTIVITY_CACHE_TTL", "300"))


def _activity_agent_queries(S):
    """Per-agent event-feed branch queries (shared by the feed page + total)."""
    return {
        "F.A.C.T.": f"""
            SELECT 'F.A.C.T.' AS agent, NULL::text AS performed_by,
                   a.id AS article_id, a.title AS title,
                   'ingested' AS result, at.created_at AS ts, s.name AS source
            FROM {S}.audit_trail at
            JOIN {S}.articles a ON a.id = at.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE at.event_type = 'ingested'""",
        "B.I.A.S.": f"""
            SELECT 'B.I.A.S.' AS agent, bs.agent_name AS performed_by,
                   a.id AS article_id, a.title AS title,
                   bs.band AS result, bs.computed_at AS ts, s.name AS source
            FROM {S}.bias_scores bs
            JOIN {S}.articles a ON a.id = bs.article_id
            JOIN {S}.sources s ON s.id = a.source_id""",
        "V.E.R.I.F.Y.": f"""
            SELECT 'V.E.R.I.F.Y.' AS agent, fc.agent_name AS performed_by,
                   a.id AS article_id, a.title AS title,
                   fc.overall_verdict AS result, fc.checked_at AS ts, s.name AS source
            FROM {S}.fact_checks fc
            JOIN {S}.articles a ON a.id = fc.article_id
            JOIN {S}.sources s ON s.id = a.source_id""",
        "L.O.C.A.L.": f"""
            SELECT 'L.O.C.A.L.' AS agent, NULL::text AS performed_by,
                   a.id AS article_id, a.title AS title,
                   a.province_code AS result, at.created_at AS ts, s.name AS source
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            JOIN {S}.audit_trail at ON at.article_id = a.id AND at.event_type = 'ingested'
            WHERE a.province_code IS NOT NULL""",
        "D.R.A.F.T.": f"""
            SELECT 'D.R.A.F.T.' AS agent, NULL::text AS performed_by,
                   NULL::int AS article_id,
                   sc.representative_title AS title,
                   'summarized' AS result, su.created_at AS ts, NULL::text AS source
            FROM {S}.summaries su
            JOIN {S}.story_clusters sc ON sc.id = su.cluster_id""",
        "I.N.K.": f"""
            SELECT 'I.N.K.' AS agent, NULL::text AS performed_by,
                   NULL::int AS article_id,
                   representative_title AS title,
                   CONCAT(article_count::text, ' article', CASE WHEN article_count = 1 THEN '' ELSE 's' END) AS result,
                   created_at AS ts, NULL::text AS source
            FROM {S}.story_clusters""",
    }


def _newsroom_agents(S):
    """Who ACTUALLY did the work in the last 24h — read from the data, never a list.

    ⚠️ THE BUG THIS REPLACES: the six "agents" on this page are PIPELINE STAGES
    whose names were hardcoded as SQL string literals (`SELECT 'V.E.R.I.F.Y.' AS
    agent ...`). News & Media has 22 agents and dispatch selects by CAPABILITY,
    with K.I.N. welfare-gating routing around a busy one by design — so measured
    over 7 days V.E.R.I.F.Y. performed only 19% of fact_checks while P.R.O.O.F.,
    E.C.H.O., V.E.T., A.X.I.O.M., C.O.N.D.U.I.T., T.A.L.O.N. and R.A.N.G.E.R. did
    the rest, and every one was published here as "V.E.R.I.F.Y."

    Same failure as the weather page advertising a hardcoded source list while
    holding no data: a template that hardcodes what should be looped goes stale
    silently, and K.I.N. can hire all it likes without the page ever noticing.

    NULL agent_name is NOT counted as anyone. It means the performer was not
    recorded (migration 059 is forward-only — the dispatcher's choice was
    discarded at write time and cannot be recovered). It is reported separately
    as `unattributed` so the total still reconciles, rather than being quietly
    folded into whichever name would make the numbers look complete.
    """
    with _db().begin() as c:
        c.execute(text("SET LOCAL jit = off"))
        rows = c.execute(text(f"""
            SELECT agent, SUM(n)::bigint AS events,
                   SUM(CASE WHEN task = 'fact-check' THEN n ELSE 0 END)::bigint AS fact_checks,
                   SUM(CASE WHEN task = 'bias'       THEN n ELSE 0 END)::bigint AS bias_scores
              FROM (
                SELECT COALESCE(agent_name, '') AS agent, 'fact-check' AS task, COUNT(*) AS n
                  FROM {S}.fact_checks
                 WHERE checked_at > NOW() - INTERVAL '24 hours'
                 GROUP BY 1
                UNION ALL
                SELECT COALESCE(agent_name, ''), 'bias', COUNT(*)
                  FROM {S}.bias_scores
                 WHERE computed_at > NOW() - INTERVAL '24 hours'
                 GROUP BY 1
              ) t
             GROUP BY agent
             ORDER BY events DESC
        """)).mappings().all()
    agents = [dict(r) for r in rows if r["agent"]]
    unattributed = sum(int(r["events"]) for r in rows if not r["agent"])
    return {
        "agents": agents,
        "unattributed": unattributed,
        "attributed": sum(int(a["events"]) for a in agents),
    }


def _activity_bundle(S):
    """Everything on /activity except the paginated event feed — one shared
    snapshot cached _ACTIVITY_CACHE_TTL seconds."""
    ent = _ACTIVITY_CACHE.get("bundle")
    if ent and ent[0] > time.time():
        return ent[1]
    # Newsroom roster rides the same cached snapshot. Both halves are indexed
    # range scans (idx_fact_checks_agent_checked / idx_bias_scores_agent_computed
    # from migration 059), so it adds nothing meaningful to a bundle that is
    # already ~40 whole-table COUNTs.
    try:
        _newsroom = _newsroom_agents(S)
    except Exception as _exc:  # a roster failure must not take the page down
        _newsroom = {"agents": [], "unattributed": 0, "attributed": 0, "error": str(_exc)[:120]}
    with _db().begin() as c:
        c.execute(text("SET LOCAL jit = off"))
        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
        stats = c.execute(text(f"""
            SELECT
              -- Transparency page: the one place a wrong count is worst.
              (SELECT COUNT(*) FROM {S}.articles
                WHERE suppressed_reason IS NULL) AS total_articles,
              -- ⚠️ Every article-derived count on this page MUST exclude suppressed
              -- articles. These are the numbers the transparency page publishes; an
              -- unfiltered COUNT credits the site for work on articles it does not
              -- serve. Before migration 069 that was 27,317 fact-checks on hidden
              -- duplicates; the 74 publisher_suffix_title rows remain the reason the
              -- filter (not the delete) is the actual fix.
              (SELECT COUNT(*) FROM {S}.bias_scores b
                 JOIN {S}.articles a ON a.id = b.article_id
                WHERE a.suppressed_reason IS NULL) AS bias_scored,
              (SELECT COUNT(*) FROM {S}.fact_checks f
                 JOIN {S}.articles a ON a.id = f.article_id
                WHERE a.suppressed_reason IS NULL) AS fact_checked,
              (SELECT COUNT(DISTINCT f.article_id) FROM {S}.fact_checks f
                 JOIN {S}.articles a ON a.id = f.article_id
                WHERE a.suppressed_reason IS NULL) AS fact_checked_articles,
              (SELECT COUNT(*) FROM {S}.articles WHERE province_code IS NOT NULL) AS geo_mapped,
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested') AS fact_ingested,
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested' AND created_at > NOW() - INTERVAL '24 hours') AS articles_24h,
              (SELECT COUNT(*) FROM {S}.bias_scores WHERE computed_at > NOW() - INTERVAL '24 hours') AS bias_24h,
              (SELECT COUNT(DISTINCT article_id) FROM {S}.fact_checks WHERE checked_at > NOW() - INTERVAL '24 hours') AS verify_24h,
              (SELECT COUNT(*) FROM {S}.summaries WHERE created_at > NOW() - INTERVAL '24 hours') AS draft_24h,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE created_at > NOW() - INTERVAL '24 hours') AS ink_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed_at > NOW() - INTERVAL '24 hours'
                 AND suppressed_reason IS NULL) AS llm_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed_at > NOW() - INTERVAL '1 hour'
                 AND suppressed_reason IS NULL) AS llm_analyzed_1h,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count = 1) AS cluster_singletons,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count BETWEEN 2 AND 3) AS cluster_small,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count BETWEEN 4 AND 9) AS cluster_medium,
              (SELECT COUNT(*) FROM {S}.story_clusters WHERE article_count >= 10) AS cluster_large,
              (SELECT COUNT(*) FROM {S}.summaries) AS draft_summarized,
              (SELECT COUNT(*) FROM {S}.story_clusters) AS ink_clustered,
              (SELECT COUNT(*) FROM {S}.articles WHERE cluster_id IS NOT NULL) AS ink_articles_clustered,
              (SELECT COUNT(*) FROM {S}.articles WHERE ai_analyzed=true
                 AND suppressed_reason IS NULL) AS llm_analyzed,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier='pending'
                 AND suppressed_reason IS NULL) AS tier_pending,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier='quick_v1'
                 AND suppressed_reason IS NULL) AS tier_quick_v1,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier='quick_v1+full'
                 AND suppressed_reason IS NULL) AS tier_quick_v1_full,
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier IN ('quick_v1_failed', 'quick_v1_failed+full', 'quick_v1+failed')) AS tier_quick_v1_failed,
              (SELECT COUNT(*) FROM {S}.articles WHERE tier2_pending=true) AS tier2_pending_count,
              (SELECT COUNT(DISTINCT article_id) FROM {S}.fact_checks) AS verify_total,
              (SELECT COUNT(*) FROM {S}.articles WHERE province_code IS NOT NULL OR country_code IS NOT NULL) AS geo_mapped,
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
              (SELECT COUNT(*) FROM {S}.articles WHERE tier2_failures > 0) AS tier2_failed,
              -- 24h trend: yesterday window (24-48h ago) for delta calculation
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested' AND created_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours') AS articles_yesterday,
              (SELECT COUNT(*) FROM {S}.bias_scores WHERE computed_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours') AS bias_yesterday,
              (SELECT COUNT(DISTINCT article_id) FROM {S}.fact_checks WHERE checked_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours') AS verify_yesterday
        """)).mappings().first()

        # --- Extra analytics queries (activity page enrichments) ---
        beat_breakdown, top_stories, throughput_sparkline, bias_spectrum = [], [], [], []
        llm_rate, geo_rate = 0.0, 0.0
        c.execute(text("SAVEPOINT extra_analytics"))
        try:
            beat_rows = c.execute(text(f"""
                SELECT COALESCE(beat,'unknown') AS beat, COUNT(*) AS cnt
                FROM {S}.articles WHERE beat IS NOT NULL AND beat != ''
                GROUP BY beat ORDER BY cnt DESC LIMIT 12
            """)).mappings().all()
            beat_breakdown = [{"beat": r["beat"], "cnt": int(r["cnt"])} for r in beat_rows]

            top_story_rows = c.execute(text(f"""
                SELECT sc.representative_title AS headline, sc.id AS cluster_id,
                       COUNT(a.id) AS article_count, COUNT(DISTINCT s.id) AS outlet_count
                FROM {S}.story_clusters sc
                JOIN {S}.articles a ON a.cluster_id = sc.id
                JOIN {S}.sources s ON s.id = a.source_id
                WHERE a.published_at > NOW() - INTERVAL '24 hours'
                  AND sc.representative_title IS NOT NULL
                GROUP BY sc.id, sc.representative_title
                ORDER BY article_count DESC, outlet_count DESC LIMIT 5
            """)).mappings().all()
            top_stories = [{"headline": r["headline"][:80], "articles": int(r["article_count"]),
                            "outlets": int(r["outlet_count"]), "id": r["cluster_id"]} for r in top_story_rows]

            sparkline_rows = c.execute(text(f"""
                SELECT date_trunc('hour', completed_at) -
                       MOD(EXTRACT(HOUR FROM completed_at)::int, 2) * INTERVAL '1 hour' AS bucket,
                       COUNT(*) AS cnt
                FROM {S}.llm_analyses
                WHERE completed_at > NOW() - INTERVAL '24 hours'
                GROUP BY bucket ORDER BY bucket
            """)).mappings().all()
            throughput_sparkline = [{"t": r["bucket"].isoformat(), "cnt": int(r["cnt"])} for r in sparkline_rows]

            bias_spectrum_rows = c.execute(text(f"""
                SELECT COALESCE(bias_lean, 'unknown') AS lean, COUNT(*) AS cnt
                FROM {S}.sources
                GROUP BY lean ORDER BY cnt DESC
            """)).mappings().all()
            bias_spectrum = [{"lean": r["lean"], "cnt": int(r["cnt"])} for r in bias_spectrum_rows]

            rate_rows = c.execute(text(f"""
                SELECT
                    (SELECT COUNT(*) FROM {S}.llm_analyses WHERE completed_at > NOW() - INTERVAL '6 hours') / 6.0 AS llm_hr,
                    (SELECT COUNT(*) FROM {S}.articles WHERE geo_confidence > 0 AND published_at > NOW() - INTERVAL '6 hours') / 6.0 AS geo_hr
            """)).mappings().first()
            llm_rate = float(rate_rows["llm_hr"] or 0)
            geo_rate = float(rate_rows["geo_hr"] or 0)
        except Exception as _e:
            import logging; logging.getLogger(__name__).warning("Extra analytics queries failed: %s", _e)
            try: c.execute(text("ROLLBACK TO SAVEPOINT extra_analytics"))
            except Exception: pass
        else:
            try: c.execute(text("RELEASE SAVEPOINT extra_analytics"))
            except Exception: pass

        # Compute 24h trend deltas (today vs yesterday, >10% = show indicator)
        def _trend_pct(today, yesterday):
            y = yesterday or 0
            t = today or 0
            if y == 0:
                return None
            return round((t - y) / y * 100)

        trends = {
            "ingested": _trend_pct(stats["articles_24h"], stats["articles_yesterday"]),
            "bias": _trend_pct(stats["bias_24h"], stats["bias_yesterday"]),
            "verify": _trend_pct(stats["verify_24h"], stats["verify_yesterday"]),
        }

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
                s.name,
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
        src_total = r["articles_total"] or 0
        src_recent = r["articles_7d"] or 0
        src_with_body = r["articles_with_body"] or 0
        if src_total == 0:
            status = "dead"
        elif src_recent == 0:
            status = "stalled"
        else:
            status = "active"
        source_health.append({
            "slug": r["slug"],
            "name": r["name"] or r["slug"],
            "bias_lean": r["bias_lean"] or "?",
            "owner": owner,
            "ownership_type": ownership_type,
            "articles_total": src_total,
            "articles_7d": src_recent,
            "body_pct": int(src_with_body / src_total * 100) if src_total else 0,
            "last_article": r["last_article"].isoformat() if r["last_article"] else "—",
            "status": status,
        })

    B = {
        "source_count": source_count,
        "stats": dict(stats),
        "trends": trends,
        "beat_breakdown": beat_breakdown,
        "top_stories": top_stories,
        "throughput_sparkline": throughput_sparkline,
        "bias_spectrum": bias_spectrum,
        "llm_rate": llm_rate,
        "geo_rate": geo_rate,
        "sparklines": sparklines,
        "source_health": source_health,
        "newsroom": _newsroom,
    }
    _ACTIVITY_CACHE["bundle"] = (time.time() + _ACTIVITY_CACHE_TTL, B)
    return B


@bp.get("/activity")
def activity():
    from flask import request as _req
    S = _schema()
    PAGE_SIZE = 100
    # Page cap bounds the per-branch feed LIMIT below (100 pages = 10k events
    # per branch worst case — far beyond any human scroll depth).
    try:
        page = max(1, min(100, int(_req.args.get("page", 1))))
    except (TypeError, ValueError):
        page = 1
    agent_filter = _req.args.get("agent", "all")
    offset = (page - 1) * PAGE_SIZE

    B = _activity_bundle(S)
    stats = B["stats"]

    agent_queries = _activity_agent_queries(S)
    if agent_filter != "all" and agent_filter in agent_queries:
        selected = {agent_filter: agent_queries[agent_filter]}
    else:
        selected = agent_queries

    # Feed total is a whole-union COUNT (~800k rows) — cache per filter.
    _tk = ("total", agent_filter if agent_filter in agent_queries else "all")
    _te = _ACTIVITY_CACHE.get(_tk)

    with _db().begin() as c:
        c.execute(text("SET LOCAL jit = off"))
        if _te and _te[0] > time.time():
            total = _te[1]
        else:
            union_all = " UNION ALL ".join(f"({q})" for q in selected.values())
            total = c.execute(text(f"SELECT COUNT(*) FROM ({union_all}) x")).scalar() or 0
            _ACTIVITY_CACHE[_tk] = (time.time() + _ACTIVITY_CACHE_TTL, total)

        # Each branch is pre-sorted + capped so the union never materializes
        # and sorts whole tables per request (was ~800k rows every view). Honest
        # note: the planner satisfies these caps with parallel top-N sorts
        # (~750ms total), NOT the migration-051 ts indexes — those serve the
        # 24h stats windows. Cost grows linearly with table size; revisit if
        # the feed crosses ~2s again.
        cap = offset + PAGE_SIZE
        union_sql = " UNION ALL ".join(
            f"(SELECT * FROM ({q}) b{i} ORDER BY ts DESC NULLS LAST LIMIT {cap})"
            for i, q in enumerate(selected.values())
        )
        rows = c.execute(text(f"""
            SELECT * FROM ({union_sql}) x
            ORDER BY ts DESC NULLS LAST
            LIMIT {PAGE_SIZE} OFFSET {offset}
        """)).fetchall()

    # ⚠️ POSITIONAL ACCESS — the column ORDER in _activity_agent_queries is a
    # contract with this mapping. Adding `performed_by` as the 2nd column shifted
    # every index and produced `TypeError: 'int' object is not subscriptable`
    # (article_id landed where title was expected). Same family as the
    # RealDictCursor int-indexing trap in security-network.md. If you add a
    # column to those UNION branches, update this line in the same commit.
    events = [
        {"agent": r[0], "performed_by": r[1], "article_id": r[2],
         "title": (r[3] or "")[:120],
         "result": r[4] or "", "source": r[6] or "",
         "ts": r[5].isoformat() if r[5] else None}
        for r in rows
    ]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    llm_rate = B["llm_rate"]
    geo_rate = B["geo_rate"]
    llm_pending_count = int(stats.get("llm_pending") or 0)
    geo_pending_count = int(stats.get("geo_pending") or 0)
    llm_days_left = round(llm_pending_count / (llm_rate * 24), 1) if llm_rate > 0 else None
    geo_days_left = round(geo_pending_count / (geo_rate * 24), 1) if geo_rate > 0 else None
    llm_hours_left = round(llm_pending_count / llm_rate, 1) if llm_rate and llm_rate > 0 else None

    creed_scan = _fetch_creed_scan()

    return render_template("activity.html", events=events,
                           source_count=B["source_count"],
                           total=total, page=page, total_pages=total_pages,
                           page_size=PAGE_SIZE, agent_filter=agent_filter,
                           stats=stats, source_health=B["source_health"],
                           # ⚠️ MUST be passed explicitly — this route enumerates
                           # its context keys, so a bundle key that is not listed
                           # here renders the panel's EMPTY state, which reads as
                           # "no agents did any work" rather than "not wired".
                           newsroom=B.get("newsroom") or {},
                           sparklines=B["sparklines"],
                           agent_stats=_fetch_agent_stats(),
                           trends=B["trends"],
                           beat_breakdown=B["beat_breakdown"],
                           top_stories=B["top_stories"],
                           throughput_sparkline=B["throughput_sparkline"],
                           bias_spectrum=B["bias_spectrum"],
                           llm_days_left=llm_days_left,
                           geo_days_left=geo_days_left,
                           llm_rate=round(llm_rate, 1),
                           llm_hours_left=llm_hours_left,
                           llm_pending_count=llm_pending_count,
                           creed_scan=creed_scan,
                           is_subscriber=is_subscriber())


# ── /activity live counters (#6219) ────────────────────────────────────────
# The page's numbers only moved on a full refresh. This is the cheap half of
# /activity, polled by the client so the counters tick up in place.
#
# ⚠️ IT MUST NOT TOUCH _activity_bundle. That bundle is ~40 whole-table COUNTs
# measured at 20-36s, cached 5 min per worker; polling it would re-trigger that
# on every cache miss, from a PUBLIC url, across N viewers. That is precisely
# the shape that wedged all four workers and served 502 for 30 minutes
# (KB #299315). Only rolling-window counters live here, and every one of them
# was verified to be an INDEX-ONLY SCAN before shipping:
#   idx_audit_trail_event_created · idx_bias_scores_computed
#   idx_fact_checks_checked · idx_summaries_created
#   idx_story_clusters_created · idx_articles_ai_analyzed_at
# All-time totals stay OFF this path — they are the expensive ones and they
# move slowly enough that the 5-min bundle is the right cadence for them.
#
# ⚠️ THE CACHE IS THE REAL LIMITER. With a 10s TTL, N pollers cost at most one
# query per 10s per worker no matter how large N gets — it bounds the EXPENSIVE
# OPERATION rather than the caller, which is the lesson from that outage (a
# guard keyed on who is asking is opt-in; a guard on what it costs is not).
# The aggregate ceiling below is a second layer, not the primary one.
_ACTIVITY_LIVE_CACHE: dict = {}
_ACTIVITY_LIVE_TTL = int(os.environ.get("WTF_ACTIVITY_LIVE_TTL", "10"))
_ACTIVITY_LIVE_BUCKET: list = []
_ACTIVITY_LIVE_LIMIT = int(os.environ.get("WTF_ACTIVITY_LIVE_LIMIT", "120"))  # per worker per min


def _activity_live_rate_ok() -> bool:
    """UA-blind aggregate ceiling. Fail-OPEN: a bug in the limiter must never
    take the endpoint down, and a stalled counter is a cosmetic failure."""
    try:
        now = time.time()
        _ACTIVITY_LIVE_BUCKET[:] = [t for t in _ACTIVITY_LIVE_BUCKET if t > now - 60]
        if len(_ACTIVITY_LIVE_BUCKET) >= _ACTIVITY_LIVE_LIMIT:
            return False
        _ACTIVITY_LIVE_BUCKET.append(now)
        return True
    except Exception:
        return True


def _activity_live_counters(S):
    """The six rolling counters, cached _ACTIVITY_LIVE_TTL seconds."""
    ent = _ACTIVITY_LIVE_CACHE.get("live")
    if ent and ent[0] > time.time():
        return ent[1]
    with _db().begin() as c:
        c.execute(text("SET LOCAL jit = off"))
        row = c.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM {S}.audit_trail
                 WHERE event_type='ingested'
                   AND created_at > NOW() - INTERVAL '24 hours')            AS articles_24h,
              (SELECT COUNT(*) FROM {S}.bias_scores
                 WHERE computed_at > NOW() - INTERVAL '24 hours')           AS bias_24h,
              (SELECT COUNT(DISTINCT article_id) FROM {S}.fact_checks
                 WHERE checked_at > NOW() - INTERVAL '24 hours')            AS verify_24h,
              (SELECT COUNT(*) FROM {S}.summaries
                 WHERE created_at > NOW() - INTERVAL '24 hours')            AS draft_24h,
              (SELECT COUNT(*) FROM {S}.story_clusters
                 WHERE created_at > NOW() - INTERVAL '24 hours')            AS ink_24h,
              (SELECT COUNT(*) FROM {S}.articles
                 WHERE ai_analyzed_at > NOW() - INTERVAL '24 hours')        AS llm_24h
        """)).mappings().first()
    out = {k: int(v or 0) for k, v in dict(row or {}).items()}
    _ACTIVITY_LIVE_CACHE["live"] = (time.time() + _ACTIVITY_LIVE_TTL, out)
    return out


@bp.get("/api/activity/live")
def activity_live():
    """Rolling 24h counters for the /activity ticker. Cheap, cached, public.

    Returns 200 with `stale: true` rather than an error when the counters
    cannot be read — a ticker that stops updating should degrade quietly, not
    put an error banner on a page that is otherwise fine.
    """
    if not _activity_live_rate_ok():
        return jsonify({"ok": False, "stale": True, "reason": "rate"}), 429
    try:
        return jsonify({"ok": True, "stale": False, "counters": _activity_live_counters(_schema())})
    except Exception as exc:
        from flask import current_app

        current_app.logger.warning("activity_live failed: %s", exc)
        return jsonify({"ok": False, "stale": True, "reason": "unavailable"}), 200


@bp.get("/team")
def team():
    S = _schema()
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
    portrait_lookup = _get_portrait_lookup()
    welfare_lookup = _get_welfare_lookup()
    agents = []
    for agent in TEAM_AGENTS:
        a = dict(agent)
        live_url = portrait_lookup.get(agent["name"])
        if live_url:
            a["portrait_url"] = live_url
        a["welfare"] = welfare_lookup.get(agent["name"])  # None if unavailable
        agents.append(a)
    return render_template("team.html", agents=agents, source_count=source_count)


@bp.get("/cost")
def cost_of_parliament():
    """"What Parliament Costs Canadians" — national cost-to-taxpayers page.

    Renders the shell only; the figures are fetched client-side from the public,
    cached /api/cost/summary endpoint (the single source of truth in
    ingest.parliament.cost). Every figure is labelled approximate and sourced in
    the template. Public (no paywall) — this is public money.
    """
    S = _schema()
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
    return render_template("cost.html", source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/")
def index():
    S = _schema()
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
            -- Guard: a source occasionally emits a wildly-future published_at (a date
            -- parse error) that would pin that one article atop the feed indefinitely.
            -- Exclude anything more than a small grace window ahead of now.
            -- (WTF front-page freeze, 2026-07-14)
            WHERE a.suppressed_reason IS NULL
                  AND a.published_at <= NOW() + INTERVAL '2 hours'
            ORDER BY a.published_at DESC LIMIT 50
        """)).mappings().all()
        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
    return render_template("index.html", articles=rows,
                           source_count=source_count, is_subscriber=is_subscriber())


# ───────────────────────────────────────────────────────────────────────────
# Server-side proxy routes — browser JS must never call wtf-tech directly
# (mixed content: page is HTTPS, wtf-tech is an internal Docker hostname)
# ───────────────────────────────────────────────────────────────────────────
def _proxy_tech(path: str, method: str = "GET", body: bytes = None, timeout: int = 30) -> Response:
    # Default is the CONTAINER name, never the public hostname (#5794). A public
    # default is a latent mesh-mandate violation: if the env var is ever dropped or
    # missing in a new environment, every consumer->tech call silently traverses the
    # internet — capped at 60s by the CDN, bypassing the queue, invisible to
    # task_execution_log — and fails as mystery latency rather than a clear error.
    # Production already sets http://wtf-tech:8104; this makes that the fallback too.
    url = os.environ.get("WTF_TECH_URL", "http://wtf-tech:8104") + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Response(resp.read(), content_type="application/json")
    except Exception as exc:
        return Response(json.dumps({"error": str(exc)}), status=502, content_type="application/json")


# ---------------------------------------------------------------------------
# C.R.E.E.D. badge proxy — server-side only; CREED_API_URL never exposed to JS
# (KB #267314: internal URLs must never reach browser JavaScript)
# ---------------------------------------------------------------------------
_CREED_FALLBACK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20">'
    b'<rect width="120" height="20" rx="3" fill="#1a1a2e"/>'
    b'<text x="6" y="14" font-family="monospace" font-size="10" fill="#a0a0c0">'
    b'C.R.E.E.D.</text></svg>'
)


@bp.get("/api/creed-badge")
def creed_badge():
    """Proxy WTF's OWN C.R.E.E.D. tenant badge SVG server-side so the internal
    CREED_API_URL is never exposed to browser JavaScript. (Repointed from the
    Institute overall badge to the what-the-fact org badge — #4898, ADR-011.)"""
    creed_url = os.environ.get("CREED_API_URL", "https://creed.kytranempowerment.com")
    try:
        req = urllib.request.Request(
            creed_url + "/api/v1/badge/what-the-fact/overall",
            headers={"Accept": "image/svg+xml"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            svg_data = resp.read()
        return Response(svg_data, content_type="image/svg+xml")
    except Exception:
        return Response(_CREED_FALLBACK_SVG, content_type="image/svg+xml")


@bp.get("/governance")
def governance_page():
    """WTF's own AI-newsroom governance page — the live what-the-fact C.R.E.E.D.
    tenant score with per-pillar breakdown (#4898, ADR-011). Public by design,
    like the /activity banner and the badge (#3358)."""
    scan = _fetch_creed_scan()
    S = _schema()
    source_count = 0
    try:
        with _db().begin() as c:
            source_count = c.execute(
                text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
            ).scalar() or 0
    except Exception:
        pass
    return render_template(
        "governance.html", scan=scan, source_count=source_count, is_subscriber=is_subscriber()
    )


# Canonical beats — single source of truth is VALID_BEATS (defined above). The old
# private copy here DRIFTED (transit/sci-tech/arts/foreign are not the stored beat
# names), so those categories silently returned 0 rows. Legacy aliases are mapped to
# canonical instead of rejected. (WTF audit 2026-07-14, #4895)
_BEAT_ALIASES = {"transit": "transportation", "sci-tech": "science-tech",
                 "arts": "arts-culture", "foreign": "foreign-policy"}
_VALID_BEATS = set(VALID_BEATS)


def _norm_beat(beat: str) -> str:
    """Map legacy beat aliases to canonical names; unknown values → 'all'."""
    beat = _BEAT_ALIASES.get(beat, beat)
    return beat if beat in _VALID_BEATS else "all"


# The 13 real province/territory codes — the geocoder occasionally misfires
# (KY/US/TX/'11' seen live); aggregates must not leak junk codes. (#4895)
_PROVINCE_CODES = ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT")
_PROVINCE_SQL_LIST = "('" + "','".join(_PROVINCE_CODES) + "')"
_VALID_SCOPES = {"all","national","provincial","international"}


@bp.get("/api/proxy/map-data")
def proxy_map_data():
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    beat = request.args.get("beat", "all")
    scope = request.args.get("scope", "all")
    beat = _norm_beat(beat)
    if scope not in _VALID_SCOPES:
        scope = "all"
    return _proxy_tech("/api/v1/map-data?" + urllib.parse.urlencode({"beat": beat, "scope": scope}))


@bp.get("/api/proxy/agent-activity")
def proxy_agent_activity():
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    return _proxy_tech("/api/v1/agent-activity")


@bp.get("/api/proxy/articles/geo")
def proxy_articles_geo():
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    beat = request.args.get("beat", "all")
    beat = _norm_beat(beat)
    province = (request.args.get("province") or "").strip().upper()[:2]
    scope = (request.args.get("scope") or "canada").strip()[:10]
    S = _schema()
    where = ["a.lat IS NOT NULL", "a.lng IS NOT NULL"]
    params: dict = {}
    if beat and beat != "all":
        where.append("a.beat = :beat"); params["beat"] = beat
    if scope == "canada":
        if province:
            where.append("a.province_code = :province"); params["province"] = province

    with _db().begin() as c:
        if scope == "world":
            # Country aggregate (accurate totals, no LIMIT)
            agg_where = ["a.lat IS NOT NULL", "a.country_code IS NOT NULL"]
            if beat and beat != "all":
                agg_where.append("a.beat = :beat")
            agg_rows = c.execute(text(f"""
                SELECT a.country_code, COUNT(*) AS cnt,
                       AVG(a.lat) AS lat, AVG(a.lng) AS lng,
                       MODE() WITHIN GROUP (ORDER BY b.band) AS dominant_band
                FROM {S}.articles a
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                WHERE {' AND '.join(agg_where)}
                GROUP BY a.country_code
            """), params).mappings().all()
            province_counts = {r["country_code"]: {
                "count": r["cnt"],
                "lat": float(r["lat"]) if r["lat"] else None,
                "lng": float(r["lng"]) if r["lng"] else None,
                "band": r["dominant_band"],
            } for r in agg_rows}
        else:
            # Province aggregate for Canada mode
            prov_where = [f"a.province_code IN {_PROVINCE_SQL_LIST}", "a.lat IS NOT NULL"]
            if beat and beat != "all":
                prov_where.append("a.beat = :beat")
            if province:
                prov_where.append("a.province_code = :province")
            # SQL-injection safety: every f-string interpolation here is a static,
            # server-controlled literal — {S} is the env-configured schema name,
            # prov_where contains only the hardcoded _PROVINCE_SQL_LIST plus
            # ":beat"/":province" PLACEHOLDERS (their user-supplied values are bound
            # via `params`, never interpolated).
            prov_rows = c.execute(text(f"""
                SELECT a.province_code, COUNT(*) AS cnt,
                       MODE() WITHIN GROUP (ORDER BY b.band) AS dominant_band,
                       AVG(b.score) AS avg_score
                FROM {S}.articles a
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                WHERE {' AND '.join(prov_where)}
                GROUP BY a.province_code
            """), params).mappings().all()
            # avg_score powers the province LEAN colouring (ADR-011): a continuous
            # average is required because MODE(band) is 'center' for every province
            # (92.9% of bias rows) — categorical colouring would be monochrome.
            province_counts = {r["province_code"]: {
                "count": r["cnt"],
                "band": r["dominant_band"],
                "avg_score": float(r["avg_score"]) if r["avg_score"] is not None else None,
            } for r in prov_rows}

        # Individual pins (limited for performance)
        pin_rows = c.execute(text(f"""
            SELECT a.id, a.title, a.lat, a.lng, a.province_code, a.country_code,
                   a.ai_analyzed, s.name AS source_name, b.band AS bias_band
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.suppressed_reason IS NULL AND {' AND '.join(where)}
            ORDER BY a.published_at DESC NULLS LAST
            LIMIT 500
        """), params).mappings().all()
    import json as _json
    from flask import Response as _Resp
    return _Resp(
        _json.dumps({"ok": True,
            "province_counts": province_counts,
            "articles": [
                {"id": r["id"], "title": r["title"],
                 "lat": float(r["lat"]), "lng": float(r["lng"]),
                 "province_code": r["province_code"],
                 "source_name": r["source_name"],
                 "bias_band": r["bias_band"],
                 "ai_analyzed": bool(r["ai_analyzed"])}
                for r in pin_rows
            ]}),
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@bp.post("/api/proxy/articles/<int:article_id>/analyze")
def proxy_article_analyze(article_id: int):
    # Returns instantly (queued=true) — background thread handles the hub call
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    return _proxy_tech(f"/api/v1/articles/{article_id}/analyze", method="POST", body=b"{}", timeout=10)


@bp.get("/api/proxy/articles/<int:article_id>/analyze/status")
def proxy_article_analyze_status(article_id: int):
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    return _proxy_tech(f"/api/v1/articles/{article_id}/analyze/status")


@bp.post("/api/proxy/articles/<int:article_id>/flag")
def proxy_article_flag(article_id: int):
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
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
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT a.id, a.title, a.body, a.url, a.published_at,
                   a.ai_analyzed, a.ai_analyzed_at, a.province_code, a.cluster_id,
                   -- city/geo_scope feed the "Local coverage" section below.
                   -- ⚠️ city is present on only ~10% of articles while
                   -- province_code covers ~64%, so the section keys on city
                   -- ONLY when it exists and falls back to province.
                   a.city, a.geo_scope,
                   -- 'wire' = press release / newswire copy. The political bias
                   -- panel is SUPPRESSED for these: a corporate announcement has
                   -- no partisan lean, so a "CENTER" reading there is not a
                   -- measurement, and #065 already removed them from the outlet
                   -- average for the same reason.
                   a.content_type,
                   -- drive the 301/410 immediately below
                   a.suppressed_reason, a.canonical_article_id,
                   a.analysis_tier, a.tier2_pending,
                   a.bias_v2_score, a.bias_v2_label,
                   a.bias_ensemble_score, a.bias_ensemble_band,
                   s.name AS source_name, s.slug AS source_slug,
                   s.owner_name, s.owner_type, s.bias_lean AS source_bias_lean,
                   s.country AS source_country,
                   b.band AS bias_band, b.score AS bias_score,
                   b.rationale AS bias_rationale, b.trigger_phrases,
                   b.confidence AS bias_confidence, b.analyzed_by AS bias_analyzed_by,
                   -- FALSE = the detector matched no trigger term. score/band are
                   -- schema fillers and assert NOTHING; the template must not draw
                   -- a needle from them. See migration 063.
                   b.signal_detected AS bias_signal_detected,
                   obs.avg_score AS outlet_avg_score, obs.band AS outlet_rolling_band,
                   -- ⚠️ TWO DIFFERENT POPULATIONS — keep them labelled apart.
                   -- outlet_sample_count/window_days are what the rolling average
                   -- was actually computed from (30-day window, signal-bearing
                   -- rows only — ingest/outlet_bias.py). outlet_article_count is
                   -- every article ever ingested from this outlet. Rendering the
                   -- lifetime figure under the average claimed 5,737 articles of
                   -- evidence for a number built from 919 (Global News, measured
                   -- 2026-08-31) — a 6x overstatement of how well-evidenced the
                   -- reading is.
                   obs.article_count AS outlet_sample_count,
                   obs.window_days   AS outlet_window_days,
                   (SELECT COUNT(*) FROM {S}.articles a2
                    WHERE a2.source_id = a.source_id) AS outlet_article_count,
                   fc.overall_verdict, fc.claims AS fact_check_claims,
                   fc.analyzed_by AS fc_analyzed_by
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = a.source_id
            -- ⚠️ LATERAL + ORDER BY id DESC LIMIT 1, never a bare LEFT JOIN.
            --
            -- fact_checks has NO unique constraint on article_id and eight
            -- INSERT sites across six files, none of which upsert — so it holds
            -- 431,295 rows for 121,123 articles (3.6x). A plain LEFT JOIN
            -- fanned out across those duplicates and `.first()` then took an
            -- ARBITRARY one, with no ordering to make the choice stable.
            --
            -- For the 6,906 articles whose duplicates DISAGREE, that means the
            -- published verdict was non-deterministic. Article 200618 carries
            -- 2x 'unverifiable' (llm_v1, 2026-06-08) and 4x 'verified'
            -- (dhq_v1, 2026-06-14): the page could show either, and the stale
            -- one is just as likely. Newest-wins is the only defensible rule.
            --
            -- The LIST view (see the #5719 rewrite above) already did this
            -- correctly; the article page did not. Same query, same table,
            -- two different answers.
            LEFT JOIN LATERAL (
                SELECT fc2.overall_verdict, fc2.claims, fc2.analyzed_by
                  FROM {S}.fact_checks fc2
                 WHERE fc2.article_id = a.id
                   AND fc2.checker NOT LIKE 'GoogleFCT%%'
                 ORDER BY fc2.id DESC
                 LIMIT 1
            ) fc ON TRUE
            WHERE a.id = :id
        """), {"id": article_id}).mappings().first()
    if not row:
        abort(404)

    # A suppressed article must not RENDER. #3036 hid ~8,300 re-fetched duplicates
    # from every listing, feed and sitemap — but this route kept serving each one at
    # 200, so the hidden article was still a live, indexable page reachable by direct
    # link. Removing something from the navigation is not the same as removing it
    # from the web.
    #
    # 301 (not 404) where we know the survivor: these are real fetches of a real
    # story that already have inbound links and search-engine history. A 301 hands
    # that to the canonical copy and tells crawlers to consolidate; a 404 throws it
    # away and leaves the reader at a dead end.
    #
    # 410 (not 404) where we don't: `publisher_suffix_title` articles are junk with
    # no survivor to point at. 410 GONE is the honest answer — it says "this will not
    # come back", which 404 ("not found, maybe later") does not, and crawlers drop a
    # 410 faster. Migration 070 supplies the pointer that makes this distinction
    # possible at all; before it, the table recorded THAT a row was a duplicate but
    # never OF WHAT.
    if row["suppressed_reason"]:
        canonical_id = row["canonical_article_id"]
        if canonical_id:
            return redirect(url_for(".article", article_id=canonical_id), code=301)
        abort(410)

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

    # Outlet sparkline — daily avg bias score over the outlet's last 7 days of COVERAGE.
    #
    # ⚠️ Buckets by a.published_at, NOT bs.computed_at. computed_at is when the
    # ANALYSIS ran, so a backlog pass plots decade-old articles as today's bias:
    # measured 2026-08-31, one pilot run put 2,105 points on a single day for
    # Global News, 1,954 of them (93%) articles published more than 7 days
    # earlier. A chart captioned "7-day bias trend" must describe the outlet's
    # last 7 days of journalism, not our last 7 days of compute.
    #
    # ⚠️ signal_detected IS NOT FALSE — same exclusion the outlet rollup uses
    # (ingest/outlet_bias.py, #3012). A no-signal row carries score 0.0 / band
    # 'center' as schema-required placeholders and asserts nothing; averaging
    # them in halved the reading (-0.108 shown vs -0.226 real on that same day).
    sparkline = []
    try:
        with _db().begin() as c:
            sp_rows = c.execute(text(f"""
                SELECT a2.published_at::date AS d,
                       AVG(bs.score)::float AS avg_score,
                       MODE() WITHIN GROUP (ORDER BY bs.band) AS modal_band
                FROM {S}.bias_scores bs
                JOIN {S}.articles a2 ON a2.id = bs.article_id
                WHERE a2.source_id = (SELECT source_id FROM {S}.articles WHERE id = :aid)
                  AND a2.published_at > NOW() - INTERVAL '7 days'
                  AND bs.signal_detected IS NOT FALSE
                GROUP BY 1 ORDER BY 1
            """), {"aid": article_id}).fetchall()
        sparkline = [{"score": round(float(r[1]), 3), "band": r[2] or "center"} for r in sp_rows]
    except Exception:
        pass

    # Exchange tickers named in the body (TSXV: AVCR, NASDAQ: ..., etc).
    # Pure regex over text we already hold — no model, no extra fetch, and the
    # answer is exact rather than inferred. Present in ~1.5% of articles overall
    # but concentrated in the wire/business population, which is precisely where
    # a reader most wants the market link.
    # Renders only when non-empty (see the template) — an empty "Listed
    # securities" heading would assert a company that isn't there.
    # ⚠️ ONE definition, imported — not a second copy of the regex here.
    # Dockerfile.consumer does `COPY ingest/ /app/ingest/`, so the consumer can
    # import it directly; a duplicated pattern would drift from the classifier
    # that sets content_type and the two would disagree about the same article.
    tickers = []
    try:
        from ingest.content_kind import extract_tickers as _extract_tickers
        tickers = _extract_tickers(a.get("body"))
    except Exception:
        tickers = []

    # ------------------------------------------------------------------
    # Local coverage — other reporting from the same place.
    #
    # Keyed on CITY when the article has one, else PROVINCE. That order is
    # not cosmetic: city is populated on only ~10% of articles while
    # province_code covers ~64%, so a city-only section would be absent from
    # nine articles in ten. Measured 2026-08-31: 69.6% of the last 30 days
    # carry at least one of the two.
    #
    # ⚠️ Match on CITY ALONE, never (city, province). Toronto is recorded
    # 1,288 times with province_code='ON' and 1,146 times with province_code
    # NULL — the geo extractor fills city without province on roughly half of
    # them. Joining on the pair would silently drop half of Toronto's coverage
    # and present the remainder as the whole.
    #
    # ⚠️ geo_scope='unmappable' (30% of articles) means the extractor found no
    # place at all. Those must render NO section rather than an empty one — an
    # empty "Local coverage" heading reads as "nothing happened there", which
    # is a claim we have not made.
    local_articles, local_place = [], None
    try:
        _city = (a.get("city") or "").strip()
        _prov = (a.get("province_code") or "").strip()
        if (a.get("geo_scope") or "") != "unmappable" and (_city or _prov):
            if _city:
                _where, _param, local_place = "a2.city = :key", _city, _city
            else:
                # Display the province NAME, not the two-letter code: "Local
                # coverage · Alberta" reads as a place, "· AB" reads as a
                # database value. Reuses the aurora_map map rather than adding a
                # second copy — a divergent duplicate is how a province goes
                # missing (see _canon_prov's NF/NL note there). Falls back to
                # the raw code for anything unmapped, never to a blank heading.
                from .aurora_map import _PROV_NAMES as _PN
                _where, _param = "a2.province_code = :key", _prov
                local_place = _PN.get(_prov, _prov)
            with _db().begin() as c:
                # ⚠️ DISTINCT ON (title) — the same story is ingested more than
                # once. Measured 2026-09-01: 794 duplicate (title, source_id)
                # groups in 14 days, 948 redundant rows. Without this the panel
                # listed "Atlantic Canada's largest used book sale returns to
                # Saint John" TWICE in six slots, which reads as two separate
                # stories and wastes a third of the panel.
                #
                # Dedup on title alone, not (title, source): the same wire copy
                # runs at several outlets, and showing it once is the point.
                # The inner ORDER BY picks the newest row per title; the outer
                # one restores recency order for display.
                local_rows = c.execute(text(f"""
                    SELECT * FROM (
                        SELECT DISTINCT ON (a2.title)
                               a2.id, a2.title, a2.published_at, s2.name AS source_name
                          FROM {S}.articles a2
                          JOIN {S}.sources s2 ON s2.id = a2.source_id
                         WHERE {_where}
                           AND a2.id <> :aid
                           AND a2.published_at > NOW() - INTERVAL '14 days'
                         ORDER BY a2.title, a2.published_at DESC
                    ) d
                    ORDER BY d.published_at DESC
                    LIMIT 6
                """), {"key": _param, "aid": article_id}).mappings().all()
            local_articles = [dict(r) for r in local_rows]
    except Exception:
        local_articles, local_place = [], None

    # MP election claims — tagged MPs for this article × claim_tracker (#3013)
    mp_claims = []
    try:
        with _db().begin() as c:
            mp_claim_rows = c.execute(text(f"""
                SELECT ct.id, ct.politician_slug, ct.politician_name,
                       ct.claim_text, ct.claim_date, ct.status, ct.verdict_summary
                FROM {S}.article_mp_tags t
                JOIN parliament.mps m ON m.id = t.mp_id
                JOIN {S}.claim_tracker ct ON ct.mp_id = m.id
                WHERE t.article_id = :aid
                  AND ct.status != 'pending'
                ORDER BY ct.created_at DESC
                LIMIT 10
            """), {"aid": article_id}).mappings().all()
        mp_claims = [dict(r) for r in mp_claim_rows]
        for r in mp_claims:
            if r.get("claim_date"):
                r["claim_date"] = str(r["claim_date"])
    except Exception:
        # Missing table or no parliament data — never break article rendering
        pass

    # Cross-Watch teaser (#3331 1b) — entities tagged in this story that ALSO appear
    # in another Watch product (gov/civic/legal/market). Free hook → /entity/<id>.
    cross_watch_entities = []
    try:
        SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
        with _db().begin() as c:
            cw_rows = c.execute(text(f"""
                WITH ae AS (
                    SELECT DISTINCT em.entity_id
                    FROM {SH}.entity_mentions em
                    WHERE em.product='wtf' AND em.content_type='article'
                      AND em.content_id = :aid_text
                )
                SELECT e.id, e.entity_type, e.canonical_name,
                       array_agg(DISTINCT em2.product) AS other_products
                FROM ae
                JOIN {SH}.entities e ON e.id=ae.entity_id AND e.status='active'
                JOIN {SH}.entity_mentions em2
                     ON em2.entity_id=ae.entity_id AND em2.product <> 'wtf'
                GROUP BY e.id, e.entity_type, e.canonical_name
                ORDER BY count(*) DESC LIMIT 6
            """), {"aid_text": str(article_id)}).mappings().all()
        cross_watch_entities = [
            {"id": r["id"], "name": r["canonical_name"], "type": r["entity_type"],
             "products": list(r["other_products"] or [])}
            for r in cw_rows
        ]
    except Exception:
        # Never break article rendering on the teaser
        pass

    # ── People & organisations named in this story ───────────────────────────
    #
    # Distinct from the Cross-Watch teaser above: that one lists only entities
    # that ALSO appear in another Watch product (an accountability hook). This
    # lists who the story is ABOUT.
    #
    # ⚠️ THIS PANEL EXISTED IN DRAFT AND WAS DELIBERATELY NOT SHIPPED UNTIL THE
    # DATA WAS HONEST. Measured 2026-09-01, before the #3032 purge: 66% of
    # product='wtf' entity mentions named an entity whose name appears NOWHERE in
    # the article. An article titled "For Hamiltonians battling addiction, peer
    # support is a dose of empathy" was tagged with MP Wade Grant at confidence
    # 0.950, because the matcher tested `"grant" in text` and the body contained
    # "granted". Publishing that panel would have printed a sitting MP's name on
    # a story they have nothing to do with. After the purge: 1,064 of 1,064
    # person mentions in the last 7 days are grounded at a word boundary.
    #
    # ⚠️ JOURNALISTS ARE EXCLUDED. A byline is who WROTE the story, not who it is
    # about, and those rows come from a different producer (author_resolver) with
    # a different validity question — the name legitimately need not appear in
    # the body at all, so it cannot be grounded the same way.
    article_entities = []
    try:
        SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
        with _db().begin() as c:
            ent_rows = c.execute(text(f"""
                SELECT e.id, e.canonical_name, e.entity_type,
                       EXISTS (
                           SELECT 1 FROM {SH}.entity_mentions x
                            WHERE x.entity_id = e.id AND x.product <> 'wtf'
                       ) AS in_other_watch
                  FROM {SH}.entity_mentions em
                  JOIN {SH}.entities e
                    ON e.id = em.entity_id AND e.status = 'active'
                  JOIN {S}.articles art ON art.id = em.content_id::int
                 WHERE em.product = 'wtf'
                   AND em.content_type = 'article'
                   AND em.content_id = :aid_text
                   AND e.entity_type <> 'journalist'
                   -- ⚠️ THE NAME WE PRINT MUST APPEAR IN THE ARTICLE WE PRINT IT ON.
                   -- Not "a tag exists" — the tag can be right in the graph and
                   -- still wrong to publish. The surviving family-name tier from
                   -- #3032 matches a capitalised SURNAME at a word boundary, which
                   -- is enough for the entity graph but NOT for a public label:
                   -- live examples were MP "Roman Baber" on a house-fire story and
                   -- MP "Grant Jackson" on a US Federal Reserve story, both from a
                   -- lone surname elsewhere in the body.
                   --
                   -- Requiring the FULL canonical name verbatim drops 769 of 1,154
                   -- mentions (7d) and keeps 385 across 326 articles — every one of
                   -- which a reader can find by searching the page. A name we
                   -- cannot point at is not shown at all.
                   AND (COALESCE(art.title,'') || ' ' || COALESCE(art.body,''))
                       ~* ('\\y' || regexp_replace(
                              e.canonical_name,
                              '([.^$*+?()\\[\\]{{}}|\\\\])', '\\\\\\1', 'g') || '\\y')
                 GROUP BY e.id, e.canonical_name, e.entity_type
                 ORDER BY e.canonical_name
                 LIMIT 8
            """), {"aid_text": str(article_id)}).mappings().all()
        article_entities = [
            {"id": r["id"], "name": r["canonical_name"], "type": r["entity_type"],
             "in_other_watch": bool(r["in_other_watch"])}
            for r in ent_rows
        ]
    except Exception:
        pass

    # ── Key figures — VERBATIM sentences containing a quantified figure ──────
    #
    # Quotes, never summarises: every string is a span copied out of the body, so
    # the reader can check it against the source and we cannot invent a statistic.
    # On a site whose product is fact-checking, a fabricated number is the worst
    # defect available. Returns [] for a short/absent body, and the panel then
    # renders nothing rather than an empty box.
    key_figures = []
    try:
        from ingest.content_kind import extract_key_figures
        if not is_paywalled and not is_limited_body:
            key_figures = extract_key_figures(a.get("body"))
    except Exception:
        pass

    return render_template("article.html", a=a,
                           article_entities=article_entities,
                           key_figures=key_figures,
                           is_subscriber=subscribed,
                           is_paywalled=is_paywalled,
                           is_limited_body=is_limited_body,
                           google_fact_checks=google_fact_checks,
                           cluster_articles=cluster_articles,
                           reading_time_min=reading_time_min,
                           article_type=article_type,
                           sparkline=sparkline,
                           local_articles=local_articles,
                           local_place=local_place,
                           tickers=tickers,
                           is_wire=(a.get("content_type") == "wire"),
                           mp_claims=mp_claims,
                           cross_watch_entities=cross_watch_entities)


# ───────────────────────────────────────────────────────────────────────────
# Election Claim Tracker — public pages (#3013)
# ───────────────────────────────────────────────────────────────────────────

@bp.get("/claims")
def claims_index():
    S = _schema()
    status_filter = request.args.get("status")
    params = {}
    where = "WHERE ct.status != 'pending'"
    if status_filter and status_filter != "all":
        where += " AND ct.status = :status"
        params["status"] = status_filter
    try:
        with _db().begin() as c:
            rows = c.execute(
                text(
                    f"""
                    SELECT id, politician_slug, politician_name,
                           claim_text, claim_date, status, verdict_summary
                    FROM {S}.claim_tracker ct
                    {where}
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                ),
                params,
            ).mappings().all()
        claims = []
        for r in rows:
            d = dict(r)
            if d.get("claim_date"):
                d["claim_date"] = str(d["claim_date"])
            claims.append(d)
    except Exception:
        claims = []
    subscribed = is_subscriber()
    return render_template("claims.html", claims=claims,
                           is_subscriber=subscribed,
                           active_status=status_filter or "all")


@bp.get("/claims/<slug>")
def claims_by_politician(slug: str):
    if not slug.replace("-", "").replace("_", "").isalnum():
        abort(404)
    S = _schema()
    try:
        with _db().begin() as c:
            rows = c.execute(
                text(
                    f"""
                    SELECT id, politician_slug, politician_name,
                           claim_text, claim_date, status, verdict_summary
                    FROM {S}.claim_tracker
                    WHERE politician_slug = :slug
                    ORDER BY created_at DESC
                    """
                ),
                {"slug": slug},
            ).mappings().all()
        claims = []
        for r in rows:
            d = dict(r)
            if d.get("claim_date"):
                d["claim_date"] = str(d["claim_date"])
            claims.append(d)
    except Exception:
        claims = []
    if not claims:
        # No tracked claims for this slug — any junk URL previously rendered
        # a fake politician page with the raw slug as the name (#5728).
        abort(404)
    subscribed = is_subscriber()
    politician_name = claims[0]["politician_name"]
    return render_template("claims.html", claims=claims,
                           is_subscriber=subscribed,
                           active_status="all",
                           politician_slug=slug,
                           politician_name=politician_name)


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
            WHERE a.suppressed_reason IS NULL AND v.user_email = :email
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
            WHERE a.suppressed_reason IS NULL AND a.source_id = :sid
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
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
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
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid AND a.title IS NOT NULL
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


_CLUSTER_WINDOWS = (3, 7, 30)
_CLUSTER_LIMIT = 40

# The lean scale as an ORDINAL. Declared once because the median, the spread
# bounds and the label all have to agree; two copies drift and the page starts
# reporting a median that is not one of the bands it displays.
_BAND_ORDER = ("left", "center-left", "center", "center-right", "right")
_BAND_ORD_SQL = (
    "CASE b.band WHEN 'left' THEN 0 WHEN 'center-left' THEN 1 WHEN 'center' THEN 2 "
    "WHEN 'center-right' THEN 3 WHEN 'right' THEN 4 END"
)


def _band_label(ordinal) -> str:
    """Ordinal -> display label. Returns '' for None so a caller cannot print 'None'."""
    if ordinal is None:
        return ""
    try:
        return _BAND_ORDER[int(ordinal)].title()   # "center-right" -> "Center-Right"
    except (IndexError, ValueError, TypeError):
        return ""


def _spread_sentence(outlets: int, scored: int, lo, hi) -> str:
    """The card body, derived from the data — never generated, never invented.

    ⚠️ `story_clusters.framing_summary` is NULL on ALL 5,485 rows in a 7-day
    window (measured 2026-09-02) — the column exists but nothing has ever
    written it. The design prototype's card bodies are prose like "Framing
    splits on which government the findings land on", which no column in this
    schema can produce. Deriving a factual sentence from the bands we actually
    scored is the only honest option, and it needs no LLM in the render path.
    """
    if not scored:
        return "No outlet in this cluster has been scored for bias yet."
    if lo is None or hi is None or lo == hi:
        return (
            f"All {scored} scored outlet{'' if scored == 1 else 's'} landed in the same "
            f"band — {_band_label(lo)}. No framing spread."
        )
    return (
        f"Framing runs from {_band_label(lo)} to {_band_label(hi)} across "
        f"{outlets} outlets."
    )


def _age_text(dt) -> str:
    """Relative age, e.g. '3h ago'.

    ⚠️ Deliberately RELATIVE, not an absolute timestamp. `latest_published_at`
    is `timestamp WITHOUT time zone` holding UTC, and this app registers NO
    Jinja filters at all — there is no `|localtime` here the way there is in
    the platform (using one raises TemplateAssertionError and 500s the page).
    A relative age cannot be rendered in the wrong zone, so it sidesteps the
    problem rather than getting it subtly wrong.

    Compared against a NAIVE utcnow to match the column; mixing naive and
    aware raises TypeError.
    """
    from datetime import datetime as _dt, timezone as _tz
    if dt is None:
        return "—"
    try:
        secs = (_dt.now(_tz.utc).replace(tzinfo=None) - dt).total_seconds()
    except TypeError:                      # an aware value slipped through
        secs = (_dt.now(_tz.utc) - dt).total_seconds()
    if secs < 0:                           # clock skew — never print "-2m ago"
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def _cluster_index_rows(days: int, limit: int = _CLUSTER_LIMIT):
    """Clusters carried by 2+ outlets, widest framing spread first.

    Counts are computed LIVE from articles rather than read from the
    denormalised `story_clusters.source_count`/`article_count`, for one reason:
    they must agree with /cluster/<id>, which filters `suppressed_reason IS
    NULL`. (Spot-checked 2026-09-02: the denormalised values happen to match on
    current rows, but a metric refreshed on a different filter is exactly how
    a list page comes to disagree with the detail page it links to.)
    """
    S = _schema()
    with _db().begin() as c:
        return c.execute(text(f"""
            WITH m AS (
              SELECT a.cluster_id                                         AS cid,
                     COUNT(DISTINCT a.source_id)                          AS outlets,
                     COUNT(DISTINCT a.id)                                 AS articles,
                     MAX(a.published_at)                                  AS last_pub,
                     COUNT(b.band)                                        AS scored,
                     percentile_disc(0.5) WITHIN GROUP (
                       ORDER BY {_BAND_ORD_SQL})                          AS med,
                     MIN({_BAND_ORD_SQL})                                 AS lo,
                     MAX({_BAND_ORD_SQL})                                 AS hi
                FROM {S}.articles a
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
               WHERE a.suppressed_reason IS NULL
                 AND a.cluster_id IS NOT NULL
                 AND a.published_at > NOW() - make_interval(days => :days)
               GROUP BY a.cluster_id
              HAVING COUNT(DISTINCT a.source_id) >= 2
            )
            SELECT m.cid AS id, m.outlets, m.articles, m.last_pub,
                   m.scored, m.med, m.lo, m.hi,
                   (m.hi - m.lo) AS spread,
                   sc.representative_title, sc.certainty_label
              FROM m JOIN {S}.story_clusters sc ON sc.id = m.cid
             ORDER BY (m.hi - m.lo) DESC NULLS LAST, m.outlets DESC, m.last_pub DESC
             LIMIT :lim
        """), {"days": days, "lim": limit}).mappings().all()


def _cluster_index_totals(days: int) -> dict:
    """Qualifying totals for the header tiles.

    ⚠️ These are the WINDOW totals, never `rows|length` — the same trap called
    out in blindspot.html. Measured 2026-09-02 over 7 days: 546 clusters
    qualify and only 106 of them (19%) show any framing spread at all. A page
    that showed 40 cards each with a different lean pill would imply a
    diversity of framing this corpus does not have.
    """
    S = _schema()
    with _db().begin() as c:
        row = c.execute(text(f"""
            WITH m AS (
              SELECT a.cluster_id,
                     COUNT(DISTINCT a.source_id) AS outlets,
                     MIN({_BAND_ORD_SQL}) AS lo,
                     MAX({_BAND_ORD_SQL}) AS hi
                FROM {S}.articles a
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
               WHERE a.suppressed_reason IS NULL
                 AND a.cluster_id IS NOT NULL
                 AND a.published_at > NOW() - make_interval(days => :days)
               GROUP BY a.cluster_id
              HAVING COUNT(DISTINCT a.source_id) >= 2
            )
            SELECT COUNT(*)                                        AS qualifying,
                   COUNT(*) FILTER (WHERE hi > lo)                 AS with_spread,
                   COALESCE(MAX(outlets), 0)                       AS widest
              FROM m
        """), {"days": days}).mappings().first()
    return dict(row) if row else {"qualifying": 0, "with_spread": 0, "widest": 0}


@bp.get("/clusters")
def clusters_index():
    """Story-cluster index — 'one event, many tellings' (#6149 Design phase 2).

    Linked from the main nav (News > Clusters) but returned 404 until now; the
    only cluster surface was the /cluster/<id> detail page, reachable solely
    from a link on another page.

    Ordered by framing SPREAD, not recency, because spread is the page's whole
    claim. The ordering is stated on the page rather than left implicit.
    """
    from flask import request as _req
    try:
        days = int(_req.args.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in _CLUSTER_WINDOWS:
        days = 7

    rows = [dict(r) for r in _cluster_index_rows(days)]
    for r in rows:
        r["median_band"] = (
            _BAND_ORDER[int(r["med"])] if r["med"] is not None else "center"
        )
        r["spread_text"] = _spread_sentence(
            r["outlets"], r["scored"], r["lo"], r["hi"]
        )
        r["age_text"] = _age_text(r["last_pub"])
    return render_template("clusters.html",
                           clusters=rows,
                           totals=_cluster_index_totals(days),
                           days=days,
                           windows=_CLUSTER_WINDOWS,
                           shown=len(rows))


_ARCHIVE_WINDOWS = (7, 30, 90, 365)
_ARCHIVE_PAGE = 50
# Free-tier ceilings, per the handoff spec: 10 stories or 50 articles by view.
_ARCHIVE_FREE_STORIES = 10
_ARCHIVE_FREE_ARTICLES = 50

# Sort direction is NAMED, never a bare arrow — "Filed · newest" says which end
# you are looking at; an arrow leaves the reader to guess.
_ARCHIVE_SORTS = {
    "filed":    ("Filed · newest",   "last_pub DESC"),
    "oldest":   ("Filed · oldest",   "last_pub ASC"),
    "outlets":  ("Outlets · most",   "outlets DESC, last_pub DESC"),
    "headline": ("Headline · A–Z",   "title ASC"),
    "outlet":   ("Outlet · A–Z",     "outlet ASC, last_pub DESC"),
}

# ⚠️ province (66.0% populated) and city (10.0% — #6174) are DELIBERATELY NOT
# offered as filters. A filter that silently drops a third — or nine tenths — of
# the archive misrepresents the corpus, which is the defect class ADR-020 was
# written about. The page says so out loud instead of quietly omitting them.
# Re-add province once #6174 lands, and label the coverage when you do.


def _archive_filters(args) -> dict:
    """Validate every filter against a CLOSED set. Never interpolate user text."""
    def _one(name, allowed, default="all"):
        v = (args.get(name) or default).strip()
        return v if v in allowed else default

    try:
        days = int(args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in _ARCHIVE_WINDOWS:
        days = 30
    sort = args.get("sort", "filed")
    if sort not in _ARCHIVE_SORTS:
        sort = "filed"
    try:
        page = max(1, int(args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    return {
        "view": _one("view", {"story", "article"}, "story"),
        "days": days,
        "sort": sort,
        "page": page,
        "q": (args.get("q") or "").strip()[:120],
        "lean": _one("lean", {"all", "left", "center-left", "center", "center-right", "right"}),
        "verdict": _one("verdict", {"all", "verified", "mostly_true", "mixed",
                                    "disputed", "unverifiable", "descriptive_reporting"}),
        "beat": _one("beat", set(VALID_BEATS) | {"all"}),
        "lang": _one("lang", {"all", "en", "fr"}),
        "outlet": (args.get("outlet") or "all").strip()[:80],
    }


def _archive_where(f: dict) -> tuple:
    """Build the shared WHERE fragment + bind params. Parameterised throughout."""
    where = ["a.suppressed_reason IS NULL",
             "a.published_at > NOW() - make_interval(days => :days)"]
    p = {"days": f["days"]}
    if f["q"]:
        # ILIKE on title only: body is large and unindexed for this, and a
        # headline search is what the spec's highlight behaviour describes.
        where.append("a.title ILIKE :q")
        p["q"] = f"%{f['q']}%"
    if f["lean"] != "all":
        where.append("b.band = :lean");        p["lean"] = f["lean"]
    if f["verdict"] != "all":
        where.append("fc.overall_verdict = :verdict"); p["verdict"] = f["verdict"]
    if f["beat"] != "all":
        where.append("a.beat = :beat");        p["beat"] = f["beat"]
    if f["lang"] != "all":
        where.append("s.language = :lang");    p["lang"] = f["lang"]
    if f["outlet"] != "all":
        where.append("s.name = :outlet");      p["outlet"] = f["outlet"]
    return " AND ".join(where), p


def _archive_qs(f: dict, **override) -> str:
    """Build an /archive URL preserving current filters, with overrides applied.

    Lives in Python, not the template: Jinja macros cannot take **kwargs (the
    first draft tried and raised TemplateSyntaxError at render time), and URL
    assembly is worth unit-testing. Defaults and empties are dropped so a shared
    link stays short and readable.
    """
    from urllib.parse import urlencode
    merged = {k: f[k] for k in ("view", "days", "sort", "page", "q",
                                "lean", "verdict", "beat", "lang", "outlet")}
    merged.update(override)
    keep = {k: v for k, v in merged.items()
            if v not in (None, "", "all") and not (k == "page" and v == 1)}
    return "/archive" + ("?" + urlencode(keep) if keep else "")


@bp.get("/cluster/<int:cluster_id>")
def cluster_comparison(cluster_id: int):
    """Side-by-side outlet comparison for a story cluster (#3069)."""
    S = _schema()
    with _db().begin() as c:
        meta = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.created_at, sc.framing_summary, sc.framing_generated_at,
                   sc.coverage_gap_score
            FROM {S}.story_clusters sc
            WHERE sc.id = :cid
        """), {"cid": cluster_id}).mappings().first()
    if not meta:
        abort(404)
    with _db().begin() as c:
        # LATERAL subquery prevents duplicate rows when article has multiple fact_checks
        articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   LEFT(a.body, 400) AS excerpt,
                   s.name AS source_name, s.slug AS source_slug, s.bias_lean,
                   s.language AS source_language,
                   b.band AS bias_band, b.score AS bias_score,
                   b.rationale AS bias_rationale, b.analyzed_by,
                   fc.overall_verdict, fc.analyzed_by AS fc_analyzed_by
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN LATERAL (
                SELECT overall_verdict, analyzed_by
                FROM {S}.fact_checks
                WHERE article_id = a.id AND checker NOT LIKE 'GoogleFCT%%'
                ORDER BY created_at DESC LIMIT 1
            ) fc ON true
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid
            ORDER BY a.published_at ASC
        """), {"cid": cluster_id}).mappings().all()

        # AI summary for this cluster (from summaries table)
        summary_row = c.execute(text(f"""
            SELECT headline, brief, summarizer
            FROM {S}.summaries
            WHERE cluster_id = :cid
            ORDER BY created_at DESC LIMIT 1
        """), {"cid": cluster_id}).mappings().first()
        cluster_summary = dict(summary_row) if summary_row else None

        source_count = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0
        distinct_source_count = len({a["source_name"] for a in articles})

        # Coverage Gap Score — distinct bias_lean bands that covered this cluster (#3010)
        _ALL_BANDS = ["left", "center-left", "center", "center-right", "right"]
        band_rows = c.execute(text(f"""
            SELECT DISTINCT LOWER(TRIM(s.bias_lean)) AS band
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid
              AND s.bias_lean IS NOT NULL
              AND TRIM(s.bias_lean) != ''
        """), {"cid": cluster_id}).fetchall()
        covered_bands = {r[0] for r in band_rows} & set(_ALL_BANDS)
        bias_coverage_count = len(covered_bands)
        stored_gap = meta.get("coverage_gap_score")
        if stored_gap is not None:
            gap_score = round(float(stored_gap), 3)
        else:
            gap_score = round(1.0 - (bias_coverage_count / 5.0), 3)
        coverage_data = {
            "gap_score": gap_score,
            "bias_coverage_count": bias_coverage_count,
            "covered_bands": covered_bands,
            "all_bands": _ALL_BANDS,
        }
    return render_template("cluster.html",
                           cluster=dict(meta),
                           articles=[dict(r) for r in articles],
                           distinct_source_count=distinct_source_count,
                           cluster_summary=cluster_summary,
                           source_count=source_count,
                           is_subscriber=is_subscriber(),
                           framing_summary=dict(meta).get("framing_summary"),
                           coverage_data=coverage_data)


# ---------------------------------------------------------------------------
# T3007 — Bias Drift Tracker: monthly outlet bias trend (JSON API)
# ---------------------------------------------------------------------------

@bp.get("/api/v1/outlets/<int:source_id>/bias-trend")
def outlet_bias_trend(source_id: int):
    """Return monthly avg bias score + band for an outlet (last 12 months).

    Response: {source_id, months: [{month, avg_score, band, article_count}]}
    No auth required — same public data shown in source profile.
    """
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            -- ⚠️ Buckets by a.published_at, NOT bs.computed_at — see the article
            -- sparkline above. A backlog pass would otherwise collapse a year of
            -- journalism into whichever month we happened to run the analyzer,
            -- which is the opposite of a drift tracker.
            -- ⚠️ signal_detected IS NOT FALSE — a no-signal row's 0.0/'center'
            -- are placeholders, not a centrist finding (#3012).
            SELECT
                TO_CHAR(DATE_TRUNC('month', a.published_at), 'YYYY-MM') AS month,
                ROUND(AVG(bs.score)::numeric, 3)                         AS avg_score,
                MODE() WITHIN GROUP (ORDER BY bs.band)                   AS band,
                COUNT(*)                                                  AS article_count
            FROM {S}.bias_scores bs
            JOIN {S}.articles a ON a.id = bs.article_id
            WHERE a.source_id = :sid
              AND a.published_at >= NOW() - INTERVAL '12 months'
              AND bs.signal_detected IS NOT FALSE
            GROUP BY DATE_TRUNC('month', a.published_at)
            ORDER BY 1 ASC
        """), {"sid": source_id}).mappings().all()
    return jsonify({
        "source_id": source_id,
        "months": [dict(r) for r in rows],
    })


# ---------------------------------------------------------------------------
# T3008 — "You've Been in a Bubble" weekly score (JSON API)
# ---------------------------------------------------------------------------

@bp.get("/api/me/bubble-score")
def me_bubble_score():
    """Return the current user's reading diet breakdown for the past 7 days.

    Requires login. Joins user_article_views → bias_scores, groups by band,
    returns percentage distribution + a raw bubble score (0=diverse, 1=mono).

    Response: {total_articles, distribution: {band: pct}, bubble_score}
    """
    from flask import request as _req
    email = session.get("wtf_email")
    if not email:
        return jsonify({"error": "login required"}), 401

    S = _schema()
    with _db().begin() as c:
        band_rows = c.execute(text(f"""
            SELECT COALESCE(bs.band, 'unscored') AS band, COUNT(*) AS n
            FROM {S}.user_article_views uav
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = uav.article_id
            WHERE uav.user_email = :email
              AND uav.last_view_at >= NOW() - INTERVAL '7 days'
            GROUP BY 1
        """), {"email": email}).mappings().all()

    total = sum(int(r["n"]) for r in band_rows)
    if total == 0:
        return jsonify({"total_articles": 0, "distribution": {}, "bubble_score": None})

    distribution = {r["band"]: round(int(r["n"]) / total * 100, 1) for r in band_rows}

    # Bubble score: fraction of articles from a single dominant band
    max_pct = max(distribution.values()) / 100.0
    _ORDERED_BANDS = ["left", "center-left", "center", "center-right", "right"]
    scored_total = sum(int(r["n"]) for r in band_rows if r["band"] in _ORDERED_BANDS)
    if scored_total >= 3:
        bubble_score = round(max_pct, 3)
    else:
        bubble_score = None  # not enough scored articles to be meaningful

    return jsonify({
        "total_articles": total,
        "distribution": distribution,
        "bubble_score": bubble_score,
    })


# ---------------------------------------------------------------------------
# T3011 — Story Timeline View: articles in a cluster ordered by time (JSON API)
# ---------------------------------------------------------------------------

@bp.get("/api/clusters/<int:cluster_id>/timeline")
def cluster_timeline(cluster_id: int):
    """Return all articles in a cluster ordered chronologically.

    Response: {cluster_id, article_count, articles: [{id, title, url,
               published_at, source_name, source_slug, bias_band, bias_score}]}
    """
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    S = _schema()
    with _db().begin() as c:
        meta = c.execute(text(f"""
            SELECT id, representative_title, article_count
            FROM {S}.story_clusters WHERE id = :cid
        """), {"cid": cluster_id}).mappings().first()
        if not meta:
            return jsonify({"error": "cluster not found"}), 404

        articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   s.name AS source_name, s.slug AS source_slug, s.bias_lean,
                   b.band AS bias_band, b.score AS bias_score
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid
            ORDER BY a.published_at ASC
        """), {"cid": cluster_id}).mappings().all()

    return jsonify({
        "cluster_id": cluster_id,
        "representative_title": meta["representative_title"],
        "article_count": meta["article_count"],
        "articles": [
            {
                **dict(r),
                "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            }
            for r in articles
        ],
    })


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
    from .crtc_data import get_concentration_badge
    dtype = _req.args.get("type", "all")
    S = _schema()
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
        source_count = c.execute(text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")).scalar() or 0

        # Ownership concentration data for the CRTC panel
        owner_rows = c.execute(text(f"""
            SELECT
                s.owner_name,
                s.owner_type,
                COUNT(s.id)                           AS outlet_count,
                ROUND(AVG(obs.avg_score)::numeric, 2) AS avg_bias,
                MIN(s.bias_lean)                      AS sample_lean
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            WHERE s.owner_name IS NOT NULL
            GROUP BY s.owner_name, s.owner_type
            ORDER BY outlet_count DESC
            LIMIT 10
        """)).mappings().all()
        owners_summary = [dict(r) for r in owner_rows]

    concentration_badge = get_concentration_badge(owners_summary, source_count)

    return render_template("crtc.html",
                           decisions=[dict(r) for r in rows],
                           dtype=dtype,
                           source_count=source_count,
                           owners_summary=owners_summary,
                           concentration_badge=concentration_badge,
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


# ── nav live-source counter ───────────────────────────────────────────────────
# base.html renders "LIVE · N SOURCES" in both the desktop and mobile nav from
# `nav_source_count`. It is injected for EVERY template by the context
# processor below rather than passed per route, because the per-route approach
# failed twice over: /lobbying and /claims rendered a literal ZERO (their routes
# never passed it), and the routes that DID pass it used two different
# definitions — COUNT(*) FROM sources (46, every source ever ingested) vs
# distinct sources active in 48h (41) — so the same "LIVE" label showed a
# different number depending on which page you were on.
#
# One definition, one place, and a route can no longer forget it. Per-page
# `source_count` values are deliberately left alone: some pages legitimately
# display a total in their own copy.
_NAV_SOURCE_CACHE: dict = {}
_NAV_SOURCE_TTL = int(os.environ.get("WTF_NAV_SOURCE_TTL", "300"))


def _nav_source_count() -> int:
    """Distinct sources that actually published in the last 48h. Cached — this
    runs on every page render, so it must never be a per-request query."""
    hit = _NAV_SOURCE_CACHE.get("n")
    now = time.time()
    if hit and hit[0] > now:
        return hit[1]
    try:
        with _db().begin() as c:
            n = c.execute(text(
                f"SELECT COUNT(DISTINCT s.id) FROM {_schema()}.sources s "
                f"JOIN {_schema()}.articles a ON a.source_id = s.id "
                f"AND a.ingested_at > NOW() - INTERVAL '48 hours'"
            )).scalar() or 0
    except Exception:      # a nav counter must never take a page down
        return (hit or (0, 0))[1]
    _NAV_SOURCE_CACHE["n"] = (now + _NAV_SOURCE_TTL, int(n))
    return int(n)


@bp.app_context_processor
def _inject_nav_source_count():
    return {"nav_source_count": _nav_source_count()}


_LOBBY_CACHE: dict = {}  # ("index"|org) -> (expiry_ts, payload)
_LOBBY_CACHE_TTL = int(os.environ.get("WTF_LOBBY_CACHE_TTL", "1800"))

# Registry junk that must never reach a leaderboard: 1,286 rows have an empty
# client_org and 464 carry the LITERAL four-character string 'null' (true SQL
# NULLs: zero). Unfiltered, 'null' ranks 8th among 3,689 organizations.
# Deep OFFSET paging is unbounded work: Postgres walks every skipped row, so
# a far page costs ~19x a near one. Cap it and point bulk callers at `since`
# (index-backed). 10k rows deep is far past any legitimate UI need.
_API_MAX_OFFSET = int(os.environ.get("WTF_API_MAX_OFFSET", "10000"))

_LOBBY_ORG_FILTER = "btrim(lc.client_org) NOT IN ('', 'null', 'NULL')"


@bp.get("/lobbying")
def lobbying_tracker():
    """Who lobbies Parliament — org leaderboard, most-lobbied MPs, per-org drill-down.

    Aggregate statistics are PUBLIC (they are counts, and the accountability
    story is the point of the product); the contact-level rows stay subscriber
    -gated, which is exactly what the /mp paywall copy already promises
    ("lobbying contacts ... available to subscribers"). Flipping either half is
    a one-line change — see is_subscriber use in templates/lobbying.html.

    subject_matter is deliberately absent from this page: the column exists in
    the DDL but is 100% NULL (the registry export carries no topic), so a
    "what they lobbied about" panel would be an empty promise.
    """
    from flask import request as _req
    org = (_req.args.get("org") or "").strip()
    cache_key = ("org", org.lower()) if org else ("index",)
    hit = _LOBBY_CACHE.get(cache_key)
    now = time.time()
    if hit and hit[0] > now:
        payload = hit[1]
    else:
        payload = _lobbying_payload(org)
        _LOBBY_CACHE[cache_key] = (now + _LOBBY_CACHE_TTL, payload)
    return render_template("lobbying.html", org=org, **payload,
                           is_subscriber=is_subscriber())


def _lobbying_payload(org: str) -> dict:
    """One DB round-trip for the /lobbying page (cached by the caller)."""
    with _db().begin() as c:
        stats = dict(c.execute(text(f"""
            SELECT count(*) AS contacts,
                   count(DISTINCT upper(btrim(lc.client_org)))
                       FILTER (WHERE {_LOBBY_ORG_FILTER}) AS orgs,
                   count(DISTINCT lc.mp_id) AS mps,
                   min(lc.communication_date) AS first_seen,
                   max(lc.communication_date) AS last_seen,
                   count(*) FILTER (
                       WHERE lc.communication_date > CURRENT_DATE - 30) AS last_30d
            FROM parliament.lobbyist_contacts lc
        """)).mappings().first() or {})

        # Freshness stamp from the ingest heartbeat — the page states when the
        # registry was last pulled rather than implying it is live.
        stats["synced_at"] = c.execute(text("""
            SELECT max(run_at) FROM parliament.ingest_log
            WHERE task = 'lobbying' AND COALESCE(error, '') = ''
        """)).scalar()

        if org:
            detail = c.execute(text(f"""
                SELECT (array_agg(lc.client_org ORDER BY lc.client_org))[1] AS org_label,
                       count(*) AS contacts, count(DISTINCT lc.mp_id) AS mps,
                       min(lc.communication_date) AS first_seen,
                       max(lc.communication_date) AS last_seen
                FROM parliament.lobbyist_contacts lc
                WHERE upper(btrim(lc.client_org)) = upper(:org) AND {_LOBBY_ORG_FILTER}
            """), {"org": org}).mappings().first()
            if not detail or not detail["contacts"]:
                abort(404)
            org_mps = c.execute(text(f"""
                SELECT m.slug, m.name, m.party, m.riding_name, m.is_current,
                       count(*) AS contacts, max(lc.communication_date) AS last_seen
                FROM parliament.lobbyist_contacts lc
                JOIN parliament.mps m ON m.id = lc.mp_id
                WHERE upper(btrim(lc.client_org)) = upper(:org) AND {_LOBBY_ORG_FILTER}
                GROUP BY m.id, m.slug, m.name, m.party, m.riding_name, m.is_current
                ORDER BY count(*) DESC, m.name
                LIMIT 60
            """), {"org": org}).mappings().all()
            contacts = c.execute(text(f"""
                SELECT lc.communication_date, lc.lobbyist_first, lc.lobbyist_last,
                       m.name AS mp_name, m.slug AS mp_slug
                FROM parliament.lobbyist_contacts lc
                JOIN parliament.mps m ON m.id = lc.mp_id
                WHERE upper(btrim(lc.client_org)) = upper(:org) AND {_LOBBY_ORG_FILTER}
                ORDER BY lc.communication_date DESC NULLS LAST, lc.id DESC
                LIMIT 100
            """), {"org": org}).mappings().all()
            return {"stats": stats, "detail": dict(detail),
                    "org_mps": [dict(r) for r in org_mps],
                    "contacts": [dict(r) for r in contacts],
                    "top_orgs": [], "top_mps": [], "recent": []}

        top_orgs = c.execute(text(f"""
            SELECT (array_agg(lc.client_org ORDER BY lc.client_org))[1] AS org_label,
                   upper(btrim(lc.client_org)) AS org_key,
                   count(*) AS contacts, count(DISTINCT lc.mp_id) AS mps,
                   max(lc.communication_date) AS last_seen
            FROM parliament.lobbyist_contacts lc
            WHERE {_LOBBY_ORG_FILTER}
            GROUP BY upper(btrim(lc.client_org))
            ORDER BY count(*) DESC
            LIMIT 40
        """)).mappings().all()

        top_mps = c.execute(text(f"""
            SELECT m.slug, m.name, m.party, m.riding_name,
                   count(*) AS contacts,
                   count(DISTINCT upper(btrim(lc.client_org))) AS orgs
            FROM parliament.lobbyist_contacts lc
            JOIN parliament.mps m ON m.id = lc.mp_id
            WHERE lc.communication_date > CURRENT_DATE - 365
              AND m.is_current = true AND {_LOBBY_ORG_FILTER}
            GROUP BY m.id, m.slug, m.name, m.party, m.riding_name
            ORDER BY count(*) DESC, m.name
            LIMIT 25
        """)).mappings().all()

        recent = c.execute(text(f"""
            SELECT lc.communication_date, lc.client_org,
                   lc.lobbyist_first, lc.lobbyist_last,
                   m.name AS mp_name, m.slug AS mp_slug
            FROM parliament.lobbyist_contacts lc
            JOIN parliament.mps m ON m.id = lc.mp_id
            WHERE {_LOBBY_ORG_FILTER}
            ORDER BY lc.communication_date DESC NULLS LAST, lc.id DESC
            LIMIT 50
        """)).mappings().all()

    return {"stats": stats, "detail": None, "org_mps": [], "contacts": [],
            "top_orgs": [dict(r) for r in top_orgs],
            "top_mps": [dict(r) for r in top_mps],
            "recent": [dict(r) for r in recent]}


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

        # ⚠️ source_count is the DENOMINATOR of every ownership share on this
        # page, so it must count the same population as owner.outlet_count —
        # which is every source, not the recently-active ones.
        #
        # It used to be COUNT(DISTINCT s.id) ... JOIN articles ... ingested_at >
        # NOW() - INTERVAL '48 hours', i.e. outlets that PUBLISHED in the last
        # two days: 31 of 46 when this was measured. The header therefore
        # claimed "31 outlets tracked" while the site tracks 46, and each share
        # divided a 46-population count by 31 — so the four concentration tiles
        # read 55% + 10% + 45% + 39% = 149%, which is visibly impossible on a
        # page whose whole subject is ownership concentration.
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
        source_count = c.execute(text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")).scalar() or 0
        # COALESCE is load-bearing: the template does `groupby('caucus')`, and
        # Jinja's groupby SORTS by key — None < str raises TypeError and 500s
        # the whole page. A freshly-appointed senator legitimately has no
        # caucus yet (2026-08-18: three appointees took /mps down for ~2.5h).
        # 'Non-affiliated' is also the factual label for a new appointee.
        senators = c.execute(text("""
            SELECT slug, name, given_name, family_name,
                   COALESCE(caucus, 'Non-affiliated') AS caucus,
                   province, photo_url, profile_url, appointed_at
            FROM parliament.senators WHERE is_current = true
            ORDER BY COALESCE(caucus, 'Non-affiliated'), name
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
        # FORMER senators are served too (badged in the template), not 404'd.
        # Their voting record is permanent public record and we hold it: 12
        # former senators carry 222 ballots, and the 4 who departed in the
        # 2026-08-18 roster sync had LIVE urls that turned into 404s the
        # moment they retired — link rot on a transparency product.
        row = c.execute(text("""
            SELECT id, slug, name, given_name, family_name, caucus, province,
                   photo_url, profile_url, appointed_at, date_of_birth,
                   appointed_by, biography, office_phone, office_email,
                   twitter_handle, linkedin_url, website_url, is_current
            FROM parliament.senators WHERE slug = :slug
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
        # A forward-looking countdown is meaningless for someone who has
        # already left the chamber — emit it only for sitting senators.
        if senator.get("is_current"):
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


# MP donor-rollup cache — the two EC aggregations in mp_profile are the
# expensive part of the page (parliament.ec_contributions, 7.3M rows). EC
# data changes at most daily; keyed by normalized riding so every MP page
# in a riding shares one entry (343 ridings max — bounded).
_MP_DONOR_CACHE: dict = {}  # lower(riding) -> (expiry_ts, (totals, donors))
_MP_DONOR_CACHE_TTL = int(os.environ.get("WTF_MP_DONOR_CACHE_TTL", "3600"))


def _donor_group_sort_key(label: str):
    """Display order for the riding-funding groups (#5731): contest returns
    (the newest money) first, then annual association returns newest-year
    first with undated last, then general elections newest first. Sorted in
    Python because the DB collation orders 'Annual (undated)' ABOVE
    'Annual 2025' — punctuation-vs-digit ordering is collation-dependent."""
    m = re.search(r"(\d{4})$", label)
    year = int(m.group(1)) if m else 0
    if label.startswith("Contest returns"):
        return (0, -year)
    if label.startswith("Annual"):
        return (1, -year if year else 1)  # undated (year 0) sinks below real years
    m = re.match(r"(\d+)", label)
    return (2, -int(m.group(1)) if m else 0, label)


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
            WHERE a.suppressed_reason IS NULL AND t.mp_id = :mp_id
            ORDER BY a.published_at DESC
            LIMIT 15
        """), {"mp_id": mp["id"]}).mappings().all()

        source_count = c.execute(text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")).scalar() or 0

    stats = {r["ballot"]: r["cnt"] for r in vote_stats}
    total_votes = sum(stats.values())

    # Accountability data — best-effort (tables may not exist on first run)
    lobbying_contacts = []
    expense_periods = []
    disclosures = []
    promises = []
    committees = []
    try:
        with _db().begin() as c:
            committees = c.execute(text("""
                SELECT committee_abbr, committee_name, role
                FROM parliament.mp_committees
                WHERE member_id = :mp_id AND is_current
                ORDER BY CASE role WHEN 'chair' THEN 0
                                   WHEN 'vice-chair' THEN 1 ELSE 2 END,
                         committee_name
            """), {"mp_id": mp["id"]}).mappings().all()

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

    # Donor data from Elections Canada (parliament.ec_contributions).
    # The two aggregations scan a 7.3M-row table, so the riding filter MUST
    # stay index-usable: lower(electoral_district) = lower(:riding) is served
    # by ix_ec_district_lower (migration 049). ILIKE here previously forced a
    # full seq scan per query (~24s/page — the "won't populate" outage).
    # EC data changes at most daily; all MPs in a riding share one cache entry.
    riding_donor_totals = []
    top_named_donors = []
    try:
        riding = mp.get("riding_name") or ""
        # EC uses "--" (double dash), parliament.mps uses "—" (em dash) — normalize
        riding_ec = riding.replace("—", "--").replace("–", "--")
        _dk = riding_ec.lower()
        _dc = _MP_DONOR_CACHE.get(_dk)
        if _dc and _dc[0] > time.time():
            riding_donor_totals, top_named_donors = _dc[1]
        else:
            with _db().begin() as c:
                # 'Annual' association returns are split by YEAR (#5731) —
                # lumping 2019-2025 into one row made the panel read as if
                # nothing newer than the last election existed. Note EC's
                # cadence: riding association returns are ANNUAL, so the
                # current year appears only once EC publishes it (spring of
                # the following year); rows with an empty electoral_event
                # are leadership/nomination contest returns.
                riding_donor_totals = [dict(r) for r in c.execute(text("""
                    SELECT CASE
                             WHEN electoral_event = 'Annual'
                               THEN 'Annual ' || COALESCE(
                                      EXTRACT(YEAR FROM contribution_date)::int::text,
                                      '(undated)')
                             WHEN COALESCE(electoral_event, '') = ''
                               THEN TRIM('Contest returns ' || COALESCE(
                                      EXTRACT(YEAR FROM contribution_date)::int::text, ''))
                             ELSE electoral_event
                           END AS electoral_event,
                           political_entity,
                           COUNT(*) AS donation_count,
                           SUM(monetary_amount) AS total_raised,
                           COUNT(DISTINCT contributor_name)
                               FILTER (WHERE contributor_name NOT ILIKE '%200 or less%'
                                         AND contributor_name NOT ILIKE '%ou moins%') AS named_donors
                    FROM parliament.ec_contributions
                    WHERE lower(electoral_district) = lower(:riding)
                      AND monetary_amount > 0
                    GROUP BY 1, political_entity
                    ORDER BY 1 DESC, total_raised DESC
                    LIMIT 16
                """), {"riding": riding_ec}).mappings().all()]
                riding_donor_totals.sort(
                    key=lambda r: _donor_group_sort_key(r["electoral_event"] or ""))

                top_named_donors = [dict(r) for r in c.execute(text("""
                    SELECT contributor_name, contributor_city, contributor_province,
                           SUM(monetary_amount) AS total_given,
                           COUNT(*) AS num_contributions,
                           MAX(electoral_event) AS latest_event
                    FROM parliament.ec_contributions
                    WHERE lower(electoral_district) = lower(:riding)
                      AND monetary_amount >= 200
                      AND contributor_name NOT ILIKE '%200 or less%'
                      AND contributor_name NOT ILIKE '%ou moins%'
                      AND contributor_name != ''
                    GROUP BY contributor_name, contributor_city, contributor_province
                    ORDER BY total_given DESC
                    LIMIT 20
                """), {"riding": riding_ec}).mappings().all()]
            _MP_DONOR_CACHE[_dk] = (
                time.time() + _MP_DONOR_CACHE_TTL,
                (riding_donor_totals, top_named_donors),
            )
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
                           committees=[dict(r) for r in committees],
                           is_subscriber=is_subscriber())


@bp.get("/journalists")
def journalists_listing():
    """Public directory of tracked journalists (RSS bylines → shared entity graph). #3329."""
    S = _schema()
    SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
    q = (request.args.get("q") or "").strip()
    like = f"%{q.lower()}%"
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT count(*) FROM {S}.sources")).scalar() or 0
        total = c.execute(
            text(f"SELECT count(*) FROM {SH}.entities WHERE entity_type='journalist'")
        ).scalar() or 0
        rows = c.execute(text(f"""
            SELECT e.id, e.canonical_name, e.slug,
                   (SELECT count(DISTINCT em.content_id) FROM {SH}.entity_mentions em
                     WHERE em.entity_id=e.id AND em.product='wtf'
                       AND em.content_type='article') AS article_count
              FROM {SH}.entities e
             WHERE e.entity_type='journalist'
               AND (:q='' OR lower(e.canonical_name) LIKE :like
                    OR EXISTS (SELECT 1 FROM unnest(e.aliases) al WHERE lower(al) LIKE :like))
             ORDER BY article_count DESC NULLS LAST, e.canonical_name ASC
             LIMIT 200
        """), {"q": q.lower(), "like": like}).mappings().all()
    return render_template("journalists.html",
                           journalists=[dict(r) for r in rows], q=q, total=total,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.get("/journalist/<int:entity_id>")
def journalist_profile(entity_id):
    """Journalist profile — outlets + recent coverage (free), bias-lean + volume trend +
    co-mentioned entities (premium). Reads the live shared entity graph. #3329."""
    S = _schema()
    SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
    subscribed = is_subscriber()
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT count(*) FROM {S}.sources")).scalar() or 0
        ent = c.execute(text(f"""
            SELECT id, canonical_name, slug, COALESCE(metadata, '{{}}'::jsonb) AS metadata
              FROM {SH}.entities WHERE id=:e AND entity_type='journalist'
        """), {"e": entity_id}).mappings().first()
        if not ent:
            abort(404)
        ent = dict(ent)
        # a.id::text = content_id (never cast content_id->int, a stray value would 500)
        join = (f"FROM {SH}.entity_mentions em JOIN {S}.articles a ON a.id::text=em.content_id "
                f"WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article'")
        article_count = c.execute(
            text(f"SELECT count(DISTINCT a.id) {join}"), {"e": entity_id}
        ).scalar() or 0
        outlets = c.execute(text(f"""
            SELECT src.slug, src.name, count(DISTINCT a.id) n
              FROM {SH}.entity_mentions em JOIN {S}.articles a ON a.id::text=em.content_id
              JOIN {S}.sources src ON src.id=a.source_id
             WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article'
             GROUP BY src.slug, src.name ORDER BY n DESC LIMIT 10
        """), {"e": entity_id}).mappings().all()
        recent = c.execute(text(f"""
            SELECT a.id, a.title, a.published_at, a.bias_ensemble_band AS bias_band,
                   src.slug AS source_slug, src.name AS source_name
              FROM {SH}.entity_mentions em JOIN {S}.articles a ON a.id::text=em.content_id
              JOIN {S}.sources src ON src.id=a.source_id
             WHERE a.suppressed_reason IS NULL AND em.entity_id=:e AND em.product='wtf' AND em.content_type='article'
             ORDER BY a.published_at DESC NULLS LAST LIMIT 12
        """), {"e": entity_id}).mappings().all()
        # Premium analysis — only run the heavier queries for subscribers.
        bias, trend, co = [], [], []
        if subscribed:
            bias = c.execute(text(
                f"SELECT COALESCE(a.bias_ensemble_band,'unknown') band, count(DISTINCT a.id) n "
                f"{join} GROUP BY 1 ORDER BY n DESC"), {"e": entity_id}).mappings().all()
            trend = c.execute(text(
                f"SELECT to_char(date_trunc('month', a.published_at),'YYYY-MM') m, "
                f"count(DISTINCT a.id) n {join} GROUP BY 1 ORDER BY 1 DESC LIMIT 12"),
                {"e": entity_id}).mappings().all()
            co = c.execute(text(f"""
                SELECT e2.id, e2.canonical_name, e2.entity_type, count(DISTINCT em2.content_id) n
                  FROM {SH}.entity_mentions em1
                  JOIN {SH}.entity_mentions em2 ON em2.content_id=em1.content_id
                       AND em2.product='wtf' AND em2.content_type='article'
                       AND em2.entity_id<>em1.entity_id
                  JOIN {SH}.entities e2 ON e2.id=em2.entity_id
                 WHERE em1.entity_id=:e AND em1.product='wtf' AND em1.content_type='article'
                 GROUP BY e2.id, e2.canonical_name, e2.entity_type ORDER BY n DESC LIMIT 10
            """), {"e": entity_id}).mappings().all()
    return render_template("journalist.html", j=ent, article_count=article_count,
                           outlets=[dict(r) for r in outlets],
                           recent=[dict(r) for r in recent],
                           bias=[dict(r) for r in bias],
                           trend=[dict(r) for r in trend],
                           co_mentioned=[dict(r) for r in co],
                           source_count=source_count, is_subscriber=subscribed)


@bp.get("/entity/<int:entity_id>")
def entity_profile_page(entity_id):
    """Cross-Watch entity profile — the accountability footprint across all Watch
    products (#3331). Free = identity + which products mention this entity + recent
    WTF coverage. Premium = chain links (contracts/donations/votes/lobbying) +
    co-mentioned entities. Reads the live shared entity graph."""
    S = _schema()
    SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
    subscribed = is_subscriber()
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT count(*) FROM {S}.sources")).scalar() or 0
        ent = c.execute(text(f"""
            SELECT id, entity_type, canonical_name, slug, aliases,
                   COALESCE(metadata, '{{}}'::jsonb) AS metadata
              FROM {SH}.entities
             WHERE id=:e AND status='active'
               AND entity_type IN ('person','organization','journalist')
        """), {"e": entity_id}).mappings().first()
        if not ent:
            abort(404)
        ent = dict(ent)
        # Cross-product footprint: mentions grouped by product (the cross-watch link).
        products = c.execute(text(f"""
            SELECT product, count(*) AS mentions, count(DISTINCT content_type) AS kinds
              FROM {SH}.entity_mentions WHERE entity_id=:e
             GROUP BY product ORDER BY mentions DESC
        """), {"e": entity_id}).mappings().all()
        # Recent WTF coverage (free). a.id::text = content_id (never cast content_id->int).
        recent = c.execute(text(f"""
            SELECT a.id, a.title, a.published_at, a.bias_ensemble_band AS bias_band,
                   src.slug AS source_slug, src.name AS source_name
              FROM {SH}.entity_mentions em JOIN {S}.articles a ON a.id::text=em.content_id
              JOIN {S}.sources src ON src.id=a.source_id
             WHERE a.suppressed_reason IS NULL AND em.entity_id=:e AND em.product='wtf' AND em.content_type='article'
             ORDER BY a.published_at DESC NULLS LAST LIMIT 12
        """), {"e": entity_id}).mappings().all()
        # Competition Bureau items naming this organization (free — Legal Watch link, #3059).
        # http(s)-only guard is defense-in-depth (news_url is a trusted GC canada.ca link).
        competition = []
        if ent["entity_type"] == "organization":
            competition = [
                dict(r) for r in c.execute(text(f"""
                    SELECT content_id AS news_url, mention_context AS headline
                      FROM {SH}.entity_mentions
                     WHERE entity_id=:e AND product='legal-watch'
                       AND content_type='competition_enforcement'
                     ORDER BY id DESC LIMIT 20
                """), {"e": entity_id}).mappings().all()
                if (r["news_url"] or "").startswith(("http://", "https://"))
            ]
        # Publicly-traded federal contractor (FREE — public money, the #373 Contract->Market
        # link, L6). The company entity --market_reaction_to--> its security node (slug
        # 'security-<ticker>'); join securities.issuer_contracts for the dollar footprint the
        # structural graph edge lacks. Read-only; market=None when the company isn't a linked
        # TSX contractor.
        market = None
        if ent["entity_type"] == "organization":
            mrow = c.execute(text(f"""
                SELECT upper(replace(s.slug, 'security-', '')) AS ticker, ic.exchange,
                       ic.total, ic.n, ic.jv
                  FROM {SH}.entity_relationships r
                  JOIN {SH}.entities s ON s.id = r.to_entity_id AND s.slug LIKE 'security-%'
                  JOIN securities.issuer_contracts ic
                       ON upper(replace(s.slug, 'security-', '')) = upper(ic.ticker)
                 WHERE r.from_entity_id = :e AND r.relationship_type = 'market_reaction_to'
                   AND ic.total > 0
                 ORDER BY ic.total DESC LIMIT 1
            """), {"e": entity_id}).mappings().first()
            market = dict(mrow) if mrow else None
        # Premium: chain links + co-mentioned (WTF-bounded, like the journalist page).
        links, co = [], []
        if subscribed:
            links = c.execute(text(f"""
                SELECT r.relationship_type, clt.label, clt.is_spine,
                       count(*) FILTER (WHERE r.from_entity_id=:e) AS out_n,
                       count(*) FILTER (WHERE r.to_entity_id=:e) AS in_n
                  FROM {SH}.entity_relationships r
                  JOIN {SH}.chain_link_types clt ON clt.relationship_type=r.relationship_type
                 WHERE r.from_entity_id=:e OR r.to_entity_id=:e
                 GROUP BY r.relationship_type, clt.label, clt.is_spine
                 ORDER BY count(*) DESC
            """), {"e": entity_id}).mappings().all()
            co = c.execute(text(f"""
                SELECT e2.id, e2.canonical_name, e2.entity_type, count(DISTINCT em2.content_id) n
                  FROM {SH}.entity_mentions em1
                  JOIN {SH}.entity_mentions em2 ON em2.content_id=em1.content_id
                       AND em2.product='wtf' AND em2.content_type='article'
                       AND em2.entity_id<>em1.entity_id
                  JOIN {SH}.entities e2 ON e2.id=em2.entity_id AND e2.status='active'
                 WHERE em1.entity_id=:e AND em1.product='wtf' AND em1.content_type='article'
                 GROUP BY e2.id, e2.canonical_name, e2.entity_type ORDER BY n DESC LIMIT 12
            """), {"e": entity_id}).mappings().all()
    total_mentions = sum(int(p["mentions"]) for p in products)
    return render_template("entity.html", e=ent,
                           products=[dict(r) for r in products],
                           recent=[dict(r) for r in recent],
                           competition=competition,
                           market=market,
                           links=[dict(r) for r in links],
                           co_mentioned=[dict(r) for r in co],
                           total_mentions=total_mentions,
                           source_count=source_count, is_subscriber=subscribed)


_CROSSWATCH_CACHE: dict = {}
_CROSSWATCH_CACHE_TTL = 300  # 5 min — cross-product membership changes slowly


def _crosswatch_top(c, SH):
    """Cached ranked list of entities spanning >=2 Watch products. The ranking
    GROUP BY over entity_mentions is ~670ms, so cache it (per-worker TTL) — never
    run it uncached on every page hit (the 2026-06-15 shared-gunicorn DoS lesson)."""
    now = time.time()
    if _CROSSWATCH_CACHE.get("ts", 0) + _CROSSWATCH_CACHE_TTL > now:
        return _CROSSWATCH_CACHE.get("data", [])
    rows = c.execute(text(f"""
        SELECT e.id, e.entity_type, e.canonical_name,
               array_agg(DISTINCT m.product) AS products, count(*) AS mentions
        FROM {SH}.entities e
        JOIN {SH}.entity_mentions m ON m.entity_id=e.id
        WHERE e.status='active' AND e.entity_type IN ('person','organization')
        GROUP BY e.id, e.entity_type, e.canonical_name
        HAVING count(DISTINCT m.product) >= 2
        ORDER BY count(DISTINCT m.product) DESC, count(*) DESC
        LIMIT 60
    """)).mappings().all()
    data = [{"id": r["id"], "name": r["canonical_name"], "type": r["entity_type"],
             "products": list(r["products"] or []), "mentions": int(r["mentions"])} for r in rows]
    _CROSSWATCH_CACHE["ts"] = now
    _CROSSWATCH_CACHE["data"] = data
    return data


@bp.get("/cross-watch")
def cross_watch_explorer():
    """Cross-Watch explorer (#3331 1c) — browse/search entities resolved across the
    Watch Series. Default = top entities spanning the most products (cached); ?q=
    searches by name/alias. Public; each result links to its /entity/<id> footprint."""
    S = _schema()
    SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
    q = (request.args.get("q") or "").strip()
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT count(*) FROM {S}.sources")).scalar() or 0
        if q:
            like = f"%{q.lower()}%"
            rows = c.execute(text(f"""
                SELECT e.id, e.entity_type, e.canonical_name,
                       array_agg(DISTINCT m.product) AS products, count(*) AS mentions
                FROM {SH}.entities e
                JOIN {SH}.entity_mentions m ON m.entity_id=e.id
                WHERE e.status='active' AND e.entity_type IN ('person','organization')
                  AND (lower(e.canonical_name) LIKE :like
                       OR EXISTS (SELECT 1 FROM unnest(e.aliases) a WHERE lower(a) LIKE :like))
                GROUP BY e.id, e.entity_type, e.canonical_name
                ORDER BY count(DISTINCT m.product) DESC, count(*) DESC
                LIMIT 60
            """), {"like": like}).mappings().all()
            entities = [{"id": r["id"], "name": r["canonical_name"], "type": r["entity_type"],
                         "products": list(r["products"] or []), "mentions": int(r["mentions"])}
                        for r in rows]
        else:
            entities = _crosswatch_top(c, SH)
    return render_template("cross_watch.html", entities=entities, q=q,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.get("/markets")
def markets_page():
    """Publicly traded federal contractors (#373 Contract->Market, chain link L6) — a
    browsable, menu-visible ranked list of the TSX-listed companies that are also federal
    contractors, by cumulative federal-contract $. Public (like the per-entity market
    block). Each row links to that company's /entity/<id> Cross-Watch footprint. Picks,
    per issuer, the most-connected linked entity so the link lands on a rich page."""
    S = _schema()
    SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT count(*) FROM {S}.sources")).scalar() or 0
        rows = c.execute(text(f"""
            SELECT ic.ticker, ic.name, ic.exchange, ic.total, ic.n, ic.jv, link.entity_id
            FROM securities.issuer_contracts ic
            JOIN {SH}.entities s
                 ON s.slug LIKE 'security-%'
                AND upper(replace(s.slug, 'security-', '')) = upper(ic.ticker)
            JOIN LATERAL (
                SELECT r.from_entity_id AS entity_id
                FROM {SH}.entity_relationships r
                WHERE r.to_entity_id = s.id AND r.relationship_type = 'market_reaction_to'
                ORDER BY (SELECT count(*) FROM {SH}.entity_relationships rr
                          WHERE rr.from_entity_id = r.from_entity_id
                             OR rr.to_entity_id = r.from_entity_id) DESC, r.from_entity_id
                LIMIT 1
            ) link ON true
            WHERE ic.total > 0
            ORDER BY ic.total DESC
        """)).mappings().all()
    issuers = [{"ticker": r["ticker"], "name": r["name"], "exchange": r["exchange"],
                "total": int(r["total"] or 0), "n": int(r["n"] or 0), "jv": bool(r["jv"]),
                "entity_id": r["entity_id"]} for r in rows]
    total_all = sum(i["total"] for i in issuers)
    return render_template("markets.html", issuers=issuers, total_all=total_all,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.route("/score", methods=["GET", "POST"])
def score_url():
    """Subscriber-gated: paste any article text for instant AI analysis."""
    from flask import request as _req, redirect
    subscribed = is_subscriber()
    # GET renders publicly (score.html shows the Subscribe CTA when not subscribed) —
    # the old top-of-route login bounce sent anonymous visitors straight to the
    # platform SSO ("A.R.C.H.I.E. — System Access"), a dead end + internal-branding
    # leak for a public nav item. Only the POST (actual analysis) is gated. (#4895)
    result = None
    error = None
    article_text = ""
    if _req.method == "POST":
        if not _user_email():
            return redirect("/login?next=/score")
        if not subscribed:
            return redirect("/join?gated=score")
        article_text = (_req.form.get("text") or "").strip()[:5000]
        article_title = (_req.form.get("title") or "").strip()[:200]
        if len(article_text) < 100:
            error = "Please paste at least 100 characters of article text."
        else:
            wtf_tech_url = os.environ.get("WTF_TECH_URL", "http://wtf-tech:8104")
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
            source_count = c.execute(text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")).scalar() or 0
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
            c.execute(text("SET LOCAL jit = off"))
            source_count = c.execute(text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")).scalar() or 0
            # The WHERE expression must stay byte-identical to the expression
            # GIN index idx_articles_fts (migration 051) or the planner falls
            # back to a full seq scan recomputing to_tsvector over 108k bodies
            # — measured 45s+ per query, a guaranteed edge 504 (#5725).
            # ts_rank re-derives the tsvector per row (detoasting the body),
            # so it runs only over the newest 400 matches, never unbounded:
            # relevance-among-recent is the right semantics for a news site.
            rows = c.execute(text(f"""
                SELECT m.id, m.title, m.url, m.published_at,
                       m.source, m.source_slug, m.band,
                       ts_rank(to_tsvector('english', COALESCE(m.title,'') || ' ' || COALESCE(m.body,'')),
                               plainto_tsquery('english', :q)) AS rank
                FROM (
                    SELECT a.id, a.title, a.body, a.url, a.published_at,
                           s.name AS source, s.slug AS source_slug, b.band
                    FROM {S}.articles a
                    JOIN {S}.sources s ON s.id = a.source_id
                    LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                    WHERE a.suppressed_reason IS NULL AND to_tsvector('english', COALESCE(a.title,'') || ' ' || COALESCE(a.body,''))
                          @@ plainto_tsquery('english', :q)
                    ORDER BY a.published_at DESC
                    LIMIT 400
                ) m
                ORDER BY rank DESC, m.published_at DESC
                LIMIT 50
            """), {"q": q}).mappings().all()
        results = [dict(r) for r in rows]
    else:
        source_count = 0
    return render_template("search.html", q=q, results=results,
                           source_count=source_count, is_subscriber=is_subscriber())


@bp.get("/chain")
def chain_explorer():
    """Public 8-link Accountability-Chain Explorer (project #373, task #3793).

    Renders the chain-query API (/api/public/chain/*) which is same-origin,
    bounded + cached — so this page can never trigger a heavy read.
    """
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("chain.html", chain_slug=None, source_count=source_count)


@bp.get("/chain/<slug>")
def chain_explorer_entity(slug):
    """Deep-link into a single entity's accountability chain."""
    with _db().begin() as c:
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("chain.html", chain_slug=slug, source_count=source_count)


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
        # Faceted /news (any query string: band/province/beat/scope/riding/page
        # permutations) is a crawl trap — thousands of DB-heavy URL variants of
        # the same content. Clean /news stays crawlable; articles are in the
        # sitemap. GPTBot walking these facets was 91% of traffic 2026-08-18.
        "Disallow: /news?\n"
        "Sitemap: https://what-the-fact.com/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


# One article-sitemap file holds 40k URLs — under the 50k/50MB protocol cap
# with headroom. With faceted /news disallowed in robots.txt, the sitemap is
# the primary crawl path to the article back-catalogue, which outgrows a
# single file (#5717) — so /sitemap.xml is a sitemap INDEX.
_SITEMAP_ARTICLE_PAGE = 40000


@bp.get("/sitemap.xml")
def sitemap_xml():
    """Sitemap INDEX — points at the core sitemap + paged article sitemaps."""
    from flask import Response
    S = _schema()
    with _db().begin() as c:
        total, newest = c.execute(text(f"""
            SELECT COUNT(*), MAX(published_at) FROM {S}.articles
            -- Must match the paged listing's filter EXACTLY. If the count includes
            -- rows the listing excludes, the index advertises a page number the
            -- listing cannot fill and search engines fetch an empty sitemap.
            WHERE suppressed_reason IS NULL
        """)).fetchone()
    pages = max(1, -(-int(total or 0) // _SITEMAP_ARTICLE_PAGE))
    newest_tag = (f"<lastmod>{newest.strftime('%Y-%m-%d')}</lastmod>"
                  if newest else "")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             "  <sitemap><loc>https://what-the-fact.com/sitemap-core.xml</loc>"
             f"{newest_tag}</sitemap>"]
    for p in range(1, pages + 1):
        # Chunks are OLDEST-first, so earlier pages are immutable and only
        # the LAST page grows — stamp it so crawlers re-fetch just that one.
        tag = newest_tag if p == pages else ""
        lines.append(
            f"  <sitemap><loc>https://what-the-fact.com/sitemap-articles-{p}.xml</loc>"
            f"{tag}</sitemap>"
        )
    lines.append("</sitemapindex>")
    return Response("\n".join(lines), mimetype="application/xml")


@bp.get("/sitemap-core.xml")
def sitemap_core():
    """Static pages + source profiles (formerly the head of the single sitemap)."""
    from flask import Response
    S = _schema()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    static_pages = ["/", "/sources", "/map", "/team", "/join", "/activity", "/news", "/lobbying"]
    for path in static_pages:
        lines.append(f"  <url><loc>https://what-the-fact.com{path}</loc></url>")
    with _db().begin() as c:
        src_rows = c.execute(text(f"SELECT slug FROM {S}.sources ORDER BY slug")).fetchall()
    for sr in src_rows:
        lines.append(
            f"  <url><loc>https://what-the-fact.com/source/{sr[0]}</loc>"
            "<changefreq>weekly</changefreq></url>"
        )
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")


@bp.get("/sitemap-articles-<int:page>.xml")
def sitemap_articles(page: int):
    """One 40k-article chunk, OLDEST first — page 1 never changes, new
    articles only ever append to the last page (crawler-cache friendly).
    Ordering is bare ASC (published_at has no NULLs; id breaks ties) so the
    published_at index + incremental sort serve it — no full-table sort.
    """
    from flask import Response
    # Werkzeug's int converter is unbounded — a 20-digit page would reach
    # Postgres and 500 on bigint overflow. 50k pages = 2B articles.
    if page < 1 or page > 50000:
        abort(404)
    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT id, published_at
            FROM {S}.articles
            -- ⚠️ NEVER ADVERTISE A PAGE THE SITE SUPPRESSES.
            -- This query had NO WHERE CLAUSE, so every suppressed article was
            -- submitted to search engines — and a suppressed article still serves
            -- a full HTTP 200 page (measured: 55,861 bytes with a real <title>).
            -- After #3036 that is ~8,300 duplicate-content pages this site's own
            -- sitemap points Google at, plus the pre-existing suppressed_reason
            -- population from migration 056.
            -- Proof it was including them: the index advertised 4 article pages
            -- (123,641 / 40,000) where the visible count gives 3 (115,279).
            WHERE suppressed_reason IS NULL
            ORDER BY published_at ASC, id ASC
            LIMIT :lim OFFSET :off
        """), {"lim": _SITEMAP_ARTICLE_PAGE,
               "off": (page - 1) * _SITEMAP_ARTICLE_PAGE}).fetchall()
    if not rows and page != 1:
        abort(404)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
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


@bp.get("/api/v1/featured-story")
def featured_story():
    """Return the top story cluster ranked by distinct outlets (not raw article count)."""
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    S = _schema()
    with _db().begin() as c:
        row = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   COUNT(DISTINCT a.source_id) AS real_source_count,
                   sc.coverage_gap_score, sc.certainty_label, sc.latest_published_at,
                   sm.headline, sm.brief
            FROM {S}.story_clusters sc
            JOIN {S}.articles a ON a.cluster_id = sc.id
            LEFT JOIN {S}.summaries sm ON sm.cluster_id = sc.id
            WHERE sc.latest_published_at > NOW() - INTERVAL '24 hours'
              AND sc.article_count >= 3
            GROUP BY sc.id, sc.representative_title, sc.article_count,
                     sc.coverage_gap_score, sc.certainty_label, sc.latest_published_at,
                     sm.headline, sm.brief
            HAVING COUNT(DISTINCT a.source_id) >= 2
            ORDER BY COUNT(DISTINCT a.source_id) DESC, sc.article_count DESC,
                     sc.latest_published_at DESC
            LIMIT 1
        """)).fetchone()
    if not row:
        return _api_cors_response({"story": None})
    keys = ["id", "representative_title", "article_count", "source_count",
            "coverage_gap_score", "certainty_label", "latest_published_at",
            "headline", "brief"]
    story = {}
    for k, v in zip(keys, row):
        story[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return _api_cors_response({"story": story})


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
_API_RATE_BUCKETS: dict = _rate_limit.BUCKETS  # ip → [timestamps]; shared with cross_watch
_API_RATE_LIMIT = int(os.environ.get("WTF_API_V1_RATE_LIMIT", "60"))
_API_RATE_WINDOW_SEC = 60


def _api_rate_ok(ip: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds).

    Kept for the callers that bucket by an explicit key (/news, crawler facets).
    The algorithm now lives in the stdlib-only ``rate_policy`` so it is unit
    tested without Flask (KB #290497); behaviour here is unchanged.
    """
    return _rate_policy.bucket_allow(
        _API_RATE_BUCKETS.setdefault(ip, []),
        time.time(),
        _API_RATE_LIMIT,
        _API_RATE_WINDOW_SEC,
    )


# --- /news overload defense (#4256): short-TTL data cache + generous per-IP limit.
# /news is the public feed; the heavy part is the DB queries, NOT the render, and
# the data does not vary by tier — so we cache the query RESULTS (keyed on the
# filters) and still render per-request (is_subscriber() stays correct, no paywall
# leak). The rate limit uses the REAL client IP (X-Forwarded-For — remote_addr is
# the Caddy gateway) and is fail-open + generous so it never bricks the site.
_NEWS_CACHE: dict = {}  # filter-key -> (expiry_ts, (source_count, total, rows, sources, ridings))
_NEWS_CACHE_TTL = int(os.environ.get("WTF_NEWS_CACHE_TTL", "60"))
_NEWS_CACHE_MAX = int(os.environ.get("WTF_NEWS_CACHE_MAX", "512"))
_NEWS_RATE_LIMIT = int(os.environ.get("WTF_NEWS_RATE_LIMIT", "180"))  # per-IP /news req / 60s


def _client_ip() -> str:
    """Real client IP behind Caddy — X-Forwarded-For first hop, else remote_addr."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _news_rate_ok(ip: str) -> bool:
    """Generous per-IP limiter for the heavy /news page. Fail-open on any error."""
    try:
        now = time.time()
        bucket = _API_RATE_BUCKETS.setdefault("news:" + ip, [])
        bucket[:] = [t for t in bucket if t > now - 60]
        if len(bucket) >= _NEWS_RATE_LIMIT:
            return False
        bucket.append(now)
        return True
    except Exception:
        return True


# Faceted-crawl guard: one bucket shared by ALL crawler UAs hitting /news
# with query params. Per-IP limiting can't catch a bot fleet (GPTBot crawled
# faceted /news from many IPs at 91% of traffic, 2026-08-18) and each unique
# facet permutation misses _NEWS_CACHE by construction. Clean /news (no query
# string) is never subject to this bucket. Fail-open on any error.
# Deliberately NOT matched: user-triggered fetchers (facebookexternalhit link
# previews, ChatGPT-User) — a human sharing /news?province=ON must still get
# a preview card. Bulk crawlers only.
_CRAWLER_UA_RE = re.compile(
    r"(?i)(gptbot|oai-searchbot|claudebot|claude-web|ccbot|"
    r"bytespider|amazonbot|petalbot|semrushbot|ahrefsbot|mj12bot|dotbot|"
    r"googlebot|bingbot|yandexbot|applebot|perplexitybot|meta-externalagent)"
)
_CRAWLER_FACET_BUCKET: list = []
# PER-WORKER limit — module state is per gunicorn worker (4 sync workers ⇒
# aggregate ≈ 4×). Default 6/min/worker ≈ 24/min aggregate, which binds below
# the measured incident rate (~35 faceted req/min, 2026-08-18).
_CRAWLER_FACET_LIMIT = int(os.environ.get("WTF_CRAWLER_FACET_LIMIT", "6"))


def _is_crawler_ua(ua: str) -> bool:
    return bool(_CRAWLER_UA_RE.search(ua or ""))


def _crawler_facet_rate_ok() -> bool:
    """Shared token bucket for faceted /news requests from crawler UAs."""
    try:
        now = time.time()
        _CRAWLER_FACET_BUCKET[:] = [t for t in _CRAWLER_FACET_BUCKET if t > now - 60]
        if len(_CRAWLER_FACET_BUCKET) >= _CRAWLER_FACET_LIMIT:
            return False
        _CRAWLER_FACET_BUCKET.append(now)
        return True
    except Exception:
        return True


# ── UA-INDEPENDENT faceted ceiling (2026-08-30 outage) ──────────────────────
# The guard above keys on _is_crawler_ua, i.e. on a SELF-DECLARED User-Agent,
# which is attacker-controlled. On 2026-08-30 a fleet walked /news facets
# presenting ordinary browser UAs ("Chrome/145.0.0.0 Edg/145.0.0.0" 6,913 hits,
# "Mac OS X 10_15_7" 2,264) — matching NOTHING in the named-bot allowlist — so
# the tight 6/min guard never fired. They fell through to _news_rate_ok's
# generous 180/min PER IP, which a handful of source IPs clears trivially:
# measured ~378 faceted req/min sustained 17:42-18:05, all 4 workers saturated,
# then WEDGED — the site stayed 502 for ~10 minutes AFTER the flood stopped.
#
# The expensive thing is not "a crawler". It is "a faceted /news request that
# misses the cache by construction", which is true of ANY sender. So this bucket
# is deliberately UA-BLIND. It sits ABOVE realistic human faceted browsing and
# far BELOW fleet volume, so it never bites a real reader.
#
# Per-worker like its sibling: 4 sync workers ⇒ aggregate ≈ 4×. Default 30/min
# /worker ≈ 120/min aggregate vs the ~378/min incident rate and vs a human, who
# changes a filter a handful of times a minute at most.
# Clean /news (no query string) is NEVER throttled here — only facets.
_FACET_ANY_BUCKET: list = []
_FACET_ANY_LIMIT = int(os.environ.get("WTF_FACET_ANY_LIMIT", "30"))


def _facet_any_rate_ok() -> bool:
    """Ceiling on faceted /news for EVERY caller, whatever UA it claims.

    Fail-open on any error: a bug in the limiter must never take the page down,
    which is the failure mode this whole guard exists to prevent.
    """
    try:
        now = time.time()
        _FACET_ANY_BUCKET[:] = [t for t in _FACET_ANY_BUCKET if t > now - 60]
        if len(_FACET_ANY_BUCKET) >= _FACET_ANY_LIMIT:
            return False
        _FACET_ANY_BUCKET.append(now)
        return True
    except Exception:
        return True


def _news_cache_get(key):
    ent = _NEWS_CACHE.get(key)
    if ent and ent[0] > time.time():
        return ent[1]
    if ent:
        _NEWS_CACHE.pop(key, None)
    return None


def _news_cache_set(key, payload):
    now = time.time()
    if len(_NEWS_CACHE) >= _NEWS_CACHE_MAX:
        for k in [k for k, v in list(_NEWS_CACHE.items()) if v[0] <= now]:
            _NEWS_CACHE.pop(k, None)
        if len(_NEWS_CACHE) >= _NEWS_CACHE_MAX:
            for k in sorted(_NEWS_CACHE, key=lambda k: _NEWS_CACHE[k][0])[: max(1, _NEWS_CACHE_MAX // 8)]:
                _NEWS_CACHE.pop(k, None)
    _NEWS_CACHE[key] = (now + _NEWS_CACHE_TTL, payload)


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


def _api_rate_check(tier: str | None = None):
    """Returns a 429 response if rate-limited, else None to proceed.

    ``tier`` defaults to whatever ``rate_policy.classify()`` makes of the request
    path, so an expensive route (``/analyze``, which enqueues LLM work on the
    hub) or a write (``/flag``, ``/newsletter/subscribe``) gets its small budget
    without every call site having to remember. The reported ``limit`` is the
    AGGREGATE figure, not the per-worker number enforced, so this response and
    the public API docs quote the same number.
    """
    ok, retry, limit, window = _rate_limit.check(tier=tier)
    if not ok:
        resp = _api_cors_response({
            "ok": False, "error": "rate_limited",
            "retry_after": retry,
            "limit": limit,
            "window_seconds": window,
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
    beat = (_req.args.get("beat") or "all").strip()[:20]
    beat = _norm_beat(beat)
    try:
        limit = min(100, max(1, int(_req.args.get("limit", 50))))
        # OFFSET IS CLAMPED because deep paging is the real availability risk on
        # this endpoint — not request volume. A deep page costs ~19x a shallow
        # one (Postgres still walks every skipped row), so SIX concurrent
        # deep-offset requests — an order of magnitude UNDER the published
        # 60/min quota — drove the public /news page from 0.14s to 11.13s
        # (measured 2026-08-18). No rate-limit setting fixes that; bounding the
        # scan does. Callers needing the full corpus should page by `since`,
        # which is index-backed and unbounded.
        offset = max(0, min(_API_MAX_OFFSET, int(_req.args.get("offset", 0))))
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
    if beat and beat != "all":
        where.append("a.beat = :beat"); params["beat"] = beat
    where_clause = " AND ".join(where)

    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, a.province_code,
                   a.country_code, a.geo_scope, a.analysis_tier,
                   a.ai_analyzed, a.cluster_id,
                   sc.article_count AS cluster_size,
                   s.slug AS source_slug, s.name AS source_name,
                   s.bias_lean AS source_bias_lean,
                   b.band AS bias_band, b.score AS bias_score,
                   (SELECT STRING_AGG(m.name, ', ' ORDER BY m.name)
                    FROM {S}.article_mp_tags t
                    JOIN parliament.mps m ON m.id = t.mp_id
                    WHERE t.article_id = a.id) AS mp_mentions,
                   (SELECT fc.overall_verdict FROM {S}.fact_checks fc
                    WHERE fc.article_id = a.id AND fc.checker NOT LIKE 'GoogleFCT%%'
                    ORDER BY fc.checked_at DESC LIMIT 1) AS overall_verdict
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
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
                "overall_verdict": r["overall_verdict"],
                "geo": {"province_code": r["province_code"],
                        "country_code": r["country_code"],
                        "scope": r["geo_scope"]},
                "analysis_tier": r["analysis_tier"],
                "ai_analyzed": bool(r["ai_analyzed"]),
                "cluster_id": r["cluster_id"],
                "cluster_size": r["cluster_size"],
                "mp_mentions": r["mp_mentions"],
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


_BLINDSPOT_WINDOWS = (3, 7, 14, 30)


def _blindspot_total(days=7, max_gap=0.15):
    """How many stories QUALIFY in this window — not how many are shown.

    ⚠️ These differ by orders of magnitude: measured 255 qualifying in 3 days
    and 2,883 in 30, against a page size of 20. Labelling the page size as
    "stories in window" would tell a reader there are 20 blind spots in a month
    when there are nearly three thousand.
    """
    S = _schema()
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT count(*) FROM {S}.story_clusters sc
            WHERE sc.coverage_gap_score > 0
              AND sc.coverage_gap_score <= :max_gap
              AND sc.article_count >= 2
              AND sc.latest_published_at >= NOW() - INTERVAL '1 day' * :days
              AND EXISTS (
                  SELECT 1 FROM {S}.articles a
                  WHERE a.cluster_id = sc.id
                    AND (a.country_code = 'CA'
                         OR a.geo_scope IN ('national', 'provincial'))
              )
        """), {"max_gap": max_gap, "days": days}).scalar() or 0


def _blindspot_rows(days=7, limit=20, max_gap=0.15):
    """Rows behind BOTH /blindspot and /api/v1/blindspot.

    Extracted so the page and the API cannot drift: a blindspot shown to a
    reader and one returned to an API client must be the same story set.

    ⚠️ ORDERING CAVEAT (measured 2026-08-31): ~2,981 clusters are TIED at the
    minimum coverage_gap_score, so `coverage_gap_score ASC` barely
    discriminates and `latest_published_at DESC` is the real sort. With 255
    qualifying stories already inside the 3-day window, the top `limit` is the
    same set for every window — widening to 30 days adds candidates that all
    rank below it. The window therefore changes the POPULATION but not this
    page's visible list. Surfaced honestly via _blindspot_total(); making the
    control change the list is an editorial decision about what "blind spot"
    should rank on, not a rendering fix.
    """
    S = _schema()
    with _db().begin() as c:
        return c.execute(text(f"""
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
              AND EXISTS (
                  SELECT 1 FROM {S}.articles a
                  WHERE a.cluster_id = sc.id
                    AND (a.country_code = 'CA'
                         OR a.geo_scope IN ('national', 'provincial'))
              )
            ORDER BY sc.coverage_gap_score ASC, sc.latest_published_at DESC
            LIMIT :n
        """), {"max_gap": max_gap, "days": days, "n": limit}).mappings().all()


@bp.get("/blindspot")
def blindspot_page():
    """Dedicated Blindspot Feed page — rendered SERVER-SIDE.

    ⚠️ This page shipped as an empty <div id="bs-list"> waiting for JavaScript
    that was never written: no <script> in the template, and nothing anywhere
    in static/js/ referenced `bs-list` or `wtf-bs-`. /api/v1/blindspot has been
    returning 20 real stories the whole time, and the page is linked from the
    main nav — so every visitor got a heading, four dead filter buttons, and
    nothing else. Rendering from the shared helper needs no client JS at all.

    The window buttons are now plain links (?days=N), so filtering works
    without JavaScript too.

    (The old call also passed a hardcoded source_count=46. It was dead — the
    nav reads `nav_source_count` from a context processor, which takes
    precedence — and a hardcoded constant standing in for a live count is the
    defect class that made /owners' shares sum to 149%.)
    """
    from flask import request as _req
    try:
        days = int(_req.args.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in _BLINDSPOT_WINDOWS:
        days = 7
    return render_template("blindspot.html",
                           blindspots=_blindspot_rows(days=days),
                           total_in_window=_blindspot_total(days=days),
                           days=days,
                           windows=_BLINDSPOT_WINDOWS,
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
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    from flask import request as _req
    limit = min(int(_req.args.get("limit", 20)), 100)
    days = min(int(_req.args.get("days", 7)), 90)
    max_gap = float(_req.args.get("max_gap_score", 0.15))
    # Same helper the PAGE renders from — the two cannot drift apart.
    rows = _blindspot_rows(days=days, limit=limit, max_gap=max_gap)
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
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
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
            WHERE (
                -- True bias gap: both sides have meaningful coverage
                (cl.en_count >= 2 AND cl.fr_count >= 2
                 AND ABS(COALESCE(cl.en_avg_score, 0) - COALESCE(cl.fr_avg_score, 0)) >= :min_div)
                OR
                -- EN only: significant English presence, French press silent
                (cl.en_count >= 3 AND cl.fr_count = 0)
                OR
                -- FR only: significant French presence, English press silent
                (cl.fr_count >= 3 AND cl.en_count = 0)
            )
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
# T3005 — Riding-level geo-filter API
# ───────────────────────────────────────────────────────────────────────────


@bp.get("/api/v1/ridings")
def api_v1_ridings():
    """Return ridings that have tagged articles, with counts.

    Query params:
      province   — filter by province code (e.g. ON, BC). Default: all.
      min_count  — minimum article count to include (default 1).
      limit      — max results (default 100, max 338 = total Canadian ridings).
    """
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    from flask import request as _req

    province = (_req.args.get("province") or "all").strip().upper()
    try:
        min_count = max(1, int(_req.args.get("min_count", 1)))
    except (ValueError, TypeError):
        min_count = 1
    try:
        limit = min(338, max(1, int(_req.args.get("limit", 100))))
    except (ValueError, TypeError):
        limit = 100

    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT m.riding_name,
                   m.province_code,
                   COUNT(t.article_id) AS article_count
            FROM parliament.mps m
            JOIN {S}.article_mp_tags t ON t.mp_id = m.id
            WHERE m.riding_name IS NOT NULL
              AND m.is_current = true
              AND (:province = 'ALL' OR m.province_code = :province)
            GROUP BY m.riding_name, m.province_code
            HAVING COUNT(t.article_id) >= :min_count
            ORDER BY COUNT(t.article_id) DESC
            LIMIT :limit
        """), {"province": province, "min_count": min_count, "limit": limit}).mappings().all()

    return _api_cors_response({
        "ok": True,
        "count": len(rows),
        "province_filter": province,
        "ridings": [
            {
                "riding_name": r["riding_name"],
                "province_code": r["province_code"],
                "article_count": r["article_count"],
            }
            for r in rows
        ],
    })


# ───────────────────────────────────────────────────────────────────────────
# Map page (#2961) — Leaflet map of articles pinned by lat/lng
# ───────────────────────────────────────────────────────────────────────────


@bp.get("/map")
def map_page():
    """Public map view — articles pinned globally by their lat/lng."""
    return render_template("map.html", source_count=46, is_subscriber=is_subscriber())


# The 13 Canadian provinces & territories. This is an ALLOWLIST on purpose:
# articles.province_code is not exclusively Canadian — it also holds US state
# codes (KY, NY), and one row even carries 'CA', a COUNTRY code in the province
# column. Deriving "Canadian" from "has a province_code" would therefore file
# Kentucky under Canada.
_CA_PROVINCES = frozenset(
    ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
)


def _pin_country(country_code, province_code):
    """Country for a map pin, plus HOW we know it.

    articles.country_code stopped being populated at some point — every one of
    the 4,291 geocoded articles in the current 7-day window has it NULL while
    5,475 older rows carry 'CA'. /map colours pins by country, so the whole map
    rendered a single "unknown" grey and the legend advertised two categories
    that could never appear.

    A province code IS a statement about the country, so we can recover most of
    it. Two rules keep that honest:

      1. A REPORTED country always wins. There are 89 rows with country 'US' and
         province 'ON'; trusting the province there would relabel them Canadian.
      2. Only the 13 real Canadian codes derive a country. Anything else stays
         unknown rather than being guessed at.

    Returns (code, source) where source is reported | derived | unknown, so the
    UI can distinguish a reading from an inference instead of flattening both.
    """
    cc = (country_code or "").strip().upper()
    if cc and cc != "??":
        return cc, "reported"
    pc = (province_code or "").strip().upper()
    if pc in _CA_PROVINCES:
        return "CA", "derived"
    return "??", "unknown"


@bp.get("/api/v1/map-data")
def api_map_data():
    """JSON pin data for /map. Aggregates by (lat, lng) cluster to avoid
    1,700+ stacked dots at province centroids. Returns up to 3 sample
    article titles + a total count per pin.

    Supports ?beat=<slug> to filter pins by news beat (category).
    """
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    from flask import jsonify, request as _req
    S = _schema()
    beat = _req.args.get("beat", "all")
    if beat not in VALID_BEATS:
        beat = "all"
    beat_where = "AND a.beat = :beat" if beat != "all" else ""
    params = {"beat": beat} if beat != "all" else {}
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
            WHERE a.suppressed_reason IS NULL AND a.lat IS NOT NULL AND a.lng IS NOT NULL
              AND a.published_at > NOW() - INTERVAL '7 days'
              {beat_where}
            GROUP BY 1, 2, 3, 4
            ORDER BY article_count DESC
            LIMIT 500
        """), params).mappings().all()
    pins = []
    for r in rows:
        country, source = _pin_country(r["country_code"], r["province_code"])
        pins.append({
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "country_code": country,
            # How we know the country. The map colours by country, so a guess and
            # a reading must not render alike — see _pin_country.
            "country_source": source,
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
# Newsletter capture (#4899, ADR-011) — public weekly-digest signup.
# CASL: express consent at the form (consent_at), unsubscribe token in every
# digest email, identified sender. Rows sync to KBS CRM via the ingest cycle.
# ───────────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


@bp.post("/api/newsletter/subscribe")
def newsletter_subscribe():
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    data = request.get_json(silent=True) or {}
    # Honeypot — real users never fill the hidden 'website' field; bots that
    # do get a quiet 200 and no row.
    if (data.get("website") or "").strip():
        return jsonify({"ok": True})
    email = (data.get("email") or "").strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "invalid_email"}), 400
    S = _schema()
    with _db().begin() as c:
        c.execute(
            text(f"""
                INSERT INTO {S}.newsletter_subscribers (email, source)
                VALUES (:email, 'footer')
                ON CONFLICT (email) DO UPDATE
                  SET active = TRUE, unsubscribed_at = NULL
            """),
            {"email": email},
        )
    return jsonify({"ok": True})


@bp.get("/newsletter/unsubscribe")
def newsletter_unsubscribe():
    token = (request.args.get("token") or "").strip()
    ok = False
    if token:
        S = _schema()
        try:
            with _db().begin() as c:
                row = c.execute(
                    text(f"""
                        UPDATE {S}.newsletter_subscribers
                        SET active = FALSE, unsubscribed_at = NOW()
                        WHERE unsub_token = CAST(:tok AS uuid)
                        RETURNING id
                    """),
                    {"tok": token},
                ).fetchone()
            ok = row is not None
        except Exception:
            ok = False  # malformed token — treat as invalid, no 500
    return render_template("unsubscribe.html", ok=ok)


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
    from flask import jsonify

    from ingest import tier2_upgrade

    if not is_subscriber():
        return jsonify({"ok": False, "error": "subscriber_required"}), 402

    # ONE implementation, shared with tier2_precompute_worker. This used to carry
    # its own ~90 lines of dispatch + persist; a second copy in the worker is how
    # queued_dispatch_text ended up with two divergent versions.
    res = tier2_upgrade.upgrade_article(_db(), _schema(), article_id)
    status = res.get("status")

    if status == "upgraded":
        return jsonify({
            "ok": True,
            "analysis_tier": "quick_v1+full",
            "bias_summary": res.get("bias_summary") or {},
            "claims_count": res.get("claims", 0),
            "agent": res.get("agent") or "",
        })
    if status == "already":
        return jsonify({"ok": True, "result": "already_upgraded"})
    if status == "not_found":
        return jsonify({"ok": False, "error": "not_found"}), 404
    if status == "rate_limited":
        return jsonify({"ok": False, "error": "hub_rate_limited",
                        "retry_after": res.get("retry_after")}), 429
    if status == "timeout":
        return jsonify({"ok": False, "error": "hub_timeout"}), 504
    if res.get("error") == "hub_not_configured":
        return jsonify({"ok": False, "error": "hub_not_configured"}), 503
    return jsonify({"ok": False, "error": res.get("error") or "dispatch_failed"}), 502


# ---------------------------------------------------------------------------
# T3016 — Institutional Licensing: Education API for Media Literacy
# Public, no-auth endpoints for classrooms, journalism courses, research.
# Rate limit: reuses _api_rate_check() (same bucket as /api/v1 — abusers
# cannot bypass limits by switching to /api/edu paths).
# ---------------------------------------------------------------------------

_EDU_MAX_LIMIT = 50


@bp.get("/edu")
def edu_landing():
    """Education API landing page — explains the API and institutional licensing."""
    # Render the ENFORCED limit, never a hardcoded promise. This page advertised
    # "100 requests / hour per IP" while the code enforced 60/60s (#5748); a
    # number typed into a template drifts the moment the constant changes.
    _limit, _window = _rate_policy.limits_for("default")
    return render_template(
        "edu.html",
        is_subscriber=is_subscriber(),
        rate_limit=_limit,
        rate_window=_window,
    )


@bp.get("/api/edu/v1/articles")
def edu_api_articles():
    """Paginated article list with bias scores for classroom use.

    Params: beat, province, bias_band, days (default 7), page (1-based), limit (max 50)
    Returns: id, title, url, source_name, published_at, bias_band, bias_score,
             province_code, beat, fact_check_verdict
    """
    from flask import request as _req
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err

    beat = (_req.args.get("beat") or "").strip()[:60]
    province = (_req.args.get("province") or "").strip().upper()[:2]
    bias_band = (_req.args.get("bias_band") or "").strip()[:20]
    try:
        days = max(1, min(90, int(_req.args.get("days", 7))))
        page = max(1, int(_req.args.get("page", 1)))
        limit = max(1, min(_EDU_MAX_LIMIT, int(_req.args.get("limit", 20))))
    except (TypeError, ValueError):
        return _api_cors_response({"ok": False, "error": "invalid numeric param"}, status=400)

    offset = (page - 1) * limit
    S = _schema()
    where = ["a.published_at > NOW() - :days * INTERVAL '1 day'"]
    params: dict = {"limit": limit, "offset": offset, "days": days}

    if beat:
        where.append("a.beat = :beat")
        params["beat"] = beat
    if province:
        where.append("a.province_code = :province")
        params["province"] = province
    if bias_band:
        where.append("b.band = :bias_band")
        params["bias_band"] = bias_band

    where_clause = " AND ".join(where)

    with _db().begin() as c:
        total = c.execute(text(f"""
            SELECT COUNT(*)
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE {where_clause}
        """), params).scalar() or 0

        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at,
                   a.province_code, a.beat,
                   s.name AS source_name, s.slug AS source_slug,
                   b.band AS bias_band, b.score AS bias_score,
                   fc.overall_verdict AS fact_check_verdict
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.fact_checks fc
                ON fc.article_id = a.id AND fc.checker NOT LIKE 'GoogleFCT%%'
            WHERE a.suppressed_reason IS NULL AND {where_clause}
            ORDER BY a.published_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return _api_cors_response({
        "ok": True,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, -(-total // limit)),  # ceiling division
        "days": days,
        "articles": [
            {
                "id": r["id"],
                "title": r["title"],
                "url": r["url"],
                "source_name": r["source_name"],
                "source_slug": r["source_slug"],
                "published_at": r["published_at"].isoformat() if r.get("published_at") else None,
                "bias_band": r["bias_band"],
                "bias_score": float(r["bias_score"]) if r.get("bias_score") is not None else None,
                "province_code": r["province_code"],
                "beat": r["beat"],
                "fact_check_verdict": r["fact_check_verdict"],
            }
            for r in rows
        ],
    })


@bp.get("/api/edu/v1/sources")
def edu_api_sources():
    """All tracked sources with bias info for media literacy context.

    Returns: slug, name, bias_lean, avg_score, band, outlet_count, owner_name
    """
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err

    S = _schema()
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT s.slug, s.name, s.url, s.bias_lean, s.owner_name, s.owner_type,
                   s.country, s.language,
                   obs.avg_score, obs.band,
                   COUNT(a.id) AS outlet_count
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN {S}.articles a ON a.source_id = s.id
            GROUP BY s.id, s.slug, s.name, s.url, s.bias_lean, s.owner_name,
                     s.owner_type, s.country, s.language, obs.avg_score, obs.band
            ORDER BY s.name
        """)).mappings().all()

    def _domain_from_url(u):
        """Derive a bare matchable domain from a source url.

        Browser-extension keys link matching strictly on `domain`, so every
        source must expose one. urlparse handles urls with/without scheme.
        """
        if not u:
            return None
        try:
            netloc = urllib.parse.urlparse(u).hostname
            if not netloc:
                # url stored without scheme (e.g. "cbc.ca/news") — fall back
                netloc = urllib.parse.urlparse("//" + u).hostname
            if not netloc:
                return None
            netloc = netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return None

    return _api_cors_response({
        "ok": True,
        "count": len(rows),
        "sources": [
            {
                "slug": r["slug"],
                "name": r["name"],
                "url": r["url"],
                "domain": _domain_from_url(r["url"]),
                "bias_lean": r["bias_lean"],
                "avg_score": float(r["avg_score"]) if r.get("avg_score") is not None else None,
                # alias for browser extension which expects numeric src.bias_score
                "bias_score": float(r["avg_score"]) if r.get("avg_score") is not None else None,
                "band": r["band"],
                "outlet_count": int(r["outlet_count"]),
                "owner_name": r["owner_name"],
                "owner_type": r["owner_type"],
                "country": r["country"],
                "language": r["language"],
            }
            for r in rows
        ],
    })


@bp.get("/api/edu/v1/story/<int:cluster_id>")
def edu_api_story(cluster_id: int):
    """Full story cluster for classroom discussion.

    Returns cluster metadata + all articles + bias distribution + fact check verdicts.
    """
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err

    S = _schema()
    with _db().begin() as c:
        meta = c.execute(text(f"""
            SELECT id, representative_title, article_count,
                   created_at, framing_summary, coverage_gap_score
            FROM {S}.story_clusters
            WHERE id = :cid
        """), {"cid": cluster_id}).mappings().first()

    if not meta:
        return _api_cors_response({"ok": False, "error": "cluster not found"}, status=404)

    with _db().begin() as c:
        articles = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, a.province_code,
                   s.name AS source_name, s.slug AS source_slug, s.bias_lean,
                   b.band AS bias_band, b.score AS bias_score,
                   fc.overall_verdict AS fact_check_verdict
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            LEFT JOIN {S}.fact_checks fc
                ON fc.article_id = a.id AND fc.checker NOT LIKE 'GoogleFCT%%'
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid
            ORDER BY a.published_at ASC
        """), {"cid": cluster_id}).mappings().all()

        band_rows = c.execute(text(f"""
            SELECT COALESCE(b.band, 'unscored') AS band, COUNT(*) AS n
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid
            GROUP BY 1 ORDER BY 2 DESC
        """), {"cid": cluster_id}).mappings().all()

        verdict_rows = c.execute(text(f"""
            SELECT fc.overall_verdict, COUNT(*) AS n
            FROM {S}.fact_checks fc
            JOIN {S}.articles a ON a.id = fc.article_id
            WHERE a.suppressed_reason IS NULL AND a.cluster_id = :cid
              AND fc.checker NOT LIKE 'GoogleFCT%%'
              AND fc.overall_verdict IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC
        """), {"cid": cluster_id}).mappings().all()

    bias_distribution = {r["band"]: int(r["n"]) for r in band_rows}
    fact_check_summary = {r["overall_verdict"]: int(r["n"]) for r in verdict_rows}

    return _api_cors_response({
        "ok": True,
        "cluster": {
            "id": meta["id"],
            "title": meta["representative_title"],
            "article_count": meta["article_count"],
            "created_at": meta["created_at"].isoformat() if meta.get("created_at") else None,
            "framing_summary": meta["framing_summary"],
            "coverage_gap_score": float(meta["coverage_gap_score"]) if meta.get("coverage_gap_score") is not None else None,
            "bias_distribution": bias_distribution,
            "fact_check_summary": fact_check_summary,
        },
        "articles": [
            {
                "id": r["id"],
                "title": r["title"],
                "url": r["url"],
                "published_at": r["published_at"].isoformat() if r.get("published_at") else None,
                "province_code": r["province_code"],
                "source_name": r["source_name"],
                "source_slug": r["source_slug"],
                "source_bias_lean": r["bias_lean"],
                "bias_band": r["bias_band"],
                "bias_score": float(r["bias_score"]) if r.get("bias_score") is not None else None,
                "fact_check_verdict": r["fact_check_verdict"],
            }
            for r in articles
        ],
    })


@bp.get("/api/edu/v1/stats")
def edu_api_stats():
    """Platform-level stats for media literacy discussions.

    Returns: total_sources, total_articles, bias_distribution (%), top_stories_this_week
    """
    rate_err = _api_rate_check()
    if rate_err:
        return rate_err

    S = _schema()
    with _db().begin() as c:
        total_sources = c.execute(
            text(f"SELECT COUNT(DISTINCT s.id) FROM {S}.sources s JOIN {S}.articles a ON a.source_id = s.id AND a.ingested_at > NOW() - INTERVAL '48 hours'")
        ).scalar() or 0

        total_articles = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.articles")
        ).scalar() or 0

        band_rows = c.execute(text(f"""
            SELECT b.band, COUNT(*) AS n
            FROM {S}.bias_scores b
            WHERE b.band IS NOT NULL
            GROUP BY b.band
            ORDER BY n DESC
        """)).mappings().all()

        total_scored = sum(int(r["n"]) for r in band_rows)
        bias_distribution = {
            r["band"]: {
                "count": int(r["n"]),
                "pct": round(int(r["n"]) / total_scored * 100, 1) if total_scored else 0.0,
            }
            for r in band_rows
        }

        top_rows = c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.created_at, sc.coverage_gap_score
            FROM {S}.story_clusters sc
            WHERE sc.created_at > NOW() - INTERVAL '7 days'
            ORDER BY sc.article_count DESC
            LIMIT 10
        """)).mappings().all()

    return _api_cors_response({
        "ok": True,
        "total_sources": total_sources,
        "total_articles": total_articles,
        "scored_articles": total_scored,
        "bias_distribution": bias_distribution,
        "top_stories_this_week": [
            {
                "id": r["id"],
                "title": r["representative_title"],
                "article_count": r["article_count"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "coverage_gap_score": float(r["coverage_gap_score"]) if r.get("coverage_gap_score") is not None else None,
            }
            for r in top_rows
        ],
    })


# ---------------------------------------------------------------------------
# End T3016 Education API
# ---------------------------------------------------------------------------


@bp.route("/api/internal/set-tier", methods=["POST"])
def internal_set_tier():
    """Internal webhook — platform billing pushes tier changes here.
    Auth: X-Internal-Key header == INTERNAL_API_KEY env var.
    Payload: {"email": "...", "tier": "starter|solo|..."}
    No-downgrade: lower-ranked incoming tier is ignored.
    WTF stores canonical platform tiers as-is (no local mapping needed).
    """
    from .db import get_db, get_billing_tier

    expected = os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        return jsonify({"error": "internal key not configured"}), 503
    if request.headers.get("X-Internal-Key", "") != expected:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    tier = (data.get("tier") or "free").strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400
    VALID = {"kytran", "owner", "admin", "pro", "agency", "team", "solo", "starter", "free"}
    if tier not in VALID:
        return jsonify({"error": f"unknown tier '{tier}'"}), 400

    _TIER_RANK = {
        "free": 0, "starter": 10, "solo": 30, "team": 40, "agency": 50,
        "pro": 60, "admin": 90, "owner": 99, "kytran": 99,
    }
    existing = get_billing_tier(email)
    if _TIER_RANK.get(tier, 0) < _TIER_RANK.get(existing, 0):
        return jsonify({"ok": True, "email": email, "tier": existing, "unchanged": True})

    try:
        conn = get_db()
        if tier == "free":
            conn.execute(
                "UPDATE billing_subscriptions SET tier='free', status='cancelled',"
                " updated_at=CURRENT_TIMESTAMP WHERE LOWER(email)=LOWER(?)",
                (email,),
            )
        else:
            conn.execute(
                """INSERT INTO billing_subscriptions (email, tier, status, updated_at)
                   VALUES (LOWER(?), ?, 'active', CURRENT_TIMESTAMP)
                   ON CONFLICT(email) DO UPDATE SET
                       tier=excluded.tier, status='active', updated_at=CURRENT_TIMESTAMP""",
                (email, tier),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True, "email": email, "tier": tier})


# ═══════════════════════════════════════════════════════════════════════════
# Public API keys + docs (task #2138)
#
# Keys are FREE and self-serve (owner decision 2026-08-19). They exist to give a
# caller an IDENTITY so limits can be per-caller instead of per-IP — two
# colleagues behind one NAT stop sharing a budget, and one abusive client can be
# revoked without throttling everyone around them. Paid tiers are a table change
# in rate_policy.PLANS, not a schema or route change.
#
# The docs page renders the ENFORCED numbers straight out of the policy, for the
# same reason /edu does: a hardcoded "100 requests/hour" in the docs was wrong
# for as long as it existed, and nobody could tell by reading it.
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/account/api-keys")
def api_keys_page():
    """Self-serve key management. Login required; no tier requirement."""
    from flask import redirect
    email = _user_email()
    if not email:
        return redirect("/login?next=/account/api-keys")
    from . import api_keys as _ak
    try:
        keys = _ak.list_keys(_db(), email)
    except Exception as exc:
        logger.warning("[api-keys] list failed: %s", exc)
        keys = []
    return render_template(
        "api_keys.html",
        keys=keys,
        email=email,
        is_subscriber=is_subscriber(),
        max_keys=_ak.MAX_ACTIVE_KEYS_PER_USER,
    )


@bp.post("/api/account/api-keys")
def api_keys_create():
    """Mint a key. The full value is returned ONCE and is not recoverable."""
    from flask import jsonify, request as freq
    email = _user_email()
    if not email:
        return jsonify({"error": "authentication_required"}), 401
    limited = _api_rate_check("write")
    if limited is not None:
        return limited
    body = freq.get_json(silent=True) or {}
    label = (body.get("label") or "").strip()[:80]
    from . import api_keys as _ak
    try:
        created = _ak.create_key(_db(), email, label=label)
    except ValueError as exc:
        # e.g. per-user cap reached — a user-correctable condition, not a 500
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("[api-keys] create failed: %s", exc)
        return jsonify({"error": "could not create key"}), 500
    return jsonify({"ok": True, **created}), 201


@bp.post("/api/account/api-keys/<prefix>/revoke")
def api_keys_revoke(prefix: str):
    """Soft-revoke one of the caller's OWN keys.

    Scoped to owner_email in SQL, so a guessed prefix cannot revoke someone
    else's key. Returns 404 (not 403) on a miss — a caller must not be able to
    probe which prefixes exist.
    """
    from flask import jsonify
    email = _user_email()
    if not email:
        return jsonify({"error": "authentication_required"}), 401
    limited = _api_rate_check("write")
    if limited is not None:
        return limited
    from . import api_keys as _ak
    try:
        ok = _ak.revoke_key(_db(), email, (prefix or "").strip())
    except Exception as exc:
        logger.error("[api-keys] revoke failed: %s", exc)
        return jsonify({"error": "could not revoke key"}), 500
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "prefix": prefix, "revoked": True})


@bp.get("/api/docs")
def api_docs_page():
    """Public API documentation.

    Every limit shown is read live from rate_policy, so the page cannot drift
    from what the edge enforces — the failure the /edu page had until #5748.
    """
    from . import rate_policy as _rp
    from . import rate_limit as _rate_limit
    plans = []
    for plan in _rp.PLAN_ORDER:
        rows = []
        for tier in sorted(_rp.PLANS[plan]):
            limit, window = _rp.limits_for(tier, plan)
            rows.append({"tier": tier, "limit": limit, "window": window})
        plans.append({"plan": plan, "rows": rows})
    return render_template(
        "api_docs.html",
        plans=plans,
        key_header=_rate_limit.API_KEY_HEADER,
        signed_in=bool(_user_email()),
    )
