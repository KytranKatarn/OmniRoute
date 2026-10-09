"""The existing completion authority handles manifests without weakening QA gates."""

import json
import pytest
from services import repair_verification as verification
from services import planned_repair_verification as artifacts
from tests.test_repair_completion_receipt import active_suites, completion  # noqa: F401


@pytest.fixture
def planned(completion, monkeypatch):
    row, runs, writes, _ = completion
    row["metadata"].update(apply_mode="planned_codex_pr", repair_artifacts={"version": 1})
    evidence = {
        "artifacts": [{"path": "reviewed.py", "sha256": "trusted"}],
        "merge_sha": "b" * 40,
        "deployed_sha": "c" * 40,
    }
    monkeypatch.setattr(artifacts, "verify_artifacts", lambda *a: (evidence, {"faith"}))
    return row, runs, writes, evidence


def test_manifest_receipt_preserves_qa_and_runtime_evidence(planned):
    row, _, writes, evidence = planned
    result = verification.verify_completion(42)
    assert result["verified"]
    receipt = json.loads(writes[0][1][0])["repair_verification"]
    assert receipt["artifacts"] == evidence["artifacts"]
    assert receipt["merge_sha"] == evidence["merge_sha"]
    assert receipt["qa_run_ids"] == [99]
    assert receipt["runtime_started_at"] == verification.RUNTIME_STARTED_AT


def test_planned_repair_cannot_fall_back_to_single_file_receipt(planned):
    row, _, writes, _ = planned
    del row["metadata"]["repair_artifacts"]
    assert not verification.verify_completion(42)["success"]
    assert writes == []


def test_every_affected_module_requires_active_coverage(planned, monkeypatch):
    _, _, writes, evidence = planned
    monkeypatch.setattr(artifacts, "verify_artifacts", lambda *a: (evidence, {"faith", "app"}))
    monkeypatch.setattr("services.qa_service.MODULE_SUITE_MAP", {"faith": [1], "app": [2]})
    assert not verification.verify_completion(42)["success"]
    assert writes == []


def test_failed_qa_keeps_manifest_repair_open(planned):
    _, runs, writes, _ = planned
    runs[0].update(passed=1, failed=1)
    assert not verification.verify_completion(42)["success"]
    assert writes == []


def test_deployment_change_during_qa_cannot_receive_receipt(planned, monkeypatch):
    _, _, writes, evidence = planned
    calls = []

    def verify(*args):
        calls.append(True)
        if len(calls) > 1:
            raise ValueError("Deployment changed")
        return evidence, {"faith"}

    monkeypatch.setattr(artifacts, "verify_artifacts", verify)
    assert not verification.verify_completion(42)["success"]
    assert len(calls) == 2 and writes == []
