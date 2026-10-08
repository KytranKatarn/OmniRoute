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

__all__ = ["jsonify", "request", "get_db_cursor", "register_work_routes"]

# #5703 'Real inference only' — the SAME exclusion the A.R.M.A.D.A. Dispatch tab
# applies by default (dispatch_routes.py feed filter) and that
# carbon_footprint_service._is_llm_model encodes as the SSOT: orchestration
# MARKERS (worker_type IS NULL, model_used='bridge-managed', 0 tokens,
# duration = cycle wall-clock), internal 0-token actions (S.C.O.U.T./M.A.V.E.N.
# model_used='internal'), scrape (browser), image gen (comfyui), and embedding
# (batch / *embed*) rows. Live "jobs" counts on the Performance tab must never
# include these — Executive Office showed 6,296 jobs of which 6,256 were markers.
# NOTE: '%%' is safe both with params (psycopg2 unescapes to '%') and without
# (SQL LIKE treats consecutive wildcards the same as one).
_REAL_INFERENCE_SQL = (
    "{t}.worker_type IS NOT NULL "
    "AND lower(COALESCE({t}.model_used, '')) NOT IN "
    "('bridge-managed', 'internal', 'batch', 'browser', 'comfyui', '') "
    "AND lower(COALESCE({t}.model_used, '')) NOT LIKE '%%embed%%'"
)


def register_work_routes(bp, admin_required):
    """Work welfare entry point; detail routes are registered below without changing their guards."""

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
                        -- #5157(2): the welfare loop only advances ACTIVE agents, so a
                        -- benched agent's emotional state stops updating and the card
                        -- keeps showing its bench-time snapshot. Without the timestamp
                        -- the UI cannot tell a live reading from a frozen one.
                        ae.timestamp        AS stats_updated_at,
                        -- Age computed HERE, not in Python: agent_emotional_state.timestamp
                        -- and agent_learning_records.learned_at are 'timestamp WITHOUT time
                        -- zone' (they deviate from the platform's TIMESTAMPTZ convention),
                        -- so `now_utc() - value` raises
                        -- "can't subtract offset-naive and offset-aware datetimes" and 500s
                        -- the whole tab. Postgres compares them in the session's UTC frame
                        -- without that split. Do NOT move this back into Python.
                        EXTRACT(EPOCH FROM (NOW() - ae.timestamp)) / 3600.0 AS stats_age_hours_sql,
                        -- #5157(3): a failure-benched agent (kin_failure_standby wrote an
                        -- Academy record) is a DIFFERENT situation from one that merely
                        -- stranded in 'barracked'. The operator needs to tell them apart:
                        -- one is under verification, the other is an accident.
                        lb.learned_at       AS benched_at,
                        EXTRACT(EPOCH FROM (NOW() - lb.learned_at)) / 3600.0 AS bench_age_hours_sql,
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
                        -- `timestamp` must be SELECTed, not merely ORDERed BY: the outer
                        -- query reads ae.timestamp for stat-freshness (#5157) and a
                        -- LATERAL only exposes its select list. Omitting it raises
                        -- "column ae.timestamp does not exist" and 500s the whole tab.
                        SELECT stress_level, energy_level, current_mood, timestamp
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
                    LEFT JOIN LATERAL (
                        -- Most recent failure-standby Academy record (kin_failure_standby).
                        -- Present => benched for reliability; absent on a 'barracked' agent
                        -- => it stranded there some other way (#5155).
                        SELECT learned_at FROM agent_learning_records
                        WHERE agent_id = a.id AND learning_type = 'failure_standby'
                        ORDER BY learned_at DESC LIMIT 1
                    ) lb ON TRUE
                    LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
                    WHERE (a.worker_type = 'ai'
                           -- K.I.N. manages any agent with a budget row: external
                           -- contract workers (Codex) get load governance too.
                           OR (a.worker_type = 'contractor' AND ab.agent_id IS NOT NULL))
                      AND a.shift_state != 'decommissioned'
                    ORDER BY
                        -- #5157(3): a benched agent has NO active rest cycle, so under the
                        -- old ordering it sorted BELOW every resting agent and blended into
                        -- the tail of the list. Benched means "off the floor and not coming
                        -- back on its own" — it outranks every other welfare condition.
                        (a.shift_state = 'barracked') DESC,
                        (rc.rest_type IS NOT NULL) DESC,
                        (ab.current_task_count >= ab.task_queue_limit) DESC,
                        ae.stress_level DESC NULLS LAST
                    """
                )
                rows = cur.fetchall() or []

                # Dispatch velocity + dispatches since last budget reset
                from services.welfare_load import welfare_token_filter_sql

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
                    """
                    # #5319: warmups never bill a welfare ledger — excluding them here
                    # keeps this tab equal to governance (KB #272470). Deliberately also
                    # removes warmups from the dispatch COUNTS: keep-warm pings are not
                    # work, and 663/day of them drowned K.I.N.'s real activity signal.
                    + welfare_token_filter_sql("tel")
                    + """
                    GROUP BY tel.agent_name
                    """
                )
                # Key by ROSTER name: external CLI workers log telemetry as
                # '<Name> (CLI)' (Token Economy convention) but the agents row
                # is plain '<Name>' — strip the suffix so Codex's load joins up.
                velocity_map = {r["agent_name"].removesuffix(" (CLI)"): r for r in (cur.fetchall() or [])}

                # Task #3798: layered 24h recovery — hourly token/dispatch buckets per
                # agent so the UI can show old work AGING OUT of the rolling window
                # (recovery made visible, not just a number that shrinks).
                cur.execute(
                    """
                    SELECT tel.agent_name,
                           date_trunc('hour', tel.created_at) AS bucket,
                           COUNT(*) AS dispatches,
                           COALESCE(SUM(tel.tokens_used), 0) AS tokens
                    FROM task_execution_log tel
                    WHERE tel.created_at > NOW() - INTERVAL '24 hours'
                    """
                    # #5319: the aging-out chart must agree with the velocity headline
                    # above — both exclude infrastructure warm-ups.
                    + welfare_token_filter_sql("tel")
                    + """
                    GROUP BY tel.agent_name, bucket
                    """
                )
                # Bucket keys MUST be normalized to UTC: the DB session runs in
                # America/Toronto, so psycopg2 returns tz-aware timestamps at -04:00,
                # while the slot grid below is built from now_utc() (+00:00). Equal
                # instants, different isoformat strings — astimezone(utc) aligns them.
                from datetime import timezone as _tz

                history_map = {}
                for hr in cur.fetchall() or []:
                    _key = hr["bucket"].astimezone(_tz.utc).isoformat()
                    history_map.setdefault(hr["agent_name"].removesuffix(" (CLI)"), {})[_key] = {
                        "tokens": int(hr["tokens"] or 0),
                        "dispatches": int(hr["dispatches"] or 0),
                    }

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
                    hours_map[_hrec["name"].removesuffix(" (CLI)")] = {
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

                try:
                    cur.execute(
                        """
                        SELECT status, COUNT(*) AS cnt
                        FROM media_generation_queue
                        WHERE status IN ('pending', 'dispatched', 'generating')
                           OR (status = 'failed' AND created_at > NOW() - INTERVAL '24 hours')
                        GROUP BY status
                        """
                    )
                    media_queue_by_status = {row["status"]: int(row["cnt"] or 0) for row in cur.fetchall()}
                except Exception:
                    media_queue_by_status = {}

            # Task #3798: fixed 24-slot hour grid (oldest → newest) so every agent's
            # recovery series has the same shape and empty hours render as zero.
            from datetime import timedelta

            from services.time_utils import now_utc

            _now_h = now_utc().replace(minute=0, second=0, microsecond=0)
            _hour_slots = [(_now_h - timedelta(hours=i)).isoformat() for i in range(23, -1, -1)]

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
                tokens_1h_v = int(vel.get("tokens_1h") or 0)
                tokens_24h_v = int(vel.get("tokens_24h") or 0)
                # No 150k fallback: an agent without a budget row has no token limit —
                # don't fabricate one that masks an underfunded agent (token_ratio stays
                # 0, since you can't exceed a limit that does not exist).
                token_limit = int(r["token_limit_per_day"]) if r["token_limit_per_day"] else None
                token_ratio = (tokens_24h_v / token_limit) if token_limit else 0.0
                # Task #3799: at_limit gates on TOKENS vs the per-LLM daily budget (the
                # C.R.E.E.D. capacity model, KB #271838) — not dispatches-since-reset.
                # A 200-dispatch classifier is fine; a 10-dispatch 40k-token analyst may
                # not be. Concurrent queue-slot check (task_count >= task_limit) stays.
                at_limit = at_limit or token_ratio >= 1.0
                # ETA to limit from the token burn rate (tokens left / tokens-per-hour)
                if token_limit and tokens_1h_v > 0 and tokens_24h_v < token_limit:
                    hours_to_limit = round((token_limit - tokens_24h_v) / tokens_1h_v, 1)
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

                # B1: label WHICH dimension is at/over limit (so the UI stops showing a
                # bare "at limit"), and — for tokens — when the rolling 24h window recovers
                # below budget as old work ages out (token "recovery" is time passing, NOT
                # a rest; ADR-004). Priority: token > task > hours > stress.
                _stress = float(r["stress"]) if r["stress"] else 0.0
                if token_limit and token_ratio >= 1.0:
                    limit_dimension = "token"
                elif task_count >= task_limit:
                    limit_dimension = "task"
                elif overwork_level in ("warning", "critical"):
                    limit_dimension = "hours"
                elif _stress >= 0.60:
                    limit_dimension = "stress"
                else:
                    limit_dimension = "none"
                token_recovery_eta_min = None
                if token_limit and token_ratio >= 1.0:
                    _running = tokens_24h_v
                    for _i, _slot in enumerate(_hour_slots):  # oldest hour ages out first
                        _running -= (history_map.get(r["name"], {}).get(_slot) or {}).get("tokens", 0)
                        if _running < token_limit:
                            token_recovery_eta_min = (_i + 1) * 60
                            break

                # #5157(3): 'barracked' is the bench — off the floor and, unlike
                # cooldown, NOT self-recovering. Split it by cause so the operator can
                # act: a failure-standby record within the Academy window means "under
                # verification"; its absence means the agent stranded there (#5155) and
                # is simply lost. The UI must never render either as a healthy agent.
                # #5829: is this "benched" agent actually still WORKING? Four agents
                # (P.U.B.L.I.S.H. 582 runs/24h, C.O.D.E.X. 173, G.A.V.E.L. 59,
                # P.R.O.B.E. 41) sat barracked while serving hundreds of tasks a day —
                # excluded from skill-based selection, yet fed by pinned/known-tool paths
                # that never consult shift_state. The card rendered them like any other
                # bench, so the contradiction was invisible for as long as it lasted.
                # Reuses the velocity query already run above (d1h) — no extra query, and
                # the 1-hour window is the sharper signal: a task that STARTED before the
                # bench can log shortly after it, but an agent still dispatching an hour
                # later is not resting by any reading.
                _recent_runs = d1h
                _benched = r["shift_state"] == "barracked"
                _benched_at = r.get("benched_at")
                _bench_age_h = None
                if r.get("bench_age_hours_sql") is not None:
                    _bench_age_h = round(float(r["bench_age_hours_sql"]), 1)
                # #5157(2): the welfare loop advances ACTIVE agents only, so a benched
                # agent's stress/energy/mood freeze at the bench-time snapshot. Surface
                # the age so a frozen reading is never mistaken for a live one.
                _stats_at = r.get("stats_updated_at")
                _stats_age_h = None
                if r.get("stats_age_hours_sql") is not None:
                    _stats_age_h = round(float(r["stats_age_hours_sql"]), 1)

                agent_data = {
                    "id": r["id"],
                    "name": r["name"],
                    "department": r["department"],
                    "shift_state": r["shift_state"],
                    "benched": _benched,
                    # 'failure'          => kin_failure_standby benched it (under Academy
                    #                        verification);
                    # 'stranded_working'  => benched but STILL LOGGING WORK — a contradiction
                    #                        between the status field and the work record
                    #                        (#5829), the most actionable of the three;
                    # 'stranded'          => barracked with no failure record and no activity,
                    #                        i.e. probably an accident (#5155).
                    # A failure-standby record wins: it explains the bench, and the agent may
                    # legitimately flush a task that began before it.
                    "bench_reason": (
                        ("failure" if _benched_at else ("stranded_working" if _recent_runs > 0 else "stranded"))
                        if _benched
                        else None
                    ),
                    # Shown on the card so the claim is auditable, not just asserted.
                    "bench_recent_runs": _recent_runs if _benched else None,
                    "bench_age_hours": _bench_age_h if _benched else None,
                    "stats_updated_at": (_stats_at.isoformat() + "Z" if _stats_at else None),
                    "stats_age_hours": _stats_age_h,
                    # Frozen once the reading outlives a couple of welfare cycles.
                    "stats_stale": bool(_stats_age_h is not None and _stats_age_h >= 2.0),
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
                    "tokens_1h": tokens_1h_v,
                    "tokens_24h": tokens_24h_v,
                    "token_limit_per_day": token_limit,
                    "token_ratio": round(token_ratio, 3),
                    "limit_dimension": limit_dimension,
                    "token_recovery_eta_min": token_recovery_eta_min,
                    "recovery_24h": [
                        {
                            "t": slot,
                            "tokens": (history_map.get(r["name"], {}).get(slot) or {}).get("tokens", 0),
                            "dispatches": (history_map.get(r["name"], {}).get(slot) or {}).get("dispatches", 0),
                        }
                        for slot in _hour_slots
                    ],
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
                    or token_ratio >= 0.9
                    or (r["stress"] or 0) > 0.7
                    or overwork_level != "normal"
                    or agent_data["rest_approval_id"]
                    # #5157: a BENCHED agent matches none of the above — it is not
                    # resting (barracked has no rest cycle), not at-limit, and its
                    # tokens/stress/overwork all read LOW precisely because it stopped
                    # working. So it was filtered OUT of the payload entirely and never
                    # reached the card renderer. Colouring the card (#2454) only helps
                    # once the agent is in the list. An agent pulled off the floor that
                    # does NOT self-recover is the single most important thing this tab
                    # can show; it must never be filtered out for looking calm.
                    or _benched
                ):
                    agents.append(agent_data)

                # Workload table: all agents with any activity or task_count > 0
                if d24h > 0 or task_count > 0:
                    workload.append(agent_data)

            # Task #3799: rank by TOKEN load, not dispatch count. Welfare cards:
            # resting agents first, then heaviest token-budget consumers. Workload
            # table: heaviest 24h token consumers first.
            # THIS sort is authoritative — it runs after the query and overrides the
            # SQL ORDER BY completely. #2454 added `(a.shift_state='barracked') DESC`
            # to that ORDER BY and it could never take effect: a benched agent is
            # `not resting` => True => sorted LAST, then -token_ratio pushed it last
            # again (a benched agent has ~0 tokens because it stopped working). It
            # rendered at position 13 of 14. Benched leads here for the same reason it
            # leads in SQL: an agent off the floor that does NOT self-recover is the
            # most urgent thing on this tab. Keep the two orderings in step.
            agents.sort(key=lambda x: (not x.get("benched"), not x["resting"], -x.get("token_ratio", 0.0)))
            workload.sort(key=lambda x: x.get("tokens_24h", 0), reverse=True)

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
                media_queue={
                    "by_status": media_queue_by_status,
                    "active": sum(
                        media_queue_by_status.get(status, 0) for status in ("pending", "dispatched", "generating")
                    ),
                    "failed": media_queue_by_status.get("failed", 0),
                },
            )
        except Exception as e:
            return jsonify(success=False, error=str(e)[:200]), 500

    from .work_detail_routes import register_work_detail_routes

    register_work_detail_routes(bp, admin_required)
