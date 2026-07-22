"""Regression: praise tagged [CRITICAL] must not block a merge (#5075 follow-on).

Measured live on PR #2403, where F.O.R.G.E. returned REQUEST CHANGES on:

    [CRITICAL] Content Verification Check Added — Ensures that the deployed code matches
    what is running in the sandbox, preventing potential discrepancies.

That is a description of the change working AS INTENDED. No defect is asserted anywhere in
it — the CRITICAL tag alone flipped the verdict, because only CRITICAL/WARNING block.

This is the THIRD distinct false-block mode, and it slips the other two by construction:
  * the cited evidence is a real ADDED line -> grounding (#5009) passes it,
  * it is an ADDED line -> the polarity gate (#5075) correctly leaves it alone,
  * it makes no runtime claim -> the #5098 guard does not apply.
Nothing is wrong with it except that its severity does not match its content, so the
severity layer is the only place that can judge it.

Demote-only, never dropped: the observation still reaches the human, it just stops blocking.
All externals are pure; no DB, no GitHub, no model.
"""

import tools.repair_bay.services.pr_diff_analyzer as pda
from tools.repair_bay.services.pr_diff_analyzer import (
    _asserts_no_defect,
    _demote_nonblocking_lines,
    _normalize_severity,
)

# Verbatim from the live #2403 review.
PRAISE_TITLE = "Content Verification Check Added"
PRAISE_WHY = (
    "Ensures that the deployed code matches what is running in the sandbox, " "preventing potential discrepancies."
)


class TestPraiseStopsBlocking:
    def test_the_exact_2403_finding_is_demoted(self):
        """THE REGRESSION, verbatim."""
        issues = [{"severity": "CRITICAL", "title": PRAISE_TITLE, "why": PRAISE_WHY, "evidence": "+x = 1"}]
        out = _normalize_severity(issues)
        assert out[0]["severity"] == "INFO"
        assert out[0]["_demoted_from"] == "CRITICAL"

    def test_it_is_demoted_not_dropped(self):
        """The observation must still reach the human — only its blocking power is removed."""
        issues = [{"severity": "CRITICAL", "title": PRAISE_TITLE, "why": PRAISE_WHY}]
        out = _normalize_severity(issues)
        assert len(out) == 1
        assert out[0]["title"] == PRAISE_TITLE and out[0]["why"] == PRAISE_WHY

    def test_freeform_path_is_rewritten_too(self):
        """The freeform reviewer emits the same praise as a tagged LINE."""
        text = f"- [CRITICAL] {PRAISE_TITLE} — {PRAISE_WHY} — Evidence: +x = 1"
        out = _demote_nonblocking_lines(text)
        assert "[INFO]" in out and "[CRITICAL]" not in out
        assert PRAISE_TITLE in out  # content preserved

    def test_approval_phrasing_variants(self):
        for blob in (
            "Adds a validation check — ensures inputs are well formed",
            "Improves error handling and prevents duplicate writes",
            "The guard correctly aligns with existing policy",
            "Adds verification — safeguards against silent drift",
        ):
            assert _asserts_no_defect(blob), blob


class TestRealFindingsStillBlock:
    """The asymmetry is the safety property: ANY predicative fault claim wins over approval."""

    def test_approval_plus_a_real_fault_still_blocks(self):
        blob = "The new guard prevents injection but the old path is still vulnerable"
        assert not _asserts_no_defect(blob)
        issues = [{"severity": "CRITICAL", "title": "partial fix", "why": blob}]
        assert _normalize_severity(issues)[0]["severity"] == "CRITICAL"

    def test_plain_defect_findings_are_untouched(self):
        for blob in (
            "The function does not handle a None input and will crash",
            "Connection is missing a rollback so the pool leaks",
            "This should be parameterized — it is vulnerable to injection",
            "Unhandled exception in the retry path",
        ):
            assert not _asserts_no_defect(blob), blob

    def test_a_normal_critical_finding_keeps_its_severity(self):
        issues = [
            {
                "severity": "CRITICAL",
                "title": "SQL built by concatenation",
                "why": "user input is concatenated into the query and is vulnerable",
            }
        ]
        assert _normalize_severity(issues)[0]["severity"] == "CRITICAL"

    def test_neutral_text_is_not_treated_as_praise(self):
        """No approval wording -> not our business, regardless of content."""
        assert not _asserts_no_defect("Refactors the loop into a helper")
        assert not _asserts_no_defect("")


class TestExistingBehaviourPreserved:
    def test_nonblocking_category_demotion_still_works(self):
        issues = [{"severity": "WARNING", "title": "no unit tests", "why": "test coverage is thin"}]
        assert _normalize_severity(issues)[0]["severity"] == "INFO"

    def test_info_severity_is_left_alone(self):
        issues = [{"severity": "INFO", "title": PRAISE_TITLE, "why": PRAISE_WHY}]
        out = _normalize_severity(issues)
        assert out[0]["severity"] == "INFO"
        assert "_demoted_from" not in out[0]

    def test_both_regexes_exist_and_are_used(self):
        assert pda._APPROVAL_RE.search("this ensures correctness")
        assert pda._DEFECT_ASSERTION_RE.search("it is vulnerable to injection")
