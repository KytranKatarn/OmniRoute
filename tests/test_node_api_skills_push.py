# tests/test_node_api_skills_push.py
"""Test the /api/skills/push endpoint on node_api."""
import json
import os
import sys

import pytest


@pytest.fixture
def client(tmp_path):
    """Flask test client with a temporary SKILLS_DIR."""
    os.environ["DATABASE_URL"] = ""
    os.environ["NODE_ID"] = "test-node-001"
    skills_dir = str(tmp_path / "skills")
    os.makedirs(skills_dir, exist_ok=True)
    os.environ["SKILLS_DIR"] = skills_dir

    node_client_path = os.path.join(os.path.dirname(__file__), "..", "node_client")
    if node_client_path not in sys.path:
        sys.path.insert(0, node_client_path)

    # Fresh import each test so env vars are picked up
    if "node_api" in sys.modules:
        del sys.modules["node_api"]
    import node_api as _mod
    _mod.SKILLS_DIR = skills_dir

    with _mod.app.test_client() as c:
        yield c, skills_dir


def test_skills_push_writes_file(client):
    c, skills_dir = client
    payload = {
        "skill_id": 42,
        "repo_slug": "test-org-test-repo",
        "slug": "my-skill",
        "content": "# My Skill\n\nDoes things.",
        "quality_score": 0.85,
        "adapted": False,
    }
    resp = c.post(
        "/api/skills/push",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert data["slug"] == "my-skill"
    skill_path = os.path.join(skills_dir, "test-org-test-repo", "my-skill.md")
    assert os.path.exists(skill_path)
    with open(skill_path) as f:
        assert f.read() == "# My Skill\n\nDoes things."


def test_skills_push_missing_slug_returns_400(client):
    c, _ = client
    resp = c.post(
        "/api/skills/push",
        data=json.dumps({"skill_id": 1, "content": "# test", "repo_slug": "r"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["success"] is False


def test_skills_push_missing_content_returns_400(client):
    c, _ = client
    resp = c.post(
        "/api/skills/push",
        data=json.dumps({"skill_id": 1, "slug": "test", "repo_slug": "r"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["success"] is False


def test_skills_push_creates_nested_dirs(client):
    c, skills_dir = client
    payload = {
        "skill_id": 7,
        "repo_slug": "some-org-some-repo",
        "slug": "nested-skill",
        "content": "# Nested",
        "quality_score": 0.9,
        "adapted": True,
    }
    resp = c.post(
        "/api/skills/push",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert os.path.isdir(os.path.join(skills_dir, "some-org-some-repo"))
