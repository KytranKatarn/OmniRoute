"""GATE 5 (#6817) — the cited evidence IS the remedy the finding demands.

A finding that says something is MISSING and cites the ADDED line that SUPPLIES it refutes
itself. All four ADR-001 gates pass on it — the citation is real (grounding), it is an added
line (polarity), the claim is diff-checkable (claim), and it reads as a definite fault
(severity) — and GATE 6 leaves it alone because it asserts rather than hedges. Only a gate
that compares the claim against what the diff ADDS can see it.

MEASURED on PR #3414 (#6817): two findings each cited the `+` line adding the very thing they
called missing. Both flipped REQUEST CHANGES → APPROVE on written rebuttal with zero code
change — i.e. the reviewer, re-run, disagreed with itself.

⚠️ PROVENANCE OF THE FIXTURES. `forge_reviews.raw_payload` stores verdict/severities/coverage
but NOT finding text, and #3414's summary was overwritten by the APPROVE re-review, so the
verbatim findings are gone. The two EVIDENCE lines below are quoted from #6817
("+ excluded = len(rows) - len(considered)" and "+def is_inference_path"); the surrounding
claim wording is RECONSTRUCTED from the task's description of it. The evidence lines — the
part the gate keys on — are real.

⚠️ THE HALF THAT MATTERS IS MUST_KEEP. A drop is stronger than a demotion, so the risk is
deleting a true finding. Two cases in particular keep this gate honest: a GUARD claim cited on
its own subject ("X is missing a null check" on "+def X") is legitimate, and a test that is
added but VISIBLY SKIPPED makes "it does not run" legitimate.
"""

from __future__ import annotations

import pytest

from tools.repair_bay.services.pr_diff_analyzer import (
    _count_ungrounded,
    _evidence_supplies_the_remedy,
    _verify_evidence,
)

DIFF_ADDS_TESTS = """diff --git a/platform_v2/tests/test_x.py b/platform_v2/tests/test_x.py
+def test_is_inference_path_handles_none():
+    assert is_inference_path(None) is False
diff --git a/platform_v2/services/x.py b/platform_v2/services/x.py
+def is_inference_path(row):
+    return bool(row)
"""

DIFF_ADDS_THE_VALUE = """diff --git a/a.py b/a.py
+        excluded = len(rows) - len(considered)
+        out["excluded"] = excluded
"""

DIFF_ADDS_A_SUBJECT_ONLY = """diff --git a/a.py b/a.py
+def parse_node(raw):
+    return raw["id"]
"""


def _issue(title, why, evidence):
    return {"title": title, "why": why, "evidence": evidence}


# Real #3414 shapes — these must DROP.
SELF_REFUTING = [
    (
        "no-tests cited on the added subject, while the diff adds the test",
        _issue("No tests provided", "The new is_inference_path helper has no tests provided.", "+def is_inference_path(row):"),
        DIFF_ADDS_TESTS,
    ),
    (
        "underreporting cited on the added binding of the very value",
        _issue("Underreporting", "The excluded count is not reported to the caller.", "+        excluded = len(rows) - len(considered)"),
        DIFF_ADDS_THE_VALUE,
    ),
]

# These must SURVIVE. Each is a finding a human would want to see.
MUST_KEEP = [
    (
        "a GUARD claim cited on its own subject is legitimate",
        _issue("Missing null check", "parse_node is missing a null check on raw.", "+def parse_node(raw):"),
        DIFF_ADDS_A_SUBJECT_ONLY,
    ),
    (
        "a test that is added but VISIBLY SKIPPED does not run",
        _issue("No tests", "no tests are provided for this path", "+def test_thing():"),
        DIFF_ADDS_TESTS + '+@pytest.mark.skip(reason="wip")\n',
    ),
    (
        "an unreported value whose evidence is NOT the binding",
        _issue("Not reported", "The excluded count is not reported anywhere.", "+        return out"),
        DIFF_ADDS_THE_VALUE,
    ),
    (
        "evidence absent from the diff — grounding owns that, not this gate",
        _issue("No tests", "no tests provided", "+def totally_absent_line():"),
        DIFF_ADDS_TESTS,
    ),
    (
        "an ordinary real defect",
        _issue("Leak", "the connection is never closed", "+        conn = connect()"),
        DIFF_ADDS_THE_VALUE,
    ),
]


class TestThePredicate:
    @pytest.mark.parametrize("label,issue,diff", SELF_REFUTING, ids=[c[0][:40] for c in SELF_REFUTING])
    def test_a_self_refuting_finding_is_caught(self, label, issue, diff):
        assert _evidence_supplies_the_remedy(issue, diff) is True, label

    @pytest.mark.parametrize("label,issue,diff", MUST_KEEP, ids=[c[0][:40] for c in MUST_KEEP])
    def test_a_legitimate_finding_is_never_caught(self, label, issue, diff):
        assert _evidence_supplies_the_remedy(issue, diff) is False, label

    def test_it_fails_closed_on_nothing(self):
        for issue in ({}, {"title": "", "why": "", "evidence": ""}, None):
            assert _evidence_supplies_the_remedy(issue, DIFF_ADDS_TESTS) is False


class TestWiredIntoTheDropChain:
    """A predicate nobody calls is not a gate — the house precedent (#5194, #5862, #2738, and
    the multi-pass merge itself)."""

    def test_the_drop_chain_drops_it_with_the_right_reason(self):
        issue = SELF_REFUTING[0][1]
        kept, dropped = _verify_evidence([dict(issue)], DIFF_ADDS_TESTS)
        assert kept == []
        assert len(dropped) == 1
        assert dropped[0]["_drop_reason"] == "evidence_is_the_remedy"

    def test_the_drop_chain_keeps_a_legitimate_finding(self):
        issue = MUST_KEEP[0][1]
        kept, dropped = _verify_evidence([dict(issue)], DIFF_ADDS_A_SUBJECT_ONLY)
        assert len(kept) == 1
        assert dropped == []

    def test_it_does_not_count_toward_the_ungrounded_floor(self):
        """#5009's APPROVE floor counts ONLY evidence_not_in_diff. A self-refuting finding means
        the model WAS reading its input, so counting it here would re-block correct PRs — the
        same reasoning the polarity and claim gates already carry."""
        _, dropped = _verify_evidence([dict(SELF_REFUTING[0][1])], DIFF_ADDS_TESTS)
        assert _count_ungrounded(dropped) == 0
