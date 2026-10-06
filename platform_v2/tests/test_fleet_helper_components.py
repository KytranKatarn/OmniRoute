"""Fleet helper extraction preserves caching, GPU accounting and node ownership."""

from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import psutil

from tools.department_hq import fleet_helpers as helpers
from services.code_issue_reconciler import finding_still_reproduces

GB = 1024**3


@pytest.fixture
def hardware(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(helpers, "_hw_capacity_cache", {"data": None, "time": 0})
    monkeypatch.setattr(helpers.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        psutil, "virtual_memory", lambda: SimpleNamespace(total=64 * GB, available=40 * GB, percent=37.5)
    )
    loaded = Mock(
        return_value=[
            {"name": "gpu:latest", "size": 4 * GB, "size_vram": 4 * GB},
            {"name": "split:latest", "size": 4 * GB, "size_vram": 2 * GB},
            {"name": "cpu:latest", "size": 2 * GB, "size_vram": 0},
        ]
    )
    monkeypatch.setattr(helpers, "_get_cached_ollama_ps", loaded)
    probe = Mock(
        return_value=SimpleNamespace(returncode=0, stdout="M4000,8192,1024,7168,GPU-A\nTITAN,12288,5120,7168,GPU-B\n")
    )
    monkeypatch.setattr(helpers.subprocess, "run", probe)
    comfy = Mock(
        return_value=SimpleNamespace(
            status_code=200, json=lambda: {"devices": [{"type": "cuda", "torch_vram_total": GB}]}
        )
    )
    monkeypatch.setattr(helpers.requests, "get", comfy)
    db = Mock(side_effect=AssertionError("loaded ComfyUI does not need checkpoint lookup"))
    monkeypatch.setattr(helpers, "get_db_cursor", db)
    return clock, loaded, probe, comfy, db


def test_capacity_keeps_multigpu_totals_and_cpu_gpu_split(hardware):
    result = helpers._get_cached_hw_capacity()
    assert result["gpu"]["gpu_count"] == 2
    assert result["gpu"]["vram_total_gb"] == 20
    assert result["gpu"]["vram_used_gb"] == 6
    assert result["gpu"]["largest_free_gb"] == 7
    assert [g["uuid"] for g in result["gpu"]["gpus"]] == ["GPU-A", "GPU-B"]
    assert [m["processor"] for m in result["gpu_models"]] == ["gpu", "split"]
    assert result["gpu_models"][1]["gpu_pct"] == 50
    assert result["cpu_models"][0]["processor"] == "cpu"
    assert result["models_ram_gb"] == 10 and result["models_loaded"] == 3
    assert result["ram"]["llm_budget_gb"] == 44.8 and result["ram"]["status"] == "green"
    assert result["gpu"]["comfyui_status"] == "loaded"
    hardware[-1].assert_not_called()


def test_cache_retains_identity_and_expires_at_thirty_seconds(hardware):
    clock, loaded, probe, comfy, _ = hardware
    first = helpers._get_cached_hw_capacity()
    clock[0] += 29
    assert helpers._get_cached_hw_capacity() is first
    assert loaded.call_count == probe.call_count == comfy.call_count == 1
    clock[0] += 1
    assert helpers._get_cached_hw_capacity() is not first
    assert loaded.call_count == probe.call_count == comfy.call_count == 2


def test_missing_gpu_probe_keeps_capacity_unknown(hardware):
    hardware[2].side_effect = FileNotFoundError("no GPU passthrough")
    result = helpers._get_cached_hw_capacity()
    assert result["gpu"]["total_known"] is False
    assert result["gpu"]["vram_total_gb"] is None
    assert result["gpu"]["usage_pct"] is None
    assert result["gpu"]["vram_used_gb"] == 6


def test_idle_comfy_checkpoint_lookup_uses_original_db_override(hardware, monkeypatch):
    hardware[3].return_value = SimpleNamespace(status_code=200, json=lambda: {"devices": []})
    calls = []

    @contextmanager
    def db(commit=False):
        calls.append(commit)
        cur = Mock()
        cur.fetchone.return_value = {"image_model": "sd_xl_base"}
        yield None, cur

    monkeypatch.setattr(helpers, "get_db_cursor", db)
    result = helpers._get_cached_hw_capacity()
    assert calls == [False]
    assert result["gpu"]["comfyui_reserved_gb"] == 6.5


@pytest.fixture
def nodes(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    columns = "node_id,node_name,deployment_mode,hostname,port,status,is_active,bridge_enabled,bridge_priority,gpu_model,gpu_vram_gb,cpu_model,cpu_cores,ram_gb,disk_gb,approval_status,last_heartbeat,client_version,node_role,mesh_status,mesh_last_seen,mesh_latency_ms,reachable_port,privacy_settings,registered_by".split(
        ","
    )
    conn.execute("CREATE TABLE remote_nodes (id INTEGER PRIMARY KEY, " + ",".join(columns) + ")")
    conn.executemany(
        "INSERT INTO remote_nodes (id,node_id,node_name,registered_by) VALUES (?,?,?,?)",
        [(1, "owned", "Owned", 42), (2, "foreign", "Foreign", 7), (3, "orphan", "Orphan", None)],
    )
    commits = []

    class Cursor:
        def execute(self, sql, params=()):
            self.cur = conn.execute(sql.replace("%s", "?").replace("::jsonb", ""), params)

        def fetchone(self):
            row = self.cur.fetchone()
            return dict(row) if row else None

        def fetchall(self):
            return [dict(row) for row in self.cur.fetchall()]

    @contextmanager
    def db(commit=False):
        commits.append(commit)
        yield conn, Cursor()
        if commit:
            conn.commit()

    monkeypatch.setattr(helpers, "get_db_cursor", db)
    yield conn, commits
    conn.close()


def test_user_list_excludes_foreign_nodes_and_keeps_unclaimed_visibility(nodes):
    assert {n["node_id"] for n in helpers._get_user_nodes(42)} == {"owned", "orphan"}
    assert {n["node_id"] for n in helpers._get_user_nodes(42, is_admin=True)} == {"owned", "foreign", "orphan"}
    assert nodes[1] == [False, False]


def test_node_lookup_cannot_claim_another_users_node(nodes):
    assert helpers._get_node_for_user("foreign", 42) is None
    assert helpers._get_node_for_user("owned", 42)["registered_by"] == 42
    assert helpers._get_node_for_user("orphan", 42)["registered_by"] == 42
    assert helpers._get_node_for_user("orphan", 7) is None
    assert nodes[1] == [True] * 4


def test_numeric_lookup_preserves_the_same_ownership_rules(nodes):
    assert helpers._get_node_for_user_by_int_id(2, 42) is None
    assert helpers._get_node_for_user_by_int_id(3, 42)["registered_by"] == 42
    assert helpers._get_node_for_user_by_int_id(3, 7) is None


def test_explicit_nonowner_lookup_keeps_legacy_behavior(nodes):
    assert helpers._get_node_for_user("foreign", 42, require_owner=False)["registered_by"] == 7


def test_model_assignment_keeps_db_parameters_and_return_count(monkeypatch):
    cursor = Mock()
    cursor.fetchall.return_value = [{"id": 1}, {"id": 2}]

    @contextmanager
    def db(commit=False):
        assert commit
        yield None, cursor

    monkeypatch.setattr(helpers, "get_db_cursor", db)
    assert helpers.auto_assign_agents_for_model("node-1", "qwen:7b") == 2
    assert cursor.execute.call_args.args[1] == ("node-1", "qwen:7b")


def test_model_assignment_failure_still_returns_zero(monkeypatch):
    monkeypatch.setattr(helpers, "get_db_cursor", Mock(side_effect=RuntimeError("database unavailable")))
    assert helpers.auto_assign_agents_for_model("node-1", "qwen:7b") == 0


def test_extraction_resolves_size_finding_without_creating_another():
    root = __import__("pathlib").Path(__file__).parents[1] / "tools/department_hq"
    for path in [
        root / "fleet_helpers.py",
        root / "services/fleet_hardware_capacity.py",
        root / "services/fleet_node_store.py",
    ]:
        assert finding_still_reproduces("LARGE_FILE historical size", path.read_text()) is False
