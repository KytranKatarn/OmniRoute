"""WTF consumer OAuth: state validation (login-CSRF) + open redirect — #6150.

Measured 2026-08-30 against the LIVE site before the fix: `/login` emitted
`.../oauth/authorize?client_id=wtf-consumer&redirect_uri=...&response_type=code`
with **no `state` at all**, and `/auth/callback` read only `code`. There was
nothing to validate, so any attacker-supplied code completed a login into the
victim's browser session (classic login-CSRF), and `?next=` flowed unchecked
into the post-login `redirect()`.

This is a SEPARATE implementation from the shared `kytran_auth` client that the
rest of the fleet uses (KB #299307) — WTF has no `/auth/kytran/*` routes at all,
and `shared/kytran_auth.py` is only a re-export shim, so grepping THAT file for
the shared fix proves nothing about this one.

`consumer/auth.py` imports only flask + stdlib + `.tiers`, so these tests import
it directly and can never silently skip (KB #290497).
"""

import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consumer.auth import _safe_next, auth_bp  # noqa: E402


@pytest.fixture()
def client():
    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test-only-not-a-real-secret"
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.register_blueprint(auth_bp)
    return app.test_client()


class TestSafeNext:
    """Only a same-site relative path may survive."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "//evil.com",              # protocol-relative — browsers resolve off-site
            "///evil.com",
            "https://evil.com",        # absolute
            "http://evil.com",
            "/\\evil.com",             # backslash — browsers normalise to //
            "\\\\evil.com",
            "javascript:alert(1)",
            "  //evil.com",            # leading whitespace must not smuggle it through
        ],
    )
    def test_off_site_targets_fall_back_to_default(self, hostile):
        assert _safe_next(hostile) == "/"

    @pytest.mark.parametrize("empty", [None, "", "   ", 0, [], {}])
    def test_empty_and_non_string_fall_back(self, empty):
        assert _safe_next(empty) == "/"

    @pytest.mark.parametrize(
        "ok",
        ["/", "/account", "/news?beat=municipal", "/entity/42#chain", "/a/b/c"],
    )
    def test_same_site_paths_are_preserved(self, ok):
        assert _safe_next(ok) == ok

    def test_custom_default_is_honoured(self):
        assert _safe_next("//evil.com", default="/home") == "/home"


class TestSessionCookieSameSite:
    """The state check depends on the session cookie surviving the callback.

    The callback is a top-level GET from platform.kytranempowerment.com, i.e.
    cross-site: "Lax" still sends the cookie, "Strict" would not and every real
    login would fail the check. It must therefore be stated, not inherited from
    a browser default.
    """

    def test_setdefault_is_a_noop_on_flask_config(self):
        """Why app.py must use direct assignment.

        Flask PRE-POPULATES SESSION_COOKIE_SAMESITE with None, so the key
        already exists and setdefault() never fires. Measured live: the first
        version of this fix used setdefault and the Set-Cookie header still
        carried no SameSite at all.
        """
        from flask import Flask

        probe = Flask(__name__)
        assert "SESSION_COOKIE_SAMESITE" in probe.config  # key exists, value None
        probe.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
        assert probe.config["SESSION_COOKIE_SAMESITE"] is None, "setdefault should be inert"
        probe.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        assert probe.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_app_factory_sets_samesite_effectively(self):
        """Assert on the SOURCE of the factory, not a hand-built test app.

        The `client` fixture sets SameSite itself, so it can never catch a
        factory that fails to — which is precisely how the setdefault bug
        survived a green suite.
        """
        src = (ROOT / "consumer" / "app.py").read_text()
        assert 'app.config["SESSION_COOKIE_SAMESITE"] = "Lax"' in src, (
            "the factory must assign SameSite directly; setdefault is inert here"
        )
        assert 'setdefault("SESSION_COOKIE_SAMESITE"' not in src


class TestLoginMintsState:
    def test_authorize_url_carries_a_state(self, client):
        r = client.get("/login")
        assert r.status_code == 302
        assert "state=" in r.headers["Location"], (
            "no state on the authorize URL means there is nothing to validate "
            "at the callback — this is the whole vulnerability"
        )

    def test_state_is_persisted_for_the_callback_to_check(self, client):
        with client:
            client.get("/login")
            from flask import session

            assert session.get("wtf_oauth_state")
            assert len(session["wtf_oauth_state"]) >= 20  # not a guessable token

    def test_two_logins_mint_different_states(self, client):
        seen = set()
        for _ in range(2):
            with client:
                client.get("/login")
                from flask import session

                seen.add(session["wtf_oauth_state"])
        assert len(seen) == 2, "a constant state is as good as no state"

    def test_hostile_next_never_reaches_the_session(self, client):
        with client:
            client.get("/login?next=//evil.com")
            from flask import session

            assert session["wtf_next"] == "/"

    def test_legitimate_next_is_kept(self, client):
        with client:
            client.get("/login?next=/account")
            from flask import session

            assert session["wtf_next"] == "/account"


class TestCallbackRequiresState:
    """Each case must be refused BEFORE the token exchange.

    The marker `?login=state_error` is the evidence: a token-exchange failure
    also redirects, so without a distinct destination a vulnerable build and a
    fixed one are indistinguishable to a probe (mistake KB #299308).
    """

    def _rejected(self, resp):
        return resp.status_code == 302 and "login=state_error" in resp.headers["Location"]

    def test_no_state_at_all_is_refused(self, client):
        # THE bug: with no state in the query and none in the session, an
        # equality comparison of two absent values authorises the request.
        assert self._rejected(client.get("/auth/callback?code=attacker_code"))

    def test_state_present_but_no_session_state_is_refused(self, client):
        assert self._rejected(client.get("/auth/callback?code=x&state=guessed"))

    def test_mismatched_state_is_refused(self, client):
        with client:
            client.get("/login")
            assert self._rejected(client.get("/auth/callback?code=x&state=wrong"))

    def test_empty_state_param_is_refused(self, client):
        with client:
            client.get("/login")
            assert self._rejected(client.get("/auth/callback?code=x&state="))

    def test_matching_state_gets_PAST_the_state_check(self, client):
        """The fix must not simply refuse everything.

        A real login carries the minted state; it must reach the token
        exchange. That exchange fails here (no platform in a unit test) and
        redirects to "/" — the point is only that it is NOT `state_error`.
        """
        with client:
            client.get("/login")
            from flask import session

            good = session["wtf_oauth_state"]
            r = client.get(f"/auth/callback?code=x&state={good}")
        assert r.status_code == 302
        assert "login=state_error" not in r.headers["Location"], (
            "a valid state was rejected — this would break every real login"
        )

    def test_state_is_single_use(self, client):
        with client:
            client.get("/login")
            from flask import session

            good = session["wtf_oauth_state"]
            client.get(f"/auth/callback?code=x&state={good}")
            # replaying the same callback URL must not authenticate again
            assert self._rejected(client.get(f"/auth/callback?code=x&state={good}"))

    def test_missing_code_still_short_circuits(self, client):
        r = client.get("/auth/callback")
        assert r.status_code == 302 and r.headers["Location"] == "/"
