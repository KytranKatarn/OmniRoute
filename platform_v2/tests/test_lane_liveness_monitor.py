"""Lane dormancy observer (project #380).

Codex ran last on 2026-06-28 and the engine on 2026-07-20; nobody noticed,
because nothing reported a quiet lane. These tests pin the three rules that
make this observer trustworthy: never-run is UNKNOWN not an alert, a fresh
lane is OK, and a lane past its threshold is STALE.
"""

from datetime import datetime, timedelta, timezone

from services.lane_liveness_monitor import LANES, lane_status

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _row(source, hours_ago):
    return {"module_source": source, "last_dispatch": NOW - timedelta(hours=hours_ago)}


def test_all_three_lanes_are_reported_even_with_no_rows():
    out = lane_status([], NOW)
    assert {d["lane"] for d in out} == set(LANES)


def test_a_lane_that_never_ran_is_unknown_not_stale():
    out = {d["lane"]: d for d in lane_status([], NOW)}
    assert out["codex"]["status"] == "unknown"
    assert out["codex"]["age_hours"] is None


def test_a_recent_lane_is_ok():
    out = {d["lane"]: d for d in lane_status([_row("claude_cli", 1)], NOW)}
    assert out["claude"]["status"] == "ok"
    assert out["claude"]["age_hours"] == 1.0


def test_a_lane_past_its_threshold_is_stale():
    out = {d["lane"]: d for d in lane_status([_row("codex_cli", 24 * 40)], NOW)}
    assert out["codex"]["status"] == "stale"


def test_engine_matches_either_of_its_two_module_sources():
    out = {d["lane"]: d for d in lane_status([_row("archie_code_engine", 2)], NOW)}
    assert out["engine"]["status"] == "ok"


def test_newest_row_wins_when_a_lane_has_several_sources():
    rows = [_row("archie_engine", 500), _row("archie_code_engine", 3)]
    out = {d["lane"]: d for d in lane_status(rows, NOW)}
    assert out["engine"]["age_hours"] == 3.0


def test_observer_is_registered_as_a_scheduled_job():
    """A monitor nobody schedules is exactly the dormancy this fixes."""
    import pathlib

    # CONTROLLER RULING (pre-flight scan): ai_bridge is an IDENTITY mount at
    # /mnt/archie_brain/ai_bridge inside archie_platform -- NOT under /app.
    # Verified in-container. Use the one real path; the plan's /app/../ variant
    # does not exist and would make this test pass only via its fallback.
    src = pathlib.Path("/mnt/archie_brain/ai_bridge/agent_loop.py")
    text = src.read_text()
    assert "lane_liveness_monitor" in text, "observer is never scheduled"
    assert "check_lane_liveness" in text, "scheduled job does not call the checker"


def test_liveness_endpoint_is_on_the_internal_key_surface():
    """The cockpit is a separate container: it has the internal key, not a session.
    #2781 shipped exactly this bug -- a registry gated so its only consumer 401'd."""
    import pathlib

    src = pathlib.Path("/app/app.py")
    if not src.exists():
        src = pathlib.Path("/mnt/archie_brain/platform_v2/app.py")
    text = src.read_text()
    assert "/api/internal/lane-liveness" in text, "endpoint missing"
    idx = text.index("/api/internal/lane-liveness")
    window = text[idx : idx + 1200]
    assert "check_lane_liveness" in window, "route does not call the checker"
    assert "login_required" not in window, "internal route must not be session-gated"
