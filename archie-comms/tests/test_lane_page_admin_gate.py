"""Every terminal SURFACE refuses a non-admin — the page, not just the mint.

Owner, 2026-09-11: "just ensure they are all admin protected so that no one can
access the terminals pages."

The mint (`/api/cockpit/terminal/<lane>/token`) was already admin-gated; the PAGE
at `/<lane>/terminal` was only session-gated. In practice nothing got through,
because `on_sso_login` discards any session whose role != "admin" — so there is no
non-admin session to have. That is exactly the problem: the page's protection was a
property of the LOGIN PATH, not something the terminal code asserted. A later change
admitting non-admins to comms for some unrelated feature would have handed them the
terminal page silently, and nothing here would have failed.

So these tests fabricate the session that cannot currently exist — authenticated,
role != "admin" — and require a refusal anyway. They are deliberately testing a
state the system does not produce today, because the whole point is to keep the
guarantee when it does.

The landing page is NOT gated and must not be: it is the public front door that
carries the "Connect with Kytran Empowerment" CTA, so it has to render logged-out.
"""

import os
import sys

import pytest

COMMS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if COMMS not in sys.path:
    sys.path.insert(0, COMMS)

pytest.importorskip("flask")

# app_comms refuses to import without a persistent SECRET_KEY (OAuth sessions must
# survive across gunicorn workers). A test-only value satisfies that without
# touching the real one — and without this the whole module SKIPPED, which for an
# authorization test is worse than useless: it would report green while proving
# nothing about who can reach a shell.
os.environ.setdefault("SECRET_KEY", "test-only-value-never-used-in-production")

try:
    import app_comms
    from services import terminal_lanes
except Exception as exc:  # pragma: no cover
    pytest.skip(f"app_comms not importable: {exc}", allow_module_level=True)

LANES = sorted(terminal_lanes.LANES)


@pytest.fixture
def client():
    app_comms.app.config["TESTING"] = True
    return app_comms.app.test_client()


def _session(client, **values):
    with client.session_transaction() as sess:
        sess.clear()
        sess.update(values)


ADMIN = {"user_id": 4, "kytran_user": {"sub": 4}, "username": "kytran", "role": "admin"}
# The session that cannot exist today. See the module docstring.
NON_ADMIN = {"user_id": 77, "kytran_user": {"sub": 77}, "username": "someone", "role": "user"}
# Authenticated by the legacy key only, with no role at all — the shape a future
# non-SSO login path would most plausibly produce.
NO_ROLE = {"user_id": 88, "username": "legacy"}


class TestTerminalPageRefusesNonAdmins:
    @pytest.mark.parametrize("lane", LANES)
    def test_anonymous_is_sent_to_the_front_door(self, client, lane):
        _session(client)
        r = client.get(f"/{lane}/terminal")
        assert r.status_code == 302, f"{lane}: anonymous got {r.status_code}, expected a redirect"
        assert r.headers["Location"].endswith(f"/{lane}"), r.headers["Location"]

    @pytest.mark.parametrize("lane", LANES)
    def test_authenticated_non_admin_is_refused(self, client, lane):
        """The case the login path currently makes impossible. Refuse it anyway."""
        _session(client, **NON_ADMIN)
        r = client.get(f"/{lane}/terminal")
        assert r.status_code == 302, (
            f"{lane}: a signed-in NON-ADMIN received {r.status_code} — the terminal page "
            f"must never render for them"
        )
        assert "denied=admin" in r.headers["Location"], r.headers["Location"]

    @pytest.mark.parametrize("lane", LANES)
    def test_session_with_no_role_at_all_is_refused(self, client, lane):
        """Fail CLOSED on a missing role, never open."""
        _session(client, **NO_ROLE)
        r = client.get(f"/{lane}/terminal")
        assert r.status_code == 302 and "denied=admin" in r.headers["Location"], (
            f"{lane}: a session carrying no role reached the terminal page"
        )

    @pytest.mark.parametrize("lane", LANES)
    def test_admin_gets_the_page(self, client, lane):
        """The gate must not be so tight it locks out the person it is for."""
        _session(client, **ADMIN)
        r = client.get(f"/{lane}/terminal")
        assert r.status_code == 200, f"{lane}: an ADMIN was refused ({r.status_code})"
        assert b"about:blank" in r.data, "the terminal frame should start unmounted"


class TestTheMintIsGatedToo:
    """Belt and braces: the page gate must not be the only thing standing there.
    A page can be bypassed by calling the API directly."""

    @pytest.mark.parametrize("lane", LANES)
    def test_non_admin_cannot_mint(self, client, lane):
        _session(client, **NON_ADMIN)
        r = client.post(f"/api/cockpit/terminal/{lane}/token")
        assert r.status_code == 403, f"{lane}: non-admin minted a shell token ({r.status_code})"

    @pytest.mark.parametrize("lane", LANES)
    def test_anonymous_cannot_mint(self, client, lane):
        _session(client)
        r = client.post(f"/api/cockpit/terminal/{lane}/token")
        assert r.status_code == 401, f"{lane}: anonymous reached the mint ({r.status_code})"


class TestTheLandingPageStaysPublic:
    """Not an oversight — the front door carries the sign-in CTA, so gating it
    would make signing in impossible."""

    @pytest.mark.parametrize("lane", LANES)
    def test_landing_renders_logged_out(self, client, lane):
        _session(client)
        r = client.get(f"/{lane}")
        assert r.status_code == 200, f"{lane}: the public landing page returned {r.status_code}"
        assert b"Connect with Kytran Empowerment" in r.data, (
            f"{lane}: the landing page lost its SSO CTA — there is then no way to sign in"
        )

    @pytest.mark.parametrize("lane", LANES)
    def test_landing_never_leaks_a_terminal(self, client, lane):
        """It links TO the terminal; it must not embed one."""
        _session(client)
        r = client.get(f"/{lane}")
        assert b"<iframe" not in r.data, f"{lane}: the public landing page embeds a frame"
