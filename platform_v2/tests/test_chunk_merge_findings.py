"""Merging chunk results: worst-wins, union floor, dedup (#5848)."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services.pr_diff_analyzer import _merge_chunk_summaries  # noqa: E402

_META = "\n[review-meta] structured=json model=m confidence=0.9"


def test_any_blocking_chunk_blocks_the_pr():
    out = _merge_chunk_summaries(["VERDICT: APPROVE", "VERDICT: REQUEST CHANGES"], {"complete": True})
    assert "REQUEST CHANGES" in out


def test_all_approve_yields_approve():
    out = _merge_chunk_summaries(["VERDICT: APPROVE", "VERDICT: APPROVE"], {"complete": True})
    assert "APPROVE" in out and "REQUEST CHANGES" not in out


def test_an_unparseable_chunk_fails_closed():
    """A lost chunk is not a silent pass — it must not approve."""
    out = _merge_chunk_summaries(["VERDICT: APPROVE", None], {"complete": True})
    assert "APPROVE" not in out.split("VERDICT:")[-1]


def test_identical_findings_are_deduped():
    f = "- [WARNING] same thing — because reasons — Evidence: +x = 1"
    out = _merge_chunk_summaries([f"{f}\nVERDICT: APPROVE", f"{f}\nVERDICT: APPROVE"], {"complete": True})
    assert out.count("same thing") == 1


def test_distinct_findings_are_all_kept():
    a = "- [WARNING] alpha — why — Evidence: +a = 1"
    b = "- [CRITICAL] beta — why — Evidence: +b = 2"
    out = _merge_chunk_summaries([f"{a}\nVERDICT: APPROVE", f"{b}\nVERDICT: REQUEST CHANGES"], {"complete": True})
    assert "alpha" in out and "beta" in out


def test_a_missing_verdict_line_fails_closed_without_asserting_a_defect():
    """parse_verdict returns REVIEWED (not APPROVE) with no VERDICT line, so the merge must not
    approve. It must NOT reach for REQUEST CHANGES either: that asserts a defect the pass never
    found. NEEDS REVIEW is the honest label and blocks auto-merge just as hard —
    verdict_is_approved admits APPROVE only."""
    out = _merge_chunk_summaries(["- [INFO] noted — why — Evidence: +x", "VERDICT: APPROVE"], {"complete": True})
    assert "VERDICT: APPROVE" not in out
    assert "VERDICT: NEEDS REVIEW" in out
    assert "REQUEST CHANGES" not in out


def test_path_marker_survives_when_every_pass_was_structured():
    """_classify_review_path reads no-marker as 'legacy: the degraded path' and alarms on it,
    so a healthy chunked review must carry its marker forward."""
    out = _merge_chunk_summaries([f"VERDICT: APPROVE{_META}", f"VERDICT: APPROVE{_META}"], {"complete": True})
    assert "structured=json" in out


def test_a_degraded_pass_downgrades_the_merged_marker():
    gated = "VERDICT: APPROVE\n[review-meta] structured=freeform-gated"
    out = _merge_chunk_summaries([f"VERDICT: APPROVE{_META}", gated], {"complete": True})
    assert "structured=freeform-gated" in out and "structured=json" not in out


def test_a_blocking_pass_with_no_parseable_finding_still_says_why():
    """Otherwise chunking can emit 'REQUEST CHANGES / No issues found.' — unactionable."""
    out = _merge_chunk_summaries(
        ["VERDICT: APPROVE", "the model rambled and blocked\nVERDICT: REQUEST CHANGES"], {"complete": True}
    )
    assert "No issues found." not in out
    assert "rambled" in out


def test_files_read_is_reported_when_coverage_knows():
    out = _merge_chunk_summaries(["VERDICT: APPROVE"], {"complete": False, "total": 6, "reviewed": 3})
    assert "3/6 files read" in out
