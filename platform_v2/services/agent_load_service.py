"""Shared per-agent / fleet load from task_execution_log — ONE source of truth (COORD-1).

The K.I.N. tab and the ARMADA tab historically disagreed about "how busy is this
agent": K.I.N. surfaced raw dispatch COUNT (and PERFORMANCE read the partial
``bridge_jobs`` table, ~53% success), while ARMADA read real tokens from
``task_execution_log`` (~100%). This service is the single query both sides call so
their numbers match. Spec: ``.claude/plans/kin-armada-token-unification.md``. KB #270619/#270621.

Load math is delegated to ``services.welfare_load`` (the same token formula that now drives
agent fatigue) — this module supplies DATA, not math, so welfare, work-sessions, performance
and the kin_workload_monitor all agree.

``model_used = 'internal'`` rows are non-LLM (admin/orchestration) and legitimately carry 0
tokens — they count toward dispatch/success tallies but contribute 0 to token load, so heavy
"internal" coordination never reads as token work.
"""

from __future__ import annotations

from services.welfare_load import DEFAULT_TOKEN_LIMIT_PER_DAY, compute_token_load

# Accepted window keywords → (interval SQL, minutes) for the rolling task_execution_log slice.
_WINDOWS = {
    "1h": ("1 hour", 60),
    "24h": ("24 hours", 1440),
    "7d": ("7 days", 10080),
}


def _resolve_window(window: str) -> tuple[str, int]:
    return _WINDOWS.get((window or "1h").lower(), _WINDOWS["1h"])


def get_agent_load(agent_id: int | None = None, window: str = "1h") -> dict | list[dict]:
    """Return token-based load for one agent (dict) or all AI agents (list of dicts).

    Args:
        agent_id: a specific ``agents.id``; ``None`` → every ``worker_type='ai'`` agent.
        window: ``'1h'`` (default), ``'24h'`` or ``'7d'`` — the rolling window summed.

    Each dict has: ``agent_id, agent_name, tokens, duration_ms, dispatches, success,
    failures, success_rate, token_limit_per_day, load`` where ``load`` ∈ [0,1] from the
    shared welfare_load formula (token + duration vs the agent's daily budget, scaled to
    the window). Used by K.I.N. WELFARE/WORKLOAD + PERFORMANCE so they match ARMADA.
    """
    interval_sql, window_min = _resolve_window(window)

    sql = f"""
        SELECT a.id              AS agent_id,
               a.name            AS agent_name,
               COALESCE(SUM(tel.tokens_used), 0)                       AS tokens,
               COALESCE(SUM(tel.duration_ms), 0)                       AS duration_ms,
               COUNT(tel.id)                                           AS dispatches,
               COUNT(tel.id) FILTER (WHERE tel.success)                AS success,
               COUNT(tel.id) FILTER (WHERE NOT tel.success)            AS failures,
               COALESCE(ab.token_limit_per_day, %s)                    AS token_limit_per_day
        FROM agents a
        LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
        LEFT JOIN task_execution_log tel
               ON tel.agent_id = a.id
              AND tel.created_at > NOW() - INTERVAL '{interval_sql}'
        WHERE a.worker_type = 'ai'
          {{agent_filter}}
        GROUP BY a.id, a.name, ab.token_limit_per_day
        ORDER BY tokens DESC
    """
    params: list = [DEFAULT_TOKEN_LIMIT_PER_DAY]
    if agent_id is not None:
        sql = sql.replace("{agent_filter}", "AND a.id = %s")
        params.append(agent_id)
    else:
        sql = sql.replace("{agent_filter}", "")

    # Lazy import so the module loads in any context (e.g. standalone self-test); the
    # scheduler's kin_workload_monitor imports get_db_cursor the same way.
    from database import get_db_cursor

    with get_db_cursor() as (_conn, cur):
        cur.execute(sql, params)
        rows = cur.fetchall() or []

    out = []
    for r in rows:
        tokens = int(r["tokens"] or 0)
        duration_ms = int(r["duration_ms"] or 0)
        dispatches = int(r["dispatches"] or 0)
        success = int(r["success"] or 0)
        failures = int(r["failures"] or 0)
        limit = r["token_limit_per_day"]
        out.append(
            {
                "agent_id": r["agent_id"],
                "agent_name": r["agent_name"],
                "tokens": tokens,
                "duration_ms": duration_ms,
                "dispatches": dispatches,
                "success": success,
                "failures": failures,
                "success_rate": round(success / dispatches, 3) if dispatches else None,
                "token_limit_per_day": int(limit) if limit else DEFAULT_TOKEN_LIMIT_PER_DAY,
                "load": round(compute_token_load(tokens, duration_ms, limit, window_min), 3),
                "window": window,
            }
        )

    if agent_id is not None:
        return (
            out[0]
            if out
            else {
                "agent_id": agent_id,
                "agent_name": None,
                "tokens": 0,
                "duration_ms": 0,
                "dispatches": 0,
                "success": 0,
                "failures": 0,
                "success_rate": None,
                "token_limit_per_day": DEFAULT_TOKEN_LIMIT_PER_DAY,
                "load": 0.0,
                "window": window,
            }
        )
    return out


def real_compute_hours_today(cur=None, agent_id=None) -> dict:
    """Real (non-internal) compute time per AI agent for TODAY as WALL-CLOCK busy
    time — the UNION of overlapping dispatch intervals, not the raw SUM of durations.

    KB #270628: hours-worked-today was ``SUM(duration_ms)``, so an agent running N
    concurrent dispatches had overlapping wall-clock counted N times (V.E.R.I.F.Y.
    read 89h of "work" in a 15h day from ~6x parallelism). The ``LEAST(sum, elapsed)``
    cap masked it by pegging such an agent at full elapsed time, so it tripped the 12h
    mandatory-rest threshold, rested, got woken by the reaper, and was immediately
    re-flagged on the same stale hours — a rest→reflag loop. This computes TRUE busy
    time via ``range_agg`` interval-union (Postgres 14+; live DB is pg16) and resets
    the day's window to AFTER the agent's last completed rest today (post-rest
    cooldown) so a just-rested agent starts fresh and cannot re-trip on stale hours.

    ``model_used = 'internal'`` (0-token orchestration that mostly WAITS on sub-tasks)
    and ``fleet_warmup`` rows are excluded — same as the agent_daily_summary builder —
    so orchestrators are not falsely flagged for coordinating.

    Args:
        cur: an existing ``RealDictCursor`` (callers — track_agent_hr, the K.I.N.
            welfare route — are mid-transaction and pass theirs); omit to self-open.
        agent_id: restrict to one ``agents.id`` (returns a 1-entry dict) — used by
            per-task ``update_welfare_after_task`` to fetch its own hours cheaply
            without scanning the whole fleet; ``None`` → every ``worker_type='ai'`` agent.

    Returns:
        ``{agent_id: {agent_id, name, shift_state, compute_ms, elapsed_ms, hours,
        window_start}}`` for every ``worker_type='ai'`` agent. ``hours`` is the
        capped (``min(compute_ms, elapsed_ms)``) wall-clock busy hours, rounded to 0.1.
        Agents with no real compute since their window start → ``0.0`` hours.
    """
    sql = """
        WITH daystart AS (
            SELECT (DATE_TRUNC('day', NOW() AT TIME ZONE 'America/Toronto')
                    AT TIME ZONE 'America/Toronto') AS t0
        ),
        restwin AS (
            -- Most recent COMPLETED rest today; the day's hours window restarts here.
            SELECT arc.agent_id, MAX(arc.ended_at) AS last_rest_end
            FROM agent_rest_cycles arc, daystart d
            WHERE arc.started_at >= d.t0
              AND arc.ended_at IS NOT NULL
              AND arc.ended_at <= NOW()
            GROUP BY arc.agent_id
        ),
        win AS (
            SELECT a.id AS agent_id, a.name, a.shift_state,
                   GREATEST(d.t0, COALESCE(rw.last_rest_end, d.t0)) AS w0
            FROM agents a
            CROSS JOIN daystart d
            LEFT JOIN restwin rw ON rw.agent_id = a.id
            WHERE a.worker_type = 'ai'
              {agent_filter}
        ),
        merged AS (
            -- range_agg merges overlapping [start, start+duration] intervals into a
            -- multirange, collapsing concurrent dispatches to real occupied time.
            SELECT tel.agent_id,
                   range_agg(tstzrange(
                       tel.created_at,
                       tel.created_at + (tel.duration_ms * INTERVAL '1 millisecond')
                   )) AS mr
            FROM task_execution_log tel
            JOIN win w ON w.agent_id = tel.agent_id
            WHERE tel.created_at >= w.w0
              AND tel.model_used IS DISTINCT FROM 'internal'
              AND tel.duration_ms IS NOT NULL
              AND tel.duration_ms > 0
              AND COALESCE(tel.module_source, '') != 'fleet_warmup'
            GROUP BY tel.agent_id
        ),
        compute AS (
            SELECT m.agent_id,
                   COALESCE(SUM(EXTRACT(EPOCH FROM (upper(r) - lower(r))) * 1000), 0)
                       AS compute_ms
            FROM merged m, unnest(m.mr) AS r
            GROUP BY m.agent_id
        )
        SELECT w.agent_id, w.name, w.shift_state,
               COALESCE(c.compute_ms, 0)                  AS compute_ms,
               EXTRACT(EPOCH FROM (NOW() - w.w0)) * 1000  AS elapsed_ms,
               w.w0                                       AS window_start
        FROM win w
        LEFT JOIN compute c ON c.agent_id = w.agent_id
    """

    if agent_id is not None:
        sql = sql.replace("{agent_filter}", "AND a.id = %s")
        params = (agent_id,)
    else:
        sql = sql.replace("{agent_filter}", "")
        params = None

    def _fetch(c):
        c.execute(sql, params)
        return c.fetchall() or []

    if cur is not None:
        rows = _fetch(cur)
    else:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, c):
            rows = _fetch(c)

    out: dict = {}
    for r in rows:
        compute_ms = float(r["compute_ms"] or 0)
        elapsed_ms = float(r["elapsed_ms"] or 0)
        capped_ms = min(compute_ms, elapsed_ms)
        out[r["agent_id"]] = {
            "agent_id": r["agent_id"],
            "name": r["name"],
            "shift_state": r["shift_state"],
            "compute_ms": compute_ms,
            "elapsed_ms": elapsed_ms,
            "hours": round(capped_ms / 3_600_000, 1),
            "window_start": r["window_start"],
        }
    return out


if __name__ == "__main__":  # pragma: no cover - live smoke test
    fleet = get_agent_load(window="24h")
    print(f"fleet rows (24h): {len(fleet)}")
    for row in fleet[:5]:
        print(
            f"  {row['agent_name']:16} tok={row['tokens']:>8} "
            f"disp={row['dispatches']:>4} load={row['load']:.3f} "
            f"succ={row['success_rate']}"
        )
    if fleet:
        one = get_agent_load(agent_id=fleet[0]["agent_id"], window="1h")
        print(f"single agent 1h: {one['agent_name']} load={one['load']} tokens={one['tokens']}")

    print("\nreal_compute_hours_today (interval-union, post-rest window) — KB #270628:")
    hrs = real_compute_hours_today()
    top = sorted(hrs.values(), key=lambda x: x["hours"], reverse=True)[:8]
    for h in top:
        raw = h["compute_ms"] / 3_600_000
        elapsed = h["elapsed_ms"] / 3_600_000
        print(f"  {h['name']:16} union={h['hours']:>5.1f}h  raw_union={raw:>5.1f}h  elapsed={elapsed:>5.1f}h")
