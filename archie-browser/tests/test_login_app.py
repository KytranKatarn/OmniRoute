"""Tests for the login sidecar supervisor (#4006 additions).

Covers: bearer auth, /profiles enumeration, dynamic-platform /start
validation (the sidecar-side trust boundary), and that the baked platforms
keep their original behavior.
"""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN = "test-internal-key"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def login_app(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", TOKEN)
    monkeypatch.setenv("BROWSER_PROFILES_DIR", str(tmp_path))
    import login_app as mod

    mod = importlib.reload(mod)  # re-read env at import time
    yield mod
    mod._proc = None


@pytest.fixture
def client(login_app):
    login_app.app.config["TESTING"] = True
    return login_app.app.test_client()


def test_auth_required(client):
    assert client.get("/profiles").status_code == 401
    assert client.post("/start", json={}).status_code == 401


def test_profiles_enumerates_real_dirs(client, login_app, tmp_path):
    est = tmp_path / "342-linkedin"
    est.mkdir()
    (est / "Cookies").write_text("x")
    (tmp_path / "999-custom_site").mkdir()  # empty = not established
    (tmp_path / "junk-name!").mkdir()  # no match — ignored
    (tmp_path / "stray.txt").write_text("x")

    r = client.get("/profiles", headers=AUTH)
    assert r.status_code == 200
    profs = {(p["agent_id"], p["platform"]): p["established"] for p in r.get_json()["profiles"]}
    assert profs == {(342, "linkedin"): True, (999, "custom_site"): False}


def test_start_dynamic_platform_requires_login_payload(client):
    r = client.post("/start", json={"agent_id": 1, "platform": "mysite"}, headers=AUTH)
    assert r.status_code == 400  # no login_url/allowed_hosts


def test_start_dynamic_platform_rejects_private_hosts(client):
    for hosts in (["192.168.1.200"], ["archie_database"], ["nas.local"]):
        r = client.post(
            "/start",
            json={
                "agent_id": 1,
                "platform": "mysite",
                "login_url": "https://example.com/login",
                "allowed_hosts": hosts,
            },
            headers=AUTH,
        )
        assert r.status_code == 400, hosts


def test_start_dynamic_platform_rejects_offlist_login_url(client):
    r = client.post(
        "/start",
        json={
            "agent_id": 1,
            "platform": "mysite",
            "login_url": "https://evil.com/login",
            "allowed_hosts": ["example.com"],
        },
        headers=AUTH,
    )
    assert r.status_code == 400


def test_start_dynamic_platform_spawns_with_identity_env(client, login_app):
    fake = MagicMock()
    fake.poll.return_value = None
    with patch.object(login_app.subprocess, "Popen", return_value=fake) as popen:
        r = client.post(
            "/start",
            json={
                "agent_id": 77,
                "platform": "mysite",
                "login_url": "https://www.example.com/login",
                "allowed_hosts": ["www.example.com", "example.com"],
            },
            headers=AUTH,
        )
    assert r.status_code == 200 and r.get_json()["started"] is True
    env = popen.call_args.kwargs["env"]
    assert env["LOGIN_AGENT_ID"] == "77"
    assert env["LOGIN_PLATFORM"] == "mysite"
    login_app._proc = None


def test_start_baked_platform_ignores_caller_hosts(client, login_app):
    """Baked platforms keep the hardcoded allowlist — a caller-supplied
    allowed_hosts must NOT widen where the trusted profile navigates."""
    fake = MagicMock()
    fake.poll.return_value = None
    with patch.object(login_app.subprocess, "Popen", return_value=fake):
        r = client.post(
            "/start",
            json={
                "agent_id": 1,
                "platform": "linkedin",
                "url": "https://evil.com/login",
                "allowed_hosts": ["evil.com"],
            },
            headers=AUTH,
        )
    assert r.status_code == 400  # off-allowlist url rejected despite caller hosts
    login_app._proc = None


def test_invalid_platform_key_rejected(client):
    r = client.post("/start", json={"agent_id": 1, "platform": "Bad Key!"}, headers=AUTH)
    assert r.status_code == 400
