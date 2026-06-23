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
