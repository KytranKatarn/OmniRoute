"""An in-flight review must SAY how long it has run, and be cancellable (#6778).

THE DEFECT: the PR Review tab rendered a bare, disabled "Analyzing…" for every
`in_progress` row. A review that would finish in 40 seconds and one whose dispatch had
died 45 minutes earlier were pixel-identical, and because the Analyze button is disabled
in exactly that state there was no way out of it short of the CLI. Measured live on
archie-platform #3385 and archie-code #71: both read "Reviewing…", one had a live
dispatch on USS-245, the other had already had a dispatch reaped as stale.

Four things are tested, and #3 is the one that protects the real property:

  1. The pure mapping (status, updated_at) -> what the row should say, including the two
     cases that must never be faked: an absent timestamp reads "unknown", never "0m"
     (which would say "just started"), and a tz-naive value must not raise.

  2. The overdue boundary, because the whole point of the marker is to distinguish
     "slow, which is normal" from "overdue, which the reaper should act on".

  3. THE INVARIANT: the UI's overdue threshold IS the reaper's own window, pinned by
     identity rather than by two copies of the number 20. If they drift, the UI
     confidently predicts a recovery that never comes. This is the same class as the
     verdict rule that #2722 had to collapse into one definition.

  4. A guard that the threshold has not leaked into the client, mirroring
     test_merge_state_ui.py: the template renders a decision the server made.
"""

import inspect
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.repair_bay.services import pr_review_service as svc  # noqa: E402
from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    _REAP_STALE_MINUTES,
    reap_stale_reviews,
    review_progress,
)

_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "tools" / "repair_bay.html"
_ROUTES = Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "github_routes.py"

_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _ago(minutes):
    return _NOW - timedelta(minutes=minutes)


class TestReviewProgressMapping(unittest.TestCase):
    def test_only_in_progress_is_active(self):
        """Callers render unconditionally, so every other status must come back inactive."""
        for status in ("reviewed", "pending", "skipped", None, ""):
            p = review_progress(status, _ago(90), now=_NOW)
            self.assertFalse(p["active"], status)
            self.assertIsNone(p["label"], status)
            self.assertFalse(p["stale"], status)

    def test_elapsed_is_reported(self):
        p = review_progress("in_progress", _ago(4), now=_NOW)
        self.assertTrue(p["active"])
        self.assertEqual(p["elapsed_minutes"], 4)
        self.assertIn("4m", p["label"])

    def test_absent_timestamp_reads_unknown_not_zero(self):
        """THE FABRICATION GUARD. Rendering '0m' for a row with no timestamp would say
        'just started' — a claim the data cannot support, and precisely the kind of
        confident-but-unfounded status this change exists to delete."""
        p = review_progress("in_progress", None, now=_NOW)
        self.assertTrue(p["active"])
        self.assertIsNone(p["elapsed_minutes"])
        self.assertEqual(p["label"], "Analyzing…")
        self.assertNotIn("0m", p["label"])
        self.assertFalse(p["stale"], "cannot claim overdue without knowing the elapsed time")
        self.assertIn("unknown", p["hint"].lower())

    def test_naive_timestamp_does_not_raise(self):
        """Several platform tables are `timestamp WITHOUT time zone`, and a naive/aware
        subtraction raises TypeError — which here would blank the row over a formatting
        detail. Documented recurring trap; degrade, never raise."""
        p = review_progress("in_progress", _ago(7).replace(tzinfo=None), now=_NOW)
        self.assertEqual(p["elapsed_minutes"], 7)

    def test_junk_timestamp_degrades_to_unknown(self):
        """The catch in _elapsed_minutes is NARROW (AttributeError/TypeError/ValueError/
        OverflowError) after the F.O.R.G.E. review of #3389. These are the shapes that
        actually arrive from a bad row; each must read "unknown", not crash the listing
        and not fabricate an elapsed time."""
        for junk in ("2026-09-15T12:00:00", 1789518783, object(), []):
            p = review_progress("in_progress", junk, now=_NOW)
            self.assertTrue(p["active"], junk)
            self.assertIsNone(p["elapsed_minutes"], junk)
            self.assertEqual(p["label"], "Analyzing…", junk)
            self.assertFalse(p["stale"], junk)

    def test_future_timestamp_clamps_instead_of_going_negative(self):
        p = review_progress("in_progress", _NOW + timedelta(minutes=3), now=_NOW)
        self.assertEqual(p["elapsed_minutes"], 0)

    def test_hours_are_humanized(self):
        self.assertIn("2h 5m", review_progress("in_progress", _ago(125), now=_NOW)["label"])
        self.assertIn("3h", review_progress("in_progress", _ago(180), now=_NOW)["label"])


class TestOverdueBoundary(unittest.TestCase):
    def test_under_the_window_is_not_overdue(self):
        """A per-file review is several SERIAL dispatches — minutes are normal, and
        crying stale at a healthy review is how a marker becomes noise."""
        p = review_progress("in_progress", _ago(_REAP_STALE_MINUTES - 1), now=_NOW)
        self.assertFalse(p["stale"])

    def test_at_and_past_the_window_is_overdue(self):
        for mins in (_REAP_STALE_MINUTES, _REAP_STALE_MINUTES + 30):
            self.assertTrue(review_progress("in_progress", _ago(mins), now=_NOW)["stale"], mins)

    def test_overdue_hint_names_the_recovery(self):
        """An overdue marker that does not say what happens next is just an alarm."""
        hint = review_progress("in_progress", _ago(45), now=_NOW)["hint"].lower()
        self.assertIn(str(_REAP_STALE_MINUTES), hint)
        self.assertIn("retry", hint)


class TestThresholdIsSharedWithTheReaper(unittest.TestCase):
    """#3 — the property that actually matters."""

    def test_reaper_and_ui_share_one_window(self):
        """Pinned by IDENTITY, not by two copies of the number.

        review_progress only ever PREDICTS what reap_stale_reviews will do. If the two
        thresholds drift, the UI promises a recovery that is not coming (or marks a row
        overdue that the reaper considers healthy).
        """
        reaper_default = inspect.signature(reap_stale_reviews).parameters["stale_minutes"].default
        ui_default = inspect.signature(review_progress).parameters["stale_minutes"].default
        self.assertEqual(reaper_default, _REAP_STALE_MINUTES)
        self.assertEqual(ui_default, _REAP_STALE_MINUTES)
        self.assertEqual(reaper_default, ui_default)

    def test_both_measure_the_same_column(self):
        """The reaper's staleness predicate reads pr_reviews.updated_at; list_reviews must
        hand review_progress that same column. Measuring a different clock than the reaper
        is the subtle way these two fall out of step."""
        reaper_src = inspect.getsource(reap_stale_reviews)
        self.assertIn("updated_at <", reaper_src.replace("\n", " "))
        list_src = inspect.getsource(svc.list_reviews)
        self.assertIn('review_progress(row.get("review_status"), row.get("updated_at"))', list_src)


class TestServerSideOnly(unittest.TestCase):
    """#4 — the template renders a decision; it must not make one."""

    def setUp(self):
        self.tpl = _TEMPLATE.read_text(encoding="utf-8")

    def test_template_consumes_the_server_value(self):
        self.assertIn("review_progress", self.tpl)
        self.assertIn(".stale", self.tpl)

    def test_template_does_not_recompute_elapsed_from_the_row(self):
        """No client-side clock arithmetic on the review row. The existing `_stale` flag
        deliberately measures time since the LIST WAS FETCHED (a different, legitimate
        question); this guard is about the review's own age."""
        code = re.sub(r"//[^\n]*", "", self.tpl)  # strip line comments; they discuss updated_at
        self.assertNotIn("pr.updated_at", code)

    def test_template_does_not_hardcode_the_window(self):
        """A literal 20 in the client is the drift this whole design avoids."""
        window = re.search(r"review_progress.{0,600}", self.tpl, re.S)
        self.assertIsNotNone(window)
        self.assertNotRegex(window.group(0), r"\b%d\b" % _REAP_STALE_MINUTES)


class TestRetryRouteIsNarrow(unittest.TestCase):
    """Retry must never be able to discard a stored verdict.

    The merge gate reads the stored verdict, so resetting a *reviewed* row would let a
    stray click turn a REQUEST CHANGES into a fresh, possibly-different review. The route
    is restricted to in_progress and refuses everything else.
    """

    def setUp(self):
        self.src = _ROUTES.read_text(encoding="utf-8")
        start = self.src.index("def forge_pr_review_retry")
        self.body = self.src[start : start + 3000]

    def test_route_exists_and_is_admin_gated(self):
        self.assertIn('"/api/forge/pr-reviews/<int:pr_number>/retry"', self.src)
        head = self.src[: self.src.index("def forge_pr_review_retry")]
        self.assertIn("@admin_required", head.rsplit("@bp.route", 1)[-1])

    def test_route_refuses_anything_not_in_progress(self):
        self.assertIn('!= "in_progress"', self.body)
        self.assertIn("409", self.body)

    def test_route_validates_and_honours_the_repo(self):
        """PR numbers collide across repos (1-20 each live in 2-5 of them), so a bare
        lookup silently resolves a plausible WRONG row instead of erroring."""
        self.assertIn("_is_valid_repo", self.body)
        self.assertIn("get_review(pr_number, repo=", self.body)
        self.assertIn("mark_review_pending(pr_number, repo=", self.body)


if __name__ == "__main__":
    unittest.main()
