"""Tests for job_resume_handlers (#4499) — concrete consciousness-backlog resume."""

import sys
import types

import services.job_resume_handlers as h
import services.job_recovery_service as jr


def _inject_trigger(monkeypatch, fn):
    """Make `from tools.consciousness.processing_routes import _trigger_loop_op` resolve to fn."""
    fake = types.ModuleType("tools.consciousness.processing_routes")
    fake._trigger_loop_op = fn
    monkeypatch.setitem(sys.modules, "tools.consciousness.processing_routes", fake)


def test_consciousness_backlog_maps_jobtype_to_op(monkeypatch):
    calls = []
    _inject_trigger(monkeypatch, lambda op: calls.append(op))
    res = h._resume_consciousness_backlog(None, {"job_type": "batch_embedding", "id": 1})
    assert res["executed"] is True
    assert calls == ["embedding"]


def test_consciousness_backlog_all_three_ops(monkeypatch):
    seen = []
    _inject_trigger(monkeypatch, lambda op: seen.append(op))
    for jt, op in (("batch_analysis", "analysis"), ("translate_batch", "translate")):
        h._resume_consciousness_backlog(None, {"job_type": jt, "id": 1})
    assert seen == ["analysis", "translate"]


def test_consciousness_backlog_unknown_jobtype_is_honest():
    res = h._resume_consciousness_backlog(None, {"job_type": "not_a_batch", "id": 1})
    assert res["executed"] is False
    assert "unknown" in res["detail"].lower()


def test_consciousness_backlog_trigger_failure_is_honest(monkeypatch):
    def boom(op):
        raise RuntimeError("ollama down")

    _inject_trigger(monkeypatch, boom)
    res = h._resume_consciousness_backlog(None, {"job_type": "batch_embedding", "id": 1})
    assert res["executed"] is False  # never fake success


def test_three_batch_types_registered_on_import():
    for jt in ("batch_embedding", "batch_analysis", "translate_batch"):
        assert jr.RESUME_HANDLERS.get(jt) is h._resume_consciousness_backlog
