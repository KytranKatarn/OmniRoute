"""A reachable large-window model must not make its fallback truncate review segments."""

from services.review_coverage import coverage
from tools.repair_bay.services import pr_diff_analyzer as analyzer
from tools.repair_bay.services.pr_review_service import parse_verdict


def run_fallback_review(monkeypatch, file_count=2, bound=2):
    # Strong model is reachable at planning time, but returns no usable review.
    # The actual fallback receives only the smaller window on every pass.
    full = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n"
        "@@ -0,0 +1,80 @@\n" + "+entry = 'unchanged metadata'\n" * 80
        for i in range(file_count)
    )
    visible = []
    chunks = []

    def fallback(prompt, *args, **kwargs):
        assert kwargs["diff"] == full, "grounding must retain the full diff"
        chunks.append(prompt)
        visible.append(analyzer._truncate_diff(prompt, 600)[0])
        return "VERDICT: APPROVE"

    monkeypatch.setattr(analyzer, "_get_setting", lambda *a, **k: None)
    monkeypatch.setattr(analyzer, "_tier3_is_reachable", lambda: True)
    monkeypatch.setattr(analyzer, "_diff_cap_for_model", lambda strong: 1200 if strong else 600)
    monkeypatch.setattr(analyzer, "_structured_review", lambda *a, **k: None)
    monkeypatch.setattr(analyzer, "_run_forge_review", fallback)
    monkeypatch.setattr(analyzer, "_build_prompt", lambda review, chunk: chunk)
    monkeypatch.setattr(analyzer, "mark_review_progress", lambda *a, **k: None)
    monkeypatch.setattr(analyzer, "_publish_file_progress", lambda *a, **k: None)
    with analyzer.review_scope_override(plan="per_file", max_files=bound):
        result = analyzer._obtain_review_summary({"title": "test"}, full, 1, "test/repo")
    return result, coverage(full, "\n".join(visible)), chunks


def test_strong_model_fallback_reads_every_file_completely(monkeypatch):
    result, actual_coverage, chunks = run_fallback_review(monkeypatch)
    assert len(chunks) > 2, "oversized files must be split into readable segments"
    assert all(len(chunk) <= 600 for chunk in chunks)
    assert actual_coverage["complete"] is True
    assert actual_coverage["reviewed"] == 2
    assert parse_verdict(result) == "APPROVE"
    assert "READ ONLY IN PART" not in result


def test_file_bound_still_blocks_unread_files(monkeypatch):
    result, actual_coverage, chunks = run_fallback_review(monkeypatch, file_count=3)
    assert all(len(chunk) <= 600 for chunk in chunks)
    assert actual_coverage["complete"] is False
    assert "f2.py" in actual_coverage["dropped"]
    assert parse_verdict(result) == "NEEDS REVIEW"
