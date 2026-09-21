"""A review must get a model whose window can HOLD the diff (#6023).

MEASURED 2026-08-25. Three PRs reviewed minutes apart, all on the structured path:

    #2827  structured=json model=gemma3:12b  -> cap 18,768 -> FULL coverage
    #2828  structured=json model=default     -> cap  9,000 -> 205 of 11,570 chars (2%)
    #2829  structured=json model=default     -> cap  9,000 -> 0 of 3 files

`_diff_cap_for_model` gives the impatient 7B 9,000 chars and the patient gemma3:12b the
full window. Nothing ensured a diff got a model that could hold it, so a low-tier PR over
9,000 was simply CUT — #2828's 11,570-char diff to **205 characters**, with the reviewer
still emitting `confidence=1.0`.

⚠️ The coverage gate was HONEST throughout and is NOT the bug. It reported the truncation
accurately and floored the verdict. Do not "fix" it.
"""

import contextlib
from unittest import mock

from tools.repair_bay.services import pr_diff_analyzer
from tools.repair_bay.services.pr_diff_analyzer import _diff_cap_for_model, _review_is_strong

WEAK = _diff_cap_for_model(False)
STRONG = _diff_cap_for_model(True)


def _low_tier():
    """A PR the tier classifier will not call Tier-3."""
    return {"pr_number": 1, "title": "chore: tweak a comment", "repo": "KytranKatarn/archie-platform"}


# ------------------------------------------------------------- the premise


def test_the_two_caps_actually_differ():
    """The whole bug depends on this. If they ever converge the escalation is pointless
    and these tests would silently pass on a no-op."""
    assert WEAK < STRONG, f"weak {WEAK} must be below strong {STRONG}"


# ------------------------------------------------------------- the escalation


@contextlib.contextmanager
def _reachable(value: bool = True):
    """#6779 gave `_review_is_strong` a second input: is the patient model REACHABLE.

    The size-rule tests must pin ONE variable, so they pin reachability. Without this
    they fail wherever no node carries the tier-3 model — which is every test host —
    and, worse, the "must NOT escalate" assertions would pass vacuously.
    """
    with mock.patch.object(pr_diff_analyzer, "_tier3_is_reachable", return_value=value):
        yield


def test_an_unreachable_patient_model_is_never_requested():
    """The #6779 gate itself: deserving is not the same as reachable. Asking for a model
    no node can run is what produced the 1-second refusals and the weak-cap review."""
    with _reachable(False):
        assert _review_is_strong(_low_tier(), "x" * (WEAK + 1)) is False
    with _reachable(True):
        assert _review_is_strong(_low_tier(), "x" * (WEAK + 1)) is True

def test_a_diff_over_the_weak_cap_requests_the_strong_model():
    """The fix. #2828's 11,570 chars against a 9,000 cap."""
    with _reachable():
        assert _review_is_strong(_low_tier(), "x" * (WEAK + 1)) is True


def test_a_diff_that_fits_does_NOT_escalate():
    """The negative control — without it, a function that always returned True would pass
    every other test here, and every review would be pushed onto the slow model."""
    assert _review_is_strong(_low_tier(), "x" * (WEAK - 1)) is False


def test_a_diff_that_fits_EXACTLY_does_not_escalate():
    """Boundary. `> cap`, not `>= cap` — a diff that fits needs no patient model."""
    assert _review_is_strong(_low_tier(), "x" * WEAK) is False


def test_no_diff_falls_back_to_the_tier_rule_only():
    """The parameter is optional, so existing callers keep the pre-#6023 behaviour rather
    than silently gaining a wide window."""
    assert _review_is_strong(_low_tier()) is False
    assert _review_is_strong(_low_tier(), None) is False
    assert _review_is_strong(_low_tier(), "") is False


def test_escalation_survives_a_broken_tier_classifier():
    """The size rule must not sit BEHIND a raising classifier. Before the fix the tier
    check was the only rule and its except returned immediately; a classifier failure
    would now silently strand every oversized diff on the 9,000 cap."""
    with _reachable():
        assert _review_is_strong({"garbage": object()}, "x" * (WEAK + 1)) is True


def test_an_unclassifiable_pr_with_a_small_diff_still_fails_CLOSED():
    """Fail-closed is preserved: unknown tier + a diff that fits => narrow path."""
    assert _review_is_strong({"garbage": object()}, "x" * (WEAK - 1)) is False


# ------------------------------------- the invariant the helper exists to protect


def test_both_call_sites_pass_a_diff_so_they_cannot_drift():
    """`_structured_review` (model selection) and `_obtain_review_summary` (coverage cap)
    MUST decide from the same input. That is the entire reason this is one helper — and
    the model selection is handed a CHUNK, so the coverage side must use the chunk too,
    not the whole diff.
    """
    import ast
    import inspect

    from tools.repair_bay.services import pr_diff_analyzer

    tree = ast.parse(inspect.getsource(pr_diff_analyzer))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_review_is_strong"
    ]
    assert len(calls) >= 2, f"expected both call sites, found {len(calls)}"
    for c in calls:
        assert len(c.args) == 2, "every _review_is_strong call must pass a diff — a bare call re-opens #6023"
    # the coverage-side call must use the CHUNK, not the full diff
    names = {c.args[1].id for c in calls if isinstance(c.args[1], ast.Name)}
    assert "_chunk" in names, "the coverage-side call must decide from the chunk the model sees"


def test_the_weak_cap_is_not_quietly_widened():
    """The 7B's 9,000 cap is load-bearing: it must finish inside the 240s per-node dispatch
    window or it times out to the weaker freeform path (#1901). The fix escalates the MODEL;
    widening this cap instead would re-open that bug."""
    from tools.repair_bay.services.pr_diff_analyzer import _DIFF_MAX_7B

    assert _DIFF_MAX_7B <= 9000, "raising the 7B cap re-opens the #1901 timeout — escalate the model instead"
