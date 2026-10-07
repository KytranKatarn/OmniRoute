"""Exercise the real throwaway patch applicator and publication artifact guard."""

import hashlib
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
import pytest


@pytest.fixture
def native_forge(monkeypatch):
    base = Path(__file__).parents[1] / "tools/repair_bay/services"
    for name in ("tools.repair_bay", "tools.repair_bay.services"):
        package = ModuleType(name)
        package.__path__ = [str(base.parent if name == "tools.repair_bay" else base)]
        monkeypatch.setitem(sys.modules, name, package)
    loaded = []
    for name in ("github_service", "forge_pipeline"):
        fullname = "tools.repair_bay.services." + name
        spec = importlib.util.spec_from_file_location(fullname, base / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fullname, module)
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded[1], loaded[0]


def test_native_patch_applicator_handles_success_and_drift(tmp_path, monkeypatch, native_forge):
    forge, github_service = native_forge
    monkeypatch.setattr(github_service, "REPO_PATH", str(tmp_path))
    file = tmp_path / "example.py"
    file.write_text("value = 1\n")
    diff = "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    assert forge._patched_content("example.py", diff) == "value = 2\n"
    assert file.read_text() == "value = 1\n"
    file.write_text("value = 3\n")
    assert forge._patched_content("example.py", diff) is None
    assert file.read_text() == "value = 3\n"


def test_publication_refuses_target_drift_before_pushing(tmp_path, monkeypatch, native_forge):
    forge, gh = native_forge
    monkeypatch.setattr(gh, "health_check", lambda: {"success": True})
    monkeypatch.setattr(gh, "create_branch", lambda _: {"success": True})
    push = Mock()
    monkeypatch.setattr(gh, "push_changes", push)
    monkeypatch.setattr(forge, "_patched_content", lambda *_: "different target")
    proposal = {
        "id": 42,
        "code_changes": "saved diff",
        "metadata": {
            "file_path": "example.py",
            "repair_submission": {"target_sha256": hashlib.sha256(b"tested target").hexdigest()},
        },
    }
    result = forge.deploy_via_forge(proposal, 88)
    assert not result["success"] and "Source changed" in result["error"]
    push.assert_not_called()


@pytest.mark.parametrize("change", ["patch", "target", "receipt", "status", "source", "unchanged"])
def test_publication_rechecks_the_tested_patch_under_lock(native_forge, monkeypatch, change):
    from services.proposal_service import _publish_tested_proposal

    fake, _ = native_forge
    row = {
        "id": 42,
        "status": "ready_for_review",
        "code_changes": "saved diff",
        "metadata": {"source": "code_health_audit", "file_path": "platform_v2/tools/faith/routes.py"},
    }
    row["metadata"]["repair_submission"] = {
        "stage": "sandbox_passed",
        "sandbox_run_id": 77,
        "patch_sha256": hashlib.sha256(b"saved diff").hexdigest(),
        "target_sha256": hashlib.sha256(b"patched source").hexdigest(),
    }
    tested = dict(row, metadata=dict(row["metadata"]))
    if change == "patch":
        row["code_changes"] = "changed during testing"
    elif change == "target":
        row["metadata"]["file_path"] = "platform_v2/tools/doc/routes.py"
    elif change == "receipt":
        row["metadata"]["repair_submission"]["stage"] = "sandbox_testing"
    elif change == "status":
        row["status"] = "pr_open"
    elif change == "source":
        row["metadata"]["source"] = "other_workflow"
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append(sql)

        def fetchone(self):
            return {"id": 88} if calls[-1].startswith("INSERT") else row

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr("database.get_db_cursor", db)
    fake.deploy_via_forge = Mock(return_value={"success": True, "method": "forge_pr", "pr_number": 19})
    result = _publish_tested_proposal(42, tested)
    if change == "unchanged":
        assert result["pr_number"] == 19
        fake.deploy_via_forge.assert_called_once()
    else:
        assert not result["success"]
        fake.deploy_via_forge.assert_not_called()
        assert not any(sql.startswith(("INSERT", "UPDATE")) for sql in calls)
