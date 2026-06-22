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

from services.welfare_governance import (
    DEFAULT_SCORE_EWMA_ALPHA,
    governance_limits,
    grade_for,
    recommend,
    score_welfare,
    smooth_score,
)
from services.welfare_load import merge_break_config

logger = logging.getLogger(__name__)

# CREED category for AI-workforce welfare. Phase 3 CATEGORY SWITCH (#379): welfare
# now emits as its OWN public pillar category='welfare' (scored by the standalone
# welfare_engine), NOT category='accountability'. Riding 'accountability' double-
# counted welfare into the ethics grade AND meant the public welfare grade never
# got any events. The per-dimension emit lives in services/welfare_emit.py.
_CREED_MODULE = "Welfare"


def pool_over_budget_by_skill(skill_name: str, settings_key: str = "welfare:backlog:pool_pause_ratio") -> bool:
    """True when EVERY agent in the pool for ``skill_name`` is at/over its 24h token
    budget — i.e. even the LEAST-loaded agent's (24h tokens_used / daily budget) ratio
    is >= the pause ratio from ``platform_settings[settings_key]`` (default 0.9). Used to
    back a discretionary backlog/generation cycle off so the 24h window can drain when
    the dispatch throttle would otherwise just rotate work among at-limit agents
    (ADR-004/#4090, ADR-002).

    Fail-OPEN: no pool, no budget data, or any error → returns ``False`` (never gate).

    Shared single source of the welfare pool gate: WTF backlog jobs pass
    ``welfare:backlog:pool_pause_ratio``; S.I.G.N.A.L. generation/engagement pass
    ``welfare:signal:pool_pause_ratio``. (Promoted from the former nested closure
    ``jobs._wtf_backlog_pool_over_budget`` so non-job callers can reuse it.)
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s",
                (settings_key,),
            )
            _row = cur.fetchone()
            try:
                pause_ratio = float(_row["value"]) if _row and _row.get("value") not in (None, "") else 0.9
            except (TypeError, ValueError):
                pause_ratio = 0.9
            cur.execute(
                """
                SELECT MIN(COALESCE(t.tok, 0)::float / NULLIF(ab.token_limit_per_day, 0)) AS min_ratio,
                       COUNT(*) AS n
                FROM agent_skills s
                JOIN agents a ON a.id = s.agent_id
                JOIN agent_budgets ab ON ab.agent_id = a.id
                LEFT JOIN (
                    SELECT agent_id, SUM(tokens_used) AS tok
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY agent_id
                ) t ON t.agent_id = a.id
                WHERE s.skill_name = %s
                  AND a.worker_type IN ('ai', 'contractor')
                  AND a.shift_state IN ('active', 'deployed', 'winding_down')
                """,
                (skill_name,),
            )
            r = cur.fetchone()
        if not r or not r["n"] or r["min_ratio"] is None:
            return False  # no pool / no budget data → never gate
        min_ratio = float(r["min_ratio"])
        gated = min_ratio >= pause_ratio
        if gated:
            # Diagnostic: surface WHY a backlog/generation cycle was paused so an
            # operator tuning the ratio can see the pool's actual headroom.
            logger.info(
                "[WelfarePool] gating skill=%s: pool min 24h token ratio %.2f >= pause %.2f (key=%s, n=%s)",
                skill_name,
                min_ratio,
                pause_ratio,
                settings_key,
                r["n"],
            )
        return gated
    except Exception:
        logger.warning(
            "[WelfarePool] gate check failed for skill=%s key=%s; not gating",
            skill_name,
            settings_key,
            exc_info=True,
        )
        return False


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
    """One row per AI agent in the work/rest cycle (active, deployed, winding_down,
    cooldown) with the welfare metrics.

    winding_down/cooldown are INCLUDED because an agent that blew past its token budget
    transitions there as it winds down — excluding those states hid the very agents most
    likely to be over-limit and made the score falsely 100/A+ while the K.I.N. tab (which
    includes them) correctly showed them "at limit" (mistake #272470, population side).
    barracked/off_duty/decommissioned stay excluded (not in the active work cycle).

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
          AND a.shift_state IN ('active', 'deployed', 'winding_down', 'cooldown')
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


def gather_sole_agent_capabilities(cur):
    """Capabilities served by exactly ONE active agent (a single point of failure).

    Same active population as gather_snapshots (worker_type ai/contractor, shift_state
    active/deployed). When that sole agent is over its token budget, recommend() raises a
    staffing_gap — the throttle has no healthy peer to route to (#4090 part 3). Returns a
    list of {capability, agent_id, agent_name}."""
    cur.execute(
        """
        SELECT s.skill_name AS capability,
               MIN(a.id)    AS agent_id,
               MIN(a.name)  AS agent_name
        FROM agent_skills s
        JOIN agents a ON a.id = s.agent_id
        WHERE a.worker_type IN ('ai', 'contractor')
          AND a.shift_state IN ('active', 'deployed')
          AND s.skill_name IS NOT NULL
        GROUP BY s.skill_name
        HAVING COUNT(DISTINCT a.id) = 1
        """
    )
    return [
        {"capability": r["capability"], "agent_id": r["agent_id"], "agent_name": r["agent_name"]}
        for r in (cur.fetchall() or [])
    ]


def _latest_ewma_score(cur):
    """Most recent persisted EWMA welfare score, or None (never persisted / column new)."""
    cur.execute(
        "SELECT ewma_score FROM agent_welfare_scores " "WHERE ewma_score IS NOT NULL ORDER BY computed_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    return float(row["ewma_score"]) if row and row.get("ewma_score") is not None else None


def run_welfare_governance(cur, emit=True):
    """Compute the welfare score, persist it, emit per-violation C.R.E.E.D. events.
    Returns the full result dict (score/grade/violations/recommendations)."""
    break_cfg = load_break_config(cur)
    gov_cfg = governance_limits(break_cfg)  # token violation at budget (1.0), not 0.60
    snaps = gather_snapshots(cur)
    result = score_welfare(snaps, gov_cfg)
    result["recommendations"] = recommend(snaps, gov_cfg, sole_agent_capabilities=gather_sole_agent_capabilities(cur))
    # D3: EWMA-smoothed headline (steady) — blend this raw score with the prior EWMA
    # so a single bad daily snapshot can't tank the grade. First run seeds to raw.
    prev_ewma = _latest_ewma_score(cur)
    ewma = smooth_score(result["score"], prev_ewma, DEFAULT_SCORE_EWMA_ALPHA)
    result["ewma_score"] = ewma
    result["ewma_grade"] = grade_for(ewma, gov_cfg)

    cur.execute(
        """
        INSERT INTO agent_welfare_scores
            (score, grade, healthy_pct, break_honored_pct, active_agents,
             needed_break, violations, recommendations, ewma_score, ewma_grade)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            result["ewma_score"],
            result["ewma_grade"],
        ),
    )
    row = cur.fetchone()
    result["id"] = row["id"] if row else None

    if emit:
        # Phase 3: per-dimension, de-duped, category='welfare' emit (welfare_emit).
        # The daily run still persists the headline row above; the actual public
        # signal comes from the de-duped per-agent/dimension events. The intraday
        # job (welfare_emit_intraday) is what keeps the public welfare grade moving
        # mid-day — the daily 06:00 sample is the token-window low and emits little.
        result["emit_summary"] = emit_welfare_snapshots(cur, snaps=snaps, break_cfg=break_cfg)
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


def _safe_record_outage(reason):
    """Record a welfare-emit outage loudly even when welfare_emit itself is the
    import that failed — try the shared recorder, else fall back to an error log."""
    try:
        from services.welfare_emit import record_welfare_emit_outage

        record_welfare_emit_outage(reason)
    except Exception:
        logger.error("welfare governance: outage (welfare_emit unavailable): %s", reason)


def emit_welfare_snapshots(cur, snaps=None, break_cfg=None):
    """Emit per-dimension, de-duped, category='welfare' C.R.E.E.D. events for the
    active workforce (Phase 3, roadmap item D). Delegates to welfare_emit, which:

      * builds one welfare_<dim> event per agent×dimension (hours/tokens/actions/
        stress) + break-honor events, with severity mapped to welfare_engine's
        ladder (info=0/warning=1/violation=3/critical=5) so the standalone
        computes a real per-dimension violation rate;
      * de-dupes against agent_welfare_emit_state (emit only on state change or a
        heartbeat window) so 54 agents × 4 dims don't flood the public store;
      * makes emit failures LOUD (governance_audit_log + system_notification).

    category='welfare' (NOT 'accountability') → lands on the public welfare grade,
    excluded from the ethics accountability pillar. Routed per-tenant by
    creed_emit (WTF agents → what-the-fact, others → kytran-empowerment).
    Returns the welfare_emit summary dict. Never raises."""
    zero = {"built": 0, "emitted": 0, "skipped": 0, "failed": 0}
    try:
        from services.welfare_emit import emit_welfare_events, record_welfare_emit_outage
    except Exception as exc:
        logger.error("welfare governance: welfare_emit unavailable, emit skipped", exc_info=True)
        _safe_record_outage(f"welfare_emit module unavailable: {exc!r}")
        return zero
    try:
        if snaps is None:
            snaps = gather_snapshots(cur)
        if break_cfg is None:
            break_cfg = load_break_config(cur)
        return emit_welfare_events(cur, snaps, break_cfg=break_cfg)
    except Exception as exc:
        logger.error("welfare governance: welfare emit failed", exc_info=True)
        record_welfare_emit_outage(f"welfare emit raised: {exc!r}")
        return zero


def welfare_emit_intraday(cur):
    """Intraday welfare emit — the FIX-1 entry point for the hourly job. Gathers a
    FRESH snapshot (NOT the 06:00 daily-low) and emits the de-duped per-dimension
    welfare events. Does NOT persist an agent_welfare_scores headline row (the
    daily job owns that), so it is cheap to run every cycle. Returns the summary."""
    break_cfg = load_break_config(cur)
    snaps = gather_snapshots(cur)
    return emit_welfare_snapshots(cur, snaps=snaps, break_cfg=break_cfg)


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
    result["recommendations"] = recommend(snaps, gov_cfg, sole_agent_capabilities=gather_sole_agent_capabilities(cur))
    # D3: smoothed headline for live reads — blend the live raw with the last
    # PERSISTED EWMA (no write; the daily run is what advances the EWMA).
    ewma = smooth_score(result["score"], _latest_ewma_score(cur), DEFAULT_SCORE_EWMA_ALPHA)
    result["ewma_score"] = ewma
    result["ewma_grade"] = grade_for(ewma, gov_cfg)
    return result


def get_latest_welfare_score(cur):
    """Latest welfare-governance snapshot for /creed + CREED Command. None if never run."""
    cur.execute(
        """
        SELECT id, computed_at, score, grade, healthy_pct, break_honored_pct,
               active_agents, needed_break, violations, recommendations,
               ewma_score, ewma_grade
        FROM agent_welfare_scores
        ORDER BY computed_at DESC
        LIMIT 1
        """
    )
    return cur.fetchone()
