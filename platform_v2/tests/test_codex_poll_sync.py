"""Scheduled polling must import COMMENT review verdicts, scoped to its repository."""

from unittest.mock import Mock

from tools.repair_bay.services import pr_review_service as service, codex_verdicts


def test_normal_poll_imports_codex_for_its_repo(monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.list_all_prs_enriched", lambda *a, **k: {"success": True, "prs": []}
    )
    monkeypatch.setattr(service, "check_review_path_health", lambda: None)
    ingest = Mock(return_value={"checked": 1, "recorded": 1})
    monkeypatch.setattr(codex_verdicts, "ingest_for_open_prs", ingest)
    result = service.poll_open_prs(repo="owner/other")
    ingest.assert_called_once_with(repo="owner/other")
    assert result["codex"]["recorded"] == 1


def test_codex_failure_preserves_successful_poll(monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.list_all_prs_enriched", lambda *a, **k: {"success": True, "prs": []}
    )
    monkeypatch.setattr(service, "check_review_path_health", lambda: None)
    monkeypatch.setattr(codex_verdicts, "ingest_for_open_prs", Mock(side_effect=RuntimeError("offline")))
    result = service.poll_open_prs()
    assert result["errors"] == 0
    assert result["codex"]["recorded"] == 0
    assert result["codex"]["reasons"]


def test_ingest_never_fetches_other_repositories(monkeypatch):
    monkeypatch.setattr(
        service, "list_reviews", lambda **kw: [{"pr_number": 12, "repo": "other/project", "state": "open"}]
    )
    fetch = Mock(side_effect=AssertionError("wrong repository queried"))
    monkeypatch.setattr(service, "pr_head_sha", fetch)
    assert codex_verdicts.ingest_for_open_prs(repo="owner/project")["checked"] == 0
    fetch.assert_not_called()
