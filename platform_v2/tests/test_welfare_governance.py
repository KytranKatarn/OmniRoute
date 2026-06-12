"""Unit tests for pure welfare-governance scoring (project #379 Phase 4).

score_welfare / recommend / classify_agent are pure (no DB) → run on the host.
"""

import os

from services.welfare_governance import (
    classify_agent,
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
    c = classify_agent(_agent("NO_REST", tok=0.76, rested=0), BC)
    assert c["needs_break"] and not c["honored"]


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
    # 4 healthy + 1 over-and-not-rested: honored 0/1=0 -> 0.6*0.8 = 0.48 -> 48
    snaps = [_agent(f"a{i}", tok=0.1) for i in range(4)] + [_agent("X", tok=0.8, rested=0)]
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


# --- service wiring guard ---------------------------------------------------


def test_service_runs_pure_scorer_and_emits_creed_events():
    p = os.path.join(os.path.dirname(__file__), "..", "services", "welfare_governance_service.py")
    src = open(p, encoding="utf-8").read()
    assert "score_welfare(" in src and "recommend(" in src
    assert "emit_event(" in src, "violations must emit C.R.E.E.D. governance events"
    assert "agent_welfare_scores" in src, "must persist the score snapshot"


def test_job_registered_in_jobs():
    p = os.path.join(os.path.dirname(__file__), "..", "tools", "department_hq", "jobs.py")
    src = open(p, encoding="utf-8").read()
    assert "creed_welfare_governance" in src, "welfare-governance job must be registered"
