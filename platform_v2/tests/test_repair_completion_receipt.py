"""Merged repairs require artifact, runtime, QA and finding evidence."""

import hashlib
import json
import sys
from contextlib import contextmanager
from types import ModuleType
import pytest
from services import repair_submission as service
from services import repair_verification as verification
from services import repair_progress as progress_service


@pytest.fixture
def active_suites():
    return [{"id": 1}]


@pytest.fixture
def completion(monkeypatch, tmp_path, active_suites):
    file = tmp_path / "fixed.py"
    file.write_text("cur.execute('SELECT 1')\n")
    row = {
        "status": "pr_open",
        "metadata": {
            "source": "code_health_audit",
            "file_path": "platform_v2/tools/faith/routes.py",
            "issue_code": "SQL_INJECTION_RISK",
            "merged_pr": 17,
            "repair_submission": {
                "stage": "merged_awaiting_verification",
                "target_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            },
        },
    }
    runs = [{"id": 99, "suite_id": 1, "status": "completed", "total": 2, "passed": 2, "failed": 0, "errors": 0}]
    writes = []

    class Cursor:
        def execute(self, sql, params):
            self.suite_query = sql.startswith("SELECT id FROM qa_test_suites")
            if sql.startswith("UPDATE"):
                writes.append((sql, params))

        def fetchone(self):
            return row

        def fetchall(self):
            return active_suites if self.suite_query else runs

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(service, "get_db_cursor", db)
    monkeypatch.setattr(verification, "get_db_cursor", db)
    monkeypatch.setattr(verification, "RUNTIME_STARTED_AT", file.stat().st_mtime + 1)
    monkeypatch.setattr(
        "services.audit_pipeline.resolve_proposal_source",
        lambda _: (str(file), "platform_v2/tools/faith/routes.py", "ok"),
    )
    monkeypatch.setattr("services.qa_service.MODULE_SUITE_MAP", {"faith": [1]})
    return row, runs, writes, file


def test_merge_keeps_code_health_repair_open(completion):
    row, _, writes, _ = completion
    del row["metadata"]["merged_pr"]
    assert service.record_code_health_merge(42, 17)
    assert len(writes) == 1 and "status='deployed'" not in writes[0][0]
    saved = json.loads(writes[0][1][0])
    assert saved["code_applied"] is False
    assert saved["repair_submission"]["stage"] == "merged_awaiting_verification"


def test_complete_only_after_artifact_restart_qa_and_finding_proof(completion):
    _, _, writes, _ = completion
    result = service.verify_completion(42)
    assert result["verified"]
    assert len(writes) == 2
    assert "status='deployed'" in writes[0][0]
    saved = json.loads(writes[0][1][0])
    assert saved["repair_submission"]["stage"] == "verified_complete"
    assert saved["repair_verification"]["qa_run_ids"] == [99]


@pytest.mark.parametrize(
    "problem",
    ["unmerged", "wrong_hash", "old_process", "missing_qa", "failed_qa", "unknown_finding", "missing_fingerprint"],
)
def test_incomplete_evidence_never_closes_repair(completion, monkeypatch, problem):
    row, runs, writes, file = completion
    if problem == "unmerged":
        del row["metadata"]["merged_pr"]
    elif problem == "wrong_hash":
        row["metadata"]["repair_submission"]["target_sha256"] = "wrong"
    elif problem == "old_process":
        monkeypatch.setattr(verification, "RUNTIME_STARTED_AT", file.stat().st_mtime - 1)
    elif problem == "missing_qa":
        runs.clear()
    elif problem == "failed_qa":
        runs[0]["passed"] = 1
        runs[0]["failed"] = 1
    elif problem == "unknown_finding":
        row["metadata"]["issue_code"] = "UNKNOWN"
    else:
        del row["metadata"]["repair_submission"]["target_sha256"]
    assert not service.verify_completion(42)["success"]
    assert writes == []


@pytest.mark.parametrize(
    "state,tier,head,reviewed,expected",
    [
        ("open", 2, "abc", "abc", "awaiting_governed_merge"),
        ("open", 3, "abc", "abc", "awaiting_human_merge"),
        ("open", 2, "new", "old", "pr_review"),
        ("merged", 2, "abc", "abc", "merged_awaiting_verification"),
        ("closed", 2, "abc", "abc", "pr_closed_unmerged"),
    ],
)
def test_live_pr_progress_requires_current_head_review(monkeypatch, state, tier, head, reviewed, expected):
    review = {
        "state": state,
        "review_status": "reviewed",
        "ai_summary": "APPROVE",
        "metadata": {"head_sha": head, "reviewed_head_sha": reviewed},
    }

    class Cursor:
        def execute(self, *args):
            pass

        def fetchone(self):
            return review

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(progress_service, "get_db_cursor", db)
    fake = ModuleType("tools.repair_bay.services.pr_review_service")
    fake.classify_pr_tier = lambda _: tier
    fake.verdict_is_approved = lambda _: True
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    result = service.progress({"status": "pr_open", "metadata": {"source": "code_health_audit", "pr_number": 17}})
    assert result["stage"] == expected
    assert result["merge_tier"] == tier


def test_disabled_mapped_suite_does_not_block_fresh_active_qa(completion, monkeypatch):
    monkeypatch.setattr("services.qa_service.MODULE_SUITE_MAP", {"faith": [1, 59]})
    result = service.verify_completion(42)
    assert result["verified"]
    assert result["verification"]["qa_run_ids"] == [99]


@pytest.mark.parametrize("active", [[], [{"id": 1}, {"id": 2}]])
def test_empty_or_incomplete_active_coverage_never_completes(completion, active_suites, active):
    _, _, writes, _ = completion
    active_suites[:] = active
    assert not service.verify_completion(42)["success"]
    assert writes == []
