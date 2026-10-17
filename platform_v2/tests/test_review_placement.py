"""Readiness admission uses read-only status, never warm-up or inference."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from services import review_placement as policy
from tools.repair_bay.services import pr_diff_analyzer as analyzer


MODEL = "gemma3:12b"


def node(**changes):
    result = {
        "node_id": "fixture-gpu",
        "status": "online",
        "is_active": True,
        "last_heartbeat": datetime.now(timezone.utc),
        "gpu_available": True,
        "gpu_vram_gb": 12,
        "ram_gb": 128,
        "ollama_available": True,
        "mesh_ip": "100.64.0.3",
        "port": 11434,
        "current_load": 0,
        "max_concurrent": 2,
        "extra_capabilities": {"ollama_models": [MODEL]},
        "deployment_mode": "starship",
        "score": 1.0,
    }
    result.update(changes)
    return result


@pytest.fixture
def resident(monkeypatch):
    service = Mock()
    service.check_loaded_models.return_value = [{"name": MODEL, "size": 8_000_000_000, "size_vram": 8_000_000_000}]
    factory = Mock(return_value=service)
    monkeypatch.setattr(policy, "ModelService", factory)
    monkeypatch.setattr(policy, "can_node_run_model", lambda n, m: True)
    monkeypatch.setattr(policy, "score_node_for_model", lambda n, m: n["score"])
    return service, factory


def test_gpu_resident_model_is_admitted_and_status_uses_mesh(resident):
    service, factory = resident
    assert policy.ready_review_nodes([node()], MODEL) == ["fixture-gpu"]
    factory.assert_called_once_with(ollama_host="http://100.64.0.3:11434")
    service.check_loaded_models.assert_called_once_with()
    service.ensure_model_ready.assert_not_called()
    service.load_model.assert_not_called()


@pytest.mark.parametrize(
    "vram,size",
    [
        (0, 8_000_000_000),
        (1_000_000_000, 8_000_000_000),
        (0, 0),
        (float("nan"), 8_000_000_000),
        (float("inf"), 8_000_000_000),
    ],
)
def test_cpu_or_unknown_offload_is_not_large_window_readiness(resident, vram, size):
    service, _ = resident
    service.check_loaded_models.return_value = [{"name": MODEL, "size": size, "size_vram": vram}]
    assert policy.ready_review_nodes([node()], MODEL) == []


def test_pulled_but_cold_model_is_not_ready(resident):
    service, _ = resident
    service.check_loaded_models.return_value = []
    assert policy.ready_review_nodes([node()], MODEL) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"last_heartbeat": None},
        {"last_heartbeat": datetime.now(timezone.utc) - timedelta(minutes=10)},
        {"status": "offline"},
        {"is_active": False},
        {"gpu_available": False},
        {"ollama_available": False},
        {"current_load": 2},
        {"max_concurrent": 0},
        {"extra_capabilities": {}},
        {"extra_capabilities": {"ollama_models": []}},
        {"extra_capabilities": {"ollama_models": "unknown"}},
        {"extra_capabilities": {"ollama_models": ["other:7b"]}},
    ],
)
def test_unqualified_nodes_are_rejected_before_network_probe(resident, changes):
    _, factory = resident
    assert policy.ready_review_nodes([node(**changes)], MODEL) == []
    factory.assert_not_called()


def test_hardware_rest_and_capacity_are_preserved(resident, monkeypatch):
    assert policy.ready_review_nodes([node()], MODEL, starships_undocked=True) == []
    monkeypatch.setattr(policy, "can_node_run_model", lambda n, m: False)
    assert policy.ready_review_nodes([node()], MODEL) == []


def test_rank_eligible_nodes_by_existing_resource_score_not_query_order(resident):
    rows = [node(node_id="slow", score=1), node(node_id="fast", score=3)]
    assert policy.ready_review_nodes(rows, MODEL) == ["fast", "slow"]


def test_one_broken_node_does_not_hide_other_ready_nodes(resident):
    rows = [node(node_id="bad", port="invalid"), node(node_id="good")]
    assert policy.ready_review_nodes(rows, MODEL) == ["good"]


def test_generic_score_cannot_undo_observed_gpu_readiness(resident, monkeypatch):
    monkeypatch.setattr(policy, "score_node_for_model", lambda n, m: None if n["node_id"] == "last" else 1.0)
    assert policy.ready_review_nodes([node(node_id="last")], MODEL) == ["last"]
    assert policy.ready_review_nodes([node(node_id="last"), node(node_id="preferred")], MODEL) == ["preferred", "last"]


def test_readiness_uses_supported_vpn_fallback(resident, monkeypatch):
    _, factory = resident
    cur = Mock()
    cur.fetchall.return_value = [node(mesh_ip=None, vpn_ip="100.64.0.6", hostname=None)]

    @contextmanager
    def db(**kwargs):
        yield Mock(), cur

    monkeypatch.setattr("database.get_db_cursor", db)
    monkeypatch.setattr("tools.department_hq.fleet_helpers.is_starships_undocked", lambda: False)
    monkeypatch.setattr(analyzer, "_TIER3_PLACEABLE_CACHE", {"at": 0, "nodes": None})
    assert analyzer._nodes_for_model(MODEL) == ["fixture-gpu"]
    assert "vpn_ip" in cur.execute.call_args.args[0]
    factory.assert_called_once_with(ollama_host="http://100.64.0.6:11434")


def test_ram_fit_cpu_runner_no_longer_triggers_strong_model_override(resident, monkeypatch):
    service, _ = resident
    service.check_loaded_models.return_value = [{"name": MODEL, "size": 8_000_000_000, "size_vram": 0}]
    cur = Mock()
    cur.fetchall.return_value = [node()]

    @contextmanager
    def db(**kwargs):
        yield Mock(), cur

    monkeypatch.setattr("database.get_db_cursor", db)
    monkeypatch.setattr("tools.department_hq.fleet_helpers.is_starships_undocked", lambda: False)
    monkeypatch.setattr(analyzer, "_TIER3_PLACEABLE_CACHE", {"at": 0, "nodes": None})
    monkeypatch.setattr("tools.repair_bay.services.pr_review_service.classify_pr_tier", lambda *_: 3)
    assert analyzer._nodes_for_model(MODEL) == []
    assert analyzer._review_is_strong({"title": "large high-risk change"}, "x" * 20_000) is False


def test_ready_strong_model_still_available(resident, monkeypatch):
    monkeypatch.setattr(analyzer, "_nodes_for_model", lambda *_: ["fixture-gpu"])
    monkeypatch.setattr("tools.repair_bay.services.pr_review_service.classify_pr_tier", lambda *_: 3)
    assert analyzer._review_is_strong({"title": "high risk"}, "x" * 20_000) is True
