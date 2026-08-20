"""chunk_plan packs whole diff blocks into at most max_chunks bins (#5848).

Task 1 of docs/superpowers/plans/2026-08-20-chunked-multipass-pr-review.md.

Why this exists: `_DIFF_MAX_7B = 9000` caps the diff for every Tier-1/2 review, so anything
larger is truncated and the reviewer is TOLD it could not read the PR. Measured 2026-08-20,
five of six consecutive truncations were the TEST file — `prioritize()` (#2715) orders code
before tests, so tests sit at the back of the window and fall off first. Every APPROVE that
day was issued without the tests in view.

chunk_plan is the pure, dispatcher-free foundation: split the diff into bins the reviewer can
actually read. It must never split a block — splitting mid-hunk reintroduces the exact
mid-statement cut `_truncate_diff` exists to avoid.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.review_coverage import chunk_plan, split_blocks  # noqa: E402


def _diff(*paths):
    out = []
    for p in paths:
        out.append(f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n+{'x' * 400}\n")
    return "".join(out)


def test_single_chunk_is_byte_identical_to_truncation():
    """The killswitch. At max_chunks=1 nothing about today's behaviour may change."""
    d = _diff("a.py", "b.py", "c.py")
    assert chunk_plan(d, cap=10_000, max_chunks=1) == [d]


def test_blocks_are_never_split_across_chunks():
    d = _diff("a.py", "b.py", "c.py")
    chunks = chunk_plan(d, cap=600, max_chunks=3)
    for c in chunks:
        assert c.startswith("diff --git")
        assert c.count("diff --git") == len(split_blocks(c))


def test_never_exceeds_max_chunks():
    d = _diff(*[f"f{i}.py" for i in range(20)])
    assert len(chunk_plan(d, cap=500, max_chunks=3)) <= 3


def test_every_chunk_within_cap_unless_one_block_exceeds_it():
    d = _diff("a.py", "b.py")
    for c in chunk_plan(d, cap=600, max_chunks=3):
        assert len(c) <= 600 or c.count("diff --git") == 1


def test_oversized_single_block_gets_its_own_chunk():
    big = "diff --git a/big.py b/big.py\n@@ -1 +1 @@\n+" + ("y" * 5000) + "\n"
    small = _diff("small.py")
    chunks = chunk_plan(big + small, cap=1000, max_chunks=3)
    assert any(c.count("diff --git") == 1 and len(c) > 1000 for c in chunks)


def test_empty_and_none_are_safe():
    assert chunk_plan("", cap=100, max_chunks=3) == []
    assert chunk_plan(None, cap=100, max_chunks=3) == []


def test_code_precedes_tests_precedes_docs():
    """prioritize()'s ordering must survive packing, or chunk 1 stops being the code —
    which is the whole reason tests were the thing being truncated."""
    d = _diff("README.md", "tests/test_a.py", "svc.py")
    first = chunk_plan(d, cap=600, max_chunks=3)[0]
    assert "svc.py" in first
