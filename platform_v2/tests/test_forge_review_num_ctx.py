"""Unit tests for QW-5: the F.O.R.G.E. review num_ctx flag helper.

_review_num_ctx() gates the per-dispatch num_ctx for F.O.R.G.E. reviews.
Default-safe OFF: 0/unset/garbage -> None (no num_ctx passed = byte-identical
to pre-QW-5 behavior). A floor of 512 rejects nonsense small values.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def pda():
    from tools.repair_bay.services import pr_diff_analyzer

    return pr_diff_analyzer


@pytest.mark.parametrize(
    "val,expected",
    [
        ("0", None),  # default OFF
        ("", None),
        ("8192", 8192),  # enabled
        ("6144", 6144),
        ("512", 512),  # exactly the floor
        ("511", None),  # below floor
        ("100", None),
        ("garbage", None),
        (None, None),
    ],
)
def test_review_num_ctx(pda, val, expected):
    with patch.object(pda, "_get_setting", return_value=val):
        assert pda._review_num_ctx() == expected


# ---------------------------------------------------------------------------
# QW-5 follow-on: _diff_max_chars() scales the diff truncation cap to the
# per-dispatch review window so a raised window truncates fewer PRs, while
# rollback (flag off) keeps the conservative floor. Clamped to
# [_DIFF_MAX_CHARS, _DIFF_MAX_WIDE]; budgets ~3500 tokens for rubric+format+output.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "num_ctx,expected",
    [
        (None, 12000),  # flag off / rollback -> conservative floor
        (0, 12000),  # falsy window -> floor
        (8192, 18768),  # default raised window -> (8192-3500)*4
        (6144, 12000),  # modest window -> budget below floor, floor holds
        (1024, 12000),  # tiny window -> negative budget, floor holds
        (512, 12000),  # at the num_ctx floor -> still the cap floor
        (32768, 20000),  # huge window -> clamped to the ceiling
    ],
)
def test_diff_max_chars_scales_with_window(pda, num_ctx, expected):
    with patch.object(pda, "_review_num_ctx", return_value=num_ctx):
        assert pda._diff_max_chars() == expected


def test_diff_max_chars_stays_within_bounds(pda):
    """No window value can push the cap outside the documented [floor, ceiling]."""
    for nc in (None, 0, 512, 1024, 4096, 8192, 16384, 65536):
        with patch.object(pda, "_review_num_ctx", return_value=nc):
            cap = pda._diff_max_chars()
            assert pda._DIFF_MAX_CHARS <= cap <= pda._DIFF_MAX_WIDE


def test_truncate_diff_honors_explicit_cap(pda):
    """An explicit max_chars overrides the window-aware default (no settings read)."""
    diff = "\ndiff --git a/x b/x\n" + ("+x\n" * 5000)  # ~15k chars, single file
    content, truncated = pda._truncate_diff(diff, max_chars=2000)
    assert truncated is True
    assert len(content) <= 2000


def test_truncate_diff_small_diff_not_truncated(pda):
    """A diff under the cap is returned whole regardless of window."""
    diff = "\ndiff --git a/x b/x\n+only one line\n"
    with patch.object(pda, "_review_num_ctx", return_value=8192):
        content, truncated = pda._truncate_diff(diff)
    assert truncated is False
    assert content == diff


def test_truncate_diff_uses_window_aware_default(pda):
    """No explicit cap -> _truncate_diff pulls the window-aware _diff_max_chars().
    A ~15.6k-char single-file diff truncates under the 12k floor but fits whole
    under the raised 8192-window cap (18768)."""
    body = "\ndiff --git a/x b/x\n" + ("+line\n" * 2600)  # ~15.6k chars, one file
    with patch.object(pda, "_review_num_ctx", return_value=None):
        _, truncated_off = pda._truncate_diff(body)
    with patch.object(pda, "_review_num_ctx", return_value=8192):
        content_on, truncated_on = pda._truncate_diff(body)
    assert truncated_off is True
    assert truncated_on is False
    assert content_on == body
