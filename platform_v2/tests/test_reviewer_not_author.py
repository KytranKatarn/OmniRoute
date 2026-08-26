"""Reviewer != author (#6040, spec 2026-08-26 Phase 3).

F.O.R.G.E. plans machine-authored fixes (ship_as_pr's archie/forge/* branches,
the engine's engine/* branches); letting it also review those PRs is
self-review. These pin: the branch->reviewer mapping, that BOTH review
dispatch sites consult it, and that P.R.O.B.E. actually carries the skill.
"""

from pathlib import Path

from tools.repair_bay.services.pr_diff_analyzer import (
    _REVIEW_HEAD_BRANCH,
    _review_prefer_agent,
)


class TestBranchMapping:
    def _with_branch(self, branch):
        token = _REVIEW_HEAD_BRANCH.set(branch)
        try:
            return _review_prefer_agent()
        finally:
            _REVIEW_HEAD_BRANCH.reset(token)

    def test_pipeline_branch_moves_the_seat_to_probe(self):
        assert self._with_branch("archie/forge/11985-medium-pyflakes") == "P.R.O.B.E."

    def test_engine_branch_moves_the_seat_to_probe(self):
        assert self._with_branch("engine/add-comment-abc123") == "P.R.O.B.E."

    def test_human_branch_keeps_default_routing(self):
        assert self._with_branch("fix/repair-ledger-honesty") is None
        assert self._with_branch("feat/self-repair-ship-as-pr") is None

    def test_unknown_branch_keeps_default_routing(self):
        """Empty/unset must NOT move the seat — a missing head_branch is not
        evidence of machine authorship (fail toward the status quo)."""
        assert self._with_branch("") is None


def test_both_review_dispatch_sites_consult_the_helper():
    """A guard wired at one of two sites is a guard with holes (#5862 family):
    the structured attempt AND the freeform fallback must both consult it."""
    src = Path("/app/tools/repair_bay/services/pr_diff_analyzer.py").read_text()
    assert src.count("_review_prefer_agent()") >= 2, "one of the dispatch sites lost the #6040 seat rule"
    assert "_REVIEW_HEAD_BRANCH.set(review.get" in src, "review_pr no longer stamps the head branch"


# NOTE deliberately NOT a pytest: "P.R.O.B.E. carries code_review Lv>=3" is PROD
# state, and pytest runs against archie_test (conftest hard-overrides DB_NAME,
# KB #296268), whose agent data does not mirror prod — the assertion would test
# the wrong database. It is a DEPLOY-TIME verification instead (run against prod):
#   SELECT s.proficiency_level FROM agent_skills s JOIN agents a ON a.id=s.agent_id
#    WHERE replace(a.name,'.','')='PROBE' AND s.skill_name='code_review';
# Verified 2026-08-26: Lv4, wake-on-demand covers the barracked state.
