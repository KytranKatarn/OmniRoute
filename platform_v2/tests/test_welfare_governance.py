"""Unit tests for pure welfare-governance scoring (project #379 Phase 4).

score_welfare / recommend / classify_agent are pure (no DB) → run on the host.
"""

import os

from services.welfare_governance import (
    GOVERNANCE_TOKEN_LIMIT,
    classify_agent,
    governance_limits,
    grade_for,
    recommend,
    score_welfare,
)

# Break thresholds matching the live calibrated platform_settings.
BC = {"hours_cap": 4.0, "token_pct": 0.60, "action_pct": 0.90, "stress": 0.45}


def _agent(name, hours=0.0, tok=0.0, act=0.0, stress=0.0, rested=0):
    return {
        "name": name,
        "agent_id": hash(name) % 1000,
        "hours": hours,
        "token_ratio": tok,
        "action_ratio": act,
        "stress": stress,
        "rested_today": rested,
    }


# --- classify_agent ---------------------------------------------------------


def test_healthy_agent_is_not_over_anything():
    c = classify_agent(_agent("OK", hours=1, tok=0.2, act=0.1, stress=0.2), BC)
    assert c["over"] == [] and c["healthy"] and c["honored"]


def test_over_tokens_flagged_and_needs_break():
    c = classify_agent(_agent("HOT", tok=0.76), BC)
    assert c["over"] == ["tokens"] and c["needs_break"] and not c["healthy"]


def test_over_but_rested_is_honored():
    c = classify_agent(_agent("DID_REST", tok=0.76, rested=1), BC)
    assert c["needs_break"] and c["honored"]  # break was given


def test_over_and_not_rested_is_unhonored():
    # A REST-requiring overage (stress) with no rest today is UNHONORED. Token
    # overage is throttle-managed/honored post-#4123 — see the token test below.
    c = classify_agent(_agent("NO_REST", stress=0.50, rested=0), BC)
    assert "stress" in c["over"] and c["needs_break"] and not c["honored"]


def test_string_metrics_coerced():
    c = classify_agent({"name": "S", "token_ratio": "0.9", "rested_today": "0"}, BC)
    assert "tokens" in c["over"]


# --- score_welfare ----------------------------------------------------------


def test_all_healthy_scores_100():
    snaps = [_agent(f"a{i}", tok=0.1) for i in range(5)]
    r = score_welfare(snaps, BC)
    assert r["score"] == 100 and r["grade"] == "A+"
    assert r["needed_break"] == 0 and r["violations"] == []


def test_empty_workforce_is_vacuously_perfect():
    r = score_welfare([], BC)
    assert r["score"] == 100 and r["active_agents"] == 0


def test_over_but_all_rested_keeps_score_high():
    # 4 healthy + 1 over-but-rested: healthy 4/5=0.8, honored 1/1=1.0 -> 0.6*0.8+0.4*1.0=0.88
    snaps = [_agent(f"a{i}", tok=0.1) for i in range(4)] + [_agent("R", tok=0.8, rested=1)]
    r = score_welfare(snaps, BC)
    assert r["score"] == 88
    assert r["needed_break"] == 1 and r["honored"] == 1 and r["violations"] == []


def test_unhonored_break_drops_score_and_logs_violation():
    # 4 healthy + 1 over-a-REST-dim-and-not-rested: honored 0/1=0 -> 0.6*0.8 = 0.48 -> 48.
    # Uses stress (a rest-requiring dim); token overage is throttle-honored post-#4123.
    snaps = [_agent(f"a{i}", tok=0.1) for i in range(4)] + [_agent("X", stress=0.50, rested=0)]
    r = score_welfare(snaps, BC)
    assert r["score"] == 48 and r["grade"] == "F"
    types = {v["type"] for v in r["violations"]}
    assert "over_limit_no_rest" in types


def test_over_hours_cap_emits_its_own_violation():
    snaps = [_agent("LONG", hours=5.0, rested=1)]  # honored, but still over hours cap
    r = score_welfare(snaps, BC)
    types = {v["type"] for v in r["violations"]}
    assert "over_hours_cap" in types  # logged even when rested


def test_grade_bands():
    assert grade_for(96) == "A+"
    assert grade_for(90) == "A"
    assert grade_for(72) == "C"
    assert grade_for(10) == "F"


# --- recommend --------------------------------------------------------------


def test_recommends_rebalance_when_idle_and_overloaded_coexist():
    snaps = [_agent("IDLE", tok=0.0, act=0.0), _agent("BUSY", tok=0.9, rested=0)]
    kinds = {r["kind"] for r in recommend(snaps, BC)}
    assert "rebalance_routing" in kinds


def test_recommends_raise_budget_when_over_tokens_after_rest():
    # the owner's gap: rested but still over budget
    snaps = [_agent("BIAS", tok=0.76, rested=1)]
    recs = recommend(snaps, BC)
    rb = [r for r in recs if r["kind"] == "raise_budget_or_throttle"]
    assert rb and "throttle" in rb[0]["detail"]


def test_recommends_breaks_not_honored_as_critical():
    snaps = [_agent("STUCK", stress=0.9, rested=0)]
    recs = recommend(snaps, BC)
    bnh = [r for r in recs if r["kind"] == "breaks_not_honored"]
    assert bnh and bnh[0]["severity"] == "critical"


def test_no_recommendations_when_everyone_healthy():
    snaps = [_agent(f"a{i}", tok=0.1) for i in range(3)]
    assert recommend(snaps, BC) == []


# --- staffing_gap: sole active agent over budget (#4090 part 3) -----------------


def test_recommends_staffing_gap_for_sole_over_budget_agent():
    # F.O.R.G.E. is over its 24h budget AND the only active agent for code_review (SPOF):
    # the throttle has no healthy peer to route to -> recommend reactivate/hire.
    forge = _agent("F.O.R.G.E.", tok=1.4)
    sole = [{"capability": "code_review", "agent_id": forge["agent_id"], "agent_name": "F.O.R.G.E."}]
    recs = recommend([forge], governance_limits(BC), sole_agent_capabilities=sole)
    gap = [r for r in recs if r["kind"] == "staffing_gap"]
    assert gap, "sole over-budget agent must raise a staffing_gap"
    assert "code_review" in gap[0]["capabilities"]
    assert gap[0]["agent_id"] == forge["agent_id"]
    assert gap[0]["severity"] == "warning"


def test_no_staffing_gap_when_sole_agent_under_budget():
    forge = _agent("F.O.R.G.E.", tok=0.3)  # well within budget
    sole = [{"capability": "code_review", "agent_id": forge["agent_id"], "agent_name": "F.O.R.G.E."}]
    recs = recommend([forge], governance_limits(BC), sole_agent_capabilities=sole)
    assert "staffing_gap" not in {r["kind"] for r in recs}


def test_no_staffing_gap_when_over_budget_agent_has_peers():
    # over budget but NOT a sole-agent capability -> it has active peers -> no gap
    over = _agent("V.E.R.I.F.Y.", tok=1.5)
    recs = recommend([over], governance_limits(BC), sole_agent_capabilities=[])
    assert "staffing_gap" not in {r["kind"] for r in recs}


def test_staffing_gap_aggregates_multiple_capabilities_per_agent():
    forge = _agent("F.O.R.G.E.", tok=1.4)
    sole = [
        {"capability": "code_review", "agent_id": forge["agent_id"], "agent_name": "F.O.R.G.E."},
        {"capability": "debug", "agent_id": forge["agent_id"], "agent_name": "F.O.R.G.E."},
    ]
    recs = recommend([forge], governance_limits(BC), sole_agent_capabilities=sole)
    gap = [r for r in recs if r["kind"] == "staffing_gap"]
    assert len(gap) == 1, "one aggregated rec per over-budget sole agent, not one per capability"
    assert set(gap[0]["capabilities"]) == {"code_review", "debug"}


# --- governance_limits: token violation at budget (1.0), not the break line ----


def test_governance_limits_raises_token_line_to_budget():
    gov = governance_limits(BC)
    assert gov["token_pct"] == GOVERNANCE_TOKEN_LIMIT == 1.0
    # other dimensions are untouched (keep their break lines)
    assert gov["hours_cap"] == BC["hours_cap"] and gov["stress"] == BC["stress"]


def test_agent_at_70pct_budget_is_a_break_concern_but_not_a_governance_violation():
    a = _agent("WARM", tok=0.70)
    # the break engine (0.60 line) would flag it...
    assert "tokens" in classify_agent(a, BC)["over"]
    # ...but governance (1.0 line) does NOT — it's within budget
    assert "tokens" not in classify_agent(a, governance_limits(BC))["over"]


def test_over_token_budget_is_throttle_honored_not_a_violation():
    # #4123 (ADR-004/005, "throttle, don't rest"): a token-over agent is OVER budget
    # and needs_break, but HONORED — the dispatch throttle manages it automatically,
    # so it is NOT an unhonored welfare violation (the 4 throttled fact-checkers).
    a = _agent("OVER", tok=1.30, rested=0)  # 130% of budget, like B.I.A.S. on 24h
    c = classify_agent(a, governance_limits(BC))
    assert "tokens" in c["over"] and c["needs_break"] and c["honored"]


def test_score_with_governance_limits_only_dings_over_budget():
    # 4 within budget (0.7) + 1 over budget unrested: under the 1.0 line only ONE is flagged
    snaps = [_agent(f"a{i}", tok=0.7) for i in range(4)] + [_agent("X", tok=1.2, rested=0)]
    r = score_welfare(snaps, governance_limits(BC))
    assert r["needed_break"] == 1  # not 5 — the 0.7 agents are within budget


# --- service wiring guard ---------------------------------------------------


def test_service_runs_pure_scorer_and_emits_creed_events():
    p = os.path.join(os.path.dirname(__file__), "..", "services", "welfare_governance_service.py")
    src = open(p, encoding="utf-8").read()
    assert "score_welfare(" in src and "recommend(" in src
    # Phase 3 (#379): emission moved into the dedicated per-dimension, de-duped
    # welfare_emit module — the service delegates via emit_welfare_snapshots.
    assert "emit_welfare_snapshots(" in src, "must emit C.R.E.E.D. welfare events"
    assert "agent_welfare_scores" in src, "must persist the score snapshot"
    assert "governance_limits(" in src, "must score against the budget (1.0) token line"
    assert "INTERVAL '24 hours'" in src, "token window must be 24h rolling (match K.I.N. tab)"
    assert "'ai', 'contractor'" in src, "welfare scope must include contractors (Codex)"


def test_welfare_emit_module_emits_welfare_category_not_accountability():
    """Phase 3 CATEGORY SWITCH guard: the welfare emitter must push
    category='welfare' (its own public pillar) and the dimension event_types the
    standalone welfare_engine resolves — NOT category='accountability'."""
    p = os.path.join(os.path.dirname(__file__), "..", "services", "welfare_emit.py")
    src = open(p, encoding="utf-8").read()
    assert 'WELFARE_CATEGORY = "welfare"' in src
    assert "emit_event(" in src, "welfare_emit is the actual C.R.E.E.D. emit site"
    for et in ("welfare_hours", "welfare_tokens", "welfare_actions", "welfare_stress"):
        assert et in src, f"must emit {et} event_type"
    assert "welfare_break_honored" in src and "welfare_break_violated" in src
    # The emit category constant must be 'welfare', never 'accountability'.
    assert 'category="accountability"' not in src
    assert "_CREED_CATEGORY" not in src, "no leftover accountability category constant"


def test_job_registered_in_jobs():
    p = os.path.join(os.path.dirname(__file__), "..", "tools", "department_hq", "jobs.py")
    src = open(p, encoding="utf-8").read()
    assert "creed_welfare_governance" in src, "welfare-governance job must be registered"
