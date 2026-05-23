"""M.A.R.K.E.T. dispatch endpoint — hub-side HTTP surface for the Market Watch
standalone's AI chat overlay.

Mirror of gavel_dispatch.py / civic_dispatch.py — same JWT HS256 bearer auth,
same Bridge dispatch path. Standalone is Kytran Market Watch at
market.kytranempowerment.com; the /api/market/chat route hits this endpoint
so welfare-gating + cost tracking + fleet routing are honoured through DHQ.

Contract:

    POST /api/market/dispatch
    Authorization: Bearer <kytran access_token>
    Content-Type: application/json

    {
        "capability": "market_analysis",   # required
        "prompt":     "...",               # required
        "system":     "...",               # optional — override M.A.R.K.E.T. persona
    }

Returns:

    {
        "response":    "M.A.R.K.E.T. here. ...",
        "agent":       "M.A.R.K.E.T.",
        "agent_id":    32,
        "model":       "mistral:7b",
        "department":  "Analytics & Intelligence",
        "duration_ms": 1234,
        "cost":        0.0,
        "user":        "<username>"
    }

Supported capabilities (M.A.R.K.E.T. agent_skills):
    market_analysis, market_intelligence, stock_analysis, portfolio_analysis,
    sector_analysis, technical_analysis, risk_assessment, earnings_analysis
"""

from __future__ import annotations

import logging

import jwt
from flask import Blueprint, current_app, jsonify, request

from database import get_db_cursor

log = logging.getLogger("platform.market_dispatch")

market_dispatch_bp = Blueprint("market_dispatch", __name__, url_prefix="/api/market")

VALID_CAPABILITIES = {
    "market_analysis",
    "market_intelligence",
    "stock_analysis",
    "portfolio_analysis",
    "sector_analysis",
    "technical_analysis",
    "risk_assessment",
    "earnings_analysis",
    "trading_strategy",
    "economic_outlook",
}


def _resolve_user_from_bearer() -> tuple[int | None, dict | str]:
    """Return (user_id, user_row_or_err). Mirrors gavel_dispatch pattern."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Bearer token required"
    token = auth_header[7:]

    secret = current_app.config.get("SECRET_KEY", "fallback-secret")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"

    user_id = payload.get("sub")
    if not user_id:
        return None, "Invalid token payload"

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, username, role FROM users WHERE id = %s AND is_active = TRUE",
            (user_id,),
        )
        user = cur.fetchone()
    if not user:
        return None, "User not found"
    return int(user["id"]), user


@market_dispatch_bp.route("/dispatch", methods=["POST"])
def dispatch_market():
    user_id, user_or_err = _resolve_user_from_bearer()
    if user_id is None:
        return jsonify({"error": user_or_err}), 401
    user = user_or_err

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "market_analysis").strip()
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    if capability not in VALID_CAPABILITIES:
        capability = "market_analysis"

    prompt = prompt[:16000]
    system = (data.get("system") or "").strip()[:4000] or None

    # Load M.A.R.K.E.T.'s stored persona from agents table
    if not system:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT system_prompt FROM agents WHERE name = %s",
                    ("M.A.R.K.E.T.",),
                )
                row = cur.fetchone()
                if row and row.get("system_prompt"):
                    system = row["system_prompt"]
        except Exception:
            log.exception("failed to load M.A.R.K.E.T. system_prompt; continuing without")

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability=capability,
            prompt=prompt,
            system_prompt=system,
        )
    except Exception as e:
        log.exception("market dispatch failed for user %s", user_id)
        return jsonify({"error": f"dispatch failed: {e}"}), 502

    if not getattr(result, "success", False):
        return (
            jsonify(
                {
                    "error": getattr(result, "error", "dispatch returned non-success"),
                    "department": getattr(result, "department", None),
                }
            ),
            502,
        )

    meta = getattr(result, "metadata", None) or {}
    cost = float(meta.get("cost", 0.0) or 0.0)
    agent_id = getattr(result, "agent_id", None)
    agent_label = getattr(result, "agent_name", None)
    if agent_id:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT name, display_name FROM agents WHERE id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
                if row:
                    agent_label = row.get("name") or row.get("display_name") or agent_label
        except Exception:
            log.exception("agent name lookup failed for id=%s", agent_id)

    return (
        jsonify(
            {
                "response": getattr(result, "response", ""),
                "agent": agent_label,
                "agent_id": agent_id,
                "model": getattr(result, "model_used", None),
                "department": meta.get("agent_department")
                or meta.get("department")
                or getattr(result, "department", None),
                "duration_ms": int(getattr(result, "duration_ms", 0) or 0),
                "cost": cost,
                "user": user["username"],
            }
        ),
        200,
    )
