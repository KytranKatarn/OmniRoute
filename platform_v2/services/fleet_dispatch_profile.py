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
