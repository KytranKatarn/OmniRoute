"""qa_spec_runner: `auth.mode: browser` skips the HTTP pre-login and leaves the browser runner to sign in.

2026-10-06, run 3994: the wtf-mp-expenses-e2e suite errored on both tests with "Authentication failed after 3
attempts: Login returned status 405 for user probe" and never asserted anything. what-the-fact.com/login is a
REDIRECT to the platform's OAuth sign-in (it answers a POST with 405), so qa_spec_runner's HTTP pre-login — which
runs for every suite that has credentials, before any e2e test is handed to the browser runner — could never
succeed, even though the browser runner can follow the redirect and has its own login.

The fix is opt-in (`auth.mode: browser`), so every existing suite is unchanged.
"""

import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import qa_spec_runner as r  # noqa: E402

E2E = {"name": "t1", "type": "e2e", "path": "/x"}


def _spec(auth, tests=None):
    return {"suite": {"name": "s", "base_url": "https://example.test", "auth": auth}, "tests": tests or [dict(E2E)]}


@pytest.fixture
def calls(monkeypatch):
    log = {"auth": 0, "batch": []}

    def fake_auth(session, base_url, auth):
        log["auth"] += 1
        raise RuntimeError("Login returned status 405 for user probe")  # what WTF's /login does to a POST

    def fake_batch(tests, base_url, auth):
        log["batch"].append(dict(auth))
        return [{"test_name": t["name"], "test_type": "e2e", "status": "passed"} for t in tests]

    monkeypatch.setattr(r, "_authenticate", fake_auth)
    monkeypatch.setattr(r, "_run_e2e_batch", fake_batch)
    monkeypatch.setattr(r.time, "sleep", lambda s: None)
    return log


def test_browser_mode_never_attempts_the_http_login(calls):
    out = r.execute_spec(_spec({"mode": "browser", "username": "probe", "password": "pw"}))
    assert calls["auth"] == 0
    assert [x["status"] for x in out] == ["passed"]


def test_browser_mode_still_hands_the_credentials_to_the_browser_runner(calls):
    r.execute_spec(_spec({"mode": "browser", "username": "probe", "password": "pw"}))
    assert calls["batch"] and calls["batch"][0]["username"] == "probe" and calls["batch"][0]["password"] == "pw"


def test_without_the_opt_in_the_http_login_still_runs_and_still_fails_loudly(calls):
    """Every existing suite: unchanged. Three attempts, then every test is an error naming the cause."""
    out = r.execute_spec(_spec({"username": "probe", "password": "pw"}))
    assert calls["auth"] == 3
    assert [x["status"] for x in out] == ["error"] and "405" in out[0]["error_message"]
    assert calls["batch"] == []  # never reached the browser — the bug this fixes, for suites that opt in


@pytest.mark.parametrize("mode", ["", "form", "http", "browserish", None])
def test_only_the_exact_word_browser_opts_in(calls, mode):
    r.execute_spec(_spec({"mode": mode, "username": "probe", "password": "pw"}))
    assert calls["auth"] == 3


def test_mode_is_case_and_whitespace_tolerant(calls):
    r.execute_spec(_spec({"mode": "  Browser ", "username": "probe", "password": "pw"}))
    assert calls["auth"] == 0


def test_a_non_e2e_test_in_a_browser_mode_suite_is_warned_about(calls, caplog):
    spec = _spec(
        {"mode": "browser", "username": "probe", "password": "pw"},
        [dict(E2E), {"name": "t2", "type": "api", "method": "GET", "path": "/h", "expect": {"status": [200]}}],
    )
    with caplog.at_level("WARNING"):
        try:
            r.execute_spec(spec)
        except Exception:  # the api test would hit the network — only the warning matters here
            pass
    assert any("auth.mode=browser" in m and "non-e2e" in m for m in caplog.messages)


def test_the_wtf_suite_opts_in_and_is_all_e2e():
    path = os.path.join(os.path.dirname(__file__), "..", "qa_suites", "wtf-mp-expenses-e2e.yaml")
    spec = yaml.safe_load(open(path, encoding="utf-8"))
    assert spec["suite"]["auth"]["mode"] == "browser"
    assert {t["type"] for t in spec["tests"]} == {"e2e"}
    assert spec["suite"]["auth"]["username"] == "${ARCHIE_TEST_USERNAME}"
