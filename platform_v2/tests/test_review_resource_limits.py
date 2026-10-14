from unittest.mock import Mock

from tools.repair_bay.services import pr_diff_analyzer as pda


def setup(monkeypatch, settings):
    monkeypatch.setattr(pda, "_get_setting", lambda key, default=None: settings.get(key, default))
    monkeypatch.setattr(pda, "_review_plan", lambda: "per_file")
    monkeypatch.setattr(pda, "_review_max_files", lambda: 3)
    monkeypatch.setattr(pda, "_diff_cap_for_model", lambda strong: 9000)
    monkeypatch.setattr(pda, "_review_is_strong", lambda *_: False)
    monkeypatch.setattr(pda, "_check_dockerfile_provenance", lambda *_: [])
    monkeypatch.setattr(pda, "_publish_file_progress", lambda *_, **kw: {})
    monkeypatch.setattr(pda, "mark_review_file_progress", lambda *_, **kw: True)
    call = Mock(return_value="VERDICT: APPROVE")
    monkeypatch.setattr(pda, "_structured_review", call)
    diff = "".join(f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+x={i}\n" for i in range(2))
    return diff, call


def test_pass_limit_never_claims_remaining_file_was_read(monkeypatch):
    diff, call = setup(monkeypatch, {"forge:review_max_passes": 1})
    result = pda._obtain_review_summary({"title": "t"}, diff, 1, "o/r")
    assert call.call_count == 1
    assert "pass_limit" in result and "f1.py" in result
    assert pda.parse_verdict(result) == "NEEDS REVIEW"


def test_elapsed_budget_stops_only_at_safe_pass_boundary(monkeypatch):
    diff, call = setup(monkeypatch, {"forge:review_time_budget_seconds": 60})
    monkeypatch.setattr(pda, "_review_clock", Mock(side_effect=[0, 0, 61]))
    result = pda._obtain_review_summary({"title": "t"}, diff, 1, "o/r")
    assert call.call_count == 1 and "elapsed_time_limit" in result
    assert pda.parse_verdict(result) == "NEEDS REVIEW"


def test_pipeline_resumes_only_interrupted_identical_review(monkeypatch):
    import copy
    from services import review_checkpoints as rc

    diff, call = setup(monkeypatch, {"forge:review_max_passes": 1})
    monkeypatch.setattr(pda, "_review_prefer_agent", lambda: "F.O.R.G.E.")

    # Use a real function so the policy fingerprint includes loaded bytecode.
    def structured(*args, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(pda, "_structured_review", structured)
    saved = []
    monkeypatch.setattr(rc, "persist_checkpoint", lambda *args: saved.append(copy.deepcopy(args[-1])) or True)
    review = {"title": "t", "metadata": {}, "_checkpoint_identity": {"head_sha": "a" * 40, "base_sha": "b" * 40}}
    first = pda._obtain_text_review_summary(review, diff, 1, "o/r")
    assert call.call_count == 1 and "pass_limit" in first
    assert saved and saved[-1]["complete"] is False
    review["metadata"]["review_pass_checkpoint"] = saved[-1]
    second = pda._obtain_text_review_summary(review, diff, 1, "o/r")
    assert call.call_count == 2 and "pass_limit" not in second
    assert saved[-1]["complete"] is True
    review["metadata"]["review_pass_checkpoint"] = saved[-1]
    pda._obtain_text_review_summary(review, diff, 1, "o/r")
    assert call.call_count == 3  # Completed review is fresh, and hits this attempt's limit.
