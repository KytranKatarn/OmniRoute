"""Completion orchestration calls the authenticated serving process without redirects."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from services import planned_repair_completion as service


@pytest.fixture
def serving(monkeypatch):
    monkeypatch.setenv("PLATFORM_INTERNAL_URL", "http://100.64.0.4:3000")
    monkeypatch.setenv("INTERNAL_API_KEY", "test-only")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"success": True, "verified": True})

    monkeypatch.setattr(service.requests, "post", post)
    return calls


def test_scheduler_calls_web_authority(serving):
    assert service.request_serving_verification(19)["verified"]
    url, args = serving[0]
    assert url == "http://100.64.0.4:3000/api/internal/repair/proposals/19/verify"
    assert args == {"headers": {"Authorization": "Bearer test-only"}, "timeout": 15, "allow_redirects": False}


@pytest.mark.parametrize(
    "base",
    [
        "https://example.com",
        "http://100.64.0.4.evil.test",
        "http://user:secret@100.64.0.4",
        "http://100.64.0.4/path",
        "http://100.64.0.999",
        "file:///tmp/x",
    ],
)
def test_credential_destination_is_validated(serving, monkeypatch, base):
    monkeypatch.setenv("PLATFORM_INTERNAL_URL", base)
    with pytest.raises(ValueError):
        service.request_serving_verification(19)
    assert serving == []


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_http_failure_never_proves_completion(serving, monkeypatch, status):
    monkeypatch.setattr(service.requests, "post", lambda *a, **k: SimpleNamespace(status_code=status))
    with pytest.raises(ValueError):
        service.request_serving_verification(19)


def test_missing_config_fails_closed(serving, monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY")
    with pytest.raises(ValueError):
        service.request_serving_verification(19)
    assert serving == []


@pytest.mark.parametrize("setting", ["HUB_MESH_URL", "BRIDGE_URL"])
def test_existing_internal_endpoint_settings_are_supported(serving, monkeypatch, setting):
    monkeypatch.delenv("PLATFORM_INTERNAL_URL")
    monkeypatch.delenv("BRIDGE_URL", raising=False)
    monkeypatch.delenv("HUB_MESH_URL", raising=False)
    monkeypatch.setenv(setting, "http://100.64.0.4:3000")
    assert service.request_serving_verification(19)["verified"]
    assert serving[0][0].startswith("http://100.64.0.4:3000/")


def test_absent_base_settings_fail_closed(serving, monkeypatch):
    for setting in ("PLATFORM_INTERNAL_URL", "BRIDGE_URL", "HUB_MESH_URL"):
        monkeypatch.delenv(setting, raising=False)
    with pytest.raises(ValueError, match="not configured"):
        service.request_serving_verification(19)
    assert serving == []


def test_hub_mesh_setting_keeps_destination_validation(serving, monkeypatch):
    monkeypatch.delenv("PLATFORM_INTERNAL_URL")
    monkeypatch.delenv("BRIDGE_URL", raising=False)
    monkeypatch.setenv("HUB_MESH_URL", "https://example.com")
    with pytest.raises(ValueError, match="mesh endpoint"):
        service.request_serving_verification(19)
    assert serving == []


def test_invalid_explicit_setting_does_not_fall_back_to_mesh(serving, monkeypatch):
    monkeypatch.setenv("PLATFORM_INTERNAL_URL", "https://example.com")
    monkeypatch.setenv("HUB_MESH_URL", "http://100.64.0.4:3000")
    with pytest.raises(ValueError, match="mesh endpoint"):
        service.request_serving_verification(19)
    assert serving == []


def test_internal_endpoint_requires_write_scope_and_ignores_browser_evidence():
    """Extract the actual route into a minimal Flask app, avoiding production startup."""
    from flask import Flask, jsonify
    from services import repair_verification
    from unittest.mock import patch

    source = (Path(__file__).parents[1] / "app.py").read_text()
    tree = ast.parse(source)
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "api_internal_repair_proposal_verify"
    )
    app = Flask(__name__)
    scopes = []

    def require_scope(scope):
        scopes.append(scope)

        def decorator(fn):
            from functools import wraps
            from flask import request

            @wraps(fn)
            def checked(*args, **kwargs):
                if request.headers.get("Authorization") != "Bearer test-only":
                    return jsonify(success=False), 403
                return fn(*args, **kwargs)

            return checked

        return decorator

    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "<actual-route>", "exec"),
        {"app": app, "jsonify": jsonify, "require_internal_scope": require_scope},
    )
    assert scopes == ["repair:write"]
    with patch.object(repair_verification, "verify_completion", return_value={"success": True}) as verify:
        client = app.test_client()
        assert client.post("/api/internal/repair/proposals/19/verify").status_code == 403
        verify.assert_not_called()
        response = client.post(
            "/api/internal/repair/proposals/19/verify",
            json={"fingerprint": "forged"},
            headers={"Authorization": "Bearer test-only"},
        )
        assert response.json == {"success": True}
        verify.assert_called_once_with(19)


@pytest.fixture
def cycle(monkeypatch):
    from contextlib import contextmanager
    from copy import deepcopy
    import sys
    from types import ModuleType

    fake_package = ModuleType("tools.repair_bay")
    fake_package.__path__ = [str(Path(__file__).parents[1] / "tools/repair_bay")]
    monkeypatch.setitem(sys.modules, "tools.repair_bay", fake_package)
    from tools.repair_bay.services import github_service

    manifest = {"repo": service.REPO, "pr_number": 123, "head_sha": "a" * 40, "files": []}
    row = {
        "id": 19,
        "status": "pr_open",
        "metadata": {
            "source": "code_health_audit",
            "pr_number": 123,
            "apply_mode": "planned_codex_pr",
            "planned_repair": {"task_id": 77},
        },
    }
    task = {"metadata": {"codex_pr": 123}, "delegation_args": {"capability": "codex_task"}}
    state = {
        "row": row,
        "task": task,
        "snapshot": deepcopy(row),
        "writes": [],
        "calls": [],
        "merged": True,
        "race": False,
        "review_ok": True,
    }

    class Cursor:
        def execute(self, sql, params):
            self.sql = sql
            if sql.startswith("UPDATE"):
                state["writes"].append((sql, params))

        def fetchall(self):
            return [deepcopy(state["snapshot"])]

        def fetchone(self):
            if "unified_tasks" in self.sql:
                return state["task"]
            if "pr_reviews" in self.sql:
                return {"approved": True}
            row = deepcopy(state["row"])
            if state["race"]:
                row["metadata"]["planned_repair"]["task_id"] = 88
            return row

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(service, "get_db_cursor", db)
    monkeypatch.setattr(service, "build_manifest", lambda *a: manifest)
    monkeypatch.setattr(service, "_review_ok", lambda *a: state["review_ok"])
    monkeypatch.setattr(
        github_service,
        "_api_get",
        lambda *a: (
            True,
            {
                "head": {"sha": "a" * 40},
                "merged": state["merged"],
                "merge_commit_sha": "b" * 40,
                "merged_at": "2026-10-09T12:00:00Z",
            },
        ),
    )

    def verify(proposal_id):
        state["calls"].append(proposal_id)
        return state.get("result", {"success": True})

    monkeypatch.setattr(service, "request_serving_verification", verify)
    return state


def test_merged_cycle_records_proof_then_calls_serving_process(cycle):
    assert service.reconcile_planned_completion() == {"checked": 1, "verified": 1, "blocked": 0}
    assert cycle["calls"] == [19]
    updates = cycle["writes"][0][1][0].adapted
    assert updates["planned_merge"]["merge_sha"] == "b" * 40
    assert updates["code_applied"] is False
    assert updates["repair_submission"]["stage"] == "merged_awaiting_verification"
    assert "status='deployed'" not in cycle["writes"][0][0]


def test_open_pr_refreshes_without_claiming_merge(cycle):
    cycle["merged"] = False
    result = service.reconcile_planned_completion()
    assert result["verified"] == 0 and cycle["calls"] == []
    updates = cycle["writes"][0][1][0].adapted
    assert "repair_artifacts" in updates and "planned_merge" not in updates


def test_failed_verification_preserves_open_status_and_exposes_reason(cycle):
    cycle["result"] = {"success": False, "error": "QA missing"}
    result = service.reconcile_planned_completion()
    assert result["blocked"] == 1 and result["verified"] == 0
    sql, params = cycle["writes"][-1]
    assert params[0].adapted == "QA missing"
    assert "status='pr_open'" in sql and "completion_checked_at" in sql


def test_replaced_attempt_is_not_overwritten(cycle):
    cycle["race"] = True
    service.reconcile_planned_completion()
    assert cycle["writes"] == [] and cycle["calls"] == []


def test_review_changed_under_lock_is_not_registered(cycle):
    cycle["review_ok"] = False
    service.reconcile_planned_completion()
    assert cycle["writes"] == [] and cycle["calls"] == []


def test_task_pr_mismatch_blocks_completion(cycle):
    cycle["task"]["metadata"]["codex_pr"] = 456
    assert service.reconcile_planned_completion()["blocked"] == 1
    assert cycle["calls"] == []
    assert "repair_artifacts" not in cycle["writes"][0][1][0].adapted
