from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from services import audit_pipeline as pipeline
from services import code_metrics_service as metrics


@pytest.fixture
def roots(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    site = tmp_path / "external-site"
    repo.mkdir()
    site.mkdir()
    monkeypatch.setattr(pipeline, "_REPAIR_REPO_ROOT", str(repo))
    monkeypatch.setattr(metrics, "WEBSITE_PRODUCTS", [{"module_key": "website_what_the_fact", "path": str(site)}])
    return repo, site


def test_product_placeholder_resolves_to_tracked_repository_root(roots):
    repo, _ = roots
    target = repo / "what-the-fact/consumer/app.py"
    target.parent.mkdir(parents=True)
    target.write_text("pass\n")
    absolute, display, status = pipeline.resolve_proposal_source("standalone_what_the_fact/consumer/app.py")
    assert (absolute, display, status) == (str(target), "what-the-fact/consumer/app.py", "ok")


def test_external_website_is_found_without_inventing_a_repository_destination(roots):
    _, site = roots
    target = site / "index.html"
    target.write_text("<html></html>")
    assert pipeline.resolve_proposal_source("website_what_the_fact/index.html") == (
        str(target),
        "website_what_the_fact/index.html",
        "external_owner",
    )


@pytest.mark.parametrize(
    "path",
    [
        "standalone_what_the_fact/../../outside.py",
        "website_what_the_fact/../outside.html",
        "/etc/passwd",
        "website_what_the_fact/../../etc/passwd",
    ],
)
def test_traversal_is_never_resolved(roots, path):
    assert pipeline.resolve_proposal_source(path)[2] == "missing"


def test_symlink_escape_is_not_read_or_handed_off(roots, tmp_path):
    repo, site = roots
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (repo / "what-the-fact").mkdir()
    (repo / "what-the-fact/leak.py").symlink_to(outside)
    (site / "leak.html").symlink_to(outside)
    for path in ["standalone_what_the_fact/leak.py", "website_what_the_fact/leak.html"]:
        assert pipeline.resolve_proposal_source(path)[2] == "missing"


def test_archive_sweep_preserves_external_findings(roots, monkeypatch):
    _, site = roots
    (site / "index.html").write_text("<html></html>")
    cur = Mock()
    cur.fetchall.return_value = [{"id": 1, "file_path": "website_what_the_fact/index.html"}]

    @contextmanager
    def db(**kwargs):
        yield None, cur

    monkeypatch.setattr(pipeline, "get_db_cursor", db)
    result = pipeline.archive_unfixable_audit_proposals(dry_run=True)
    assert result["archived"] == 0 and result["kept"] == 1
    assert not any("UPDATE" in call.args[0] for call in cur.execute.call_args_list)


def test_external_dispatch_stops_before_inference_and_does_not_archive(roots, monkeypatch):
    from services import work_tracking_service as work

    _, site = roots
    (site / "index.html").write_text("<html></html>")
    cur = Mock()
    cur.fetchone.return_value = {
        "id": 1,
        "status": "approved",
        "metadata": {
            "source": "code_health_audit",
            "file_path": "website_what_the_fact/index.html",
            "module_name": "website_what_the_fact",
            "issue_code": "INLINE_SCRIPT",
        },
    }

    @contextmanager
    def db(**kwargs):
        yield None, cur

    monkeypatch.setattr(pipeline, "get_db_cursor", db)
    monkeypatch.setattr(work, "create_work_session", lambda **kwargs: None)
    archive = Mock(side_effect=AssertionError("must not archive an existing external source"))
    monkeypatch.setattr(pipeline, "_archive_stale_proposal", archive)
    monkeypatch.setattr(
        pipeline, "creed_gate_pre_dispatch", Mock(side_effect=AssertionError("must not reach inference path"))
    )
    result = pipeline.dispatch_proposal_fix(1)
    assert result["blocked"] and result["error"] == "external_owner:website"
    archive.assert_not_called()
