"""Demand threshold for the startup warm-up list (#7330, #6106)."""

from __future__ import annotations

from services.warmup_demand import Thresholds, filter_by_demand, load_thresholds

INFRA = {"arctic-embed-cpu", "qwen25-classify", "minicpm-v-cpu"}
SKIP = {"qwen2.5vl:7b", "dolphin3:latest"}


def _row(model, runs, agents=1):
    return {"model": model, "dispatch_count": runs, "agent_count": agents}


def _run(rows, **kw):
    return filter_by_demand(rows, thresholds=kw.pop("thresholds", Thresholds()), infra=INFRA, hard_skip=SKIP)


def test_measured_2026_10_19_population():
    rows = [
        _row("qwen2.5:7b", 52445, 99),
        _row("qwen2.5:1.5b", 18256, 11),
        _row("gemma3:12b", 10589, 2),
        _row("mistral:7b", 4492, 7),
        _row("arctic-embed-cpu:latest", 458),
        _row("qwen2.5vl:7b", 113, 3),
        _row("qwen2.5-coder:7b", 102),
        _row("dolphin3:latest", 72, 3),
        _row("phi3.5:latest", 0),
    ]
    kept, dropped = _run(rows)
    assert kept == ["qwen2.5:7b", "qwen2.5:1.5b", "gemma3:12b", "mistral:7b", "arctic-embed-cpu:latest"]
    assert dict(dropped)["qwen2.5vl:7b"] == "hard_skip"
    assert dict(dropped)["dolphin3:latest"] == "hard_skip"
    assert dict(dropped)["phi3.5:latest"].startswith("low_demand")
    assert "runs_7d=102<200" in dict(dropped)["qwen2.5-coder:7b"]


def test_a_new_single_agent_idle_model_is_dropped_without_code_change():
    kept, dropped = _run([_row("brand-new:9b", 3)])
    assert kept == [] and dropped[0][0] == "brand-new:9b"


def test_infra_models_are_never_filtered_or_duplicated():
    kept, dropped = _run([_row("qwen25-classify", 0), _row("arctic-embed-cpu", 0)])
    assert kept == [] and dropped == []


def test_agent_count_alternative_is_off_by_default_and_works_when_set():
    assert _run([_row("wide:7b", 0, agents=5)])[0] == []
    kept, _ = _run([_row("wide:7b", 0, agents=5)], thresholds=Thresholds(min_agents=3))
    assert kept == ["wide:7b"]


def test_threshold_boundary_is_inclusive():
    assert _run([_row("edge:7b", 200)])[0] == ["edge:7b"]
    assert _run([_row("edge:7b", 199)])[0] == []


def test_null_counts_do_not_raise():
    kept, dropped = _run([{"model": "x:1b", "dispatch_count": None, "agent_count": None}])
    assert kept == [] and dropped[0][0] == "x:1b"


class _Cur:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom = rows or [], boom

    def execute(self, *_a):
        if self.boom:
            raise RuntimeError("db down")

    def fetchall(self):
        return self.rows


def test_thresholds_read_from_settings():
    cur = _Cur([{"key": "warmup:min_runs_7d", "value": "50"}, {"key": "warmup:min_agents", "value": "4"}])
    assert load_thresholds(cur) == Thresholds(min_runs_7d=50, min_agents=4)


def test_bad_or_missing_settings_fall_back_to_defaults():
    assert load_thresholds(_Cur([{"key": "warmup:min_runs_7d", "value": "lots"}])) == Thresholds()
    assert load_thresholds(_Cur([{"key": "warmup:min_runs_7d", "value": "-5"}])) == Thresholds()
    assert load_thresholds(_Cur(boom=True)) == Thresholds()
    assert load_thresholds(_Cur([])) == Thresholds()
