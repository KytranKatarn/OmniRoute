"""Procure dispatch endpoint — hub-side HTTP surface for the Gov Watch
standalone's P.R.O.C.U.R.E. surface (Project #203 Phase 1).

Mirror of maven_dispatch.py — same JWT HS256 bearer auth, same
Bridge dispatch path. Standalone is Kytran Gov Watch at
gov.kytranempowerment.com; the /procure route there hits this
endpoint for every P.R.O.C.U.R.E. call so welfare-gating + cost
tracking + GPU placement are honoured through Department HQ.

Contract:

    POST /api/procure/dispatch
    Authorization: Bearer <kytran access_token>
    Content-Type: application/json

    {
        "capability": "tender_match",   # required — must exist in
                                         # CAPABILITY_DEPARTMENT_MAP
        "prompt":     "...",             # required
        "system":     "...",             # optional — override
                                         # P.R.O.C.U.R.E.'s default persona
        "model":      "qwen2.5:7b"       # optional — ignored today,
                                         # reserved for phase 2 overrides
    }

Returns:

    {
        "response": "Procure here. ...",
        "agent":    "P.R.O.C.U.R.E.",
        "tier":     "home",
        "cost":     0.0,
        "user":     "<username>"
    }

Supported capabilities (seeded as P.R.O.C.U.R.E. agent_skills):
    tender_match, tender_summarize, bid_draft, naics_mapping,
    deadline_alert, award_history_analysis, sosa_navigation,
    supplier_profile
"""

from __future__ import annotations

import logging

import jwt
from flask import Blueprint, current_app, jsonify, request

from database import get_db_cursor

log = logging.getLogger("platform.procure_dispatch")

procure_dispatch_bp = Blueprint("procure_dispatch", __name__, url_prefix="/api/procure")


def _resolve_user_from_bearer() -> tuple[int | None, dict | str]:
    """Return (user_id, user_row_or_err_message). user_id is None on
    failure and the second element carries the error string. Mirrors
    /oauth/userinfo validation."""
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


@procure_dispatch_bp.route("/dispatch", methods=["POST"])
def dispatch_procure():
    user_id, user_or_err = _resolve_user_from_bearer()
    if user_id is None:
        return jsonify({"error": user_or_err}), 401
    user = user_or_err

    data = request.get_json(silent=True) or {}
    capability = (data.get("capability") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    if not capability or not prompt:
        return jsonify({"error": "capability + prompt required"}), 400

    # Truncate defensively — RFP pastes can be large; a rogue standalone
    # shouldn't be able to pin the dispatcher.
    prompt = prompt[:16000]
    system = (data.get("system") or "").strip()[:4000] or None
    model = (data.get("model") or "").strip() or None

    # Persona injection: if the caller didn't supply a system prompt, load
    # P.R.O.C.U.R.E.'s stored persona from the agents table so every
    # response opens with "Procure here." The dispatcher does NOT auto-load
    # an agent's system_prompt today, so we do it here — keeps the
    # standalone persona-agnostic (single source of truth is the DB row).
    if not system:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT system_prompt FROM agents WHERE name = %s",
                    ("P.R.O.C.U.R.E.",),
                )
                row = cur.fetchone()
                if row and row.get("system_prompt"):
                    system = row["system_prompt"]
        except Exception:
            log.exception("failed to load P.R.O.C.U.R.E. system_prompt; continuing without")

    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        _ = model  # noqa: F841 — reserved for phase 2 agent-aware overrides
        result = dispatch(
            capability=capability,
            prompt=prompt,
            system_prompt=system,
        )
    except Exception as e:
        log.exception("procure dispatch failed for user %s", user_id)
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

    # DispatchResult fields: agent_name, agent_id, model_used, department.
    # Cost lives under metadata for contractor/cloud calls; local Ollama is
    # free (0.0).
    #
    # Two hub-wide display bugs in DispatchResult we work around here:
    # (a) agent_name is mislabelled as "ARCHIE" even when agent_id is a
    #     specialist — resolve the real display name from the agents table
    #     using the agent_id so this endpoint reports the correct worker.
    # (b) `department` aliases `station_code` which holds the floor (SERVICES)
    #     rather than the department. metadata.agent_department has the
    #     proper value.
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
                    # Prefer the acronym name (P.R.O.C.U.R.E.) over display
                    # (Procure) — name is what's on the module card.
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
