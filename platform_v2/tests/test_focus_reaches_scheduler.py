"""AUX POWER focus must reach the SCHEDULER, not just the within-model row order (#6080).

Measured 2026-10-15. The owner selected `Platform + AUX POWER -> REPAIR BAY`, expecting
Repair Bay PR reviews to get queue priority. The setting was stored and read correctly and
`queue_row_gets_priority` returned True — yet reviews still waited and expired. The reason
was structural, not a disabled flag:

  * the focus reached exactly ONE decision, the row ORDER inside a single model's claim
    pool (`_claim_tasks` -> `_profile_ordered_ids`);
  * Repair Bay reviews need `gemma3:12b`, whose pool held ONE row, so reordering it was a
    no-op;
  * the two decisions that actually gate whether that model ever RUNS — which cold model
    gets the cycle's single load slot (`_get_highest_priority_queued_model`) and which warm
    lane drains first (`_drain_order`, #6749) — did not consult the focus at all.

`_cold_load_candidates` and `_drain_order(..., priority_models=...)` close that gap. The
call-site assertions matter as much as the helper ones: this repo has reverted a fix at the
call site while helper-only tests stayed green.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.model_dispatch_service as m  # noqa: E402
from services.model_dispatch_service import (  # noqa: E402
    _canonical_model_name,
    _cold_load_candidates,
    _drain_order,
)

_SERVICE_SRC = os.path.join(os.path.dirname(__file__), "..", "services", "model_dispatch_service.py")


# ---------------------------------------------------------------------------
# fakes — the probe must be testable without a DB
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return list(self._rows)


class _FakeCM:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *_a):
        return False


def _patch_db(monkeypatch, rows):
    monkeypatch.setattr(m, "get_db_cursor", lambda *a, **k: _FakeCM(_FakeCursor(rows)))


# ---------------------------------------------------------------------------
# 1. drain order: focus wins, head-age order preserved within groups
# ---------------------------------------------------------------------------


class TestDrainOrderFocus:
    def test_focused_lane_sorts_first_even_against_an_older_head(self):
        """The whole point: Repair Bay's lane must not lose to a bigger backlog."""
        warm = {"qwen25-classify:latest": [None], "gemma3:12b": [None]}
        ages = {"qwen25-classify:latest": 9000.0, "gemma3:12b": 60.0}
        order = [n for n, _ in _drain_order(warm, ages, priority_models={_canonical_model_name("gemma3:12b")})]
        assert order[0] == "gemma3:12b"

    def test_head_age_order_preserved_within_each_group(self):
        warm = {"a:latest": [None], "b:latest": [None], "c:latest": [None], "d:latest": [None]}
        ages = {"a:latest": 100.0, "b:latest": 900.0, "c:latest": 50.0, "d:latest": 800.0}
        # a,b focused -> b (older) then a; c,d plain -> d (older) then c.
        order = [
            n
            for n, _ in _drain_order(
                warm,
                ages,
                priority_models={_canonical_model_name("a"), _canonical_model_name("b")},
            )
        ]
        assert order == ["b:latest", "a:latest", "d:latest", "c:latest"]

    def test_no_priority_models_is_byte_identical_to_before(self):
        warm = {"a:latest": [None], "b:latest": [None], "c:latest": [None]}
        ages = {"a:latest": 60.0, "b:latest": 7800.0, "c:latest": 300.0}
        assert [n for n, _ in _drain_order(warm, ages)] == ["b:latest", "c:latest", "a:latest"]
        assert [n for n, _ in _drain_order(warm, ages, priority_models=set())] == ["b:latest", "c:latest", "a:latest"]

    def test_focus_never_drops_or_duplicates_a_model(self):
        warm = {"a:latest": [None], "b:latest": [None]}
        ages = {"a:latest": 10.0, "b:latest": 20.0}
        order = [n for n, _ in _drain_order(warm, ages, priority_models={_canonical_model_name("a")})]
        assert sorted(order) == ["a:latest", "b:latest"]
        assert len(order) == 2

    def test_focus_name_absent_from_inventory_is_harmless(self):
        warm = {"a:latest": [None]}
        order = [n for n, _ in _drain_order(warm, {}, priority_models={_canonical_model_name("ghost:12b")})]
        assert order == ["a:latest"]


# ---------------------------------------------------------------------------
# 2. cold-load candidate: focused first, but never hostage to a warm/unplaceable one
# ---------------------------------------------------------------------------


class TestColdLoadCandidates:
    def test_focused_cold_model_is_tried_before_the_plain_pick(self, monkeypatch):
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: "qwen25-classify")
        out = _cold_load_candidates({}, {"gemma3:12b": {"max_prio": 7, "cnt": 1}})
        assert out == ["gemma3:12b", "qwen25-classify"]

    def test_focused_highest_priority_wins_within_the_family(self, monkeypatch):
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: "qwen25-classify")
        meta = {"gemma3:12b": {"max_prio": 7, "cnt": 1}, "audit-x": {"max_prio": 9, "cnt": 4}}
        assert _cold_load_candidates({}, meta)[0] == "audit-x"

    def test_warm_focused_model_does_not_hold_the_slot(self, monkeypatch):
        """Once gemma3:12b is warm the slot must fall through to classify, not be wasted."""
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: "qwen25-classify")
        out = _cold_load_candidates({"gemma3:12b": [None]}, {"gemma3:12b": {"max_prio": 7, "cnt": 1}})
        assert out == ["qwen25-classify"]

    def test_focused_equals_plain_yields_one_attempt(self, monkeypatch):
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: "gemma3:12b")
        assert _cold_load_candidates({}, {"gemma3:12b": {"max_prio": 7, "cnt": 1}}) == ["gemma3:12b"]

    def test_no_focus_degenerates_to_the_plain_pick(self, monkeypatch):
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: "qwen25-classify")
        assert _cold_load_candidates({}, {}) == ["qwen25-classify"]

    def test_everything_warm_yields_no_candidates(self, monkeypatch):
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: "qwen25-classify")
        warm = {"qwen25-classify": [None], "gemma3:12b": [None]}
        assert _cold_load_candidates(warm, {"gemma3:12b": {"max_prio": 7, "cnt": 1}}) == []

    def test_bare_and_tagged_warm_forms_both_suppress_the_candidate(self, monkeypatch):
        """A colon-less model must match its ``:latest`` warm key (#6749), or a warm
        focused model would be cold-loaded again every cycle."""
        monkeypatch.setattr(m, "_get_highest_priority_queued_model", lambda: None)
        warm = {"arctic-embed-cpu:latest": [None]}
        assert _cold_load_candidates(warm, {"arctic-embed-cpu": {"max_prio": 3, "cnt": 1}}) == []


# ---------------------------------------------------------------------------
# 3. the probe itself: focused family only, fail-safe to {}
# ---------------------------------------------------------------------------


class TestFocusedFamilyProbe:
    def test_returns_only_the_focused_family_models(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "platform")
        monkeypatch.setattr(m, "_get_profile_focus", lambda mode: "repair_bay")
        _patch_db(
            monkeypatch,
            [
                {"model_needed": "gemma3:12b", "max_prio": 7, "cnt": 1, "mods": ["repair_bay"]},
                {"model_needed": "qwen25-classify", "max_prio": 9, "cnt": 23, "mods": ["quality_scorer"]},
            ],
        )
        meta = m._focused_family_model_meta()
        assert set(meta) == {"gemma3:12b"}
        assert meta["gemma3:12b"] == {"max_prio": 7, "cnt": 1}

    def test_never_boost_module_is_not_adopted(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "platform")
        monkeypatch.setattr(m, "_get_profile_focus", lambda mode: "repair_bay")
        _patch_db(
            monkeypatch,
            [{"model_needed": "qwen2.5:1.5b", "max_prio": 1, "cnt": 500, "mods": ["kin_warmth"]}],
        )
        assert m._focused_family_model_meta() == {}

    def test_family_match_is_case_and_substring_tolerant(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "platform")
        monkeypatch.setattr(m, "_get_profile_focus", lambda mode: "repair_bay")
        _patch_db(monkeypatch, [{"model_needed": "m", "max_prio": 1, "cnt": 1, "mods": ["audit_pipeline"]}])
        assert set(m._focused_family_model_meta()) == {"m"}

    def test_auto_mode_short_circuits_without_touching_the_db(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "auto")
        monkeypatch.setattr(m, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB hit")))
        assert m._focused_family_model_meta() == {}

    def test_platform_without_focus_short_circuits(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "platform")
        monkeypatch.setattr(m, "_get_profile_focus", lambda mode: "")
        monkeypatch.setattr(m, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB hit")))
        assert m._focused_family_model_meta() == {}

    def test_db_error_fails_safe_to_no_focus(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "platform")
        monkeypatch.setattr(m, "_get_profile_focus", lambda mode: "repair_bay")

        def _boom(*_a, **_k):
            raise RuntimeError("db down")

        monkeypatch.setattr(m, "get_db_cursor", _boom)
        assert m._focused_family_model_meta() == {}

    def test_null_module_id_row_is_not_adopted(self, monkeypatch):
        monkeypatch.setattr(m, "_get_profile_mode", lambda: "platform")
        monkeypatch.setattr(m, "_get_profile_focus", lambda mode: "repair_bay")
        _patch_db(monkeypatch, [{"model_needed": "m", "max_prio": 1, "cnt": 1, "mods": [None]}])
        assert m._focused_family_model_meta() == {}


# ---------------------------------------------------------------------------
# 4. call sites — a helper-only fix proves nothing about the running drain
# ---------------------------------------------------------------------------


class TestWorkerCallSites:
    def _src(self):
        with open(_SERVICE_SRC, encoding="utf-8") as fh:
            return fh.read()

    def test_worker_uses_cold_load_candidates(self):
        assert "_cold_load_candidates(all_warm_by_model" in self._src()

    def test_worker_passes_priority_models_to_drain_order(self):
        src = self._src()
        assert "_drain_order(all_warm_by_model" in src, "drain-order call site must stay present (#6749 guard test)"
        assert "priority_models=_focus_models" in src

    def test_worker_shares_one_focus_probe_between_drain_and_load(self):
        src = self._src()
        assert "_focus_meta = _focused_family_model_meta()" in src
        assert "_cold_load_candidates(all_warm_by_model, _focus_meta)" in src
