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


def _code_fix_label(action_type, meta):
    """Human-readable label + category for a Code-Health fix approval card,
    from the proposal metadata — turns the raw 'improvement_approve_red'
    action_type into e.g. '🔴 Code fix — WRONG_SUBMODULE_IMPORT in
    security_network/routes.py'. Degrades gracefully when metadata is missing."""
    meta = meta or {}
    code = meta.get("issue_code") or "code issue"
    module = meta.get("module_name") or "?"
    file_path = meta.get("file_path") or ""
    short = file_path.rsplit("/", 1)[-1] if file_path else ""
    loc = f"{module}/{short}" if short else module
    if str(action_type).endswith("_red"):
        return "code_fix_red", f"🔴 Code fix — {code} in {loc}"
    return "code_fix", f"🔧 Code fix — {code} in {loc}"


def _code_fix_reason(meta, proposal_id):
    """Detail line for a code-fix card: SEVERITY · what's wrong · proposal #."""
    meta = meta or {}
    sev = (meta.get("severity_tier") or "").upper()
    detail = meta.get("detail") or meta.get("issue_code") or ""
    parts = [p for p in (sev, detail, f"proposal #{proposal_id}" if proposal_id else "") if p]
    return " · ".join(parts)


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


def _already_approved(source_id: int) -> bool:
    """True when the row is ALREADY past `pending` — i.e. nothing left to approve.

    Tier-1 action types are auto-approved by `request_approval` at creation, so "not
    pending" here means SUCCESS, not failure. Returns False on any error: an uncertain
    read must not let a caller claim an approval it cannot see.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT status FROM autonomy_approval_queue WHERE id = %s",
                (source_id,),
            )
            row = cur.fetchone()
        if not row:
            return False
        status = (row["status"] if isinstance(row, dict) else row[0]) or ""
        return status in ("approved", "executed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[backup_now] could not read approval %s status: %s", source_id, exc)
        return False


def _approve_autonomy(source_id: int, user_id: int):
    """Approve an autonomy_approval_queue row. Returns (ok, action_type).

    For welfare_rest_8h: also opens the 8h rest cycle on the agent
    so approving from DHQ web UI has the same effect as tapping
    the Telegram action button.
    """
    import json as _json

    from database import get_db_cursor

    tg_msg_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
               SET status = 'approved', approved_by = %s,
                   approved_at = NOW(), updated_at = NOW()
               WHERE id = %s AND status = 'pending'
               RETURNING action_type, action_data, telegram_message_id""",
            (user_id, source_id),
        )
        row = cur.fetchone()
        if not row:
            return (False, None)

        action_type = row["action_type"] if isinstance(row, dict) else row[0]
        action_data = row["action_data"] if isinstance(row, dict) else row[1]
        tg_msg_id = row["telegram_message_id"] if isinstance(row, dict) else row[2]

        # welfare_rest_8h: enforce the rest cycle on approval (mirror of Telegram callback)
        if action_type == "welfare_rest_8h":
            try:
                _ad = action_data if isinstance(action_data, dict) else _json.loads(action_data or "{}")
                _agent_id = _ad.get("agent_id")
                if _agent_id:
                    # Open 8h rest cycle
                    cur.execute(
                        """
                        INSERT INTO agent_rest_cycles
                            (agent_id, rest_type, reason, started_at, ended_at, initiated_by)
                        SELECT %s, 'approved_rest',
                               'Kytran approved 8h rest via DHQ Approvals tab',
                               NOW(), NOW() + INTERVAL '8 hours', 'dhq_approval'
                        WHERE NOT EXISTS (
                            -- Block on ANY active rest cycle (open-ended OR future-ended).
                            -- The old 'started_at > NOW()-30min' clause let a long (8h)
                            -- rest started >30min ago slip past, so a second cycle stacked
                            -- on top and the agent was benched far longer than intended.
                            SELECT 1 FROM agent_rest_cycles
                            WHERE agent_id = %s
                              AND (ended_at IS NULL OR ended_at > NOW())
                        )
                        """,
                        (_agent_id, _agent_id),
                    )
                    # Transition to winding_down via the single-writer (agent_service) —
                    # raw agents-table SQL is blocked by the K.I.N. guardrail. Mirrors the
                    # COO path (agent_jobs.py). Idempotent if already resting.
                    try:
                        from services.agent_service import transition_shift_state as _ts

                        _ts(_agent_id, "winding_down", "DHQ-approved 8h rest")
                    except Exception as _ts_err:
                        logger.warning("welfare_rest_8h shift transition failed: %s", _ts_err)
                    cur.execute(
                        """UPDATE agent_budgets
                              SET current_task_count=0, last_task_reset_at=NOW(),
                                  task_reset_reason='DHQ-approved 8h rest',
                                  task_reset_by='dhq_approval', updated_at=NOW()
                            WHERE agent_id=%s""",
                        (_agent_id,),
                    )
            except Exception as _we:
                logger.warning("welfare_rest_8h DHQ approval execution failed: %s", _we)

    # Mail HQ Smart Inbox (Slice 4): send the drafted reply on approval. Runs OUTSIDE the
    # DB transaction above (never hold a txn open across an SMTP/network call). The
    # executor is idempotent, so the Telegram tap and this web path can't double-send.
    if action_type == "email_reply":
        try:
            from tools.email_manager.draft_proposal_service import execute_email_reply

            execute_email_reply(source_id, user_id)
        except Exception as _ee:
            logger.warning("email_reply DHQ approval execution failed: %s", _ee)

    # #4325: echo the dashboard decision onto Telegram (update text + drop buttons) so
    # the phone message reflects the action taken here. Best-effort — a Telegram failure
    # must never break the approve. The inbound callback does the same edit on a tap.
    if tg_msg_id:
        try:
            from services.telegram_service import edit_message

            edit_message(int(tg_msg_id), "✅ Approved via dashboard", clear_buttons=True)
        except Exception as _te:
            logger.warning("telegram echo (approve) failed: %s", _te)
    return (True, action_type)


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

    tg_msg_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        # Fetch action details before update for denial learning
        cur.execute(
            "SELECT action_type, action_data, telegram_message_id FROM autonomy_approval_queue WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()
        if row:
            tg_msg_id = row["telegram_message_id"] if isinstance(row, dict) else row[2]

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

    # #4325: echo the denial onto Telegram (update text + drop buttons). Best-effort.
    if denied and tg_msg_id:
        try:
            from services.telegram_service import edit_message

            edit_message(int(tg_msg_id), "❌ Denied via dashboard", clear_buttons=True)
        except Exception as _te:
            logger.warning("telegram echo (deny) failed: %s", _te)

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


def parse_approval_id(approval_id):
    """('autonomy:123') -> ('autonomy', 123). Mirrors the split the session
    approve/deny routes already do (partition on ':')."""
    source, _, sid = str(approval_id).partition(":")
    return source, int(sid)


def list_pending_approvals():
    """Unified pending Tier-2 approvals (autonomy + contractor + bridge + hire)
    as a plain list of dicts — no Flask/session. Shared by the @admin_required
    /api/approvals/pending route AND the @_require_internal_key cockpit endpoint.
    Row shaping (incl. the PR #2205 code-fix labels + escalation chain) is
    identical to what the DHQ Approvals tab renders."""
    from database import get_db_cursor

    approvals: list = []

    with get_db_cursor() as (conn, cur):
        # Prefetch Code-Health proposal metadata for rich code-fix labels
        # (one query, keyed by proposal_id) so every improvement_approve*
        # card shows real module/issue/file instead of the raw action_type.
        _prop_meta = {}
        try:
            cur.execute(
                """SELECT id, metadata FROM improvement_proposals
                   WHERE id IN (
                       SELECT (action_data->>'proposal_id')::int
                       FROM autonomy_approval_queue
                       WHERE status = 'pending' AND tier >= 2
                         AND action_type IN ('improvement_approve', 'improvement_approve_red')
                         AND action_data->>'proposal_id' ~ '^[0-9]+$')"""
            )
            import json as _json

            for _pr in cur.fetchall():
                _pr = dict(_pr)
                _md = _pr["metadata"] if isinstance(_pr["metadata"], dict) else _json.loads(_pr["metadata"] or "{}")
                _prop_meta[_pr["id"]] = _md
        except Exception:
            logger.warning("approvals: code-fix metadata prefetch failed", exc_info=True)

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
            elif at == "linkedin_post":
                _ad = r.get("action_data") or {}
                _pt = _ad.get("post_type", "personal") if isinstance(_ad, dict) else "personal"
                _acct_label = {"company": "KE Inc.", "creed": "Creed-AI", "personal": "Kytran"}.get(_pt, _pt.title())
                category, display = "linkedin_post", f"LinkedIn Post — {_acct_label}"
            elif at == "linkedin_like":
                _ad = r.get("action_data") or {}
                _rx = _ad.get("reaction", "like") if isinstance(_ad, dict) else "like"
                category, display = "linkedin_like", f"LinkedIn {str(_rx).title()}"
            elif at == "linkedin_comment":
                category, display = "linkedin_comment", "LinkedIn Comment"
            elif at == "pr_merge":
                # Tier-3 / sensitive-path PR awaiting Kytran's merge (#5283).
                # Without this it rendered as category 'other' with the raw
                # action_type as its label — present in the tab, but not
                # recognisable as the merge decision it is.
                _ad = r.get("action_data") or {}
                _pr = _ad.get("pr_number") if isinstance(_ad, dict) else None
                _ptitle = (_ad.get("title") or "") if isinstance(_ad, dict) else ""
                category, display = "pr_merge", f"🔀 Merge PR #{_pr} — {_ptitle[:60]}"
            elif at == "contractor_dispatch":
                category, display = "contractor_dispatch", "Contractor Dispatch"
            elif at == "restart_container":
                category, display = "restart_container", "Container Restart"
            elif at == "welfare_rest_8h":
                # K.I.N. welfare approval — agent overwork >12h
                _ad = r.get("action_data") or {}
                _aname = _ad.get("agent_name", "Agent") if isinstance(_ad, dict) else "Agent"
                _hrs = _ad.get("hours", "12+") if isinstance(_ad, dict) else "12+"
                category, display = "welfare", f"😴 {_aname} — {_hrs}h overwork (8h rest?)"
            elif at == "email_reply":
                _ad = r.get("action_data") or {}
                _to = (_ad.get("to_address") or "?") if isinstance(_ad, dict) else "?"
                _subj = (_ad.get("subject") or "") if isinstance(_ad, dict) else ""
                category, display = "email_reply", f"✉️ Reply to {_to} — {_subj[:50]}"
            elif at in ("improvement_approve", "improvement_approve_red"):
                _ad = r.get("action_data") or {}
                try:
                    _pid = (
                        int(_ad.get("proposal_id"))
                        if isinstance(_ad, dict) and _ad.get("proposal_id") is not None
                        else None
                    )
                except (TypeError, ValueError):
                    _pid = None
                _md = _prop_meta.get(_pid, {})
                category, display = _code_fix_label(at, _md)
                # override the reason with the concrete finding detail
                r["reason"] = _code_fix_reason(_md, _pid) or r.get("reason")
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
                    "contractor": f"{r.get('contractor_provider') or ''}/{r.get('contractor_model') or ''}".strip("/"),
                    "estimated_cost": (float(r["estimated_cost"]) if r.get("estimated_cost") is not None else None),
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
                   a.display_name AS proposer_name,
                   -- #5829: age ONLY. Pure arithmetic on a column already selected —
                   -- no join, no scan.
                   --
                   -- ⚠️ An earlier revision of this query ALSO computed demand_30d and
                   -- active_holders here, as correlated subqueries over
                   -- task_execution_log. That table holds 1,238,358 rows and is
                   -- deliberately never pruned (it is the token ledger, #4550), and the
                   -- lower(replace(...)) on both sides defeated every index — so it ran
                   -- ONE FULL SCAN PER HIRING ROW. Measured live: this endpoint went
                   -- from ~70ms to 57-84s and the tab died with "Unexpected end of JSON
                   -- input" as the worker timed out mid-response. Even the corrected
                   -- single-aggregate form costs 778ms, which is still wrong for an
                   -- endpoint the UI polls.
                   --
                   -- Demand belongs where it already lives: the SCHEDULED gate in
                   -- welfare_governance_service.recommend_sole_agent_staffing_gaps(),
                   -- which stops a no-demand proposal from ever being created. A UI
                   -- poll must not re-derive it.
                   EXTRACT(EPOCH FROM (NOW() - hc.proposed_at)) / 86400.0 AS age_days_sql
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
                        # #5829: a proposal nobody drains should show its own age.
                        # 15 sat pending, oldest 08-17, none ever actioned.
                        "age_days": (round(float(r["age_days_sql"]), 1) if r.get("age_days_sql") is not None else None),
                        "stale": bool(r.get("age_days_sql") is not None and float(r["age_days_sql"]) >= 7.0),
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
    return approvals


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
        new_agent = body.get("new_agent")
        notes = body.get("notes", "") or ""
        # Reactivation needs an existing-agent pick; a net-new hire needs a spec.
        if new_agent is None and not isinstance(chosen_agent_id, int):
            return jsonify({"ok": False, "reason": "chosen_agent_id or new_agent required"}), 400

        result = hiring_service.approve_candidate(
            hire_id=hire_id,
            chosen_agent_id=chosen_agent_id if isinstance(chosen_agent_id, int) else None,
            decided_by_user_id=current_user.id,
            notes=notes,
            new_agent=new_agent if isinstance(new_agent, dict) else None,
        )

        if result.get("ok"):
            return jsonify(result), 200
        status_map = {
            "not_found": 404,
            "already_decided": 409,
            "candidate_not_in_shortlist": 400,
            "not_a_new_hire_candidate": 400,
            "name_required": 400,
            "model_required": 400,
            "name_exists": 409,
            "create_rejected": 400,
            "create_failed": 500,
            "model_missing": 409,
            "ollama_unreachable": 409,
            "transition_failed": 500,
            "race_lost": 409,
        }
        status = status_map.get(result.get("reason", ""), 400)
        return jsonify(result), status

    @bp.route("/api/approvals/hire/<int:hire_id>/suggest-name", methods=["POST"])
    @admin_required_decorator
    def suggest_hire_name(hire_id: int):
        """Generate a unique, job-fit acronym name for a net-new hire.

        The server reads the candidate's capability itself (nothing
        client-supplied to trust). Fail-soft: any error returns HTTP 200
        {ok: false} so the UI can fall back to manual typing — this never
        blocks approval.
        """
        from database import get_db_cursor
        from services import agent_identity_builder

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT capability FROM hiring_candidates WHERE id = %s", (hire_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "error": "hire_not_found"}), 404
            capability = row["capability"] if isinstance(row, dict) else row[0]
            result = agent_identity_builder.build_identity(capability)
            return jsonify({"ok": True, **result}), 200
        except Exception as exc:
            logger.warning("suggest_hire_name(%s) failed: %s", hire_id, exc)
            return jsonify({"ok": False, "error": "generation_failed"}), 200

    @bp.route("/api/approvals/hire/<int:hire_id>/generate-name", methods=["POST"])
    @admin_required_decorator
    def generate_hire_name_async(hire_id: int):
        """Kick off async name generation and return a job_id immediately.

        The sync suggest-name endpoint above can spin 6-23s (up to ~60s) holding a
        gunicorn worker; this returns instantly and the frontend polls
        ``generate-name/<job_id>``. Fail-soft: any error → 200 {ok:false} so the UI
        can fall back to the sync path / manual typing (#4969).
        """
        from database import get_db_cursor
        from services import hire_name_job_service

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT capability FROM hiring_candidates WHERE id = %s", (hire_id,))
                row = cur.fetchone()
            if not row:
                return jsonify({"ok": False, "error": "hire_not_found"}), 404
            capability = row["capability"] if isinstance(row, dict) else row[0]
            job_id = hire_name_job_service.create_job(hire_id, capability)
            return jsonify({"ok": True, "job_id": job_id, "status": "generating"}), 200
        except Exception as exc:
            logger.warning("generate_hire_name_async(%s) failed: %s", hire_id, exc)
            return jsonify({"ok": False, "error": "generation_failed"}), 200

    @bp.route("/api/approvals/hire/<int:hire_id>/generate-name/<job_id>", methods=["GET"])
    @admin_required_decorator
    def poll_hire_name_async(hire_id: int, job_id: str):
        """Poll an async name job. Returns {ok, status, ...identity}; status is
        generating|done|error. On ``done`` the identity fields are flattened into
        the response (name/expansion/title/bio/... — the SAME shape the sync
        suggest-name endpoint returns) so the frontend renders identically (#4969).
        """
        from services import hire_name_job_service

        try:
            job = hire_name_job_service.get_job(job_id)
            if not job:
                return jsonify({"ok": False, "error": "job_not_found"}), 404
            status = job.get("status")
            if status == "done":
                result = job.get("result") or {}
                return jsonify({"ok": True, "status": "done", **result}), 200
            if status == "error":
                return jsonify({"ok": True, "status": "error"}), 200
            return jsonify({"ok": True, "status": "generating"}), 200
        except Exception as exc:
            logger.warning("poll_hire_name_async(%s) failed: %s", job_id, exc)
            return jsonify({"ok": False, "error": "poll_failed"}), 200

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
