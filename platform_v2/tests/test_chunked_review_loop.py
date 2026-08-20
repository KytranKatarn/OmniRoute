"""The chunk loop: worst-wins verdict, union coverage, killswitch at 1 (#5848)."""

import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402


def test_default_is_one_chunk():
    """The killswitch default. At 1, nothing about today's behaviour changes."""
    with mock.patch.object(pda, "_get_setting", return_value=None):
        assert pda._review_max_chunks() == 1


def test_setting_is_clamped_to_three():
    with mock.patch.object(pda, "_get_setting", return_value="99"):
        assert pda._review_max_chunks() == 3


def test_garbage_setting_falls_back_to_one():
    with mock.patch.object(pda, "_get_setting", return_value="banana"):
        assert pda._review_max_chunks() == 1


def test_one_chunk_calls_structured_review_exactly_once():
    calls = []
    with mock.patch.object(pda, "_review_max_chunks", return_value=1), mock.patch.object(
        pda, "_structured_review", side_effect=lambda *a, **k: calls.append(k) or "VERDICT: APPROVE"
    ):
        pda._obtain_review_summary({"title": "t"}, "diff --git a/a.py b/a.py\n+x\n", 1, "r")
    assert len(calls) == 1


def test_every_chunk_is_grounded_against_the_full_diff():
    seen = []

    def fake(review, diff, pr_number=None, repo=None, ground_diff=None, dockerfile_findings=None):
        seen.append((diff, ground_diff))
        return "VERDICT: APPROVE"

    full = "".join(f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+{'z'*400}\n" for i in range(6))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=500
    ), mock.patch.object(pda, "_structured_review", side_effect=fake):
        pda._obtain_review_summary({"title": "t"}, full, 1, "r")
    assert len(seen) > 1, "a diff over the cap must produce multiple passes"
    for shown, ground in seen:
        assert ground == full, "grounding must ALWAYS be the full diff"
        assert len(shown) <= len(full)


def test_a_truncated_chunk_does_not_swallow_the_next_chunks_first_file():
    """Union coverage must survive a mid-line cut at a chunk boundary.

    _truncate_diff cuts an oversized chunk mid-line. Joining the chunks with "" glues that
    cut line straight onto the next chunk's "diff --git" header, so the ^diff --git MULTILINE
    regex stops matching and a file that WAS reviewed is reported as dropped.
    """
    big = "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -1 +1 @@\n+" + ("q" * 12000) + "\n"
    small = "".join(f"diff --git a/s{i}.py b/s{i}.py\n@@ -1 +1 @@\n+{'y' * 200}\n" for i in range(3))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=9000
    ), mock.patch.object(pda, "_structured_review", return_value="VERDICT: APPROVE"):
        out = pda._obtain_review_summary({"title": "t"}, big + small, 1, "r") or ""
    assert "s0.py" not in out, "s0.py sat in a later chunk and was reviewed — it must not read as dropped"
