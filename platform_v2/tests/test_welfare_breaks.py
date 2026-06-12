"""Unit tests for the multi-factor break decision (project #379 Phase 1).

decide_break() is pure (no DB), so these run directly on the host.
"""

from services.welfare_load import WELFARE_BREAK_DEFAULTS, decide_break


def test_no_break_when_all_under_thresholds():
    assert decide_break(hours=2.0, token_ratio=0.3, action_ratio=0.4, stress=0.45) is None


def test_hours_triggers_shift_rest():
    b = decide_break(hours=6.5, token_ratio=0.1, action_ratio=0.1, stress=0.1)
    assert b["break_type"] == "shift_rest" and b["dimension"] == "hours"
    assert b["duration_min"] == 60
    assert b["value"] == 6.5


def test_token_triggers_token_rest():
    b = decide_break(hours=1.0, token_ratio=0.95, action_ratio=0.1, stress=0.1)
    assert b["break_type"] == "token_rest" and b["dimension"] == "tokens"
    assert b["duration_min"] == 45


def test_action_triggers_action_rest():
    b = decide_break(hours=1.0, token_ratio=0.1, action_ratio=0.92, stress=0.1)
    assert b["break_type"] == "action_rest" and b["dimension"] == "actions"
    assert b["duration_min"] == 30


def test_stress_triggers_micro_rest():
    b = decide_break(hours=1.0, token_ratio=0.1, action_ratio=0.1, stress=0.65)
    assert b["break_type"] == "micro_rest" and b["dimension"] == "stress"
    assert b["duration_min"] == 15


def test_precedence_hours_beats_everything():
    b = decide_break(hours=7.0, token_ratio=0.99, action_ratio=0.99, stress=0.9)
    assert b["break_type"] == "shift_rest"


def test_precedence_token_beats_action_and_stress():
    b = decide_break(hours=1.0, token_ratio=0.95, action_ratio=0.99, stress=0.9)
    assert b["break_type"] == "token_rest"


def test_precedence_action_beats_stress():
    b = decide_break(hours=1.0, token_ratio=0.1, action_ratio=0.95, stress=0.9)
    assert b["break_type"] == "action_rest"


def test_none_metric_is_skipped_not_blocking():
    # hours unknown but tokens over -> still fires token_rest
    b = decide_break(hours=None, token_ratio=0.95, action_ratio=None, stress=None)
    assert b["break_type"] == "token_rest"
    # everything None -> no signal -> no break
    assert decide_break() is None


def test_exact_threshold_is_inclusive():
    assert decide_break(stress=WELFARE_BREAK_DEFAULTS["stress"]) is not None
    assert decide_break(token_ratio=WELFARE_BREAK_DEFAULTS["token_pct"]) is not None
    assert decide_break(hours=WELFARE_BREAK_DEFAULTS["hours_cap"])["break_type"] == "shift_rest"


def test_custom_cfg_overrides_defaults():
    cfg = {
        "hours_cap": 3.0,
        "token_pct": 0.5,
        "action_pct": 0.5,
        "stress": 0.3,
        "dur_min": {"shift_rest": 90, "token_rest": 45, "action_rest": 30, "micro_rest": 15},
    }
    b = decide_break(hours=3.5, cfg=cfg)
    assert b["break_type"] == "shift_rest" and b["duration_min"] == 90
    # default cap (6.0) would NOT trigger at hours=3.5
    assert decide_break(hours=3.5) is None


def test_string_metrics_coerced_safely():
    # platform_settings returns strings; _num coercion handles it
    b = decide_break(token_ratio="0.95")
    assert b["break_type"] == "token_rest"


def test_jobs_wires_multifactor_decide_break_with_correct_metrics():
    """Guard the K.I.N. auto-rest wiring: it must use decide_break over the CORRECT
    metrics (tokens from task_execution_log today; action = in-flight current_task_count,
    NOT the cumulative dispatch count that is the FIX-5 'cheap pings look overloaded' bug),
    and the old stress-only gate must be gone."""
    import os

    p = os.path.join(os.path.dirname(__file__), "..", "tools", "department_hq", "jobs.py")
    src = open(p, encoding="utf-8").read()
    assert "decide_break(" in src, "auto-rest must call decide_break"
    assert "break_candidates" in src
    assert "AS tokens_today" in src, "token use must come from task_execution_log, not tokens_used_today"
    assert 'action_ratio=(float(agent["current_task_count"]' in src, "action must be in-flight, not cumulative"
    assert "for agent in overloaded:" not in src, "old stress-only auto-rest gate must be removed"
