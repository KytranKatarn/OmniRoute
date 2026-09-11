"""may_use_lane is THE authorization answer for a terminal lane (#6700).

Owner decision 2026-09-11: "explicit per-user allowlist". Admins get every lane by
ROLE; everyone else gets only the lanes explicitly granted in terminal_lane_grants.

WHY THIS EXISTS AT ALL: until now "lanes are admin-only" was true by accident of the
login path — on_sso_login discards any session whose role != admin, so no non-admin
session exists to test against. That is a property of the LOGIN, not of the terminal.
The archie-tui lane is meant for approved staff who are NOT platform admins, and the
moment that ships, an accident stops being a guarantee.

So most of these tests drive states the system cannot currently produce. That is the
point: they pin the rule for when it can.

The DB seam (_live_grant_exists) is replaced throughout — these are tests of the
RULE, not of Postgres.
"""

import os
import sys

import pytest

COMMS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if COMMS not in sys.path:
    sys.path.insert(0, COMMS)

try:
    from services import terminal_lanes as tl
except Exception as exc:  # pragma: no cover
    pytest.skip(f"terminal_lanes not importable: {exc}", allow_module_level=True)

LANES = sorted(tl.LANES)
HOST_LANES = sorted(k for k, c in tl.LANES.items() if not c.get("sandboxed"))


@pytest.fixture
def no_grants(monkeypatch):
    monkeypatch.setattr(tl, "_live_grant_exists", lambda uid, lane: False)


@pytest.fixture
def all_granted(monkeypatch):
    monkeypatch.setattr(tl, "_live_grant_exists", lambda uid, lane: True)


class TestAdminsAreAllowedByRole:
    @pytest.mark.parametrize("lane", LANES)
    def test_admin_needs_no_grant(self, lane, no_grants):
        """Admins are deliberately NOT rows in the grants table — one source of truth
        per question. If an admin needed a grant, revoking it would silently demote a
        platform administrator."""
        assert tl.may_use_lane(4, "admin", lane) is True


class TestNonAdminsNeedAnExplicitGrant:
    @pytest.mark.parametrize("lane", LANES)
    def test_refused_without_a_grant(self, lane, no_grants):
        assert tl.may_use_lane(77, "user", lane) is False

    @pytest.mark.parametrize("lane", LANES)
    def test_allowed_with_a_grant(self, lane, all_granted):
        assert tl.may_use_lane(77, "user", lane) is True

    def test_a_grant_is_per_lane_not_global(self, monkeypatch):
        """The whole point of a per-user allowlist: access to the CONTAINED codex lane
        must not imply access to a HOST shell."""
        monkeypatch.setattr(
            tl, "_live_grant_exists", lambda uid, lane: lane == "codex"
        )
        assert tl.may_use_lane(77, "user", "codex") is True
        for lane in HOST_LANES:
            assert tl.may_use_lane(77, "user", lane) is False, (
                f"a codex grant leaked into {lane}, which is a HOST shell"
            )


class TestItFailsClosed:
    """A terminal is the last thing that should fail open."""

    def test_unknown_lane_refused(self, all_granted):
        assert tl.may_use_lane(4, "admin", "nope") is False
        assert tl.may_use_lane(4, "admin", "") is False

    @pytest.mark.parametrize("user_id", [None, 0, ""])
    def test_missing_user_refused(self, user_id, all_granted):
        assert tl.may_use_lane(user_id, "admin", "claude") is False

    def test_database_error_refuses_rather_than_allows(self, monkeypatch):
        """A DB blip is not a reason to hand someone a host shell. This is the
        difference between fail-closed and fail-open, and it is the only behaviour
        here that an outage will ever exercise."""

        def boom(uid, lane):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(tl, "_live_grant_exists", boom)
        assert tl.may_use_lane(77, "user", "claude") is False

    def test_none_role_refused(self, no_grants):
        """A session carrying no role at all — the shape a future non-SSO login path
        would most plausibly produce."""
        assert tl.may_use_lane(77, None, "claude") is False


class TestGrantWritesAreGuarded:
    def test_granting_an_unknown_lane_raises(self):
        """Refuse at the WRITE too. A grant row naming a lane that does not exist is
        a latent surprise: register that name later and the grant silently activates."""
        with pytest.raises(tl.UnknownLane):
            tl.grant_lane(77, "nope", granted_by=4)
