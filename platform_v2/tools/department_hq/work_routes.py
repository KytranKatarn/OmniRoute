"""
Department HQ — Work Tracking + Performance + C.R.E.E.D. routes

Endpoints:
  GET /api/work-sessions            — Recent work sessions (filters: department, status, limit)
  GET /api/performance              — Latest department metrics with KPIs
  GET /api/performance/<department> — Detailed metrics + agent breakdown for one department
  GET /api/creed                    — Per-department C.R.E.E.D. scores, governance events, welfare
  POST /api/browser-test            — Run browser test on a single URL
  POST /api/browser-test/all        — Test all critical platform pages
"""

from flask import jsonify, request
from database import get_db_cursor


def register_work_routes(bp, admin_required):
    """Register work tracking, performance, and C.R.E.E.D. routes."""

    # ------------------------------------------------------------------
    # K.I.N. Welfare Overview — resting agents, budget limits, welfare flags
    # ------------------------------------------------------------------
    @bp.route("/api/kin/welfare")
    @admin_required
    def api_kin_welfare():
        """K.I.N. welfare + workload: resting agents, task limits, dispatch velocity, reset tracking."""
        try:
            with get_db_cursor() as (conn, cur):
                # Main agent welfare query
                cur.execute(
                    """
                    SELECT
                        a.id, a.name, a.department, a.shift_state,
                        a.worker_type,
                        ae.stress_level     AS stress,
                        ae.energy_level     AS energy,
                        ae.current_mood     AS mood,
                        ab.current_task_count AS task_count,
                        ab.task_queue_limit   AS task_limit,
                        ab.token_limit_per_day AS token_limit_per_day,
                        ab.last_task_reset_at,
                        ab.task_reset_reason,
                        ab.task_reset_by,
                        rc.rest_type,
                        rc.started_at AS rest_since,
                        rc.ended_at   AS rest_until,
                        ap.canonical_image_path AS avatar_path
                    FROM agents a
                    LEFT JOIN LATERAL (
                        SELECT stress_level, energy_level, current_mood
                        FROM agent_emotional_state
                        WHERE agent_id = a.id
                        ORDER BY timestamp DESC LIMIT 1
                    ) ae ON TRUE
                    LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
                    LEFT JOIN LATERAL (
                        -- An ACTIVE rest cycle is open-ended (ended_at IS NULL) OR still
                        -- inside its window (ended_at > NOW()). The old 'ended_at IS NULL'
                        -- only check made bounded COO/approved 8h rests INVISIBLE here, so a
                        -- resting agent showed no rest card + no recovery timer. Select
                        -- ended_at too so the UI can show an accurate recovery countdown.
                        SELECT rest_type, started_at, ended_at FROM agent_rest_cycles
                        WHERE agent_id = a.id AND (ended_at IS NULL OR ended_at > NOW())
                        ORDER BY started_at DESC LIMIT 1
                    ) rc ON TRUE
                    LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
                    WHERE a.worker_type = 'ai'
                      AND a.shift_state != 'decommissioned'
                    ORDER BY
                        (rc.rest_type IS NOT NULL) DESC,
                        (ab.current_task_count >= ab.task_queue_limit) DESC,
                        ae.stress_level DESC NULLS LAST
                    """
                )
                rows = cur.fetchall() or []

                # Dispatch velocity + dispatches since last budget reset
                cur.execute(
                    """
                    SELECT tel.agent_name,
                           COUNT(*) FILTER (WHERE tel.created_at > NOW() - INTERVAL '1 hour')  AS dispatches_1h,
                           COUNT(*) FILTER (WHERE tel.created_at > NOW() - INTERVAL '24 hours') AS dispatches_24h,
                           COUNT(*) FILTER (WHERE tel.created_at > COALESCE(ab.last_task_reset_at, NOW() - INTERVAL '24 hours'))
                               AS dispatches_since_reset,
                           -- COORD-2 (KB #270619): real token load alongside dispatch count,
                           -- so WELFARE/WORKLOAD shows the same token signal as ARMADA.
                           COALESCE(SUM(tel.tokens_used) FILTER (WHERE tel.created_at > NOW() - INTERVAL '1 hour'), 0)
                               AS tokens_1h,
                           COALESCE(SUM(tel.tokens_used) FILTER (WHERE tel.created_at > NOW() - INTERVAL '24 hours'), 0)
                               AS tokens_24h
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.name = tel.agent_name
                    LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY tel.agent_name
                    """
                )
                velocity_map = {r["agent_name"]: r for r in (cur.fetchall() or [])}

                # Hours worked today = REAL (non-internal) WALL-CLOCK compute time as the
                # interval-UNION of overlapping dispatches, NOT SUM(duration_ms). KB #270628:
                # SUM counted concurrent dispatches N times (V.E.R.I.F.Y. read 89h in a 15h
                # day at ~6x parallelism); the LEAST(sum, elapsed) cap then pegged such
                # agents at full elapsed hours and falsely flagged them overworked. The
                # shared helper also resets the day's window to AFTER the agent's last
                # completed rest (post-rest cooldown). Same source as the scheduler's
                # track_agent_hr overwork check, so this DISPLAY == the ENFORCEMENT.
                # (Orchestrators — model_used='internal', 0-token waits — stay excluded, as
                # in KB #270619.) Thresholds align with enforcement: 12h rest, 8h warning.
                from services.agent_load_service import real_compute_hours_today

                hours_map = {}
                for _hrec in real_compute_hours_today(cur).values():
                    _h = _hrec["hours"]
                    hours_map[_hrec["name"]] = {
                        "hours_worked_today": _h,
                        "overwork_level": ("critical" if _h >= 12.0 else "warning" if _h >= 8.0 else "normal"),
                    }

                # Pending K.I.N. 8h-rest approvals keyed by agent id, so the welfare card
                # can show an Approve/Deny button right where the "rest approval pending"
                # status appears (previously approvable only on the separate Approvals tab
                # or Telegram, which users could not find).
                cur.execute(
                    """
                    SELECT (action_data->>'agent_id')::int AS agent_id, id AS approval_id
                    FROM autonomy_approval_queue
                    WHERE action_type = 'welfare_rest_8h' AND status = 'pending'
                      AND (expires_at IS NULL OR expires_at > NOW())
                      AND action_data->>'agent_id' IS NOT NULL
                    """
                )
                pending_rest_map = {r["agent_id"]: r["approval_id"] for r in (cur.fetchall() or [])}

                # Last reset summary (latest reset across all agents)
                cur.execute(
                    """
                    SELECT ab.last_task_reset_at, ab.task_reset_reason, ab.task_reset_by,
                           ab.task_queue_limit,
                           COUNT(*) OVER () AS agents_total
                    FROM agent_budgets ab
                    WHERE ab.last_task_reset_at IS NOT NULL
                    ORDER BY ab.last_task_reset_at DESC
                    LIMIT 1
                    """
                )
                reset_row = cur.fetchone()

            agents = []
            workload = []
            resting_count = 0
            at_limit_count = 0
            active_count = 0

            for r in rows:
                is_resting = r["rest_type"] is not None
                task_count = r["task_count"] or 0
                task_limit = r["task_limit"] or 1000
                at_limit = task_count >= task_limit

                vel = velocity_map.get(r["name"], {})
                d1h = int(vel.get("dispatches_1h") or 0)
                d24h = int(vel.get("dispatches_24h") or 0)
                d_reset = int(vel.get("dispatches_since_reset") or 0)
                # at_limit: concurrent queue full OR lifetime dispatches since reset hit the limit
                at_limit = at_limit or (d_reset >= task_limit)
                # ETA to limit based on dispatches since last reset (counter that goes up)
                if d1h > 0 and d_reset < task_limit:
                    hours_to_limit = round((task_limit - d_reset) / d1h, 1)
                else:
                    hours_to_limit = None

                if is_resting:
                    resting_count += 1
                elif at_limit:
                    at_limit_count += 1
                else:
                    active_count += 1

                hrs_row = hours_map.get(r["name"], {})
                hours_worked_today = float(hrs_row.get("hours_worked_today") or 0)
                overwork_level = hrs_row.get("overwork_level", "normal")

                agent_data = {
                    "id": r["id"],
                    "name": r["name"],
                    "department": r["department"],
                    "shift_state": r["shift_state"],
                    "resting": is_resting,
                    "rest_type": r["rest_type"],
                    "rest_since": (r["rest_since"].isoformat() + "Z" if r["rest_since"] else None),
                    "rest_until": (r["rest_until"].isoformat() + "Z" if r.get("rest_until") else None),
                    "at_limit": at_limit,
                    "task_count": task_count,
                    "task_limit": task_limit,
                    "stress": float(r["stress"]) if r["stress"] else 0.0,
                    "energy": float(r["energy"]) if r["energy"] else 0.8,
                    "mood": r["mood"],
                    "dispatches_1h": d1h,
                    "dispatches_24h": d24h,
                    "dispatches_since_reset": d_reset,
                    "tokens_1h": int(vel.get("tokens_1h") or 0),
                    "tokens_24h": int(vel.get("tokens_24h") or 0),
                    "token_limit_per_day": int(r["token_limit_per_day"]) if r["token_limit_per_day"] else 150000,
                    "hours_to_limit": hours_to_limit,
                    "hours_worked_today": hours_worked_today,
                    "overwork_level": overwork_level,
                    "rest_approval_id": pending_rest_map.get(r["id"]),
                    "avatar_url": ("/" + r["avatar_path"].lstrip("/") if r.get("avatar_path") else None),
                }

                # Welfare cards: resting, at task limit, high stress, overworked (>8h
                # today), OR has a pending 8h-rest approval (so the Approve/Deny button is
                # always visible where the action is needed, even if the agent has since
                # dropped below the overwork threshold).
                if (
                    is_resting
                    or at_limit
                    or (r["stress"] or 0) > 0.7
                    or overwork_level != "normal"
                    or agent_data["rest_approval_id"]
                ):
                    agents.append(agent_data)

                # Workload table: all agents with any activity or task_count > 0
                if d24h > 0 or task_count > 0:
                    workload.append(agent_data)

            # Sort workload by 24h dispatch volume descending
            workload.sort(key=lambda x: x["dispatches_24h"], reverse=True)

            last_reset = None
            if reset_row:
                last_reset = {
                    "at": reset_row["last_task_reset_at"].isoformat() if reset_row["last_task_reset_at"] else None,
                    "reason": reset_row["task_reset_reason"],
                    "by": reset_row["task_reset_by"],
                    "limit_set": reset_row["task_queue_limit"],
                }

            return jsonify(
                success=True,
                agents=agents,
                workload=workload,
                last_reset=last_reset,
                resting_count=resting_count,
                at_limit_count=at_limit_count,
                active_count=active_count,
                total_ai_agents=resting_count + at_limit_count + active_count,
            )
        except Exception as e:
            return jsonify(success=False, error=str(e)[:200]), 500

    # ------------------------------------------------------------------
    # K.I.N. manual state control — Wake / Rest / Cooldown with C.R.E.E.D.
    # consequences. Forcing an overworked/resting agent back to work is a
    # welfare BREACH → negative governance event scaled by a 3-LAYER load
    # (hours + tokens + dispatches). Putting an overworked agent on break is
    # welfare-positive. The frontend warns + confirms before a breach applies.
    # ------------------------------------------------------------------
    @bp.route("/api/kin/agent/<int:agent_id>/state", methods=["POST"])
    @admin_required
    def api_kin_agent_state(agent_id):
        import json as _json

        body = request.get_json(silent=True) or {}
        action = body.get("action")
        confirm = bool(body.get("confirm"))
        if action not in ("wake", "rest", "cooldown"):
            return jsonify(success=False, error="action must be wake|rest|cooldown"), 400
        try:
            from services.agent_load_service import real_compute_hours_today
            from services.agent_service import transition_shift_state

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("SELECT name FROM agents WHERE id=%s", (agent_id,))
                arow = cur.fetchone()
                if not arow:
                    return jsonify(success=False, error="agent not found"), 404
                aname = arow["name"]

                # --- 3-layer load: hours + tokens + dispatches (worst layer drives severity) ---
                hours = float(
                    (real_compute_hours_today(cur=cur, agent_id=agent_id).get(agent_id, {}) or {}).get("hours", 0) or 0
                )
                cur.execute(
                    "SELECT COALESCE(SUM(tokens_used),0) tok, COUNT(*) disp FROM task_execution_log "
                    "WHERE agent_name=%s AND created_at > NOW() - INTERVAL '24 hours'",
                    (aname,),
                )
                lr = cur.fetchone() or {}
                tokens_24h = int(lr.get("tok") or 0)
                disp_24h = int(lr.get("disp") or 0)
                cur.execute("SELECT token_limit_per_day FROM agent_budgets WHERE agent_id=%s", (agent_id,))
                budget = int((cur.fetchone() or {}).get("token_limit_per_day") or 150000)
                cur.execute(
                    "SELECT 1 FROM agent_rest_cycles WHERE agent_id=%s AND (ended_at IS NULL OR ended_at > NOW()) LIMIT 1",
                    (agent_id,),
                )
                resting = cur.fetchone() is not None

                hour_r, tok_r, disp_r = hours / 12.0, tokens_24h / max(budget, 1), disp_24h / 200.0
                load = max(hour_r, tok_r, disp_r)
                layers = {
                    "hours": {"value": round(hours, 1), "ratio": round(hour_r, 2)},
                    "tokens": {"value": tokens_24h, "ratio": round(tok_r, 2), "budget": budget},
                    "dispatches": {"value": disp_24h, "ratio": round(disp_r, 2)},
                }

                # --- PUT ON BREAK (welfare-positive, always allowed) ---
                if action in ("rest", "cooldown"):
                    target = "cooldown" if action == "cooldown" else "winding_down"
                    cur.execute(
                        """INSERT INTO agent_rest_cycles
                               (agent_id, rest_type, reason, started_at, ended_at, initiated_by)
                           SELECT %s, 'manual_rest', 'Manual 8h rest via K.I.N. welfare tab',
                                  NOW(), NOW()+INTERVAL '8 hours', 'kin_manual'
                           WHERE NOT EXISTS (SELECT 1 FROM agent_rest_cycles
                               WHERE agent_id=%s AND (ended_at IS NULL OR ended_at > NOW()))""",
                        (agent_id, agent_id),
                    )
                    cur.execute(
                        """INSERT INTO governance_audit_log
                               (agent_id, event_category, event_type, action, reason, details, timestamp)
                           VALUES (%s,'creed_compliance','manual_rest_granted','kin_manual',%s,%s::jsonb,NOW())""",
                        (
                            agent_id,
                            f"Manual rest for {aname}" + (f" (overworked {hours:.1f}h)" if hours >= 8 else ""),
                            _json.dumps({"layers": layers, "welfare_positive": True}),
                        ),
                    )
                    transition_shift_state(agent_id, target, "Manual rest via K.I.N. welfare tab")
                    return jsonify(
                        success=True,
                        new_state=target,
                        layers=layers,
                        message=f"{aname} placed on break — recovers in 8h",
                    )

                # --- FORCE TO WORK (wake) — breach check + scaled penalty ---
                is_breach = resting or hours >= 8.0 or tok_r >= 1.0
                if load >= 1.6 or hours >= 20:
                    severity, penalty = "severe", 20
                elif load >= 1.2 or hours >= 16:
                    severity, penalty = "serious", 10
                elif load >= 0.9 or hours >= 12:
                    severity, penalty = "moderate", 5
                else:
                    severity, penalty = "minor", 2
                breach = {
                    "is_breach": is_breach,
                    "severity": severity,
                    "penalty": penalty,
                    "layers": layers,
                    "message": (
                        f"Forcing {aname} back to work breaches C.R.E.E.D. welfare ({severity}: "
                        f"{hours:.1f}h · {tokens_24h:,}/{budget:,} tok · {disp_24h} dispatches) — −{penalty} pts."
                    ),
                }
                if is_breach and not confirm:
                    return jsonify(success=False, needs_confirm=True, breach=breach)

                cur.execute(
                    "UPDATE agent_rest_cycles SET ended_at=NOW(), notes=COALESCE(notes,'')||' [force-woken via K.I.N. welfare tab]' "
                    "WHERE agent_id=%s AND (ended_at IS NULL OR ended_at > NOW())",
                    (agent_id,),
                )
                if is_breach:
                    cur.execute(
                        """INSERT INTO governance_audit_log
                               (agent_id, event_category, event_type, action, reason, details, timestamp)
                           VALUES (%s,'creed_compliance','forced_work_override','kin_manual_force',%s,%s::jsonb,NOW())""",
                        (
                            agent_id,
                            breach["message"],
                            _json.dumps(
                                {
                                    "severity": severity,
                                    "penalty_points": penalty,
                                    "layers": layers,
                                    "welfare_breach": True,
                                }
                            ),
                        ),
                    )
                transition_shift_state(agent_id, "active", "Manual wake via K.I.N. welfare tab")
                return jsonify(success=True, new_state="active", breach=(breach if is_breach else None), applied=True)
        except Exception as e:
            return jsonify(success=False, error=str(e)[:200]), 500

    # ------------------------------------------------------------------
    # Work Sessions
    # ------------------------------------------------------------------
    @bp.route("/api/work-sessions")
    @admin_required
    def api_work_sessions():
        """Agent activity summary from task_execution_log (last 24h).

        Replaces the old dept_work_sessions source which only tracked Repair Bay
        automated fix sessions. Now shows real agent dispatches grouped per agent.
        """
        department = request.args.get("department")
        limit = min(int(request.args.get("limit", 50)), 200)

        try:
            dept_filter = "AND a.department = %s" if department else ""
            params = [department] if department else []

            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    f"""
                    SELECT
                        COALESCE(a.name, tel.agent_name)        AS agent_name,
                        COALESCE(a.display_name, a.name, tel.agent_name) AS agent_display_name,
                        a.department,
                        MAX(ap.canonical_image_path)            AS portrait_path,
                        COUNT(*)                                 AS total_dispatches,
                        COUNT(*) FILTER (WHERE tel.success)     AS jobs_completed,
                        COUNT(*) FILTER (WHERE NOT tel.success) AS jobs_failed,
                        ROUND(AVG(tel.duration_ms)::numeric, 0) AS avg_duration_ms,
                        SUM(tel.tokens_used)                    AS tokens_used,
                        MODE() WITHIN GROUP (ORDER BY tel.capability) AS top_capability,
                        MAX(tel.created_at)                     AS last_active,
                        MIN(tel.created_at)                     AS first_active
                    FROM task_execution_log tel
                    LEFT JOIN LATERAL (
                        -- Direct match (hub agents)
                        SELECT ha.id, ha.name, ha.display_name, ha.department
                        FROM agents ha
                        WHERE ha.name = tel.agent_name AND ha.worker_type = 'ai'
                        UNION ALL
                        -- Fleet agent resolution: fleet-agent-<hub_agent_id> → hub agent
                        SELECT ha.id, ha.name, ha.display_name, ha.department
                        FROM node_agents na
                        JOIN agents ha ON ha.id = na.hub_agent_id AND ha.worker_type = 'ai'
                        WHERE tel.agent_name ~ '^fleet-agent-[0-9]+$'
                          AND na.hub_agent_id::text = substring(tel.agent_name FROM 13)
                        LIMIT 1
                    ) a ON TRUE
                    LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    {dept_filter}
                    GROUP BY COALESCE(a.name, tel.agent_name),
                             COALESCE(a.display_name, a.name, tel.agent_name),
                             a.department
                    ORDER BY total_dispatches DESC
                    LIMIT %s
                    """,
                    params + [limit],
                )
                rows = cur.fetchall()

            sessions = []
            for r in rows:
                success_rate = (
                    round(r["jobs_completed"] / r["total_dispatches"] * 100, 1) if r["total_dispatches"] > 0 else 0.0
                )
                status = "active" if success_rate >= 80 else "degraded" if success_rate >= 50 else "failed"
                sessions.append(
                    {
                        "agent_name": r["agent_name"],
                        "agent_display_name": r["agent_display_name"],
                        "department": r["department"] or "—",
                        "portrait_path": r["portrait_path"] or None,
                        "session_type": "dispatch",
                        "title": f"{r['top_capability']} · {r['total_dispatches']} dispatches/24h",
                        "status": status,
                        "jobs_completed": r["jobs_completed"],
                        "jobs_failed": r["jobs_failed"],
                        "tokens_used": r["tokens_used"] or 0,
                        "avg_duration_ms": float(r["avg_duration_ms"] or 0),
                        "success_rate": success_rate,
                        "started_at": r["first_active"].isoformat() if r["first_active"] else None,
                        "last_active": r["last_active"].isoformat() if r["last_active"] else None,
                    }
                )

            return jsonify({"sessions": sessions, "count": len(sessions)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # Performance — All Departments
    # ------------------------------------------------------------------
    @bp.route("/api/performance")
    @admin_required
    def api_performance():
        """Latest department metrics with KPIs across all departments."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Latest metrics per department (most recent period)
                cur.execute(
                    """
                    SELECT DISTINCT ON (department)
                           id, department, period_start, period_end,
                           jobs_completed, jobs_failed, avg_response_ms,
                           tokens_used, sessions_completed, kpis,
                           creed_score, computed_at
                    FROM department_metrics
                    ORDER BY department, computed_at DESC
                """
                )
                metrics = cur.fetchall()

                # Live counts from task_execution_log (last 7 days). COORD-3 (KB #270619):
                # was bridge_jobs (partial table → ~53% success), which diverged from the
                # ARMADA tab that reads task_execution_log (~100%). Same source now, so the
                # K.I.N. PERFORMANCE numbers match ARMADA, plus real token volume.
                cur.execute(
                    """
                    SELECT a.department,
                           COUNT(*) AS total_jobs,
                           COUNT(*) FILTER (WHERE tel.success) AS completed,
                           COUNT(*) FILTER (WHERE NOT tel.success) AS failed,
                           COALESCE(SUM(tel.tokens_used), 0) AS tokens,
                           AVG(tel.duration_ms) FILTER (WHERE tel.success) AS avg_ms
                    FROM task_execution_log tel
                    JOIN agents a ON a.name = tel.agent_name
                    WHERE tel.created_at >= NOW() - INTERVAL '7 days'
                      AND a.department IS NOT NULL
                    GROUP BY a.department
                """
                )
                live_rows = cur.fetchall()
                live_map = {r["department"]: dict(r) for r in live_rows}

            result = []
            for m in metrics:
                dept = m["department"]
                entry = dict(m)
                # Merge live data
                live = live_map.get(dept, {})
                entry["live_jobs_7d"] = live.get("total_jobs", 0)
                entry["live_completed_7d"] = live.get("completed", 0)
                entry["live_failed_7d"] = live.get("failed", 0)
                entry["live_tokens_7d"] = int(live.get("tokens") or 0)
                entry["live_avg_ms_7d"] = round(live.get("avg_ms") or 0, 1)
                result.append(entry)

            return jsonify({"departments": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # Performance — Single Department Detail
    # ------------------------------------------------------------------
    @bp.route("/api/performance/<department>")
    @admin_required
    def api_performance_detail(department):
        """Detailed metrics + agent breakdown for one department."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Department metrics history (last 10 periods)
                cur.execute(
                    """
                    SELECT id, department, period_start, period_end,
                           jobs_completed, jobs_failed, avg_response_ms,
                           tokens_used, sessions_completed, kpis,
                           creed_score, computed_at
                    FROM department_metrics
                    WHERE department = %s
                    ORDER BY computed_at DESC
                    LIMIT 10
                    """,
                    [department],
                )
                history = cur.fetchall()

                # Agent breakdown for this department (last 7 days)
                cur.execute(
                    """
                    -- COORD-3 (KB #270619): task_execution_log (matches ARMADA), was bridge_jobs.
                    SELECT a.id, a.name, a.display_name, a.shift_state, a.is_department_ai,
                           COUNT(tel.id) AS total_jobs,
                           COUNT(tel.id) FILTER (WHERE tel.success) AS completed,
                           COUNT(tel.id) FILTER (WHERE NOT tel.success) AS failed,
                           COALESCE(SUM(tel.tokens_used), 0) AS tokens,
                           AVG(tel.duration_ms) FILTER (WHERE tel.success) AS avg_ms
                    FROM agents a
                    LEFT JOIN task_execution_log tel ON tel.agent_name = a.name
                        AND tel.created_at >= NOW() - INTERVAL '7 days'
                    WHERE a.department = %s
                    GROUP BY a.id, a.name, a.display_name, a.shift_state, a.is_department_ai
                    ORDER BY a.is_department_ai DESC, total_jobs DESC
                    """,
                    [department],
                )
                agents = cur.fetchall()

            return jsonify(
                {
                    "department": department,
                    "history": [dict(h) for h in history],
                    "agents": [
                        {**dict(a), "avg_ms": round(a["avg_ms"] or 0, 1), "tokens": int(a["tokens"] or 0)}
                        for a in agents
                    ],
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # C.R.E.E.D. — Ethics & Governance
    # ------------------------------------------------------------------
    @bp.route("/api/creed")
    @admin_required
    def api_creed():
        """Per-department C.R.E.E.D. scores, governance events, welfare alerts."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Latest creed_score per department
                cur.execute(
                    """
                    SELECT DISTINCT ON (department)
                           department, creed_score, computed_at
                    FROM department_metrics
                    WHERE creed_score IS NOT NULL
                    ORDER BY department, computed_at DESC
                """
                )
                scores = cur.fetchall()
                score_map = {r["department"]: r for r in scores}

                # Recent governance events (last 7 days)
                cur.execute(
                    """
                    SELECT gal.id, gal.event_type, gal.event_category,
                           gal.action, gal.outcome, gal.agent_id,
                           gal.timestamp,
                           a.name AS agent_name, a.display_name, a.department
                    FROM governance_audit_log gal
                    LEFT JOIN agents a ON a.id = gal.agent_id
                    WHERE gal.timestamp >= NOW() - INTERVAL '7 days'
                    ORDER BY gal.timestamp DESC
                    LIMIT 50
                """
                )
                events = cur.fetchall()

                # Agent welfare — agents with stress indicators
                cur.execute(
                    """
                    SELECT aes.agent_id, aes.stress_level, aes.mood_intensity,
                           a.name, a.display_name, a.department
                    FROM agent_emotional_state aes
                    JOIN agents a ON a.id = aes.agent_id
                    WHERE a.department IS NOT NULL
                    ORDER BY aes.stress_level DESC NULLS LAST
                    LIMIT 20
                """
                )
                welfare = cur.fetchall()

            # Build per-department summary
            departments = {}
            for s in scores:
                dept = s["department"]
                departments[dept] = {
                    "department": dept,
                    "creed_score": float(s["creed_score"]) if s["creed_score"] else None,
                    "computed_at": s["computed_at"].isoformat() + "Z" if s["computed_at"] else None,
                    "events": [],
                    "welfare_alerts": [],
                }

            for ev in events:
                dept = ev.get("department")
                if dept and dept in departments:
                    departments[dept]["events"].append(
                        {
                            "id": ev["id"],
                            "event_type": ev["event_type"],
                            "event_category": ev["event_category"],
                            "action": ev["action"],
                            "outcome": ev["outcome"],
                            "agent_name": ev["agent_name"],
                            "display_name": ev["display_name"],
                            "timestamp": ev["timestamp"].isoformat() + "Z" if ev["timestamp"] else None,
                        }
                    )

            for w in welfare:
                dept = w.get("department")
                if dept and dept in departments:
                    departments[dept]["welfare_alerts"].append(
                        {
                            "agent_id": w["agent_id"],
                            "agent_name": w["name"],
                            "display_name": w["display_name"],
                            "stress_level": float(w["stress_level"]) if w["stress_level"] else 0,
                            "mood_intensity": float(w["mood_intensity"]) if w["mood_intensity"] else 0,
                        }
                    )

            return jsonify(
                {
                    "departments": list(departments.values()),
                    "total_events_7d": len(events),
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # Browser Tests
    # ------------------------------------------------------------------
    @bp.route("/api/browser-test", methods=["POST"])
    @admin_required
    def run_browser_test():
        """Run a browser test on a URL."""
        from services.browser_test_service import test_page

        data = request.get_json(silent=True) or {}
        url = data.get("url", "")
        checks = data.get("checks", [])
        if not url:
            return jsonify({"error": "url is required"}), 400
        result = test_page(url, checks=checks)
        return jsonify(result)

    @bp.route("/api/browser-test/all", methods=["POST"])
    @admin_required
    def run_all_browser_tests():
        """Test all critical platform pages."""
        from services.browser_test_service import test_all_modules

        results = test_all_modules()
        return jsonify(results)
