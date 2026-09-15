"""Tests for Repair Bay Pushes — Create PR endpoint.

Proves the route:
  - 404s on unknown branch
  - 400s when commits_ahead == 0 (nothing to push)
  - 502s when push or PR creation fails
  - returns pr_url/pr_number on success
  - surfaces GitHub's 422 (already-exists) as a clear error
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROWS = [
    {
        "branch": "feat/test-push-a",
        "local_sha": "abc1234",
        "remote_sha": "aaa1111",
        "commits_ahead": 3,
        "commits_behind": 0,
        "last_touched": "2026-09-14T00:00:00+00:00",
        "last_commit_subject": "feat: add widget",
        "has_remote": True,
    },
    {
        "branch": "fix/nothing-here",
        "local_sha": "def5678",
        "remote_sha": "def5678",
        "commits_ahead": 0,
        "commits_behind": 0,
        "last_touched": "2026-09-13T00:00:00+00:00",
        "last_commit_subject": "chore: clean up",
        "has_remote": True,
    },
]

_FAKE_PR = {
    "success": True,
    "pr_url": "https://github.com/KytranKatarn/archie-platform/pull/9999",
    "pr_number": 9999,
    "branch": "feat/test-push-a",
}


class _User(UserMixin):
    id = 1
    is_super_admin = True
    is_admin = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def push_client():
    """Minimal Flask client with only the pending-push routes mounted."""
    app = Flask(__name__, template_folder=str(PLATFORM_ROOT / "templates"))
    app.config["SECRET_KEY"] = "test"
    app.config["TESTING"] = True

    login_manager = LoginManager(app)

    @login_manager.user_loader
    def load_user(uid):
        return _User()

    from flask import Blueprint
    bp = Blueprint("push_test", __name__, url_prefix="/tools/repair-bay")

    from tools.repair_bay.pending_push_routes import register_pending_push_routes
    register_pending_push_routes(bp, lambda f: f)

    app.register_blueprint(bp)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_unknown_branch_returns_404(push_client, monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.scan_pending_pushes",
        lambda: _ROWS,
    )
    resp = push_client.post("/tools/repair-bay/api/pushes/feat/nonexistent/create-pr")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert "not found" in data["error"]


def test_nothing_ahead_returns_400(push_client, monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.scan_pending_pushes",
        lambda: _ROWS,
    )
    resp = push_client.post("/tools/repair-bay/api/pushes/fix/nothing-here/create-pr")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "nothing to PR" in data["error"]


def test_push_failure_returns_502(push_client, monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.scan_pending_pushes",
        lambda: _ROWS,
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.push_pending_branch",
        lambda b: {"success": False, "error": "cloned failed: OOM"},
    )
    resp = push_client.post("/tools/repair-bay/api/pushes/feat/test-push-a/create-pr")
    assert resp.status_code == 502
    data = resp.get_json()
    assert data["success"] is False
    assert "OOM" in data["error"]


def test_pr_creation_failure_returns_502(push_client, monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.scan_pending_pushes",
        lambda: _ROWS,
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.push_pending_branch",
        lambda b: {"success": True, "branch": b},
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.pending_commit_subjects",
        lambda b: ["feat: add widget", "tests: add coverage"],
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.create_pr",
        lambda b, t, body: {"success": False, "error": "HTTP 422: validation failed"},
    )
    resp = push_client.post("/tools/repair-bay/api/pushes/feat/test-push-a/create-pr")
    assert resp.status_code == 502
    data = resp.get_json()
    assert data["success"] is False
    assert "422" in data["error"]


def test_success(push_client, monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.scan_pending_pushes",
        lambda: _ROWS,
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.push_pending_branch",
        lambda b: {"success": True, "branch": b},
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.pending_commit_subjects",
        lambda b: ["feat: add widget"],
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.create_pr",
        lambda b, t, body: dict(_FAKE_PR),
    )
    resp = push_client.post("/tools/repair-bay/api/pushes/feat/test-push-a/create-pr")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["pr_url"] == _FAKE_PR["pr_url"]
    assert data["pr_number"] == 9999
    assert data["branch"] == "feat/test-push-a"


def test_success_fallback_title_uses_subject(push_client, monkeypatch):
    """When pending_commit_subjects returns empty, title falls back to last_commit_subject."""
    captured = {}

    def _fake_create_pr(branch, title, body):
        captured["title"] = title
        captured["body"] = body
        return dict(_FAKE_PR)

    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.scan_pending_pushes",
        lambda: _ROWS,
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.push_pending_branch",
        lambda b: {"success": True, "branch": b},
    )
    monkeypatch.setattr(
        "tools.repair_bay.services.pending_push_service.pending_commit_subjects",
        lambda b: [],
    )
    monkeypatch.setattr("tools.repair_bay.services.github_service.create_pr", _fake_create_pr)

    resp = push_client.post("/tools/repair-bay/api/pushes/feat/test-push-a/create-pr")
    assert resp.status_code == 200
    assert captured["title"] == "feat: add widget"


def test_branch_with_slashes(push_client, monkeypatch):
    row = dict(_ROWS[0], branch="fix/dispatch-unpinned-budget-floor-6749")
    monkeypatch.setattr("tools.repair_bay.services.pending_push_service.scan_pending_pushes", lambda: [row])
    monkeypatch.setattr("tools.repair_bay.services.github_service.push_pending_branch", lambda b: {"success": True, "branch": b})
    monkeypatch.setattr("tools.repair_bay.services.pending_push_service.pending_commit_subjects", lambda b: ["fix: unpin budget"])
    monkeypatch.setattr("tools.repair_bay.services.github_service.create_pr", lambda b, t, body: dict(_FAKE_PR))

    resp = push_client.post("/tools/repair-bay/api/pushes/fix/dispatch-unpinned-budget-floor-6749/create-pr")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
