from pathlib import Path

import services.coordinator_lane as cl


def setup_function(_):
    cl._reset_cache()


def test_coordinator_capabilities_expected_set():
    assert cl.COORDINATOR_CAPABILITIES == frozenset({"classify", "sentiment", "tagging", "detect_language"})


def test_should_apply_floor_true_when_enabled_and_not_pinned(monkeypatch):
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: True)
    assert cl.should_apply_floor("classify", caller_pinned_model=False) is True


def test_should_apply_floor_false_when_caller_pinned(monkeypatch):
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: True)
    assert cl.should_apply_floor("classify", caller_pinned_model=True) is False


def test_should_apply_floor_false_for_non_coordinator_capability(monkeypatch):
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: True)
    assert cl.should_apply_floor("bias_analysis", caller_pinned_model=False) is False


def test_should_apply_floor_false_when_lane_disabled(monkeypatch):
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: False)
    assert cl.should_apply_floor("classify", caller_pinned_model=False) is False


def test_request_work_references_should_apply_floor():
    # tests/ is a direct child of platform_v2 (container /app) — resolve relative
    # to this file so the check works both on host and inside the container.
    dispatcher_path = (
        Path(__file__).resolve().parent.parent / "tools" / "department_hq" / "services" / "department_dispatcher.py"
    )
    assert "should_apply_floor" in dispatcher_path.read_text()
