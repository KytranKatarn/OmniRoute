"""Shared AGENT MOBILITY PROFILE helper (auto / news / platform).

Single source of truth for the fleet dispatch profile selected in the
A.R.M.A.D.A. (DHQ → Fleet) "AGENT MOBILITY PROFILE" control. The profile is
persisted in ``system_config.fleet_dispatch_mode`` by
``/api/fleet/dispatch-mode``. This module lets K.I.N. warmth
(``services/fleet_jobs.py``), the score-based fleet router
(``services/fleet_resource_router.py`` callers), and the Fleet Backlog Runner
(``ai_bridge/agent_loop.py``) all read the SAME profile and apply a consistent
priority rule — so the AUTO / 📰 NEWS / 🖥 PLATFORM buttons move warmth,
routing, and backlog together instead of being a UI-only stub.

Profiles
--------
auto      no profile bias — pure demand / score (the default).
news      News & Media agents get warm-slot + routing + backlog priority.
platform  all non-News (core platform) agents get priority.

The dispatcher's own ``_find_fleet_agent_for_hub_agent`` already reads the same
``fleet_dispatch_mode`` key for node-ordering (routing block 1a); this helper
covers the remaining surfaces (warmth, score-path, backlog) and keeps the
"News vs everything-else" split identical to that block's ``is_news`` logic.
"""

from typing import Optional

VALID_MODES = ("auto", "news", "platform")

# Mirror dispatcher block 1a: the split is binary — News & Media vs the rest.
NEWS_DEPARTMENT = "News & Media"


def get_dispatch_mode() -> str:
    """Return the active mobility profile from system_config. Fail-safe → 'auto'."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute("SELECT value FROM system_config WHERE key='fleet_dispatch_mode'")
            row = cur.fetchone()
            mode = (row["value"] if row else "auto").lower()
        return mode if mode in VALID_MODES else "auto"
    except Exception:
        return "auto"


def is_priority_department(department: Optional[str], mode: str) -> bool:
    """Does ``department`` get priority under the active ``mode``?

    auto      → always False (no bias).
    news      → True only for News & Media.
    platform  → True for any non-News department (core platform).
    """
    if not mode or mode == "auto":
        return False
    dept = (department or "").strip()
    if not dept:
        return False
    if mode == "news":
        return dept == NEWS_DEPARTMENT
    if mode == "platform":
        return dept != NEWS_DEPARTMENT
    return False


# Project-name keywords that mark a project as NEWS / watch-product work (vs
# core PLATFORM work). Used by the Fleet Backlog Runner to drain the active
# profile's product backlog first. Best-effort + fail-safe: a misclassification
# only reorders backlog promotion, it never drops or duplicates a task.
NEWS_PROJECT_KEYWORDS = (
    "wtf",
    "what the fact",
    "creed",
    "c.r.e.e.d",
    "civic watch",
    "legal watch",
    "market watch",
    "gov watch",
    "watch —",
    "watch -",
    "watch series",
    "news & media",
)


# Module ids that produce NEWS / watch-product work in dispatch_pending_queue.
#
# ⚠️ Why module_id and not capability alone: the capability→department map is
# authoritative for ROUTING but does NOT describe which PRODUCT the work serves.
# Measured 2026-07-23, the live queue was 80 rows of which ~61 were WTF work, yet
# `classify` (38 rows, the single largest block) maps to "Analytics & Intelligence",
# and `translate` (13) to "Documentation & Knowledge" — neither is News & Media.
# Classifying by capability alone would therefore have marked the bulk of the news
# backlog as PLATFORM work and boosted it under platform mode, i.e. the exact
# opposite of the operator's intent. `source_product` is no help either — every row
# carries 'archie_platform'.
NEWS_MODULE_KEYWORDS = (
    "wtf",
    "quality_scorer",
    "coverage_scan",
    "bias",
    "factcheck",
    "fact_check",
    "news",
    "article",
    "beat",
)


def is_news_queue_row(capability: Optional[str], module_id: Optional[str]) -> bool:
    """Best-effort: is this dispatch_pending_queue row NEWS/watch-product work?

    Two signals, OR'd — a row is news if EITHER its capability routes to News & Media
    OR its module_id looks like a watch-product producer. Deliberately generous: a
    false positive only reorders a queue, it never drops or duplicates work.
    """
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

    cap = (capability or "").strip()
    if cap and CAPABILITY_DEPARTMENT_MAP.get(cap) == NEWS_DEPARTMENT:
        return True
    mod = (module_id or "").strip().lower()
    return bool(mod) and any(k in mod for k in NEWS_MODULE_KEYWORDS)


def queue_row_gets_priority(capability: Optional[str], module_id: Optional[str], mode: str) -> bool:
    """Does this queued dispatch row get drained first under ``mode``?

    auto      → always False (no bias; drain order byte-identical to pre-profile).
    news      → news rows first.
    platform  → everything that is NOT news first.
    """
    if not mode or mode == "auto":
        return False
    is_news = is_news_queue_row(capability, module_id)
    if mode == "news":
        return is_news
    if mode == "platform":
        return not is_news
    return False


def is_priority_project(project_name: Optional[str], mode: str) -> bool:
    """Best-effort: does this project's backlog get priority under ``mode``?

    news      → projects matching NEWS_PROJECT_KEYWORDS (WTF / watch / CREED).
    platform  → every other (named) project.
    auto      → always False (no bias).
    """
    if not mode or mode == "auto":
        return False
    name = (project_name or "").strip().lower()
    if not name:
        return False
    is_news = any(k in name for k in NEWS_PROJECT_KEYWORDS)
    if mode == "news":
        return is_news
    if mode == "platform":
        return not is_news
    return False
