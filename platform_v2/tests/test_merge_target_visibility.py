"""A merge row must name the branch it would actually land on (#5866).

2026-08-25: a 4-PR stack was "shipped" by clicking Merge on the TOP PR. That folded it
into its own parent — a branch that already contained everything below it — so the click
was a no-op and `main` never moved. The row read "Merge" and gave no hint it was not
shipping.

TWO defects, at different layers, and fixing either alone changes nothing:

  1. `list_all_prs_enriched` returns a FLATTENED payload with `head_ref` but **no `base`
     key at all**, while `poll_open_prs` read `pr["base"]["ref"]` — a key the producer has
     never emitted. It silently stored None every time: 1,878 of 2,518 rows were NULL.
  2. The upsert's `ON CONFLICT DO UPDATE SET` omitted `base_branch`, so even a correctly
     seeded row could never be refreshed — and GitHub RETARGETS a stacked PR when its
     parent merges, which is exactly when the stored value must be right.
"""

import ast
import inspect
from pathlib import Path

from tools.repair_bay.services.pr_review_service import merge_state

_APPROVED = "VERDICT: APPROVE"
_CHANGES = "VERDICT: REQUEST CHANGES"


# ------------------------------------------------------------- the pure decoration


def test_a_pr_targeting_main_is_untouched():
    """The negative control. Everything about a normal PR must be unchanged."""
    ms = merge_state("reviewed", _APPROVED, "main")
    assert ms["stacked"] is False
    assert ms["label"] == "APPROVED"
    assert ms["mergeable"] is True


def test_a_stacked_pr_names_its_real_target():
    ms = merge_state("reviewed", _APPROVED, "feat/parent")
    assert ms["stacked"] is True
    assert "feat/parent" in ms["label"]
    assert "NOT main" in ms["hint"] and "will NOT ship" in ms["hint"]


def test_stacking_does_NOT_change_mergeability():
    """WHERE it lands is orthogonal to WHETHER it may land. Merging into a parent is a
    legitimate act — the row just has to say so. If this ever starts gating, the
    decoration has quietly become a policy and can block correct merges."""
    for base in ("main", "feat/parent"):
        assert merge_state("reviewed", _APPROVED, base)["mergeable"] is True


def test_stacking_does_NOT_rescue_a_rejected_pr():
    """The other direction — decoration must not relax a real refusal either."""
    ms = merge_state("reviewed", _CHANGES, "feat/parent")
    assert ms["mergeable"] is False
    assert ms["stacked"] is True


def test_a_missing_base_is_not_reported_as_stacked():
    """NULL is UNKNOWN, not 'stacked'. Claiming a PR won't ship when we simply don't know
    would train the operator to ignore the warning."""
    for base in (None, "", "   "):
        assert merge_state("reviewed", _APPROVED, base)["stacked"] is False


def test_the_shape_is_stable_so_the_ui_needs_no_fallbacks():
    for base in (None, "main", "feat/parent"):
        ms = merge_state("reviewed", _APPROVED, base)
        assert {"state", "mergeable", "label", "hint", "dropped_files", "base_branch", "stacked"} <= set(ms)


def test_every_merge_state_carries_the_target_fields():
    """All five states route through the decorator — not just the happy one."""
    cases = [("in_progress", ""), ("pending", ""), ("reviewed", _APPROVED), ("reviewed", _CHANGES)]
    for status, summary in cases:
        ms = merge_state(status, summary, "feat/parent")
        assert "stacked" in ms and "base_branch" in ms, f"{status} lost the target fields"


# --------------------------------------------- the producer/consumer contract (defect 1)


def test_the_enriched_payload_emits_the_key_the_writer_reads():
    """THE regression test. The writer read `base`, the producer emitted neither `base`
    nor `base_ref` — so it stored None forever and nothing ever failed loudly.

    Parsed with ast, not grepped: a substring match would pass on the explanatory COMMENT
    that now sits directly above the key, which is exactly the "green on a comment" trap
    this suite has already been bitten by.
    """
    from tools.repair_bay.services import github_service

    src = inspect.getsource(github_service)
    keys = {
        n.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Dict)
        for n in node.keys
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "base_ref" in keys, "list_all_prs_enriched must flatten base_ref beside head_ref"
    assert "head_ref" in keys, "premise check — if this fails the test is looking at the wrong dicts"


def test_the_poll_reads_base_ref():
    from tools.repair_bay.services import pr_review_service

    src = inspect.getsource(pr_review_service.poll_open_prs)
    assert 'pr.get("base_ref")' in src, "poll_open_prs must read the flattened base_ref"


# ------------------------------------------------- the upsert refreshes it (defect 2)


def test_the_upsert_refreshes_base_branch_and_not_only_on_insert():
    """A poll must UPDATE the refs, not merely seed them.

    GitHub retargets a stacked PR when its parent merges, so a base captured at INSERT is
    wrong precisely when it decides whether a merge ships. Checked on the SQL text because
    the behaviour lives in the ON CONFLICT clause, and the alternative — a live upsert
    against a retargeted PR — cannot run in CI.
    """
    src = inspect.getsource(__import__("tools.repair_bay.services.pr_review_service", fromlist=["x"]).poll_open_prs)
    conflict = src.split("ON CONFLICT", 1)
    assert len(conflict) == 2, "premise check — the upsert must still use ON CONFLICT"
    update_clause = conflict[1]
    assert (
        "base_branch    = EXCLUDED.base_branch" in update_clause
        or "base_branch = EXCLUDED.base_branch" in update_clause
    )
    assert "head_branch" in update_clause


def test_the_service_file_is_where_the_fix_lives():
    """Guards against the fix being reverted by a file move."""
    p = Path(inspect.getfile(merge_state))
    assert p.name == "pr_review_service.py"
