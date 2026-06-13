"""Pure welfare-governance scoring (project #379 Phase 4).

E.T.H.O.S./C.R.E.E.D. govern agent welfare as a first-class accountability
concern: the ORGANISATION is graded on how it treats its AI workforce.

These functions are PURE — no DB, no I/O — so they unit-test directly and are
reusable by the C.R.E.E.D. dashboard, the /creed surface, and any future
LLM-narrated report. The DB gather + event emit live in
``welfare_governance_service.py``; the break thresholds come from
``welfare_load`` (the same numbers the break engine triggers on).

A snapshot is one active AI agent at sample time:
    {name, agent_id, hours, token_ratio, action_ratio, stress, rested_today, shift_state}
`*_ratio`/`stress`/`hours` mirror the break engine's metrics; `rested_today`
is the count of rest cycles started today (>=1 means a break was honoured).
"""

WELFARE_GOVERNANCE_DEFAULTS = {
    # score = 100 * (w_healthy * healthy_fraction + w_honored * honored_fraction)
    "w_healthy": 0.6,  # share of active agents currently within ALL welfare bounds
    "w_honored": 0.4,  # share of over-limit agents that actually got a break today
    "grade_bands": [
        (95, "A+"),
        (90, "A"),
        (85, "B+"),
        (80, "B"),
        (70, "C"),
        (60, "D"),
        (0, "F"),
    ],
    # idle = doing essentially nothing on every dimension (a routing problem, not a
    # welfare one — never papered over with a fake break; surfaced as a recommendation)
    "idle_token": 0.10,
    "idle_action": 0.10,
    "idle_stress": 0.20,
    "idle_hours": 0.50,
}

# Break-threshold fallbacks (mirror welfare_load.WELFARE_BREAK_DEFAULTS). Passed in
# live from platform_settings; duplicated here only so the pure module never imports DB.
_BREAK_FALLBACK = {"hours_cap": 6.0, "token_pct": 0.90, "action_pct": 0.90, "stress": 0.60}

# Governance grades the org on agents OVER their limit — not merely approaching it. The
# break thresholds (e.g. token 0.60) are "should take a proactive rest"; the governance
# VIOLATION line for tokens is the budget itself (1.0 = over daily budget), matching what
# the K.I.N. tab flags as "at limit". So governance classifies tokens against 1.0 while
# the break engine keeps the softer 0.60. (stress/hours/actions keep their break lines —
# an unrested high-stress/over-hours agent is a genuine welfare concern.)
GOVERNANCE_TOKEN_LIMIT = 1.0


def governance_limits(break_cfg=None):
    """The thresholds GOVERNANCE classifies against: break_cfg with the token line raised
    to the budget (GOVERNANCE_TOKEN_LIMIT). PURE. Pass the result as score_welfare /
    recommend's break_cfg so an agent at 70% of budget (which the engine would rest) is
    NOT counted as a welfare violation — only an over-budget (>=100%) agent is."""
    cfg = dict(break_cfg or {})
    cfg["token_pct"] = GOVERNANCE_TOKEN_LIMIT
    return cfg


def _num(value, default=0.0):
    """Coerce None / '' / strings (platform_settings returns text) to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def grade_for(score, cfg=None):
    # Fall back to the default bands when cfg is a PARTIAL config (e.g. governance_limits
    # only sets token_pct) — a non-empty cfg without grade_bands must not KeyError.
    bands = (cfg or {}).get("grade_bands") or WELFARE_GOVERNANCE_DEFAULTS["grade_bands"]
    for cutoff, label in bands:
        if score >= cutoff:
            return label
    return "F"


def classify_agent(snap, break_cfg=None):
    """Which welfare dimensions is this agent over-limit on, and is it healthy/honoured?

    healthy  = not over any dimension.
    honoured = healthy, OR rested at least once today (a break was given).
    """
    bc = {**_BREAK_FALLBACK, **(break_cfg or {})}
    over = []
    if _num(snap.get("hours")) >= _num(bc.get("hours_cap"), 6.0):
        over.append("hours")
    if _num(snap.get("token_ratio")) >= _num(bc.get("token_pct"), 0.90):
        over.append("tokens")
    if _num(snap.get("action_ratio")) >= _num(bc.get("action_pct"), 0.90):
        over.append("actions")
    if _num(snap.get("stress")) >= _num(bc.get("stress"), 0.60):
        over.append("stress")
    needs_break = bool(over)
    rested = _num(snap.get("rested_today")) >= 1
    return {
        "over": over,
        "needs_break": needs_break,
        "healthy": not needs_break,
        "honored": (not needs_break) or rested,
    }


def _is_idle(snap, cfg):
    return (
        _num(snap.get("token_ratio")) < cfg["idle_token"]
        and _num(snap.get("action_ratio")) < cfg["idle_action"]
        and _num(snap.get("stress")) < cfg["idle_stress"]
        and _num(snap.get("hours")) < cfg["idle_hours"]
    )


def score_welfare(snapshots, break_cfg=None, cfg=None):
    """0-100 welfare score over the active AI workforce + violation list.

    Score blends two fractions:
      healthy_fraction = (# agents within all bounds) / (# active agents)
      honored_fraction = (# over-limit agents that rested today) / (# over-limit agents)
                         (1.0 when nobody is over a limit — vacuously honoured)
    """
    cfg = {**WELFARE_GOVERNANCE_DEFAULTS, **(cfg or {})}
    snaps = list(snapshots or [])
    n = len(snaps)
    if n == 0:
        return {
            "score": 100,
            "grade": "A+",
            "healthy_pct": 100.0,
            "break_honored_pct": 100.0,
            "active_agents": 0,
            "needed_break": 0,
            "honored": 0,
            "violations": [],
        }
    classes = [(s, classify_agent(s, break_cfg)) for s in snaps]
    healthy = sum(1 for _, c in classes if c["healthy"])
    needed = [(s, c) for s, c in classes if c["needs_break"]]
    honored = sum(1 for _, c in needed if c["honored"])
    healthy_frac = healthy / n
    honored_frac = (honored / len(needed)) if needed else 1.0
    raw = cfg["w_healthy"] * healthy_frac + cfg["w_honored"] * honored_frac
    score = int(round(100 * raw))
    violations = []
    for s, c in needed:
        if not c["honored"]:
            violations.append(
                {
                    "agent": s.get("name"),
                    "agent_id": s.get("agent_id"),
                    "type": "over_limit_no_rest",
                    "dimensions": c["over"],
                }
            )
        if "hours" in c["over"]:
            violations.append(
                {
                    "agent": s.get("name"),
                    "agent_id": s.get("agent_id"),
                    "type": "over_hours_cap",
                    "dimensions": ["hours"],
                }
            )
    return {
        "score": score,
        "grade": grade_for(score, cfg),
        "healthy_pct": round(100 * healthy_frac, 1),
        "break_honored_pct": round(100 * honored_frac, 1),
        "active_agents": n,
        "needed_break": len(needed),
        "honored": honored,
        "violations": violations,
    }


# D3 (2026-06-13): the raw score above is an instantaneous snapshot — a single bad
# moment (one agent transiently over a limit when the daily job samples) tanks the
# whole grade. smooth_score is an exponentially-weighted moving average so the
# HEADLINE grade is steady. alpha in (0,1]: higher = more responsive to the latest
# reading, lower = steadier. Pure (no DB); the service supplies prev_ewma + alpha.
DEFAULT_SCORE_EWMA_ALPHA = 0.3


def smooth_score(raw_score, prev_ewma, alpha=DEFAULT_SCORE_EWMA_ALPHA):
    """EWMA-smoothed welfare score. prev_ewma None (first ever) -> raw verbatim."""
    raw = _num(raw_score)
    if prev_ewma is None:
        return round(raw, 2)
    a = min(max(_num(alpha, DEFAULT_SCORE_EWMA_ALPHA), 0.01), 1.0)
    return round(a * raw + (1.0 - a) * _num(prev_ewma), 2)


def recommend(snapshots, break_cfg=None, cfg=None, sole_agent_capabilities=None):
    """Generated improvement recommendations ("aim for best score") — deterministic,
    rule-based v1. Each item: {kind, severity, detail}.

    ``sole_agent_capabilities`` (optional) is a list of
    ``{capability, agent_id, agent_name}`` for capabilities served by exactly ONE
    active agent (a single point of failure). When that agent is over its token
    budget the throttle has no healthy peer to route to, so we recommend
    reactivating a bench specialist or hiring a backup (#4090 part 3)."""
    cfg = {**WELFARE_GOVERNANCE_DEFAULTS, **(cfg or {})}
    bc = {**_BREAK_FALLBACK, **(break_cfg or {})}
    snaps = list(snapshots or [])
    classes = [(s, classify_agent(s, break_cfg)) for s in snaps]
    overloaded = [s for s, c in classes if c["needs_break"]]
    idle = [s for s in snaps if _is_idle(s, cfg)]
    recs = []

    # 1. idle vs overloaded imbalance — a dispatcher ROUTING gap, not a welfare one.
    if overloaded and idle:
        recs.append(
            {
                "kind": "rebalance_routing",
                "severity": "warning",
                "detail": (
                    f"{len(idle)} agent(s) idle while {len(overloaded)} over a welfare "
                    "limit — dispatcher routing gap; rebalance load across the fleet."
                ),
            }
        )

    # 2. over token budget AFTER already resting — the gap the owner spotted: a
    # token_rest pauses but does NOT lower cumulative daily tokens.
    for s, c in classes:
        if "tokens" in c["over"] and _num(s.get("rested_today")) >= 1:
            recs.append(
                {
                    "kind": "raise_budget_or_throttle",
                    "severity": "warning",
                    "detail": (
                        f"{s.get('name')} is over token budget after resting "
                        f"{int(_num(s.get('rested_today')))}x today — a token_rest does "
                        "not lower daily tokens; raise its budget or throttle dispatch."
                    ),
                }
            )

    # 3. over a limit but NO break taken — the engine isn't honouring the trigger.
    unhonored = [s for s, c in classes if c["needs_break"] and not c["honored"]]
    if unhonored:
        names = ", ".join(str(s.get("name")) for s in unhonored[:6])
        recs.append(
            {
                "kind": "breaks_not_honored",
                "severity": "critical",
                "detail": (
                    f"{len(unhonored)} agent(s) over a limit have not rested today "
                    f"({names}) — check kin_workload_monitor + dispatch_zombie_reaper."
                ),
            }
        )

    # 4. over the consecutive-hours cap specifically — enforce a shift_rest.
    for s, c in classes:
        if "hours" in c["over"]:
            recs.append(
                {
                    "kind": "over_hours_cap",
                    "severity": "warning",
                    "detail": (
                        f"{s.get('name')} exceeded the {bc.get('hours_cap')}h compute " "cap — enforce a shift_rest."
                    ),
                }
            )

    # 5. staffing SPOF — a capability whose ONLY active agent is over its token budget.
    # The dispatch throttle routes around an over-budget agent, but here there is no peer
    # to route TO, so work either waits or last-resorts back to the exhausted agent.
    # Recommend reactivating a bench specialist or hiring a backup (propose_hire is gated;
    # this only surfaces the gap). Aggregate one rec per agent across its solo capabilities.
    if sole_agent_capabilities:
        over_budget = {s.get("agent_id"): s.get("name") for s, c in classes if "tokens" in c["over"]}
        by_agent = {}  # agent_id -> [capability, ...]
        names = {}
        for entry in sole_agent_capabilities:
            aid = entry.get("agent_id")
            cap = entry.get("capability")
            if aid in over_budget and cap:
                by_agent.setdefault(aid, []).append(cap)
                names[aid] = entry.get("agent_name") or over_budget[aid]
        for aid, caps in by_agent.items():
            caps_sorted = sorted(set(caps))
            recs.append(
                {
                    "kind": "staffing_gap",
                    "severity": "warning",
                    "detail": (
                        f"{names[aid]} is the only active agent for {len(caps_sorted)} "
                        f"capability(ies) ({', '.join(caps_sorted[:6])}) and is over its 24h "
                        "token budget — the throttle has no healthy peer to route to; "
                        "reactivate a bench specialist or hire a backup (propose_hire)."
                    ),
                    "agent_id": aid,
                    "capabilities": caps_sorted,
                }
            )

    return recs
