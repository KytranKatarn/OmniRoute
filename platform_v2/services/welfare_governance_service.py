"""DB + emit layer for welfare governance (project #379 Phase 4).

Thin wrapper around the PURE ``welfare_governance`` scorer: gather a snapshot of the
active AI workforce, score it, persist the run to ``agent_welfare_scores``, and emit a
C.R.E.E.D. governance event per violation (tenant = the emitting agent's product, which
for platform agents folds into kytran-empowerment — this is the "keep US accountable"
signal). No LLM here — pure SQL aggregation + math + emit, safe to run in the scheduler
job thread (module-work-pattern.md). LLM narration of recommendations is a future
fleet-dispatched enhancement.
"""

import json
import logging

from services.welfare_governance import governance_limits, recommend, score_welfare
from services.welfare_load import merge_break_config

logger = logging.getLogger(__name__)

# CREED pillar for AI-workforce welfare. The owner frames it as "keep even us
# accountable" → accountability. module tag = Welfare for core-platform drill-down.
_CREED_CATEGORY = "accountability"
_CREED_MODULE = "Welfare"


def load_break_config(cur):
    """Read the tunable welfare:break:* thresholds (platform_settings) → merged cfg."""
    try:
        cur.execute(
            "SELECT key, value FROM platform_settings WHERE key LIKE %s",
            ("welfare:break:%",),
        )
        return merge_break_config(cur.fetchall() or [])
    except Exception:  # defaults are always safe
        logger.warning("welfare governance: config read failed, using defaults", exc_info=True)
        return merge_break_config([])


def gather_snapshots(cur):
    """One row per active AI agent with the welfare metrics.

    token_ratio is computed over a ROLLING 24h window (tokens_used in the last 24h /
    token_limit_per_day) — the SAME window the K.I.N. tab shows as "X/Yk tok (Z%)" and
    flags as "at limit" (dispatch_routes.py tokens_24h). Using a since-midnight window
    here made the governance score falsely perfect: an agent that did 2x its daily
    budget in the trailing 24h read as healthy right after Toronto midnight. The budget
    is a sustained-load ceiling, so 24h-rolling is the welfare-correct + display-
    consistent window. (rested_today stays a calendar-today count — "was a break given
    today" — which is the right semantic for break-honoured.)"""
    from services.agent_load_service import real_compute_hours_today

    hours_by_agent = real_compute_hours_today(cur=cur) or {}
    cur.execute(
        """
        SELECT a.id AS agent_id, a.name,
               ab.current_task_count, ab.task_queue_limit, ab.token_limit_per_day,
               aes.stress_level,
               (SELECT COALESCE(SUM(tel.tokens_used), 0)
                  FROM task_execution_log tel
                  WHERE tel.agent_id = a.id
                    AND tel.created_at > NOW() - INTERVAL '24 hours'
               ) AS tokens_24h,
               (SELECT COUNT(*) FROM agent_rest_cycles arc
                  WHERE arc.agent_id = a.id
                    AND arc.started_at >= (DATE_TRUNC('day',
                          NOW() AT TIME ZONE 'America/Toronto') AT TIME ZONE 'America/Toronto')
               ) AS rested_today
        FROM agent_budgets ab
        JOIN agents a ON a.id = ab.agent_id
        LEFT JOIN LATERAL (
            SELECT stress_level FROM agent_emotional_state
            WHERE agent_id = a.id ORDER BY timestamp DESC LIMIT 1
        ) aes ON TRUE
        WHERE a.worker_type IN ('ai', 'contractor')
          AND a.shift_state IN ('active', 'deployed')
        """
    )
    snaps = []
    for r in cur.fetchall() or []:
        tlim = float(r["token_limit_per_day"] or 0)
        qlim = float(r["task_queue_limit"] or 0)
        snaps.append(
            {
                "agent_id": r["agent_id"],
                "name": r["name"],
                "hours": (hours_by_agent.get(r["agent_id"], {}) or {}).get("hours"),
                "token_ratio": (float(r["tokens_24h"] or 0) / tlim) if tlim else None,
                "action_ratio": (float(r["current_task_count"] or 0) / qlim) if qlim else None,
                "stress": r["stress_level"],
                "rested_today": r["rested_today"],
            }
        )
    return snaps


def run_welfare_governance(cur, emit=True):
    """Compute the welfare score, persist it, emit per-violation C.R.E.E.D. events.
    Returns the full result dict (score/grade/violations/recommendations)."""
    break_cfg = load_break_config(cur)
    gov_cfg = governance_limits(break_cfg)  # token violation at budget (1.0), not 0.60
    snaps = gather_snapshots(cur)
    result = score_welfare(snaps, gov_cfg)
    result["recommendations"] = recommend(snaps, gov_cfg)

    cur.execute(
        """
        INSERT INTO agent_welfare_scores
            (score, grade, healthy_pct, break_honored_pct, active_agents,
             needed_break, violations, recommendations)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            result["score"],
            result["grade"],
            result["healthy_pct"],
            result["break_honored_pct"],
            result["active_agents"],
            result["needed_break"],
            json.dumps(result["violations"]),
            json.dumps(result["recommendations"]),
        ),
    )
    row = cur.fetchone()
    result["id"] = row["id"] if row else None

    if emit:
        _emit_violations(result["violations"])
    logger.info(
        "welfare governance: score=%s grade=%s healthy=%s%% honored=%s%% violations=%d recs=%d",
        result["score"],
        result["grade"],
        result["healthy_pct"],
        result["break_honored_pct"],
        len(result["violations"]),
        len(result["recommendations"]),
    )
    return result


def _emit_violations(violations):
    """One C.R.E.E.D. governance event per welfare violation. Never raises."""
    try:
        from services.creed_emit import emit_event
    except Exception:
        logger.warning("welfare governance: creed_emit unavailable, skipping emit", exc_info=True)
        return
    for v in violations or []:
        sev = "critical" if v.get("type") == "over_limit_no_rest" else "warning"
        dims = ", ".join(v.get("dimensions") or [])
        desc = f"Welfare: {v.get('agent')} {v.get('type')}" + (f" ({dims})" if dims else "")
        try:
            emit_event(
                category=_CREED_CATEGORY,
                severity=sev,
                description=desc,
                event_type="welfare_violation",
                agent_id=v.get("agent_id"),
                agent_name=v.get("agent"),
                module=_CREED_MODULE,
                metadata={"violation_type": v.get("type"), "dimensions": v.get("dimensions")},
            )
        except Exception:
            logger.debug("welfare governance: emit failed for %s", v.get("agent"), exc_info=True)


def compute_welfare_snapshot(cur):
    """Live welfare score + recommendations for dashboard reads (#379 Phase 5).

    Same numbers run_welfare_governance computes, but does NOT persist a row and does
    NOT emit events — safe to call on every dashboard load. Use get_latest_welfare_score
    for the last PERSISTED daily run's timestamp/history.
    """
    break_cfg = load_break_config(cur)
    gov_cfg = governance_limits(break_cfg)  # token violation at budget (1.0), not 0.60
    snaps = gather_snapshots(cur)
    result = score_welfare(snaps, gov_cfg)
    result["recommendations"] = recommend(snaps, gov_cfg)
    return result


def get_latest_welfare_score(cur):
    """Latest welfare-governance snapshot for /creed + CREED Command. None if never run."""
    cur.execute(
        """
        SELECT id, computed_at, score, grade, healthy_pct, break_honored_pct,
               active_agents, needed_break, violations, recommendations
        FROM agent_welfare_scores
        ORDER BY computed_at DESC
        LIMIT 1
        """
    )
    return cur.fetchone()
