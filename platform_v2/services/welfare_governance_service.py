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
from typing import Optional

from services.welfare_governance import (
    DEFAULT_SCORE_EWMA_ALPHA,
    governance_limits,
    grade_for,
    recommend,
    score_welfare,
    smooth_score,
)
from services.welfare_load import merge_break_config, welfare_token_filter_sql

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
                """
                + welfare_token_filter_sql()  # #5319: warmups never bill a welfare ledger
                + """
                    GROUP BY agent_id
                ) t ON t.agent_id = a.id
                WHERE s.skill_name = %s
                  AND a.worker_type IN ('ai', 'contractor')
                  AND a.org_id IS NULL   -- internal agents only; client (AaaS) agents excluded (#4590)
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


def recommend_pool_staffing_gaps(
    ratio_key: str = "welfare:staffing:pool_gap_ratio",
    min_backlog_settings_key: str = "welfare:staffing:min_backlog",
    default_min_backlog: int = 3,
) -> list:
    """POOL-SATURATION staffing gaps: a skill whose ENTIRE active internal-AI pool
    (>= 2 agents) is at/over its 24h token-budget ceiling AND has a sustained dispatch
    backlog. This is the "the whole department is maxed — add an agent" signal.

    Distinct from the two existing hire signals so it doesn't double-fire:
      * ``_list_current_capability_gaps`` (agent_jobs) = a capability with ZERO agents.
      * ``recommend()`` staffing_gap = a SOLE-agent skill at >= budget (single point of
        failure). Only fires when ``COUNT(DISTINCT agent) == 1``.
    A shared skill held by several agents (e.g. ``fact_check`` across V.E.R.I.F.Y. and
    P.R.O.O.F.) that is JOINTLY saturated slips past both — this closes that gap. It is
    only meaningful because per-agent token accounting is now honest (A.R.M.A.D.A.
    attribution fix + backfill).

    Returns ``[{capability, pool_size, backlog, gap_reason}]`` (deepest backlog first,
    possibly empty). Fail-OPEN: any error → ``[]`` so a DB hiccup never fabricates a
    hiring signal.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (min_backlog_settings_key,))
            _row = cur.fetchone()
            try:
                min_backlog = (
                    int(_row["value"]) if _row and _row.get("value") not in (None, "") else default_min_backlog
                )
            except (TypeError, ValueError):
                min_backlog = default_min_backlog

            # Candidate skills: MULTI-agent pools (>= 2) among active internal AI agents.
            # Mirrors the pool definition in pool_over_budget_by_skill (worker_type,
            # org_id IS NULL, active shift states) so 'pool' means the same thing here.
            cur.execute(
                """
                SELECT s.skill_name AS skill, COUNT(DISTINCT a.id) AS pool_size
                FROM agent_skills s
                JOIN agents a ON a.id = s.agent_id
                WHERE a.worker_type IN ('ai', 'contractor')
                  AND a.org_id IS NULL
                  AND a.shift_state IN ('active', 'deployed', 'winding_down')
                GROUP BY s.skill_name
                HAVING COUNT(DISTINCT a.id) >= 2
                """
            )
            pools = {r["skill"]: int(r["pool_size"]) for r in cur.fetchall()}
            if not pools:
                return []

            # Backlog per capability: dispatches that had to QUEUE for this capability over
            # the last 24h (sustained contention/demand). Deliberately NOT an instantaneous
            # non-terminal snapshot — the cold-load queue drains fast, so a snapshot would
            # read ~0 for a chronically-maxed pool between daily checks. Counting queued_at
            # over 24h pairs naturally with the 24h saturation gate below.
            cur.execute(
                """
                SELECT capability, COUNT(*) AS n
                FROM dispatch_pending_queue
                WHERE queued_at > NOW() - INTERVAL '24 hours'
                  AND capability = ANY(%s)
                GROUP BY capability
                """,
                (list(pools.keys()),),
            )
            backlog = {r["capability"]: int(r["n"]) for r in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001 — never fabricate a hiring signal on error
        logger.warning("recommend_pool_staffing_gaps query failed: %s", exc)
        return []

    gaps: list = []
    for skill, pool_size in pools.items():
        depth = backlog.get(skill, 0)
        if depth < min_backlog:
            continue
        # pool_over_budget_by_skill is the single source of the 'whole pool at/over
        # budget' truth (reads welfare:staffing:pool_gap_ratio, default 1.0 = fully maxed).
        try:
            saturated = pool_over_budget_by_skill(skill, settings_key=ratio_key)
        except Exception:  # noqa: BLE001
            saturated = False
        if not saturated:
            continue
        gaps.append(
            {
                "capability": skill,
                "pool_size": pool_size,
                "backlog": depth,
                "gap_reason": (
                    f"pool_saturation: all {pool_size} active agent(s) for '{skill}' at/over their "
                    f"24h token budget with {depth} dispatch(es) queued in the last 24h"
                ),
            }
        )
    gaps.sort(key=lambda g: g["backlog"], reverse=True)
    return gaps


def recommend_sole_agent_staffing_gaps(
    ratio_key: str = "welfare:staffing:pool_gap_ratio",
) -> list:
    """SOLE-AGENT saturation gaps: a skill whose ONLY active agent is at/over its 24h
    token budget. Returns ``[{capability, pool_size, agent_id, agent_name, gap_reason}]``.

    WHY THIS EXISTS SEPARATELY (2026-08-02).
    ``recommend()`` has raised a ``staffing_gap`` for exactly this case since #4090 — and
    it works: ``gather_sole_agent_capabilities`` returns the capability and the rec is
    produced. But that rec is ADVISORY TEXT in the governance result. The only path that
    ever reaches ``hiring_service.propose_for_gap`` (and therefore the DHQ Hiring Queue)
    is ``kin_recommend_pool_staffing`` -> ``recommend_pool_staffing_gaps``, which requires
    ``COUNT(DISTINCT agent) >= 2``. So a lone maxed agent was described but never queued
    for hire: every ``hiring_candidates`` row on the platform carried a
    ``pool_saturation:`` reason, none a sole-agent one.

    Measured case: P.U.B.L.I.S.H. is the ONLY holder of ``beat_classification`` and ran at
    654,032 / 150,000 tokens = 4.36x budget over 24h, with 3,024 runs and zero failures.

    ⚠️ NO BACKLOG GATE — and that asymmetry is the whole point, not an oversight.
    ``recommend_pool_staffing_gaps`` requires >= ``welfare:staffing:min_backlog`` (default
    3) queued dispatches. ``beat_classification`` had **ZERO** rows in
    ``dispatch_pending_queue`` over the same 24h. A pool of >=2 queues work when it
    saturates; a LONE agent has nothing to queue behind and simply absorbs the load,
    overrunning its budget instead. The empty queue is a symptom of the overwork, not
    evidence against it. Copying the backlog gate here would have produced a signal that
    could never fire for the case that motivated it.

    Budget overrun IS the saturation signal for a sole agent. Reuses
    ``pool_over_budget_by_skill`` unchanged — its ``MIN(ratio)`` over a one-agent pool is
    simply that agent's ratio, so the "at/over budget" definition stays identical to the
    pool path and cannot drift from it.

    Fail-OPEN: any error → ``[]``, so a DB hiccup never fabricates a hiring signal.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (_conn, cur):
            # Sole-agent skills. Population matches gather_sole_agent_capabilities and
            # recommend_pool_staffing_gaps so "the pool" means one thing platform-wide.
            cur.execute(
                """
                WITH demand AS (
                    -- #5829: DEMAND GATE. The ZERO-AGENT scan was gated in #5187 for
                    -- exactly this reason — ungated, it produced 104 "gaps" with zero
                    -- real dispatches, pure skill-inventory noise. The SOLE-AGENT path
                    -- never got the same gate and reproduced the identical failure at
                    -- smaller scale: measured 2026-08-19, 14 of the 15 pending
                    -- proposals had ZERO dispatches in 30 days.
                    --
                    -- A sole agent who is over budget for work NOBODY REQUESTS is not a
                    -- staffing gap; hiring against it adds an agent, a budget row,
                    -- welfare tracking and warm-model pressure, and changes nothing.
                    --
                    -- Same definition as the zero-agent gate (real inference only,
                    -- 30 days, the shared marker exclude-list) so "demand" means ONE
                    -- thing platform-wide and the two scans cannot disagree.
                    SELECT DISTINCT lower(replace(capability, ' ', '_')) AS capability
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '30 days'
                      AND worker_type IS NOT NULL
                      AND capability IS NOT NULL
                      AND lower(COALESCE(model_used, '')) NOT IN
                          ('bridge-managed', 'internal', 'batch', 'browser', 'comfyui', '')
                )
                SELECT s.skill_name AS skill,
                       MIN(a.id)    AS agent_id,
                       MIN(a.name)  AS agent_name
                FROM agent_skills s
                JOIN agents a ON a.id = s.agent_id
                WHERE a.worker_type IN ('ai', 'contractor')
                  AND a.org_id IS NULL
                  AND a.shift_state IN ('active', 'deployed')
                  AND s.skill_name IS NOT NULL
                  -- Normalized both sides: agent_skills carries Title Case rows from
                  -- older/human agents, task_execution_log carries snake_case.
                  AND lower(replace(s.skill_name, ' ', '_')) IN (SELECT capability FROM demand)
                GROUP BY s.skill_name
                HAVING COUNT(DISTINCT a.id) = 1
                """
            )
            solos = [
                {"skill": r["skill"], "agent_id": r["agent_id"], "agent_name": r["agent_name"]}
                for r in (cur.fetchall() or [])
            ]
    except Exception as exc:  # noqa: BLE001 — never fabricate a hiring signal on error
        logger.warning("recommend_sole_agent_staffing_gaps query failed: %s", exc)
        return []

    gaps: list = []
    for solo in solos:
        skill = solo["skill"]
        try:
            saturated = pool_over_budget_by_skill(skill, settings_key=ratio_key)
        except Exception:  # noqa: BLE001
            saturated = False
        if not saturated:
            continue
        gaps.append(
            {
                "capability": skill,
                "pool_size": 1,
                "agent_id": solo["agent_id"],
                "agent_name": solo["agent_name"],
                # Tags the alert path so it cannot borrow the pool wording — a sole-agent
                # gap has no backlog, and rendering "None dispatch(es) queued" would make
                # the alert misdescribe its own cause.
                "signal": "sole_agent_saturation",
                "gap_reason": (
                    f"sole_agent_saturation: the only active agent for '{skill}' "
                    f"({solo['agent_name']}) is at/over its 24h token budget — the dispatch "
                    "throttle has no healthy peer to route to"
                ),
            }
        )
    gaps.sort(key=lambda g: g["capability"])
    return gaps


def in_flight_over_cap(
    job_type: str,
    cap_key: str = "welfare:backlog:max_inflight",
    default_cap: int = 25,
    window_minutes: int = 10,
) -> bool:
    """True when ``job_type`` already has >= cap in-flight ``bridge_jobs`` — a QUEUE-DEPTH
    backpressure gate that complements the token-budget gate ``pool_over_budget_by_skill``.

    The token gate backs a backlog off when its agent POOL is out of 24h headroom; this
    gate backs it off when the DISPATCH PIPE for that job_type is already saturated — e.g.
    ``fact_check`` jobs piling up 240s-timeouts on the contended hub GPU faster than they
    drain (#4536). Only rows created within ``window_minutes`` are counted, so a stuck
    'running' zombie older than the dispatch timeout can never permanently starve the lane.

    Cap is tunable via ``platform_settings[cap_key]`` (default 25). A cap <= 0 DISABLES the
    gate (always False) so it can be turned off without a deploy.

    Fail-OPEN: missing data / any error → ``False`` (never gate).
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s",
                (cap_key,),
            )
            _row = cur.fetchone()
            try:
                cap = int(float(_row["value"])) if _row and _row.get("value") not in (None, "") else default_cap
            except (TypeError, ValueError):
                cap = default_cap
            if cap <= 0:
                return False  # gate disabled via settings
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM bridge_jobs
                WHERE job_type = %s
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                  AND created_at > NOW() - make_interval(mins => %s)
                """,
                (job_type, window_minutes),
            )
            r = cur.fetchone()
        in_flight = int(r["n"]) if r and r.get("n") is not None else 0
        over = in_flight >= cap
        if over:
            logger.info(
                "[BacklogBackpressure] gating job_type=%s: in-flight %d >= cap %d (key=%s, window=%dm)",
                job_type,
                in_flight,
                cap,
                cap_key,
                window_minutes,
            )
        return over
    except Exception:
        logger.warning(
            "[BacklogBackpressure] in-flight check failed for job_type=%s key=%s; not gating",
            job_type,
            cap_key,
            exc_info=True,
        )
        return False


# The 7B "lanes" that all contend for the hub's single 8GB GPU — which can't hold a 7B
# beside the warm small set, so they run on hub CPU. A concurrent BURST of these saturates
# the hub → 240s-timeout cascade that also starves F.O.R.G.E. reviews (RCA KB #278774).
# These are the DEFAULT baseline; a future 7B producer can be ADDED to the aggregate count
# via platform_settings[HUB_LANES_KEY] (CSV) with no deploy — see effective_hub_lanes().
HUB_CONTENDED_LANES = (
    "fact_check",
    "fact_check_backlog",
    "bias_analysis",
    "bias_backlog",
    "code_review",
    "geo_extraction",
    "analyze",
)

# platform_settings key holding ADDITIONAL contended-lane job_types (CSV) to fold into the
# aggregate count. bridge_jobs has no model column, so the AGGREGATE denominator must be
# job_type-scoped — this makes that scope tunable without a deploy. (The GATE side in
# department_dispatcher._execute_llm is separately generalized to _model_is_gpu_class(model),
# which auto-covers any future 7B producer regardless of this list — RCA KB #278774 f/u.)
HUB_LANES_KEY = "dispatch:hub_contended_lanes"


def effective_hub_lanes(extra_csv=None):
    """DEFAULT ``HUB_CONTENDED_LANES`` ∪ additive extras parsed from ``extra_csv``.

    Pure (no DB). ADDITIVE-ONLY: extras are unioned onto the defaults, never replace them,
    so a bad/empty setting can NEVER drop a known-critical lane from the count. Order-stable
    and de-duplicated. Called by ``hub_lane_over_cap`` with the live setting value.
    """
    extra = [t.strip() for t in str(extra_csv or "").split(",") if t.strip()]
    return list(dict.fromkeys(list(HUB_CONTENDED_LANES) + extra))


def reserved_cap_for(cap: int, reserve: int, mode: str, is_prioritised: bool) -> int:
    """Pure: the effective in-flight cap for an INCOMING 7B job under a mobility profile.

    Reserves ``reserve`` slots of the contended lane for the PRIORITISED domain by lowering
    the admission cap for NON-prioritised work while a diversion (``news``/``platform``) is
    active. This is what makes the A.R.M.A.D.A. buttons cause the favoured domain to actually
    RUN, not merely queue first (#5132 follow-up): the drain reorder put platform work at the
    HEAD of the queue, but a lane already saturated by news work had no free slot for it to
    EXECUTE in. Holding R slots open fixes that.

    - ``auto`` mode, OR a prioritised job → FULL ``cap`` (no change).
    - a non-prioritised job under a diversion → ``cap - reserve``.

    ``reserve`` is clamped to ``[0, cap-1]`` so a non-prioritised job ALWAYS keeps at least
    one slot — a diversion favours a domain, it never totally locks the other one out.
    """
    if mode not in ("news", "platform") or is_prioritised:
        return cap
    try:
        r = int(reserve)
    except (TypeError, ValueError):
        r = 0
    r = max(0, min(r, cap - 1))
    return cap - r


def hub_lane_over_cap(
    cap_key: str = "dispatch:hub_inflight_max",
    default_cap: int = 8,
    window_minutes: int = 10,
    capability: "Optional[str]" = None,
    module_id: "Optional[str]" = None,
    reserve_key: str = "dispatch:hub_reserve_slots",
    default_reserve: int = 3,
) -> bool:
    """True when the hub-contended 7B lanes ALREADY have >= cap in-flight ``bridge_jobs`` — an
    AGGREGATE admission gate for the shared hub CPU (complements per-job_type
    ``in_flight_over_cap``).

    fact_check / bias / code_review / geo / analyze all run 7B on the hub CPU (the 8GB M4000
    can't hold a 7B beside the warm small models). A concurrent burst thrashes the CPU so each
    job blows past the 240s dispatch timeout, cascading into queue congestion that also starves
    F.O.R.G.E. reviews (RCA KB #278774). Capping the AGGREGATE in-flight count sheds the burst
    so the admitted jobs actually finish.

    Cap tunable via ``platform_settings[cap_key]`` (default 8 — set GENEROUSLY so it only fires
    under genuine saturation). cap <= 0 DISABLES the gate (always False) with no deploy. Only
    rows within ``window_minutes`` are counted, so a stuck zombie can never permanently gate.

    The counted lane set = ``HUB_CONTENDED_LANES`` ∪ ``platform_settings[HUB_LANES_KEY]`` (an
    ADDITIVE CSV) — a future 7B producer joins the aggregate with no deploy (bridge_jobs has no
    model column, so the denominator must be job_type-scoped). See ``effective_hub_lanes``.

    Fail-OPEN: missing data / any error → ``False`` (never gate).
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (cap_key,))
            _row = cur.fetchone()
            try:
                cap = int(float(_row["value"])) if _row and _row.get("value") not in (None, "") else default_cap
            except (TypeError, ValueError):
                cap = default_cap
            if cap <= 0:
                return False  # disabled via settings
            # Effective lane list = DEFAULT tuple ∪ additive CSV setting (no deploy needed).
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (HUB_LANES_KEY,))
            _lrow = cur.fetchone()
            _extra = _lrow["value"] if _lrow and _lrow.get("value") not in (None, "") else None
            lanes = effective_hub_lanes(_extra)
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM bridge_jobs
                WHERE job_type = ANY(%s)
                  AND status NOT IN ('completed', 'failed', 'cancelled')
                  AND created_at > NOW() - make_interval(mins => %s)
                """,
                (lanes, window_minutes),
            )
            r = cur.fetchone()
            in_flight = int(r["n"]) if r and r.get("n") is not None else 0

            # SLOT RESERVATION (#5132 f/u). Blanket callers (no capability/module_id — e.g.
            # the GPU-overflow escalation at department_dispatcher ~L964) keep the FULL cap,
            # so their behaviour is byte-identical. A classified caller (the hub shed-gate at
            # ~L4003) computes an EFFECTIVE cap: while a diversion is active, NON-prioritised
            # 7B work is admitted only up to cap-reserve, holding `reserve` slots open for the
            # favoured domain to actually execute in. See reserved_cap_for().
            eff_cap = cap
            classified = capability is not None or module_id is not None
            _mode = "auto"
            if classified:
                try:
                    from services.fleet_dispatch_profile import (
                        get_dispatch_mode,
                        queue_row_gets_priority,
                    )

                    _mode = get_dispatch_mode()
                    if _mode in ("news", "platform"):
                        cur.execute("SELECT value FROM platform_settings WHERE key = %s", (reserve_key,))
                        _rrow = cur.fetchone()
                        try:
                            reserve = (
                                int(float(_rrow["value"]))
                                if _rrow and _rrow.get("value") not in (None, "")
                                else default_reserve
                            )
                        except (TypeError, ValueError):
                            reserve = default_reserve
                        _prioritised = queue_row_gets_priority(capability, module_id, _mode)
                        eff_cap = reserved_cap_for(cap, reserve, _mode, _prioritised)
                except Exception:
                    eff_cap = cap  # fail-open to blanket cap on any classification error

            over = in_flight >= eff_cap
            if over:
                logger.info(
                    "[HubAdmission] gating hub 7B lane: in-flight %d >= eff_cap %d "
                    "(base=%d mode=%s cap_key=%s cap=%s window=%dm)",
                    in_flight,
                    eff_cap,
                    cap,
                    _mode,
                    cap_key,
                    capability,
                    window_minutes,
                )
            return over
    except Exception:
        logger.warning("[HubAdmission] in-flight check failed; not gating", exc_info=True)
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
        """
        + welfare_token_filter_sql("tel")  # #5319: warmups never bill a welfare ledger
        + """
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
          AND a.org_id IS NULL   -- internal agents only; client (AaaS) load must not pollute the org CREED welfare score (#4590)
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
          AND a.org_id IS NULL   -- internal agents only; a client (AaaS) sole agent is not OUR staffing gap (#4590)
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
