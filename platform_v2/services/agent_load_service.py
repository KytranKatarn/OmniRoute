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
