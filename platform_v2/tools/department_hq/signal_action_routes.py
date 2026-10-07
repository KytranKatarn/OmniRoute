"""Department HQ social routes: signal action routes."""

from flask import jsonify, request
from flask_login import current_user


def register_signal_action_routes(bp, admin_required):
    @bp.route("/api/signal/calendar/backfill", methods=["POST"])
    @admin_required
    def api_signal_calendar_backfill():
        """One-shot: dedup the failed/staged backlog onto per-account
        calendars, 1/day forward. Idempotent; nothing publishes."""
        import logging as _logging

        from services import signal_calendar_service

        try:
            return jsonify({"success": True, **signal_calendar_service.backfill_calendar()})
        except Exception as e:
            _logging.getLogger("platform.signal_calendar").exception("backfill failed")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/calendar/scheduled")
    @admin_required
    def api_signal_calendar_scheduled():
        """Scheduled queue for ?account= (personal|terry|company|creed)."""
        from services import signal_calendar_service

        account = (request.args.get("account") or "personal").strip().lower()
        try:
            return jsonify(
                {
                    "account": account,
                    "posts": signal_calendar_service.get_scheduled(account),
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/calendar/scheduled/<int:post_id>/cancel", methods=["POST"])
    @admin_required
    def api_signal_calendar_cancel(post_id):
        """Cancel one scheduled entry (prune stale backlog content)."""
        from services import signal_calendar_service

        ok = signal_calendar_service.cancel_scheduled(post_id)
        return jsonify({"success": ok}), (200 if ok else 404)

    @bp.route("/api/social/linkedin/comments/draft-replies", methods=["POST"])
    @admin_required
    def api_linkedin_comments_draft_replies():
        """Manually run the reply drafter (#3992) — same path as the 6h job.
        Drafts go to the Tier-2 Telegram approval queue; nothing posts."""
        from services import linkedin_comment_monitor as mon

        try:
            return jsonify({"success": True, **mon.draft_comment_replies()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/calendar/top-up", methods=["POST"])
    @admin_required
    def api_signal_calendar_topup():
        """Manually run the generation top-up (thin backlogs → fresh drafts
        onto the calendar). Same path as the 10:00 ET job."""
        from services import signal_calendar_service

        try:
            return jsonify({"success": True, **signal_calendar_service.top_up_calendars()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/calendar/release-now", methods=["POST"])
    @admin_required
    def api_signal_calendar_release_now():
        """Manually run the daily release (due posts → approval queue).
        Same path as the 09:05 ET job; still Telegram-gated downstream."""
        from services import signal_calendar_service

        try:
            return jsonify({"success": True, **signal_calendar_service.release_due_posts()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/compose", methods=["POST"])
    @admin_required
    def api_signal_compose():
        """UI → S.I.G.N.A.L. announce proxy (avoids exposing API key to browser)."""
        import json as _json
        import os
        import urllib.error
        import urllib.request

        data = request.get_json(silent=True) or {}
        payload = _json.dumps(
            {
                "announcement": (data.get("announcement") or "").strip(),
                "tone": data.get("tone", "professional"),
                "post_type": data.get("post_type", "both"),
                "hashtags": data.get("hashtags", []),
                "priority": int(data.get("priority", 6)),
            }
        ).encode()
        api_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
        req = urllib.request.Request(
            "http://localhost:3000/api/signal/announce",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return jsonify(_json.loads(r.read())), r.status
        except urllib.error.HTTPError as e:
            return jsonify({"error": e.read().decode()}), e.code
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @bp.route("/api/signal/run-now", methods=["POST"])
    @admin_required
    def api_signal_run_now():
        """Trigger signal_linkedin_draft job for a specific account (or all).

        Body: {"account": "personal"|"company"|"all"}  (default: "all")
        """
        import threading

        data = request.get_json(silent=True) or {}
        account = data.get("account", "all").strip().lower()
        try:
            from services.agent_jobs import signal_linkedin_draft

            def _run():
                signal_linkedin_draft(account_filter=account)

            threading.Thread(target=_run, daemon=True).start()
            return jsonify(
                {
                    "success": True,
                    "message": f"signal_linkedin_draft triggered for: {account}",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/pending/<int:approval_id>/approve", methods=["POST"])
    @admin_required
    def api_signal_approve(approval_id):
        """Approve a pending LinkedIn post draft."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                       WHERE id = %s AND action_type = 'linkedin_post' AND status = 'pending'
                       RETURNING id""",
                    (current_user.id, approval_id),
                )
                row = cur.fetchone()
            if not row:
                return (
                    jsonify({"success": False, "error": "Not found or already processed"}),
                    404,
                )
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/pending/<int:approval_id>/deny", methods=["POST"])
    @admin_required
    def api_signal_deny(approval_id):
        """Deny a pending LinkedIn post draft.

        If a reason is provided, S.I.G.N.A.L. immediately revises
        the draft and re-queues it for approval (same as Suggest).
        """
        import threading
        from database import get_db_cursor

        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        reject_reason = reason or "Denied via web UI"
        try:
            # Load original draft before marking rejected
            original_draft = ""
            action_data = {}
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """SELECT action_data FROM autonomy_approval_queue
                       WHERE id = %s AND action_type = 'linkedin_post' AND status = 'pending'""",
                    (approval_id,),
                )
                row = cur.fetchone()
                if not row:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Not found or already processed",
                            }
                        ),
                        404,
                    )
                import json as _json

                action_data = (
                    row["action_data"] if isinstance(row["action_data"], dict) else _json.loads(row["action_data"])
                )
                original_draft = action_data.get("content", "")
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'rejected', approved_by = %s,
                           rejected_reason = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (current_user.id, reject_reason, approval_id),
                )

            # If reason given, kick S.I.G.N.A.L. to revise in background
            revising = bool(reason and original_draft)
            if revising:
                _od, _ad, _r = original_draft, action_data, reason

                def _revise():
                    try:
                        from signal_dispatch import redraft_with_suggestion

                        redraft_with_suggestion(_od, _r, _ad)
                    except Exception as _e:
                        import logging

                        logging.getLogger("platform.signal_dispatch").warning("Auto-revise after deny failed: %s", _e)

                threading.Thread(target=_revise, daemon=True).start()

            return jsonify(
                {
                    "success": True,
                    "approval_id": approval_id,
                    "revising": revising,
                    "message": ("Denied — S.I.G.N.A.L. is revising based on your feedback." if revising else "Denied."),
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── SIGNAL Phase 4 — Retry / Abandon ────────────────────────

    @bp.route("/api/signal/posts/<int:approval_id>/retry", methods=["POST"])
    @admin_required
    def api_signal_retry(approval_id):
        """Retry a failed LinkedIn post: reset status='approved' so the
        autonomy worker re-picks it up and re-fires the skill.

        Defense-in-depth: WHERE clause enforces failure-state check on execution_result
        to prevent re-posting of already-successful posts."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'approved',
                           execution_result = NULL,
                           executed_at = NULL,
                           updated_at = NOW()
                       WHERE id = %s
                         AND action_type = 'linkedin_post'
                         AND status = 'executed'
                         AND (
                                (execution_result->>'success')::text = 'false'
                             OR (execution_result->'result'->>'success')::text = 'false'
                             OR (execution_result->>'_status') IN ('failed', 'timeout')
                             OR (execution_result->'result'->>'_status') IN ('failed', 'timeout')
                         )
                       RETURNING id""",
                    (approval_id,),
                )
                row = cur.fetchone()
            if not row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Not found or not in a failed state",
                        }
                    ),
                    404,
                )
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/posts/<int:approval_id>/abandon", methods=["POST"])
    @admin_required
    def api_signal_abandon(approval_id):
        """Abandon (Mark Won't Fix) a post: terminal state='abandoned'.
        No worker action — chip displays as 'rejected' grey via classifier mapping."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'abandoned',
                           updated_at = NOW()
                       WHERE id = %s
                         AND action_type = 'linkedin_post'
                         AND status NOT IN ('abandoned', 'rejected', 'pending')
                       RETURNING id""",
                    (approval_id,),
                )
                row = cur.fetchone()
            if not row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Not found or not in an abandonable state",
                        }
                    ),
                    404,
                )
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── SIGNAL Calendar Live ──────────────────────────────────────

    @bp.route("/api/signal/calendar/live", methods=["GET"])
    @admin_required
    def api_signal_calendar_live():
        """Return the 7-day living-dashboard view for one account.

        Query params:
            account: any registered S.I.G.N.A.L. account_key (required) — data-driven from
            the registry so terry / archie / supporting accounts all work (was hardcoded to
            personal/company/creed, which 400'd terry).
        """
        import logging

        from services import signal_accounts, signal_calendar_live_service

        _logger = logging.getLogger("platform.signal_calendar_live")

        account = (request.args.get("account") or "").strip().lower()
        _valid = set(signal_accounts.account_keys())
        if account not in _valid:
            return (
                jsonify({"error": "account must be one of: " + ", ".join(sorted(_valid))}),
                400,
            )

        try:
            view = signal_calendar_live_service.get_week_view(account=account)
        except Exception:
            _logger.exception("[signal-calendar-live] failed to build view")
            return jsonify({"error": "failed to build calendar view"}), 500

        return jsonify(view), 200
