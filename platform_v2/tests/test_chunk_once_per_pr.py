"""Per-PR checks run ONCE, on the full diff — never once per chunk (#5848 task 5)."""

import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402

_FULL = "".join(f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+{'z' * 400}\n" for i in range(6))


def test_provenance_runs_exactly_once_for_a_three_chunk_review():
    """== 1, not <= 1. With _structured_review mocked out, a provenance call made INSIDE it
    happens zero times, so a '<= 1' assertion passes before AND after the hoist and can never
    go red. The check must be made by _obtain_review_summary itself."""
    calls = []
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=500
    ), mock.patch.object(
        pda, "_check_dockerfile_provenance", side_effect=lambda d: calls.append(d) or []
    ), mock.patch.object(
        pda, "_structured_review", return_value="VERDICT: APPROVE"
    ):
        pda._obtain_review_summary({"title": "t"}, _FULL, 1, "r")
    assert len(calls) == 1, f"whole-PR provenance must run once per review, ran {len(calls)}x"


def test_provenance_sees_the_full_diff_not_a_chunk():
    """A Dockerfile in chunk 3 must still be checked — the guard is a whole-PR property."""
    calls = []
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=500
    ), mock.patch.object(
        pda, "_check_dockerfile_provenance", side_effect=lambda d: calls.append(d) or []
    ), mock.patch.object(
        pda, "_structured_review", return_value="VERDICT: APPROVE"
    ):
        pda._obtain_review_summary({"title": "t"}, _FULL, 1, "r")
    assert calls and calls[0] == _FULL, "provenance must be handed the FULL diff, not one chunk"


def test_single_chunk_still_delivers_provenance_findings_into_the_review():
    """The killswitch path must keep surfacing them, or hoisting silently drops #4749."""
    seen = {}

    def fake_structured(review, diff, pr_number=None, repo=None, ground_diff=None, dockerfile_findings=None):
        seen["findings"] = dockerfile_findings
        return "VERDICT: APPROVE"

    with mock.patch.object(pda, "_review_max_chunks", return_value=1), mock.patch.object(
        pda, "_check_dockerfile_provenance", return_value=[{"severity": "low", "title": "no GIT_SHA"}]
    ), mock.patch.object(pda, "_structured_review", side_effect=fake_structured):
        pda._obtain_review_summary({"title": "t"}, _FULL, 1, "r")
    assert seen.get("findings"), "provenance findings must reach the single-chunk review"


def test_provenance_is_attached_to_one_chunk_only():
    """Attaching it to every chunk would duplicate the finding N times in the merged review."""
    handed = []

    def fake_structured(review, diff, pr_number=None, repo=None, ground_diff=None, dockerfile_findings=None):
        handed.append(bool(dockerfile_findings))
        return "VERDICT: APPROVE"

    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=500
    ), mock.patch.object(
        pda, "_check_dockerfile_provenance", return_value=[{"severity": "low", "title": "no GIT_SHA"}]
    ), mock.patch.object(
        pda, "_structured_review", side_effect=fake_structured
    ):
        pda._obtain_review_summary({"title": "t"}, _FULL, 1, "r")
    assert len(handed) > 1 and sum(handed) == 1, f"exactly one chunk carries the findings, got {handed}"


def test_merged_verdict_does_not_escalate_needs_review_to_request_changes():
    """NEEDS REVIEW means 'a human should look'; REQUEST CHANGES asserts a DEFECT. Folding the
    first into the second manufactures a defect claim no pass actually made — and false blocks
    are the live problem this whole work item exists to reduce."""
    out = pda._merge_chunk_summaries(["VERDICT: APPROVE", "VERDICT: NEEDS REVIEW"], {"complete": True})
    assert "VERDICT: NEEDS REVIEW" in out
    assert "REQUEST CHANGES" not in out


def test_a_real_rejection_still_outranks_needs_review():
    out = pda._merge_chunk_summaries(["VERDICT: NEEDS REVIEW", "VERDICT: REQUEST CHANGES"], {"complete": True})
    assert "VERDICT: REQUEST CHANGES" in out
