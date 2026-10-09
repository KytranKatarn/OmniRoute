"""Coder results must prove identity, review freshness and complete artifact coverage."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from services import planned_repair_results as service
from services import planned_repair_service
from services.planned_repair_policy import validate_artifact_path
from services import planned_repair_policy as policy


def test_partial_container_mount_reads_exact_tracked_scope(monkeypatch):
    monkeypatch.setattr(policy.Path, "is_file", lambda _: False)
    result = type(
        "Result",
        (),
        {"stdout": 'codex:\n  allowed_paths: [platform_v2/]\n  blocked_globs: ["**/department_dispatcher.py"]\n'},
    )()
    run = Mock(return_value=result)
    monkeypatch.setattr(policy.subprocess, "run", run)
    assert policy.load_scope()["allowed_paths"] == ["platform_v2/"]
    assert run.call_args.args[0] == ["git", "--git-dir=/mnt/archie_brain/.git", "show", "HEAD:config/agents/codex.yaml"]
    assert run.call_args.kwargs["timeout"] == 5 and run.call_args.kwargs["check"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "codex: {}",
        "codex: {allowed_paths: [platform_v2/]}",
        "codex: {allowed_paths: platform_v2/, blocked_globs: []}",
    ],
)
def test_missing_or_invalid_scope_never_grants_access(monkeypatch, text):
    monkeypatch.setattr(policy.Path, "is_file", lambda _: False)
    monkeypatch.setattr(policy.subprocess, "run", Mock(return_value=type("Result", (), {"stdout": text})()))
    with pytest.raises(ValueError, match="scope could not be verified"):
        policy.load_scope()


@pytest.fixture
def result(monkeypatch):
    # Import service files without the Repair Bay Blueprint's production DDL.
    package = ModuleType("tools.repair_bay")
    package.__path__ = [str(Path(__file__).parents[1] / "tools/repair_bay")]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    github = importlib.import_module("tools.repair_bay.services.github_service")
    path = "platform_v2/tools/department_hq/jobs.py"
    proposal = {
        "id": 19,
        "status": "approved",
        "metadata": {
            "source": "code_health_audit",
            "issue_code": "LARGE_FILE",
            "file_path": path,
            "planned_repair": {"task_id": 77},
        },
    }
    task = {
        "id": 77,
        "status": "review",
        "delegation_args": {"capability": "codex_task", "args": {"repair_proposal_id": 19}},
        "metadata": {"codex_pr": 123, "codex_branch": "codex/refactor-jobs"},
    }
    head = "a" * 40
    review = {
        "review_status": "reviewed",
        "ai_summary": "VERDICT: APPROVE",
        "metadata": {"head_sha": head, "reviewed_head_sha": head},
    }
    pr = {
        "number": 123,
        "state": "open",
        "changed_files": 1,
        "head": {"sha": head, "ref": task["metadata"]["codex_branch"], "repo": {"full_name": service.REPO}},
        "base": {"ref": "main", "repo": {"full_name": service.REPO}},
    }
    content = "# bounded refactor\n"
    raw = content.encode()
    blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    files = [{"filename": path, "status": "modified", "sha": blob_sha}]
    blob = {"sha": blob_sha, "content": content, "size": len(raw)}
    monkeypatch.setattr(github, "_api_get", lambda url, **kw: (True, files if url.endswith("/files") else pr))
    monkeypatch.setattr(github, "get_file_at_ref", lambda path, ref: blob)
    monkeypatch.setattr(planned_repair_service, "classify", lambda _: {"eligible": True, "file_path": path})
    return proposal, task, review, pr, files, blob, github


def test_manifest_is_bound_to_reviewed_head_and_content(result):
    proposal, task, review, _, _, blob, github = result
    manifest = service.build_manifest(proposal, task, review, github)
    assert manifest["head_sha"] == "a" * 40
    assert manifest["files"][0]["sha256"] == hashlib.sha256(blob["content"].encode()).hexdigest()
    assert manifest["repo"] == service.REPO


@pytest.mark.parametrize(
    "problem",
    [
        "foreign_task",
        "foreign_branch",
        "foreign_repo",
        "wrong_base",
        "stale_review",
        "changes_requested",
        "incomplete",
        "too_large",
        "closed",
        "corrupt_blob",
        "short_blob",
        "duplicate",
        "protected",
        "rename_protected",
        "wrong_target",
    ],
)
def test_untrusted_or_incomplete_results_are_refused(result, problem):
    proposal, task, review, pr, files, blob, github = result
    if problem == "foreign_task":
        task["delegation_args"]["args"]["repair_proposal_id"] = 20
    elif problem == "foreign_branch":
        pr["head"]["ref"] = "codex/other-task"
    elif problem == "foreign_repo":
        pr["head"]["repo"]["full_name"] = "other/repo"
    elif problem == "wrong_base":
        pr["base"]["ref"] = "release"
    elif problem == "stale_review":
        review["metadata"]["reviewed_head_sha"] = "b" * 40
    elif problem == "changes_requested":
        review["ai_summary"] = "VERDICT: REQUEST CHANGES"
    elif problem == "incomplete":
        pr["changed_files"] = 2
    elif problem == "too_large":
        pr["changed_files"] = 26
    elif problem == "closed":
        pr["state"] = "closed"
    elif problem == "corrupt_blob":
        blob["content"] = "x" * blob["size"]
    elif problem == "short_blob":
        blob["size"] += 1
    elif problem == "duplicate":
        files.append(dict(files[0]))
        pr["changed_files"] = 2
    elif problem == "protected":
        files[0]["filename"] = "platform_v2/tools/department_hq/services/smart_router.py"
    elif problem == "rename_protected":
        files[0].update(status="renamed", previous_filename="config/agents/codex.yaml")
    else:
        files[0]["filename"] = "platform_v2/tools/department_hq/other.py"
    with pytest.raises(ValueError):
        service.build_manifest(proposal, task, review, github)


def test_push_during_manifest_collection_is_refused(result, monkeypatch):
    proposal, task, review, pr, files, _, github = result
    later = deepcopy(pr)
    later["head"]["sha"] = "b" * 40
    monkeypatch.setattr(github, "_api_get", Mock(side_effect=[(True, pr), (True, files), (True, later)]))
    with pytest.raises(ValueError, match="head changed"):
        service.build_manifest(proposal, task, review, github)


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "./platform_v2/tools/repair_bay/a.py",
        "config/agents/codex.yaml",
        "platform_v2/services/planned_repair_results.py",
        "platform_v2/tools/repair_bay/a.py",
        "platform_v2/tools/department_hq/services/department_dispatcher.py",
    ],
)
def test_artifact_policy_blocks_traversal_and_oversight(path):
    with pytest.raises(ValueError):
        validate_artifact_path(path)


@pytest.mark.parametrize("race", [None, "task_replaced", "already_shipped", "review_changed", "target_changed"])
def test_reconciler_links_once_and_never_completes_repair(result, monkeypatch, race):
    proposal, task, review, _, _, _, _ = result
    row = deepcopy(proposal)
    writes = []

    class Cursor:
        def execute(self, sql, params):
            if "SELECT * FROM improvement_proposals" in sql:
                self.rows = [proposal]
            elif "SELECT status,metadata FROM improvement_proposals" in sql:
                self.row = row
                if race == "task_replaced":
                    row["metadata"]["planned_repair"]["task_id"] = 88
                if race == "already_shipped":
                    row["status"] = "pr_open"
                if race == "target_changed":
                    row["metadata"]["file_path"] = "platform_v2/tools/faith/routes.py"
            elif "SELECT * FROM unified_tasks" in sql:
                self.row = task
            elif "SELECT * FROM pr_reviews" in sql:
                self.row = review
                if race == "review_changed" and "FOR SHARE" in sql:
                    self.row = dict(review, ai_summary="VERDICT: REQUEST CHANGES")
            elif "UPDATE improvement_proposals" in sql:
                writes.append(params)
            else:
                raise AssertionError(sql)

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(service, "get_db_cursor", db)
    outcome = service.reconcile_planned_results()
    if race:
        assert not writes and outcome["linked"] == 0
    else:
        assert outcome["linked"] == 1 and len(writes) == 1
        status, payload, proposal_id = writes[0]
        assert status == "pr_open" and proposal_id == 19
        assert payload.adapted["code_applied"] is False
        assert payload.adapted["apply_mode"] == "planned_codex_pr"
        assert "repair_verification" not in payload.adapted
        row.update(status=status)
        row["metadata"].update(payload.adapted)
        assert service.reconcile_planned_results()["linked"] == 0


def test_tracking_precedes_admission_pause():
    import ast

    source = (Path(__file__).parents[1] / "tools/department_hq/jobs.py").read_text()
    fn = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == "code_health_backlog_drain_job"
    )
    text = ast.get_source_segment(source, fn)
    assert text.index("reconcile_planned_results(limit=3)") < text.index(
        'if not is_enabled("code_health_backlog_drain"'
    )
