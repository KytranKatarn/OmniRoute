"""The sensitive-path allowlist must live at the CHOKE POINT (#5370).

PROVEN BYPASS, 2026-07-28: PR #2538 auto-merged while changing
``ai_bridge/agent_loop.py`` and ``pr_review_service.py``.
``_automerge_paths_allowed(2538)`` returns False naming exactly those two files —
the gate WOULD have refused it. Nothing ever asked, because the gate lived in
``pr_review_service.mark_review_done`` while the tier worker reaches GitHub through
``merge_pr`` -> ``_automerge_governance_ok``, which checked only verdict + tier.

Same omission twice: #2409 reached main carrying ``delegation_service.py`` "purely
because the diff was small enough for Tier 1" (the reason the allowlist exists), and
#2458 merged on a needs_changes verdict via this very second path. The #2459 fix moved
VERDICT and TIER to the choke point and left PATHS behind — two of three conditions.

The tests below pin BOTH directions. A gate that denies everything would be just as
broken as one that denies nothing, so the "allowlisted PR still merges" cases are as
load-bearing as the bypass case.
"""

import sys
import types

import pytest

import tools.repair_bay.services.github_service as gs


_HEAD_SHA = "abc123def4567890abc123def4567890abc123de"


@pytest.fixture
def gate(monkeypatch):
    """Drive _automerge_governance_ok with every dependency stubbed."""
    # ⚠️ This fixture replaces pr_review_service with a STUB MODULE, so it must expose
    # EVERY symbol _automerge_governance_ok imports. #5646/#2601 added `pr_head_sha` to
    # that import list; the stub did not gain it, so the import raised and the gate
    # returned a refusal before calling ANY stub function — `calls` stayed empty and the
    # failures read as `assert 'paths' in []`, i.e. the path gate looking broken when the
    # real problem was a stub missing one name. A stub module is a contract: adding an
    # import to the function under test means adding it here too.
    state = {
        "review": {
            "ai_summary": "VERDICT: APPROVE",
            "additions": 10,
            "deletions": 0,
            "changed_files": 1,
            # CONDITION 1b: the verdict must name the commit it covers, and it must equal
            # the current head (_head_sha below). Freshness itself is pinned in
            # test_merge_governance_gate.py::TestStaleVerdictGate, not here.
            "metadata": {"reviewed_head_sha": _HEAD_SHA},
        },
        "approved": True,
        "tier": 1,
        "paths_ok": True,
        "blocking": [],
        "head_sha": _HEAD_SHA,
        # CONDITION 0 (#380/#6680): None = an ordinary human-authored PR. Set it to a
        # reason string to make the stub report a machine-authored one. Machine
        # authorship is pinned in test_merge_governance_gate.py, not here — this key
        # exists so the path tests are not refused by a condition they are not about.
        "machine": None,
        "calls": [],
    }

    stub = types.ModuleType("tools.repair_bay.services.pr_review_service")

    def _get_review(pr, repo=None):
        state["calls"].append("get_review")
        return state["review"]

    def _verdict(summary):
        state["calls"].append("verdict")
        return state["approved"]

    def _tier(review):
        state["calls"].append("tier")
        return state["tier"]

    def _paths(pr, repo):
        state["calls"].append("paths")
        return state["paths_ok"], state["blocking"]

    def _head_sha(pr, repo=None):
        state["calls"].append("head_sha")
        return state["head_sha"]

    def _machine_authored(review):
        state["calls"].append("machine")
        return state["machine"]

    stub.get_review = _get_review
    stub.verdict_is_approved = _verdict
    stub.classify_pr_tier = _tier
    stub._automerge_paths_allowed = _paths
    stub.pr_head_sha = _head_sha
    stub.machine_authored_reason = _machine_authored
    monkeypatch.setitem(sys.modules, "tools.repair_bay.services.pr_review_service", stub)
    monkeypatch.setenv("FORGE_AUTO_MERGE_MAX_TIER", "1")
    return state


class TestTheBypassIsClosed:
    def test_non_allowlisted_paths_deny_the_merge(self, gate):
        """THE #2538 CASE. Tier 1 + APPROVE was enough before; now it is not."""
        gate["paths_ok"] = False
        gate["blocking"] = ["ai_bridge/agent_loop.py", "platform_v2/tools/repair_bay/services/pr_review_service.py"]

        ok, why = gs._automerge_governance_ok(2538)

        assert ok is False
        assert "allowlist" in why
        assert "agent_loop.py" in why, "name the offending file — a refusal must be actionable"

    def test_denial_holds_for_the_coo_authority_too(self, gate):
        """Safety properties are UNIVERSAL (decision #953) — not per-actor."""
        gate["paths_ok"] = False
        gate["blocking"] = ["platform_v2/services/agent_service.py"]
        gate["tier"] = 2

        ok, why = gs._automerge_governance_ok(1, authority="coo")

        assert ok is False
        assert "allowlist" in why

    def test_unknown_authority_also_denied(self, gate):
        gate["paths_ok"] = False
        gate["blocking"] = ["platform_v2/app.py"]
        ok, _ = gs._automerge_governance_ok(1, authority="something-new")
        assert ok is False

    def test_fails_closed_when_the_file_list_is_unavailable(self, gate):
        """Not knowing what a PR touches is not evidence that it is safe."""
        gate["paths_ok"] = False
        gate["blocking"] = ["<changed-file list unavailable>"]
        ok, why = gs._automerge_governance_ok(1)
        assert ok is False
        assert "unavailable" in why


class TestLegitimateAutoMergesStillWork:
    """A gate that denies everything is as broken as one that denies nothing."""

    def test_allowlisted_pr_is_still_permitted(self, gate):
        gate["paths_ok"] = True
        ok, why = gs._automerge_governance_ok(1)
        assert ok is True
        assert "approved" in why

    def test_allowlisted_tier2_under_coo_still_permitted(self, gate, monkeypatch):
        monkeypatch.setenv("ARCHIE_COO_AUTO_MERGE_MAX_TIER", "2")
        gate["tier"] = 2
        gate["paths_ok"] = True
        ok, _ = gs._automerge_governance_ok(1, authority="coo")
        assert ok is True

    def test_path_gate_does_not_override_an_existing_tier_denial(self, gate):
        """Allowlisted but over the ceiling must STILL be denied, on tier grounds."""
        gate["paths_ok"] = True
        gate["tier"] = 3
        ok, why = gs._automerge_governance_ok(1)
        assert ok is False
        assert "Tier 3" in why


class TestOrdering:
    def test_verdict_is_checked_before_paths(self, gate):
        """Don't spend a GitHub call on a merge the verdict already doomed."""
        gate["approved"] = False
        ok, _ = gs._automerge_governance_ok(1)
        assert ok is False
        assert "paths" not in gate["calls"], "path lookup costs an API call — skip it on a dead verdict"

    def test_paths_are_checked_before_tier(self, gate):
        """Universal safety check precedes the per-actor authority limit."""
        gate["paths_ok"] = False
        gate["blocking"] = ["platform_v2/app.py"]
        gs._automerge_governance_ok(1)
        assert "paths" in gate["calls"]
        assert "tier" not in gate["calls"], "a path denial should short-circuit before tier work"


class TestHumanOverrideIsUnaffected:
    def test_merge_pr_skips_the_whole_gate_for_a_human(self):
        """An authenticated interactive /merge-pr is a deliberate human decision."""
        import inspect

        src = inspect.getsource(gs.merge_pr)
        assert "if not human_override:" in src
        idx = src.index("if not human_override:")
        assert "_automerge_governance_ok" in src[idx : idx + 400], (
            "the governance gate — path check included — must sit INSIDE the "
            "`not human_override` branch so a human merge is never blocked by it"
        )


class TestDocstringMatchesBehaviour:
    def test_docstring_declares_every_condition(self):
        """It previously said TWO, then THREE, and each time named the asymmetry it closed.

        The count is load-bearing: this docstring is where the next person learns what
        the choke point actually enforces, and every under-count so far has coincided
        with a real condition living somewhere else (#2409 paths, #2458 verdict,
        #6680 machine authorship). Bump it when you add one.
        """
        doc = gs._automerge_governance_ok.__doc__ or ""
        assert "FOUR independent conditions" in doc
        assert "allowlisted paths" in doc
        assert "MACHINE-AUTHORED" in doc
        assert "safety" in doc.lower() and "authority" in doc.lower()
