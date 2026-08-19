"""Bench integrity — catch an agent the platform thinks is resting but isn't (#5829).

WHY THIS EXISTS
---------------
On 2026-08-19 four agents sat ``shift_state='barracked'`` while actively working:

    P.U.B.L.I.S.H.  582 runs/24h    C.O.D.E.X.  173 runs/24h
    G.A.V.E.L.       59 runs/24h    P.R.O.B.E.   41 runs/24h

All four had ZERO open ``agent_rest_cycles`` and no rotation-log row. The two
dispatch surfaces disagreed: skill-based selection EXCLUDED them (score 0.0,
blocked), so ``documentation`` cross-routed to a Lv4 agent in another department
instead of its Lv5 owner — while pinned / known-tool / direct paths, which never
consult ``shift_state``, kept feeding them hundreds of tasks a day.

Nothing failed. No alert fired. K.I.N.'s hire detectors could not see it either:
they look for zero-agent gaps and pool saturation, and a stranded-but-working
owner is neither — it even looks UNDER-utilised, because a benched agent's
stress/energy/token stats freeze at bench time (#5157).

The detectable fact is a CONTRADICTION between a status field and the work
record — the same shape as ADR-014 (gate on the artifact, not the status) and
``backup_posture_monitor`` (measure the last SUCCESS, not the newest row).

DELIBERATELY NOT AN LLM. This is arithmetic on two columns; a model in this path
would add latency, cost and a failure mode for no gain.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

# States in which the platform believes an agent is NOT taking new work.
BENCH_STATES = ("barracked", "off_duty", "cooldown", "winding_down")

# Activity inside this window while benched is a contradiction, not lag.
# 6h is deliberately generous: a task that STARTED before the bench can log
# after it, and we would rather miss a marginal case than page on a race.
STRANDED_ACTIVITY_HOURS = 6

# Classifications
RESTING = "resting"  # benched WITH an open rest cycle — legitimate
STRANDED_WORKING = "stranded_working"  # benched, no rest cycle, STILL LOGGING WORK
STRANDED_IDLE = "stranded_idle"  # benched, no rest cycle, no activity


def classify_bench(
    shift_state: Optional[str],
    open_rest_cycles: int,
    runs_in_window: int,
) -> Optional[str]:
    """Classify one agent's bench state. ``None`` means 'not benched'.

    Pure: no DB, no clock. Every input is a plain value so the whole decision
    table is testable without fixtures.

    Precedence matters. An open rest cycle wins over activity: an agent that is
    genuinely resting may still flush a task that began before the bench, and
    calling that a defect would make the detector cry wolf on normal operation.
    """
    if not shift_state or shift_state not in BENCH_STATES:
        return None
    if open_rest_cycles and open_rest_cycles > 0:
        return RESTING
    if runs_in_window and runs_in_window > 0:
        return STRANDED_WORKING
    return STRANDED_IDLE


def is_contradiction(classification: Optional[str]) -> bool:
    """Only STRANDED_WORKING is a proven contradiction.

    STRANDED_IDLE is *suspicious* — a bench with no rest cycle behind it — but it
    is consistent with a deliberate manual bench, so it is reported, never alerted.
    Alerting on it would train everyone to ignore the alert.
    """
    return classification == STRANDED_WORKING


def summarize(rows: Iterable[dict]) -> dict:
    """Fold classified rows into a report. ``rows`` need name/classification keys."""
    out: List[dict] = list(rows)
    working = [r for r in out if r.get("classification") == STRANDED_WORKING]
    idle = [r for r in out if r.get("classification") == STRANDED_IDLE]
    resting = [r for r in out if r.get("classification") == RESTING]
    return {
        "checked": len(out),
        "stranded_working": len(working),
        "stranded_idle": len(idle),
        "resting": len(resting),
        "runs_stranded": sum(int(r.get("runs_in_window") or 0) for r in working),
        "agents": [r.get("name") for r in working],
        "healthy": not working,
    }


# ── DB-facing query (thin; the logic above stays pure) ───────────────────────
_SQL = """
    SELECT a.id, a.name, a.department, a.shift_state,
           (SELECT count(*) FROM agent_rest_cycles r
             WHERE r.agent_id = a.id AND r.ended_at IS NULL) AS open_rest_cycles,
           (SELECT count(*) FROM task_execution_log t
             WHERE t.agent_name = a.name
               AND t.created_at > now() - make_interval(hours => %s)) AS runs_in_window
      FROM agents a
     WHERE a.worker_type = 'ai'
       AND a.shift_state = ANY(%s)
"""


def find_bench_contradictions(cur, hours: int = STRANDED_ACTIVITY_HOURS) -> dict:
    """Run the check against a live cursor and return :func:`summarize` output."""
    cur.execute(_SQL, (hours, list(BENCH_STATES)))
    rows = []
    for row in cur.fetchall():
        rec = dict(row) if not isinstance(row, dict) else row
        rec["classification"] = classify_bench(
            rec.get("shift_state"),
            int(rec.get("open_rest_cycles") or 0),
            int(rec.get("runs_in_window") or 0),
        )
        rows.append(rec)
    report = summarize(rows)
    report["window_hours"] = hours
    report["detail"] = rows
    return report
