r"""#5841 — the SEVERITY gate's design-observation demotion: article form + contrastive veto.

TWO changes, and the second exists BECAUSE of the first.

1. `_DESIGN_OBSERVATION_RE` matched "introduces new functions" but NOT "introduces **a** new
   function" — a missing optional article. That is the shape that blocked PR #2715:
   "[WARNING] New function `prioritize` introduced — While this is a reasonable addition, it
   introduces a new function that wasn't present in the original codebase."

2. Adding the article ALONE would have suppressed a REAL finding. Measured against the live
   corpus (1,629 stored reviews / 1,741 issue lines), the one blocking finding it newly
   demoted was pr_reviews #1692:

     "[WARNING] The PR introduces a new function `_logout(client)` which clears the
      Flask-Login session. HOWEVER, this function is not used in any of the tests added in
      this PR. It should either be used or removed to avoid unnecessary code."

   That is dead code — a real observation wearing a design-observation opening. And
   `_DEFECT_ASSERTION_RE` misses it, because its pattern is `should\s+(be|use|have|not)` and
   the text says "should EITHER be". Hence `_CONTRASTIVE_RE`: after however/but/although the
   operative claim is what FOLLOWS, so the shape remark before it cannot speak for the whole
   finding.

MEASURED IMPACT on 1,741 real issue lines — 82 demoted before, 82 after:
  * 4 NEWLY demoted, and all four were ALREADY `[INFO]`, so ZERO verdicts change.
  * 4 STOP being demoted, including a genuine
    "[WARNING] SQL Injection Risk: ... queries use string formatting directly"
    that the gate had been silently demoting. The guard is a net SAFETY gain, not just a
    cost.

This gate DEMOTES, so a false positive SUPPRESSES A REAL DEFECT — the worse direction. That
asymmetry is why the contrastive veto is deliberately broad (any contrastive anywhere vetoes)
and why the article widening was kept to exactly what the corpus measurement covered.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repair_bay.services.pr_diff_analyzer import _is_design_observation  # noqa: E402


class TestArticleForm(unittest.TestCase):
    def test_pr_2715_shape_now_demotes(self):
        blob = (
            "new function prioritize introduced while this is a reasonable addition it "
            "introduces a new function that was not present in the original codebase"
        )
        self.assertTrue(_is_design_observation(blob))

    def test_article_less_form_still_demotes(self):
        self.assertTrue(_is_design_observation("this introduces new functions which add complexity"))

    def test_the_article(self):
        self.assertTrue(_is_design_observation("introduces the new helper"))

    def test_singular_class_now_matches_PRE_EXISTING_TYPO(self):
        """`classes?` meant "classe" + optional "s" — it NEVER matched the singular "class",
        because the plural of class adds *es*, not *s*. A pre-existing bug in the pattern,
        found by this test, fixed to `class(es)?`. `functions?`/`methods?`/`helpers?` were
        always fine."""
        self.assertTrue(_is_design_observation("introduces a new class"))
        self.assertTrue(_is_design_observation("introduces the new class Foo"))
        self.assertTrue(_is_design_observation("introduces new classes"))

    def test_adjective_between_article_and_noun_is_OUT_OF_SCOPE(self):
        """ "introduces an ADDITIONAL method" does not match, deliberately.

        Allowing an arbitrary adjective would widen the demotion beyond what the corpus
        measurement covered, and every widening of a demote-only gate is a suppression
        risk. Pinned so the boundary is a known decision, not an oversight — revisit only
        with a fresh measurement."""
        self.assertFalse(_is_design_observation("the change introduces an additional method for parsing"))


class TestContrastiveVeto(unittest.TestCase):
    def test_pr_1692_dead_code_finding_is_NOT_demoted(self):
        """The real finding the article fix would otherwise have suppressed."""
        blob = (
            "the pr introduces a new function _logout(client) which clears the flask-login "
            "session. however, this function is not used in any of the tests added in this "
            "pr. it should either be used or removed to avoid unnecessary code"
        )
        self.assertFalse(_is_design_observation(blob))

    def test_but_also_vetoes(self):
        self.assertFalse(_is_design_observation("introduces a new helper, but it silently swallows errors"))

    def test_although_and_though_veto(self):
        self.assertFalse(_is_design_observation("although it introduces a new function, the retry is unbounded"))
        self.assertFalse(_is_design_observation("introduces a new class though the lock is never released"))

    def test_defect_assertion_still_vetoes_independently(self):
        self.assertFalse(_is_design_observation("introduces a new function that is vulnerable to injection"))

    def test_hardcode_carve_out_still_vetoes_independently(self):
        self.assertFalse(_is_design_observation("introduces a new function with a hardcoded api key"))

    def test_plain_shape_remark_with_no_contrastive_still_demotes(self):
        """The veto must not swallow the whole gate — a clean design observation still
        demotes, otherwise the ADR-001 SEVERITY work is undone."""
        self.assertTrue(_is_design_observation("this change adds to the complexity of the module"))
        self.assertTrue(_is_design_observation("the threshold may be too long or too short"))


if __name__ == "__main__":
    unittest.main()
