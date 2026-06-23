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


# ---------------------------------------------------------------------------
# ST-3: _diff_cap_for_model(strong) right-sizes the cap to the model that runs
# the review. The Tier-3 gemma3:12b (strong=True) keeps the full window-aware
# cap; the 7B (strong=False, every Tier-1/2 structured review + all freeform)
# is capped at _DIFF_MAX_7B so it finishes inside the 240s per-node window.
# ---------------------------------------------------------------------------


def test_diff_max_7b_below_floor(pda):
    # The 7B cap must be tighter than the default floor, or it would never bite.
    assert pda._DIFF_MAX_7B < pda._DIFF_MAX_CHARS


@pytest.mark.parametrize(
    "num_ctx,strong,expected",
    [
        (8192, True, 18768),  # strong keeps the full window-aware cap
        (8192, False, 9000),  # 7B capped at _DIFF_MAX_7B
        (None, True, 12000),  # flag off: strong == floor
        (None, False, 9000),  # flag off: 7B still capped tighter
        (32768, True, 20000),  # strong ceilings with the window
        (32768, False, 9000),  # 7B unaffected by a huge window
    ],
)
def test_diff_cap_for_model(pda, num_ctx, strong, expected):
    with patch.object(pda, "_review_num_ctx", return_value=num_ctx):
        assert pda._diff_cap_for_model(strong) == expected


def test_diff_cap_strong_equals_full_window(pda):
    # strong=True must exactly track the window-aware _diff_max_chars().
    for nc in (None, 0, 8192, 16384):
        with patch.object(pda, "_review_num_ctx", return_value=nc):
            assert pda._diff_cap_for_model(True) == pda._diff_max_chars()


def test_build_json_prompt_strong_keeps_more_diff(pda):
    # A diff between the 7B cap and the full window: 7B truncates, strong does not.
    review = {"pr_number": 1, "title": "t", "additions": 0, "deletions": 0, "changed_files": 1}
    body = "\ndiff --git a/x b/x\n" + ("+line\n" * 2200)  # ~13.2k chars, one file
    note = "[diff truncated at a hunk boundary"  # the specific note (rubric also says "truncated")
    with patch.object(pda, "_review_num_ctx", return_value=8192):
        weak = pda._build_json_prompt(review, body, strong=False)
        strong = pda._build_json_prompt(review, body, strong=True)
    assert note in weak  # 13.2k > 9000 -> 7B truncates
    assert note not in strong  # 13.2k < 18768 -> strong keeps it whole
