"""Unit tests for the REQUEST-CHANGES defer gate (#3962 follow-up).

Pure-logic tests of `_changes_requested_recently` — no DB. Covers the defer window
(within / outside / default / disabled), missing marker, string-encoded metadata,
and fail-open on bad data. This is the gate that stops a flaky/non-deterministic
APPROVE from auto-merging a PR another review just flagged REQUEST-CHANGES.
"""

import json
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services.time_utils import now_utc  # noqa: E402
from tools.repair_bay.services import pr_review_service as prs  # noqa: E402


def _review(delta: timedelta) -> dict:
    """A pr_reviews row whose changes_requested_at is `delta` in the past."""
    return {"metadata": {"changes_requested_at": (now_utc() - delta).isoformat()}}


def test_within_window_defers():
    assert prs._changes_requested_recently(_review(timedelta(hours=1)), "6") is True


def test_outside_window_allows():
    assert prs._changes_requested_recently(_review(timedelta(hours=10)), "6") is False


def test_default_window_is_6h():
    assert prs._changes_requested_recently(_review(timedelta(hours=2)), None) is True
    assert prs._changes_requested_recently(_review(timedelta(hours=7)), None) is False


def test_disabled_window():
    assert prs._changes_requested_recently(_review(timedelta(hours=1)), "0") is False
    assert prs._changes_requested_recently(_review(timedelta(hours=1)), "-1") is False


def test_no_marker():
    assert prs._changes_requested_recently({"metadata": {}}, "6") is False
    assert prs._changes_requested_recently({}, "6") is False
    assert prs._changes_requested_recently({"metadata": None}, "6") is False


def test_string_encoded_metadata():
    rev = {"metadata": json.dumps({"changes_requested_at": (now_utc() - timedelta(hours=1)).isoformat()})}
    assert prs._changes_requested_recently(rev, "6") is True


def test_fail_open_on_bad_data():
    assert prs._changes_requested_recently({"metadata": {"changes_requested_at": "not-a-date"}}, "6") is False
    assert prs._changes_requested_recently({"metadata": "not-json"}, "6") is False
    assert prs._changes_requested_recently(_review(timedelta(hours=1)), "garbage") is True  # bad env -> default 6h
