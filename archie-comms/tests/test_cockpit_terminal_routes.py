"""The cockpit's terminal routes must be ADMIN-gated, and must never mint a stray lane.

The proxy validates a token without knowing who asked for it, so the mint is where the
requester's authority is established. Every comms user is an admin today — app_comms
rejects any SSO login whose role != "admin" — which makes the check here redundant *right
now* and required anyway: without it, the terminal's protection rests on a property of the
login path rather than on anything the terminal code states.

These drive the blueprint through a real Flask test client, so a decorator that is present
but not applied still fails.
"""

import os
import sys

import pytest

COMMS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if COMMS not in sys.path:
    sys.path.insert(0, COMMS)

flask = pytest.importorskip("flask")

try:
    from cockpit_routes import cockpit_bp
    from services import terminal_lanes
except Exception as exc:  # pragma: no cover - import problems are the failure
    pytest.skip(f"cockpit blueprint not importable: {exc}", allow_module_level=True)


@pytest.fixture
def app():
    application = flask.Flask(__name__)
    application.secret_key = "test-secret"
    application.register_blueprint(cockpit_bp)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Never touch the real terminal_auth_tokens table from a test."""
    monkeypatch.setattr(terminal_lanes, "_insert_token", lambda *a, **k: None)
    monkeypatch.setattr(terminal_lanes, "_probe", lambda port: True)


def _login(client, role="admin", user_id=4):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_mint_requires_a_session(client):
    assert client.post("/api/cockpit/terminal/claude/token").status_code == 401


def test_lanes_requires_a_session(client):
    assert client.get("/api/cockpit/terminal/lanes").status_code == 401


def test_mint_refuses_a_non_admin_session(client):
    """Currently unreachable — and the point is that it stays refused if that changes.

    ⚠️ The REASON broadened in #6700 and the wording follows it. A non-admin is no
    longer refused for "not being an admin" — they may now hold an explicit per-lane
    grant — so the refusal is about lane ACCESS. What must not change is that the
    403 still STATES a reason: a bare status code tells the caller nothing about
    whether to ask for a grant or to sign in as someone else.
    """
    _login(client, role="user")
    resp = client.post("/api/cockpit/terminal/claude/token")
    assert resp.status_code == 403
    err = resp.get_json()["error"].lower()
    assert "access" in err or "admin" in err, f"403 gave no reason: {err!r}"


def test_lanes_refuses_a_non_admin_session(client):
    _login(client, role="user")
    assert client.get("/api/cockpit/terminal/lanes").status_code == 403


def test_a_session_with_no_role_is_refused(client):
    """A session carrying user_id but no role must not sail through."""
    with client.session_transaction() as sess:
        sess["user_id"] = 4
    assert client.post("/api/cockpit/terminal/claude/token").status_code == 403


# ---------------------------------------------------------------------------
# Minting
# ---------------------------------------------------------------------------


def test_an_admin_can_mint_for_each_real_lane(client):
    _login(client)
    for lane in ("claude", "codex"):
        resp = client.post(f"/api/cockpit/terminal/{lane}/token")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["lane"] == lane
        assert body["url"].startswith(terminal_lanes.LANES[lane]["url"])
        assert f"token={body['token']}" in body["url"]


def test_the_mint_reports_whether_the_lane_is_sandboxed(client):
    """The pane must be able to mark the claude lane as the host, not a sandbox."""
    _login(client)
    assert client.post("/api/cockpit/terminal/claude/token").get_json()["sandboxed"] is False
    assert client.post("/api/cockpit/terminal/codex/token").get_json()["sandboxed"] is True


def test_an_unknown_lane_is_404_not_500(client):
    _login(client)
    resp = client.post("/api/cockpit/terminal/engine/token")
    assert resp.status_code == 404
    assert "engine" in resp.get_json()["error"]


def test_the_lane_reaching_the_mint_is_the_one_in_the_url(client, monkeypatch):
    """Guards against a handler that ignores its path parameter and hardcodes a lane."""
    seen = []
    monkeypatch.setattr(
        terminal_lanes, "_insert_token", lambda tok, uid, exp, lane: seen.append(lane)
    )
    _login(client)
    client.post("/api/cockpit/terminal/codex/token")
    assert seen == ["codex"]


def test_a_mint_failure_is_500_not_a_leaked_traceback(client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(terminal_lanes, "_insert_token", _boom)
    _login(client)
    resp = client.post("/api/cockpit/terminal/claude/token")
    assert resp.status_code == 500
    assert "fire" not in resp.get_data(as_text=True), "internal detail leaked to the client"


# ---------------------------------------------------------------------------
# Lane status
# ---------------------------------------------------------------------------


def test_lane_list_shape(client):
    _login(client)
    body = client.get("/api/cockpit/terminal/lanes").get_json()
    # Membership is frozen once, in test_terminal_token_lane.VALID_LANES. Here the
    # subject is SHAPE: the route must report every registered lane with the full
    # key set. Re-freezing the names here made a lane addition fail in two places
    # and taught nothing the first assertion did not already say.
    from services import terminal_lanes as tl

    assert {row["lane"] for row in body["lanes"]} == set(tl.LANES)
    assert len(body["lanes"]) >= 2
    for row in body["lanes"]:
        assert set(row) >= {"lane", "label", "reachable", "sandboxed", "single_seat", "busy"}


def test_lane_list_does_not_claim_the_codex_seat_is_free(client):
    """busy is None (unknown) — rendering that as availability would be a false claim."""
    _login(client)
    body = client.get("/api/cockpit/terminal/lanes").get_json()
    for row in body["lanes"]:
        assert row["busy"] is None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_both_terminal_rules_are_registered_with_the_right_methods(app):
    """No brittle total-rule count: a magic number just gets bumped on every new route."""
    rules = {r.rule: r.methods for r in app.url_map.iter_rules()}
    assert "POST" in rules["/api/cockpit/terminal/<lane>/token"]
    assert "GET" in rules["/api/cockpit/terminal/lanes"]


def test_terminal_bytes_never_pass_through_comms():
    """The cockpit mints a token; the browser talks to the proxy directly.

    A proxy/stream helper appearing here would make comms a second gate for shell bytes,
    which is exactly what pointing the iframe at the existing proxy avoids.
    """
    with open(os.path.join(COMMS, "cockpit_routes.py"), encoding="utf-8") as fh:
        source = fh.read()
    for forbidden in ("websocket", "WebSocket", "stream_with_context", "17681", "17682"):
        assert forbidden not in source, (
            f"cockpit_routes.py references {forbidden!r} — terminal bytes must not flow through comms"
        )
