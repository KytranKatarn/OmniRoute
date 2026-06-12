"""C.R.E.E.D. Command — main routes and admin_required decorator (scaffold, P0)."""

import json
import logging
import os
import time
import urllib.request
from functools import wraps

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from rbac import Permission, has_permission
from logging_config import audit_log
from database import get_db_cursor

logger = logging.getLogger(__name__)

_CREED_URL = os.getenv("CREED_API_URL", "http://192.168.1.200:8086")
_dash_cache = {"ts": 0.0, "data": None}
_DASH_TTL = 60  # seconds


def admin_required(f):
    """Decorator to require admin access (matches the platform module pattern)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permission.ADMIN_ACCESS, current_user):
            audit_log(
                "ADMIN_ACCESS_DENIED",
                {
                    "route": request.endpoint,
                    "user_id": (current_user.id if current_user.is_authenticated else None),
                },
                success=False,
            )
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


from . import creed_command_bp  # noqa: E402


@creed_command_bp.route("/")
@login_required
@admin_required
def creed_command_home():
    """C.R.E.E.D. Command Center — E.T.H.O.S. work dashboard (tabbed shell)."""
    return render_template("creed_command.html")


@creed_command_bp.route("/api/status")
def creed_command_status():
    """Unauthenticated health/status endpoint (used by the module registry)."""
    return jsonify(
        {
            "healthy": True,
            "module": "creed_command",
            "agent": "E.T.H.O.S.",
            "phase": "P0 scaffold",
        }
    )


def _fetch_creed_governance():
    """Server-side fetch of live C.R.E.E.D. governance grade + incident count.

    Server-side (not browser) on purpose: the hub-LAN admin page would hit Chrome
    Private Network Access if it fetched creed.kytranempowerment.com directly
    (split-horizon DNS, KB #269948). Best-effort.
    """
    out = {"grade": None, "score": None, "incidents_disclosed": None}
    try:
        s = json.loads(urllib.request.urlopen(_CREED_URL + "/api/v1/scores", timeout=5).read())
        out["grade"] = s.get("grade")
        ov = s.get("overall")
        out["score"] = round(ov, 1) if isinstance(ov, (int, float)) else None
    except Exception as e:
        logger.warning("creed_command: scores fetch failed: %s", e)
    try:
        i = json.loads(urllib.request.urlopen(_CREED_URL + "/api/public/incidents", timeout=5).read())
        out["incidents_disclosed"] = i.get("count")
    except Exception as e:
        logger.warning("creed_command: incidents fetch failed: %s", e)
    return out


def _build_dashboard():
    """Gather the E.T.H.O.S. dashboard payload from live sources (best-effort)."""
    data = {
        "governance": _fetch_creed_governance(),
        "redress": {"total": 0, "pending": 0},
        "grants": {"active": 0, "next_deadline": None},
        "ethos_activity_7d": 0,
        "recent_activity": [],
        "latest_brief": None,
    }
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT status, COUNT(*) AS n FROM grievance_log GROUP BY status")
            for r in cur.fetchall() or []:
                data["redress"]["total"] += int(r["n"])
                if r["status"] == "pending":
                    data["redress"]["pending"] = int(r["n"])
            cur.execute(
                "SELECT COUNT(*) AS n FROM task_execution_log "
                "WHERE agent_name='E.T.H.O.S.' AND created_at > NOW() - INTERVAL '7 days'"
            )
            row = cur.fetchone()
            data["ethos_activity_7d"] = int(row["n"]) if row else 0
            cur.execute(
                "SELECT capability, success, created_at FROM task_execution_log "
                "WHERE agent_name='E.T.H.O.S.' ORDER BY created_at DESC LIMIT 6"
            )
            data["recent_activity"] = [
                {
                    "capability": r["capability"],
                    "success": bool(r["success"]),
                    "at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in cur.fetchall() or []
            ]
            cur.execute(
                "SELECT title, created_at FROM knowledge_base "
                "WHERE source_type='ethos_ethics_brief' ORDER BY created_at DESC LIMIT 1"
            )
            b = cur.fetchone()
            if b:
                data["latest_brief"] = {
                    "title": b["title"],
                    "at": b["created_at"].isoformat() if b["created_at"] else None,
                }
            cur.execute(
                "SELECT COUNT(*) AS n, "
                "MIN(deadline) FILTER (WHERE deadline >= CURRENT_DATE) AS next_deadline "
                "FROM creed_grants WHERE status NOT IN ('awarded', 'declined')"
            )
            gr = cur.fetchone()
            if gr:
                data["grants"]["active"] = int(gr["n"])
                nd = gr["next_deadline"]
                data["grants"]["next_deadline"] = nd.isoformat() if nd else None
    except Exception as e:
        logger.error("creed_command: dashboard DB gather failed: %s", e)
    return data


@creed_command_bp.route("/api/dashboard")
@login_required
@admin_required
def creed_command_dashboard():
    """E.T.H.O.S. dashboard KPIs + recent activity (60s cached, server-side gather)."""
    now = time.time()
    if _dash_cache["data"] is None or (now - _dash_cache["ts"]) > _DASH_TTL:
        _dash_cache["data"] = _build_dashboard()
        _dash_cache["ts"] = now
    return jsonify(_dash_cache["data"])


_welfare_cache = {"data": None, "ts": 0.0}
_WELFARE_TTL = 60


@creed_command_bp.route("/api/welfare")
@login_required
@admin_required
def creed_command_welfare():
    """AI-workforce welfare score + improvement recommendations (#379 Phase 5).

    The org's own accountability surface: how it treats its AI workforce. Live score
    (the daily creed_welfare_governance job persists history to agent_welfare_scores).
    60s cached. All values are plain JSON types — jsonify-safe.
    """
    now = time.time()
    if _welfare_cache["data"] is None or (now - _welfare_cache["ts"]) > _WELFARE_TTL:
        try:
            from services.welfare_governance_service import (
                compute_welfare_snapshot,
                get_latest_welfare_score,
            )

            with get_db_cursor() as (conn, cur):
                data = compute_welfare_snapshot(cur)
                latest = get_latest_welfare_score(cur)
            if latest and latest.get("computed_at"):
                data["last_run_at"] = latest["computed_at"].isoformat()
            else:
                data["last_run_at"] = None
            _welfare_cache["data"] = data
            _welfare_cache["ts"] = now
        except Exception as e:
            logger.warning("creed_command: welfare load failed: %s", e)
            return jsonify({"error": "unavailable"}), 503
    return jsonify(_welfare_cache["data"])
