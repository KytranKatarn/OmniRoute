r"""#5846 — "your pattern might not cover every future input" must not block a PR.

The FOURTH non-finding shape, and the one that blocked PR #2718 three times running:

    [WARNING] Regex pattern might be too narrow — The regex `_PERMANENT_AUTH_RE` is
    deliberately narrow to avoid false positives, but it could still miss some cases where
    the server rejects a credential.

By the third pass the finding had absorbed the rebuttal and stated the design rationale
ITSELF — and still carried [WARNING], which blocks. It asserts no present defect: it
hypothesises about INPUTS THAT DO NOT EXIST IN THE DIFF. No diff can show that a pattern
handles every string that might ever arrive, so a reviewer can say "your allow-list might be
incomplete" about any allow-list, forever. That is a CLAIM problem in ADR-001 terms, and it
matches none of the three existing demotion predicates: _asserts_no_defect needs APPROVAL
wording, _is_design_observation needs a SHAPE remark, _NONBLOCKING_CATEGORY_RE needs a known
nit category.

THIS GATE DEMOTES, so a false positive SUPPRESSES A REAL DEFECT. Hence three conditions, and
hence the change was corpus-measured BEFORE shipping (1,743 real issue lines): it demotes 6
lines total, only 2 of which carried a BLOCKING severity, and neither alleges a defect. The
exemplar rule keeps the third blocking candidate at WARNING.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repair_bay.services.pr_diff_analyzer import (  # noqa: E402
    _demote_nonblocking_lines,
    _is_speculative_coverage_claim,
    _normalize_severity,
)

PR2718 = (
    "Regex pattern might be too narrow — The regex _PERMANENT_AUTH_RE is deliberately narrow "
    "to avoid false positives, but it could still miss some cases where the server rejects a "
    "credential"
)


class TestPredicate(unittest.TestCase):
    def test_the_pr_2718_blocker_demotes(self):
        self.assertTrue(_is_speculative_coverage_claim(PR2718))

    def test_other_speculative_phrasings(self):
        for b in (
            "the list is not exhaustive",
            "this may not be comprehensive",
            "future error messages might not match the pattern",
        ):
            self.assertTrue(_is_speculative_coverage_claim(b), b)

    def test_a_CONCRETE_EXEMPLAR_keeps_its_severity(self):
        """ "may not cover all edge cases, SUCH AS multiple retries" names a case a human can
        go and check — an observation, not speculation. Measured: this exclusion is what keeps
        the real pr_reviews exception-handling finding blocking."""
        self.assertFalse(
            _is_speculative_coverage_claim(
                "the current exception handling is basic and may not cover all edge cases, "
                "such as multiple retries or different types of exceptions"
            )
        )
        self.assertFalse(_is_speculative_coverage_claim("may not cover all inputs, e.g. unicode"))

    def test_fail_to_phrasing_is_vetoed_by_the_defect_gate(self):
        """ "could FAIL TO cover" trips `_DEFECT_ASSERTION_RE` (`fail(s|ing|ed)? to`) and keeps
        its severity. That is the conservative outcome and it is why this predicate carries no
        "fail to ..." branch — such a branch could never take effect."""
        self.assertFalse(_is_speculative_coverage_claim("the handler could fail to cover all inputs"))

    def test_a_real_defect_alongside_keeps_its_severity(self):
        self.assertFalse(
            _is_speculative_coverage_claim("the pattern may not match and the token is missing so auth is broken")
        )

    def test_ordinary_findings_untouched(self):
        for b in ("the retry loop is unbounded and will spin forever", "", None):
            self.assertFalse(_is_speculative_coverage_claim(b), b)


class TestWiredIntoBothSeverityPaths(unittest.TestCase):
    """The structured and freeform paths are separate implementations; a fix to one is not a
    fix to the other."""

    def test_structured_path_demotes(self):
        issues = [{"severity": "WARNING", "title": "Regex pattern might be too narrow", "why": PR2718}]
        self.assertEqual(_normalize_severity(issues)[0]["severity"], "INFO")
        self.assertEqual(issues[0]["_demoted_from"], "WARNING")

    def test_freeform_path_demotes(self):
        line = "- [WARNING] %s" % PR2718
        self.assertIn("[INFO]", _demote_nonblocking_lines(line))

    def test_freeform_keeps_a_real_blocker(self):
        line = "- [WARNING] the retry loop is unbounded and will spin forever"
        self.assertIn("[WARNING]", _demote_nonblocking_lines(line))

    def test_freeform_keeps_an_exemplar_backed_finding(self):
        line = "- [WARNING] may not cover all edge cases, such as multiple retries"
        self.assertIn("[WARNING]", _demote_nonblocking_lines(line))


if __name__ == "__main__":
    unittest.main()
