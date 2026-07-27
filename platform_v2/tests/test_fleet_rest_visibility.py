"""#5321 — the hardware-rest schedule must be VISIBLE on the A.R.M.A.D.A. cluster view.

EVIDENCE (2026-07-27, owner request): the rest window (20:00-06:00 ET) exists only
as a system_config JSON blob — invisible everywhere. That invisibility produced two
real wrong beliefs in ONE day: "it's past 8PM, Starships are resting" (a UTC/ET
mix-up at 16:00 ET) and "Starships rest at 8PM nightly" (the toggle is actually
enabled=false right now — the schedule everyone treats as fact is NOT armed).

rest_status_snapshot(cfg, now) is the pure, injectable truth for the cluster strip:
  * enabled     — is the toggle on (system_config fleet_hardware_rest)
  * in_window   — is NOW inside the configured window, regardless of toggle
  * active      — enabled AND in_window (the only state that changes routing)
  * window_label / now_et — human-readable, ALWAYS suffixed ET
  * next_transition — kind (rest_start|rest_end from the WINDOW, not the toggle),
    clock label, and minutes until — correct across the midnight-crossing window.
"""

import os
import sys
from datetime import datetime

import pytz

_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

from tools.department_hq import fleet_helpers as fh  # noqa: E402

_TZ = pytz.timezone("America/Toronto")


def _at(hour, minute=0):
    return _TZ.localize(datetime(2026, 7, 27, hour, minute))


CFG_OFF = {"enabled": False, "start_hour": 20, "end_hour": 6}
CFG_ON = {"enabled": True, "start_hour": 20, "end_hour": 6}


class TestSnapshot:
    def test_afternoon_disabled_the_2026_07_27_reality(self):
        """16:00 ET, toggle off — the exact state that produced both wrong beliefs."""
        s = fh.rest_status_snapshot(CFG_OFF, now=_at(16))
        assert s["enabled"] is False
        assert s["in_window"] is False
        assert s["active"] is False
        assert s["window_label"] == "20:00–06:00 ET"
        assert s["now_et"].endswith("ET")
        assert s["next_transition"]["kind"] == "rest_start"
        assert s["next_transition"]["in_minutes"] == 240  # 16:00 -> 20:00

    def test_window_now_but_toggle_off_is_distinguishable(self):
        """23:00 with rest DISABLED: in_window True, active False — the UI must be
        able to say 'window now, but rest is OFF' instead of lying either way."""
        s = fh.rest_status_snapshot(CFG_OFF, now=_at(23))
        assert s["in_window"] is True
        assert s["active"] is False

    def test_resting_crosses_midnight(self):
        s = fh.rest_status_snapshot(CFG_ON, now=_at(23))
        assert s["active"] is True
        assert s["next_transition"]["kind"] == "rest_end"
        assert s["next_transition"]["in_minutes"] == 7 * 60  # 23:00 -> 06:00

    def test_early_morning_still_inside_crossing_window(self):
        s = fh.rest_status_snapshot(CFG_ON, now=_at(5, 30))
        assert s["active"] is True
        assert s["next_transition"]["kind"] == "rest_end"
        assert s["next_transition"]["in_minutes"] == 30

    def test_daytime_enabled_counts_down_to_rest_start(self):
        s = fh.rest_status_snapshot(CFG_ON, now=_at(10))
        assert s["active"] is False
        assert s["next_transition"]["kind"] == "rest_start"
        assert s["next_transition"]["in_minutes"] == 10 * 60

    def test_non_crossing_window(self):
        cfg = {"enabled": True, "start_hour": 9, "end_hour": 17}
        assert fh.rest_status_snapshot(cfg, now=_at(12))["active"] is True
        assert fh.rest_status_snapshot(cfg, now=_at(18))["active"] is False
