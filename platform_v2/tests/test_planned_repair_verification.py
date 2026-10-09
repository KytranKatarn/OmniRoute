"""Multi-file receipts reject incomplete deployment, stale imports and moved findings."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os

import pytest

from services import planned_repair_verification as service
from services.planned_repair_results import REPO


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    target = "platform_v2/tools/department_hq/jobs.py"
    extracted = "platform_v2/tools/department_hq/new_jobs.py"
    removed = "platform_v2/tools/department_hq/old_jobs.py"
    root = tmp_path
    entries = []
    for path in (target, extracted):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("value = 1\n")
        os.utime(file, (100, 100))
        entries.append({"path": path, "status": "modified", "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    entries.append({"path": removed, "status": "removed"})
    meta = {
        "issue_code": "LARGE_FILE",
        "detail": "700 lines",
        "file_path": target,
        "pr_number": 123,
        "merged_pr": 123,
        "repair_artifacts": {"version": 1, "repo": REPO, "pr_number": 123, "head_sha": "a" * 40, "files": entries},
        "planned_merge": {
            "repo": REPO,
            "pr_number": 123,
            "head_sha": "a" * 40,
            "merge_sha": "b" * 40,
            "merged_at": datetime.fromtimestamp(150, timezone.utc).isoformat(),
        },
    }
    monkeypatch.setattr(service, "deployment_root", lambda: root)
    monkeypatch.setattr(service, "deployed_head", lambda _: "c" * 40)
    monkeypatch.setattr("services.audit_pipeline.resolve_proposal_source", lambda _: (str(root / target), target, "ok"))
    return meta, root


def test_all_artifacts_and_merge_are_receipted(artifacts):
    meta, _ = artifacts
    receipt, modules = service.verify_artifacts(meta, 200)
    assert receipt["artifacts"] == meta["repair_artifacts"]["files"]
    assert receipt["merge_sha"] == "b" * 40
    assert receipt["deployed_sha"] == "c" * 40
    assert modules == {"department_hq"}


@pytest.mark.parametrize(
    "problem",
    [
        "missing_merge",
        "foreign_repo",
        "wrong_head",
        "wrong_pr",
        "old_runtime",
        "naive_time",
        "missing_time",
        "duplicate",
        "empty",
        "unknown_status",
        "hash",
        "missing_file",
        "deleted_present",
        "renamed_present",
        "moved_large",
        "syntax",
        "fresh_file",
        "outside",
        "symlink",
        "protected",
        "target_absent",
        "unknown_finding",
    ],
)
def test_incomplete_or_false_evidence_refuses_receipt(artifacts, problem, monkeypatch):
    meta, root = artifacts
    entries = meta["repair_artifacts"]["files"]
    file = root / entries[1]["path"]
    runtime = 200
    if problem == "missing_merge":
        meta["planned_merge"] = {}
    elif problem == "foreign_repo":
        meta["repair_artifacts"]["repo"] = "attacker/repo"
    elif problem == "wrong_head":
        meta["planned_merge"]["head_sha"] = "d" * 40
    elif problem == "wrong_pr":
        meta["merged_pr"] = 456
    elif problem == "old_runtime":
        runtime = 140
    elif problem == "naive_time":
        meta["planned_merge"]["merged_at"] = "2020-01-01T00:00:00"
    elif problem == "missing_time":
        del meta["planned_merge"]["merged_at"]
    elif problem == "duplicate":
        entries.append(deepcopy(entries[0]))
    elif problem == "empty":
        entries.clear()
    elif problem == "unknown_status":
        entries[1]["status"] = "copied"
    elif problem == "hash":
        file.write_text("changed = 2")
        os.utime(file, (100, 100))
    elif problem == "missing_file":
        file.unlink()
    elif problem == "deleted_present":
        (root / entries[2]["path"]).write_text("old")
    elif problem == "renamed_present":
        entries[1].update(status="renamed", previous_path=entries[2]["path"])
        entries.pop()
        (root / entries[1]["previous_path"]).write_text("old")
    elif problem in {"moved_large", "syntax"}:
        file.write_text("x=1\n" * 601 if problem == "moved_large" else "def invalid(:\n")
        os.utime(file, (100, 100))
        entries[1]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    elif problem == "fresh_file":
        os.utime(file, (250, 250))
    elif problem == "outside":
        entries[1]["path"] = "platform_v2/../../etc/passwd"
    elif problem == "symlink":
        file.unlink()
        file.symlink_to(root / entries[0]["path"])
    elif problem == "protected":
        entries[1]["path"] = "platform_v2/services/agent_service.py"
    elif problem == "target_absent":
        entries.pop(0)
    elif problem == "unknown_finding":
        meta["issue_code"] = "UNKNOWN"
    with pytest.raises((ValueError, OSError, SyntaxError)):
        service.verify_artifacts(meta, runtime)


def test_deployed_commit_must_include_merge(artifacts, monkeypatch):
    import subprocess

    monkeypatch.setattr(
        service, "deployed_head", lambda _: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "git"))
    )
    with pytest.raises(subprocess.SubprocessError):
        service.verify_artifacts(artifacts[0], 200)


def test_container_maps_only_the_serving_mount(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(service, "deployment_root", lambda: Path("/"))
    assert service.artifact_file("platform_v2/tools/faith/routes.py") == Path("/app/tools/faith/routes.py")
    with pytest.raises(ValueError, match="serving deployment mapping"):
        service.artifact_file("docs/example.md")


def test_shared_artifacts_require_existing_core_qa_mapping(artifacts):
    meta, root = artifacts
    path = "platform_v2/tests/test_example.py"
    file = root / path
    file.parent.mkdir(parents=True)
    file.write_text("assert True\n")
    os.utime(file, (100, 100))
    meta["repair_artifacts"]["files"].append(
        {"path": path, "status": "added", "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    )
    assert service.verify_artifacts(meta, 200)[1] == {"department_hq", "app"}


def test_real_git_deployment_requires_merged_commit_ancestry(tmp_path, monkeypatch):
    import subprocess

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "merged repair",
    )
    merged = git("rev-parse", "HEAD")
    monkeypatch.setattr(service, "deployment_root", lambda: tmp_path)
    assert service.deployed_head(merged) == merged
    git("checkout", "--orphan", "unrelated")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "unrelated deployment",
    )
    with pytest.raises(subprocess.CalledProcessError):
        service.deployed_head(merged)
