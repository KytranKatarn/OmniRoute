"""
Department HQ — Approvals Routes
=================================
Consolidated view of pending Tier-2 approvals with web approve/deny buttons.
Mirrors the Telegram approval flow so agents can be approved via either channel.
"""

import logging

from flask import jsonify, request
from flask_login import current_user

logger = logging.getLogger(__name__)


# Preserve the original callable import surface used by the cockpit and tests.
from . import approvals_helpers as _helpers
from .approvals_queue import list_pending_approvals

_code_fix_label = _helpers._code_fix_label
_code_fix_reason = _helpers._code_fix_reason
_build_escalation_chain = _helpers._build_escalation_chain
_already_approved = _helpers._already_approved
_approve_autonomy = _helpers._approve_autonomy
_approve_contractor = _helpers._approve_contractor
_approve_bridge = _helpers._approve_bridge
_deny_autonomy = _helpers._deny_autonomy
_deny_contractor = _helpers._deny_contractor
_deny_bridge = _helpers._deny_bridge
parse_approval_id = _helpers.parse_approval_id


def register_approvals_routes(bp, admin_required_decorator):
    """Register all approvals endpoints on the department_hq blueprint."""

    @bp.route("/api/approvals/pending", methods=["GET"])
    @admin_required_decorator
    def approvals_pending():
        """List pending approvals from every source the platform uses.

        Thin wrapper over module-level list_pending_approvals() (shared with the
        cockpit's internal endpoint); preserves the {success, approvals, count,
        by_source} envelope the DHQ Approvals tab consumes.
        """
        try:
            from tools.department_hq.services.approvals_bulk import (
                MAX_BULK,
                blocking_reasons,
                bulk_all_reason,
                can_bulk_all,
                category_of,
                category_priority,
            )

            from tools.department_hq.services.approvals_bulk import (
                BACKUP_FRESH_HOURS,
                backup_is_actionable,
                unsatisfied_prerequisites,
            )

            approvals = list_pending_approvals()
            pending_types = {(a.get("action_type") or "").strip().lower() for a in approvals}

            # A prerequisite is satisfied by the ARTIFACT, not by the status field
            # (ADR-014). Approving a backup removes it from `pending` INSTANTLY while the
            # executor has not run and nothing is on disk yet — measured 2026-08-19 on
            # #11442 — so the gate must also ask: is one still RUNNING, and did a backup
            # actually LAND? Both are cheap indexed reads.
            backup_in_flight, recent_backup_ok, pr_merge_open = False, True, None
            try:
                from database import get_db_cursor

                with get_db_cursor(commit=False) as (_c, cur):
                    cur.execute(
                        "SELECT count(*) AS n FROM autonomy_approval_queue "
                        "WHERE action_type='backup_before_deploy' AND status='approved' "
                        "AND executed_at IS NULL"
                    )
                    row = cur.fetchone()
                    backup_in_flight = bool((row["n"] if isinstance(row, dict) else row[0]) or 0)

                    cur.execute(
                        "SELECT count(*) AS n FROM backup_log "
                        "WHERE status='success' AND created_at > now() - make_interval(hours => %s)",
                        (BACKUP_FRESH_HOURS,),
                    )
                    row = cur.fetchone()
                    recent_backup_ok = bool((row["n"] if isinstance(row, dict) else row[0]) or 0)

                    # Is any PENDING pr_merge approval about a PR that is STILL OPEN?
                    # A pending row whose PR already merged is stale and must not block —
                    # merging through Repair Bay does not action the approval row, and
                    # historic rows sat 24-50h before expiring. `pr_reviews.state` is the
                    # cheap local mirror Repair Bay maintains; anything not 'open'
                    # (closed / merged) means the merge already happened.
                    cur.execute(
                        """
                        SELECT count(*) AS n
                          FROM autonomy_approval_queue q
                          JOIN pr_reviews r
                            ON r.pr_number = NULLIF(q.action_data->>'pr_number','')::int
                         WHERE q.action_type = 'pr_merge'
                           AND q.status = 'pending' AND q.executed_at IS NULL
                           AND r.state = 'open'
                        """
                    )
                    row = cur.fetchone()
                    pr_merge_open = bool((row["n"] if isinstance(row, dict) else row[0]) or 0)
            except Exception as _pre_exc:  # noqa: BLE001
                # FAIL SAFE, not fail open: if the facts cannot be read we assume the
                # backup is NOT satisfied, so the gate stays on. A gate that disappears
                # when its own query breaks is worse than no gate — it looks green.
                logger.warning("prerequisite state unreadable (%s) — holding the gate", _pre_exc)
                backup_in_flight, recent_backup_ok, pr_merge_open = True, False, None

            unsatisfied = unsatisfied_prerequisites(
                pending_types,
                backup_in_flight=backup_in_flight,
                recent_backup_ok=recent_backup_ok,
                pr_merge_open=pr_merge_open,
            )

            by_source = {}
            for a in approvals:
                by_source[a["source"]] = by_source.get(a["source"], 0) + 1
                # Stamped server-side so the UI does not keep a SECOND copy of the
                # publishing carve-out or the prerequisite graph that could drift.
                a["bulk_all_allowed"] = can_bulk_all(a.get("action_type"))
                a["blocked_reasons"] = blocking_reasons(a.get("action_type"), unsatisfied)
                a["bulk_all_reason"] = bulk_all_reason(a.get("action_type"))
                # Drives the "Back up now" button. A FLAG, not the reason text — the UI
                # must never key off prose (a reword would silently disable the remedy).
                a["backup_actionable"] = backup_is_actionable(
                    a.get("action_type"), unsatisfied, backup_in_flight=backup_in_flight
                )
                # Sub-tab grouping for the Approvals tab. Stamped here for the same
                # reason as the fields above: a second copy of the taxonomy in JS would
                # drift from the one the backend enforces.
                a["category"] = category_of(a.get("action_type"))

            # Prerequisites first: the queue is presented in the order it is SAFE to clear,
            # so "work top-down" is correct behaviour rather than something to remember.
            approvals.sort(
                key=lambda a: (
                    category_priority(a.get("action_type")),
                    (a.get("action_type") or ""),
                    str(a.get("id") or ""),
                )
            )
            return jsonify(
                {
                    "success": True,
                    "approvals": approvals,
                    "count": len(approvals),
                    "by_source": by_source,
                    # The UI disables its bulk buttons past this rather than letting the
                    # server reject a batch the operator already thought was submitted.
                    "max_bulk": MAX_BULK,
                }
            )
        except Exception as exc:
            logger.error("approvals_pending error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # Keep hiring routes in their original registration order and guard them
    # with the same decorator supplied to this public entry point.
    from .approvals_hire_routes import register_hire_approval_routes

    register_hire_approval_routes(bp, admin_required_decorator)

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

    @bp.route("/api/approvals/bulk", methods=["POST"])
    @admin_required_decorator
    def approvals_bulk():
        """Approve or deny several approvals in one request.

        Body: {"action": "approve"|"deny", "ids": ["autonomy:123", "bridge:9", ...]}

        Reuses the SAME per-source helpers as the single-item routes, so bulk introduces
        no second execution path that could drift from it.

        Returns PER-ITEM results, never a bare "done". Partial failure is the normal case:
        an item already actioned from Telegram in the meantime simply is not pending any
        more, and reporting that as success would tell the operator work happened that
        did not. The response is 200 with the breakdown even when some items fail — the
        caller renders it.
        """
        from tools.department_hq.services.approvals_bulk import validate_batch

        try:
            data = request.get_json(silent=True) or {}
            parsed, err = validate_batch(data.get("ids"), (data.get("action") or "").strip())
            if err:
                return jsonify({"success": False, "error": err}), 400

            action = data["action"].strip()
            reason = (data.get("reason") or "Bulk denied via Approvals tab").strip()
            approved, failed = [], []
            for approval_id, prefix, source_id in parsed:
                try:
                    if action == "approve":
                        if prefix == "autonomy":
                            ok, action_type = _approve_autonomy(source_id, current_user.id)
                        elif prefix == "contractor":
                            ok, action_type = _approve_contractor(source_id, current_user.id)
                        else:
                            ok, action_type = _approve_bridge(source_id, current_user.id)
                    else:
                        # NOTE the asymmetry: the _deny_* helpers take a REASON and return
                        # a plain bool, while the _approve_* helpers return
                        # (ok, action_type). Unpacking them the same way raises.
                        action_type = None
                        if prefix == "autonomy":
                            ok = _deny_autonomy(source_id, current_user.id, reason)
                        elif prefix == "contractor":
                            ok = _deny_contractor(source_id, current_user.id, reason)
                        else:
                            ok = _deny_bridge(source_id, current_user.id, reason)
                    if ok:
                        approved.append({"id": approval_id, "action_type": action_type})
                    else:
                        failed.append({"id": approval_id, "error": "not found or already processed"})
                except Exception as item_exc:  # noqa: BLE001 — one bad item must not
                    # abort the rest; the operator gets a per-item reason instead.
                    logger.error("bulk %s failed for %s: %s", action, approval_id, item_exc)
                    failed.append({"id": approval_id, "error": str(item_exc)})

            logger.info(
                "Bulk %s by user %s: %s succeeded, %s failed",
                action,
                current_user.id,
                len(approved),
                len(failed),
            )
            return jsonify(
                {
                    "success": True,
                    "action": action,
                    "requested": len(parsed),
                    "succeeded": len(approved),
                    "failed_count": len(failed),
                    "results": approved,
                    "failed": failed,
                }
            )
        except Exception as exc:
            logger.error("approvals_bulk error: %s", exc)
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

    @bp.route("/api/approvals/backup-now", methods=["POST"])
    @admin_required_decorator
    def approvals_backup_now():
        """Take a fresh restore point NOW, so blocked deploys can proceed.

        The Approvals tab shows "no successful backup in the last Nh" as a prerequisite
        on every deploy row. Before this endpoint that message named a blocker with no
        remedy anywhere in the UI — the operator could only wait for the nightly cron.

        Three states, three different honest answers:
          - a backup is ALREADY RUNNING -> say so, change nothing (a second concurrent
            dump would just block on `acquire_backup_lock` and waste a queue slot)
          - a backup approval is PENDING -> approve THAT one. "Back up now" means make it
            happen, not make a duplicate.
          - neither -> create one and approve it.

        ⚠️ This does NOT run the backup in the request. A database dump takes ~14 minutes
        and would hold a gunicorn worker for all of it. It marks the row approved and the
        `archie_scheduler` approval executor picks it up — the SAME path a Telegram tap
        uses, so there is no second implementation to drift.

        An authenticated admin clicking this button IS the approval. That is the same
        principle as `human_override` on merges (decision #953): the gate exists to
        require a human, and a human is the one clicking.
        """
        try:
            from database import get_db_cursor
            from services.backup_autoraise import BACKUP_ACTION

            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT id, status FROM autonomy_approval_queue "
                    "WHERE action_type = %s "
                    "  AND (status = 'pending' "
                    "       OR (status = 'approved' AND executed_at IS NULL)) "
                    "ORDER BY id DESC LIMIT 1",
                    (BACKUP_ACTION,),
                )
                existing = cur.fetchone()

            if existing:
                existing = dict(existing)
                if existing["status"] == "approved":
                    return jsonify(
                        {
                            "success": True,
                            "started": False,
                            "already_running": True,
                            "approval_id": existing["id"],
                            "message": "A backup is already running — waiting for it to finish.",
                        }
                    )
                approval_id = existing["id"]
                created = False
            else:
                from ai_bridge.agent_loop import request_approval

                approval_id = request_approval(
                    action_type=BACKUP_ACTION,
                    action_data={"trigger": "manual_button", "requested_by_user": current_user.id},
                    reason="Manual 'Back up now' from the Approvals tab — taking a fresh restore point.",
                    requested_by=f"user:{current_user.id}",
                    priority=1,
                )
                if not approval_id:
                    # request_approval signals its own dedup by returning None. Racing with
                    # the auto-raise job is the likely cause and is harmless, but claiming
                    # success for a row that does not exist is not.
                    return (
                        jsonify(
                            {
                                "success": False,
                                "started": False,
                                "message": "Could not queue the backup — a request may have just been created. Refresh and try again.",
                            }
                        ),
                        409,
                    )
                created = True

            # ⚠️ `backup_before_deploy` is a TIER-1 action, and `request_approval`
            # auto-approves tier 1 AT CREATION. So a freshly created row is already
            # `approved`, and `_approve_autonomy` (which matches `WHERE status='pending'`)
            # would find nothing and report failure for a backup that is queued and fine.
            # Caught by a live drive: row 12949 was created, approved, and running while
            # this endpoint returned 409 "could not be approved" — a status misreporting a
            # healthy artifact, which is the exact failure this whole feature exists to fix.
            # An operator who believed it would click again and queue a duplicate.
            ok = _already_approved(approval_id)
            if not ok:
                ok, _action = _approve_autonomy(approval_id, current_user.id)
            if not ok:
                return (
                    jsonify(
                        {
                            "success": False,
                            "started": False,
                            "approval_id": approval_id,
                            "message": "The backup request could not be approved (it may have just been actioned elsewhere).",
                        }
                    ),
                    409,
                )

            logger.info(
                "[backup_now] user %s approved backup #%s (%s)",
                current_user.id,
                approval_id,
                "new" if created else "existing pending request",
            )
            return jsonify(
                {
                    "success": True,
                    "started": True,
                    "approval_id": approval_id,
                    "created": created,
                    "message": (
                        "Backup queued and approved. It runs in the scheduler and takes "
                        "roughly 15 minutes — the deploy prerequisites clear once it finishes."
                    ),
                }
            )
        except Exception as e:
            logger.error("[backup_now] failed: %s", e)
            return jsonify({"success": False, "started": False, "message": str(e)}), 500

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
                         -- Approval-flow rows only — without this gate every routine
                         -- dispatch (completed/failed) floods Recent History (#5706)
                         AND (approved_at IS NOT NULL OR cancelled_by IS NOT NULL)
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
