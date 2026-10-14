"""Readiness distinguishes model RAM budget from single-card GPU headroom."""

from unittest.mock import Mock

import pytest
from services.model_service import ModelService


@pytest.fixture
def service(monkeypatch):
    svc = ModelService()
    monkeypatch.setattr(svc, "get_available_ram", lambda: 97.0)
    monkeypatch.setattr(svc, "get_gpu_fit_budget", lambda: 7.0)
    return svc


def test_gemma_reports_gpu_shortage_not_ram(service):
    status = service.capacity_status(7.2)
    assert status["blocked_reason"] == "gpu_headroom"
    assert status["gpu_required_gb"] == pytest.approx(10.08)
    assert status["ram_available_budget_gb"] == 97


def test_small_cpu_models_do_not_require_gpu_space(service, monkeypatch):
    monkeypatch.setattr(service, "get_gpu_fit_budget", lambda: 0.0)
    assert service.capacity_status(1.3)["ready"] is True


def test_ram_budget_shortage_is_explicit(service, monkeypatch):
    monkeypatch.setattr(service, "get_available_ram", lambda: 1.0)
    monkeypatch.setattr(service, "get_gpu_fit_budget", lambda: 12.0)
    assert service.capacity_status(7.2)["blocked_reason"] == "ram_budget"


def test_unavailable_capacity_fails_closed(service, monkeypatch):
    monkeypatch.setattr(service, "get_gpu_fit_budget", Mock(side_effect=RuntimeError("fixture")))
    assert service.capacity_status(7.2) == {"ready": False, "blocked_reason": "capacity_unknown"}


def test_readiness_returns_diagnostics_without_attempting_load(service, monkeypatch, caplog):
    monkeypatch.setattr(service, "_fetch_ps", lambda *_: [])
    monkeypatch.setattr(service, "ensure_capacity", lambda *_: False)
    load = Mock()
    monkeypatch.setattr(service, "load_model", load)
    result = service._ensure_model_ready_locked("F.O.R.G.E.", "gemma3:12b", None, 0)
    assert result["ready"] is False and result["blocked_reason"] == "gpu_headroom"
    assert result["capacity"]["gpu_required_gb"] == pytest.approx(10.08)
    assert result["retry_after"] > 0
    assert "Capacity blocked" in caplog.text and "Not enough RAM" not in caplog.text
    load.assert_not_called()
