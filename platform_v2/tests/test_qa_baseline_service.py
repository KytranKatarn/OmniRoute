"""Unit tests for qa_baseline_service."""

from services import qa_baseline_service


def test_compute_baseline_returns_none_when_below_min_samples(monkeypatch):
    """Below 10 successful runs → no baseline (returns None, 0)."""
    fake_history = [120, 130, 125]  # only 3 samples
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_recent_response_times",
        lambda suite_id, test_name, limit: fake_history,
    )
    p95, count = qa_baseline_service.compute_baseline(suite_id=1, test_name="x")
    assert p95 is None
    assert count == 3


def test_compute_baseline_returns_p95_at_or_above_min_samples(monkeypatch):
    """At ≥10 samples → returns p95 of the window."""
    # 30 samples; p95 = 95th percentile
    fake_history = list(range(100, 130))  # [100..129]
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_recent_response_times",
        lambda suite_id, test_name, limit: fake_history,
    )
    p95, count = qa_baseline_service.compute_baseline(suite_id=1, test_name="x")
    assert count == 30
    # p95 of [100..129] under inclusive method: quantiles[94] = 127.55 → rounds to 128
    assert p95 == 128


def test_compute_baseline_uses_max_30_window(monkeypatch):
    """Window is capped at 30 most recent samples."""
    captured = {}

    def fake_fetch(suite_id, test_name, limit):
        captured["limit"] = limit
        return list(range(100, 200))[:limit]

    monkeypatch.setattr(qa_baseline_service, "_fetch_recent_response_times", fake_fetch)
    qa_baseline_service.compute_baseline(suite_id=1, test_name="x")
    assert captured["limit"] == 30


def test_check_regression_returns_false_when_no_baseline(monkeypatch):
    """If baseline doesn't exist (or below min_samples) → no regression."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda suite_id, test_name: None,
    )
    assert qa_baseline_service.check_regression(suite_id=1, test_name="x", observed_ms=99999, override_ms=None) is False


def test_check_regression_trips_at_2x_baseline(monkeypatch):
    """observed > 2× baseline → regression."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda suite_id, test_name: {"baseline_p95_ms": 100, "sample_count": 30},
    )
    assert qa_baseline_service.check_regression(1, "x", 250, override_ms=None) is True
    assert qa_baseline_service.check_regression(1, "x", 199, override_ms=None) is False
    assert qa_baseline_service.check_regression(1, "x", 200, override_ms=None) is False


def test_check_regression_uses_override_when_set(monkeypatch):
    """override_ms wins over auto-baseline."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda suite_id, test_name: {"baseline_p95_ms": 100, "sample_count": 30},
    )
    # observed below override threshold → no regression
    assert qa_baseline_service.check_regression(1, "x", 5000, override_ms=10000) is False
    # observed above override threshold → regression (regardless of auto-baseline)
    assert qa_baseline_service.check_regression(1, "x", 11000, override_ms=10000) is True


def test_check_regression_returns_false_when_baseline_undersampled(monkeypatch):
    """Baseline exists but sample_count < MIN_SAMPLES → False (mid-bootstrap)."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_get_baseline_record",
        lambda s, t: {"baseline_p95_ms": 100, "sample_count": 5},
    )
    assert qa_baseline_service.check_regression(1, "x", 99999, None) is False


def test_check_regression_swallows_exceptions(monkeypatch):
    """If anything inside throws, return False — never propagate."""

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(qa_baseline_service, "_get_baseline_record", boom)
    assert qa_baseline_service.check_regression(1, "x", 200, override_ms=None) is False


def test_decide_action_critical_trips_on_first_regression():
    """Critical-tagged test → 'rollback' on first regression in window."""
    assert qa_baseline_service.decide_action(is_critical=True, recent_regressions_count=1) == "rollback"


def test_decide_action_non_critical_flag_then_pause():
    """Non-critical: 1 regression → 'flag', 2+ in window → 'pause'."""
    assert qa_baseline_service.decide_action(is_critical=False, recent_regressions_count=1) == "flag"
    assert qa_baseline_service.decide_action(is_critical=False, recent_regressions_count=2) == "pause"
    assert qa_baseline_service.decide_action(is_critical=False, recent_regressions_count=3) == "pause"


def test_evaluate_post_deploy_no_pending_returns_none(monkeypatch):
    """No pending regressions for the run → 'none'."""
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_pending_regressions_for_run",
        lambda run_id: [],
    )
    assert qa_baseline_service.evaluate_post_deploy(run_id=1, proposal_id=1) == "none"


def test_evaluate_post_deploy_returns_strongest_action(monkeypatch):
    """Returns 'rollback' > 'pause' > 'flag' > 'none'."""
    pending = [
        {"id": 1, "suite_id": 1, "test_name": "a", "is_critical": False},
        {"id": 2, "suite_id": 1, "test_name": "b", "is_critical": True},
    ]
    monkeypatch.setattr(
        qa_baseline_service,
        "_fetch_pending_regressions_for_run",
        lambda run_id: pending,
    )
    monkeypatch.setattr(
        qa_baseline_service,
        "_count_recent_regressions",
        lambda suite_id, test_name: 1,
    )
    monkeypatch.setattr(
        qa_baseline_service,
        "_update_regression_action",
        lambda regression_id, action, proposal_id: None,
    )
    # critical 'rollback' wins over non-critical 'flag'
    assert qa_baseline_service.evaluate_post_deploy(run_id=1, proposal_id=1) == "rollback"


def test_evaluate_post_deploy_fails_open(monkeypatch):
    """Internal exception → return 'none' (fail-open)."""

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(qa_baseline_service, "_fetch_pending_regressions_for_run", boom)
    assert qa_baseline_service.evaluate_post_deploy(run_id=1, proposal_id=1) == "none"


def test_decide_action_count_zero_edge_cases():
    """Critical short-circuits regardless of count; non-critical with 0 → 'flag'."""
    assert qa_baseline_service.decide_action(is_critical=True, recent_regressions_count=0) == "rollback"
    assert qa_baseline_service.decide_action(is_critical=False, recent_regressions_count=0) == "flag"


def test_recompute_returns_count_of_baselines_updated(monkeypatch):
    """recompute_all_baselines returns int count of baselines updated."""
    fake_tests = [
        {"suite_id": 1, "test_name": "a"},
        {"suite_id": 1, "test_name": "b"},
        {"suite_id": 2, "test_name": "c"},
    ]
    monkeypatch.setattr(qa_baseline_service, "_fetch_distinct_tests", lambda: fake_tests)
    # Two tests have ≥10 samples (return p95), one doesn't (returns None)
    monkeypatch.setattr(
        qa_baseline_service,
        "compute_baseline",
        lambda sid, tn: (150, 30) if tn != "c" else (None, 5),
    )
    upserted = []
    monkeypatch.setattr(
        qa_baseline_service,
        "_upsert_baseline",
        lambda sid, tn, p95, count: upserted.append((sid, tn, p95, count)),
    )
    count = qa_baseline_service.recompute_all_baselines()
    assert count == 2  # only "a" and "b" had baselines computed
    assert ("c",) not in [(t,) for _, t, _, _ in upserted]  # c never upserted
    assert len(upserted) == 2


# ---------------------------------------------------------------------------
# Task 6: YAML extract_perf_flags — opt-in critical + baseline_ms_override
# ---------------------------------------------------------------------------


def test_yaml_parser_extracts_critical_and_override():
    """qa_spec_runner exposes critical + baseline_ms_override on test execution."""
    from services import qa_spec_runner

    test_entry = {
        "name": "homepage",
        "type": "page_load",
        "url": "/",
        "critical": True,
        "baseline_ms_override": 5000,
    }
    flags = qa_spec_runner.extract_perf_flags(test_entry)
    assert flags["critical"] is True
    assert flags["baseline_ms_override"] == 5000


def test_yaml_parser_defaults_when_perf_flags_missing():
    """Missing fields → critical=False, override=None."""
    from services import qa_spec_runner

    test_entry = {"name": "x", "type": "page_load", "url": "/"}
    flags = qa_spec_runner.extract_perf_flags(test_entry)
    assert flags["critical"] is False
    assert flags["baseline_ms_override"] is None


def test_yaml_parser_drops_invalid_override():
    """Invalid baseline_ms_override (string, negative) → None + warning."""
    from services import qa_spec_runner

    bad_string = {"name": "x", "type": "page_load", "url": "/", "baseline_ms_override": "fast"}
    bad_negative = {"name": "x", "type": "page_load", "url": "/", "baseline_ms_override": -100}
    assert qa_spec_runner.extract_perf_flags(bad_string)["baseline_ms_override"] is None
    assert qa_spec_runner.extract_perf_flags(bad_negative)["baseline_ms_override"] is None
