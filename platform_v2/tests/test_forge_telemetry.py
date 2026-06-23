"""Unit tests for ST-4: F.O.R.G.E. review-path telemetry + settings snapshot.

- _extract_review_path: classify a review's path from its '[review-meta] structured=<x>' line.
- get_forge_review_metrics: structured-vs-freeform breakdown (prefers stamped metadata, falls back
  to parsing ai_summary) — a sharp drop in structured_ratio signals a silent regression.
- forge_settings_snapshot: effective values of every forge:* knob (no seeded rows, no drift).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def prs():
    from tools.repair_bay.services import pr_review_service

    return pr_review_service


@pytest.fixture
def pda():
    from tools.repair_bay.services import pr_diff_analyzer

    return pr_diff_analyzer


# --------------------------------------------------------------------------- #
# _extract_review_path                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,expected",
    [
        ("SUMMARY\n...\nVERDICT: APPROVE\n[review-meta] structured=json model=default confidence=1.0", "json"),
        ("...\nVERDICT: REQUEST CHANGES\n[review-meta] structured=freeform-gated dropped 1 issue", "freeform-gated"),
        ("SUMMARY\nblah\nVERDICT: APPROVE\nNo issues found.", "freeform"),  # verdict, no meta line
        ("just some prose, no verdict, no meta", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_extract_review_path(prs, text, expected):
    assert prs._extract_review_path(text) == expected


# --------------------------------------------------------------------------- #
# get_forge_review_metrics                                                     #
# --------------------------------------------------------------------------- #


class _FakeCur:
    def __init__(self, rows, raise_on_execute=False):
        self._rows = rows
        self._raise = raise_on_execute

    def execute(self, *a, **k):
        if self._raise:
            raise RuntimeError("db down")

    def fetchall(self):
        return self._rows


class _FakeCtx:
    def __init__(self, rows, raise_on_execute=False):
        self._rows = rows
        self._raise = raise_on_execute

    def __enter__(self):
        return (None, _FakeCur(self._rows, self._raise))

    def __exit__(self, *a):
        return False


def test_metrics_counts_and_ratio(prs):
    rows = [
        {"stamped": "json", "ai_summary": ""},
        {"stamped": "json", "ai_summary": ""},
        {"stamped": "freeform-gated", "ai_summary": ""},
        # unstamped -> falls back to parsing ai_summary (which is a json-path review)
        {"stamped": None, "ai_summary": "VERDICT: APPROVE\n[review-meta] structured=json"},
    ]
    with patch.object(prs, "get_db_cursor", lambda *a, **k: _FakeCtx(rows)):
        m = prs.get_forge_review_metrics(7)
    assert m["total"] == 4
    assert m["counts"]["json"] == 3
    assert m["counts"]["freeform-gated"] == 1
    assert m["structured_ratio"] == pytest.approx(0.75)


def test_metrics_empty(prs):
    with patch.object(prs, "get_db_cursor", lambda *a, **k: _FakeCtx([])):
        m = prs.get_forge_review_metrics(7)
    assert m["total"] == 0 and m["structured_ratio"] is None


def test_metrics_tuple_rows(prs):
    # Some cursors return tuples (stamped, ai_summary) instead of dicts.
    rows = [("freeform", ""), (None, "VERDICT: APPROVE\n[review-meta] structured=json")]
    with patch.object(prs, "get_db_cursor", lambda *a, **k: _FakeCtx(rows)):
        m = prs.get_forge_review_metrics(7)
    assert m["counts"]["freeform"] == 1 and m["counts"]["json"] == 1 and m["total"] == 2


def test_metrics_db_error_is_safe(prs):
    with patch.object(prs, "get_db_cursor", lambda *a, **k: _FakeCtx([], raise_on_execute=True)):
        m = prs.get_forge_review_metrics(7)
    assert m["total"] == 0 and m["structured_ratio"] is None and "error" in m


# --------------------------------------------------------------------------- #
# forge_settings_snapshot                                                      #
# --------------------------------------------------------------------------- #


def test_settings_snapshot_keys(pda):
    snap = pda.forge_settings_snapshot()
    for key in (
        "forge:structured_review_enabled",
        "forge:review_num_ctx",
        "forge:json_reprompt_enabled",
        "forge:self_refute_failclosed_enabled",
        "forge:review_confidence_min",
        "diff_cap_7b",
        "diff_cap_strong",
    ):
        assert key in snap
    # derived caps are ints; the 7B cap never exceeds the strong cap
    assert isinstance(snap["diff_cap_7b"], int) and isinstance(snap["diff_cap_strong"], int)
    assert snap["diff_cap_7b"] <= snap["diff_cap_strong"]


def test_settings_snapshot_reads_live_flags(pda):
    # The snapshot must reflect the real accessors, not hardcoded defaults.
    with patch.object(pda, "_get_setting", return_value="false"):
        snap = pda.forge_settings_snapshot()
    assert snap["forge:json_reprompt_enabled"] is False
    assert snap["forge:self_refute_failclosed_enabled"] is False
