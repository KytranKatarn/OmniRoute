"""The coverage note must describe what the review ACTUALLY saw (#5836 follow-up).

Background. `_obtain_review_summary` measured coverage at `_diff_cap_for_model(strong=False)`
— a fixed 9,000 chars — no matter which model ran. That was deliberate and safe while every
path used that cap. It stopped being accurate once Tier-3 reviews started running on
gemma3:12b, whose window-aware cap reaches _DIFF_MAX_WIDE.

Measured 2026-08-24 on PR #2792: the note reported "3 of 6 files read, github_service.py
about 39%" for a review that received the entire 19,461-char diff at a 20,000 cap. The
review then quoted a line that exists ONLY in github_service.py — it could not have done so
without reading the file the note called truncated. Every Tier-3 strong-path review is being
spuriously coverage-demoted.

The fix is NOT to measure at the strong cap. `_structured_review(...) or _run_forge_review(...)`
means a Tier-3 pass can FAIL and fall back to freeform, which always runs at the weak cap.
Measuring optimistically would OVERSTATE coverage — the exact direction #5836 exists to
prevent. Measure at the NARROWEST cap any pass actually used.
"""

from tools.repair_bay.services.pr_diff_analyzer import _effective_coverage_cap


def test_a_strong_pass_is_measured_at_the_strong_cap():
    """The bug: a Tier-3 review that saw 18,768 chars was reported against 9,000."""
    assert _effective_coverage_cap([18768], planning_cap=9000) == 18768


def test_a_freeform_fallback_pins_the_note_to_the_weak_cap():
    """A Tier-3 PR whose structured pass failed ran freeform at the WEAK cap. Reporting the
    strong cap here would claim coverage the review never had."""
    assert _effective_coverage_cap([9000], planning_cap=9000) == 9000


def test_a_mixed_run_takes_the_NARROWEST_pass_never_the_widest():
    """Chunked review: one pass strong, one fell back. The note must describe the worst pass.
    max() here would overstate coverage — #5836's own failure direction."""
    assert _effective_coverage_cap([18768, 9000], planning_cap=9000) == 9000
    assert _effective_coverage_cap([9000, 18768], planning_cap=9000) == 9000


def test_no_passes_recorded_falls_back_to_the_planning_cap():
    """Fail closed: if nothing recorded a cap, keep the conservative pre-existing behaviour
    rather than inventing a wider one."""
    assert _effective_coverage_cap([], planning_cap=9000) == 9000
    assert _effective_coverage_cap(None, planning_cap=9000) == 9000


def test_a_none_entry_cannot_widen_the_result():
    """A pass that recorded no cap is unknown, not unlimited. Unknown must not raise the
    measured window — that would be the overstating direction again."""
    assert _effective_coverage_cap([None, 18768], planning_cap=9000) == 9000
