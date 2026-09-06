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
from . import echo_data as _echo_data  # pure series math for /echo (#6272 follow-up)
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


# Platform shift states (CLAUDE.md): active, deployed, barracked, off_duty,
# winding_down, cooldown.
_SHIFT_STATE_LABELS = {
    "active": "Active",
    "deployed": "Deployed",
    "barracked": "Barracked",
    "off_duty": "Off duty",
    "winding_down": "Winding down",
    "cooldown": "Cooldown",
}


def _team_badge(welfare):
    """(label, is_active) for a named agent's top-right card badge.

    ⚠️ THE BUG THIS REPLACES: the badge was a hardcoded '{% else %}Active{%
    endif %}' in team.html, so it read "Active" for all 8 named cards
    regardless of the agent's real shift_state — while the welfare pill two
    lines below it, on the SAME card, already rendered the true state.
    Verified live 2026-09-05: F.A.C.T.'s card said "Active" at the top and
    "winding down" in the welfare pill; I.N.K.'s said "Active" and "off
    duty" — a self-contradiction on the newsroom's own transparency page.

    Falls back to ('Active', True) ONLY when welfare is genuinely
    unavailable (no dict, or an unrecognized shift_state string) — same
    fail-open philosophy _get_welfare_lookup already uses elsewhere on this
    page. It never fabricates a SPECIFIC non-active state without real data
    behind it; it can only under-report (stay silent as 'Active') if a new
    shift_state value is added upstream and this table isn't updated yet.
    """
    shift = (welfare or {}).get("shift_state") or ""
    label = _SHIFT_STATE_LABELS.get(shift)
    if label:
        return label, shift == "active"
    return "Active", True


def _team_work_label(fact_checks: int, bias_scores: int) -> str:
    """Human label for a dept-agent card's 24h task-count line.

    Replaces the old combined "N fact-check/bias · 24h" phrasing, which
    named neither task type cleanly. _newsroom_agents() already computes
    fact_checks and bias_scores as separate columns in one query — this
    was being thrown away on the way to the template (events_by_agent only
    kept the combined total). No new query; just stops discarding data
    that was already fetched.
    """
    parts = []
    if fact_checks:
        parts.append(f"{fact_checks:,} fact-check{'' if fact_checks == 1 else 's'}")
    if bias_scores:
        parts.append(f"{bias_scores:,} bias score{'' if bias_scores == 1 else 's'}")
    if not parts:
        return "no scored tasks · 24h"
    return " · ".join(parts) + " · 24h"


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


def _active_source_count(c, S, hours: int = 48) -> int:
    """Distinct sources with a VISIBLE article ingested in the last `hours` hours.

    Consolidates 14 byte-identical inline copies of this query across this file
    (#6244) — every one of them independently omitted the suppressed_reason
    filter, so a source whose only recent article was a suppressed duplicate
    refetch still counted as "active." `hours` is only ever a fixed literal
    from this file's own call sites, never user input.
    """
    return c.execute(text(f"""
        SELECT COUNT(DISTINCT s.id) FROM {S}.sources s
        JOIN {S}.articles a ON a.source_id = s.id
         AND a.ingested_at > NOW() - INTERVAL '{hours} hours'
         AND a.suppressed_reason IS NULL
    """)).scalar() or 0


# Each entry may optionally carry:
#   "weak_spot": "<short, honest sentence>" — hand-curated by Kytran, shown
#     verbatim on the agent's /team card. Absent = no weak-spot line renders
#     for that agent (never a placeholder) — add the key whenever real text
#     is ready, no other code change needed.
#   "weak_spot_href": "<path>" — optional link under the text (e.g. to a
#     page with the full detail).
# A.U.R.O.R.A. deliberately has NEITHER key here — its weak_spot is computed
# live in team() from real forecast-verification data (_aurora_team_weak_spot)
# rather than hand-written, since real, self-updating data exists for it.
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
        "weak_spot": "Coordinates coverage decisions across the team, but doesn't independently verify them — a bad call upstream (e.g. a bias score) can still propagate through to publication.",
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
        "weak_spot": "Scores each article independently — it has no memory of how it scored a similar story yesterday, so its calibration can drift over a fast-moving news cycle.",
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
        "weak_spot": "Maps each story to a single province; a story naming several provinces at once is a genuinely ambiguous case for that approach.",
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
        "weak_spot": "Threads stories together by similarity; two unrelated stories that share a name or subject can occasionally get joined as one.",
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
        "weak_spot": "Summarizes what's already reported — it doesn't source new facts, so a summary is only as complete as the article it's drawn from.",
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
        "weak_spot": "Reports what it publishes, not how it performs — reach and engagement aren't fed back into what it prioritizes next.",
    },
    {
        "name": "A.U.R.O.R.A.",
        "full": "Atmospheric & Universal Resource for Observation, Research & Analysis",
        "role": "Weather Intelligence",
        "model": "qwen2.5:7b",
        "description": "Tracks climate and severe-weather coverage across our Canadian news sources — because in Canada, the weather IS the news.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-30/7b1193b5-868.png",
        # var(--wtf-aurora) tracks style.css — was the pre-correction literal
        # #7c3aed (git history: "--wtf-aurora corrected #7c3aed -> #8b5cf6 per
        # the spec"), which never got propagated here (task #6314).
        "accent_colour": "var(--wtf-aurora)",
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
        source_count = _active_source_count(c, S)
        total_articles = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.articles WHERE suppressed_reason IS NULL")
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
# Mirrors wtf.fact_checks' fact_overall_verdict_check enum verbatim (migration
# 078) — keep both in sync if the enum ever changes.
VALID_VERDICTS = {"all", "verified", "mostly_true", "mixed", "disputed",
                   "unverifiable", "descriptive_reporting"}
VERDICT_META = [
    ("verified",              "Verified"),
    ("mostly_true",           "Mostly True"),
    ("mixed",                 "Mixed"),
    ("disputed",              "Disputed"),
    ("unverifiable",          "Unverifiable"),
    ("descriptive_reporting", "Descriptive"),
]


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
    verdict_filter = _req.args.get("verdict", "all")
    # Outlet filter (design handoff #6149 batch 11) — the source bar previously
    # linked each icon to `?band=<that outlet's own aggregate lean>`, which
    # filters by band, not by the outlet itself, so clicking (say) CBC's icon
    # surfaced every left-leaning article from ANY source rather than CBC's
    # own articles. Mirrors _archive_filters()'s `outlet` convention exactly
    # (free string, not validated against a closed set, matched via s.name —
    # parameterised below, so an unrecognised name just yields zero rows).
    outlet_filter = (_req.args.get("outlet") or "all").strip()[:80]
    if band_filter not in VALID_BANDS:
        band_filter = "all"
    if province_filter not in VALID_PROVINCES:
        province_filter = "all"
    if beat_filter not in VALID_BEATS:
        beat_filter = "all"
    if scope_filter not in VALID_SCOPES:
        scope_filter = "all"
    if verdict_filter not in VALID_VERDICTS:
        verdict_filter = "all"
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

    # Date-rail headers (design handoff #6149 phase 4 / task #16 slice 1) —
    # grouped against the SAME raw published_at values this page already
    # renders unmodified in the per-card time badge below. This app registers
    # NO custom Jinja filters (there is no |localtime here — see
    # module-capability-index.md's "Consumer pages added 2026-09-02" note),
    # so "Today"/"Yesterday" are derived in that same un-converted frame,
    # never a separately-converted one, so a rail boundary always lines up
    # with the timestamp printed on the card beside it. Computed fresh on
    # every request (cheap, no DB hit) — not cached, since "today" changes at
    # midnight regardless of the 60s article cache below.
    _now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_str = _now_utc.strftime("%Y-%m-%d")
    yesterday_str = (_now_utc - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    _ck = (band_filter, province_filter, beat_filter, scope_filter, riding_filter,
           verdict_filter, outlet_filter, page)
    _cached = _news_cache_get(_ck)
    if _cached is not None:
        (source_count, total, rows, sources, ridings, band_mix,
         band_facets, province_facets, beat_facets, scope_facets, verdict_facets,
         articles_24h, clustered_stories_24h, blindspot_flags_24h) = _cached
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return render_template("news.html", articles=rows, source_count=source_count,
                               total=total, page=page, total_pages=total_pages,
                               page_size=PAGE_SIZE, band_filter=band_filter,
                               province_filter=province_filter,
                               beat_filter=beat_filter, scope_filter=scope_filter,
                               riding_filter=riding_filter, ridings=ridings,
                               outlet_filter=outlet_filter,
                               verdict_filter=verdict_filter, verdict_meta=VERDICT_META,
                               beat_meta=BEAT_META, sources=sources,
                               band_mix=band_mix, band_facets=band_facets,
                               province_facets=province_facets, beat_facets=beat_facets,
                               scope_facets=scope_facets, verdict_facets=verdict_facets,
                               articles_24h=articles_24h,
                               clustered_stories_24h=clustered_stories_24h,
                               blindspot_flags_24h=blindspot_flags_24h,
                               today_str=today_str, yesterday_str=yesterday_str,
                               is_subscriber=is_subscriber())

    with _db().begin() as c:
        # JIT compilation alone cost 3.5s on this route's big query (its
        # correlated-subquery cost estimate keeps JIT triggered even after
        # the rewrite below). Transaction-scoped, read-only-safe. #5719
        c.execute(text("SET LOCAL jit = off"))
        source_count = _active_source_count(c, S)

        # Header stat row (design handoff #6149 phase 4 / task #16 slice 1).
        # Deliberately UNFILTERED by band/province/beat/scope/riding — these
        # are feed-health vitals, not a count of the current selection (same
        # framing as source_count above, which is likewise filter-independent).
        articles_24h = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.articles a
            WHERE a.suppressed_reason IS NULL
              AND a.published_at >= NOW() - INTERVAL '24 hours'
        """)).scalar() or 0
        clustered_stories_24h = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.story_clusters sc
            WHERE sc.article_count >= 2
              AND sc.latest_published_at >= NOW() - INTERVAL '24 hours'
        """)).scalar() or 0

        params = {}
        # Keyed by axis so a per-axis facet WHERE ("every filter except this
        # one") is a one-line dict comprehension instead of a hand-picked
        # exclusion per axis (band's earlier version only handled itself).
        filter_clauses = {}
        if band_filter != "all":
            filter_clauses["band"] = "b.band = :band"
            params["band"] = band_filter
        if province_filter != "all":
            filter_clauses["province"] = "a.province_code = :province"
            params["province"] = province_filter
        if beat_filter != "all":
            filter_clauses["beat"] = "a.beat = :beat"
            params["beat"] = beat_filter
        if scope_filter != "all":
            filter_clauses["scope"] = "a.geo_scope = :scope"
            params["scope"] = scope_filter
        if riding_filter != "all":
            filter_clauses["riding"] = (
                "EXISTS (SELECT 1 FROM wtf.article_mp_tags t"
                " JOIN parliament.mps m ON m.id = t.mp_id"
                " WHERE t.article_id = a.id AND m.riding_name = :riding)"
            )
            params["riding"] = riding_filter
        if verdict_filter != "all":
            # a.latest_verdict (migration 078) — a denormalized, indexed,
            # trigger-maintained column, NOT a per-row correlated subquery
            # against fact_checks. Filtering on verdict via the LATERAL the
            # final SELECT below uses for on-card display was measured to
            # need a 5000+ row scan for a rare verdict (mostly_true: 92 of
            # 119,574 articles) — this is a plain indexed equality, same
            # cost class as province/beat/scope.
            filter_clauses["verdict"] = "a.latest_verdict = :verdict"
            params["verdict"] = verdict_filter
        if outlet_filter != "all":
            # Same shape as province/beat/scope above — a plain indexed
            # equality against the already-joined sources table, s.name
            # exactly like _archive_where()'s outlet clause. No new join:
            # `s` is already joined into top_recent below.
            filter_clauses["outlet"] = "s.name = :outlet"
            params["outlet"] = outlet_filter

        def _where_except(*exclude_axes):
            clauses = [c for k, c in filter_clauses.items() if k not in exclude_axes]
            return ("AND " + " AND ".join(clauses)) if clauses else ""

        band_where = _where_except()  # every active filter — unchanged behaviour

        total = c.execute(text(f"""
            SELECT COUNT(*) FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL {band_where}
        """), params).scalar() or 0

        # Per-axis facet counts: each excludes ONLY its own filter, keeping
        # every other active one — so a chip shows what picking IT would
        # yield given your other selections, not what's already selected.
        # Four GROUP BY queries added here (band was first, #3106); each is
        # the same cost class as `total` above (~150-200ms measured via
        # EXPLAIN ANALYZE) and rides the same 60s _news_cache_get/set this
        # route already had — real per-second load is bounded by cache hits,
        # not by these four running on every request.
        band_facet_rows = c.execute(text(f"""
            SELECT b.band, COUNT(*) AS n
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL AND b.band IS NOT NULL {_where_except('band')}
            GROUP BY b.band
        """), params).mappings().all()
        band_facets = {r["band"]: r["n"] for r in band_facet_rows}

        # Each of these MUST join bias_scores even though it doesn't select
        # from it: _where_except() includes 'b.band = :band' whenever a band
        # filter is active (only band_facet_rows excludes it), so without
        # this join a live band filter 500s every one of these three queries
        # with "missing FROM-clause entry for table b" — caught by rendering
        # ?band=left against the real DB before shipping, not by inspection.
        province_facet_rows = c.execute(text(f"""
            SELECT a.province_code, COUNT(*) AS n
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL AND a.province_code IS NOT NULL {_where_except('province')}
            GROUP BY a.province_code
        """), params).mappings().all()
        province_facets = {r["province_code"]: r["n"] for r in province_facet_rows}

        beat_facet_rows = c.execute(text(f"""
            SELECT a.beat, COUNT(*) AS n
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL AND a.beat IS NOT NULL {_where_except('beat')}
            GROUP BY a.beat
        """), params).mappings().all()
        beat_facets = {r["beat"]: r["n"] for r in beat_facet_rows}

        scope_facet_rows = c.execute(text(f"""
            SELECT a.geo_scope, COUNT(*) AS n
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL AND a.geo_scope IS NOT NULL {_where_except('scope')}
            GROUP BY a.geo_scope
        """), params).mappings().all()
        scope_facets = {r["geo_scope"]: r["n"] for r in scope_facet_rows}

        # a.latest_verdict is the indexed column from migration 078 — same
        # cost class as the three facet queries above, not the fact_checks
        # correlated-subquery path. Still needs the bias_scores join for the
        # same reason the other three do: _where_except('verdict') carries
        # 'b.band = :band' whenever a band filter is active.
        verdict_facet_rows = c.execute(text(f"""
            SELECT a.latest_verdict, COUNT(*) AS n
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL AND a.latest_verdict IS NOT NULL {_where_except('verdict')}
            GROUP BY a.latest_verdict
        """), params).mappings().all()
        verdict_facets = {r["latest_verdict"]: r["n"] for r in verdict_facet_rows}

        # Lean-mix bar (design handoff #6149, /news Phase 3): a segmented bar +
        # named index of the CURRENT filter selection's band distribution.
        # Same WHERE-clause shape as `total` above (band_where already excludes
        # the band filter itself when band_filter=='all', and INCLUDES it when
        # set — that's fine, a mix bar under an active band filter just shows
        # one band at 100%, which is honest). One extra GROUP BY over the same
        # indexed columns `total` already scans — same cost class, not a second
        # full-table pass. Rows with no bias_scores row (band IS NULL) are
        # excluded: an unscored article is an absence, not a 'center' reading.
        band_count_rows = c.execute(text(f"""
            SELECT b.band, COUNT(*) AS n
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE 1=1 AND a.suppressed_reason IS NULL AND b.band IS NOT NULL {band_where}
            GROUP BY b.band
        """), params).mappings().all()
        _band_n = {r["band"]: r["n"] for r in band_count_rows}
        _band_scored = sum(_band_n.values())
        band_mix = [
            {"band": bk, "label": bl, "n": _band_n.get(bk, 0),
             "pct": round(100 * _band_n.get(bk, 0) / _band_scored) if _band_scored else 0}
            for bk, bl in (("left", "Left"), ("center-left", "Center-Left"),
                           ("center", "Center"), ("center-right", "Center-Right"),
                           ("right", "Right"))
        ]
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
                   sc.coverage_gap_score, sc.blindspot_side,
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
            -- s.slug feeds /static/favicons/<slug>.png in news.html. Without it the
            -- template renders /static/favicons/.png for EVERY source: 46 silent
            -- 404s, every logo falling back to its monogram, and a page that looks
            -- merely plainer rather than broken.
            SELECT s.name, s.slug, s.url, s.bias_lean,
                   obs.avg_score, obs.band AS bias_band,
                   COALESCE(ac.article_count, 0) AS article_count
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN (
                SELECT source_id, COUNT(*) AS article_count
                FROM {S}.articles WHERE suppressed_reason IS NULL GROUP BY source_id
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
    # Blindspot flags (design handoff #6149 phase 4 / task #16 slice 1) —
    # reuses the /blindspot page's OWN helper verbatim (same threshold, same
    # query shape) so the two pages can never disagree about what counts as
    # a blind spot; see _blindspot_total()'s docstring below in this file.
    # days=1 matches the "last 24h" framing of the other three stats above.
    blindspot_flags_24h = _blindspot_total(days=1)
    _news_cache_set(_ck, (source_count, total, rows, sources, ridings, band_mix,
                          band_facets, province_facets, beat_facets, scope_facets,
                          verdict_facets,
                          articles_24h, clustered_stories_24h, blindspot_flags_24h))
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render_template("news.html", articles=rows, source_count=source_count,
                           total=total, page=page, total_pages=total_pages,
                           page_size=PAGE_SIZE, band_filter=band_filter,
                           province_filter=province_filter,
                           beat_filter=beat_filter, scope_filter=scope_filter,
                           riding_filter=riding_filter, ridings=ridings,
                           outlet_filter=outlet_filter,
                           verdict_filter=verdict_filter, verdict_meta=VERDICT_META,
                           beat_meta=BEAT_META, sources=sources,
                           band_mix=band_mix, band_facets=band_facets,
                           province_facets=province_facets, beat_facets=beat_facets,
                           scope_facets=scope_facets, verdict_facets=verdict_facets,
                           articles_24h=articles_24h,
                           clustered_stories_24h=clustered_stories_24h,
                           blindspot_flags_24h=blindspot_flags_24h,
                           today_str=today_str, yesterday_str=yesterday_str,
                           is_subscriber=is_subscriber())


from .aurora_map import (  # pure, DB-free (see module docstring)
    _aurora_map_payload,
    _aurora_city_payload,
)
from .aurora_verify import (  # pure, DB-free (see module docstring)
    verification_payload as _verification_payload,
)


def _aurora_forecast_pairs(c, S):
    """Every (forecast, observed) daily-high pair we can verify — the same
    fc/ob join `weather_accuracy()` uses, factored out so `/team`'s A.U.R.O.R.A.
    weak-spot line (see team()) can feed the same real rows into
    `aurora_verify.verification_payload()` without duplicating this query."""
    return c.execute(text(f"""
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


def _aurora_weak_spot_text(summary):
    """Pure formatting, no DB — takes an aurora_verify summarise() dict and
    returns A.U.R.O.R.A.'s /team weak-spot sentence, or None.

    Uses the longest lead-time bucket's MAE, not a plain average across all
    leads — averaging in same-day forecasts would flatter the number, and
    accuracy degrading with lead time is the honest, well-understood weak
    spot of any forecaster (weather_accuracy()'s own docstring already ruled
    out inventing a causal 'why it misses' claim; this sticks to the same
    measured-number-only discipline). Returns None when there isn't enough
    data yet — never a fabricated or zero-value line."""
    mae = summary.get("longest_mae_c")
    lead = summary.get("longest_lead_days")
    if mae is None or lead is None:
        return None
    return f"Off by an average of {mae}°C at its longest forecast lead ({lead} days out)."


def _aurora_team_weak_spot(c, S):
    """DB-touching wrapper: real forecast/observed pairs -> the formatted
    sentence above, or None. See _aurora_weak_spot_text for the pure logic."""
    pairs = _aurora_forecast_pairs(c, S)
    summary = _verification_payload(pairs)["summary"]
    return _aurora_weak_spot_text(summary)


def _verify_weak_spot_text(verdict_counts):
    """Pure formatting, no DB — takes {verdict: count} and returns
    V.E.R.I.F.Y.'s /team weak-spot sentence, or None.

    Real number, not a guess: verified live 2026-09-05 at 89.1% (382,875 of
    429,804 fact-checks) — almost exactly what the design mockup GUESSED
    ("declines more claims than it checks, on purpose") without measuring
    it. No href: unlike A.U.R.O.R.A., no public page currently shows this
    aggregate verdict distribution — /claims reads claim_tracker (politician
    claim-tracking), a different table entirely, and linking there would
    point a reader at a number that isn't on the page they land on."""
    total = sum(verdict_counts.values())
    if not total:
        return None
    unverified = verdict_counts.get("unverified", 0)
    pct = round(100 * unverified / total)
    return (
        f"Declines to verify roughly {pct}% of the claims it checks — "
        "a claim without a primary document stays unverified."
    )


def _verify_team_weak_spot(c, S):
    """DB-touching wrapper: real verdict counts -> the formatted sentence
    above, or None. See _verify_weak_spot_text for the pure logic."""
    rows = c.execute(text(f"SELECT verdict, count(*) AS n FROM {S}.fact_checks GROUP BY verdict")).mappings().all()
    counts = {r["verdict"]: int(r["n"]) for r in rows if r["verdict"]}
    return _verify_weak_spot_text(counts)


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
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'climate' AND suppressed_reason IS NULL"
        )).scalar() or 0
        sci_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'science-tech' AND suppressed_reason IS NULL"
        )).scalar() or 0
        # base.html's nav renders "LIVE · {{ source_count }} SOURCES". This page
        # was a standalone document until 2026-08-18 and never supplied it, so
        # inheriting the shell without this would render "LIVE · 0 SOURCES".
        # Same definition every other page uses: distinct sources seen in 48h.
        source_count = _active_source_count(c, S)

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


@bp.get("/weather/city/<name>")
def weather_city(name: str):
    """Per-city weather detail — design-handoff/wtf-city.html, SCOPED DOWN to
    what wtf.aurora_city_obs/_city_forecast actually holds.

    ⚠️ The design mockup is NOT buildable as drawn. Its JS carries a 61-city
    fabricated dataset (hand-authored temp/wind/humidity/cloud/rain per city)
    that does not match our real 25-city MSC ingest, and a whole layer of
    sections with no backing data at all: an hourly-forecast bar chart, a
    14-day daily outlook + precipitation chart, an AQI dial, and a 30-day
    "confidence-decaying" A.U.R.O.R.A. outlook. None of that is ingested —
    wtf.aurora_city_forecast holds exactly ONE MSC citypage issue with 4
    periods (Today/Tonight/Tomorrow/Tomorrow night-shaped), not an hourly or
    14-day series. Building the mockup's version of those sections would mean
    inventing numbers, the exact failure this whole rollout exists to remove
    (see the ECCC gust-vs-absence and fire-hotspot-vs-station notes on
    /weather itself). Sun/moon times were left out too, even though they are
    real astronomy rather than fabricated data — getting sunrise/sunset math
    wrong is its own factual error, and this route ships only fields already
    proven correct by /weather's own city cards.

    What's real and shown here: current conditions (temp, condition, RH,
    wind + gust + direction, humidex, pressure, observation age/staleness)
    and the newest 4-period forecast issue — the SAME _aurora_city_payload()
    fields /weather's city grid already renders, for exactly one city.
    """
    S = _schema()
    with _db().begin() as c:
        source_count = _active_source_count(c, S)
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
        layers = c.execute(text("""
            SELECT layer_key, stale_after_hours FROM wtf.aurora_layer_status
        """)).mappings().all()

    city_payload = _aurora_city_payload(city_rows, forecast_rows)
    all_cities = city_payload["cities"]
    # Case-insensitive match on the same display_name/name_en coalesce the
    # payload builder already applies — 25 real cities, verified no two share
    # a lowercased name, so this is unambiguous.
    _want = name.strip().lower()
    city = next((c for c in all_cities if c["name"].lower() == _want), None)
    if city is None:
        abort(404)

    _city_stale_min = 180
    for _l in layers:
        if _l["layer_key"] == "city_obs" and _l["stale_after_hours"]:
            _city_stale_min = int(_l["stale_after_hours"]) * 60
            break

    return render_template(
        "weather_city.html",
        city=city,
        cities=sorted(all_cities, key=lambda c: c["name"]),
        city_stale_min=_city_stale_min,
        source_count=source_count,
        is_subscriber=is_subscriber(),
    )


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

    Batch 11 (#6254 audit) adds two more real, DB-computed panels on top of
    the same fc/ob shape, both folded onto the payload here rather than
    inside `aurora_verify` (that module is out of this batch's touch-scope):

    * A **persistence baseline** — the naive "the target day will turn out
      like the day this forecast was issued" forecast. It needs no LLM and
      no new table: it is `aurora_city_obs` joined to itself, offset by the
      SAME lead_days bucket as the real forecast above, so its dashed
      reference line lands on the real skill curve's own x-axis. Lead 0 is
      excluded on purpose — `target_day - 0 == target_day`, so a "day-0
      persistence forecast" would compare the actual high against itself
      (0.00 error, always), which is not a baseline, just an identity.
    * A **worst-call-this-month** callout — the single largest miss in the
      current calendar month, deduped to one row per (site, target_day) at
      the shortest lead we hold for that miss (the most recent, most
      informed call), so a story that missed at three lead times is not
      counted three times. No causal narrative is attached: we have no
      column that names *why* a forecast missed (see the deferred
      "where the model is weakest" panel — not buildable from this schema),
      so only the measured numbers are shown.
    """
    S = _schema()
    with _db().connect() as c:
        pairs = _aurora_forecast_pairs(c, S)

        persistence_rows = c.execute(text(f"""
            WITH ob AS (
                SELECT site_code,
                       (observed_utc AT TIME ZONE 'UTC')::date AS obs_day,
                       max(temp_c) AS observed_c
                  FROM {S}.aurora_city_obs
                 WHERE temp_c IS NOT NULL
                 GROUP BY 1, 2
            ),
            fc_days AS (
                SELECT DISTINCT site_code,
                       (period_index / 2) AS lead_days,
                       ((issued_utc AT TIME ZONE 'UTC')::date
                        + (period_index / 2)) AS target_day
                  FROM {S}.aurora_city_forecast
                 WHERE temp_high_c IS NOT NULL
                   AND period_index % 2 = 0
                   AND (period_index / 2) >= 1
            )
            SELECT fd.lead_days,
                   issued_ob.observed_c AS persistence_c,
                   target_ob.observed_c AS observed_c
              FROM fc_days fd
              JOIN ob issued_ob ON issued_ob.site_code = fd.site_code
                               AND issued_ob.obs_day = fd.target_day - fd.lead_days
              JOIN ob target_ob ON target_ob.site_code = fd.site_code
                               AND target_ob.obs_day = fd.target_day
             WHERE fd.target_day < CURRENT_DATE
        """)).mappings().all()

        worst_row = c.execute(text(f"""
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
                       max(temp_c) AS observed_c
                  FROM {S}.aurora_city_obs
                 WHERE temp_c IS NOT NULL
                 GROUP BY 1, 2
            ),
            deduped AS (
                SELECT DISTINCT ON (fc.site_code, fc.target_day)
                       fc.site_code, fc.lead_days, fc.forecast_c,
                       ob.observed_c, fc.target_day
                  FROM fc
                  JOIN ob ON ob.site_code = fc.site_code AND ob.obs_day = fc.target_day
                 WHERE fc.target_day < CURRENT_DATE
                   AND fc.target_day >= date_trunc('month', CURRENT_DATE)
                 ORDER BY fc.site_code, fc.target_day, fc.lead_days ASC
            )
            SELECT d.lead_days, d.forecast_c, d.observed_c, d.target_day,
                   COALESCE(s.display_name, s.name_en) AS city,
                   s.source_prov AS province,
                   abs(d.forecast_c - d.observed_c) AS miss_c
              FROM deduped d
              LEFT JOIN {S}.aurora_city_site s ON s.site_code = d.site_code
             ORDER BY miss_c DESC
             LIMIT 1
        """)).mappings().first()

    payload = _verification_payload([dict(r) for r in pairs])

    # Same aggregation shape aurora_verify.skill_curve uses (n / bias / mae),
    # kept local to this route rather than imported — aurora_verify is
    # outside this batch's touch-scope and the arithmetic is a few lines.
    _PERSIST_MIN_PAIRS = 30  # mirrors aurora_verify.MIN_PAIRS_FOR_CONFIDENCE
    _by_lead: dict[int, list] = {}
    for r in persistence_rows:
        f, o = r["persistence_c"], r["observed_c"]
        if f is None or o is None:
            continue
        _by_lead.setdefault(int(r["lead_days"]), []).append((f, o))
    persistence_curve = {}
    for lead, vals in _by_lead.items():
        n = len(vals)
        if n == 0:
            continue
        bias = sum(f - o for f, o in vals) / n
        mae = sum(abs(f - o) for f, o in vals) / n
        persistence_curve[lead] = {
            "pairs": n,
            "bias_c": round(bias, 2),
            "mae_c": round(mae, 2),
            "thin": n < _PERSIST_MIN_PAIRS,
        }
    payload["persistence_curve"] = persistence_curve

    _model_maes = [pt["mae_c"] for pt in payload["skill_curve"] if pt["mae_c"] is not None]
    _persist_maes = [v["mae_c"] for v in persistence_curve.values()]
    _all_maes = _model_maes + _persist_maes
    payload["chart_max_mae"] = max(_all_maes) if _all_maes else None

    worst_miss = None
    if worst_row is not None and worst_row["forecast_c"] is not None:
        worst_miss = dict(worst_row)
    payload["worst_miss"] = worst_miss

    # Batch 11 (#6254 audit), continued — two more pieces computed locally
    # from `pairs` (still never inside aurora_verify, per the module-scope
    # note above): the share of forecasts landing within 3°C — the mockup's
    # "share of days within N degrees" framing — and the lead time (if any)
    # where the naive persistence guess stops losing to our forecast. Both
    # are plain aggregation over rows already fetched; no new query.
    _WITHIN_C = 3.0

    def _pct_within(lead_days):
        vals = [
            abs(r["forecast_c"] - r["observed_c"])
            for r in pairs
            if r.get("lead_days") == lead_days
            and r.get("forecast_c") is not None
            and r.get("observed_c") is not None
        ]
        if not vals:
            return None
        return round(100.0 * sum(1 for v in vals if v <= _WITHIN_C) / len(vals))

    payload["summary"]["same_day_within3_pct"] = _pct_within(0)
    _longest_lead = payload["summary"]["longest_lead_days"]
    payload["summary"]["longest_within3_pct"] = (
        _pct_within(_longest_lead) if _longest_lead is not None else None
    )

    # First lead time (ascending) at which persistence's MAE is no longer
    # worse than ours. None means our forecast still beats persistence at
    # every lead we currently hold — an honest "not yet", never a fabricated
    # day (our data only spans a handful of lead days so far; see the route
    # docstring above).
    _catchup_lead = None
    for _pt in payload["skill_curve"]:
        _p = persistence_curve.get(_pt["lead_days"])
        if (_p and _pt["mae_c"] is not None and _p["mae_c"] is not None
                and _pt["mae_c"] >= _p["mae_c"]):
            _catchup_lead = _pt["lead_days"]
            break
    payload["summary"]["persistence_catchup_lead"] = _catchup_lead

    # Per-city share within 3°C, over the same 1-5 day lead-time band
    # `aurora_verify.city_scoreboard` already uses for the miss/direction
    # columns, so the new figure lines up with what is already on screen.
    _city_within_hits: dict = {}
    for r in pairs:
        lead, f, o, site = (r.get("lead_days"), r.get("forecast_c"),
                             r.get("observed_c"), r.get("site_code"))
        if lead is None or f is None or o is None or not site:
            continue
        if not (1 <= int(lead) <= 5):
            continue
        _city_within_hits.setdefault(site, []).append(abs(f - o) <= _WITHIN_C)
    for _city in payload["cities"]:
        _hits = _city_within_hits.get(_city.get("site_code"))
        _city["within3_pct"] = (
            round(100.0 * sum(_hits) / len(_hits)) if _hits else None
        )

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
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'economy' AND suppressed_reason IS NULL"
        )).scalar() or 0
        business_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'business' AND suppressed_reason IS NULL"
        )).scalar() or 0
        foreign_count = c.execute(text(
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'foreign-policy' AND suppressed_reason IS NULL"
        )).scalar() or 0

        # Six real, ingested economic indicators (#6272 Batch 9 + Batch 12
        # #6523). Each block has its own try/except — one table being
        # briefly unreachable degrades that one card, never the whole page
        # (the original single-indicator version already worked this way).
        # No hardcoded/sample numbers anywhere below — every value, chart
        # point and delta comes from a live query. See
        # design-handoff/wtf-economy.html's IND array for the layout this
        # replaces (that array is a hardcoded JS const, never a fetch).
        indicators = []

        try:
            boc_rows = [dict(r) for r in c.execute(text("""
                SELECT decision_date AS ref_date, rate_pct AS value
                FROM market_watch.boc_rate_decisions
                ORDER BY decision_date DESC LIMIT 25
            """)).mappings().all()]
            boc_rows.reverse()
            if boc_rows:
                series = [(r["ref_date"], r["value"]) for r in boc_rows]
                indicators.append(_econ_indicator(
                    key="overnight_rate", name="Overnight rate target",
                    value=boc_rows[-1]["value"], unit="%",
                    source="BoC Valet V122514", href="/rates", series=series,
                ))
        except Exception:
            pass

        try:
            fx_rows = [dict(r) for r in c.execute(text("""
                SELECT DISTINCT ON (date_trunc('month', rate_date)::date)
                       rate_date AS ref_date, usd_cad AS value
                FROM market_watch.fx_rates
                ORDER BY date_trunc('month', rate_date)::date, rate_date DESC
            """)).mappings().all()]
            fx_rows.sort(key=lambda r: r["ref_date"])
            fx_rows = fx_rows[-25:]
            if fx_rows:
                series = [(r["ref_date"], r["value"]) for r in fx_rows]
                indicators.append(_econ_indicator(
                    key="cad_usd", name="CAD per USD",
                    value=fx_rows[-1]["value"], unit="", decimals=4,
                    source="BoC Valet FXUSDCAD", href=None, series=series,
                ))
        except Exception:
            pass

        try:
            ind_rows = c.execute(text("""
                SELECT indicator_key, ref_date, value
                FROM market_watch.economic_indicators
                ORDER BY indicator_key, ref_date
            """)).mappings().all()
            by_key = {}
            for r in ind_rows:
                by_key.setdefault(r["indicator_key"], []).append(dict(r))

            if by_key.get("cpi_index"):
                yoy = _econ_cpi_yoy(by_key["cpi_index"])[-24:]
                if yoy:
                    indicators.append(_econ_indicator(
                        key="cpi_yoy", name="CPI, year over year",
                        value=yoy[-1][1], unit="%",
                        source="StatCan 18-10-0004-01", href=None, series=yoy,
                    ))

            if by_key.get("unemployment_rate"):
                u_rows = by_key["unemployment_rate"][-25:]
                indicators.append(_econ_indicator(
                    key="unemployment_rate", name="Unemployment rate",
                    value=u_rows[-1]["value"], unit="%",
                    source="StatCan 14-10-0287-01 (LFS)", href=None,
                    series=[(r["ref_date"], r["value"]) for r in u_rows],
                ))

            if by_key.get("gdp_level"):
                mom = _econ_gdp_mom(by_key["gdp_level"])[-24:]
                if mom:
                    indicators.append(_econ_indicator(
                        key="gdp_mom", name="Real GDP, monthly change",
                        value=mom[-1][1], unit="%", signed=True,
                        source="StatCan 36-10-0434-01", href=None, series=mom,
                    ))

            if by_key.get("housing_starts_saar"):
                h_rows = by_key["housing_starts_saar"][-25:]
                indicators.append(_econ_indicator(
                    key="housing_starts_saar", name="Housing starts, SAAR (000s)",
                    value=h_rows[-1]["value"], unit="", decimals=0,
                    source="StatCan 34-10-0158-01 (CMHC starts)", href=None,
                    series=[(r["ref_date"], r["value"]) for r in h_rows],
                ))
        except Exception:
            pass

    return render_template("economy.html",
                           articles=rows,
                           economy_count=economy_count,
                           business_count=business_count,
                           foreign_count=foreign_count,
                           indicators=indicators,
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
            f"SELECT COUNT(*) FROM {S}.articles WHERE beat = 'municipal' AND suppressed_reason IS NULL"
        )).scalar() or 0

        # City facets — only cities with real coverage (>=2) to keep the
        # filter honest while municipal geo-tagging is still expanding.
        cities = c.execute(text(f"""
            SELECT a.city, COUNT(*) AS n
            FROM {S}.articles a
            WHERE a.beat = 'municipal' AND a.city IS NOT NULL AND a.city <> ''
              AND a.suppressed_reason IS NULL
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
# Keys the /activity template renders and therefore the MINIMUM a stored
# snapshot must carry. A snapshot written by an older build is fresh and
# well-formed while missing whatever that build did not produce, and there is no
# version stamp to tell them apart — so the reader is given this list and treats
# a short snapshot as stale (KB #302073).
#
# ⚠️ ADD A KEY TO THE BUNDLE BELOW, ADD IT HERE. `test_activity_snapshot_version`
# derives the builder's real key set from this file's source and fails if the two
# drift, so this cannot quietly fall behind the way the snapshot itself did.
_ACTIVITY_SNAPSHOT_REQUIRED_KEYS = (
    "source_count", "stats", "trends", "beat_breakdown", "top_stories",
    "throughput_sparkline", "bias_spectrum", "llm_rate", "geo_rate",
    "sparklines", "source_health", "newsroom", "agent_throughput",
)

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
                  FROM {S}.fact_checks fc
                 WHERE checked_at > NOW() - INTERVAL '24 hours'
                   AND EXISTS (SELECT 1 FROM {S}.articles a
                                WHERE a.id = fc.article_id AND a.suppressed_reason IS NULL)
                 GROUP BY 1
                UNION ALL
                SELECT COALESCE(agent_name, ''), 'bias', COUNT(*)
                  FROM {S}.bias_scores bs
                 WHERE computed_at > NOW() - INTERVAL '24 hours'
                   AND EXISTS (SELECT 1 FROM {S}.articles a
                                WHERE a.id = bs.article_id AND a.suppressed_reason IS NULL)
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


# Per-agent throughput sources. Each agent's work is evidenced by rows landing
# in one table with one timestamp — the SAME tables the event feed unions in
# _activity_agent_queries, so the cards and the log can never disagree.
#
# ⚠️ WHY A RATE AND NOT A COUNT. `geo_processed_at` was added today (migration
# 073) and is deliberately not backfilled, so L.O.C.A.L. had 509 rows in a
# window advertised as 24h while the column itself was 4.7h old. Rendered beside
# V.E.R.I.F.Y.'s 8,133 that reads as "L.O.C.A.L. is 16x slower", which is false
# — it is the newest column, not the slowest agent. Counts over unequal windows
# are not comparable; a rate is. Each agent therefore carries the window it was
# actually measured over, and the window is shown.
#
# The window self-heals: once a column is older than 24h, GREATEST() pins the
# start at the 24h boundary, `partial` goes False and the caveat disappears
# without anyone editing this.
_AGENT_SOURCES = (
    ("F.A.C.T.", "audit_trail", "created_at", "verdicts recorded"),
    ("V.E.R.I.F.Y.", "fact_checks", "checked_at", "claims checked"),
    ("B.I.A.S.", "bias_scores", "computed_at", "articles scored"),
    ("D.R.A.F.T.", "summaries", "created_at", "summaries written"),
    ("I.N.K.", "articles", "ingested_at", "articles ingested"),
    ("L.O.C.A.L.", "articles", "geo_processed_at", "articles placed"),
)


def _activity_agent_throughput(S):
    """Per-agent throughput over the last 24h, honest about short windows.

    Returns a list of dicts sorted by rate: name, what, events, window_hours,
    per_hour, last_at, partial.

    Deliberately NOT reported: model name, average duration and a target.
    Those live in the hub's `task_execution_log` (a different database), and a
    target is a policy choice nobody has made — the design prototype carries all
    three as sample constants. Inventing them here would put fabricated figures
    on the page whose entire subject is how honestly this newsroom reports
    itself.
    """
    parts = []
    for name, table, col, what in _AGENT_SOURCES:
        parts.append(
            f"""SELECT '{name}' AS name, '{what}' AS what,
                   count(*) FILTER (WHERE {col} > now() - interval '24 hours') AS events,
                   GREATEST(now() - interval '24 hours', min({col})) AS win_start,
                   max({col}) AS last_at,
                   (min({col}) > now() - interval '24 hours') AS partial
              FROM {S}.{table}"""
        )
    sql = " UNION ALL ".join(f"({p})" for p in parts)

    out = []
    with _db().begin() as c:
        for r in c.execute(text(sql)).mappings():
            win_start, events = r["win_start"], int(r["events"] or 0)
            hours = 0.0
            if win_start is not None:
                # `import datetime` at module scope is the MODULE — `timezone` is
                # not a module-level name here, so the qualified form is required.
                _now = datetime.datetime.now(datetime.timezone.utc)
                hours = max(0.0, (_now - win_start).total_seconds() / 3600.0)
            # Under ~6 minutes of coverage a rate is noise, not a measurement.
            per_hour = round(events / hours, 1) if hours >= 0.1 else None
            out.append(
                {
                    "name": r["name"],
                    "what": r["what"],
                    "events": events,
                    "window_hours": round(hours, 1),
                    "per_hour": per_hour,
                    "last_at": r["last_at"],
                    "partial": bool(r["partial"]) and hours < 23.5,
                }
            )
    out.sort(key=lambda a: (a["per_hour"] is None, -(a["per_hour"] or 0)))
    return out


def _activity_bundle(S, force: bool = False):
    """Everything on /activity except the paginated event feed — one shared
    snapshot cached _ACTIVITY_CACHE_TTL seconds."""
    if not force:
        ent = _ACTIVITY_CACHE.get("bundle")
        if ent and ent[0] > time.time():
            return ent[1]

        # SHARED snapshot (migration 072). The in-process dict above is per
        # gunicorn worker — with --workers 4 that is four caches, and
        # --max-requests recycles workers back to empty, so the ~10s compute
        # recurred forever instead of warming once. Reading a row that another
        # process computed makes worker count and recycling irrelevant.
        # Fail-soft: any problem here falls through to the inline compute below,
        # which is exactly the behaviour that shipped before this existed.
        try:
            from . import activity_snapshot as _snap
            with _db().begin() as _c:
                _hit = _snap.read_snapshot(
                    _c, require_keys=_ACTIVITY_SNAPSHOT_REQUIRED_KEYS)
        except Exception:
            _hit = None
        if _hit:
            _B, _at = _hit
            _B = dict(_B)
            _B["computed_at"] = _at
            _ACTIVITY_CACHE["bundle"] = (time.time() + _ACTIVITY_CACHE_TTL, _B)
            return _B

    _started = time.time()
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
        source_count = _active_source_count(c, S)
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
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested') AS fact_ingested,
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested' AND created_at > NOW() - INTERVAL '24 hours') AS articles_24h,
              (SELECT COUNT(*) FROM {S}.bias_scores bs24
                 JOIN {S}.articles a ON a.id = bs24.article_id
                WHERE bs24.computed_at > NOW() - INTERVAL '24 hours'
                  AND a.suppressed_reason IS NULL) AS bias_24h,
              (SELECT COUNT(DISTINCT fc24.article_id) FROM {S}.fact_checks fc24
                 JOIN {S}.articles a ON a.id = fc24.article_id
                WHERE fc24.checked_at > NOW() - INTERVAL '24 hours'
                  AND a.suppressed_reason IS NULL) AS verify_24h,
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
              (SELECT COUNT(*) FROM {S}.articles WHERE analysis_tier IN ('quick_v1_failed', 'quick_v1_failed+full', 'quick_v1+failed')
                 AND suppressed_reason IS NULL) AS tier_quick_v1_failed,
              (SELECT COUNT(*) FROM {S}.articles WHERE tier2_pending=true
                 AND suppressed_reason IS NULL) AS tier2_pending_count,
              (SELECT COUNT(DISTINCT fct.article_id) FROM {S}.fact_checks fct
                 JOIN {S}.articles a ON a.id = fct.article_id
                WHERE a.suppressed_reason IS NULL) AS verify_total,
              -- ⚠️ geo_mapped is intentionally defined ONCE, here — an identically-named
              -- second definition further down this SELECT (narrower: province_code only,
              -- no suppressed_reason filter) silently shadowed this one; removed as part
              -- of #6244 rather than left as dead, inconsistent duplicate SQL.
              (SELECT COUNT(*) FROM {S}.articles WHERE (province_code IS NOT NULL OR country_code IS NOT NULL)
                 AND suppressed_reason IS NULL) AS geo_mapped,
              -- Pipeline health counters (#2955) — surfaces skipped/backlog
              -- alongside the done/failed split workers already log to stdout.
              (SELECT COUNT(*) FROM {S}.failed_ingest
                 WHERE created_at > NOW() - INTERVAL '24 hours') AS failed_ingest_24h,
              (SELECT COUNT(*) FROM {S}.failed_ingest) AS failed_ingest_total,
              (SELECT COUNT(*) FROM {S}.articles
                 WHERE province_code IS NULL AND geo_scope != 'unmappable'
                   AND suppressed_reason IS NULL) AS geo_pending,
              (SELECT COUNT(*) FROM {S}.articles WHERE NOT ai_analyzed
                 AND suppressed_reason IS NULL) AS llm_pending,
              (SELECT COUNT(*) FROM {S}.scout_body_jobs WHERE status='failed') AS scout_body_failed,
              (SELECT COUNT(*) FROM {S}.scout_body_jobs
                 WHERE status='completed' AND completed_at > NOW() - INTERVAL '24 hours') AS scout_body_done_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE geo_scope = 'unmappable'
                 AND suppressed_reason IS NULL) AS geo_unmappable,
              (SELECT COUNT(*) FROM {S}.articles
                 WHERE geo_scope = 'unmappable' AND published_at > NOW() - INTERVAL '24 hours'
                   AND suppressed_reason IS NULL) AS geo_unmappable_24h,
              (SELECT COUNT(*) FROM {S}.articles WHERE bias_v2_score IS NOT NULL
                 AND suppressed_reason IS NULL) AS bias_v2_scored,
              (SELECT COUNT(*) FROM {S}.articles WHERE tier2_failures > 0
                 AND suppressed_reason IS NULL) AS tier2_failed,
              -- 24h trend: yesterday window (24-48h ago) for delta calculation
              (SELECT COUNT(*) FROM {S}.audit_trail WHERE event_type='ingested' AND created_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours') AS articles_yesterday,
              -- Must share bias_24h/verify_24h's suppressed_reason filter above, or the
              -- trend %% compares a filtered count to an unfiltered one (#6244).
              (SELECT COUNT(*) FROM {S}.bias_scores bsy
                 JOIN {S}.articles a ON a.id = bsy.article_id
                WHERE bsy.computed_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours'
                  AND a.suppressed_reason IS NULL) AS bias_yesterday,
              (SELECT COUNT(DISTINCT fcy.article_id) FROM {S}.fact_checks fcy
                 JOIN {S}.articles a ON a.id = fcy.article_id
                WHERE fcy.checked_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours'
                  AND a.suppressed_reason IS NULL) AS verify_yesterday
        """)).mappings().first()

        # --- Extra analytics queries (activity page enrichments) ---
        beat_breakdown, top_stories, throughput_sparkline, bias_spectrum = [], [], [], []
        # geo_rate defaults to None, NOT 0.0 — "we cannot measure this" is not the
        # same claim as "the rate is zero", and on a transparency page the
        # difference matters. There is no correct query to substitute: geo_scope
        # is a CATEGORY, not the confidence number geo_hr was written against, so
        # what this should measure is a product decision, tracked as #6263.
        # Downstream must treat None as unknown (see the geo_days_left guard).
        llm_rate, geo_rate = 0.0, None
        c.execute(text("SAVEPOINT extra_analytics"))
        try:
            beat_rows = c.execute(text(f"""
                SELECT COALESCE(beat,'unknown') AS beat, COUNT(*) AS cnt
                FROM {S}.articles WHERE beat IS NOT NULL AND beat != ''
                  AND suppressed_reason IS NULL
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
                  AND a.suppressed_reason IS NULL
                  AND sc.representative_title IS NOT NULL
                GROUP BY sc.id, sc.representative_title
                ORDER BY article_count DESC, outlet_count DESC LIMIT 5
            """)).mappings().all()
            top_stories = [{"headline": r["headline"][:80], "articles": int(r["article_count"]),
                            "outlets": int(r["outlet_count"]), "id": r["cluster_id"]} for r in top_story_rows]

            sparkline_rows = c.execute(text(f"""
                SELECT date_trunc('hour', la.completed_at) -
                       MOD(EXTRACT(HOUR FROM la.completed_at)::int, 2) * INTERVAL '1 hour' AS bucket,
                       COUNT(*) AS cnt
                FROM {S}.llm_analyses la
                JOIN {S}.articles a ON a.id = la.article_id
                WHERE la.completed_at > NOW() - INTERVAL '24 hours'
                  AND a.suppressed_reason IS NULL
                GROUP BY bucket ORDER BY bucket
            """)).mappings().all()
            throughput_sparkline = [{"t": r["bucket"].isoformat(), "cnt": int(r["cnt"])} for r in sparkline_rows]

            bias_spectrum_rows = c.execute(text(f"""
                SELECT COALESCE(bias_lean, 'unknown') AS lean, COUNT(*) AS cnt
                FROM {S}.sources
                GROUP BY lean ORDER BY cnt DESC
            """)).mappings().all()
            bias_spectrum = [{"lean": r["lean"], "cnt": int(r["cnt"])} for r in bias_spectrum_rows]

            # ⚠️ llm_hr and geo_hr were ONE statement. geo_hr references
            # `articles.geo_confidence`, a column that DOES NOT EXIST (the table
            # has only geo_scope), so the whole statement raised, the except
            # below swallowed it, and BOTH rates stayed at their 0.0 defaults.
            # llm_rate was collateral damage from geo_rate's bad column — it has
            # been reading 0/hr on the live page, not because the LLM stopped but
            # because its neighbour could not compile. Splitting them means one
            # broken metric can no longer zero a working one. (#6263)
            llm_rate = float(c.execute(text(f"""
                SELECT COUNT(*) / 6.0 AS llm_hr
                FROM {S}.llm_analyses la
                JOIN {S}.articles a ON a.id = la.article_id
                WHERE la.completed_at > NOW() - INTERVAL '6 hours'
                  AND a.suppressed_reason IS NULL
            """)).scalar() or 0)
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
                SELECT bs.computed_at::date AS d, COUNT(*) FROM {S}.bias_scores bs
                JOIN {S}.articles a ON a.id = bs.article_id
                WHERE bs.computed_at > CURRENT_DATE - INTERVAL '7 days'
                  AND a.suppressed_reason IS NULL
                GROUP BY 1
            """),
            "V.E.R.I.F.Y.": _daily(f"""
                SELECT fc.checked_at::date AS d, COUNT(DISTINCT fc.article_id) FROM {S}.fact_checks fc
                JOIN {S}.articles a ON a.id = fc.article_id
                WHERE fc.checked_at > CURRENT_DATE - INTERVAL '7 days'
                  AND a.suppressed_reason IS NULL
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
                  AND suppressed_reason IS NULL
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
            LEFT JOIN {S}.articles a ON a.source_id = s.id AND a.suppressed_reason IS NULL
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
    # ⚠️ MUST be set BEFORE write_snapshot below, not after.
    # Most requests are served from the stored snapshot, not from this compute —
    # a key added after the write is persisted by nobody, so the panel renders
    # its empty state forever while the code that fills it looks correct. That is
    # exactly what happened on the first attempt here.
    # Failure is non-fatal: the cards disappear, the rest of the page still
    # renders. (`write_snapshot` uses json.dumps(default=str), so the datetime in
    # `last_at` cannot abort the write.)
    try:
        B["agent_throughput"] = _activity_agent_throughput(S)
    except Exception:
        logger.exception("activity: agent throughput failed")
        B["agent_throughput"] = []
    # Publish for every OTHER worker (and for workers not yet born — a recycled
    # one starts with an empty dict but a populated table). Best-effort: a failed
    # write costs the next reader a recompute, nothing more.
    _dur = int((time.time() - _started) * 1000)
    try:
        from . import activity_snapshot as _snap
        with _db().begin() as _c:
            _snap.write_snapshot(_c, B, _dur)
    except Exception:
        pass
    # Stamped AFTER the write so the page can say "as of HH:MM" honestly. A
    # transparency page should state its staleness rather than imply live.
    # NB: this module does `import datetime` (the MODULE), so `datetime.now()`
    # is a NameError here. Same local-alias style as elsewhere in this file.
    from datetime import datetime as _dt, timezone as _tz
    B["computed_at"] = _dt.now(_tz.utc)
    _ACTIVITY_CACHE["bundle"] = (time.time() + _ACTIVITY_CACHE_TTL, B)
    return B


@bp.post("/api/internal/activity-snapshot/refresh")
def refresh_activity_snapshot():
    """Recompute the /activity bundle off the request path and publish it.

    Called once per ingest cycle. Intended to run on wtf-ingest-api, NOT on the
    public wtf-consumer workers — same reasoning as the entity-graph ingest
    endpoint (incident KB #273424): a multi-second job on a public worker starves
    real page loads. The job TRIGGERS the compute rather than containing it, so
    the ~260 lines of bundle SQL stay in one place instead of being duplicated
    into the ingest image.

    Auth mirrors ingest_entity_graph(): a missing key is 503 (misconfigured, not
    open), a wrong key is 401. Never expose this without the key — it is a
    deliberate several-second CPU/DB burn and would be a free DoS lever.
    """
    import os as _os
    from flask import request as _req, jsonify as _jsonify

    expected = _os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        return _jsonify({"error": "internal key not configured"}), 503
    if _req.headers.get("X-Internal-Key", "") != expected:
        return _jsonify({"error": "unauthorized"}), 401

    started = time.time()
    try:
        # force=True bypasses BOTH caches: the point of a refresh is to do the
        # expensive work, so honouring a cache here would make the endpoint a
        # no-op that still reports success.
        B = _activity_bundle(_schema(), force=True)
    except Exception as exc:
        logging.getLogger(__name__).exception("activity snapshot refresh failed")
        return _jsonify({"ok": False, "error": str(exc)[:200]}), 500

    return _jsonify({
        "ok": True,
        "duration_ms": int((time.time() - started) * 1000),
        "computed_at": str(B.get("computed_at")),
        # Echoed so a caller can spot a bundle that succeeded but came back
        # empty — "it returned 200" is not the same as "it computed something".
        "stats_fields": len(B.get("stats") or {}),
    })


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
    # `geo_rate > 0` would raise TypeError now that geo_rate can be None
    # (unknown). Truthiness covers both None and 0.0 — neither can divide.
    geo_days_left = round(geo_pending_count / (geo_rate * 24), 1) if geo_rate else None
    llm_hours_left = round(llm_pending_count / llm_rate, 1) if llm_rate and llm_rate > 0 else None

    creed_scan = _fetch_creed_scan()

    # "as of H:MM AM/PM EDT" for the stats bar. The bundle is precomputed off the
    # request path (migration 072), so it can be up to ~30 min old — a
    # TRANSPARENCY page states its staleness rather than implying live. The
    # counts themselves are still EXACT; only their age is approximate.
    #
    # Formatted HERE, the single point of use, because BOTH bundle paths (a
    # snapshot read and a fresh compute) set `computed_at`; formatting at each
    # write site would be two copies to drift apart.
    #
    # The consumer has NO timezone layer — every other template does a raw
    # .strftime() on whatever the DB returned — so this converts explicitly
    # rather than rendering a UTC clock that reads 4 hours wrong to a Canadian
    # audience. %Z prints EDT/EST, so the reader never has to guess.
    stats_as_of = None
    _ca = B.get("computed_at")
    if _ca is not None:
        try:
            from zoneinfo import ZoneInfo
            stats_as_of = _ca.astimezone(
                ZoneInfo("America/Toronto")).strftime("%-I:%M %p %Z")
        except Exception:
            # Deliberately renders NO label rather than a wrong one: making no
            # claim about freshness is honest, stating the wrong time is not.
            stats_as_of = None

    return render_template("activity.html", events=events,
                           stats_as_of=stats_as_of,
                           source_count=B["source_count"],
                           total=total, page=page, total_pages=total_pages,
                           page_size=PAGE_SIZE, agent_filter=agent_filter,
                           stats=stats, source_health=B["source_health"],
                           # ⚠️ MUST be passed explicitly — this route enumerates
                           # its context keys, so a bundle key that is not listed
                           # here renders the panel's EMPTY state, which reads as
                           # "no agents did any work" rather than "not wired".
                           newsroom=B.get("newsroom") or {},
                           agent_throughput=B.get("agent_throughput") or [],
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
        source_count = _active_source_count(c, S)
        # A.U.R.O.R.A. is the one named agent with a real, already-tracked
        # weakness metric (the SAME forecast-verification /weather/accuracy
        # publishes) — see _aurora_team_weak_spot. Best-effort: a query hiccup
        # here must not take down the whole team page, same principle as
        # every other try/except on this route.
        try:
            aurora_weak_spot = _aurora_team_weak_spot(c, S)
        except Exception:
            aurora_weak_spot = None
        # V.E.R.I.F.Y. is the other named agent with a real, already-stored
        # weakness signal — its own verdict distribution (see
        # _verify_team_weak_spot). Same best-effort principle.
        try:
            verify_weak_spot = _verify_team_weak_spot(c, S)
        except Exception:
            verify_weak_spot = None
    portrait_lookup = _get_portrait_lookup()
    welfare_lookup = _get_welfare_lookup()
    agents = []
    for agent in TEAM_AGENTS:
        a = dict(agent)
        live_url = portrait_lookup.get(agent["name"])
        if live_url:
            a["portrait_url"] = live_url
        a["welfare"] = welfare_lookup.get(agent["name"])  # None if unavailable
        a["status_label"], a["status_is_active"] = _team_badge(a["welfare"])
        # The remaining named agents' weak_spot (if any) is hand-curated
        # text already sitting on their TEAM_AGENTS entry — see the dict
        # above. A.U.R.O.R.A. and V.E.R.I.F.Y. are the two computed live;
        # neither has a static "weak_spot" key in TEAM_AGENTS on purpose.
        if a["name"] == "A.U.R.O.R.A." and aurora_weak_spot:
            a["weak_spot"] = aurora_weak_spot
            a["weak_spot_href"] = "/weather/accuracy"
        elif a["name"] == "V.E.R.I.F.Y." and verify_weak_spot:
            a["weak_spot"] = verify_weak_spot
            # No href: unlike /weather/accuracy, no public page currently
            # shows this aggregate verdict distribution (see
            # _verify_weak_spot_text's docstring).
        agents.append(a)

    # ── "the rest of the department" + "who actually did the work" ──
    # design-handoff/wtf-team.html's #tm-dept and #tm-roster sections. Both
    # read from data that already exists: _get_welfare_lookup() (this file,
    # ~L204) already fetches the FULL live News & Media roster from the hub
    # (not just the 8 named agents), and _newsroom_agents() (~L1148) already
    # computes fact-check/bias-score attribution for the last 24h — it was
    # built for the Activity Log and reused here rather than re-queried.
    #
    # Deliberately NOT shown: a per-agent "title" (e.g. "Fact-check
    # specialist"). The hub's fleet-agents payload carries no such field
    # (verified live — display_name/department/shift_state/welfare metrics
    # only), and the design's own comment on this section says "nothing here
    # is invented to fill a gap." Real 24h task counts stand in instead.
    named_names = {a["name"] for a in TEAM_AGENTS}
    try:
        newsroom = _newsroom_agents(S)
    except Exception:
        newsroom = {"agents": [], "unattributed": 0, "attributed": 0}
    # _newsroom_agents() already computes fact_checks/bias_scores as separate
    # columns in one query — keep the split instead of collapsing to a single
    # combined total (that used to feed a vague "N fact-check/bias" label
    # that named neither task type cleanly; see _team_work_label).
    events_by_agent = {
        a["agent"]: {
            "events": int(a["events"]),
            "fact_checks": int(a["fact_checks"]),
            "bias_scores": int(a["bias_scores"]),
        }
        for a in newsroom["agents"]
    }

    dept_agents = []
    for name, w in welfare_lookup.items():
        if name in named_names:
            continue
        ev = events_by_agent.get(name, {"events": 0, "fact_checks": 0, "bias_scores": 0})
        dept_agents.append({
            "name": name,
            "shift_state": (w or {}).get("shift_state") or "",
            "events_24h": ev["events"],
            "work_label": _team_work_label(ev["fact_checks"], ev["bias_scores"]),
        })
    dept_agents.sort(key=lambda a: a["events_24h"], reverse=True)

    roster_rows = [
        {"label": a["agent"], "value": int(a["events"])}
        for a in newsroom["agents"]
    ]
    if newsroom["unattributed"]:
        roster_rows.append({"label": "unattributed", "value": int(newsroom["unattributed"])})

    # dept_total=None (not 0) when the hub roster is genuinely unknown — on a
    # cold cache right after a container restart, _get_welfare_lookup()'s
    # stale-while-revalidate returns {} for the FIRST request before its
    # background refresh lands (observed live: /team's first hit after
    # deploy briefly said "News & Media has 0 agents", a confident false
    # claim, before self-correcting on the very next request). 0 must mean
    # "confirmed empty," never "haven't heard back yet" — the same rule the
    # welfare pill above already follows by omitting itself rather than
    # rendering a fabricated score.
    dept_total = len(welfare_lookup) if welfare_lookup else None

    return render_template(
        "team.html",
        agents=agents,
        source_count=source_count,
        dept_agents=dept_agents,
        roster_rows=roster_rows,
        dept_total=dept_total,
        named_count=len(TEAM_AGENTS),
    )


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
        source_count = _active_source_count(c, S)
    return render_template("cost.html", source_count=source_count,
                           is_subscriber=is_subscriber())


def _home_weather_strip():
    """Compact weather + wildfire summary for the homepage strip (#wtf-weather-strip).

    Reuses the SAME aurora_city_site/_city_obs/_city_forecast tables and the
    SAME _aurora_city_payload() builder as /weather — trimmed to the 13
    provincial capitals (there is no per-visitor geolocation on this site, so
    "local" here means one representative city per province, not an IP-derived
    location). Fire data is the same aurora_fire_hotspot_daily query /weather
    runs, capped to the top 6 provinces by hotspot count for a homepage strip.

    Weather is supplementary here (unlike the article feed), so any failure
    degrades to an empty strip rather than 500ing the whole homepage.
    """
    try:
        with _db().begin() as c:
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
            fire_provinces = c.execute(text("""
                SELECT prov, sum(hotspot_count) AS hotspots, max(max_fwi) AS max_fwi,
                       max(obs_date) AS obs_date
                FROM wtf.aurora_fire_hotspot_daily
                WHERE obs_date > CURRENT_DATE - 3
                GROUP BY prov ORDER BY sum(hotspot_count) DESC LIMIT 6
            """)).mappings().all()
        payload = _aurora_city_payload(city_rows, forecast_rows)
        payload["cities"] = [c for c in payload["cities"] if c["is_capital"]]
        payload["fire_provinces"] = [dict(r) for r in fire_provinces]
        return payload
    except Exception:
        return {"cities": [], "count": 0, "reporting": 0, "warmest": None,
                "coldest": None, "provinces": [], "fire_provinces": []}


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
        source_count = _active_source_count(c, S)
    sub = is_subscriber()
    return render_template("index.html", articles=rows,
                           top_stories=_home_top_stories(rows, is_sub=sub),
                           source_count=source_count, is_subscriber=sub,
                           weather_strip=_home_weather_strip())


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
            source_count = _active_source_count(c, S)
    except Exception:
        pass
    return render_template(
        "governance.html", scan=scan, source_count=source_count, is_subscriber=is_subscriber()
    )


@bp.get("/creed")
def creed_page():
    """About C.R.E.E.D. Institute — the independent ethics layer this newsroom
    answers to. Entirely static content (the design's own footnote is explicit
    that no grade is ever hand-entered here — the live score lives on
    /governance, which reads _fetch_creed_scan() directly). No scan/dispatch
    needed on this route at all."""
    S = _schema()
    source_count = 0
    try:
        with _db().begin() as c:
            source_count = _active_source_count(c, S)
    except Exception:
        pass
    return render_template("creed.html", source_count=source_count, is_subscriber=is_subscriber())


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
            agg_where = ["a.lat IS NOT NULL", "a.country_code IS NOT NULL", "a.suppressed_reason IS NULL"]
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
            prov_where = [f"a.province_code IN {_PROVINCE_SQL_LIST}", "a.lat IS NOT NULL", "a.suppressed_reason IS NULL"]
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
                   -- Beat — free-to-render classification, used only for the
                   -- "signal breakdown" chips below (batch 11 #6284).
                   a.beat,
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

    # Blindspot flag — is THIS story one of the ones /blindspot already
    # tracks? Reads the SAME `story_clusters.blindspot_side` column that
    # page's own queries key on (migration 079 + ingest/cluster_metrics.py),
    # never a private re-derivation of "carried narrowly" here — a second
    # definition is how a story could be a blindspot on one page and not
    # the other. One extra column on a cluster row already identified by
    # a.cluster_id above; no new join, no new table.
    is_blindspot = False
    if a.get("cluster_id"):
        try:
            with _db().begin() as c:
                is_blindspot = bool(c.execute(text(f"""
                    SELECT blindspot_side FROM {S}.story_clusters WHERE id = :cid
                """), {"cid": a["cluster_id"]}).scalar())
        except Exception:
            is_blindspot = False

    # ------------------------------------------------------------------
    # Pickup order — who filed on this story first, and how far behind
    # each follow-on outlet published. Built from the SAME cluster_articles
    # rows fetched above (no new query) plus this article's own timestamp,
    # sorted ASCENDING (the comparison panel above is deliberately DESC —
    # "who filed first" only reads correctly earliest-first). #6153.
    def _fmt_pickup_offset(hours: float) -> str:
        if hours < 0.05:
            return "Same time"
        if hours < 24:
            return f"+{max(1, round(hours))}h"
        days = int(hours // 24)
        rem_h = round(hours - days * 24)
        if rem_h >= 24:
            days, rem_h = days + 1, 0
        return f"+{days}d {rem_h}h" if rem_h else f"+{days}d"

    pickup_order = []
    coverage_stats = None
    if cluster_articles:
        _entries = [{
            "id": a["id"], "title": a.get("title"),
            "source_name": a.get("source_name"), "published_at": a.get("published_at"),
            "is_current": True,
        }]
        for _ca in cluster_articles:
            _entries.append({
                "id": _ca["id"], "title": _ca.get("title"),
                "source_name": _ca.get("source_name"),
                "published_at": _ca.get("published_at"), "is_current": False,
            })
        _entries = [e for e in _entries if e.get("published_at")]
        _entries.sort(key=lambda e: e["published_at"])
        if len(_entries) >= 2:
            _first_ts = _entries[0]["published_at"]
            for _i, _e in enumerate(_entries):
                if _i == 0:
                    _e["offset_label"] = "First to report"
                else:
                    _hours = max(0.0, (_e["published_at"] - _first_ts).total_seconds() / 3600.0)
                    _e["offset_label"] = _fmt_pickup_offset(_hours)
            pickup_order = _entries

        # "What we measured" — a coverage summary computed from the SAME
        # rows: the real bias bands actually recorded for this story, never
        # an invented spread. Reuses the module-level _BAND_ORDER / _band_label
        # (declared once, below, precisely so a second copy cannot drift from
        # it) rather than a private re-encoding of the same 5-band vocabulary.
        # An outlet with no recorded band (bias not yet scored, or a wire item
        # where bias is deliberately suppressed) is excluded — an absent band
        # is not a "center" band.
        _current_band = a.get("bias_ensemble_band") or a.get("bias_band")
        _seen_bands = {_current_band} if _current_band else set()
        for _ca in cluster_articles:
            if _ca.get("bias_band"):
                _seen_bands.add(_ca["bias_band"])
        _spanned = [b for b in _BAND_ORDER if b in _seen_bands]
        if _spanned:
            if len(_spanned) > 1:
                _widest = (f"{_band_label(_BAND_ORDER.index(_spanned[0]))} "
                           f"→ {_band_label(_BAND_ORDER.index(_spanned[-1]))}")
            else:
                _widest = _band_label(_BAND_ORDER.index(_spanned[0]))
            # Verdict tile — same display rule the fact-check panel below
            # already uses for `verdict_display` (kept as ONE computation
            # here rather than a third private copy of the mapping; the
            # panel's own inline Jinja `verdict_display` is untouched).
            _ov = a.get("overall_verdict")
            if _ov == "descriptive_reporting":
                _verdict_label = "Descriptive Reporting"
            elif _ov:
                _verdict_label = _ov.replace("_", " ").title()
            else:
                _verdict_label = "None yet"
            coverage_stats = {
                "outlets_covering": 1 + len(cluster_articles),
                "bands_spanned": len(_spanned),
                "widest_label": _widest,
                "verdict_label": _verdict_label,
            }

        # Band-by-band breakdown — "where the outlets covering this sit"
        # (design-handoff/wtf-article.html's per-band .cov rows). Reuses the
        # SAME rows as coverage_stats above, just counted instead of merely
        # spanned, so this cannot show a percentage the "bands spanned" tile
        # itself disagrees with. Excluded from a band with zero real rows —
        # never renders a phantom 0% row for a band nobody occupies.
        _band_counts = {}
        if _current_band:
            _band_counts[_current_band] = _band_counts.get(_current_band, 0) + 1
        for _ca in cluster_articles:
            if _ca.get("bias_band"):
                _band_counts[_ca["bias_band"]] = _band_counts.get(_ca["bias_band"], 0) + 1
        _band_total = sum(_band_counts.values())
        band_breakdown = []
        if _band_total:
            for _b in _BAND_ORDER:
                _n = _band_counts.get(_b, 0)
                if _n:
                    band_breakdown.append({
                        "band": _b,
                        "label": _band_label(_BAND_ORDER.index(_b)),
                        "count": _n,
                        "pct": round(_n / _band_total * 100),
                    })
            band_breakdown.sort(key=lambda r: r["count"], reverse=True)
    else:
        band_breakdown = []

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

    # "Back to News" replays whatever filter querystring the reader arrived
    # with, IF the caller supplied one (?back=<news querystring>) — a plain
    # passthrough, not a re-derivation of /news' own filter logic, so this
    # can never disagree with that page about what it means to filter.
    # Absent (today, no /news link sets it yet) it degrades to a bare link
    # to /news, never a broken one.
    back_qs = request.args.get("back", "")

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
                           cross_watch_entities=cross_watch_entities,
                           pickup_order=pickup_order,
                           coverage_stats=coverage_stats,
                           band_breakdown=band_breakdown,
                           is_blindspot=is_blindspot,
                           back_qs=back_qs)


# ───────────────────────────────────────────────────────────────────────────
# Election Claim Tracker — public pages (#3013)
# ───────────────────────────────────────────────────────────────────────────


# Real, non-pending status values (claim_tracker_status_check) in a fixed,
# deliberate display order. NOT the mockup's Established/Contested/Developing
# taxonomy — that vocabulary does not exist in this schema (no "Established",
# no "Developing" state at all), and inventing a mapping onto it here would be
# exactly the fabrication this file exists to avoid. #6284 batch 11: defer any
# real taxonomy change to an owner decision; this enumerates what is actually
# stored.
_CLAIM_STATUSES = ("verified_true", "partially_true", "misleading", "false", "contested")


def _claim_stat_tiles(c, S: str) -> list:
    """Aggregate stat-row tiles for the claims index — sitewide, independent
    of any ?status= filter (a "N claims checked" figure that changes when you
    click a filter chip would be a confusing thing to show as a totals row).

    Returns [] on any query failure so the caller's existing empty-fallback
    behavior is unchanged; the caller decides whether to render the row.
    """
    status_rows = c.execute(
        text(f"SELECT status, COUNT(*) AS n FROM {S}.claim_tracker "
             "WHERE status != 'pending' GROUP BY status")
    ).mappings().all()
    counts = {r["status"]: r["n"] for r in status_rows}
    total_checked = sum(counts.values())
    tiles = [{
        "label": "Claims checked",
        "value": total_checked,
        "detail": None,
    }]
    for st in _CLAIM_STATUSES:
        n = counts.get(st, 0)
        pct = round(n / total_checked * 100) if total_checked else 0
        tiles.append({
            "label": st.replace("_", " ").title(),
            "value": f"{pct}%",
            "detail": f"{n} claim{'' if n == 1 else 's'}",
        })
    return tiles


@bp.get("/claims")
def claims_index():
    S = _schema()
    status_filter = request.args.get("status")
    params = {}
    where = "WHERE ct.status != 'pending'"
    if status_filter and status_filter != "all":
        where += " AND ct.status = :status"
        params["status"] = status_filter
    claim_stats = []
    try:
        with _db().begin() as c:
            rows = c.execute(
                text(
                    f"""
                    SELECT id, politician_slug, politician_name,
                           claim_text, claim_date, status, verdict_summary,
                           source_url
                    FROM {S}.claim_tracker ct
                    {where}
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                ),
                params,
            ).mappings().all()
            claim_stats = _claim_stat_tiles(c, S)
        claims = []
        for r in rows:
            d = dict(r)
            if d.get("claim_date"):
                d["claim_date"] = str(d["claim_date"])
            claims.append(d)
    except Exception:
        claims = []
        claim_stats = []
    subscribed = is_subscriber()
    return render_template("claims.html", claims=claims,
                           is_subscriber=subscribed,
                           active_status=status_filter or "all",
                           claim_stats=claim_stats)


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
                           claim_text, claim_date, status, verdict_summary,
                           source_url
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


@bp.get("/literacy/score")
def literacy_score_page():
    """Personal media-literacy dashboard. Subscriber-gated.

    Relocated from /literacy (#6272, Batch 9) — the design handoff wants a
    PUBLIC tips page at /literacy (see literacy_page() below), which cannot
    coexist with this gated personal dashboard at the same URL. Owner
    decision: this page moves, the design gets the URL."""
    from flask import redirect
    email = _user_email()
    if not email:
        return redirect("/login?next=/literacy/score")
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

    return render_template("literacy_score.html",
                           user_email=email,
                           score=score,
                           total_scored=total_articles,
                           total_views=sum(int(r["views"] or 0) for r in rows),
                           distribution=distribution,
                           recent=[dict(r) for r in recent])


@bp.get("/literacy")
def literacy_page():
    """Public media-literacy tips page (#6272, Batch 9) — entirely static
    editorial content ported from design-handoff/wtf-literacy.html, no login
    or subscription required. Was blocked on this URL by the gated personal
    dashboard now at /literacy/score (see literacy_score_page() above);
    owner decision moved that page so this one could take /literacy."""
    S = _schema()
    source_count = 0
    try:
        with _db().begin() as c:
            source_count = _active_source_count(c, S)
    except Exception:
        pass
    return render_template("literacy.html", source_count=source_count, is_subscriber=is_subscriber())


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


# ── /sources — MIN_N honesty floor + real fact-checked count (#6272 batch 11) ──
# MIN_N: `outlet_bias_scores.article_count` is the number of articles inside the
# ROLLING SCORING WINDOW that actually fed `avg_score`/`band` — NOT the same
# number as `total_articles` below (every article ever ingested from that
# outlet, scored or not; can run into the thousands while the scoring window
# holds a handful). A one- or two-article average is not a reliable outlet
# lean and must not render as if it were — same honesty principle as
# rate_policy.py's non-decreasing invariant and the MIN_N floors already used
# elsewhere on this site.
_SOURCES_MIN_N = 5

_SOURCES_SORTS = {
    "articles": "total_articles DESC",
    "name": "s.name ASC",
}
# "checked" and "lean" are NOT in _SOURCES_SORTS — their sort key isn't known
# until after the query returns (fact_checked_count is merged in from a
# separately-cached lookup; avg_score must respect the MIN_N honesty floor
# applied below, so ordering by the pre-floor column would rank outlets by a
# number the page refuses to display). Both are cheap in Python — at most 46
# rows — so they are re-sorted in-process after enrichment instead of pushed
# into the SQL ORDER BY.
_SOURCES_PY_SORTS = ("checked", "lean")

_SOURCES_FC_CACHE: dict = {}  # 'counts' -> (expiry, {source_id: count})
_SOURCES_FC_CACHE_TTL = int(os.environ.get("WTF_SOURCES_FC_CACHE_TTL", "300"))


def _sources_fact_checked_counts(S) -> dict:
    """Per-source count of DISTINCT articles carrying at least one fact-check.

    Cached — same TTL-dict pattern as `_NAV_SOURCE_CACHE`/`_ACTIVITY_CACHE`
    above, and for the same reason: `fact_checks` has 400k+ rows with NO
    unique constraint on `article_id` (up to 8 claims per article — see the
    #5719 comment above), so an uncached per-request join here repeats the
    exact "~40 whole-table COUNTs ... measured 20-36s per page view" mistake
    the activity-page cache was built to fix. Measured cold: ~800ms with a
    DISTINCT-first CTE (a naive COUNT(DISTINCT article_id) GROUP BY measured
    2-3.5s instead). A failed computation degrades to "0 for every outlet"
    rather than taking the page down.
    """
    hit = _SOURCES_FC_CACHE.get("counts")
    now = time.time()
    if hit and hit[0] > now:
        return hit[1]
    counts: dict = {}
    try:
        with _db().begin() as c:
            rows = c.execute(text(f"""
                SELECT a2.source_id, COUNT(*) AS n
                FROM (SELECT DISTINCT article_id FROM {S}.fact_checks) fca
                JOIN {S}.articles a2 ON a2.id = fca.article_id
                    AND a2.suppressed_reason IS NULL
                GROUP BY a2.source_id
            """)).all()
        counts = {int(r[0]): int(r[1]) for r in rows}
    except Exception:
        logger.exception("sources: fact-checked-count computation failed")
    _SOURCES_FC_CACHE["counts"] = (now + _SOURCES_FC_CACHE_TTL, counts)
    return counts


@bp.get("/sources")
def sources_list():
    """All tracked outlets — searchable by name, sortable, with the MIN_N
    honesty floor on the averaged band and a real per-outlet fact-checked
    count (#6272 batch 11). Sorting by fact-checked count or by lean
    (`checked`/`lean`) is added in the follow-up polish pass — both are
    re-sorted in Python after enrichment (see `_SOURCES_PY_SORTS`), so they
    carry no extra query cost.

    DEFERRED (documented, not half-built — see the PR description for the
    reasons): the mockup's 6 clickable stat-tile filters, the up-to-3 compare
    tray, and the visual band-range scale bar all need real client-side
    interactive state, and the mockup's "filed first" (which outlet published
    first in a multi-source story cluster) and "most bands published in" are
    real, computable data but need a per-article aggregate this page's
    request cycle should not carry: "filed first" measured 400ms-3.5s live
    with no supporting index, and "bands published in" is not the same number
    as the rolling `band` already selected here (that is one label for the
    outlet's recent window; the mockup's metric is the count of DISTINCT
    bands across the outlet's full-history articles, which needs its own
    join and cache, same shape as `_sources_fact_checked_counts` below). Both
    need a scheduled/materialized aggregate, not a page-load query.
    """
    S = _schema()
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort") or "articles"
    if sort not in _SOURCES_SORTS and sort not in _SOURCES_PY_SORTS:
        sort = "articles"
    # Python-sorted keys still need a valid SQL ORDER BY for the initial
    # fetch (overwritten below) — "articles" is a stable, harmless default.
    sql_sort = sort if sort in _SOURCES_SORTS else "articles"
    params: dict = {}
    where = ""
    if q:
        where = "WHERE s.name ILIKE :q"
        params["q"] = f"%{q}%"
    with _db().begin() as c:
        rows = c.execute(text(f"""
            SELECT s.id, s.slug, s.name, s.url, s.bias_lean, s.owner_name, s.owner_type,
                   obs.avg_score, obs.band AS rolling_band,
                   COALESCE(obs.article_count, 0) AS scored_article_count,
                   COUNT(a.id) AS total_articles,
                   COUNT(a.id) FILTER (WHERE a.published_at > NOW() - INTERVAL '7 days') AS articles_7d
            FROM {S}.sources s
            LEFT JOIN {S}.outlet_bias_scores obs ON obs.source_id = s.id
            LEFT JOIN {S}.articles a ON a.source_id = s.id AND a.suppressed_reason IS NULL
            {where}
            GROUP BY s.id, s.slug, s.name, s.url, s.bias_lean, s.owner_name, s.owner_type,
                     obs.avg_score, obs.band, obs.article_count
            ORDER BY {_SOURCES_SORTS[sql_sort]}
        """), params).mappings().all()
    fc_counts = _sources_fact_checked_counts(S)
    sources = []
    for r in rows:
        d = dict(r)
        below_min_n = int(d.get("scored_article_count") or 0) < _SOURCES_MIN_N
        if below_min_n:
            # Statistical-honesty floor — do not render an average computed
            # from too few articles as if it were a reliable measurement.
            d["avg_score"] = None
            d["rolling_band"] = None
        d["below_min_n"] = below_min_n
        d["fact_checked_count"] = fc_counts.get(d["id"], 0)
        sources.append(d)
    if sort == "checked":
        sources.sort(key=lambda d: d["fact_checked_count"], reverse=True)
    elif sort == "lean":
        # Unmeasurable outlets (below the MIN_N floor, avg_score already
        # nulled above) sort to the end — ordering by a hidden pre-floor
        # value would render an average the page has decided not to show.
        sources.sort(key=lambda d: (d["avg_score"] is None,
                                     d["avg_score"] if d["avg_score"] is not None else 0.0))
    return render_template(
        "sources.html", sources=sources, q=q, sort=sort, min_n=_SOURCES_MIN_N,
    )


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
            LEFT JOIN {S}.articles a ON a.source_id = s.id AND a.suppressed_reason IS NULL
            WHERE s.slug = :slug
            GROUP BY s.id, s.slug, s.name, s.url, s.bias_lean, s.country,
                     s.language, s.owner_name, s.owner_type, obs.avg_score, obs.band
        """), {"slug": slug}).mappings().first()
    if not src:
        abort(404)
    # #6295 batch 11 — stat tiles, coverage/peer panels, full article list,
    # and a continuous bias gauge. Everything below is computed from THIS
    # outlet's own rows; nothing here invents a metric the schema can't back
    # (audit's "blindspot count" and "fact-check rate %" were dropped for
    # exactly that reason — see the PR description).
    show_all = request.args.get("all") == "1"
    ARTICLE_LIST_CAP = 300
    article_limit = ARTICLE_LIST_CAP if show_all else 20

    with _db().begin() as c:
        band_counts = c.execute(text(f"""
            SELECT COALESCE(b.band, 'unscored') AS band, COUNT(*) AS n
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.source_id = :sid AND a.suppressed_reason IS NULL
            GROUP BY 1 ORDER BY 2 DESC
        """), {"sid": src["id"]}).mappings().all()
        recent = c.execute(text(f"""
            SELECT a.id, a.title, a.url, a.published_at, b.band, b.score
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
            WHERE a.suppressed_reason IS NULL AND a.source_id = :sid
            ORDER BY a.published_at DESC LIMIT :lim
        """), {"sid": src["id"], "lim": article_limit}).mappings().all()

        # Fact-checked count — COUNT(DISTINCT article_id): fact_checks has no
        # unique constraint on article_id (this file already notes up to 8
        # duplicate rows per article near the /article route), the same
        # dedup pattern already used at 6+ other call sites in this file.
        fact_checked_count = c.execute(text(f"""
            SELECT COUNT(DISTINCT fc.article_id)
            FROM {S}.fact_checks fc
            JOIN {S}.articles a ON a.id = fc.article_id
            WHERE a.source_id = :sid AND a.suppressed_reason IS NULL
        """), {"sid": src["id"]}).scalar() or 0

        # Filed-first count — this outlet's article published_at equals the
        # cluster's earliest_published_at. That column is set ONCE, at
        # cluster creation (ingest/cluster.py never updates it as later
        # articles join an existing cluster) — "which article the
        # clustering pipeline saw first", the same value /clusters and the
        # bias-trend API already read from this column, not a new
        # definition invented here.
        filed_first_count = c.execute(text(f"""
            SELECT COUNT(*)
            FROM {S}.articles a
            JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
            WHERE a.source_id = :sid AND a.suppressed_reason IS NULL
              AND a.published_at = sc.earliest_published_at
        """), {"sid": src["id"]}).scalar() or 0

        # Coverage profile — main beat / main region, a plain GROUP BY over
        # this outlet's own articles. beat='none' is a real stored value
        # meaning "no beat assigned" (42k+ rows platform-wide), not a beat,
        # so it is excluded the same way /news's beat facets exclude it.
        coverage = c.execute(text(f"""
            SELECT
                (SELECT beat FROM {S}.articles
                  WHERE source_id = :sid AND suppressed_reason IS NULL
                    AND beat IS NOT NULL AND beat <> 'none'
                  GROUP BY beat ORDER BY COUNT(*) DESC LIMIT 1) AS main_beat,
                (SELECT province_code FROM {S}.articles
                  WHERE source_id = :sid AND suppressed_reason IS NULL
                    AND province_code IS NOT NULL
                  GROUP BY province_code ORDER BY COUNT(*) DESC LIMIT 1) AS main_region
        """), {"sid": src["id"]}).mappings().first()

        # Peer outlets — nearest by rolling avg_score. Only meaningful once
        # THIS outlet has one itself (obs.avg_score, LEFT JOINed above);
        # outlet_bias_scores has UNIQUE(source_id) (~46 rows platform-wide),
        # so this is a cheap nearest-neighbour scan, not a heavy query.
        peers = []
        if src["avg_score"] is not None:
            peers = c.execute(text(f"""
                SELECT s.id, s.slug, s.name, obs.avg_score, obs.band
                FROM {S}.outlet_bias_scores obs
                JOIN {S}.sources s ON s.id = obs.source_id
                WHERE obs.source_id != :sid
                ORDER BY abs(obs.avg_score - :avg) ASC
                LIMIT 5
            """), {"sid": src["id"], "avg": src["avg_score"]}).mappings().all()

        # Corpus-wide weighted average score (batch 11 mockup parity) — a
        # cheap aggregate over the platform's ~46 scored outlets
        # (outlet_bias_scores has UNIQUE(source_id), same table the peers
        # query above scans). Powers the "an average is not a label"
        # disclaimer next to this outlet's own distribution; it is a single
        # platform-wide figure, not a claim about any one outlet, so it is
        # not gated by the MIN_N honesty floor used elsewhere.
        corpus_avg_score = c.execute(text(f"""
            SELECT SUM(avg_score * article_count) / NULLIF(SUM(article_count), 0)
            FROM {S}.outlet_bias_scores
        """)).scalar()

    return render_template("source.html",
                           src=dict(src),
                           band_counts=[dict(r) for r in band_counts],
                           recent=[dict(r) for r in recent],
                           fact_checked_count=fact_checked_count,
                           filed_first_count=filed_first_count,
                           coverage=dict(coverage),
                           peers=[dict(r) for r in peers],
                           corpus_avg_score=corpus_avg_score,
                           show_all=show_all,
                           article_list_cap=ARTICLE_LIST_CAP,
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


def _pickup_text(td) -> str:
    """Wall-clock span between a cluster's first and most recent article,
    e.g. 'over 6h' / 'over 2d' — the same `pickup_span` value `_CLUSTER_SORTS`
    already sorts "Slowest pickup" by, just made readable for the card meta
    line (#6149 batch 11 gap-fill — the design mockup names this explicitly).
    `td` is a Python timedelta (the Postgres interval), or None for a
    single-article cluster with no span to report.
    """
    if td is None:
        return "—"
    secs = td.total_seconds()
    if secs < 0:                # clock skew — never print a negative span
        return "—"
    if secs < 3600:
        return "under 1h"
    if secs < 86400:
        return f"over {int(secs // 3600)}h"
    return f"over {int(secs // 86400)}d"


def _divergence_score(n0: int, n1: int, n2: int, n3: int, n4: int):
    """0-100 framing-spread score, computed LIVE — the exact same closed-form
    formula as the precomputed `story_clusters.divergence_score` (migration
    080's comment: mean pairwise |band_i - band_j| distance over every
    scored-article pair, normalized /4*100), just derived from THIS request's
    live n0..n4 band counts rather than the nightly-batch column, so it can
    never disagree with the live `lo`/`hi`/`med` shown on the same card (see
    `_cluster_index_rows`'s docstring on why this page reads bands live
    rather than from the batch-refreshed columns). Returns None when fewer
    than 2 scored articles exist in the cluster — there is no pair to measure
    a spread from. This is the same math the design mockup's `spreadScore()`
    uses (design-handoff/wtf-clusters.js) — #6149 batch 11 gap-fill.
    """
    counts = (n0 or 0, n1 or 0, n2 or 0, n3 or 0, n4 or 0)
    total = sum(counts)
    if total < 2:
        return None
    pairs = total * (total - 1) // 2
    weighted = sum(
        abs(i - j) * counts[i] * counts[j]
        for i in range(5) for j in range(i + 1, 5)
    )
    return max(0, min(100, round(weighted / pairs / 4 * 100)))


_CLUSTER_SIZES = {
    "all": "Any size",
    "big": "12+ outlets",
    "mid": "6–11 outlets",
    "small": "Under 6 — blindspot seeds",
}
_CLUSTER_SIZE_HAVING = {
    "big": "COUNT(DISTINCT a.source_id) >= 12",
    "mid": "COUNT(DISTINCT a.source_id) BETWEEN 6 AND 11",
    "small": "COUNT(DISTINCT a.source_id) < 6",
}

# Named sort directions, mirroring /archive's _ARCHIVE_SORTS. "pickup" orders
# by the wall-clock span between a cluster's FIRST article and its most recent
# one — a real, derived measurement (never an LLM guess at "how fast this spread").
_CLUSTER_SORTS = {
    "spread": ("Spread",         "spread DESC NULLS LAST, m.outlets DESC, m.last_pub DESC"),
    "size":   ("Size",           "m.outlets DESC, spread DESC NULLS LAST, m.last_pub DESC"),
    "recent": ("Most recent",    "m.last_pub DESC"),
    "pickup": ("Slowest pickup", "pickup_span DESC NULLS LAST, m.last_pub DESC"),
}


def _cluster_filters(args) -> dict:
    """Validate every filter against a CLOSED set — same discipline as
    /archive's `_archive_filters`. Never interpolate user text into SQL."""
    def _one(name, allowed, default="all"):
        v = (args.get(name) or default).strip()
        return v if v in allowed else default

    try:
        days = int(args.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in _CLUSTER_WINDOWS:
        days = 7
    sort = args.get("sort", "spread")
    if sort not in _CLUSTER_SORTS:
        sort = "spread"
    return {
        "days": days,
        "sort": sort,
        "q": (args.get("q") or "").strip()[:120],
        "beat": _one("beat", set(VALID_BEATS) | {"all"}),
        "size": _one("size", set(_CLUSTER_SIZES)),
        "median": _one("median", set(_BAND_ORDER) | {"all"}),
    }


def _cluster_qs(f: dict, **override) -> str:
    """Build a /clusters URL preserving current filters — mirrors `_archive_qs`."""
    from urllib.parse import urlencode
    merged = {k: f[k] for k in ("days", "sort", "q", "beat", "size", "median")}
    merged.update(override)
    keep = {k: v for k, v in merged.items() if v not in (None, "", "all")}
    return "/clusters" + ("?" + urlencode(keep) if keep else "")


def _cluster_index_rows(f: dict, limit: int = _CLUSTER_LIMIT):
    """Clusters carried by 2+ outlets, filtered + sorted per `f` (`_cluster_filters`).

    Counts are computed LIVE from articles rather than read from the
    denormalised `story_clusters.source_count`/`article_count`, for one reason:
    they must agree with /cluster/<id>, which filters `suppressed_reason IS
    NULL`. (Spot-checked 2026-09-02: the denormalised values happen to match on
    current rows, but a metric refreshed on a different filter is exactly how
    a list page comes to disagree with the detail page it links to.)

    Filters (#6149 batch 11, all against columns this query already touches):
    `q` matches the cluster's headline, its `articles.beat`, or any outlet
    `sources.name` inside it — the same three nouns the design mockup's
    placeholder names ("Event, outlet, beat…"). `beat` is the SAME column
    /archive already filters on (87% populated over a 7-day window, measured
    2026-09-04 — nothing like the 10%/66% province/city columns ADR-020
    excludes as too sparse to offer honestly). `size` buckets on the outlet
    count this query already computes (0 clusters cleared 12+ in the live
    7-day window when this was written — an honest empty bucket, not a bug).
    `median` filters the SQL ordinal (`m.med`), never the Python display
    fallback that paints an unscored cluster's badge "center" — filtering on
    that fallback would put zero-score clusters under a lean they were never
    actually assigned.

    ⚠️ #6149 batch 11 gap-fill (design-handoff/wtf-clusters.html): `n0`..`n4`
    are the live per-band scored-article counts (same 5 bands as
    `_BAND_ORDER`), added so the page can show a numeric spread score and a
    band-mix bar computed from THIS request's live data — never from the
    precomputed `story_clusters.divergence_score` / `band0_count`..
    `band4_count` (migration 080), which are refreshed by a nightly batch and
    would disagree with the live `lo`/`hi`/`med` above on any cluster still
    growing today (the exact "metric refreshed on a different filter" trap
    this docstring already warns about). `lean_l_count`/`lean_r_count` and
    `has_dispute` (from `cluster_disputes.disputed_point`) ARE read from the
    precomputed columns — that mirrors what /divergence's own `_dispute_rows`
    already does in production, so it is an accepted reuse, not a new risk.
    """
    S = _schema()
    having = ["COUNT(DISTINCT a.source_id) >= 2"]
    outer_where = []
    p = {"days": f["days"], "lim": limit}

    if f["beat"] != "all":
        having.append("MIN(a.beat) = :beat")
        p["beat"] = f["beat"]
    if f["size"] in _CLUSTER_SIZE_HAVING:
        having.append(_CLUSTER_SIZE_HAVING[f["size"]])
    if f["q"]:
        outer_where.append(f"""(
            sc.representative_title ILIKE :q
            OR EXISTS (
                 SELECT 1 FROM {S}.articles a2
                 JOIN {S}.sources s2 ON s2.id = a2.source_id
                WHERE a2.cluster_id = m.cid
                  AND a2.suppressed_reason IS NULL
                  AND (a2.beat ILIKE :q OR s2.name ILIKE :q)
            )
        )""")
        p["q"] = f"%{f['q']}%"
    if f["median"] != "all":
        outer_where.append("m.med = :median_ord")
        p["median_ord"] = _BAND_ORDER.index(f["median"])

    outer_sql = (" AND " + " AND ".join(outer_where)) if outer_where else ""
    order = _CLUSTER_SORTS[f["sort"]][1]

    with _db().begin() as c:
        return c.execute(text(f"""
            WITH m AS (
              SELECT a.cluster_id                                         AS cid,
                     COUNT(DISTINCT a.source_id)                          AS outlets,
                     COUNT(DISTINCT a.id)                                 AS articles,
                     MAX(a.published_at)                                  AS last_pub,
                     MIN(a.published_at)                                  AS first_pub,
                     COUNT(b.band)                                        AS scored,
                     percentile_disc(0.5) WITHIN GROUP (
                       ORDER BY {_BAND_ORD_SQL})                          AS med,
                     MIN({_BAND_ORD_SQL})                                 AS lo,
                     MAX({_BAND_ORD_SQL})                                 AS hi,
                     COUNT(b.band) FILTER (WHERE b.band = 'left')         AS n0,
                     COUNT(b.band) FILTER (WHERE b.band = 'center-left')  AS n1,
                     COUNT(b.band) FILTER (WHERE b.band = 'center')       AS n2,
                     COUNT(b.band) FILTER (WHERE b.band = 'center-right') AS n3,
                     COUNT(b.band) FILTER (WHERE b.band = 'right')        AS n4
                FROM {S}.articles a
                LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
               WHERE a.suppressed_reason IS NULL
                 AND a.cluster_id IS NOT NULL
                 AND a.published_at > NOW() - make_interval(days => :days)
               GROUP BY a.cluster_id
              HAVING {' AND '.join(having)}
            )
            SELECT m.cid AS id, m.outlets, m.articles, m.last_pub,
                   m.scored, m.med, m.lo, m.hi,
                   m.n0, m.n1, m.n2, m.n3, m.n4,
                   (m.hi - m.lo) AS spread,
                   (m.last_pub - m.first_pub) AS pickup_span,
                   sc.representative_title, sc.certainty_label,
                   sc.lean_l_count, sc.lean_r_count,
                   (cd.disputed_point IS NOT NULL) AS has_dispute
              FROM m
              JOIN {S}.story_clusters sc ON sc.id = m.cid
              LEFT JOIN {S}.cluster_disputes cd ON cd.cluster_id = m.cid
             WHERE TRUE{outer_sql}
             ORDER BY {order}
             LIMIT :lim
        """), p).mappings().all()


def _cluster_index_totals(days: int) -> dict:
    """Qualifying totals for the header tiles.

    ⚠️ These are the WINDOW totals, never `rows|length` — the same trap called
    out in blindspot.html. Measured 2026-09-02 over 7 days: 546 clusters
    qualify and only 106 of them (19%) show any framing spread at all. A page
    that showed 40 cards each with a different lean pill would imply a
    diversity of framing this corpus does not have.

    Deliberately UNFILTERED (window-only) — this is the corpus-wide honesty
    message ("most coverage of an event shares one band"), not a per-filter
    count. `shown` in the template carries how many of the CURRENT filter
    selection are on screen.

    ⚠️ #6149 batch 11 gap-fill: `blindspot_seeds` (outlets < 6, the SAME
    threshold as `_CLUSTER_SIZE_HAVING["small"]` / the "size" filter's "Under
    6 — blindspot seeds" option) feeds the mockup's 4th stat tile. Zero extra
    cost — `outlets` was already selected here for `widest`.
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
                   COUNT(*) FILTER (WHERE outlets < 6)              AS blindspot_seeds,
                   COALESCE(MAX(outlets), 0)                       AS widest
              FROM m
        """), {"days": days}).mappings().first()
    return dict(row) if row else {"qualifying": 0, "with_spread": 0,
                                   "blindspot_seeds": 0, "widest": 0}


@bp.get("/clusters")
def clusters_index():
    """Story-cluster index — 'one event, many tellings' (#6149 Design phase 2).

    Linked from the main nav (News > Clusters) but returned 404 until now; the
    only cluster surface was the /cluster/<id> detail page, reachable solely
    from a link on another page.

    Ordered by framing SPREAD by default, not recency, because spread is the
    page's whole claim — but a reader can now change that (`_CLUSTER_SORTS`).

    Filters + sort added #6149 batch 11 (search / beat / size / median-band,
    named sort directions) — plain GET query params, validated against closed
    sets in `_cluster_filters`, same house pattern as /archive. DEFERRED: the
    design mockup's expandable inline per-cluster detail body (per-outlet
    grid, quote-flip, "why it matters") stays a link-out to /cluster/<id> — a
    bigger, separate build, not a filter.

    ⚠️ Second gap-fill pass (same task, reconciled against
    design-handoff/wtf-clusters.html once more): `divergence_score` (live 0-100
    spread, `_divergence_score`) + `band_counts` (for the mockup's band-mix
    bar) are computed from `n0`..`n4`, never the nightly-batch
    `story_clusters.divergence_score` column — see `_cluster_index_rows`'s
    docstring. `is_small` reuses the same `outlets < 6` threshold as the
    "size" filter's blindspot-seed bucket. `is_dispute` mirrors /divergence's
    own `_dispute_rows` qualification exactly (`lean_l_count`/`lean_r_count`
    both > 0, `disputed_point IS NOT NULL`, `article_count >= _DISPUTE_MIN_
    ARTICLES`) so a cluster is never called "checkable" here when /divergence
    itself would not.
    """
    from flask import request as _req
    f = _cluster_filters(_req.args)

    rows = [dict(r) for r in _cluster_index_rows(f)]
    for r in rows:
        r["median_band"] = (
            _BAND_ORDER[int(r["med"])] if r["med"] is not None else "center"
        )
        r["spread_text"] = _spread_sentence(
            r["outlets"], r["scored"], r["lo"], r["hi"]
        )
        r["age_text"] = _age_text(r["last_pub"])
        r["pickup_text"] = _pickup_text(r["pickup_span"])
        r["divergence_score"] = _divergence_score(
            r["n0"], r["n1"], r["n2"], r["n3"], r["n4"]
        )
        r["band_counts"] = [r["n0"], r["n1"], r["n2"], r["n3"], r["n4"]]
        r["is_small"] = r["outlets"] < 6
        r["is_dispute"] = bool(
            r["has_dispute"]
            and (r["lean_l_count"] or 0) > 0
            and (r["lean_r_count"] or 0) > 0
            and r["articles"] >= _DISPUTE_MIN_ARTICLES
        )
    return render_template("clusters.html",
                           clusters=rows,
                           totals=_cluster_index_totals(f["days"]),
                           f=f,
                           days=f["days"],
                           windows=_CLUSTER_WINDOWS,
                           # VALID_BEATS literally contains "all" as a member
                           # (see /news' beat_filter) — excluded here so the
                           # dropdown's own "Every beat" option isn't doubled.
                           beats=sorted(VALID_BEATS - {"all"}),
                           sizes=_CLUSTER_SIZES,
                           medians=_BAND_ORDER,
                           shown=len(rows),
                           url_windows=[(w, _cluster_qs(f, days=w)) for w in _CLUSTER_WINDOWS],
                           url_sorts=[(k, s[0], _cluster_qs(f, sort=k))
                                      for k, s in _CLUSTER_SORTS.items()],
                           url_clear=_cluster_qs({**f, "q": "", "beat": "all",
                                                  "size": "all", "median": "all"}))


_HOME_TOP_N = 5
_HOME_SPREAD_HOURS = 48


def _home_top_stories(recent_rows, is_sub: bool):
    """The homepage TOP STORIES list.

    SIGNED IN  -> recency, byte-identical to what shipped before this change.
    SIGNED OUT -> the same slots ranked by FRAMING SPREAD, because spread is
                  what this site is for and it is the honest thing to show a
                  first-time reader. Falls back to recency for any shortfall,
                  so the list is never short.

    ⚠️ SCOPE. Design's Phase 3 says "the homepage feed's eight free cards are
    selected for spread". THIS SITE HAS NO SUCH FEED: the main feed is rendered
    client-side into #wtf-feed-articles, and `is_subscriber` gates an upsell
    box, not a card count. The only server-rendered story selection a logged-out
    reader sees is this 5-item sidebar, so that is what the correction maps onto
    here. Owner-confirmed 2026-09-02. Do not widen it to the JS feed without
    asking again — that is a different, larger change.

    ⚠️ MEASURED BEFORE BUILDING (2026-09-02), because a ranking with nothing to
    rank is worse than none: clusters with ANY band spread number 13 in 24h,
    36 in 48h, 117 in 7d. 48h comfortably fills 5. But **zero** clusters in 48h
    span 3+ bands, so "widest spread" here means a one- or two-band difference.
    Do not add UI copy implying dramatic divergence — the data does not support it.

    Never raises: any failure returns the recency list the page would have shown.
    """
    fallback = list(recent_rows[:_HOME_TOP_N])
    if is_sub:
        return fallback
    try:
        S = _schema()
        with _db().begin() as c:
            spread = c.execute(text(f"""
                WITH m AS (
                  SELECT a.cluster_id                       AS cid,
                         MIN(a.id)                          AS article_id,
                         MIN(a.title)                       AS title,
                         MAX(a.published_at)                AS published_at,
                         COUNT(DISTINCT a.source_id)        AS outlets,
                         MAX({_BAND_ORD_SQL}) - MIN({_BAND_ORD_SQL}) AS spread
                    FROM {S}.articles a
                    LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
                   WHERE a.suppressed_reason IS NULL
                     AND a.cluster_id IS NOT NULL
                     AND a.published_at > NOW() - make_interval(hours => :hrs)
                     AND a.published_at <= NOW() + INTERVAL '2 hours'
                   GROUP BY a.cluster_id
                )
                SELECT article_id AS id, title, published_at
                  FROM m
                 WHERE spread > 0
                 ORDER BY spread DESC, outlets DESC, published_at DESC
                 LIMIT :lim
            """), {"hrs": _HOME_SPREAD_HOURS, "lim": _HOME_TOP_N}).mappings().all()
    except Exception:
        return fallback

    picked = [dict(r) for r in spread]
    seen = {r["id"] for r in picked}
    # Top up with recency so a quiet news day cannot leave the sidebar short.
    for r in fallback:
        if len(picked) >= _HOME_TOP_N:
            break
        if r["id"] not in seen:
            picked.append(dict(r))
            seen.add(r["id"])
    return picked[:_HOME_TOP_N]


_ARCHIVE_WINDOWS = (7, 30, 90, 365)
_ARCHIVE_PAGE = 50
# Free-tier ceilings, per the handoff spec: 10 stories or 50 articles by view.
_ARCHIVE_FREE_STORIES = 10
_ARCHIVE_FREE_ARTICLES = 50
# CSV export cap (#6149 batch 11) — a subscriber exporting a broad filter
# (365 days, no query) gets a real bulk download, not the whole table
# through one request. Same shape as _blindspot_rows' own `limit` param.
_ARCHIVE_EXPORT_LIMIT = 5000
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


def _parse_archive_date(value):
    """Parse a date_from/date_to query param as a real calendar date, or None.

    Never raises on a malformed string (#6149 batch 11) — an unparsable or
    absent value is treated exactly like an absent one, falling back to the
    days-window default rather than 500ing on a hand-edited query string.
    """
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except (ValueError, AttributeError):
        return None


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

    # Custom date range (#6149 batch 11) — an ALTERNATIVE to the fixed
    # windows above, never combined with them (see _archive_where). Reversed
    # inputs are swapped rather than rejected, so a hand-typed link never
    # returns zero rows just because the two fields were the wrong way round.
    date_from = _parse_archive_date(args.get("date_from"))
    date_to = _parse_archive_date(args.get("date_to"))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

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
        "date_from": date_from,
        "date_to": date_to,
    }


def _archive_where(f: dict) -> tuple:
    """Build the shared WHERE fragment + bind params. Parameterised throughout."""
    where = ["a.suppressed_reason IS NULL"]
    p = {}
    if f.get("date_from") or f.get("date_to"):
        # Custom range REPLACES the days-window entirely (#6149 batch 11) —
        # never both, so the page's own "last N days" label can never
        # disagree with the rows a reader is actually looking at.
        if f.get("date_from"):
            where.append("a.published_at >= :date_from")
            p["date_from"] = f["date_from"]
        if f.get("date_to"):
            # Half-open range: the whole "to" day is included.
            where.append("a.published_at < :date_to_excl")
            p["date_to_excl"] = f["date_to"] + datetime.timedelta(days=1)
    else:
        where.append("a.published_at > NOW() - make_interval(days => :days)")
        p["days"] = f["days"]
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


def _archive_qs(f: dict, base_path="/archive", **override) -> str:
    """Build an /archive URL preserving current filters, with overrides applied.

    Lives in Python, not the template: Jinja macros cannot take **kwargs (the
    first draft tried and raised TemplateSyntaxError at render time), and URL
    assembly is worth unit-testing. Defaults and empties are dropped so a shared
    link stays short and readable.

    `base_path` (#6149 batch 11) lets the CSV export link reuse the exact same
    filter-preserving logic against a different route (/archive/export.csv)
    instead of duplicating the whole merge/keep dance for one caller.
    """
    from urllib.parse import urlencode
    merged = {k: f[k] for k in ("view", "days", "sort", "page", "q",
                                "lean", "verdict", "beat", "lang", "outlet",
                                "date_from", "date_to")}
    merged.update(override)
    keep = {k: v for k, v in merged.items()
            if v not in (None, "", "all") and not (k == "page" and v == 1)}
    return base_path + ("?" + urlencode(keep) if keep else "")


def _archive_page_links(f: dict, total: int):
    """Numbered page list with ellipsis gaps (design-handoff parity, #6149).

    Mirrors the design mockup's drawPager(): show 1, the last page, and a
    small window around the current page, with a gap marked by `None`
    wherever the run is not contiguous. No extra query — `total` and
    `_ARCHIVE_PAGE` are already known to the caller. Every URL reuses
    _archive_qs so the current filters ride along unchanged.

    Returns (links, cur_page) — cur_page is f["page"] clamped into
    [1, total_pages], since f["page"] itself is only lower-bounded
    (see _archive_filters) and a hand-edited ?page=999 must not crash
    the "which page is active" comparison in the template.
    """
    total_pages = max(1, (total + _ARCHIVE_PAGE - 1) // _ARCHIVE_PAGE)
    cur = min(max(1, f["page"]), total_pages)
    want = sorted({n for n in (1, total_pages, cur - 1, cur, cur + 1) if 1 <= n <= total_pages})
    links = []
    last = 0
    for n in want:
        if n - last > 1:
            links.append(None)
        links.append({"n": n, "url": _archive_qs(f, page=n)})
        last = n
    return links, cur


def _archive_rows(f: dict):
    """One query, two shapes.

    ⚠️ The story/article toggle is not cosmetic. 28,204 articles in 30 days
    collapse to far fewer stories, and a 16-outlet cluster repeats its headline
    16 times — which makes sorting by headline useless and inflates any count a
    reader takes as "how much happened". Grouping is the honest default.
    """
    S = _schema()
    where, p = _archive_where(f)
    order = _ARCHIVE_SORTS[f["sort"]][1]
    p["lim"] = _ARCHIVE_PAGE
    p["off"] = (f["page"] - 1) * _ARCHIVE_PAGE

    base = f"""
        FROM {S}.articles a
        JOIN {S}.sources s ON s.id = a.source_id
        LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
        LEFT JOIN LATERAL (
            SELECT overall_verdict FROM {S}.fact_checks
             WHERE article_id = a.id AND checker NOT LIKE 'GoogleFCT%%'
             ORDER BY created_at DESC LIMIT 1
        ) fc ON true
        LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
        WHERE {where}
    """
    if f["view"] == "story":
        sql = f"""
            SELECT MIN(a.cluster_id)                    AS cluster_id,
                   MIN(a.title)                         AS title,
                   MIN(s.name)                          AS outlet,
                   COUNT(DISTINCT a.source_id)          AS outlets,
                   MAX(a.published_at)                  AS last_pub,
                   MIN(b.band)                          AS lean,
                   MIN(fc.overall_verdict)              AS verdict,
                   MIN(a.id)                            AS article_id,
                   MIN(sc.coverage_gap_score)           AS coverage_gap_score,
                   MIN(sc.blindspot_side)               AS blindspot_side
            {base} AND a.cluster_id IS NOT NULL
            GROUP BY a.cluster_id
            ORDER BY {order} LIMIT :lim OFFSET :off
        """
    else:
        sql = f"""
            SELECT a.cluster_id, a.title, s.name AS outlet, 1 AS outlets,
                   a.published_at AS last_pub, b.band AS lean,
                   fc.overall_verdict AS verdict, a.id AS article_id,
                   sc.coverage_gap_score AS coverage_gap_score,
                   sc.blindspot_side AS blindspot_side
            {base}
            ORDER BY {order} LIMIT :lim OFFSET :off
        """
    with _db().begin() as c:
        return c.execute(text(sql), p).mappings().all()


def _archive_total(f: dict) -> int:
    S = _schema()
    where, p = _archive_where(f)
    inner = "COUNT(DISTINCT a.cluster_id)" if f["view"] == "story" else "COUNT(*)"
    extra = " AND a.cluster_id IS NOT NULL" if f["view"] == "story" else ""
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT {inner}
              FROM {S}.articles a
              JOIN {S}.sources s ON s.id = a.source_id
              LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
              LEFT JOIN LATERAL (
                  SELECT overall_verdict FROM {S}.fact_checks
                   WHERE article_id = a.id AND checker NOT LIKE 'GoogleFCT%%'
                   ORDER BY created_at DESC LIMIT 1
              ) fc ON true
             WHERE {where}{extra}
        """), p).scalar() or 0


def _archive_outlets(days: int):
    """Outlet options, most-published first.

    ⚠️ The prototype's control reads "All 33 outlets". There are 46 sources.
    The list is built from the DB so the label can never go stale again.
    """
    S = _schema()
    with _db().begin() as c:
        return [dict(r) for r in c.execute(text(f"""
            SELECT s.name, COUNT(*) AS n
              FROM {S}.articles a JOIN {S}.sources s ON s.id = a.source_id
             WHERE a.suppressed_reason IS NULL
               AND a.published_at > NOW() - make_interval(days => :days)
             GROUP BY s.name ORDER BY n DESC
        """), {"days": days}).mappings().all()]


def _archive_export_rows(f: dict):
    """Bounded, unpaginated rows for CSV export (#6149 batch 11).

    Mirrors _archive_rows' SQL shape rather than sharing it — the same
    trade-off _archive_total already makes for this page: a page/offset
    query and a bounded "give me everything up to the cap" query are
    different enough queries that reusing one via flags reads worse than
    two small, obviously-correct copies.
    """
    S = _schema()
    where, p = _archive_where(f)
    order = _ARCHIVE_SORTS[f["sort"]][1]
    p["lim"] = _ARCHIVE_EXPORT_LIMIT

    base = f"""
        FROM {S}.articles a
        JOIN {S}.sources s ON s.id = a.source_id
        LEFT JOIN {S}.bias_scores b ON b.article_id = a.id
        LEFT JOIN LATERAL (
            SELECT overall_verdict FROM {S}.fact_checks
             WHERE article_id = a.id AND checker NOT LIKE 'GoogleFCT%%'
             ORDER BY created_at DESC LIMIT 1
        ) fc ON true
        LEFT JOIN {S}.story_clusters sc ON sc.id = a.cluster_id
        WHERE {where}
    """
    if f["view"] == "story":
        sql = f"""
            SELECT MIN(a.cluster_id) AS cluster_id, MIN(a.title) AS title,
                   MIN(s.name) AS outlet, COUNT(DISTINCT a.source_id) AS outlets,
                   MAX(a.published_at) AS last_pub, MIN(b.band) AS lean,
                   MIN(fc.overall_verdict) AS verdict,
                   MIN(sc.coverage_gap_score) AS coverage_gap_score,
                   MIN(sc.blindspot_side) AS blindspot_side
            {base} AND a.cluster_id IS NOT NULL
            GROUP BY a.cluster_id
            ORDER BY {order} LIMIT :lim
        """
    else:
        sql = f"""
            SELECT a.cluster_id, a.title, s.name AS outlet, 1 AS outlets,
                   a.published_at AS last_pub, b.band AS lean,
                   fc.overall_verdict AS verdict,
                   sc.coverage_gap_score AS coverage_gap_score,
                   sc.blindspot_side AS blindspot_side
            {base}
            ORDER BY {order} LIMIT :lim
        """
    with _db().begin() as c:
        return c.execute(text(sql), p).mappings().all()


def _csv_filed_local(dt) -> str:
    """Local, human time for the export (#6149 batch 11).

    Storage is UTC; per timezone.md, anything user-facing renders in
    America/Toronto with an explicit EDT/EST suffix rather than an
    unlabelled or literally-"UTC" clock. Mirrors the one other place this
    file already does this (the /activity stats_as_of formatter, ~L1890) —
    same try/except-to-nothing shape: a formatting failure renders an empty
    cell, never a wrong or half-converted time.
    """
    if dt is None:
        return ""
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %-I:%M %p %Z")
    except Exception:
        return ""


def _csv_safe(value) -> str:
    """Defuse CSV formula injection (#6149 batch 11).

    Excel/Sheets treats a cell that STARTS with =, +, -, or @ as a formula
    to evaluate. Article titles are external RSS content this site does not
    control, so a headline that happens to start with one of those characters
    gets a defusing leading apostrophe rather than being handed to a
    spreadsheet as executable input.
    """
    s = "" if value is None else str(value)
    return ("'" + s) if s[:1] in ("=", "+", "-", "@") else s


@bp.get("/archive")
def archive_index():
    """The full archive — by story or by article (#6149 Design phase 2)."""
    from flask import request as _req
    f = _archive_filters(_req.args)
    rows = [dict(r) for r in _archive_rows(f)]
    for r in rows:
        r["age_text"] = _age_text(r["last_pub"])
        # Political-lean coverage imbalance (task #6524) — same column
        # /blindspot itself reads, precomputed by ingest/cluster_metrics.py.
        # NOT the outlet-count coverage_gap_score (still selected above,
        # still a real metric — just no longer what "Blindspot" means).
        r["is_blindspot"] = r.get("blindspot_side") is not None
    total = _archive_total(f)

    sub = is_subscriber()
    cap = _ARCHIVE_FREE_STORIES if f["view"] == "story" else _ARCHIVE_FREE_ARTICLES
    gated = (not sub) and len(rows) > cap
    if gated:
        rows = rows[:cap]

    # Numbered page list (design-handoff parity, #6149 batch 11 follow-up) —
    # only meaningful when the paywall isn't already replacing the pager.
    page_links, cur_page = _archive_page_links(f, total)

    return render_template("archive.html",
                           rows=rows, total=total, f=f,
                           sorts=_ARCHIVE_SORTS, windows=_ARCHIVE_WINDOWS,
                           outlets=_archive_outlets(f["days"]),
                           beats=sorted(VALID_BEATS),
                           page_size=_ARCHIVE_PAGE,
                           page_links=page_links, cur_page=cur_page,
                           is_subscriber=sub, gated=gated, cap=cap,
                           # URLs built server-side (see _archive_qs)
                           url_story=_archive_qs(f, view="story", page=1),
                           url_article=_archive_qs(f, view="article", page=1),
                           # Picking a preset window clears any custom date
                           # range — otherwise the range would silently keep
                           # overriding the window the reader just clicked.
                           url_windows=[(w, _archive_qs(f, days=w, page=1,
                                                         date_from=None, date_to=None))
                                        for w in _ARCHIVE_WINDOWS],
                           url_sorts=[(k, s[0], _archive_qs(f, sort=k, page=1))
                                      for k, s in _ARCHIVE_SORTS.items()],
                           url_clear=_archive_qs({**f, "q": "", "lean": "all", "verdict": "all",
                                                  "beat": "all", "lang": "all", "outlet": "all",
                                                  "date_from": None, "date_to": None}, page=1),
                           url_prev=_archive_qs(f, page=f["page"] - 1) if f["page"] > 1 else None,
                           url_next=_archive_qs(f, page=f["page"] + 1),
                           url_export=_archive_qs(f, base_path="/archive/export.csv", page=1),
                           # This page's own "Copy link" affordance: the exact
                           # current filter state, canonicalised the same way
                           # every other link on the page already is.
                           url_permalink=_archive_qs(f))


@bp.get("/archive/export.csv")
def archive_export():
    """CSV export of the current /archive filter view (#6149 batch 11, Starter+).

    Server-side and filter-matched — never a dump of whatever happened to be
    rendered on screen. Gated on the SAME is_subscriber() check the page
    itself already uses; this adds no new gating logic or tier, only a new
    action behind the existing gate (HARD RULE: never touch paywall scope).
    """
    from flask import request as _req

    if not is_subscriber():
        return redirect("/join?gated=export")

    f = _archive_filters(_req.args)
    rows = [dict(r) for r in _archive_export_rows(f)]

    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    outlet_header = "Outlets" if f["view"] == "story" else "Outlet"
    writer.writerow(["Filed", outlet_header, "Headline", "Lean", "Verdict",
                      "Blindspot", "Link"])
    for r in rows:
        filed = _csv_filed_local(r.get("last_pub"))
        verdict = (r.get("verdict") or "").replace("_", " ").title()
        # Political-lean coverage imbalance (task #6524) — same column
        # /blindspot itself reads. "L"/"R" names which side was silent;
        # blank means balanced or too thin to call.
        blindspot_side = r.get("blindspot_side")
        link = f"https://what-the-fact.com/cluster/{r['cluster_id']}" if r.get("cluster_id") else ""
        writer.writerow([
            _csv_safe(filed),
            _csv_safe(r.get("outlet") or r.get("outlets") or ""),
            _csv_safe(r.get("title") or ""),
            _csv_safe(r.get("lean") or ""),
            _csv_safe(verdict),
            _csv_safe(blindspot_side or ""),
            _csv_safe(link),
        ])

    resp = Response(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=wtf-archive-{f['view']}-{f['days']}d.csv"
    )
    return resp


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

        source_count = _active_source_count(c, S)
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
              AND a.suppressed_reason IS NULL
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
            ORDER BY decision_year DESC, (split_part(decision_number, '-', 2))::integer DESC
            LIMIT 500
        """.format("WHERE decision_type = :dtype" if dtype != "all" else "")
        params = {"dtype": dtype} if dtype != "all" else {}
        rows = c.execute(text(query), params).mappings().all()
        source_count = _active_source_count(c, S)
        # Unfiltered total for the paywall promo copy — decision_number is
        # "<year>-<seq>" (280/280 rows match, confirmed 2026-09-04), so ORDER BY
        # now sorts numerically instead of lexicographically (was letting
        # '2024-100' sort below '2024-99'). LIMIT 500 comfortably covers the
        # real 280-row table with room to grow; decisions|length in the
        # template is only accurate once the LIMIT isn't truncating it.
        total_rulings = c.execute(
            text("SELECT COUNT(*) FROM legal_watch.crtc_decisions")
        ).scalar()

        # Ownership concentration data for the CRTC panel.
        # bias_band mirrors ingest/outlet_bias.py's _BANDS thresholds exactly
        # (-0.6/-0.2/0.2/0.6, < wins, else 'right') — that module owns avg_score,
        # so its bucketing is the source of truth, not a re-derived one here.
        owner_rows = c.execute(text(f"""
            SELECT
                s.owner_name,
                s.owner_type,
                COUNT(s.id)                           AS outlet_count,
                ROUND(AVG(obs.avg_score)::numeric, 2) AS avg_bias,
                MIN(s.bias_lean)                      AS sample_lean,
                CASE
                    WHEN AVG(obs.avg_score) IS NULL THEN NULL
                    WHEN AVG(obs.avg_score) < -0.6 THEN 'left'
                    WHEN AVG(obs.avg_score) < -0.2 THEN 'center-left'
                    WHEN AVG(obs.avg_score) < 0.2  THEN 'center'
                    WHEN AVG(obs.avg_score) < 0.6  THEN 'center-right'
                    ELSE 'right'
                END                                    AS bias_band
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
                           total_rulings=total_rulings,
                           owners_summary=owners_summary,
                           concentration_badge=concentration_badge,
                           is_subscriber=is_subscriber())


@bp.get("/ethics")
def ethics_rulings():
    """Ethics Commissioner investigation reports."""
    from flask import request as _req
    q = (_req.args.get("q") or "").strip()
    with _db().begin() as c:
        clauses = []
        params = {}
        if q:
            clauses.append(
                "(e.report_name ILIKE :q OR e.subject_name ILIKE :q OR m.name ILIKE :q)"
            )
            params["q"] = f"%{q}%"
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = c.execute(text(f"""
            SELECT e.report_name, e.subject_name, e.ruling_date,
                   e.report_type, e.report_url, e.mp_slug,
                   m.name AS mp_name
            FROM legal_watch.ethics_rulings e
            LEFT JOIN parliament.mps m ON m.slug = e.mp_slug
            {where}
            ORDER BY e.ruling_date DESC
        """), params).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    rulings = [dict(r) for r in rows]
    # Header stats — computed from the rows already fetched above (WTF-11
    # batch, KB vault_note pending). Reflects the active search filter, same
    # "window" convention as /gic's stat row. `finding` is a real column on
    # legal_watch.ethics_rulings but is NULL on all 30 live rows (verified via
    # `docker exec archie_database psql -d wtf` 2026-09-04) — there is no
    # contravention/no-contravention text to classify a per-row "kind" badge
    # from, so none is built here; doing so would mean guessing outcomes.
    act_count = sum(1 for r in rulings if r.get("report_type") == "act")
    code_count = len(rulings) - act_count
    mp_linked_count = sum(1 for r in rulings if r.get("mp_slug"))
    return render_template("ethics.html",
                           rulings=rulings,
                           q=q,
                           act_count=act_count,
                           code_count=code_count,
                           mp_linked_count=mp_linked_count,
                           source_count=source_count,
                           is_subscriber=is_subscriber())


@bp.get("/gic")
def gic_appointments():
    """Governor in Council appointments — patronage tracking via Orders-in-Council."""
    from flask import request as _req
    dept = _req.args.get("dept", "all")
    q = (_req.args.get("q") or "").strip()
    with _db().begin() as c:
        clauses = []
        params = {}
        if dept != "all":
            clauses.append("department ILIKE :dept")
            params["dept"] = f"%{dept}%"
        if q:
            clauses.append(
                "(appointee_name ILIKE :q OR organization ILIKE :q OR pc_number ILIKE :q)"
            )
            params["q"] = f"%{q}%"
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT pc_number, oic_date, department, subject, precis,
                   oic_url, appointee_name, organization
            FROM gov_watch.gic_appointments
            {where}
            ORDER BY oic_date DESC, pc_number DESC
            LIMIT 200
        """
        rows = c.execute(text(query), params).mappings().all()
        depts = c.execute(text("""
            SELECT DISTINCT department FROM gov_watch.gic_appointments
            WHERE department IS NOT NULL ORDER BY department
        """)).scalars().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    # Header stats — computed from the rows/depts already fetched above, no
    # new query. "Vacant posts" from the mockup is deliberately NOT here: no
    # gov_watch.gic_vacancies (or equivalent) table exists anywhere in this
    # codebase, so a vacancy count would be fabricated (KB vault_note #304357).
    organisations_count = len({r["organization"] for r in rows if r["organization"]})
    return render_template("gic.html",
                           appointments=[dict(r) for r in rows],
                           depts=list(depts),
                           dept=dept,
                           q=q,
                           organisations_count=organisations_count,
                           departments_count=len(depts),
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
    q = (_req.args.get("q") or "").strip()
    cache_key = ("org", org.lower()) if org else ("index", q.lower())
    hit = _LOBBY_CACHE.get(cache_key)
    now = time.time()
    if hit and hit[0] > now:
        payload = hit[1]
    else:
        payload = _lobbying_payload(org, q)
        _LOBBY_CACHE[cache_key] = (now + _LOBBY_CACHE_TTL, payload)
    return render_template("lobbying.html", org=org, q=q, **payload,
                           is_subscriber=is_subscriber())


def _lobbying_payload(org: str, q: str = "") -> dict:
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
            # Monthly filing counts, real communication_date data already in
            # this table — no new schema. 24-month window keeps the bar chart
            # readable; a shorter real history renders fewer, honest bars.
            monthly = c.execute(text(f"""
                SELECT to_char(date_trunc('month', lc.communication_date), 'YYYY-MM') AS month,
                       count(*) AS n
                FROM parliament.lobbyist_contacts lc
                WHERE upper(btrim(lc.client_org)) = upper(:org) AND {_LOBBY_ORG_FILTER}
                  AND lc.communication_date >= CURRENT_DATE - INTERVAL '24 months'
                GROUP BY date_trunc('month', lc.communication_date)
                ORDER BY 1
            """), {"org": org}).mappings().all()
            return {"stats": stats, "detail": dict(detail),
                    "org_mps": [dict(r) for r in org_mps],
                    "contacts": [dict(r) for r in contacts],
                    "monthly": [dict(r) for r in monthly],
                    "top_orgs": [], "top_mps": [], "recent": []}

        top_orgs = c.execute(text(f"""
            SELECT (array_agg(lc.client_org ORDER BY lc.client_org))[1] AS org_label,
                   upper(btrim(lc.client_org)) AS org_key,
                   count(*) AS contacts, count(DISTINCT lc.mp_id) AS mps,
                   max(lc.communication_date) AS last_seen
            FROM parliament.lobbyist_contacts lc
            WHERE {_LOBBY_ORG_FILTER}
                  {"AND lc.client_org ILIKE :q" if q else ""}
            GROUP BY upper(btrim(lc.client_org))
            ORDER BY count(*) DESC
            LIMIT 40
        """), ({"q": f"%{q}%"} if q else {})).mappings().all()

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

    return {"stats": stats, "detail": None, "org_mps": [], "contacts": [], "monthly": [],
            "top_orgs": [dict(r) for r in top_orgs],
            "top_mps": [dict(r) for r in top_mps],
            "recent": [dict(r) for r in recent]}


# ── /rates support (Batch 11, #6272 follow-up) ──────────────────────────────
# market_watch.boc_rate_decisions is a MONTHLY average of the BoC Valet
# series V122514 (one row per calendar month), not literal per-announcement
# rows — real BoC decisions land only 8x/year on fixed dates, but the ingest
# (ingest/market/boc_rates.py) records the realized monthly average, which
# drifts by a few bps even in months the Bank held. "Material move" below
# means the SAME >=10bps threshold the decisions-table query already uses to
# separate a real cut/hike from monthly averaging noise — reusing it (rather
# than inventing a second threshold) keeps the stat tiles and the table
# honestly describing the same events.
#
# All three helpers are pure (no DB): they take `history`, the FULL ascending
# (decision_date, rate_pct, change_bps) series, and are anchored on the
# dataset's own latest row rather than wall-clock time, so a stale ingest
# cannot claim a "peak" or a "streak" that hasn't happened in the data yet.

_BOC_MATERIAL_BPS = 10

# Era boundaries are well-established Bank of Canada / Canadian monetary
# policy history (dot-com bust, 2008 financial crisis, 2015 oil shock,
# COVID-19, the 2022-23 hiking cycle) — public facts, not derived from this
# table. The min/max rate shown for each era IS derived from the real data
# below; the boundary years and one-line context are not.
_BOC_ERAS = [
    ("Dot-com bust & post-9/11 easing", 2001, 2002,
     "Rates were cut sharply after the dot-com crash and the September 11 attacks."),
    ("Mid-2000s tightening", 2004, 2007,
     "A multi-year hiking cycle as the economy expanded, ending just before the 2008 crisis."),
    ("Global financial crisis", 2008, 2009,
     "Rates were cut aggressively toward zero as the global financial system seized up."),
    ("Oil shock & normalization", 2015, 2018,
     "The 2014-15 oil price collapse hit the Canadian economy; the Bank cut in 2015, "
     "then raised rates gradually through 2018."),
    ("Pandemic & inflation surge", 2020, 2023,
     "Rates were slashed toward zero during COVID-19, then raised at the fastest pace "
     "in decades to fight the inflation that followed."),
    ("Easing cycle", 2024, None,
     "The Bank has been lowering its policy rate as inflation cooled."),
]


def _boc_shift_years(d, delta_years):
    """date +/- N years, Feb-29-safe. Every row in this table is the 1st of
    a month, so the leap fallback never actually fires — kept for safety."""
    try:
        return d.replace(year=d.year + delta_years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + delta_years)


def _boc_hold_streak(history):
    """Consecutive most-recent months with no move >= _BOC_MATERIAL_BPS,
    counting back from the latest row. Returns None for an empty series,
    else {'months': int, 'since': date|None} where `since` is the first
    month of the current streak (the month right after the last material
    move, or the first row on record if the series has never had one)."""
    if not history:
        return None
    n = len(history)
    i = n - 1
    while i >= 0:
        bps = history[i].get("change_bps")
        if bps is None or abs(bps) >= _BOC_MATERIAL_BPS:
            break
        i -= 1
    since_idx = i + 1
    months = n - since_idx
    since = history[since_idx]["decision_date"] if 0 <= since_idx < n else None
    return {"months": months, "since": since}


def _boc_peak_since(history, years=5):
    """The highest reading of the current cycle (within `years` of the
    dataset's own latest row) and the bps change from there to now. The
    window is wide enough to hold a full hiking-to-holding cycle (the
    2022-2024 cycle peaked ~18 months before its hold ended) while excluding
    unrelated older peaks. Falls back to the full series if `years` finds
    nothing (a young or sparse dataset)."""
    if not history:
        return None
    latest = history[-1]
    cutoff = _boc_shift_years(latest["decision_date"], -years)
    window = [r for r in history if r["decision_date"] >= cutoff] or history
    peak = max(window, key=lambda r: r["rate_pct"])
    bps_change = round((float(latest["rate_pct"]) - float(peak["rate_pct"])) * 100)
    return {
        "peak_date": peak["decision_date"],
        "peak_rate": peak["rate_pct"],
        "current_rate": latest["rate_pct"],
        "bps_change": bps_change,
    }


def _boc_eras(history):
    """Real min/max rate observed in this table within each well-known era
    window (see _BOC_ERAS). Skips an era entirely if the table holds no rows
    for it (never renders a fabricated range)."""
    if not history:
        return []
    latest_year = history[-1]["decision_date"].year
    out = []
    for name, start_year, end_year, note in _BOC_ERAS:
        hi_year = end_year if end_year is not None else latest_year
        window = [r for r in history if start_year <= r["decision_date"].year <= hi_year]
        if not window:
            continue
        lo = min(window, key=lambda r: r["rate_pct"])
        hi = max(window, key=lambda r: r["rate_pct"])
        out.append({
            "label": f"{start_year}–{end_year if end_year else ''}",
            "name": name,
            "note": note,
            "low": lo["rate_pct"],
            "high": hi["rate_pct"],
        })
    return out


def _boc_rate_chart(history, width=720, height=200, pad=28):
    """Hand-rolled SVG polyline geometry for the public rate-path chart — no
    chart library. Returns None when there's nothing to plot (0 or 1 row,
    which can't form a line)."""
    if not history or len(history) < 2:
        return None
    dates = [r["decision_date"] for r in history]
    rates = [float(r["rate_pct"]) for r in history]
    t0, t1 = dates[0].toordinal(), dates[-1].toordinal()
    span = (t1 - t0) or 1
    lo, hi = min(rates), max(rates)
    rspan = (hi - lo) or 1.0

    def _x(d):
        return pad + (d.toordinal() - t0) / span * (width - 2 * pad)

    def _y(v):
        return height - pad - (v - lo) / rspan * (height - 2 * pad)

    points = " ".join(f"{_x(d):.1f},{_y(v):.1f}" for d, v in zip(dates, rates))

    # Axis scaffolding (Batch 11 design-reconciliation follow-up). The mockup
    # draws whole-percent gridlines + year tick labels around this same
    # polyline; the prior version returned only the line geometry, so the
    # live chart had no scale reference at all. Gridlines bracket the real
    # [lo, hi] range (never a hardcoded 0-6%) so a series that never touches
    # those extremes doesn't draw a tick past its own data.
    lo_grid = int(lo) if lo == int(lo) else int(lo) - (1 if lo < 0 else 0)
    hi_grid = int(hi) if hi == int(hi) else int(hi) + 1
    gridlines = [{"value": v, "y": round(_y(v), 1)} for v in range(lo_grid, hi_grid + 1)]

    # Year ticks every 5 years, same cadence as the mockup, generalized to
    # whatever span the data actually covers rather than a hardcoded
    # 2000-2025 — only ticks that fall inside the real date range are kept.
    y0 = (dates[0].year // 5) * 5
    year_ticks = [
        {"year": yr, "x": round(_x(datetime.date(yr, 1, 1)), 1)}
        for yr in range(y0, dates[-1].year + 1, 5)
        if dates[0] <= datetime.date(yr, 1, 1) <= dates[-1]
    ]

    return {
        "width": width, "height": height, "points": points,
        "min_rate": lo, "max_rate": hi,
        "start_date": dates[0], "end_date": dates[-1],
        "end_x": round(_x(dates[-1]), 1), "end_y": round(_y(rates[-1]), 1),
        "gridlines": gridlines, "year_ticks": year_ticks, "xaxis_y": height - 8, "pad": pad,
    }


def _econ_mini_chart(series, width=220, height=54, pad=4):
    """Hand-rolled SVG polyline for a small /economy indicator-card chart —
    same linear x/y scaling as _boc_rate_chart, generalized to any (date,
    value) series and sized for a grid card rather than a full-page chart.
    `series` is a list of (date, value) tuples, oldest first. Returns None
    when there's nothing to plot (0 or 1 point, which can't form a line)."""
    if not series or len(series) < 2:
        return None
    dates = [s[0] for s in series]
    vals = [float(s[1]) for s in series]
    t0, t1 = dates[0].toordinal(), dates[-1].toordinal()
    span = (t1 - t0) or 1
    lo, hi = min(vals), max(vals)
    rspan = (hi - lo) or 1.0

    def _x(d):
        return pad + (d.toordinal() - t0) / span * (width - 2 * pad)

    def _y(v):
        return height - pad - (v - lo) / rspan * (height - 2 * pad)

    points = " ".join(f"{_x(d):.1f},{_y(v):.1f}" for d, v in zip(dates, vals))
    return {
        "width": width, "height": height, "points": points,
        "end_x": round(_x(dates[-1]), 1), "end_y": round(_y(vals[-1]), 1),
    }


def _econ_cpi_yoy(rows):
    """Year-over-year %% change from raw StatCan CPI index rows (each a
    dict with ref_date/value, oldest first, ref_date always the 1st of a
    month). A point requires the same calendar month exactly 12 months
    earlier to also be present in `rows` — returns fewer points (or [])
    rather than guess at a rate when there isn't 12 months of history
    behind a given row yet. The raw index is stored by the ingest; this
    view is computed here, never baked into storage (mirrors how /rates
    derives peak/hold-streak stats from raw rate_pct rows)."""
    by_date = {r["ref_date"]: float(r["value"]) for r in rows}
    out = []
    for r in rows:
        d = r["ref_date"]
        prior = datetime.date(d.year - 1, d.month, 1)
        base = by_date.get(prior)
        if base:
            out.append((d, (float(r["value"]) / base - 1) * 100))
    return out


def _econ_gdp_mom(rows):
    """Month-over-month %% change from raw StatCan GDP level rows (each a
    dict with ref_date/value, oldest first). Plain consecutive-row delta —
    no synthetic first point, no fabricated value when a row is missing
    (a gap just means one fewer point, not an interpolated one)."""
    out = []
    prev = None
    for r in rows:
        if prev is not None and prev["value"]:
            out.append((r["ref_date"], (float(r["value"]) / float(prev["value"]) - 1) * 100))
        prev = r
    return out


def _econ_indicator(*, key, name, value, unit, source, href, series, decimals=1, signed=False):
    """Assembles one /economy indicator card's template data from a plain
    (date, value) series (oldest first, already capped to the window the
    caller wants shown). Formats the current value, and — only when the
    series has 2+ points — the change from the series' own first point to
    its last (never a synthetic baseline). `signed` puts a '+' on a
    positive current value (used only for GDP month-over-month, which
    fluctuates around zero and needs the sign to read at a glance — the
    other five indicators don't carry a '+' in the design either)."""
    value = float(value)
    prefix = "+" if signed and value > 0 else ""
    display_value = f"{prefix}{value:.{decimals}f}{unit}"
    delta = None
    if len(series) >= 2:
        first_v, last_v = float(series[0][1]), float(series[-1][1])
        d = round(last_v - first_v, decimals)
        dprefix = "+" if d > 0 else ""
        delta = {
            "start_date": series[0][0], "end_date": series[-1][0],
            "text": f"{dprefix}{d}{unit}",
        }
    return {
        "key": key, "name": name, "value": display_value,
        "source": source, "href": href,
        "as_of": series[-1][0] if series else None,
        "chart": _econ_mini_chart(series),
        "delta": delta,
    }


@bp.get("/rates")
def boc_rates():
    """Bank of Canada overnight rate decisions."""
    with _db().begin() as c:
        current = c.execute(text("""
            SELECT rate_pct, decision_date
            FROM market_watch.boc_rate_decisions
            ORDER BY decision_date DESC LIMIT 1
        """)).mappings().first()
        # No LIMIT — same "full series, no cap" convention the `history`
        # query below already uses on this table. A LIMIT 60 here used to
        # cap the gated table to the last ~5 years (most months in a long
        # hold stretch carry change_bps=0 and so qualify), which quietly
        # contradicted the page's own "full series back to 2000" framing.
        # The table is monthly-granularity and bounded (~300 rows since
        # 2000), so this is not an unbounded/slow query.
        decisions = c.execute(text("""
            SELECT decision_date, rate_pct, change_bps
            FROM market_watch.boc_rate_decisions
            WHERE ABS(change_bps) >= 10 OR change_bps = 0 OR change_bps IS NULL
            ORDER BY decision_date DESC
        """)).mappings().all()
        # Full ascending series (no filter, no limit) for the public
        # historical-path chart + era stats + the peak/streak tiles below.
        # `decisions` above stays a display-limited, gated list — this is a
        # separate, ungated read of the same table (#6272 follow-up, Batch 11).
        history = c.execute(text("""
            SELECT decision_date, rate_pct, change_bps
            FROM market_watch.boc_rate_decisions
            ORDER BY decision_date ASC
        """)).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0

    history = [dict(r) for r in history]
    return render_template("rates.html",
                           current=dict(current) if current else {},
                           decisions=[dict(r) for r in decisions],
                           source_count=source_count,
                           chart=_boc_rate_chart(history),
                           eras=_boc_eras(history),
                           peak_stat=_boc_peak_since(history),
                           hold_streak=_boc_hold_streak(history),
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
                MIN(s.bias_lean)                         AS sample_lean,
                -- bias_band mirrors ingest/outlet_bias.py's _BANDS thresholds
                -- (-0.6/-0.2/0.2/0.6, less-than wins, else 'right') — same
                -- pattern as /crtc's owner-concentration panel. Without this,
                -- owners.html's is-bias-band-set Jinja check was always false
                -- (the column never existed) and the aggregate lean pill
                -- silently never rendered for any owner.
                CASE
                    WHEN AVG(obs.avg_score) IS NULL THEN NULL
                    WHEN AVG(obs.avg_score) < -0.6 THEN 'left'
                    WHEN AVG(obs.avg_score) < -0.2 THEN 'center-left'
                    WHEN AVG(obs.avg_score) < 0.2  THEN 'center'
                    WHEN AVG(obs.avg_score) < 0.6  THEN 'center-right'
                    ELSE 'right'
                END                                       AS bias_band
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
        source_count = _active_source_count(c, S)
        # The seat-distribution bar's majority line needs the REAL total seat
        # count, unconditionally — NOT len(mps), which is party/province-
        # FILTERED when those query params are set, and NOT a hardcoded 338/343:
        # measured live 2026-09-03, is_current=true returns 337, not the
        # textbook 343 (vacant seats awaiting byelections are real and drift
        # the count independently of any code change here).
        total_seats = c.execute(text(
            "SELECT COUNT(*) FROM parliament.mps WHERE is_current = true"
        )).scalar() or 0
        # COALESCE is load-bearing: the template does `groupby('caucus')`, and
        # Jinja's groupby SORTS by key — None < str raises TypeError and 500s
        # the whole page. A freshly-appointed senator legitimately has no
        # caucus yet (2026-08-18: three appointees took /mps down for ~2.5h).
        # 'Non-affiliated' is also the factual label for a new appointee.
        senators = c.execute(text("""
            SELECT slug, name, given_name, family_name,
                   COALESCE(caucus, 'Non-affiliated') AS caucus,
                   province, photo_url, profile_url, appointed_at, date_of_birth
            FROM parliament.senators WHERE is_current = true
            ORDER BY COALESCE(caucus, 'Non-affiliated'), name
        """)).mappings().all()
        # "Same bill, both chambers" (#batch11): a bill with a recorded
        # division in BOTH parliament.bills (House) and parliament.senate_votes
        # (Senate) — both tables already exist and are ingested independently
        # of this route, so this is one more query over already-available
        # data, not a new source. Joined on (bill_number, session) together —
        # bill numbers restart every Parliament (measured: parliament.bills
        # spans sessions 39-1..45-1, parliament.senate_votes only has 45-1),
        # so matching bill_number alone would pair a 2015-era House bill with
        # a 2026 Senate vote. DISTINCT ON picks each chamber's MOST RECENT
        # division per bill first (a bill can have several readings/
        # amendments per chamber), then the two latest rows are joined.
        same_bill_rows = c.execute(text("""
            WITH house_latest AS (
                SELECT DISTINCT ON (bill_number, session)
                       bill_number, session, description_en, vote_date, result,
                       yea_total, nay_total
                FROM parliament.bills
                WHERE bill_number IS NOT NULL AND btrim(bill_number) <> ''
                ORDER BY bill_number, session, vote_date DESC NULLS LAST
            ),
            senate_latest AS (
                SELECT DISTINCT ON (bill_number, session)
                       bill_number, session, title, vote_date, result,
                       yea_total, nay_total
                FROM parliament.senate_votes
                WHERE bill_number IS NOT NULL AND btrim(bill_number) <> ''
                ORDER BY bill_number, session, vote_date DESC NULLS LAST
            )
            SELECT h.bill_number, h.session,
                   h.description_en AS house_desc, h.vote_date AS house_date,
                   h.result AS house_result, h.yea_total AS house_yea, h.nay_total AS house_nay,
                   s.title AS senate_desc, s.vote_date AS senate_date,
                   s.result AS senate_result, s.yea_total AS senate_yea, s.nay_total AS senate_nay
            FROM house_latest h
            JOIN senate_latest s ON s.bill_number = h.bill_number AND s.session = h.session
            ORDER BY GREATEST(h.vote_date, s.vote_date) DESC NULLS LAST
            LIMIT 8
        """)).mappings().all()

    # Retirement-wave chart (#batch11): senators face MANDATORY retirement
    # the calendar year they turn 75 (year-only — same simplification the
    # individual /senator/<slug> page already makes for its own countdown;
    # it ignores exact month/day). Computed here, BEFORE date_of_birth is
    # dropped from senators_list below: the roster page's JSON/HTML has no
    # reason to ship every sitting senator's exact birthdate to the browser
    # just to show a bar chart — only the derived retirement YEAR is needed
    # client-side (added back per-senator as retirement_year further down,
    # for the "retiring soonest" sort).
    senators_dicts = [dict(s) for s in senators]
    senators_missing_dob = sum(1 for s in senators_dicts if not s.get("date_of_birth"))
    _retirement_counts: dict = {}
    for _s in senators_dicts:
        _dob = _s.get("date_of_birth")
        if not _dob:
            continue
        _yr = _dob.year + 75
        _retirement_counts[_yr] = _retirement_counts.get(_yr, 0) + 1
    if _retirement_counts:
        _yr_lo, _yr_hi = min(_retirement_counts), max(_retirement_counts)
        # Fill every year in the span, not just years with a retirement —
        # a gap year with 0 is real information (no forced turnover that
        # year), not a row to silently drop.
        retirement_wave = [
            {"year": y, "count": _retirement_counts.get(y, 0)}
            for y in range(_yr_lo, _yr_hi + 1)
        ]
    else:
        retirement_wave = []
    max_retirement_count = max((p["count"] for p in retirement_wave), default=0)

    senators_list = []
    for _s in senators_dicts:
        _row = {k: v for k, v in _s.items() if k != "date_of_birth"}
        _dob = _s.get("date_of_birth")
        _row["retirement_year"] = (_dob.year + 75) if _dob else None
        senators_list.append(_row)

    mps = []
    for r in rows:
        mp = dict(r)
        if mp.get("photo_url") and not mp["photo_url"].startswith("http"):
            mp["photo_url"] = _OPENPARL_BASE + mp["photo_url"]
        mp["party_colour"] = _party_colour(mp.get("party") or "")
        mps.append(mp)

    # Seats-by-province panel (#batch11) — a plain count over the SAME `mps`
    # list this request already fetched (so it respects whatever party/
    # province filter is active, same as every other panel on this page) —
    # never a second query. Province/territory full names are a fixed,
    # well-established public fact table (there are exactly 13), not
    # derived from any DB row.
    _PROVINCE_NAMES = {
        "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
        "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
        "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
        "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
        "SK": "Saskatchewan", "YT": "Yukon",
    }
    _province_counts: dict = {}
    for mp in mps:
        _code = mp.get("province_code")
        if not _code:
            continue
        _province_counts[_code] = _province_counts.get(_code, 0) + 1
    province_seats = sorted(
        (
            {"code": code, "name": _PROVINCE_NAMES.get(code, code), "count": cnt}
            for code, cnt in _province_counts.items()
        ),
        key=lambda p: p["count"],
        reverse=True,
    )

    # Vote share per chamber for the "same bill" panel — yea/(yea+nay), same
    # semantics the mockup's own note describes ("the bar is the yea share of
    # that vote, not support in the country"). Paired/abstention/absent
    # ballots are deliberately excluded from the denominator: they are not a
    # "no", and folding them in would understate a lopsided division.
    same_bill_votes = []
    for _b in same_bill_rows:
        _b = dict(_b)
        _h_total = (_b.get("house_yea") or 0) + (_b.get("house_nay") or 0)
        _s_total = (_b.get("senate_yea") or 0) + (_b.get("senate_nay") or 0)
        _b["house_yea_pct"] = round(_b["house_yea"] / _h_total * 100, 1) if _h_total else None
        _b["senate_yea_pct"] = round(_b["senate_yea"] / _s_total * 100, 1) if _s_total else None
        same_bill_votes.append(_b)

    return render_template("mps.html", mps=mps, parties=list(parties),
                           provinces=list(provinces), party_filter=party_filter,
                           province_filter=province_filter, source_count=source_count,
                           senators=senators_list, total_seats=total_seats,
                           retirement_wave=retirement_wave,
                           max_retirement_count=max_retirement_count,
                           senators_missing_dob=senators_missing_dob,
                           province_seats=province_seats,
                           same_bill_votes=same_bill_votes)


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
    mp["party_colour"] = _party_colour(mp.get("party") or "")
    # parl_mp_id is stored as the literal text "['88515']" (a stringified
    # Python list from the ingest script, not an actual array column —
    # confirmed via \d parliament.mps: character varying). 337/337 current
    # MPs match this single-numeric-id pattern (verified 2026-09-04). The
    # mockup's own slug-based House of Commons URL
    # (ourcommons.ca/members/en/<slug>) was tested live and silently
    # redirects to the generic member-search page for every MP — the
    # numeric-id form (ourcommons.ca/Members/en/<id>) is the one confirmed
    # to load the actual profile.
    _hoc_id_match = re.search(r"\d+", mp.get("parl_mp_id") or "")
    mp["hoc_member_id"] = _hoc_id_match.group(0) if _hoc_id_match else None

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

        source_count = _active_source_count(c, S)

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

    # Caucus prev/next navigation (design-parity gap, mockup wtf-mp.js).
    # Same table/filter idiom as the /mps listing route above
    # (is_current=true AND party=:party, ORDER BY name) — 337 current MPs
    # total, so a per-party slice is a handful of rows; no new index needed.
    peer_mps = []
    prev_mp = None
    next_mp = None
    if mp.get("party"):
        with _db().begin() as c:
            peer_mps = [dict(r) for r in c.execute(text("""
                SELECT slug, name FROM parliament.mps
                WHERE is_current = true AND party = :party
                ORDER BY name
            """), {"party": mp["party"]}).mappings().all()]
        if len(peer_mps) > 1:
            _peer_idx = next(
                (i for i, p in enumerate(peer_mps) if p["slug"] == mp["slug"]), None
            )
            if _peer_idx is not None:
                prev_mp = peer_mps[_peer_idx - 1] if _peer_idx > 0 else peer_mps[-1]
                next_mp = peer_mps[_peer_idx + 1] if _peer_idx < len(peer_mps) - 1 else peer_mps[0]

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
                           peer_mps=peer_mps, prev_mp=prev_mp, next_mp=next_mp,
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
        # ⚠️ A per-row correlated subquery joining {SH}.entity_mentions (2.15M
        # rows) to {S}.articles here — evaluated once per candidate journalist,
        # unbounded by any shared index on the text-cast join — measured >30s
        # and hung under load (#6244 follow-up). A first fix (bulk CTE over
        # ALL entities, no candidate pre-filter) worked here only because
        # 'journalist' is a small population — the SAME shape still hung on
        # /api/entities/search?type=mp ('person' is much larger and the
        # planner built the join before applying the narrowing filter).
        # Filtering to the candidate set FIRST, then bounding entity_mentions
        # to just those ids, is the version proven fast on both populations
        # (~1.9s here measured via EXPLAIN ANALYZE).
        rows = c.execute(text(f"""
            WITH candidates AS (
                SELECT e.id, e.canonical_name, e.slug, e.aliases
                  FROM {SH}.entities e
                 WHERE e.entity_type='journalist'
            ),
            visible_counts AS (
                SELECT em.entity_id, count(DISTINCT em.content_id) AS article_count
                FROM {SH}.entity_mentions em
                JOIN {S}.articles art ON art.id::text = em.content_id
                WHERE em.product='wtf' AND em.content_type='article'
                  AND art.suppressed_reason IS NULL
                  AND em.entity_id IN (SELECT id FROM candidates)
                GROUP BY em.entity_id
            ),
            -- Per-journalist outlet counts, same join shape as visible_counts
            -- (candidates already narrowed, same tables) plus one join to
            -- {S}.sources — not a second slow correlated-subquery pass.
            -- Lean is attributed to the OUTLET (sources.bias_lean, the
            -- site's existing stable per-source vocabulary everywhere else),
            -- never to the person — a journalist writing for one outlet does
            -- not inherit an individual bias score just from that byline.
            outlet_counts AS (
                SELECT em.entity_id, src.name AS outlet_name, src.bias_lean AS outlet_lean,
                       count(DISTINCT em.content_id) AS n
                FROM {SH}.entity_mentions em
                JOIN {S}.articles art ON art.id::text = em.content_id
                JOIN {S}.sources src ON src.id = art.source_id
                WHERE em.product='wtf' AND em.content_type='article'
                  AND art.suppressed_reason IS NULL
                  AND em.entity_id IN (SELECT id FROM candidates)
                GROUP BY em.entity_id, src.name, src.bias_lean
            ),
            top_outlet AS (
                SELECT DISTINCT ON (entity_id) entity_id, outlet_name, outlet_lean
                FROM outlet_counts
                ORDER BY entity_id, n DESC
            )
            SELECT c.id, c.canonical_name, c.slug,
                   COALESCE(vc.article_count, 0) AS article_count,
                   t.outlet_name, t.outlet_lean
              FROM candidates c
              LEFT JOIN visible_counts vc ON vc.entity_id = c.id
              LEFT JOIN top_outlet t ON t.entity_id = c.id
             WHERE (:q='' OR lower(c.canonical_name) LIKE :like
                    OR EXISTS (SELECT 1 FROM unnest(c.aliases) al WHERE lower(al) LIKE :like))
             ORDER BY article_count DESC NULLS LAST, c.canonical_name ASC
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
                f"WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article' "
                f"AND a.suppressed_reason IS NULL")
        article_count = c.execute(
            text(f"SELECT count(DISTINCT a.id) {join}"), {"e": entity_id}
        ).scalar() or 0
        outlets = c.execute(text(f"""
            SELECT src.slug, src.name, count(DISTINCT a.id) n
              FROM {SH}.entity_mentions em JOIN {S}.articles a ON a.id::text=em.content_id
              JOIN {S}.sources src ON src.id=a.source_id
             WHERE em.entity_id=:e AND em.product='wtf' AND em.content_type='article'
               AND a.suppressed_reason IS NULL
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
                  JOIN {S}.articles a ON a.id::text = em1.content_id AND a.suppressed_reason IS NULL
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
                  JOIN {S}.articles a ON a.id::text = em1.content_id AND a.suppressed_reason IS NULL
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
    """Ranked list of entities spanning >=2 Watch products, shared across every
    gunicorn worker via wtf.cross_watch_snapshot (migration 075, #6166).

    The ranking GROUP BY over entity_mentions now measures 5.47s SOLO on an
    idle DB (~8x its ~670ms cost when this cache was first written — the
    #5799 entity-graph backfill grew entity_mentions to ~2.15M rows). A plain
    in-process dict here meant 4 independent per-worker caches (wtf-consumer
    runs --workers 4 --max-requests), so a worker recycle — or simply 4
    concurrent cold workers each running the same 5.47s scan against the one
    hub DB — could turn a 5.47s solo query into the >25s client timeout
    measured during the #6149 regression sweeps (the 2026-06-15
    shared-gunicorn DoS lesson, recurring). A tiny in-process read-through
    layer stays on top (this dict) purely to skip even the snapshot-table
    round trip on the hottest path; the shared DB row is what stops the
    4-workers-recompute-independently multiplication.
    """
    now = time.time()
    if _CROSSWATCH_CACHE.get("ts", 0) + _CROSSWATCH_CACHE_TTL > now:
        return _CROSSWATCH_CACHE.get("data", [])

    from . import cross_watch_snapshot as _cwsnap
    try:
        _shared = _cwsnap.read_snapshot(c)
    except Exception:
        _shared = None
    if _shared is not None:
        _CROSSWATCH_CACHE["ts"] = now
        _CROSSWATCH_CACHE["data"] = _shared
        return _shared

    _started = time.time()
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
    try:
        _cwsnap.write_snapshot(c, data, duration_ms=int((time.time() - _started) * 1000))
    except Exception:
        pass  # optimisation only — the page already has its answer
    _CROSSWATCH_CACHE["ts"] = now
    _CROSSWATCH_CACHE["data"] = data
    return data


@bp.get("/cross-watch")
def cross_watch_explorer():
    """Cross-Watch explorer (#3331 1c, filters + stats Batch 11 #6272-series) —
    browse/search entities resolved across the Watch Series. Default = top entities
    spanning the most products (cached); ?q= searches by name/alias; ?type=
    person|organization and ?min=2|3 narrow the SHOWN rows via a plain Python
    post-filter over the already-fetched population — deliberately NOT a new SQL
    query. A fresh GROUP BY over shared.entity_mentions (~2.15M rows) HAVING
    count(DISTINCT product)>=N measures ~5.8s solo on an idle DB regardless of
    whether array_agg is included (verified live, 2026-09-04) — exactly the cost
    migration 075's cross_watch_snapshot cache exists to avoid on every request, so
    a `min` value below the cached floor of 2 is deliberately not offered (it would
    need a second cached population, or a live query per request).

    `min_required` is also applied as the DEFAULT floor on ?q= search hits, which
    previously had no product-count floor at all — a single-product name could
    appear on a page titled "entities resolved across the Watch Series". Public;
    each result links to its /entity/<id> footprint."""
    S = _schema()
    SH = os.environ.get("WTF_SHARED_SCHEMA", "shared")
    q = (request.args.get("q") or "").strip()
    type_filter = (request.args.get("type") or "").strip().lower()
    if type_filter not in ("person", "organization"):
        type_filter = ""
    min_filter = request.args.get("min") or "2"
    if min_filter not in ("2", "3"):
        min_filter = "2"
    min_required = 3 if min_filter == "3" else 2
    with _db().begin() as c:
        source_count = c.execute(text(f"SELECT count(*) FROM {S}.sources")).scalar() or 0
        # Always computed (cache-backed via _crosswatch_top -> cross_watch_snapshot) —
        # feeds the #cw-stats aggregate row, which describes the canonical
        # cross-linked population regardless of any active search/filter below.
        top_entities = _crosswatch_top(c, SH)
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
            entities = top_entities
    if type_filter:
        entities = [e for e in entities if e["type"] == type_filter]
    entities = [e for e in entities if len(e["products"]) >= min_required]
    return render_template("cross_watch.html", entities=entities, q=q,
                           type_filter=type_filter, min_filter=min_filter,
                           top_entities=top_entities,
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
            source_count = _active_source_count(c, S)
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
    # ⚠️ source_count is computed for BOTH branches. It used to be assigned only
    # inside `if q:` with `else: source_count = 0`, so the landing state — the one
    # page that wants to say how many sources are searchable — received a hardcoded
    # 0 and could never display it. The template's "Across N sources" was therefore
    # unreachable by construction while looking implemented. Live value is 41.
    source_count = 0
    with _db().begin() as c:
        c.execute(text("SET LOCAL jit = off"))
        source_count = _active_source_count(c, S)
        if q:
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
        "Disallow: /literacy/score\n"
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
            JOIN {S}.articles a ON a.cluster_id = sc.id AND a.suppressed_reason IS NULL
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
            WHERE a.published_at > {floor_clause} AND a.suppressed_reason IS NULL
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
            WHERE a.published_at > {floor_clause} AND a.suppressed_reason IS NULL
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
# Blindspot Feed (#3006, redesigned task #6524) — political-LEAN coverage
# imbalance: a story covered almost entirely by one side of the spectrum.
# NOT outlet-count silence (that's coverage_gap_score, still a real column,
# just no longer what this page or the "Blindspot" badge elsewhere means —
# see migration 079 + ingest/cluster_metrics.py's _blindspot_side()).
# ───────────────────────────────────────────────────────────────────────────


_BLINDSPOT_WINDOWS = (3, 7, 14, 30)


def _blindspot_total(days=7):
    """How many stories QUALIFY in this window — not how many are shown.

    Mirrors _blindspot_rows' own caveat: the qualifying population can run
    far larger than the page size. Surfaced honestly rather than confusing
    the two.
    """
    S = _schema()
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT count(*) FROM {S}.story_clusters sc
            WHERE sc.blindspot_side IS NOT NULL
              AND sc.latest_published_at >= NOW() - INTERVAL '1 day' * :days
              AND EXISTS (
                  SELECT 1 FROM {S}.articles a
                  WHERE a.cluster_id = sc.id
                    AND (a.country_code = 'CA'
                         OR a.geo_scope IN ('national', 'provincial'))
              )
        """), {"days": days}).scalar() or 0


def _blindspot_rows(days=7, limit=20):
    """Rows behind BOTH /blindspot and /api/v1/blindspot.

    Extracted so the page and the API cannot drift: a blindspot shown to a
    reader and one returned to an API client must be the same story set.
    `province_code`/`beat` are pulled from one representative article in the
    cluster (story_clusters carries neither column itself) — good enough for
    the "why is this side silent" panel, which only needs a rough locale/topic,
    not a per-article breakdown.
    """
    S = _schema()
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.source_count, sc.coverage_gap_score, sc.certainty_label,
                   sc.blindspot_side, sc.lean_l_count, sc.lean_c_count,
                   sc.lean_r_count, sc.earliest_published_at, sc.latest_published_at,
                   sm.headline, sm.brief,
                   (SELECT a2.province_code FROM {S}.articles a2
                     WHERE a2.cluster_id = sc.id AND a2.province_code IS NOT NULL
                     LIMIT 1)                                          AS province_code,
                   (SELECT a2.beat FROM {S}.articles a2
                     WHERE a2.cluster_id = sc.id AND a2.beat IS NOT NULL
                     LIMIT 1)                                          AS beat
            FROM {S}.story_clusters sc
            LEFT JOIN {S}.summaries sm ON sm.cluster_id = sc.id
            WHERE sc.blindspot_side IS NOT NULL
              AND sc.latest_published_at >= NOW() - INTERVAL '1 day' * :days
              AND EXISTS (
                  SELECT 1 FROM {S}.articles a
                  WHERE a.cluster_id = sc.id
                    AND (a.country_code = 'CA'
                         OR a.geo_scope IN ('national', 'provincial'))
              )
            ORDER BY sc.latest_published_at DESC
            LIMIT :n
        """), {"days": days, "n": limit}).mappings().all()


def _blindspot_reasons(side, province_code, beat, age_hours):
    """Why the missing side might be silent on a cluster — argued from the
    corpus, not asserted. Ported from the mockup's own reasons() function
    (design-handoff/wtf-blindspot.js): suppression is the last explanation to
    reach for, not the first.

    `side` is 'L' or 'R' — whichever side cluster_metrics._blindspot_side
    already called absent for this cluster.
    """
    S = _schema()
    lean_filter = ("obs.band IN ('left','center-left')" if side == "L"
                   else "obs.band IN ('center-right','right')")
    out = []
    with _db().begin() as c:
        # Does ANY outlet on this side have a bureau in this province at all
        # (anywhere in the corpus, not just this cluster)?
        prov_count = 0
        if province_code:
            prov_count = c.execute(text(f"""
                SELECT COUNT(DISTINCT a.source_id)
                FROM {S}.articles a
                JOIN {S}.outlet_bias_scores obs ON obs.source_id = a.source_id
                WHERE {lean_filter} AND a.province_code = :prov
            """), {"prov": province_code}).scalar() or 0
            if not prov_count:
                out.append((
                    f"No bureau on that side in {province_code}",
                    "No outlet on that side of the spectrum has filed from "
                    "this province in the corpus at all, on any story.",
                ))

        # How thin is that side's coverage of this beat, corpus-wide?
        beat_depth = 0
        if beat:
            beat_depth = c.execute(text(f"""
                SELECT COUNT(*)
                FROM {S}.articles a
                JOIN {S}.outlet_bias_scores obs ON obs.source_id = a.source_id
                WHERE {lean_filter} AND a.beat = :beat
            """), {"beat": beat}).scalar() or 0
            if beat_depth < 4:
                out.append((
                    f"{beat} is thinly staffed on that side",
                    f"Outlets on that side have filed {beat_depth} piece"
                    f"{'s' if beat_depth != 1 else ''} on {beat.lower()} "
                    "across the whole corpus.",
                ))

        if age_hours < 6:
            out.append((
                f"The story is {age_hours:.1f} hours old",
                "A gap this young is a news cycle, not an editorial "
                "position. It may close today.",
            ))

        if prov_count and beat_depth >= 4 and age_hours >= 6:
            out.append((
                "Staffed, and still absent",
                "Outlets on that side cover this beat and this province "
                "elsewhere, and did not carry this story.",
            ))
    return out


def _blindspot_age_hours(r):
    if not r["earliest_published_at"] or not r["latest_published_at"]:
        return 0.0
    return (r["latest_published_at"] - r["earliest_published_at"]).total_seconds() / 3600


@bp.get("/blindspot")
def blindspot_page():
    """Dedicated Blindspot Feed page — rendered SERVER-SIDE.

    Redesigned (task #6524) from an outlet-count silence signal to a
    political-LEAN coverage imbalance signal — see the section header above
    _blindspot_rows for the full rationale.

    The window buttons are plain links (?days=N), so filtering works
    without JavaScript.
    """
    from flask import request as _req
    try:
        days = int(_req.args.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in _BLINDSPOT_WINDOWS:
        days = 7
    rows = [dict(r) for r in _blindspot_rows(days=days)]
    for r in rows:
        age_hours = _blindspot_age_hours(r)
        r["age_hours"] = age_hours
        r["reasons"] = _blindspot_reasons(
            r["blindspot_side"], r.get("province_code"), r.get("beat"), age_hours)
    return render_template("blindspot.html",
                           blindspots=rows,
                           total_in_window=_blindspot_total(days=days),
                           days=days,
                           windows=_BLINDSPOT_WINDOWS,
                           is_subscriber=is_subscriber())


@bp.get("/api/v1/blindspot")
def api_v1_blindspot():
    """#3006, redesigned #6524 — political-lean coverage imbalance.

    A blindspot = a story covered almost entirely by outlets on one side of
    the political spectrum, per the same MIN_TOTAL/MIN_SIDES/MINOR_MAX/MIN_DIFF
    thresholds cluster_metrics._blindspot_side applies (see that function's
    docstring). NOT outlet-count silence — that's coverage_gap_score, still
    returned below as a distinct field.

    Query params:
      limit int  default 20  max 100
      days  int  default 7   look-back window
    """
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    from flask import request as _req
    limit = min(int(_req.args.get("limit", 20)), 100)
    days = min(int(_req.args.get("days", 7)), 90)
    # Same helper the PAGE renders from — the two cannot drift apart.
    rows = _blindspot_rows(days=days, limit=limit)
    return _api_cors_response({
        "ok": True,
        "days": days,
        "blindspots": [{
            "id": r["id"],
            "title": r["representative_title"],
            "article_count": r["article_count"],
            "source_count": r["source_count"],
            "blindspot_side": r["blindspot_side"],
            "lean_l_count": r["lean_l_count"],
            "lean_c_count": r["lean_c_count"],
            "lean_r_count": r["lean_r_count"],
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

_DIVERGENCE_WINDOWS = (7, 30, 60, 90)

# ── Disputed-point tracker (task #6524 primary framing) ───────────────────
# A SEPARATE window set from the FR/EN lens above: a dispute needs real
# spread to accumulate and a verdict takes time to resolve, so a shorter
# "last 7 days" window (meaningful for language-detection) would mostly
# show "not yet checked" here. Mirrors design-handoff/wtf-divergence.js's
# qualification rule (arts.length >= 6, spans both L and R lean, AND
# V.E.R.I.F.Y. found a checkable point) — see _dispute_rows' docstring.
_DIVERGENCE_VIEWS = ("disputes", "language")
_DISPUTE_WINDOWS = (30, 90, 180, 365)
_DISPUTE_MIN_ARTICLES = 6  # same floor as ingest/dispute_backlog_worker.py's _MIN_ARTICLES


def _divergence_rows(days=30, limit=20, min_div=0.1):
    """Rows behind BOTH /divergence and /api/v1/divergence.

    Extracted so the page and the API cannot drift, same reasoning as
    _blindspot_rows above. Three divergence types:
    - en_only: story exists in English press but not French
    - fr_only: story exists in French press but not English
    - bias_gap: both cover it, but avg bias scores differ significantly
    """
    S = _schema()
    with _db().begin() as c:
        return c.execute(text(f"""
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
                  AND a.suppressed_reason IS NULL
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


def _dispute_total(days=90, include_excluded=False):
    """How many clusters QUALIFY (or, with include_excluded, exist at all)
    in this window — not how many are shown. Same honesty pattern as
    _blindspot_total: the population can run far larger than the page size.
    """
    S = _schema()
    # Opinion clusters QUALIFY (they have a real disputed_point, just no
    # document can settle a forecast) — matches the mockup, where c1/c9 are
    # in BOTH POINT and OPINION. Only a NULL disputed_point excludes.
    where_qualify = "" if include_excluded else """
        AND sc.lean_l_count > 0 AND sc.lean_r_count > 0
        AND cd.disputed_point IS NOT NULL
    """
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT count(*) FROM {S}.story_clusters sc
            LEFT JOIN {S}.cluster_disputes cd ON cd.cluster_id = sc.id
            WHERE sc.article_count >= :min_articles
              AND sc.latest_published_at >= NOW() - INTERVAL '1 day' * :days
              {where_qualify}
        """), {"min_articles": _DISPUTE_MIN_ARTICLES, "days": days}).scalar() or 0


def _dispute_rows(days=90, limit=20, include_excluded=False):
    """Rows behind BOTH /divergence (disputes view) and /api/v1/disputes.

    Qualification mirrors design-handoff/wtf-divergence.js exactly:
    article_count >= 6, spans both L (band0+1) and R (band3+4) lean, AND
    V.E.R.I.F.Y. found a real checkable point (disputed_point IS NOT NULL,
    not an opinion/forecast dispute). Excluded rows carry WHY, distinguishing
    two states the mockup's toy dataset never had to: a cluster
    dispute_backlog_worker.py hasn't reached yet ("not yet checked") from one
    it reached and found nothing checkable in ("disagreement is on tone").
    """
    S = _schema()
    # Opinion clusters QUALIFY (real disputed_point, just no document can
    # settle a forecast) — matches the mockup, where c1/c9 are in BOTH POINT
    # and OPINION. Only a NULL disputed_point excludes.
    qualify_filter = "" if include_excluded else """
        AND sc.lean_l_count > 0 AND sc.lean_r_count > 0
        AND cd.disputed_point IS NOT NULL
    """
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT sc.id, sc.representative_title, sc.article_count,
                   sc.lean_l_count, sc.lean_c_count, sc.lean_r_count,
                   sc.divergence_score, sc.earliest_published_at, sc.latest_published_at,
                   cd.disputed_point, cd.verdict, cd.is_opinion,
                   (SELECT a2.beat FROM {S}.articles a2
                     WHERE a2.cluster_id = sc.id AND a2.beat IS NOT NULL
                     LIMIT 1)                                          AS beat
            FROM {S}.story_clusters sc
            LEFT JOIN {S}.cluster_disputes cd ON cd.cluster_id = sc.id
            WHERE sc.article_count >= :min_articles
              AND sc.latest_published_at >= NOW() - INTERVAL '1 day' * :days
              {qualify_filter}
            ORDER BY sc.divergence_score DESC NULLS LAST, sc.latest_published_at DESC
            LIMIT :n
        """), {"min_articles": _DISPUTE_MIN_ARTICLES, "days": days, "n": limit}).mappings().all()


def _dispute_why(row):
    """Exclusion reason for a non-qualifying row — None when it qualifies.
    Order matches the mockup's own precedence (size first, then spread,
    then whether a point was ever found).

    `is_opinion` distinguishes "no cluster_disputes row at all" (LEFT JOIN
    yields None/NULL — the backlog worker hasn't reached this cluster yet)
    from "a row exists" (is_opinion is always a real True/False there — the
    column is NOT NULL DEFAULT false on the table, so a LEFT JOIN can only
    ever produce Python None when there was no matching row to join)."""
    if row["article_count"] < _DISPUTE_MIN_ARTICLES:
        return "fewer than six outlets"
    if not (row["lean_l_count"] > 0 and row["lean_r_count"] > 0):
        return "spread does not cross the centre"
    if row["is_opinion"] is None:
        return "not yet checked for a disputed point"
    if row["is_opinion"]:
        return None  # qualifies, just scored differently (opinion, not verdict)
    if row["disputed_point"] is None:
        return "disagreement is on tone, not a checkable point"
    return None


def _dispute_side_articles(cluster_id: int, side: str, limit: int = 4):
    """Up to `limit` representative articles from one side of the spectrum,
    for the card's 'Reads it one way / the other' panels. side is 'L' or 'R'."""
    S = _schema()
    lean_filter = "bs.score < -0.15" if side == "L" else "bs.score >= 0.25"
    with _db().begin() as c:
        return c.execute(text(f"""
            SELECT a.id, a.title, s.name AS source_name, a.published_at, bs.score
            FROM {S}.articles a
            JOIN {S}.sources s ON s.id = a.source_id
            JOIN {S}.bias_scores bs ON bs.article_id = a.id
            WHERE a.cluster_id = :cid AND {lean_filter}
            ORDER BY a.published_at DESC
            LIMIT :n
        """), {"cid": cluster_id, "n": limit}).mappings().all()


@bp.get("/divergence")
def divergence_page():
    """Coverage divergence page — rendered SERVER-SIDE, two views.

    ⚠️ This page shipped with an empty <div id="div-list"> and 4 window
    filter buttons carrying data-days attributes but no click handler
    anywhere in static/js/ — /api/v1/divergence had real rows the whole
    time. Same defect shape as /blindspot before #5767.

    Redesigned (task #6524): the PRIMARY view (?view=disputes, default) is a
    "checkable fact in dispute" tracker (design-handoff/wtf-divergence.js).
    The ORIGINAL French-English coverage-language detection (_divergence_rows,
    real and DB-backed since #3003) is kept exactly as it was, demoted to a
    secondary lens (?view=language) per Kytran's explicit confirmation this
    session that it should not be retired.
    """
    from flask import request as _req
    view = _req.args.get("view", "disputes")
    if view not in _DIVERGENCE_VIEWS:
        view = "disputes"

    if view == "language":
        try:
            days = int(_req.args.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        if days not in _DIVERGENCE_WINDOWS:
            days = 30
        return render_template("divergence.html",
                               view=view,
                               divergences=_divergence_rows(days=days),
                               days=days,
                               windows=_DIVERGENCE_WINDOWS,
                               is_subscriber=is_subscriber())

    try:
        days = int(_req.args.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    if days not in _DISPUTE_WINDOWS:
        days = 90
    show_excluded = _req.args.get("excl") == "1"

    rows = [dict(r) for r in _dispute_rows(days=days, include_excluded=show_excluded)]
    for r in rows:
        r["why"] = None if not show_excluded else _dispute_why(r)
        if r["lean_l_count"] and r["lean_r_count"]:
            r["left_articles"] = _dispute_side_articles(r["id"], "L")
            r["right_articles"] = _dispute_side_articles(r["id"], "R")
        else:
            r["left_articles"] = []
            r["right_articles"] = []

    return render_template(
        "divergence.html",
        view=view,
        disputes=rows,
        total_in_window=_dispute_total(days=days, include_excluded=show_excluded),
        show_excluded=show_excluded,
        days=days,
        windows=_DISPUTE_WINDOWS,
        is_subscriber=is_subscriber(),
    )


@bp.get("/api/v1/divergence")
def api_v1_divergence():
    """#3003 — Clusters where French and English outlets tell a different story.

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
    # Same helper the PAGE renders from — the two cannot drift apart.
    rows = _divergence_rows(days=days, limit=limit, min_div=min_div)
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


@bp.get("/api/v1/disputes")
def api_v1_disputes():
    """#6524 — Clusters with a checkable fact in political dispute.

    Query params:
      limit  int  default 20   max 100
      days   int  default 90   look-back window (one of _DISPUTE_WINDOWS)

    Same helper the PAGE renders from (disputes view) — the two cannot drift.
    """
    _rl = _api_rate_check()
    if _rl is not None:
        return _rl
    from flask import request as _req
    limit = min(int(_req.args.get("limit", 20)), 100)
    days = min(int(_req.args.get("days", 90)), 365)
    rows = _dispute_rows(days=days, limit=limit)
    return _api_cors_response({
        "ok": True,
        "days": days,
        "disputes": [{
            "id": r["id"],
            "title": r["representative_title"],
            "article_count": r["article_count"],
            "beat": r["beat"],
            "divergence_score": r["divergence_score"],
            "left_count": r["lean_l_count"],
            "center_count": r["lean_c_count"],
            "right_count": r["lean_r_count"],
            "latest": r["latest_published_at"].isoformat() if r["latest_published_at"] else None,
            "disputed_point": r["disputed_point"],
            "verdict": r["verdict"],
            "is_opinion": bool(r["is_opinion"]),
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
    where = ["a.published_at > NOW() - :days * INTERVAL '1 day'", "a.suppressed_reason IS NULL"]
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
            LEFT JOIN {S}.articles a ON a.source_id = s.id AND a.suppressed_reason IS NULL
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
        total_sources = _active_source_count(c, S)

        total_articles = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.articles WHERE suppressed_reason IS NULL")
        ).scalar() or 0

        band_rows = c.execute(text(f"""
            SELECT b.band, COUNT(*) AS n
            FROM {S}.bias_scores b
            JOIN {S}.articles a ON a.id = b.article_id
            WHERE b.band IS NOT NULL AND a.suppressed_reason IS NULL
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


# ---------------------------------------------------------------------------
# Newsroom rebuild — Phase 1 placeholders
#
# The rebuilt nav (design-handoff/_nav.html) has seven groups; nine of their
# destinations have no route yet. A nav full of 404s is worse than the nav it
# replaces, so each gets a real page that says plainly it is not built.
#
# Copy is Design's own (title/h1/lede lifted from the matching wtf-*.html), so
# the placeholder and the finished page describe the same thing. `blocker`
# names what each is actually waiting on — verified against the live schema on
# 2026-09-02, not guessed:
#
#   parliament.* holds SITTING-MEMBER data (mps 343, senators 107,
#   mp_promises 5,561, votes, expenses, ec_contributions). There is no table
#   for elections, candidates, races, party records, platform documents,
#   fiscal aggregates or phrase counts. Five of these nine need an ingest that
#   does not exist; they are not "nearly done".
#
# Each becomes a real view in its phase; deleting an entry here is what
# "shipped" looks like.
# ---------------------------------------------------------------------------

_COMING_SOON = {
    # "parties" graduated to a real page — see parties() below. Its placeholder
    # is DELETED rather than disabled: a page that exists must not also be
    # advertised as unbuilt.
    #
    # ⚠️ The blocker it named was half right, and the surviving half shaped the
    # page. "No historical seat or vote series" is now answered — but only for
    # TWO elections, because CKAN publishes no more (GE38-41 absent, GE42 on a
    # disallowed host). "No party entity" was exactly right and remains the
    # hard part: shared/party_identity.py is the minimum honest substitute, and
    # "promises kept and broken" still has no data at all, so the page does not
    # claim it.
    "platforms": (
        "Platforms and promises — did they do what they said?",
        "Did they do what they said?",
        "Every commitment quoted from the platform that made it, with the "
        "document it came from and the evidence for where it now stands.",
        "Waiting on real promise extraction linked to platform documents. "
        "`parliament.mp_promises` holds 5,561 rows, but they are naive "
        "keyword-matched article snippets, not verified commitments — "
        "sampled rows include ad boilerplate and comment-widget footer "
        "text, not quotes from platform documents. Nothing here can "
        "honestly be shown as a tracked commitment yet.",
    ),
    "elections": (
        "Elections — federal, provincial and municipal",
        "Elections",
        "Every Canadian election on one calendar — federal, provincial and "
        "municipal, with how soon each legislature must go to the polls.",
        "Waiting on an election-calendar ingest. No table records election "
        "dates, fixed-date rules or writ periods today.",
    ),
    # "races" graduated to a real page — see races() below. Its placeholder is
    # deleted rather than disabled: a page that exists must not also be
    # advertised as unbuilt.
    "global": (
        "Global Affairs spending — what Canada sends abroad",
        "Global Affairs spending",
        "What Canada sends abroad from tax dollars — development assistance, "
        "humanitarian aid, multilateral contributions and Ukraine support — "
        "and who receives it.",
        "Waiting on a Global Affairs spending ingest. Not yet collected.",
    ),
    "debt": (
        "Debt tracker — taxes, spending and the federal debt",
        "Debt tracker",
        "Taxes in, spending out, and what the gap has added to the federal "
        "debt across ten fiscal years.",
        "Waiting on fiscal aggregates. Departmental contracts are ingested, "
        "but revenue, total programme spending and the debt series are not.",
    ),
    # "echo" graduated to a real page — see echo() below (#6272 follow-up).
    # "methodology" graduated to a real page — see methodology() below. Its
    # placeholder is DELETED rather than disabled: a page that exists must not
    # also be advertised as unbuilt. The content this stub promised ("brought
    # onto this site" from what-the-fact.tech/transparency) already existed,
    # fully written, in tech/templates/methodology.html — ported here rather
    # than rewritten, since it is real documentation (prompts, thresholds,
    # known limitations with live remediation-registry links), not a mockup.
    # "creed" graduated to a real page — see creed_page() below. Its
    # placeholder is DELETED rather than disabled, same rule as "methodology":
    # a page that exists must not also be advertised as unbuilt.
}


def _register_coming_soon(slug, title, h1, lede, blocker):
    """Register one placeholder. Closure per slug so each endpoint is distinct —
    a shared function object would collide on Flask's endpoint name."""

    def view():
        return render_template(
            "_coming_soon.html",
            page_title=f"{title} · What The Fact",
            page_h1=h1,
            page_lede=lede,
            page_blocker=blocker,
        )

    view.__name__ = f"coming_soon_{slug}"
    bp.get(f"/{slug}")(view)


for _slug, _copy in _COMING_SOON.items():
    _register_coming_soon(_slug, *_copy)


@bp.get("/echo")
def echo():
    """Echo — real slogan/phrase and word-frequency counts (#6272 follow-up).

    Graduated from `_COMING_SOON` in a REDUCED form vs. the design mockup
    (wtf-echo.html): a slogan table and a word-frequency panel, both backed
    by real counts from `wtf.articles`' full-text index. Dropped entirely:
    the "pickup" metric, the "who posts most" social-cadence panel, and the
    "fed by the Watch series" cross-link teaser — see echo_data.py's module
    docstring for why each was cut rather than shipped with invented values.
    """
    S = _schema()
    with _db().begin() as c:
        slogans = _echo_data.build_slogan_rows(c, S)
        words = _echo_data.build_word_rows(c, S)

    slogans_sorted_by_uses = sorted(slogans, key=lambda r: r["uses"], reverse=True)
    most_used = slogans_sorted_by_uses[0] if slogans_sorted_by_uses else None
    fading_candidates = [r for r in slogans if r["trend"] == "fading"]
    fading = min(fading_candidates, key=lambda r: r["trend_pct"]) if fading_candidates else None
    total_uses = sum(r["uses"] for r in slogans)

    return render_template(
        "echo.html",
        slogans=slogans,
        words=words,
        most_used=most_used,
        fading=fading,
        total_uses=total_uses,
        window_weeks=_echo_data.SLOGAN_WINDOW_WEEKS,
        word_window_days=_echo_data.WORD_WINDOW_DAYS,
        is_subscriber=is_subscriber(),
    )


@bp.get("/methodology")
def methodology():
    """Public methodology / radical transparency page.

    Ported from tech/routes.py's methodology() (served there at /transparency,
    matching what-the-fact.tech/transparency) — same stats query, same real
    content (prompts, thresholds, known limitations with live C.R.E.E.D.
    remediation-registry links). Not a rewrite: this documentation was already
    accurate and live, just on the other app in this monorepo.
    """
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
              AND suppressed_reason IS NULL
        """)).mappings().first()
    return render_template("methodology.html", stats=stats or {},
                           is_subscriber=is_subscriber())


# ---------------------------------------------------------------------------
# /races — federal general election results by riding
#
# Reads parliament.election_candidates (migration 074, ingested by
# ingest/elections/results.py from open.canada.ca CKAN).
#
# ⚠️ THESE ARE PAST RESULTS, NOT LIVE RACES. The design prototype is written for
# an election period — "who is running where". No dataset provides that outside
# a writ period, and CKAN carries completed elections only. The page says so in
# its own lede rather than letting a reader assume a contest is under way.
#
# ⚠️ `elected` COMES FROM THE DATA, never from the `**` marker in the source —
# that marks incumbency and would name the wrong MP in 53 of 338 ridings
# (KB #301957). Nothing here re-derives a winner.
# ---------------------------------------------------------------------------

_RACES_CACHE: dict = {}
_RACES_CACHE_TTL = int(os.environ.get("WTF_RACES_CACHE_TTL", "900"))


def _races_bundle(ge_number: int) -> dict:
    key = ("races", ge_number)
    hit = _RACES_CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    with _db().begin() as c:
        elections = [
            dict(r) for r in c.execute(text(
                "SELECT ge_number, election_date FROM parliament.elections "
                "ORDER BY ge_number DESC")).mappings()
        ]
        if not elections:
            return {"elections": [], "ge": None, "races": [], "tiles": [], "parties": []}

        rows = [dict(r) for r in c.execute(text("""
            WITH ranked AS (
              SELECT ec.*,
                     row_number() OVER (PARTITION BY ec.district_number
                                        ORDER BY ec.votes DESC) AS rk,
                     sum(ec.votes)  OVER (PARTITION BY ec.district_number) AS cast_votes,
                     count(*)       OVER (PARTITION BY ec.district_number) AS runners
                FROM parliament.election_candidates ec
                JOIN parliament.elections e ON e.id = ec.election_id
               WHERE e.ge_number = :ge
            )
            SELECT w.district_number, w.district_name, w.province,
                   w.candidate_name, w.party, w.incumbent,
                   w.votes, w.vote_share, w.majority, w.runners, w.cast_votes,
                   r.candidate_name AS runner_up, r.party AS runner_up_party,
                   CASE WHEN w.cast_votes > 0
                        -- 2dp, NOT 1. A 12-vote win in 57,349 is 0.02%, which
                        -- rounds to exactly 0.0 at 1dp — and the template's
                        -- "show <0.1% instead of 0.0%" guard is `> 0`, so a value
                        -- already flattened to 0.0 slips straight past it and the
                        -- closest race in the country renders as a ZERO margin.
                        -- The display rounding belongs in the template; the query
                        -- must not destroy the distinction before it gets there.
                        THEN round(100.0 * w.majority / w.cast_votes, 2) END AS margin_pct
              FROM ranked w
              LEFT JOIN ranked r ON r.district_number = w.district_number AND r.rk = 2
             WHERE w.elected
             ORDER BY margin_pct NULLS LAST, w.district_name
        """), {"ge": ge_number}).mappings()]

        seats = [dict(r) for r in c.execute(text("""
            SELECT ec.party, count(*) AS seats,
                   sum(ec.votes) AS votes
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge AND ec.elected AND ec.party <> ''
             GROUP BY 1 ORDER BY 2 DESC
        """), {"ge": ge_number}).mappings()]

        totals = dict(c.execute(text("""
            SELECT count(*) AS candidates,
                   count(DISTINCT ec.district_number) AS districts,
                   count(DISTINCT NULLIF(ec.party, '')) AS parties
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge
        """), {"ge": ge_number}).mappings().first() or {})

    closest = rows[0] if rows else None
    tiles = [
        {"label": "Ridings", "value": f"{totals.get('districts', 0):,}"},
        {"label": "Candidates", "value": f"{totals.get('candidates', 0):,}"},
        {"label": "Parties", "value": f"{totals.get('parties', 0):,}"},
        {"label": "Closest margin",
         "value": (f"{closest['majority']:,} votes" if closest and closest.get("majority")
                   else "—")},
    ]
    # ranked_bars() reads .label/.value, and Jinja has NO list comprehension —
    # so the bar rows are shaped here rather than contorted in the template.
    # `display` carries the seat count with its unit; `value` stays numeric
    # because the macro divides by max(value) to size the bar.
    party_bars = [{"label": s["party"], "value": s["seats"],
                   "display": f"{s['seats']} seat" + ("" if s["seats"] == 1 else "s")}
                  for s in seats]

    out = {"elections": elections, "ge": ge_number, "races": rows,
           "tiles": tiles, "parties": seats, "party_bars": party_bars,
           "election_date": next((e["election_date"] for e in elections
                                  if e["ge_number"] == ge_number), None)}
    _RACES_CACHE[key] = (time.time() + _RACES_CACHE_TTL, out)
    return out


@bp.get("/races")
def races():
    from flask import request as _req
    try:
        ge = int(_req.args.get("ge", 0))
    except (TypeError, ValueError):
        ge = 0
    B = _races_bundle(ge) if ge else None
    if not B or not B.get("races"):
        # Default to the most recent election we actually hold.
        with _db().begin() as c:
            latest = c.execute(text(
                "SELECT max(ge_number) FROM parliament.elections")).scalar()
        B = _races_bundle(int(latest)) if latest else {
            "elections": [], "ge": None, "races": [], "tiles": [], "parties": [],
            "party_bars": [], "election_date": None}

    province = (_req.args.get("province") or "").strip()
    races_rows = B["races"]
    if province:
        races_rows = [r for r in races_rows if r["province"] == province]

    return render_template(
        "races.html",
        elections=B["elections"], ge=B["ge"], election_date=B["election_date"],
        tiles=B["tiles"], parties=B["parties"], party_bars=B["party_bars"],
        races=races_rows, total_races=len(B["races"]),
        provinces=sorted({r["province"] for r in B["races"] if r["province"]}),
        province=province,
    )


@bp.get("/races/<district_number>")
def race_detail(district_number):
    from flask import request as _req
    try:
        ge = int(_req.args.get("ge", 0))
    except (TypeError, ValueError):
        ge = 0
    with _db().begin() as c:
        if not ge:
            ge = c.execute(text("SELECT max(ge_number) FROM parliament.elections")).scalar()
        rows = [dict(r) for r in c.execute(text("""
            SELECT ec.candidate_name, ec.party, ec.incumbent, ec.votes,
                   ec.vote_share, ec.majority, ec.elected,
                   ec.district_name, ec.province
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge AND ec.district_number = :d
             ORDER BY ec.votes DESC
        """), {"ge": ge, "d": district_number}).mappings()]
        edate = c.execute(text(
            "SELECT election_date FROM parliament.elections WHERE ge_number = :ge"),
            {"ge": ge}).scalar()
    if not rows:
        abort(404)
    return render_template("race_detail.html", rows=rows, ge=ge,
                           election_date=edate,
                           district_number=district_number,
                           district_name=rows[0]["district_name"],
                           province=rows[0]["province"],
                           cast_votes=sum(r["votes"] for r in rows))


# ---------------------------------------------------------------------------
# /parties — party performance across the elections we actually hold.
#
# ⚠️ TWO ELECTIONS, NOT A TREND, AND NOT THE "25 YEARS" THE PLACEHOLDER PROMISED.
# CKAN's `elections` organisation publishes exactly THREE official voting-results
# datasets — GE42, GE43, GE44 — and GE42's resources are hosted on
# www.elections.ca, whose robots.txt 500s (RFC 9309: assume complete disallow).
# So the ceiling is GE43 + GE44, and that is a property of the SOURCE, not of
# the discovery query. Measured 2026-09-02. The page says so on its face rather
# than presenting two points as a series.
#
# ⚠️ PARTY NAMES ARE CANONICALISED IN SQL, BEFORE AGGREGATION, via
# shared.party_identity. Grouping on the raw ballot label splits a continuing
# party in two: the PPC is "People's Party" in GE43 and "People's Party - PPC"
# in GE44, so the raw grouping reports they did not exist in 2019 — destroying
# the real finding, that their vote nearly tripled. Canonicalising AFTER a
# GROUP BY would be just as wrong: it would produce two rows to add together in
# Python, which is where the sums quietly stop matching the source totals.
# ---------------------------------------------------------------------------

_PARTIES_CACHE: dict = {}
_PARTIES_CACHE_TTL = int(os.environ.get("WTF_PARTIES_CACHE_TTL", "900"))


def _party_case_sql() -> str:
    """A SQL CASE that applies shared.party_identity to ec.party.

    Built FROM the Python mapping so the two can never drift — a second copy of
    the alias table pasted into SQL is exactly how a canonicalisation boundary
    stops being one. Values are single-quote-escaped and the table is a
    module-level literal (no user input reaches it).
    """
    from shared.party_identity import _ALIASES

    whens = " ".join(
        "WHEN %s THEN %s" % (_sql_str(raw), _sql_str(canon))
        for raw, canon in sorted(_ALIASES.items())
    )
    return f"CASE btrim(ec.party) {whens} ELSE btrim(ec.party) END"


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _parties_bundle(ge_number: int) -> dict:
    key = ("parties", ge_number)
    hit = _PARTIES_CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    canon = _party_case_sql()
    with _db().begin() as c:
        elections = [dict(r) for r in c.execute(text(
            "SELECT ge_number, election_date FROM parliament.elections "
            "ORDER BY ge_number DESC")).mappings()]

        # One row per canonical party for the selected election. Seat share is
        # computed against the SEATS ACTUALLY CONTESTED in that election, not a
        # hardcoded 338 — the House changed size between elections and will
        # again (343 after the 2023 redistribution).
        rows = [dict(r) for r in c.execute(text(f"""
            WITH tot AS (
                SELECT sum(ec.votes)::numeric AS all_votes,
                       count(DISTINCT ec.district_number)::numeric AS all_seats
                  FROM parliament.election_candidates ec
                  JOIN parliament.elections e ON e.id = ec.election_id
                 WHERE e.ge_number = :ge
            )
            SELECT {canon} AS party,
                   count(*)                          AS candidates,
                   sum(ec.votes)                     AS votes,
                   count(*) FILTER (WHERE ec.elected) AS seats,
                   round(100.0 * sum(ec.votes) / NULLIF((SELECT all_votes FROM tot), 0), 2)
                       AS vote_pct,
                   round(100.0 * count(*) FILTER (WHERE ec.elected)
                         / NULLIF((SELECT all_seats FROM tot), 0), 2) AS seat_pct
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge AND btrim(ec.party) <> ''
             GROUP BY 1
             ORDER BY sum(ec.votes) DESC
        """), {"ge": ge_number}).mappings()]

        # The SAME canonicalisation for the comparison election, so a party is
        # matched across elections by canonical name and never by raw label.
        prev = c.execute(text(
            "SELECT max(ge_number) FROM parliament.elections WHERE ge_number < :ge"),
            {"ge": ge_number}).scalar()
        before = {}
        if prev:
            before = {r["party"]: dict(r) for r in c.execute(text(f"""
                SELECT {canon} AS party, sum(ec.votes) AS votes,
                       count(*) FILTER (WHERE ec.elected) AS seats
                  FROM parliament.election_candidates ec
                  JOIN parliament.elections e ON e.id = ec.election_id
                 WHERE e.ge_number = :ge AND btrim(ec.party) <> ''
                 GROUP BY 1
            """), {"ge": prev}).mappings()}

        totals = dict(c.execute(text("""
            SELECT sum(ec.votes) AS votes,
                   count(DISTINCT ec.district_number) AS seats,
                   count(*) AS candidates
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge
        """), {"ge": ge_number}).mappings().first() or {})

        # Candidates whose party could not be derived, counted SEPARATELY and
        # reported on the page.
        #
        # ⚠️ WITHOUT THIS THE ARITHMETIC DOES NOT CLOSE AND NOTHING SAYS SO.
        # The party table excludes blank-party rows while the "Votes counted"
        # tile totals every row, so GE44 rendered 2,009 candidates against
        # 2,010 in the source — a silent one-row gap. The row is real: the
        # Nationalist party fielded a SINGLE candidate, and the parser derives
        # a party name from the longest common suffix of at least two
        # candidates, so a one-candidate party has no derivable boundary and
        # keeps the whole cell as the name (see results_parse.derive_parties).
        # Same discipline as the weather map greying an uncovered province
        # explicitly instead of drawing it as zero.
        unresolved = dict(c.execute(text("""
            SELECT count(*) AS candidates, COALESCE(sum(ec.votes), 0) AS votes
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge AND COALESCE(btrim(ec.party), '') = ''
        """), {"ge": ge_number}).mappings().first() or {})

        # The SITTING House — a DIFFERENT event, a different source and a
        # different label vocabulary. Never joined to the election rows; see
        # rule 3 in shared/party_identity.py.
        house = [dict(r) for r in c.execute(text(
            "SELECT party, count(*) AS seats FROM parliament.mps "
            "WHERE COALESCE(btrim(party),'') <> '' GROUP BY 1 ORDER BY 2 DESC")).mappings()]

    for r in rows:
        b = before.get(r["party"])
        r["prev_votes"] = b["votes"] if b else None
        r["prev_seats"] = b["seats"] if b else None
        # A party absent from the earlier election has NO change — not a change
        # of zero, and not a change from zero. Left None and rendered as "new".
        r["votes_delta"] = (r["votes"] - b["votes"]) if b else None
        r["seats_delta"] = (r["seats"] - b["seats"]) if b else None
        # Disproportionality: seat share minus vote share, in points.
        r["gap"] = (float(r["seat_pct"] or 0) - float(r["vote_pct"] or 0))

    out = {
        "elections": elections, "ge": ge_number, "prev_ge": prev,
        "rows": rows, "house": house, "unresolved": unresolved,
        "election_date": next((e["election_date"] for e in elections
                               if e["ge_number"] == ge_number), None),
        "tiles": [
            {"label": "Elections on record", "value": str(len(elections))},
            {"label": "Parties fielding candidates", "value": f"{len(rows):,}"},
            {"label": "Votes counted", "value": f"{int(totals.get('votes') or 0):,}"},
            {"label": "Seats contested", "value": f"{int(totals.get('seats') or 0):,}"},
        ],
    }
    _PARTIES_CACHE[key] = (time.time() + _PARTIES_CACHE_TTL, out)
    return out


@bp.get("/parties")
def parties():
    from flask import request as _req
    try:
        ge = int(_req.args.get("ge", 0))
    except (TypeError, ValueError):
        ge = 0
    with _db().begin() as c:
        available = [r[0] for r in c.execute(text(
            "SELECT ge_number FROM parliament.elections ORDER BY ge_number DESC"))]
    if not available:
        return render_template("parties.html", elections=[], ge=None, rows=[],
                               house=[], tiles=[], election_date=None,
                               prev_ge=None, merged={}, bars=[],
                               unresolved={"candidates": 0, "votes": 0})
    if ge not in available:
        ge = available[0]

    B = _parties_bundle(ge)
    from shared.party_identity import merged_labels

    # ranked_bars rows are shaped here — Jinja has no list comprehension, and
    # the bars show VOTE SHARE, the quantity the seat gap is measured against.
    bars = [{"label": r["party"], "value": float(r["vote_pct"] or 0),
             "display": f"{float(r['vote_pct'] or 0):.1f}% of votes · "
                        f"{r['seats']} seat" + ("" if r["seats"] == 1 else "s")}
            for r in B["rows"][:8]]

    return render_template("parties.html", elections=B["elections"], ge=B["ge"],
                           prev_ge=B["prev_ge"], rows=B["rows"], house=B["house"],
                           tiles=B["tiles"], election_date=B["election_date"],
                           merged=merged_labels(), bars=bars,
                           unresolved=B["unresolved"])


# ---------------------------------------------------------------------------
# /ridings — historical riding-results DIRECTORY (a lookup, not a ranking).
#
# ⚠️ NOT THE PROTOTYPE'S LIVE TRACKER. design-handoff/wtf-ridings.html fetches
# live riding-boundary polygons from a third-party API and says itself it
# carries no MP-to-riding mapping — a different feature than this data
# supports. This page has no map, no boundary geometry, and makes no
# "current MP" claim: it reads the SAME completed-election rows /races reads
# (GE43+GE44 only — the same CKAN ceiling documented above /parties), sorted
# ALPHABETICALLY by riding name rather than by margin, because a directory is
# for looking a riding up, not for ranking how close it was (that is /races'
# job — every row here links straight to its /races/<district> detail page
# rather than duplicating it).
# ---------------------------------------------------------------------------

_RIDINGS_CACHE: dict = {}
_RIDINGS_CACHE_TTL = int(os.environ.get("WTF_RIDINGS_CACHE_TTL", "900"))


def _ridings_bundle(ge_number: int) -> dict:
    key = ("ridings", ge_number)
    hit = _RIDINGS_CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    canon = _party_case_sql()
    with _db().begin() as c:
        elections = [dict(r) for r in c.execute(text(
            "SELECT ge_number, election_date FROM parliament.elections "
            "ORDER BY ge_number DESC")).mappings()]
        if not elections:
            return {"elections": [], "ge": None, "ridings": [], "tiles": [],
                    "election_date": None}

        # One row per district — the candidate the official results record as
        # elected. Sorted by NAME, never by margin: that ranking belongs to
        # /races, not to a directory meant for looking a riding up.
        rows = [dict(r) for r in c.execute(text(f"""
            SELECT ec.district_number, ec.district_name, ec.province,
                   ec.candidate_name, {canon} AS party, ec.vote_share
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge AND ec.elected
             ORDER BY ec.district_name
        """), {"ge": ge_number}).mappings()]

        totals = dict(c.execute(text("""
            SELECT count(DISTINCT ec.district_number) AS districts,
                   count(*) AS candidates
              FROM parliament.election_candidates ec
              JOIN parliament.elections e ON e.id = ec.election_id
             WHERE e.ge_number = :ge
        """), {"ge": ge_number}).mappings().first() or {})

    # Real counts from the query — never hardcoded, so a redistribution (338
    # -> 343 seats between GE44 and the next election) needs no code change.
    tiles = [
        {"label": "Ridings", "value": f"{totals.get('districts', 0):,}"},
        {"label": "Provinces",
         "value": f"{len({r['province'] for r in rows if r['province']}):,}"},
        {"label": "Candidates", "value": f"{totals.get('candidates', 0):,}"},
    ]

    out = {"elections": elections, "ge": ge_number, "ridings": rows, "tiles": tiles,
           "election_date": next((e["election_date"] for e in elections
                                  if e["ge_number"] == ge_number), None)}
    _RIDINGS_CACHE[key] = (time.time() + _RIDINGS_CACHE_TTL, out)
    return out


@bp.get("/ridings")
def ridings():
    from flask import request as _req
    try:
        ge = int(_req.args.get("ge", 0))
    except (TypeError, ValueError):
        ge = 0
    B = _ridings_bundle(ge) if ge else None
    if not B or not B.get("ridings"):
        with _db().begin() as c:
            latest = c.execute(text(
                "SELECT max(ge_number) FROM parliament.elections")).scalar()
        B = _ridings_bundle(int(latest)) if latest else {
            "elections": [], "ge": None, "ridings": [], "tiles": [],
            "election_date": None}

    province = (_req.args.get("province") or "").strip()
    q = (_req.args.get("q") or "").strip()
    rows = B["ridings"]
    if province:
        rows = [r for r in rows if r["province"] == province]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in (r["district_name"] or "").lower()]

    # An empty search result says so by name — it must never look like the
    # same bare "no filter matched" state a province-only filter would show.
    empty_msg = (f"No ridings match “{q}”." if q
                 else "No ridings match this filter.")

    return render_template(
        "ridings.html",
        elections=B["elections"], ge=B["ge"], election_date=B["election_date"],
        tiles=B["tiles"], ridings=rows, total_ridings=len(B["ridings"]),
        provinces=sorted({r["province"] for r in B["ridings"] if r["province"]}),
        province=province, q=q, empty_msg=empty_msg,
    )


# ---------------------------------------------------------------------------
# /candidates — candidate search across the elections we hold (GE43+GE44).
#
# ⚠️ NOT THE PROTOTYPE'S NOMINATION TRACKER. design-handoff/wtf-candidates.js
# tracks UPCOMING, unconfirmed candidacies for a future writ period —
# hardcoded 2026 dates, "declared" vs "confirmed" candidacy status. CKAN
# carries completed elections only, so no such dataset exists here: this is a
# search over COMPLETED candidacies, GE43 and GE44, nothing live and nothing
# unconfirmed.
#
# ⚠️ ONE ROW PER CANDIDACY, never per person. A candidate who ran in both
# elections, or in two different ridings, produces two rows on purpose — the
# source data carries no "candidate profile" to collapse them into, and
# merging rows across elections/ridings would fabricate a continuity nobody
# can verify (same discipline as shared/party_identity.py's NOT_MERGED table:
# an unproven merge is worse than two rows a reader can compare themselves).
# ---------------------------------------------------------------------------

_CANDIDATE_RESULT_CAP = 200
_CANDIDATE_MIN_QUERY_LEN = 2


@bp.get("/candidates")
def candidates():
    from flask import request as _req

    q = (_req.args.get("q") or "").strip()
    party = (_req.args.get("party") or "").strip()
    # Shorter than the minimum is IGNORED, not silently matched against
    # everything — a single letter would otherwise return most of the table.
    q_active = len(q) >= _CANDIDATE_MIN_QUERY_LEN
    has_query = q_active or bool(party)

    canon = _party_case_sql()
    with _db().begin() as c:
        total_candidates = c.execute(text(
            "SELECT count(*) FROM parliament.election_candidates")).scalar() or 0

        # Built from the data, with the SAME canonicalisation /parties uses —
        # never a second, hand-typed party list that can drift from it.
        parties = [r[0] for r in c.execute(text(
            f"SELECT DISTINCT {canon} AS party FROM parliament.election_candidates ec "
            "WHERE btrim(ec.party) <> '' ORDER BY 1"))]

        rows = []
        matched_total = 0
        if has_query:
            clauses = ["1 = 1"]
            params: dict = {}
            if q_active:
                clauses.append("ec.candidate_name ILIKE :q")
                params["q"] = f"%{q}%"
            if party:
                clauses.append(f"{canon} = :party")
                params["party"] = party
            where_sql = " AND ".join(clauses)

            matched_total = c.execute(text(
                f"SELECT count(*) FROM parliament.election_candidates ec "
                f"JOIN parliament.elections e ON e.id = ec.election_id "
                f"WHERE {where_sql}"), params).scalar() or 0

            params["cap"] = _CANDIDATE_RESULT_CAP
            rows = [dict(r) for r in c.execute(text(f"""
                SELECT ec.candidate_name, {canon} AS party, ec.district_number,
                       ec.district_name, ec.province, ec.votes, ec.vote_share,
                       ec.elected, e.ge_number, e.election_date
                  FROM parliament.election_candidates ec
                  JOIN parliament.elections e ON e.id = ec.election_id
                 WHERE {where_sql}
                 ORDER BY e.ge_number DESC, ec.candidate_name
                 LIMIT :cap
            """), params).mappings()]

    # The LIMIT already bounds `rows`; a real overflow is proven by comparing
    # the bounded set against the unbounded count, never by len(rows)==cap
    # alone (a search that matches exactly the cap is not a truncation).
    capped = matched_total > len(rows)

    return render_template(
        "candidates.html",
        q=q, party=party, parties=parties, candidate_rows=rows, has_query=has_query,
        matched_total=matched_total, capped=capped, cap=_CANDIDATE_RESULT_CAP,
        min_query_len=_CANDIDATE_MIN_QUERY_LEN, total_candidates=total_candidates,
    )
