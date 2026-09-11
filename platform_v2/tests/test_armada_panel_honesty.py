"""A.R.M.A.D.A. Cluster sub-tab — panels must not assert things that are false.

Both defects here were found by READING THE LIVE TAB on 2026-09-11, not from a
failing test. Each is the same shape: a panel that is confidently wrong in a way
that looks like normal operation.

1. LOADED MODELS rendered `model_load_state` rows for Outpost-Singapore,
   -Lithuania and -UK — all saved 2026-08-29, the day those VPSs were RETIRED and
   the subscriptions cancelled. Thirteen-day-old rows from machines that no longer
   exist, shown as currently-loaded models. "14 loaded" was really 11.
   ⚠️ NODE HEALTH, on the SAME page, filtered correctly and showed 5. The table
   was never the problem — each panel deciding for itself whether to filter was.

2. The node card rendered a red "0% ok" for USS-246 off TWO dispatches in the
   5-minute window, while that node was actually running 98-99% over the
   preceding 2 hours (331/324 on qwen2.5:1.5b, 157/156 on qwen2.5:7b). Displayed
   beside the hub's 100% from n=214, it read as a node in trouble.

These are source-level assertions: the panels are SQL-in-a-route and a string in
a 6k-line JS file, so there is no seam to unit-test against. A source check that
names the defect is worth more than no check at all — and would have caught both.
"""

import pathlib
import re

import pytest

DHQ = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq"
ROUTES = DHQ / "fleet_dashboard_routes.py"
JS = DHQ / "static" / "js" / "department-hq.js"


def _src(p: pathlib.Path) -> str:
    if not p.exists():
        pytest.skip(f"{p} not reachable from this test root")
    return p.read_text()


class TestLoadedModelsPanel:
    """The panel asserts CURRENT state, so it must constrain liveness AND freshness."""

    def _query(self) -> str:
        src = _src(ROUTES)
        m = re.search(r"SELECT mls\.model_name.*?ORDER BY rn\.node_name, mls\.model_name", src, re.S)
        assert m, "the LOADED MODELS query has moved or been rewritten — re-verify it still filters"
        return m.group(0)

    def test_retired_nodes_cannot_appear(self):
        """status='online' — three RETIRED outposts were being rendered as live."""
        assert "rn.status = 'online'" in self._query()

    def test_stale_rows_cannot_appear(self):
        """saved_at freshness catches the OTHER half: a node that is still 'online'
        but whose state saver (job #46, every 5m) has stopped. status alone would
        render its last known models as current forever."""
        q = self._query()
        assert "mls.saved_at" in q and "INTERVAL" in q

    def test_both_guards_are_present_not_just_one(self):
        """Either alone leaves a real hole open. This is the regression guard."""
        q = self._query()
        assert "rn.status = 'online'" in q and "saved_at" in q, (
            "LOADED MODELS needs BOTH liveness and freshness — a retired node and a "
            "stalled saver are different faults and each renders false 'loaded' models"
        )


class TestNodeCardSuccessRate:
    """A percentage over a tiny sample is noise presented as a fact."""

    def _block(self) -> str:
        src = _src(JS)
        i = src.find("var okPct =")
        assert i > 0, "the node-card okPct computation has moved"
        return src[max(0, i - 700) : i + 300]

    def test_a_minimum_sample_is_required_before_showing_a_percentage(self):
        blk = self._block()
        assert "OK_PCT_MIN_SAMPLE" in blk, "no sample floor — n=2 can render a red 0% ok"
        m = re.search(r"OK_PCT_MIN_SAMPLE\s*=\s*(\d+)", blk)
        assert m and int(m.group(1)) >= 3, "a floor below 3 does not bound the noise"

    def test_the_floor_gates_the_percentage_not_merely_defined(self):
        """⚠️ The constant existing is not the fix — it has to be IN the predicate.
        Defining it and still testing `dispatches5m > 0` would pass a naive grep."""
        blk = self._block()
        m = re.search(r"var okPct\s*=\s*([^;]+);", blk)
        assert m, "okPct assignment not found"
        assert "OK_PCT_MIN_SAMPLE" in m.group(
            1
        ), f"the sample floor is not used in the okPct predicate: {m.group(1).strip()}"

    def test_below_the_floor_it_shows_nothing_rather_than_zero(self):
        """okPct must be null below the floor — the badge already renders '' for
        null. Defaulting to 0 is exactly the false red badge being fixed."""
        blk = self._block()
        m = re.search(r"var okPct\s*=\s*([^;]+);", blk)
        assert ": null" in m.group(1), "below the floor okPct must be null, never 0"


class TestLoadabilityBadgeNamesTheFault:
    """The panel must not collapse two faults with two different fixes into one
    sentence. Measured 2026-09-11: the hub's qwen2.5-coder:7b genuinely could not
    load (a scheduler restart fixed it) while USS-246's dolphin3 loaded fine and
    simply ran 325-392s against a 300s wall (a restart would change nothing).
    A badge reading "N models can no longer load" is wrong about the second, and
    wrong in the expensive direction — it sends the reader to restart a healthy
    scheduler.
    """

    def _panel(self) -> str:
        src = _src(JS)
        i = src.find("data.loadability")
        assert i > 0, "the loadability warning block has moved"
        return src[i : i + 2200]

    def test_the_badge_distinguishes_the_two_kinds(self):
        blk = self._panel()
        assert "too_slow" in blk, "the badge never reads f.kind — both faults render identically"
        assert "cannot load" in blk and "too slow" in blk

    def test_the_counts_are_split_not_summed(self):
        """A single total over both kinds is the same lie with a number on it."""
        blk = self._panel()
        assert "filter(" in blk, "the kinds must be counted separately"

    def test_a_too_slow_row_reports_its_duration_against_the_wall(self):
        """'2 attempts, 0 ok' is true but useless for a deadline fault — the
        actionable number is how far past the wall it actually runs."""
        blk = self._panel()
        assert "success_seconds" in blk and "avg_fail_seconds" in blk

    def test_the_panel_still_builds_text_safely(self):
        """Model and node names reach this from the DB. textContent, never
        innerHTML — the same rule the WTF feed lives under."""
        blk = self._panel()
        assert "innerHTML" not in blk
