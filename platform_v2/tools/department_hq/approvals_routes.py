"""
Department HQ — Approvals Routes
=================================
Consolidated view of pending Tier-2 approvals with web approve/deny buttons.
Mirrors the Telegram approval flow so agents can be approved via either channel.
"""

import logging

from flask import jsonify, request
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def _build_escalation_chain(agent_display, department, agent_cache):
    """Return [agent_name, department_director_name, 'A.R.C.H.I.E.'] or None.

    Skips the director hop if the agent IS the director (is_department_ai).
    Returns None if the agent can't be resolved (no display name).
    """
    if not agent_display:
        return None
    chain = [agent_display]
    if department and department.lower() != "executive office":
        director = None
        for cached in agent_cache.values():
            if (
                cached.get("department") == department
                and cached.get("is_department_ai")
                and (cached.get("display_name") or cached.get("name")) != agent_display
            ):
                director = cached.get("display_name") or cached.get("name")
                break
        if director:
            chain.append(director)
    chain.append("A.R.C.H.I.E.")
    return chain if len(chain) >= 2 else None


def _approve_autonomy(source_id: int, user_id: int):
    """Approve an autonomy_approval_queue row. Returns (ok, action_type)."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(), updated_at = NOW()
               WHERE id = %s AND status = 'pending'
               RETURNING action_type""",
            (user_id, source_id),
        )
        row = cur.fetchone()
    if not row:
        return (False, None)
    return (True, row["action_type"] if isinstance(row, dict) else row[0])


def _approve_contractor(source_id: int, user_id: int):
    """Approve a contractor_approval_requests row. Sets 14-day expiry window.

    The 14-day expires_at aligns with the re-check in
    archie_bridge.request_contractor_approval, which only honors approvals
    where expires_at IS NULL OR expires_at > NOW().
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE contractor_approval_requests
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(),
                   expires_at = NOW() + INTERVAL '14 days'
               WHERE id = %s AND status = 'pending'
               RETURNING task_type""",
            (user_id, source_id),
        )
        row = cur.fetchone()
    if not row:
        return (False, None)
    return (True, row["task_type"] if isinstance(row, dict) else row[0])


def _approve_bridge(source_id: int, user_id: int):
    """Approve a bridge_jobs row (pending_approval → approved).

    NOTE: No resume consumer exists yet — this is a flag-only approval. The
    original dispatch does not auto-retry. Resume path is a follow-up task.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE bridge_jobs
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(), updated_at = NOW()
               WHERE id = %s AND status = 'pending_approval'
               RETURNING job_type""",
            (user_id, source_id),
        )
        row = cur.fetchone()
    if not row:
        return (False, None)
    return (True, row["job_type"] if isinstance(row, dict) else row[0])


def _deny_autonomy(source_id: int, user_id: int, reason: str) -> bool:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        # Fetch action details before update for denial learning
        cur.execute(
            "SELECT action_type, action_data FROM autonomy_approval_queue WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()

        cur.execute(
            """UPDATE autonomy_approval_queue
               SET status = 'rejected', approved_by = %s,
                   approved_at = NOW(), rejected_reason = %s,
                   updated_at = NOW()
               WHERE id = %s AND status = 'pending'""",
            (user_id, reason, source_id),
        )
        denied = cur.rowcount > 0

    # S.I.G.N.A.L. style learning — store denial reasons for linkedin_post drafts in KB
    if denied and row and row.get("action_type") == "linkedin_post" and reason:
        try:
            import json
            from services.knowledge_service import store_knowledge

            action_data = row.get("action_data") or {}
            if isinstance(action_data, str):
                action_data = json.loads(action_data)
            preview = (action_data.get("content") or "")[:200]

            store_knowledge(
                title=f"LinkedIn Draft Denied — Style Guide Entry",
                content=(
                    f"Kytran denied a LinkedIn post draft.\n\n"
                    f"**Reason:** {reason}\n\n"
                    f"**Draft preview:** {preview}\n\n"
                    f"S.I.G.N.A.L. should avoid this style/topic in future drafts."
                ),
                knowledge_type="vault_note",
                category="signal_style_guide",
                tags=["linkedin", "signal", "style_guide", "denied_draft"],
                importance_score=0.9,
            )
        except Exception:
            pass  # KB store failure must not break denial flow

    return denied


def _deny_contractor(source_id: int, user_id: int, reason: str) -> bool:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE contractor_approval_requests
               SET status = 'denied', denied_by = %s,
                   denied_at = NOW(), denial_reason = %s
               WHERE id = %s AND status = 'pending'""",
            (user_id, reason, source_id),
        )
        return cur.rowcount > 0


def _deny_bridge(source_id: int, user_id: int, reason: str) -> bool:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE bridge_jobs
               SET status = 'cancelled', cancelled_by = %s,
                   cancelled_at = NOW(), cancellation_reason = %s,
                   updated_at = NOW()
               WHERE id = %s AND status = 'pending_approval'""",
            (user_id, reason, source_id),
        )
        return cur.rowcount > 0


def register_approvals_routes(bp, admin_required_decorator):
    """Register all approvals endpoints on the department_hq blueprint."""

    @bp.route("/api/approvals/pending", methods=["GET"])
    @admin_required_decorator
    def approvals_pending():
        """List pending approvals from every source the platform uses.

        Unified over three sources that all share the "waiting for a
        human to approve" semantic:
          - autonomy_approval_queue (Tier-2 agent loop actions)
          - contractor_approval_requests (contractor dispatch cost gate)
          - bridge_jobs with status='pending_approval' (cloud dispatch gate)

        Every row is normalised to the same shape: id, source, category,
        display_name, reason/summary, created_at, agent_name (if any).
        IDs are source-prefixed ("autonomy:123", "bridge:456") so the
        approve/deny endpoints can dispatch to the right table.
        """
        try:
            from database import get_db_cursor

            approvals: list = []

            with get_db_cursor() as (conn, cur):
                # 1. autonomy_approval_queue — Tier-2 agent loop
                cur.execute(
                    """SELECT id, action_type, action_data, tier, priority,
                              requested_by, reason, created_at, expires_at
                       FROM autonomy_approval_queue
                       WHERE status = 'pending' AND tier >= 2
                       ORDER BY priority ASC, created_at ASC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    at = r.get("action_type", "")
                    if at.startswith("compliance_fix_"):
                        category, display = "compliance_fix", "Compliance Fix"
                    elif at == "cloud_throughput_escalation":
                        category, display = "cloud_escalation", "Cloud Model Escalation"
                    elif at == "create_agent":
                        category, display = "agent_creation", "Create New Agent"
                    else:
                        category, display = "other", at
                    approvals.append(
                        {
                            "id": f"autonomy:{r['id']}",
                            "source": "autonomy_approval_queue",
                            "source_id": r["id"],
                            "category": category,
                            "display_name": display,
                            "action_type": at,
                            "tier": r.get("tier"),
                            "priority": r.get("priority"),
                            "reason": r.get("reason"),
                            "requested_by": r.get("requested_by"),
                            "agent_name": None,
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                            "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                        }
                    )

                # 2. contractor_approval_requests — cost-gated contractor dispatch
                cur.execute(
                    """SELECT r.id, r.agent_id, r.task_type, r.task_description,
                              r.module_source, r.estimated_cost, r.estimated_tokens,
                              r.contractor_provider, r.contractor_model,
                              r.priority, r.created_at, r.expires_at,
                              a.name AS agent_name, a.display_name AS agent_display
                       FROM contractor_approval_requests r
                       LEFT JOIN agents a ON a.id = r.agent_id
                       WHERE r.status = 'pending'
                       ORDER BY r.priority ASC NULLS LAST, r.created_at ASC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    approvals.append(
                        {
                            "id": f"contractor:{r['id']}",
                            "source": "contractor_approval_requests",
                            "source_id": r["id"],
                            "category": "contractor_dispatch",
                            "display_name": "Contractor Dispatch",
                            "action_type": r.get("task_type") or "contractor_dispatch",
                            "module_source": r.get("module_source"),
                            "contractor": f"{r.get('contractor_provider') or ''}/{r.get('contractor_model') or ''}".strip(
                                "/"
                            ),
                            "estimated_cost": (
                                float(r["estimated_cost"]) if r.get("estimated_cost") is not None else None
                            ),
                            "estimated_tokens": r.get("estimated_tokens"),
                            "priority": r.get("priority"),
                            "reason": (r.get("task_description") or "")[:300] or None,
                            "agent_name": r.get("agent_display") or r.get("agent_name"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                            "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                        }
                    )

                # 3. bridge_jobs.pending_approval — cloud dispatch gate
                cur.execute(
                    """SELECT id, agent_name, module_source, description, created_at
                       FROM bridge_jobs
                       WHERE status = 'pending_approval'
                       ORDER BY created_at ASC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    desc = r.get("description") or ""
                    approvals.append(
                        {
                            "id": f"bridge:{r['id']}",
                            "source": "bridge_jobs",
                            "source_id": r["id"],
                            "category": "cloud_dispatch",
                            "display_name": "Cloud Dispatch",
                            "action_type": "cloud_dispatch",
                            "module_source": r.get("module_source"),
                            "reason": desc[:300] if desc else None,
                            "agent_name": r.get("agent_name"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )

                # 4. hiring_candidates — Phase A of task #2102
                cur.execute(
                    """SELECT
                           hc.id,
                           hc.capability,
                           hc.gap_reason,
                           hc.narrative,
                           hc.shortlist,
                           hc.proposed_at,
                           hc.proposed_by_agent_id,
                           a.display_name AS proposer_name
                       FROM hiring_candidates hc
                       LEFT JOIN agents a ON a.id = hc.proposed_by_agent_id
                       WHERE hc.status = 'pending'
                       ORDER BY hc.proposed_at DESC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    shortlist = r.get("shortlist")
                    if shortlist is None:
                        shortlist = []
                    approvals.append(
                        {
                            "id": f"hire:{r['id']}",
                            "source": "hire",
                            "source_id": r["id"],
                            "category": "hiring",
                            "display_name": r["capability"],
                            "action_type": "hire_candidate",
                            "reason": r.get("narrative") or r.get("gap_reason"),
                            "agent_name": r.get("proposer_name") or "K.I.N.",
                            "created_at": r["proposed_at"].isoformat() if r.get("proposed_at") else None,
                            "payload": {
                                "shortlist": shortlist,
                                "gap_reason": r.get("gap_reason"),
                                "narrative": r.get("narrative"),
                            },
                        }
                    )

            # Decorate each row with escalation_chain
            try:
                from services.agent_service import get_agent_cache

                agent_cache = get_agent_cache() or {}
            except Exception:
                agent_cache = {}

            for a in approvals:
                display = a.get("agent_name")
                department = None
                if display:
                    for cached in agent_cache.values():
                        cname = cached.get("display_name") or cached.get("name")
                        if cname == display:
                            department = cached.get("department")
                            break
                a["escalation_chain"] = _build_escalation_chain(display, department, agent_cache)

            by_source = {}
            for a in approvals:
                by_source[a["source"]] = by_source.get(a["source"], 0) + 1

            return jsonify(
                {
                    "success": True,
                    "approvals": approvals,
                    "count": len(approvals),
                    "by_source": by_source,
                }
            )
        except Exception as exc:
            logger.error("approvals_pending error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/approvals/hire/<int:hire_id>/approve", methods=["POST"])
    @admin_required_decorator
    def approve_hire(hire_id: int):
        """Approve a hiring_candidates row via web UI.

        Delegates to hiring_service.approve_candidate and maps result.reason
        to HTTP status codes.
        """
        from services import hiring_service

        body = request.get_json(silent=True) or {}
        chosen_agent_id = body.get("chosen_agent_id")
        notes = body.get("notes", "") or ""
        if not isinstance(chosen_agent_id, int):
            return jsonify({"ok": False, "reason": "chosen_agent_id required"}), 400

        result = hiring_service.approve_candidate(
            hire_id=hire_id,
            chosen_agent_id=chosen_agent_id,
            decided_by_user_id=current_user.id,
            notes=notes,
        )

        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "candidate_not_in_shortlist": 400,
            "model_missing": 409,
            "ollama_unreachable": 409,
            "transition_failed": 500,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status

    @bp.route("/api/approvals/hire/<int:hire_id>/reject", methods=["POST"])
    @admin_required_decorator
    def reject_hire(hire_id: int):
        """Reject a hiring_candidates row via web UI.

        Delegates to hiring_service.reject_candidate and maps result.reason
        to HTTP status codes.
        """
        from services import hiring_service

        body = request.get_json(silent=True) or {}
        notes = body.get("notes", "") or ""

        result = hiring_service.reject_candidate(
            hire_id=hire_id,
            decided_by_user_id=current_user.id,
            notes=notes,
        )
        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status

    @bp.route("/api/approvals/<path:approval_id>/approve", methods=["POST"])
    @admin_required_decorator
    def approvals_approve(approval_id):
        """Approve a pending approval via web UI (mirrors Telegram approve).

        Accepts source-prefixed IDs: `autonomy:123`, `contractor:456`, `bridge:789`.
        Dispatches to the appropriate per-source helper.
        """
        try:
            prefix, _, raw_id = approval_id.partition(":")
            if not raw_id or prefix not in ("autonomy", "contractor", "bridge"):
                return jsonify({"success": False, "error": "Invalid approval ID format"}), 400
            try:
                source_id = int(raw_id)
            except ValueError:
                return jsonify({"success": False, "error": "Invalid approval ID"}), 400

            if prefix == "autonomy":
                ok, action_type = _approve_autonomy(source_id, current_user.id)
            elif prefix == "contractor":
                ok, action_type = _approve_contractor(source_id, current_user.id)
            else:  # bridge
                ok, action_type = _approve_bridge(source_id, current_user.id)

            if not ok:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404

            logger.info(
                "Approval %s (%s) approved via web by user %s",
                approval_id,
                action_type,
                current_user.id,
            )
            return jsonify(
                {
                    "success": True,
                    "approval_id": approval_id,
                    "action_type": action_type,
                }
            )
        except Exception as exc:
            logger.error("approvals_approve error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/approvals/<path:approval_id>/deny", methods=["POST"])
    @admin_required_decorator
    def approvals_deny(approval_id):
        """Deny a pending approval via web UI (mirrors Telegram deny).

        Accepts source-prefixed IDs: `autonomy:123`, `contractor:456`, `bridge:789`.
        Dispatches to the appropriate per-source helper.
        """
        try:
            prefix, _, raw_id = approval_id.partition(":")
            if not raw_id or prefix not in ("autonomy", "contractor", "bridge"):
                return jsonify({"success": False, "error": "Invalid approval ID format"}), 400
            try:
                source_id = int(raw_id)
            except ValueError:
                return jsonify({"success": False, "error": "Invalid approval ID"}), 400

            data = request.get_json(silent=True) or {}
            reason = (data.get("reason") or "Denied via web UI").strip()

            if prefix == "autonomy":
                ok = _deny_autonomy(source_id, current_user.id, reason)
            elif prefix == "contractor":
                ok = _deny_contractor(source_id, current_user.id, reason)
            else:
                ok = _deny_bridge(source_id, current_user.id, reason)

            if not ok:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404

            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as exc:
            logger.error("approvals_deny error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/approvals/history", methods=["GET"])
    @admin_required_decorator
    def approvals_history():
        """Recent approval history across all three sources."""
        try:
            from database import get_db_cursor

            limit = min(request.args.get("limit", 50, type=int), 200)
            history = []

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, action_type AS display_name, status,
                              COALESCE(approved_at, executed_at, updated_at) AS decided_at,
                              approved_by AS decided_by,
                              rejected_reason AS reason
                       FROM autonomy_approval_queue
                       WHERE status != 'pending'
                       ORDER BY updated_at DESC LIMIT %s""",
                    (limit,),
                )
                for r in cur.fetchall():
                    r = dict(r)
                    history.append(
                        {
                            "id": f"autonomy:{r['id']}",
                            "source": "autonomy_approval_queue",
                            "display_name": r["display_name"],
                            "status": r["status"],
                            "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
                            "decided_by": r.get("decided_by"),
                            "reason": r.get("reason"),
                        }
                    )

                cur.execute(
                    """SELECT id, task_type AS display_name, status,
                              COALESCE(approved_at, denied_at, created_at) AS decided_at,
                              COALESCE(approved_by, denied_by) AS decided_by,
                              denial_reason AS reason
                       FROM contractor_approval_requests
                       WHERE status != 'pending'
                       ORDER BY COALESCE(approved_at, denied_at, created_at) DESC NULLS LAST
                       LIMIT %s""",
                    (limit,),
                )
                for r in cur.fetchall():
                    r = dict(r)
                    history.append(
                        {
                            "id": f"contractor:{r['id']}",
                            "source": "contractor_approval_requests",
                            "display_name": r["display_name"],
                            "status": r["status"],
                            "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
                            "decided_by": r.get("decided_by"),
                            "reason": r.get("reason"),
                        }
                    )

                cur.execute(
                    """SELECT id, job_type AS display_name, status,
                              COALESCE(approved_at, cancelled_at, completed_at, updated_at) AS decided_at,
                              COALESCE(approved_by, cancelled_by) AS decided_by,
                              cancellation_reason AS reason
                       FROM bridge_jobs
                       WHERE status IN ('approved', 'cancelled', 'completed', 'failed')
                       ORDER BY COALESCE(approved_at, cancelled_at, completed_at, updated_at) DESC NULLS LAST
                       LIMIT %s""",
                    (limit,),
                )
                for r in cur.fetchall():
                    r = dict(r)
                    history.append(
                        {
                            "id": f"bridge:{r['id']}",
                            "source": "bridge_jobs",
                            "display_name": r["display_name"],
                            "status": r["status"],
                            "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
                            "decided_by": r.get("decided_by"),
                            "reason": r.get("reason"),
                        }
                    )

            history.sort(key=lambda h: h.get("decided_at") or "", reverse=True)
            history = history[:limit]
            return jsonify({"success": True, "history": history})
        except Exception as exc:
            logger.error("approvals_history error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
