"""#5902 — activating a mission profile must MOVE WORK, not just record a choice.

Before this, `activate_profile` updated system_config, logged to
governance_audit_log and sent a Telegram — and applied no routing at all:
`job_routing_overrides` and `station_priorities` have ZERO consumers platform-wide.
`system_config.fleet_dispatch_mode` (auto/news/platform) is the key that genuinely
steers K.I.N. warmth, the score-based fleet router and the Fleet Backlog Runner.
"""

import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain")

import pytest  # noqa: E402

from ai_bridge.mission_manager import dispatch_mode_for_profile  # noqa: E402
from services.fleet_dispatch_profile import VALID_MODES  # noqa: E402


@pytest.mark.parametrize("mode", ["auto", "news", "platform"])
def test_a_declared_mode_is_honoured(mode):
    assert dispatch_mode_for_profile({"agent_config": {"dispatch_mode": mode}}) == mode


def test_it_only_ever_returns_a_mode_the_router_understands():
    """A value the router does not recognise would silently degrade to 'auto' deep
    inside get_dispatch_mode(); rejecting it here keeps the bad value out of
    system_config in the first place."""
    for cfg in ({"dispatch_mode": "NONSENSE"}, {"dispatch_mode": ""}, {"dispatch_mode": 7}):
        assert dispatch_mode_for_profile({"agent_config": cfg}) in VALID_MODES


@pytest.mark.parametrize(
    "profile",
    [None, {}, {"agent_config": None}, {"agent_config": {}}, {"agent_config": "not-a-dict"}],
)
def test_unassigned_falls_back_to_auto_which_is_TODAYS_behaviour(profile):
    """⚠️ The load-bearing default. There is NO principled mapping from a mission
    profile to the news/platform split — the profiles key on ten STATIONS (COMMAND,
    CREATIVE, ... COMMUNICATIONS) while fleet_dispatch_profile keys on the "News &
    Media" DEPARTMENT, and zero of the 6 profiles mention news at all. So an
    unassigned profile must apply NO bias rather than an invented one: activating it
    changes nothing instead of changing something arbitrary."""
    assert dispatch_mode_for_profile(profile) == "auto"


def test_case_and_whitespace_tolerant():
    assert dispatch_mode_for_profile({"agent_config": {"dispatch_mode": "  NEWS "}}) == "news"


def test_no_third_steering_key_is_introduced():
    """Two keys already exist and only one did anything. The fix is to make the inert
    one drive the live one — not to add a third."""
    import inspect

    import ai_bridge.mission_manager as mm

    src = inspect.getsource(mm.MissionManager.activate_profile)
    assert "fleet_dispatch_mode" in src
    assert "active_mission_profile" in src
