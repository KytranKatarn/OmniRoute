"""Unattended-merge governance gate (#5194).

On 2026-07-25 PR #2458 was auto-merged to main on a ``needs_changes`` verdict. The
merge came from ai_bridge.agent_loop._run_archie_pr_review_worker, a SECOND merge path
that selects reviews by ``review_status='reviewed'`` — which only means a review
FINISHED, not that it approved — and never called verdict_is_approved(). It was blocked
twice beforehand ONLY by an accidental HTTP 405 "Pull Request is still a draft"; the
moment the PR was marked ready, the next cycle merged it. Its Tier-2 branch also merges
unconditionally, ignoring FORGE_AUTO_MERGE_MAX_TIER (default 1).

The gate therefore lives at the CHOKE POINT (github_service.merge_pr), not in the
caller: merge_pr has five call sites and gating each would leave the next new one
unprotected. These tests pin the two refusals plus fail-closed behaviour.
"""

from unittest.mock import patch

import pytest

from tools.repair_bay.services import github_service


_APPROVED = "SUMMARY\nfine\n\nISSUES\nNo issues found.\n\nVERDICT: APPROVE"
_NEEDS_CHANGES = "SUMMARY\nx\n\nISSUES\n- [HIGH] thing\n\nVERDICT: NEEDS REVIEW"


def _review(summary):
    return {"pr_number": 1, "ai_summary": summary, "repo": "KytranKatarn/archie-platform"}


class TestVerdictGate:
    """A finished review is not an approval."""

    def test_needs_changes_verdict_is_refused(self):
        with patch.object(github_service, "_automerge_governance_ok") as gate:
            gate.return_value = (False, "verdict is not an approval")
            res = github_service.merge_pr(1)
        assert res["merged"] is False
        assert res["governance_blocked"] is True

    def test_refusal_happens_before_any_github_call(self):
        """The gate must short-circuit — a refusal costs no API call and cannot race."""
        with patch.object(github_service, "_automerge_governance_ok", return_value=(False, "nope")):
            with patch.object(github_service, "_api_get") as api_get:
                res = github_service.merge_pr(1)
        api_get.assert_not_called()
        assert res["governance_blocked"] is True

    def test_human_override_skips_the_gate_entirely(self):
        """An attended admin merge must not consult the gate at all."""
        with patch.object(github_service, "_automerge_governance_ok") as gate:
            with patch.object(github_service, "_api_get", return_value=(False, {})):
                with patch.object(github_service, "check_before_write", return_value=(False, {"reason": "stop"})):
                    github_service.merge_pr(1, human_override=True)
        gate.assert_not_called()


class TestGovernanceDecision:
    """_automerge_governance_ok itself — verdict AND tier, both required."""

    def _run(self, summary, tier, max_tier="1"):
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(summary)):
            with patch(f"{mod}.classify_pr_tier", return_value=tier):
                with patch.dict("os.environ", {"FORGE_AUTO_MERGE_MAX_TIER": max_tier}):
                    return github_service._automerge_governance_ok(1)

    def test_approved_tier_1_is_allowed(self):
        ok, why = self._run(_APPROVED, 1)
        assert ok is True, why

    def test_approved_but_tier_2_is_refused(self):
        # The exact shape of #2458: policy says Tier 2/3 are human-gated (ADR-001/003).
        ok, why = self._run(_APPROVED, 2)
        assert ok is False
        assert "Tier 2" in why

    def test_needs_changes_refused_even_at_tier_1(self):
        ok, why = self._run(_NEEDS_CHANGES, 1)
        assert ok is False
        assert "not an approval" in why

    def test_needs_changes_refused_even_if_max_tier_raised(self):
        # Raising FORGE_AUTO_MERGE_MAX_TIER must not buy past the VERDICT check.
        ok, why = self._run(_NEEDS_CHANGES, 2, max_tier="3")
        assert ok is False
        assert "not an approval" in why


class TestFailsClosed:
    """Every uncertain input denies the merge. A dead review is not an approval."""

    def test_missing_review_row_is_refused(self):
        with patch("tools.repair_bay.services.pr_review_service.get_review", return_value=None):
            ok, why = github_service._automerge_governance_ok(999)
        assert ok is False
        assert "no stored" in why

    def test_exception_denies_rather_than_allows(self):
        with patch(
            "tools.repair_bay.services.pr_review_service.get_review",
            side_effect=RuntimeError("db down"),
        ):
            ok, why = github_service._automerge_governance_ok(1)
        assert ok is False
        assert "errored" in why

    @pytest.mark.parametrize("summary", ["", None, "no verdict line at all"])
    def test_empty_or_verdictless_summary_is_refused(self, summary):
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(summary)):
            with patch(f"{mod}.classify_pr_tier", return_value=1):
                ok, why = github_service._automerge_governance_ok(1)
        assert ok is False
