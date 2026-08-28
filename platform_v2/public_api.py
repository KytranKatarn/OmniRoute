"""
Public API — Unauthenticated, read-only endpoints for the public website.

Provides platform feature data so kytranempowerment.com can auto-update
whenever modules, agents, or stats change in A.R.C.H.I.E.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-19
"""

import logging
import os
import time
from flask import Blueprint, jsonify, request, make_response
from database import get_db_cursor
from services.public_roster_service import (
    get_public_roster,
    get_public_roster_live,
)

logger = logging.getLogger(__name__)

public_api_bp = Blueprint("public_api", __name__, url_prefix="/api/public")

# Simple in-memory cache: {key: (timestamp, data)}
_cache = {}
CACHE_TTL = 300  # 5 minutes


def _get_cached(key, fetch_fn):
    """Return cached data if fresh, otherwise call fetch_fn and cache result."""
    now = time.time()
    if key in _cache and (now - _cache[key][0]) < CACHE_TTL:
        return _cache[key][1]
    data = fetch_fn()
    _cache[key] = (now, data)
    return data


def _fetch_platform_features():
    """Build the platform features payload from module_registry + DB."""
    # --- Module list from registry (always available, no DB needed) ---
    try:
        from module_registry import get_enabled_modules, ModuleCategory
    except ImportError:
        logger.error("Could not import module_registry")
        return {"error": "module_registry unavailable"}, 500

    modules = []
    category_labels = {
        "admin_operations": "Admin Operations",
        "ai_command": "AI Command",
        "saas_services": "SaaS Services",
        "project_knowledge": "Project & Knowledge",
        "applications_concepts": "Applications & Concepts",
        "crypto": "Crypto",
        "media_outreach": "Media Outreach",
        "creative_studios": "Creative Studios",
        "placeholders_future": "Coming Soon",
    }

    for m in get_enabled_modules():
        # Strip HTML from description for clean API output
        desc = m.description
        if "<br>" in desc:
            desc = desc.split("<br>")[0].strip()

        modules.append(
            {
                "id": m.id,
                "name": m.name,
                "description": desc,
                "icon": m.icon,
                "category": category_labels.get(m.category.value, m.category.value),
                "beta": m.beta,
                "coming_soon": m.coming_soon,
                "version": m.version,
            }
        )

    # --- Live stats from DB ---
    stats = {
        "total_modules": len(modules),
        "total_agents": 0,
        "active_agents": 0,
        "total_stations": 10,
        "autonomous_jobs": 39,  # APScheduler in-memory jobs, not in DB
        "languages": 8,
        "version": os.getenv("ARCHIE_VERSION", "5.32.0"),
    }

    try:
        with get_db_cursor() as (conn, cur):
            # Agent counts
            cur.execute(
                "SELECT COUNT(*) AS total, " "COUNT(*) FILTER (WHERE shift_state = 'active') AS active " "FROM agents"
            )
            row = cur.fetchone()
            if row:
                stats["total_agents"] = row["total"]
                stats["active_agents"] = row["active"]

    except Exception as e:
        logger.warning("public_api: DB stats query failed: %s", e)
        # Non-fatal — return what we have from the registry

    # --- Feature highlights (curated, not auto-generated) ---
    highlights = [
        {
            "title": "Mission Profiles",
            "summary": "6 reconfigurable operation modes that reshape the entire platform's behavior, priorities, and agent assignments on demand.",
            "icon": "target",
        },
        {
            "title": "Agent Welfare (C.R.E.E.D.)",
            "summary": "Stress levels, mood intensity, rest cycles, and emotional state tracked for every agent. Ethical AI governance built in.",
            "icon": "heart",
        },
        {
            "title": "Durable Execution",
            "summary": "Checkpoint and resume for failed jobs. Long-running tasks survive crashes and pick up exactly where they left off.",
            "icon": "refresh-cw",
        },
        {
            "title": "Smart Router",
            "summary": "11-tier GPU/VRAM-aware escalation chain. Automatically routes to the right model based on task complexity and available resources.",
            "icon": "zap",
        },
        {
            "title": "Physical Security",
            "summary": "Camera surveillance, DNS filtering, SSH monitoring, and intrusion detection. Real-time Telegram alerts for every threat.",
            "icon": "shield",
        },
        {
            "title": "Live AI Translation",
            "summary": "8 languages translated in real-time across the entire platform. RTL support for Arabic and Hebrew included.",
            "icon": "globe",
        },
        {
            "title": "Device Registry",
            "summary": "Auto-discover and protect every device on your network. Continuous monitoring with anomaly detection.",
            "icon": "smartphone",
        },
        {
            "title": "Self-Improvement",
            "summary": "Scan, Propose, Sandbox, Deploy. The platform identifies its own issues and fixes them autonomously.",
            "icon": "microscope",
        },
    ]

    return {
        "modules": modules,
        "stats": stats,
        "highlights": highlights,
    }


@public_api_bp.route("/platform-features")
def platform_features():
    """Public, read-only endpoint returning current platform modules and stats.

    Used by kytranempowerment.com to auto-update its platform page.
    Cached for 5 minutes to avoid unnecessary DB hits.
    """
    data = _get_cached("platform_features", _fetch_platform_features)
    if isinstance(data, tuple):
        # Error tuple (dict, status_code)
        return jsonify(data[0]), data[1]

    response = jsonify(data)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


def _fetch_competitors():
    """Build the competitor comparison payload from the competitors page data."""
    competitors = ["A.R.C.H.I.E.", "CrewAI", "LangGraph", "Devin", "Claude Code", "Goose", "Dify", "OpenAI Agents"]

    def _row(feature, *vals):
        """Helper: map bool values to competitor dict."""
        return {
            "feature": feature,
            "support": {c: v for c, v in zip(competitors, vals)},
        }

    # --- Feature Matrix ---
    feature_matrix = {
        "archie_unique": [
            _row("Station-based dispatch", True, False, False, False, False, False, False, False),
            _row("GPU/VRAM-aware routing", True, False, False, False, False, False, False, False),
            _row("Agent welfare (C.R.E.E.D. ethics)", True, False, False, False, False, False, False, False),
            _row("Self-auditing codebase", True, False, False, False, False, False, False, False),
            _row("Code health metrics dashboard", True, False, False, False, False, False, False, False),
            _row("Warm-boot model lifecycle", True, False, False, False, False, False, False, False),
            _row("5-step escalation chain", True, False, False, False, False, False, False, False),
            _row("Mission profiles", True, False, False, False, False, False, False, False),
            _row("Physical security (cameras, DNS, SSH)", True, False, False, False, False, False, False, False),
            _row("Self-improvement pipeline", True, False, False, False, False, False, False, False),
            _row("39 autonomous background jobs", True, False, False, False, False, False, False, False),
            _row("Telegram human-in-the-loop", True, False, False, False, False, False, False, False),
            _row("Live AI translation (8 languages)", True, False, False, False, False, False, False, False),
        ],
        "shared_capabilities": [
            _row("Multi-agent orchestration", True, True, True, True, True, True, True, True),
            _row("MCP protocol support", True, False, False, False, True, True, False, False),
            _row("Fully self-hosted", True, True, True, False, True, True, True, False),
            _row("Structured agent schemas", True, True, True, False, True, False, True, True),
            _row("Agents-as-tools delegation", True, True, False, True, True, False, False, True),
            _row("Human approval system", True, False, False, True, True, False, False, False),
            _row("Event-driven flow router", True, False, True, False, False, False, True, False),
        ],
        "competitor_strengths": [
            _row("Durable execution (checkpoints)", False, False, True, False, False, False, False, False),
            _row("A2A protocol (agent-to-agent)", False, False, True, False, False, False, False, False),
            _row("Visual drag-and-drop workflow builder", False, False, False, False, False, False, True, False),
            _row("IDE integration (VS Code / editor)", False, False, False, True, True, True, False, False),
            _row("Parallel agent execution", False, True, True, True, True, False, True, True),
            _row("Cloud auto-scaling", False, False, False, True, False, False, True, True),
        ],
    }

    # --- Category Comparison ---
    categories = [
        {
            "id": "orchestration",
            "title": "Orchestration Frameworks",
            "competitors": [
                "CrewAI",
                "AG2 (AutoGen fork)",
                "LangGraph",
                "MetaGPT",
                "OpenAI Agents SDK",
                "Microsoft Agent Framework",
            ],
            "description": "Libraries for building multi-agent systems. You write code, define roles, and wire agents together. Multi-agent is now table stakes.",
            "archie_edge": "These are libraries you build with. A.R.C.H.I.E. is a running system — GPU-aware routing, warm-boot lifecycle, physical security, and 39 autonomous background jobs out of the box.",
            "their_edge": "LangGraph offers durable execution with checkpoints. Google's A2A protocol enables cross-platform agent communication.",
        },
        {
            "id": "workflow_builders",
            "title": "Workflow Builders",
            "competitors": ["Langflow", "n8n", "Dify", "Flowise (acquired by Workday)"],
            "description": "Visual drag-and-drop platforms for connecting LLMs to tools and data sources. Strong for no-code teams.",
            "archie_edge": "Workflow builders connect things. A.R.C.H.I.E. orchestrates a fleet of 23 autonomous agents with station-based dispatch, VRAM-aware model management, and self-improvement.",
            "their_edge": "Dify and n8n offer visual drag-and-drop workflow builders that non-developers can use.",
        },
        {
            "id": "coding_agents",
            "title": "Autonomous Coding Agents",
            "competitors": ["Devin", "Cursor", "Windsurf", "Claude Code", "Codex CLI", "Cline", "Aider"],
            "description": "AI-powered coding tools that write, edit, and debug code. Claude Code now has Agent Teams (Opus 4.6). Devin dropped to $20/mo.",
            "archie_edge": "Coding agents write code. A.R.C.H.I.E. is a multi-domain operations platform — it manages physical security, monitors network devices, runs background intelligence, and self-audits its own codebase.",
            "their_edge": "IDE integration (VS Code, terminal), parallel agent execution, and git-native workflows.",
        },
        {
            "id": "enterprise",
            "title": "Enterprise Platforms",
            "competitors": ["Microsoft Agent Framework", "Haystack", "Relevance AI", "Dust.tt", "OpenAI Assistants"],
            "description": "Production-grade platforms backed by major vendors. Cloud-first, enterprise-scale.",
            "archie_edge": "Enterprise platforms are cloud-dependent. A.R.C.H.I.E. runs entirely on local hardware (128GB RAM, Quadro M4000), with agent welfare governance and zero cloud lock-in.",
            "their_edge": "Cloud auto-scaling, managed infrastructure, and enterprise SSO/compliance.",
        },
        {
            "id": "self_hosted",
            "title": "Self-Hosted & Open Source",
            "competitors": ["Goose (Block/AAIF)", "LocalAGI", "Aider", "Ollama", "Open WebUI"],
            "description": "Privacy-first, local-hardware AI tools. Goose (30K+ GitHub stars) is MCP-native. All run on consumer hardware.",
            "archie_edge": "These tools do one thing well. A.R.C.H.I.E. is a complete operations platform — 23 agents, 10 stations, 39 background jobs, physical security, knowledge base, and self-auditing codebase.",
            "their_edge": "Open-source community contributions, lower setup barrier, and plug-and-play simplicity.",
        },
        {
            "id": "self_improving",
            "title": "Self-Improving & Accountable",
            "competitors": [],
            "description": "A.R.C.H.I.E. is the only platform that audits its own codebase, tracks code health metrics with before/after accountability, and maintains self-documenting rules.",
            "archie_edge": "This category doesn't exist yet. A.R.C.H.I.E. created it — a platform that measures, audits, and proves its own improvement with data.",
            "their_edge": None,
        },
    ]

    # --- Trending / Sensor Scan ---
    trending = [
        {
            "name": "OpenClaw",
            "badge": "247K stars",
            "badge_type": "viral",
            "meta": "Personal AI assistant — Chat apps — Single agent",
            "description": "The one that started the 'claw' craze. A personal AI assistant that lives in your messaging apps. Simple, elegant, one agent doing one thing well.",
            "comparison": {"them": "1 agent", "archie": "23 agents, 10 stations, 39 jobs"},
            "verdict": "Brilliant personal assistant. Not an operations platform. Like comparing a Swiss Army knife to a command center.",
        },
        {
            "name": "PicoClaw",
            "badge": "10MB RAM",
            "badge_type": "tiny",
            "meta": "Ultra-lightweight AI — $10 hardware — Edge computing",
            "description": "OpenClaw's little sibling. Runs on a $10 microcontroller with just 10MB of RAM. Perfect for IoT and embedded systems.",
            "comparison": {"them": "10 MB", "archie": "128 GB, GPU, 13 models loaded"},
            "verdict": "Cool tech, opposite universe. PicoClaw fits in your pocket. A.R.C.H.I.E. runs your entire operation.",
        },
        {
            "name": "Claw Empire",
            "badge": "Dev Toy",
            "badge_type": "fun",
            "meta": "Gamified coding — Pixel art UI — Wraps existing tools",
            "description": "A pixel-art game layer on top of Claude Code and Codex CLI. Fun, viral on TikTok, but it's a skin — the actual AI is someone else's.",
            "comparison": {"them": "Wrapper UI", "archie": "Full platform, own AI, own infrastructure"},
            "verdict": "Great marketing, zero original AI. When the game ends, you're still using Claude Code. A.R.C.H.I.E. IS the platform.",
        },
        {
            "name": "NemoClaw",
            "badge": "Watch",
            "badge_type": "watch",
            "meta": "Nvidia — Enterprise OpenClaw — Guardrails — Alpha",
            "description": "Nvidia's enterprise version of OpenClaw, announced at GTC March 2026. Adds AI guardrails, governance, and safety — features that overlap with A.R.C.H.I.E.'s C.R.E.E.D. ethics system. Still alpha.",
            "comparison": {
                "them": "Guardrails, Governance, Alpha",
                "archie": "C.R.E.E.D. live, Agent welfare, Self-auditing, Production",
            },
            "verdict": "The only one worth watching. Nvidia + governance is serious. But A.R.C.H.I.E.'s C.R.E.E.D. is already live and production-tested.",
        },
    ]

    # --- Stack comparison (tools needed to match A.R.C.H.I.E.) ---
    stack_equivalent = [
        {"tool": "CrewAI", "role": "Agent orchestration"},
        {"tool": "Ollama", "role": "Local model serving"},
        {"tool": "n8n", "role": "Workflow automation"},
        {"tool": "Frigate NVR", "role": "Camera security"},
        {"tool": "AdGuard Home", "role": "DNS protection"},
        {"tool": "Grafana", "role": "Monitoring & dashboards"},
        {"tool": "SonarQube", "role": "Code quality scanning"},
        {"tool": "Claude Code", "role": "AI coding agent"},
        {"tool": "Custom Scripts", "role": "Glue code & cron jobs"},
    ]

    # --- Roadmap gaps (honesty section) ---
    building = [
        {
            "feature": "A2A Protocol",
            "description": "Google's Agent-to-Agent standard for cross-platform agent communication.",
            "who_has_it": ["LangGraph"],
        },
        {
            "feature": "Parallel Agent Execution",
            "description": "Running multiple agents simultaneously on separate tasks.",
            "who_has_it": ["CrewAI", "LangGraph", "Devin", "Claude Code", "Dify", "OpenAI Agents"],
        },
        {
            "feature": "IDE Integration",
            "description": "Plugging into VS Code, JetBrains, or terminal editors for inline code assistance.",
            "who_has_it": ["Cursor", "Windsurf", "Claude Code", "Cline", "Codex CLI", "Aider", "Goose"],
        },
        {
            "feature": "Cloud Auto-Scaling",
            "description": "Automatically spinning up more compute when demand spikes.",
            "who_has_it": ["Devin", "Dify Cloud", "OpenAI Assistants"],
        },
        {
            "feature": "Visual Workflow Builder",
            "description": "Drag-and-drop interface for non-developers to build AI workflows.",
            "who_has_it": ["Dify", "n8n", "Langflow", "Flowise"],
        },
        {
            "feature": "Durable Execution",
            "description": "Checkpoint-based execution that survives crashes and can resume from any point.",
            "who_has_it": ["LangGraph"],
        },
    ]

    # --- Hero stats ---
    hero_stats = {
        "competitors_analyzed": 35,
        "unique_features": 24,
        "features_building": 6,
    }

    return {
        "competitors": competitors,
        "hero_stats": hero_stats,
        "feature_matrix": feature_matrix,
        "categories": categories,
        "trending": trending,
        "stack_equivalent": stack_equivalent,
        "building": building,
        "last_scanned": "2026-03-18",
    }


@public_api_bp.route("/competitors")
def competitors():
    """Public, read-only endpoint returning competitor comparison data.

    Used by kytranempowerment.com to render dynamic comparison charts.
    Cached for 5 minutes.
    """
    data = _get_cached("competitors", _fetch_competitors)
    if isinstance(data, tuple):
        return jsonify(data[0]), data[1]

    response = jsonify(data)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


ALLOWED_ORIGINS = {
    "https://kytranempowerment.com",
    "https://www.kytranempowerment.com",
    "https://creed-ai.org",
    "https://www.creed-ai.org",
    "http://localhost:3000",
    "http://localhost:8080",
}


@public_api_bp.before_request
def handle_preflight():
    """Handle CORS preflight OPTIONS requests."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        return resp


@public_api_bp.after_request
def add_cors_headers(response):
    """Ensure CORS headers on all public API responses."""
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"  # fallback for non-browser
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# ---------------------------------------------------------------------------
# Endpoint 3: /directory — Canonical public agent roster
# ---------------------------------------------------------------------------
#
# Backed by services/public_roster_service.py + public_agent_directory view
# (migration 332). Consolidated from the legacy /tools/department-hq/api/
# agents/public-roster endpoint — same shape, same CORS/PNA headers.
#
# Consumers:
#   - website/kytranempowerment.com/js/directory.js
#   - website/kytranempowerment.com/js/ai-directors.js
#   - creed-ai.org
#   - any external directory surface


def _public_directory_cors(resp, max_age=300):
    """Attach CORS + Private Network Access headers for public consumers."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    resp.headers["Access-Control-Max-Age"] = "86400"
    resp.headers["Cache-Control"] = f"public, max-age={max_age}"
    return resp


@public_api_bp.route("/directory", methods=["GET", "OPTIONS"])
def directory():
    """Public agent directory. Rich shape with acronym, thumb URL, director flag."""
    if request.method == "OPTIONS":
        return _public_directory_cors(jsonify({}), max_age=300)

    department = request.args.get("department")
    agent_type = request.args.get("type")
    search = request.args.get("search")

    cache_key = f"directory:{department}:{agent_type}:{search}"
    data = _get_cached(cache_key, lambda: get_public_roster(department, agent_type, search))

    return _public_directory_cors(jsonify(data), max_age=300)


# ---------------------------------------------------------------------------
# Endpoint 4: /directory/live — Lightweight presence poll
# ---------------------------------------------------------------------------


@public_api_bp.route("/directory/live", methods=["GET", "OPTIONS"])
def directory_live():
    """Live shift states + mood. Short cache window for near-real-time badges."""
    if request.method == "OPTIONS":
        return _public_directory_cors(jsonify({}), max_age=20)

    data = get_public_roster_live()
    return _public_directory_cors(jsonify(data), max_age=20)


# ---------------------------------------------------------------------------
# Endpoint 5: /translate — LLM translation via Bridge dispatcher
# ---------------------------------------------------------------------------

SUPPORTED_LANGS = {"en", "fr", "ar", "he", "es", "zh", "de", "ja"}
LANG_NAMES = {
    "en": "English",
    "fr": "French",
    "ar": "Arabic",
    "he": "Hebrew",
    "es": "Spanish",
    "zh": "Chinese",
    "de": "German",
    "ja": "Japanese",
}


@public_api_bp.route("/translate", methods=["POST"])
def translate():
    """Translate text via Bridge dispatcher."""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    target_lang = (body.get("target_lang") or "").strip().lower()
    source_lang = (body.get("source_lang") or "en").strip().lower()

    # Validation
    if not text:
        return jsonify({"error": "text is required"}), 400
    if not target_lang:
        return jsonify({"error": "target_lang is required"}), 400
    if target_lang not in SUPPORTED_LANGS:
        return jsonify({"error": f"target_lang must be one of: {', '.join(sorted(SUPPORTED_LANGS))}"}), 400
    if source_lang not in SUPPORTED_LANGS:
        return jsonify({"error": f"source_lang must be one of: {', '.join(sorted(SUPPORTED_LANGS))}"}), 400
    if len(text) > 5000:
        return jsonify({"error": "text exceeds 5000 character limit"}), 400

    # Same language — return unchanged
    if source_lang == target_lang:
        resp = jsonify({"translated_text": text, "source_lang": source_lang, "target_lang": target_lang})
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    try:
        from tools.department_hq.services.bridge_dispatcher import get_dispatcher

        get_dispatcher()
        prompt = (
            f"Translate the following text from {LANG_NAMES.get(source_lang, source_lang)} "
            f"to {LANG_NAMES.get(target_lang, target_lang)}. "
            f"Return ONLY the translated text, no explanations.\n\n{text}"
        )
        # Was dispatcher.dispatch(..., max_tokens=...) — that method doesn't
        # exist on the instance and max_tokens isn't a canonical kwarg.
        # Use the module-level dispatch() with a proper DispatchResult.
        from tools.department_hq.services.department_dispatcher import dispatch as _dispatch

        result = _dispatch(
            capability="translation",
            prompt=prompt,
            module_id="public_api_translation",
        )
        translated = result.response.strip() if result and result.success and result.response else ""
        resp = jsonify(
            {
                "translated_text": translated,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
        )
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp
    except Exception as e:
        logger.error("public_api /translate failed: %s", e)
        return (
            jsonify(
                {
                    "error": "translation service unavailable",
                    "translated_text": text,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                }
            ),
            502,
        )


# ---------------------------------------------------------------------------
# Endpoint 6: /compliance/badges — Compliance scan badge scores
# ---------------------------------------------------------------------------


def _score_to_grade(score):
    """Convert numeric score to letter grade + color."""
    if score >= 95:
        return "A+", "#22c55e"
    elif score >= 90:
        return "A", "#22c55e"
    elif score >= 85:
        return "B+", "#3b82f6"
    elif score >= 80:
        return "B", "#3b82f6"
    elif score >= 70:
        return "C", "#eab308"
    elif score >= 60:
        return "D", "#f97316"
    else:
        return "F", "#ef4444"


def _fetch_compliance_badges():
    """Fetch compliance badge data from scan results."""
    try:
        with get_db_cursor() as (conn, cur):
            # Get latest scan per rule pack with pass/fail counts
            cur.execute(
                """
                SELECT
                    rp.pack_id,
                    rp.name AS display_name,
                    rp.total_rules,
                    COUNT(*) FILTER (WHERE sr.status = 'pass') AS passing_rules,
                    COUNT(*) AS total_checked,
                    MAX(sr.scanned_at) AS last_scan
                FROM compliance_scan_results sr
                JOIN compliance_rule_packs rp ON sr.pack_id = rp.pack_id
                WHERE sr.scan_id = (
                    SELECT scan_id FROM compliance_scans
                    ORDER BY completed_at DESC NULLS LAST
                    LIMIT 1
                )
                GROUP BY rp.pack_id, rp.name, rp.total_rules
                ORDER BY rp.name
            """
            )
            rows = [dict(row) for row in cur.fetchall()]

            badges = []
            for row in rows:
                total = row["total_checked"] or 1
                passing = row["passing_rules"] or 0
                score = round(passing / total * 100, 1)
                grade, color = _score_to_grade(score)
                badges.append(
                    {
                        "framework": row["pack_id"],
                        "display_name": row["display_name"],
                        "score": score,
                        "grade": grade,
                        "color": color,
                        "total_rules": total,
                        "passing_rules": passing,
                        "last_scan": row["last_scan"].isoformat() if row["last_scan"] else None,
                    }
                )

            return {"badges": badges, "available": True}
    except Exception as e:
        logger.error("public_api /compliance/badges failed: %s", e)
        return {"badges": [], "available": False}


@public_api_bp.route("/compliance/frameworks")
def compliance_frameworks():
    """Public compliance badge scores per framework (detailed breakdown).

    Note: /api/public/compliance/badges already exists (badge_routes.py)
    with an aggregate view. This endpoint provides per-framework detail.
    """
    data = _get_cached("compliance_frameworks", _fetch_compliance_badges)
    response = jsonify(data)
    response.headers["Cache-Control"] = "public, max-age=600"
    return response


# ---------------------------------------------------------------------------
# Endpoint 7: /creed/stats — Governance transparency stats
# ---------------------------------------------------------------------------


def _fetch_creed_stats():
    """Fetch anonymized governance/welfare stats for C.R.E.E.D. transparency."""
    stats = {}
    try:
        with get_db_cursor() as (conn, cur):
            # Active agent count
            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM agents WHERE status = 'active'")
                stats["agents_monitored"] = cur.fetchone()["cnt"]
            except Exception:
                pass

            # Governance events total
            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM governance_audit_log")
                stats["governance_events_total"] = cur.fetchone()["cnt"]
            except Exception:
                pass

            # Shift state distribution
            try:
                cur.execute(
                    "SELECT shift_state, COUNT(*) AS cnt FROM agents " "WHERE status = 'active' GROUP BY shift_state"
                )
                stats["shift_distribution"] = {row["shift_state"]: row["cnt"] for row in cur.fetchall()}
            except Exception:
                pass

            # Agent welfare averages (last 24h)
            try:
                cur.execute(
                    "SELECT ROUND(AVG(stress_level)::numeric, 2) AS avg_stress, "
                    "ROUND(AVG(mood_intensity)::numeric, 2) AS avg_mood "
                    "FROM agent_emotional_state "
                    "WHERE timestamp > NOW() - INTERVAL '24 hours'"
                )
                row = cur.fetchone()
                if row and row["avg_stress"] is not None:
                    stats["welfare_avg_stress"] = float(row["avg_stress"])
                    stats["welfare_avg_mood_intensity"] = float(row["avg_mood"]) if row["avg_mood"] else None
            except Exception:
                pass

    except Exception as e:
        logger.error("public_api /creed/stats failed: %s", e)
        return {"stats": {}, "available": False}

    return {"stats": stats, "available": bool(stats)}


@public_api_bp.route("/creed/stats")
def creed_stats():
    """Public governance transparency stats for C.R.E.E.D. institute."""
    data = _get_cached("creed_stats", _fetch_creed_stats)
    response = jsonify(data)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


# ---------------------------------------------------------------------------
# Endpoint: /redress-request — User redress / contest an AI decision (#3266)
# ---------------------------------------------------------------------------
#
# Lets a user challenge an AI-made decision. Resolution is routed to a HUMAN
# admin via Telegram (never an AI). Public aggregate stats (no PII) at
# /accountability. grievance_log table (migration 411).


def _add_business_days(start, n):
    """Return start + n business days (skips Sat/Sun)."""
    import datetime as _dt

    d = start
    added = 0
    while added < n:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


@public_api_bp.route("/redress-request", methods=["POST"])
def redress_request():
    """Submit a request to contest an AI-made decision.

    Body: {reason (required), ai_decision_ref?, desired_outcome?, email?}.
    Creates a grievance_log row (status=pending), logs a governance_audit_log
    event, sets a 5-business-day SLA, and Telegram-notifies a human admin.
    Returns {request_ref, status, sla_due_at}. No AI auto-resolution.
    """
    import uuid as _uuid

    from services.time_utils import now_utc

    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    decision_ref = (body.get("ai_decision_ref") or body.get("decision_id") or "").strip()
    desired = (body.get("desired_outcome") or "").strip()
    email = (body.get("email") or body.get("submitter_email") or "").strip()

    # Validation
    if not reason:
        return jsonify({"error": "reason is required"}), 400
    if len(reason) > 4000:
        return jsonify({"error": "reason exceeds 4000 character limit"}), 400
    if len(desired) > 2000:
        return jsonify({"error": "desired_outcome exceeds 2000 character limit"}), 400
    if len(decision_ref) > 200:
        return jsonify({"error": "ai_decision_ref exceeds 200 character limit"}), 400
    if email and ("@" not in email or len(email) > 255):
        return jsonify({"error": "email is invalid"}), 400

    request_ref = "RDR-" + _uuid.uuid4().hex[:8]
    created = now_utc()
    sla_due = _add_business_days(created, 5)

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO grievance_log
                  (request_ref, ai_decision_ref, reason, desired_outcome,
                   submitter_email, status, sla_due_at, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
                RETURNING id
                """,
                (request_ref, decision_ref or None, reason, desired or None, email or None, sla_due, created),
            )
            grievance_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO governance_audit_log
                  (event_type, event_category, action, target_table, target_id,
                   reason, timestamp)
                VALUES ('redress_requested', 'accountability', 'redress_submitted',
                        'grievance_log', %s, %s, %s)
                """,
                (grievance_id, reason[:500], created),
            )
    except Exception as e:
        logger.error("redress_request insert failed: %s", e)
        return jsonify({"error": "could not record request, please retry"}), 500

    # Notify a human admin (never an AI). Best-effort — never block the response.
    try:
        from services import telegram_service

        telegram_service.send_system(
            "New redress request",
            f"{request_ref} — a user is contesting an AI decision"
            f"{(' (' + decision_ref + ')') if decision_ref else ''}. "
            f"SLA: {sla_due.strftime('%Y-%m-%d')}. Reason: {reason[:300]}",
        )
    except Exception as e:
        logger.warning("redress_request Telegram notify failed: %s", e)

    resp = jsonify(
        {
            "request_ref": request_ref,
            "status": "pending",
            "sla_due_at": sla_due.isoformat(),
            "message": "Your request has been logged and routed to a human reviewer.",
        }
    )
    return resp, 201


@public_api_bp.route("/accountability")
def accountability():
    """Public, no-PII redress aggregate stats for creed-ai.org/accountability.

    Returns counts by status, total, and average resolution time. Never exposes
    any individual request content, email, or user identity.
    """

    def _fetch():
        out = {
            "total": 0,
            "by_status": {"pending": 0, "under_review": 0, "resolved": 0, "denied": 0},
            "avg_resolution_days": None,
            "sla_business_days": 5,
            "resolution_is_human": True,
        }
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT status, COUNT(*) AS n FROM grievance_log GROUP BY status")
                for row in cur.fetchall() or []:
                    if row["status"] in out["by_status"]:
                        out["by_status"][row["status"]] = int(row["n"])
                out["total"] = sum(out["by_status"].values())
                cur.execute(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 86400.0)
                           AS avg_days
                    FROM grievance_log
                    WHERE resolved_at IS NOT NULL
                    """
                )
                row = cur.fetchone()
                if row and row["avg_days"] is not None:
                    out["avg_resolution_days"] = round(float(row["avg_days"]), 1)
        except Exception as e:
            logger.error("accountability stats failed: %s", e)
        return out

    data = _get_cached("accountability", _fetch)
    response = jsonify(data)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
