"""At forge:review_max_chunks=1 the pipeline is byte-identical to pre-chunking (#5848 task 6).

The plan proposed pinning `chunk_plan(d, cap, 1) == [d]`. That is necessary but nowhere near
sufficient, and `test_chunk_plan.py::test_single_chunk_is_byte_identical_to_truncation` already
covers it. The killswitch claim is about the whole of `_obtain_review_summary`: at max_chunks=1
it must call the reviewer ONCE, ground it the way the pre-chunking code did, compute the
whole-PR checks on the same input, and return the pass's summary UNTOUCHED — the merge shape
must never appear. Those are the properties a rollback actually depends on.
"""

import importlib.util
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.review_coverage import annotate, chunk_plan, coverage, prioritize  # noqa: E402
from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402

_CAP = 9000
# Oversized and multi-file, so prioritize() reorders and _truncate_diff() actually cuts —
# a diff that FITS would exercise none of the machinery this test exists to pin.
_FULL = (
    "".join(f"diff --git a/tests/test_{i}.py b/tests/test_{i}.py\n@@ -1 +1 @@\n+{'t' * 900}\n" for i in range(4))
    + "".join(f"diff --git a/svc{i}.py b/svc{i}.py\n@@ -1 +1 @@\n+{'c' * 2600}\n" for i in range(3))
    + "diff --git a/README.md b/README.md\n@@ -1 +1 @@\n+docs\n"
)
# A realistic review row: the freeform fallback builds its prompt from these, so a bare
# {"title": ...} stub KeyErrors the moment the structured path returns None.
_REVIEW = {
    "pr_number": 1,
    "title": "t",
    "author": "claude",
    "repo": "KytranKatarn/archie-platform",
    "additions": 10,
    "deletions": 2,
    "changed_files": 8,
}
_SUMMARY = (
    "SUMMARY\nlooks fine\n\nISSUES\nNo issues found.\n\n"
    "VERDICT: APPROVE\n[review-meta] structured=json model=m confidence=0.9"
)


def _run_at_one(**extra):
    patches = {"_review_max_chunks": 1, "_diff_cap_for_model": _CAP}
    with mock.patch.object(pda, "_review_max_chunks", return_value=1), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=_CAP
    ), mock.patch.object(pda, "_structured_review", side_effect=extra.get("structured", lambda *a, **k: _SUMMARY)):
        return pda._obtain_review_summary(_REVIEW, _FULL, 1, "r")


def test_output_is_byte_identical_to_the_pre_chunking_pipeline():
    """The reference is what _obtain_review_summary did before #5848, transcribed:
    prioritize -> _truncate_diff -> coverage -> annotate. Any drift in the max_chunks=1 path
    changes this string."""
    ref_diff = prioritize(_FULL, _CAP)
    ref_shown, _ = pda._truncate_diff(ref_diff, _CAP)
    expected = annotate(_SUMMARY, coverage(ref_diff, ref_shown))
    assert _run_at_one() == expected


def test_the_reviewer_is_called_exactly_once_and_shown_the_whole_prioritized_diff():
    seen = []

    def structured(review, diff, pr_number=None, repo=None, ground_diff=None, dockerfile_findings=None):
        seen.append((diff, ground_diff))
        return _SUMMARY

    _run_at_one(structured=structured)
    assert len(seen) == 1, f"one pass at max_chunks=1, got {len(seen)}"
    shown, ground = seen[0]
    assert shown == prioritize(_FULL, _CAP), "the single pass must see the whole prioritized diff"
    assert ground == shown, "at one chunk, shown and grounded are the same object of study"


def test_the_merge_never_runs_for_a_single_pass():
    """If the merge ever ran at max_chunks=1 the rollback would not be a rollback — the summary
    would come back reshaped as 'Chunked review (N passes)' with findings re-rendered."""
    called = []
    with mock.patch.object(pda, "_merge_chunk_summaries", side_effect=lambda *a, **k: called.append(1) or "x"):
        out = _run_at_one()
    assert not called, "_merge_chunk_summaries must not be reachable at max_chunks=1"
    assert "Chunked review" not in out


def test_whole_pr_provenance_is_computed_once_on_the_pre_chunking_input():
    """#4749 moved out of _structured_review in task 5. It must still run exactly once, against
    the same diff the old in-function call received (ground_diff, which was the full diff)."""
    calls = []
    with mock.patch.object(pda, "_check_dockerfile_provenance", side_effect=lambda d: calls.append(d) or []):
        _run_at_one()
    assert calls == [prioritize(_FULL, _CAP)]


def test_an_unavailable_reviewer_still_returns_None_not_a_fabricated_review():
    """Pre-chunking, both paths failing yielded None ('review unavailable'). A merge that
    invented an empty APPROVE here would be the #2458 shape."""
    with mock.patch.object(pda, "_review_max_chunks", return_value=1), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=_CAP
    ), mock.patch.object(pda, "_structured_review", return_value=None), mock.patch.object(
        pda, "_run_forge_review", return_value=None
    ):
        assert pda._obtain_review_summary(_REVIEW, _FULL, 1, "r") is None


def test_the_killswitch_guard_in_chunk_plan_is_load_bearing():
    """Mutation check (repair-bay.md): a test that cannot fail is worse than no test. Reintroduce
    the defect in a COPY of the module — never the live file — and confirm the pin goes red."""
    src = (_ROOT / "services" / "review_coverage.py").read_text()
    guard = "    if max_chunks <= 1:\n        return [diff]\n"
    assert src.count(guard) == 1, "guard moved — update this mutation test"

    broken = _ROOT / "services" / "_review_coverage_mutant.py"
    broken.write_text(src.replace(guard, "", 1))
    try:
        spec = importlib.util.spec_from_file_location("_review_coverage_mutant", broken)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert chunk_plan(_FULL, _CAP, 1) == [_FULL], "live guard must hold"
        assert mod.chunk_plan(_FULL, _CAP, 1) != [_FULL], "mutant must break the pin — else it proves nothing"
    finally:
        broken.unlink(missing_ok=True)


def test_the_byte_identity_pin_is_not_vacuous():
    """Guards the guard. If the pre-chunking reference matched at ANY max_chunks, the equality
    above would prove nothing — it would just mean the reference had drifted to track whatever
    the code does. At 3 the pipeline MUST produce something different."""
    ref_diff = prioritize(_FULL, _CAP)
    ref_shown, _ = pda._truncate_diff(ref_diff, _CAP)
    expected = annotate(_SUMMARY, coverage(ref_diff, ref_shown))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=_CAP
    ), mock.patch.object(pda, "_structured_review", return_value=_SUMMARY):
        out = pda._obtain_review_summary(_REVIEW, _FULL, 1, "r")
    assert out != expected, "chunking at 3 produced the pre-chunking output — the pin is vacuous"
