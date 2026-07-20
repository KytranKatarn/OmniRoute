"""#5018 — a verdict must carry its provenance.

On PR #2366 F.O.R.G.E. returned REQUEST CHANGES with a [CRITICAL] that was simply wrong: it
claimed dict access on tuples from `get_backup_db_cursor()`, but that cursor is never used in
the PR (both files import `get_db_cursor`, a RealDictCursor). The model had read the
*documentation* text in the diff and attributed it to the code.

The review was degraded and nothing said so: the 7B timed out 3x (warm_boot_ms 600094), the
structured parse failed, it fell back to freeform, and the Evidence field was EMPTY.

#5009 floors an ungrounded APPROVE but deliberately leaves REQUEST CHANGES alone — relaxing
one would let real findings through, which is far worse than a false positive. That asymmetry
is correct. These flags are the other half: annotate, never adjudicate.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.repair_bay.services.pr_diff_analyzer import (  # noqa: E402
    _quality_suffix,
    _should_floor_ungrounded,
    review_quality_flags,
)


def _issue(evidence=""):
    return {"severity": "CRITICAL", "title": "t", "why": "w", "evidence": evidence}


class TestTheRealCase:
    def test_pr2366_signature_is_flagged(self):
        """Freeform fallback + a blocking issue citing nothing = exactly what happened."""
        flags = review_quality_flags("freeform-gated", 0, [_issue("")])
        assert "freeform_fallback" in flags
        assert "blocking_issue_without_evidence" in flags

    def test_clean_structured_review_has_no_flags(self):
        """A good review must stay unmarked, or the signal becomes noise and gets ignored."""
        assert review_quality_flags("json", 0, [_issue("+ real code line")]) == []

    def test_clean_review_with_no_issues_has_no_flags(self):
        assert review_quality_flags("json", 0, []) == []


class TestEachFlag:
    def test_freeform_fallback_on_any_non_json_path(self):
        assert "freeform_fallback" in review_quality_flags("freeform-gated", 0, [])
        assert "freeform_fallback" not in review_quality_flags("json", 0, [])

    def test_no_grounded_evidence_when_everything_was_dropped(self):
        flags = review_quality_flags("json", 3, [])
        assert "no_grounded_evidence" in flags

    def test_partially_grounded_is_not_flagged_as_ungrounded(self):
        """Something survived verification — the model grounded a real finding."""
        flags = review_quality_flags("json", 2, [_issue("+ real line")])
        assert "no_grounded_evidence" not in flags

    def test_blank_evidence_detected_among_several_issues(self):
        flags = review_quality_flags("json", 0, [_issue("+ ok"), _issue("   ")])
        assert "blocking_issue_without_evidence" in flags


class TestNeverAdjudicates:
    def test_flags_are_strings_only_no_verdict(self):
        """This function must never be able to change an outcome — it returns labels."""
        out = review_quality_flags("freeform-gated", 5, [_issue("")])
        assert all(isinstance(f, str) for f in out)
        for v in ("APPROVE", "REQUEST CHANGES", "NEEDS REVIEW"):
            assert v not in out

    def test_floor_still_only_touches_approve(self):
        """Guard the #5009 invariant these flags sit beside: REQUEST CHANGES is never relaxed."""
        assert _should_floor_ungrounded("APPROVE", 2, []) is True
        assert _should_floor_ungrounded("REQUEST CHANGES", 2, []) is False
        assert _should_floor_ungrounded("NEEDS REVIEW", 2, []) is False


class TestMetaRendering:
    def test_suffix_empty_when_clean(self):
        """No trailing junk on a healthy review-meta line."""
        assert _quality_suffix("json", 0, [_issue("+ x")]) == ""

    def test_suffix_lists_flags(self):
        s = _quality_suffix("freeform-gated", 1, [])
        assert s.startswith(" quality=")
        assert "freeform_fallback" in s and "no_grounded_evidence" in s
