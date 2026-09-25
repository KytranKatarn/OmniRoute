"""A long review must refresh its own staleness clock, and never resurrect a dead row.

Before this, `pr_reviews.updated_at` was written only at `mark_review_started` and
`mark_review_done`, so a review looked frozen for its entire duration. That survived
only by accident: the poll upsert re-stamped `updated_at` on every OPEN pr each cycle,
keeping the clock warm as a side effect. #3416 removed that re-stamping — correctly,
it was defeating `reap_stale_reviews` entirely — and thereby removed the accidental
protection.

Measured minutes after that deploy:
    #3411  in_progress, reap_count 1   — reaped MID-FLIGHT
    #3406  in_progress, age 16:20      — a ONE-FILE pr, against a 20-minute window
With `forge:review_plan=per_file` and `forge:review_max_files=10` live, a real review
is ten serial passes, so it would be reaped ~3 times and then marked 'skipped'.

⚠️ RESIDUAL, deliberately not fixed here: a SINGLE long pass (max_chunks=1 /
max_files=1) still has no heartbeat, because there is no pass boundary to hang one on.
There is no per-pass timeout constant in pr_diff_analyzer to derive a defensible
threshold from either, so raising _REAP_STALE_MINUTES would be a guess. Tracked
separately rather than guessed at.
"""

from __future__ import annotations

import os
import re

import pytest

from tools.repair_bay.services import pr_review_service as prs

ANALYZER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "repair_bay",
    "services",
    "pr_diff_analyzer.py",
)


class _FakeCur:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self.params = params


class _FakeCtx:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *a):
        return False


@pytest.fixture
def cur(monkeypatch):
    c = _FakeCur()
    monkeypatch.setattr(prs, "get_db_cursor", lambda commit=False: _FakeCtx(c))
    return c


class TestMarkReviewProgress:
    def test_it_stamps_updated_at(self, cur):
        prs.mark_review_progress(42, repo="o/r")
        assert "SET updated_at=NOW()" in cur.sql, cur.sql

    def test_it_is_scoped_to_in_progress(self, cur):
        # Load-bearing: a heartbeat arriving after the review was reaped, skipped or
        # finished must be a no-op, never a resurrection.
        prs.mark_review_progress(42, repo="o/r")
        assert "review_status='in_progress'" in cur.sql, cur.sql

    def test_it_targets_one_pr_and_repo(self, cur):
        prs.mark_review_progress(42, repo="own/repo")
        assert "pr_number=%s" in cur.sql and "repo=%s" in cur.sql
        assert cur.params == (42, "own/repo")

    def test_it_does_not_touch_review_status(self, cur):
        # A heartbeat says "still working"; it must not CHANGE the state.
        prs.mark_review_progress(42, repo="o/r")
        assert "SET review_status" not in cur.sql, cur.sql

    def test_true_when_a_row_was_touched(self, cur):
        cur.rowcount = 1
        assert prs.mark_review_progress(42, repo="o/r") is True

    def test_false_when_the_row_was_already_terminal(self, monkeypatch):
        c = _FakeCur(rowcount=0)
        monkeypatch.setattr(prs, "get_db_cursor", lambda commit=False: _FakeCtx(c))
        # Returning False rather than raising lets the caller log-and-continue: a
        # review whose row was reaped out from under it should finish, not crash.
        assert prs.mark_review_progress(42, repo="o/r") is False
    def test_start_stamps_a_total_run_clock(self, cur):
        prs.mark_review_started(42, repo="o/r")
        assert "review_started_at" in cur.sql, cur.sql
        assert "review_file_progress" in cur.sql, cur.sql

    def test_file_progress_is_best_effort_and_state_scoped(self, cur):
        assert prs.mark_review_file_progress(42, repo="o/r", progress={"files": []}) is True
        assert "review_status='in_progress'" in cur.sql
        assert "review_file_progress" in cur.sql

    def test_invalid_file_progress_is_not_written(self, cur):
        assert prs.mark_review_file_progress(42, repo="o/r", progress=None) is False
        assert cur.sql is None


def _analyzer():
    with open(ANALYZER, "r") as fh:
        return fh.read()


class TestWiredIntoThePassLoop:
    """A function nobody calls is not a heartbeat. #5194/#5862 are the house precedent."""

    def test_the_pass_loop_calls_it(self):
        src = _analyzer()
        assert "mark_review_progress" in src, "the heartbeat is defined but never called"

    def test_the_call_is_inside_the_chunk_loop(self):
        src = _analyzer()
        i_loop = src.index("for _idx, _chunk in enumerate(_chunks):")
        # Locate the CALL, not the import: the name is now imported at module top.
        i_call = src.index("mark_review_progress(pr_number, repo)")
        # The next pass boundary after the loop header — not somewhere outside it.
        i_next_def = src.index("\ndef ", i_loop)
        assert i_loop < i_call < i_next_def, "the heartbeat must fire inside the pass loop"

    def test_file_progress_is_published_at_pass_boundaries(self):
        src = _analyzer()
        assert src.count("_publish_file_progress(") >= 3

    def test_it_cannot_fail_the_review(self):
        # A monitoring write must never break the thing it monitors.
        src = _analyzer()
        seg = src[src.index("for _idx, _chunk in enumerate(_chunks):") :][:2000]
        assert "mark_review_progress" in seg
        assert re.search(
            r"try:\s*\n.*?mark_review_progress", seg, re.S
        ), "the heartbeat call must be wrapped so a DB blip cannot abort the review"

    def test_it_is_skipped_on_the_first_pass(self):
        # mark_review_started just stamped the clock; pass 0 would be a wasted UPDATE.
        src = _analyzer()
        seg = src[src.index("for _idx, _chunk in enumerate(_chunks):") :][:2000]
        assert "if _idx:" in seg, "pass 0 should not re-stamp what mark_review_started just set"
