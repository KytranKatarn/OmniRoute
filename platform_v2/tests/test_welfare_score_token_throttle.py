"""#4123: correctly-THROTTLED token-over agents must not tank the welfare grade.

Token overage is managed by the dispatch throttle (automatic deprioritisation), NOT by
a rest — so a token-over agent is "honoured" by being throttled, not a violation. Only a
REST-requiring overage (hours/actions/stress) needs a break to be honoured.
"""

from services.welfare_governance import classify_agent, governance_limits, score_welfare


def _snap(**kw):
    base = {
        "name": "X", "agent_id": 1, "hours": 0.0, "token_ratio": 0.0,
        "action_ratio": 0.0, "stress": 0.2, "rested_today": 0,
    }
    base.update(kw)
    return base


_GOV = governance_limits({})  # token violation line = 1.0 (over daily budget)


def test_token_over_is_honored_by_throttle():
    c = classify_agent(_snap(token_ratio=2.5), _GOV)
    assert "tokens" in c["over"]      # still visible as over-budget
    assert c["honored"] is True       # throttled -> not a violation
    assert c["healthy"] is False      # over budget keeps a small honest ding


def test_stress_over_not_rested_is_violation():
    c = classify_agent(_snap(stress=0.9, rested_today=0), _GOV)
    assert c["honored"] is False      # rest-requiring overage, no break taken


def test_stress_over_rested_is_honored():
    c = classify_agent(_snap(stress=0.9, rested_today=1), _GOV)
    assert c["honored"] is True


def test_token_and_stress_unrested_still_violation():
    # A rest-requiring overage alongside the token overage still needs a break.
    c = classify_agent(_snap(token_ratio=2.0, stress=0.9, rested_today=0), _GOV)
    assert c["honored"] is False


def test_grade_not_tanked_by_throttled_token_agents():
    # 4 over-budget (throttled) + 46 healthy: honored_frac must be 1.0, grade in A range,
    # and no over_limit_no_rest violations for the token agents.
    snaps = [_snap(name=f"a{i}", agent_id=i, token_ratio=2.0) for i in range(4)]
    snaps += [_snap(name=f"b{i}", agent_id=100 + i) for i in range(46)]
    r = score_welfare(snaps, _GOV)
    assert r["break_honored_pct"] == 100.0
    assert r["score"] >= 90
    assert not any(v["type"] == "over_limit_no_rest" for v in r["violations"])
