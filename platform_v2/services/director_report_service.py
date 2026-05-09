"""Client for platform_v2 to interact with archie-comms director_reports.

Provides get_pending_reports(), triage_report(), classify_report(),
get_policies(), and submit_via_inbox() for the triage consumer job.
"""

import hashlib
import logging
import os
import time as _time
import threading

import requests

logger = logging.getLogger(__name__)

# In-process dedup cache: (category, source_agent, title_hash) -> last_submitted_epoch
# Used by submit_via_inbox when cooldown_hours > 0 to suppress repeated watchdog reports.
_dedup_cache: dict = {}
_dedup_lock = threading.Lock()

_COMMS_BASE = os.getenv("ARCHIE_COMMS_URL", "http://archie_comms:3002")
_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")
_TIMEOUT = 5

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"Content-Type": "application/json", "X-Service-Token": _TOKEN}


# ---------------------------------------------------------------------------
# Report CRUD
# ---------------------------------------------------------------------------


def get_pending_reports(limit: int = 20) -> list:
    """Fetch pending director_reports ordered by severity then age."""
    try:
        resp = requests.get(
            f"{_COMMS_BASE}/api/internal/director-reports",
            headers=_headers(),
            params={"limit": limit},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("reports", [])
    except Exception as e:
        logger.error("get_pending_reports failed: %s", e)
        return []


def triage_report(report_id: int, action: str, reason: str = "") -> bool:
    """Mark a report with triage action (resolve/consolidate/suppress/escalate)."""
    try:
        resp = requests.post(
            f"{_COMMS_BASE}/api/internal/director-reports/{report_id}/triage",
            headers=_headers(),
            json={"action": action, "reason": reason},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("success", False)
    except Exception as e:
        logger.error("triage_report(%s, %s) failed: %s", report_id, action, e)
        return False


def submit_via_inbox(
    category: str,
    title: str,
    message: str,
    source_agent: str = None,
    severity: str = "medium",
    department: str = "Unknown",
    cooldown_hours: float = 0,
) -> dict:
    """Write a message to the director_reports inbox (for privilege-redirected callers).

    When cooldown_hours > 0, repeated reports with the same category+source_agent+title
    are suppressed within the cooldown window — prevents watchdog floods for persistent
    conditions (e.g. B.A.S.E. stuck-agent reports every 10 minutes).
    """
    dedup_key = None
    if cooldown_hours > 0:
        title_hash = hashlib.md5(title.encode(), usedforsecurity=False).hexdigest()[:8]
        dedup_key = (category, source_agent or "unknown", title_hash)
        now = _time.time()
        with _dedup_lock:
            last = _dedup_cache.get(dedup_key, 0)
            if now - last < cooldown_hours * 3600:
                logger.debug(
                    "submit_via_inbox: suppressed duplicate '%s/%s' (cooldown %.1fh)",
                    category,
                    title[:40],
                    cooldown_hours,
                )
                return {"success": True, "routed_to": "suppressed_duplicate"}
    try:
        resp = requests.post(
            f"{_COMMS_BASE}/api/director/report",
            headers=_headers(),
            json={
                "department": department,
                "director_agent": source_agent or "unknown",
                "severity": severity,
                "category": category,
                "title": title,
                "summary": message,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        if dedup_key is not None:
            with _dedup_lock:
                _dedup_cache[dedup_key] = _time.time()
        return {"success": True, "routed_to": "inbox"}
    except Exception as e:
        logger.error("submit_via_inbox failed: %s", e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------

# Default rules — (severity, category_prefix, director_pattern, action, reason)
# First match wins. None = wildcard.
_DEFAULT_RULES = [
    ("critical", None, None, "escalate", "Critical severity always escalates"),
    ("high", "security", None, "escalate", "High-severity security event"),
    ("high", None, None, "escalate", "High severity requires Kytran attention"),
    ("warning", None, None, "escalate", "Warning severity requires Kytran attention"),
    ("medium", "operations", "B.A.S.E.", "consolidate", "B.A.S.E. ops reports consolidated"),
    ("medium", None, None, "suppress", "Medium severity suppressed by default"),
    ("low", None, None, "suppress", "Low severity auto-suppressed"),
    (None, None, None, "suppress", "Default: suppress unknown"),
]


def classify_report(report: dict, policies: list = None) -> tuple:
    """Return (action, reason) for a report.

    Checks DB-driven policies first (highest priority = lowest number),
    then falls through to _DEFAULT_RULES.

    Actions: resolve | consolidate | suppress | escalate
    """
    severity = (report.get("severity") or "low").lower()
    category = (report.get("category") or "").lower()
    director = (report.get("director_agent") or "").upper()

    all_rules = []
    for p in policies or []:
        all_rules.append(
            (
                p.get("severity"),
                p.get("category_prefix"),
                p.get("director_agent_pattern"),
                p["action"],
                p["reason"],
            )
        )
    all_rules.extend(_DEFAULT_RULES)

    for r_sev, r_cat, r_dir, action, reason in all_rules:
        if r_sev and r_sev != severity:
            continue
        if r_cat and not category.startswith(r_cat.lower()):
            continue
        if r_dir and r_dir.upper() not in director:
            continue
        return action, reason

    return "suppress", "No matching rule — default suppress"


# ---------------------------------------------------------------------------
# Policy cache (5-min TTL)
# ---------------------------------------------------------------------------

_policy_cache: list = []
_policy_cache_ts: float = 0.0
_POLICY_CACHE_TTL = 300


def get_policies() -> list:
    """Fetch triage policies from archie-comms with 5-min cache."""
    global _policy_cache, _policy_cache_ts
    if _time.time() - _policy_cache_ts < _POLICY_CACHE_TTL:
        return _policy_cache
    try:
        resp = requests.get(
            f"{_COMMS_BASE}/api/internal/triage-policies",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        _policy_cache = resp.json().get("policies", [])
        _policy_cache_ts = _time.time()
        return _policy_cache
    except Exception as e:
        logger.warning("get_policies failed, using stale cache: %s", e)
        return _policy_cache


def create_policy(
    action: str,
    reason: str,
    severity: str = None,
    category_prefix: str = None,
    director_agent_pattern: str = None,
    priority: int = 50,
) -> dict:
    """Create a new triage policy in archie-comms."""
    global _policy_cache_ts
    try:
        resp = requests.post(
            f"{_COMMS_BASE}/api/internal/triage-policies",
            headers=_headers(),
            json={
                "action": action,
                "reason": reason,
                "severity": severity or None,
                "category_prefix": category_prefix or None,
                "director_agent_pattern": director_agent_pattern or None,
                "priority": priority,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        _policy_cache_ts = 0  # invalidate cache
        return resp.json()
    except Exception as e:
        logger.error("create_policy failed: %s", e)
        return {"success": False, "error": str(e)}


def delete_policy(policy_id: int) -> bool:
    """Delete a triage policy by id."""
    global _policy_cache_ts
    try:
        resp = requests.delete(
            f"{_COMMS_BASE}/api/internal/triage-policies/{policy_id}",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        _policy_cache_ts = 0  # invalidate cache
        return resp.json().get("success", False)
    except Exception as e:
        logger.error("delete_policy(%s) failed: %s", policy_id, e)
        return False
