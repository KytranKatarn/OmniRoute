"""Shared approval executors and labels; re-exported by approvals_routes."""

import logging

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

    # host_root_command: run the allowlisted host-root command the owner just
    # approved. Out of transaction, like email_reply above. The executor
    # re-validates the spec and fails closed on expiry, so an approval that sat
    # too long, or a row edited in the DB, cannot execute.
    if action_type == "host_root_command":
        try:
            from services.host_command_service import execute_host_command

            execute_host_command(source_id, user_id)
        except Exception as _hc_err:
            logger.warning("host_root_command DHQ approval execution failed: %s", _hc_err)

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
                title="LinkedIn Draft Denied — Style Guide Entry",
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
    approve/deny routes already do (partition on ':').

    Raises ValueError with an ACTIONABLE message on anything malformed. It used to
    raise the bare ``invalid literal for int() with base 10: ''`` instead, because
    ``'15231'.partition(':')`` yields ``('15231', '', '')`` — an unprefixed id put an
    empty string into int(). That surfaced as a 500 ``{"error_type":"ValueError"}``
    on the internal approve/deny routes (#6666, observed 2026-09-09 from archie_comms).

    ⚠️ A bare numeric id is NOT defaulted to 'autonomy'. Each source keeps its own id
    sequence — autonomy_approval_queue.id, contractor_approval_requests.id and
    bridge_jobs.id can all be 5 — so guessing the source on an APPROVE route risks
    approving a different pending item than the caller meant. Callers already have the
    prefixed form: list_pending_approvals() returns source-prefixed ids.
    """
    raw = str(approval_id)
    source, sep, sid = raw.partition(":")
    if not sep or not source or not sid.strip().isdigit():
        raise ValueError(
            f"malformed approval id {raw!r} — expected '<source>:<int>' "
            f"(e.g. 'autonomy:123'); sources: autonomy, contractor, bridge"
        )
    return source, int(sid)
