"""#5627 slices 1-3 — the automated re-login must repair the POSTING profile,
prove it, and never announce a success it did not achieve.

The defect these pin: setup_session logged in through an EPHEMERAL
`browser.new_context()` and saved storage_state to the cookie store, while posting
reads the on-disk persistent profile. So a "successful" re-login left the profile
logged out, and the caller discarded the return value and logged
"re-login complete" even on needs_2fa.

A test that only asserts "setup_session returned active" cannot catch that — the old
code returned active too. The load-bearing assertions are WHICH launcher was used,
WHICH directory, and that 'active' requires a positive post-login feed check.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.fernet import Fernet as _Fernet

os.environ.setdefault("BROWSER_ENCRYPTION_KEY", _Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _real_session_manager():
    sys.modules.pop("session_manager", None)
    import session_manager as _sm

    sys.modules["session_manager"] = _sm
    yield


class _FakePage:
    """Walks a scripted list of URLs — one per navigation."""

    def __init__(self, urls):
        # Each entry is the URL *after* a navigation, in order. Starting blank keeps
        # the script honest: goto(login_url) consumes the first entry, so entry 0 is
        # "where the login URL actually landed us".
        self._urls = list(urls)
        self.url = "about:blank"
        self.filled = {}

    def goto(self, url, **kw):
        self.url = self._urls.pop(0) if self._urls else self.url

    def fill(self, sel, val):
        self.filled[sel] = val

    def click(self, sel):
        self.url = self._urls.pop(0) if self._urls else self.url

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def screenshot(self, **kw):
        pass

    def locator(self, sel):
        m = MagicMock()
        m.count.return_value = 0
        return m

    def keyboard_press(self, *a):
        pass

    @property
    def keyboard(self):
        k = MagicMock()
        k.press = lambda *a, **kw: None
        return k


def _fake_playwright(page, capture):
    """sync_playwright() stand-in recording how the browser was launched."""
    ctx = MagicMock()
    ctx.pages = [page]
    ctx.new_page.return_value = page
    ctx.storage_state.return_value = {"cookies": []}

    chromium = MagicMock()

    def _persistent(profile_dir, **kwargs):
        capture["persistent_dir"] = profile_dir
        capture["persistent_kwargs"] = kwargs
        return ctx

    def _launch(**kwargs):
        capture["ephemeral_launch"] = True
        b = MagicMock()
        b.new_context.return_value = ctx
        return b

    chromium.launch_persistent_context.side_effect = _persistent
    chromium.launch.side_effect = _launch

    pw = MagicMock()
    pw.chromium = chromium
    cm = MagicMock()
    cm.__enter__ = lambda _s: pw
    cm.__exit__ = lambda *_a: False
    return cm


def _run_setup(urls, **kwargs):
    """Run setup_session against a scripted URL sequence."""
    import session_manager as sm

    page = _FakePage(urls)
    capture: dict = {}
    with (
        patch("playwright.sync_api.sync_playwright", return_value=_fake_playwright(page, capture)),
        patch.object(sm, "save_credentials"),
        patch.object(sm, "save_session"),
        patch.object(sm, "mark_error"),
        patch.object(sm, "_export_state_to_hub_vault", return_value=True) as vault,
        patch("os.makedirs"),
    ):
        res = sm.setup_session(342, "linkedin", "u@example.com", "pw", **kwargs)
    return res, capture, page, vault


# ---------------------------------------------------------------------------
# Slice 1 — the profile, not a throwaway context
# ---------------------------------------------------------------------------


def test_login_uses_the_persistent_posting_profile_not_an_ephemeral_context():
    """THE #5627 defect. Old code used browser.new_context() and could never fix posting."""
    res, cap, _page, _v = _run_setup(
        ["https://www.linkedin.com/login", "https://www.linkedin.com/feed/",
         "https://www.linkedin.com/feed/"]
    )
    assert cap.get("persistent_dir") == "/profiles/342-linkedin"
    assert not cap.get("ephemeral_launch"), "must NOT log in through a throwaway context"
    assert res["status"] == "active"


def test_login_uses_the_shared_anti_detection_fingerprint():
    """A fingerprint mismatch re-triggers LinkedIn's step-up on a trusted profile."""
    _res, cap, _page, _v = _run_setup(
        ["https://www.linkedin.com/login", "https://www.linkedin.com/feed/",
         "https://www.linkedin.com/feed/"]
    )
    kw = cap["persistent_kwargs"]
    assert "--disable-blink-features=AutomationControlled" in kw["args"]
    assert kw["ignore_default_args"] == ["--enable-automation"]
    assert "Chrome/124" in kw["user_agent"]


def test_active_requires_a_positive_feed_check():
    """Submitting the form is not proof. If the feed still redirects to login the
    result must be 'failed' — the old code returned success here."""
    res, _cap, _page, _v = _run_setup(
        ["https://www.linkedin.com/login",          # initial
         "https://www.linkedin.com/feed/",          # post-submit looks fine
         "https://www.linkedin.com/login"]          # but the feed bounces = NOT authed
    )
    assert res["status"] == "failed"
    assert res["reason"] == "still_logged_out"


def test_already_authenticated_profile_is_left_alone():
    """Idempotent: never retype a password into a healthy profile."""
    res, _cap, page, _v = _run_setup(
        ["https://www.linkedin.com/feed/", "https://www.linkedin.com/feed/"]
    )
    assert res["status"] == "active"
    assert page.filled == {}, "must not submit credentials when already logged in"


def test_unclearable_challenge_reports_needs_2fa_not_success():
    res, _cap, _page, _v = _run_setup(
        ["https://www.linkedin.com/login",
         "https://www.linkedin.com/checkpoint/challenge",
         "https://www.linkedin.com/checkpoint/challenge"],
        auto_code=False,
    )
    assert res["status"] == "needs_2fa"


def test_success_clears_the_calendar_gate_via_the_hub_vault():
    """The calendar reads browser_sessions (platform), which this container does not
    write directly — without the hub export the account stays paused."""
    res, _cap, _page, vault = _run_setup(
        ["https://www.linkedin.com/login", "https://www.linkedin.com/feed/",
         "https://www.linkedin.com/feed/"]
    )
    assert vault.called
    assert res["gate_cleared"] is True


# ---------------------------------------------------------------------------
# Slice 2 — the challenge code
# ---------------------------------------------------------------------------


def test_supplied_verification_code_is_submitted():
    import session_manager as sm

    with patch.object(sm, "_submit_challenge_code") as submit:
        _run_setup(
            ["https://www.linkedin.com/login",
             "https://www.linkedin.com/checkpoint/challenge",
             "https://www.linkedin.com/checkpoint/challenge"],
            verification_code="123456",
        )
    assert submit.called
    assert submit.call_args.args[1] == "123456"


def test_auto_code_is_fetched_with_a_not_before_stamp():
    """Without not_before a STALE code from a previous attempt gets replayed and
    burns one of LinkedIn's limited attempts."""
    import challenge_code
    import session_manager as sm

    with (
        patch.object(challenge_code, "fetch_verification_code", return_value="654321") as fetch,
        patch.object(sm, "_submit_challenge_code"),
    ):
        _run_setup(
            ["https://www.linkedin.com/login",
             "https://www.linkedin.com/checkpoint/challenge",
             "https://www.linkedin.com/checkpoint/challenge"],
        )
    assert fetch.called
    assert fetch.call_args.kwargs.get("not_before"), "must pass a freshness floor"


def test_challenge_code_client_is_inert_without_config():
    """No hub URL / token -> return None quickly rather than poll for 90s."""
    import challenge_code

    with patch.dict(
        os.environ,
        {"PLATFORM_INTERNAL_URL": "", "ARCHIE_PLATFORM_URL": "", "INTERNAL_API_KEY": ""},
        clear=False,
    ):
        assert challenge_code.fetch_verification_code("u@example.com") is None


def test_hub_url_accepts_the_env_name_archie_browser_actually_has():
    """archie_browser is given ARCHIE_PLATFORM_URL; only the LOGIN sidecar gets
    PLATFORM_INTERNAL_URL. Reading one name makes this a permanent silent no-op in
    the very container that needs it."""
    import challenge_code
    import session_manager as sm

    env = {
        "PLATFORM_INTERNAL_URL": "",
        "ARCHIE_PLATFORM_URL": "http://archie_platform:3000",
        "INTERNAL_API_KEY": "k",
    }
    posted = MagicMock()
    posted.status_code = 200
    with patch.dict(os.environ, env, clear=False):
        with patch("requests.post", return_value=posted) as post:
            assert sm._export_state_to_hub_vault(342, "linkedin", {"cookies": []}) is True
        assert "archie_platform:3000" in post.call_args.args[0]

        got = MagicMock()
        got.status_code = 200
        got.json.return_value = {"code": "424242"}
        with patch("requests.get", return_value=got):
            assert challenge_code.fetch_verification_code("u@example.com") == "424242"


# ---------------------------------------------------------------------------
# Caller honesty (the "re-login complete" lie)
# ---------------------------------------------------------------------------


def test_relogin_helper_reports_no_credentials_instead_of_claiming_success():
    import skill_runner

    with patch("session_manager.get_credentials", return_value=None):
        out = skill_runner._attempt_profile_relogin(342, "linkedin")
    assert out["status"] == "no_credentials"


def test_relogin_helper_propagates_needs_2fa():
    """The old caller discarded this and logged 'complete'."""
    import skill_runner

    with (
        patch("session_manager.get_credentials", return_value={"username": "u", "password": "p"}),
        patch("session_manager.setup_session", return_value={"status": "needs_2fa"}),
    ):
        out = skill_runner._attempt_profile_relogin(342, "linkedin")
    assert out["status"] == "needs_2fa"


def test_relogin_helper_survives_a_raising_setup_session():
    import skill_runner

    with (
        patch("session_manager.get_credentials", return_value={"username": "u", "password": "p"}),
        patch("session_manager.setup_session", side_effect=RuntimeError("boom")),
    ):
        out = skill_runner._attempt_profile_relogin(342, "linkedin")
    assert out["status"] == "failed"
