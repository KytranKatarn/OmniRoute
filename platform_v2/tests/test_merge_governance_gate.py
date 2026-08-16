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

# The commit the stored review is pinned to. #5646/#2601 added CONDITION 1b: a verdict
# only counts if it demonstrably covers the CURRENT head, so a fixture review must say
# which commit it saw or the gate refuses before any verdict/tier assertion is reached.
_HEAD_SHA = "abc123def4567890abc123def4567890abc123de"


def _review(summary, head_sha=_HEAD_SHA):
    """A stored review row.

    ``metadata.reviewed_head_sha`` is REQUIRED by CONDITION 1b — pass ``head_sha=None``
    to build the pre-#5646 unstamped row that the gate must refuse.
    """
    row = {"pr_number": 1, "ai_summary": summary, "repo": "KytranKatarn/archie-platform"}
    if head_sha is not None:
        row["metadata"] = {"reviewed_head_sha": head_sha}
    return row


@pytest.fixture(autouse=True)
def _paths_allowed_by_default():
    """Neutralise the SENSITIVE-PATH condition for the tests in this file (#5370).

    `_automerge_governance_ok` gained a third required condition: the PR must touch
    only auto-merge-allowlisted paths. It is checked BEFORE tier, so without this
    stub every test here would short-circuit on paths and never reach the
    verdict/tier assertion it exists to make — and worse, it would reach for the
    real GitHub API from a unit test.

    These tests are about VERDICT and TIER, so paths are held "allowed" and the
    path behaviour is covered separately in test_automerge_path_gate.py. A test
    that genuinely cares about paths should patch this itself.
    """
    with patch(
        "tools.repair_bay.services.pr_review_service._automerge_paths_allowed",
        return_value=(True, []),
    ):
        yield


@pytest.fixture(autouse=True)
def _head_sha_is_current_by_default():
    """Neutralise the FRESHNESS condition for the tests in this file (#5646 / #2601).

    Same reasoning as the path stub above, one condition later. CONDITION 1b requires the
    stored verdict to name the commit it covers and for that to equal the CURRENT head; it
    is checked BEFORE tier, so without this stub every test here refuses with "does not
    record which commit it covers" and never reaches the verdict/tier assertion it exists
    to make. That is exactly what happened: these 7 tests were red from the moment #2601
    shipped, and a red suite hides real breakage in the gate that guards every merge.

    Freshness itself is covered deliberately in TestStaleVerdictGate below — this stub
    removes it from the OTHER tests' path, it does not remove it from the file.
    """
    with patch(
        "tools.repair_bay.services.pr_review_service.pr_head_sha",
        return_value=_HEAD_SHA,
    ):
        yield


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


class TestPerAuthorityCeiling:
    """The tier ladder is an AUTHORITY ladder: tier 1 F.O.R.G.E., 2 A.R.C.H.I.E., 3 Kytran.

    The first cut of this gate read FORGE_AUTO_MERGE_MAX_TIER for every caller, so
    A.R.C.H.I.E.'s Tier-2 COO path inherited F.O.R.G.E.'s Tier-1 ceiling and was always
    refused — silently removing the COO from her own loop. Safety (an approved verdict) is
    UNIVERSAL; the ceiling is PER-ACTOR.
    """

    def _run(self, tier, authority, env=None):
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(_APPROVED)):
            with patch(f"{mod}.classify_pr_tier", return_value=tier):
                with patch.dict("os.environ", env or {}, clear=False):
                    return github_service._automerge_governance_ok(1, authority=authority)

    def test_coo_may_merge_tier_2(self):
        ok, why = self._run(2, "coo")
        assert ok is True, why

    def test_forge_may_not_merge_tier_2(self):
        ok, why = self._run(2, "forge")
        assert ok is False
        assert "FORGE_AUTO_MERGE_MAX_TIER" in why

    def test_forge_may_still_merge_tier_1(self):
        ok, why = self._run(1, "forge")
        assert ok is True, why

    def test_tier_3_is_refused_even_for_the_coo(self):
        # Tier 3 is Kytran's. No delegated authority reaches it.
        ok, why = self._run(3, "coo")
        assert ok is False
        assert "Tier 3" in why

    def test_unknown_authority_falls_back_to_most_restrictive(self):
        # An unrecognised caller must never inherit COO powers.
        ok, _ = self._run(2, "some_new_agent")
        assert ok is False

    def test_default_authority_is_forge(self):
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(_APPROVED)):
            with patch(f"{mod}.classify_pr_tier", return_value=2):
                ok, _ = github_service._automerge_governance_ok(1)  # no authority passed
        assert ok is False

    def test_coo_ceiling_is_independently_tunable(self):
        # Her ceiling is HERS — not a FORGE_-scoped setting.
        ok, _ = self._run(3, "coo", env={"ARCHIE_COO_AUTO_MERGE_MAX_TIER": "3"})
        assert ok is True

    def test_verdict_gate_is_universal_across_authorities(self):
        """COO authority buys tier headroom, never a pass on a non-approval."""
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(_NEEDS_CHANGES)):
            with patch(f"{mod}.classify_pr_tier", return_value=2):
                ok, why = github_service._automerge_governance_ok(1, authority="coo")
        assert ok is False
        assert "not an approval" in why


class TestStaleVerdictGate:
    """CONDITION 1b (#5646 / #2601): an approval of DIFFERENT code is not an approval.

    The two autouse fixtures above hold freshness "current" for every other test in this
    file so they can assert verdict/tier. This class is where freshness itself is pinned —
    it overrides those stubs deliberately. Without it, stamping the fixtures would have
    QUIETLY DELETED the coverage of the newest condition in the merge gate.

    Measured on PR #2600: APPROVE stored at 02:38:36Z, then a commit at 02:41:41Z touching
    a file the review never saw. The verdict was genuine — of different code.
    """

    def _run(self, *, reviewed_sha, current_sha, tier=1):
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(_APPROVED, head_sha=reviewed_sha)):
            with patch(f"{mod}.classify_pr_tier", return_value=tier):
                with patch(f"{mod}.pr_head_sha", return_value=current_sha):
                    with patch.dict("os.environ", {"FORGE_AUTO_MERGE_MAX_TIER": "1"}):
                        return github_service._automerge_governance_ok(1)

    def test_matching_head_sha_is_allowed(self):
        ok, why = self._run(reviewed_sha=_HEAD_SHA, current_sha=_HEAD_SHA)
        assert ok is True, why

    def test_stale_verdict_is_refused(self):
        """The review covers an older commit than the one about to merge."""
        ok, why = self._run(reviewed_sha=_HEAD_SHA, current_sha="9999999999999999999999999999999999999999")
        assert ok is False
        assert "STALE VERDICT" in why

    def test_unstamped_pre_5646_row_is_refused(self):
        """Fails CLOSED: a row that cannot prove freshness does not get the benefit of doubt."""
        ok, why = self._run(reviewed_sha=None, current_sha=_HEAD_SHA)
        assert ok is False
        assert "does not record which commit" in why

    def test_unreadable_head_sha_is_refused(self):
        """An unknown CURRENT sha is refused too — never assume the stored verdict is current."""
        ok, why = self._run(reviewed_sha=_HEAD_SHA, current_sha="")
        assert ok is False
        assert "could not read the current head SHA" in why

    def test_freshness_binds_the_coo_too(self):
        """A SAFETY property is universal; only tier ceilings are per-authority (#953)."""
        mod = "tools.repair_bay.services.pr_review_service"
        with patch(f"{mod}.get_review", return_value=_review(_APPROVED, head_sha=None)):
            with patch(f"{mod}.classify_pr_tier", return_value=1):
                with patch(f"{mod}.pr_head_sha", return_value=_HEAD_SHA):
                    ok, why = github_service._automerge_governance_ok(1, authority="coo")
        assert ok is False
        assert "does not record which commit" in why
