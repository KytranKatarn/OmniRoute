"""#5626 — translation must survive a QUEUED dispatch, and drain on a drip.

The bug these pin: `batch_translate` called a helper that returned "" whenever the
dispatcher reported `queued=True`. Queued is ACCEPTANCE, not failure — the work runs
and `model_dispatch_worker` writes a result. Returning "" threw that result away, so
on a contended cluster every batch silently produced zero translations and the keys
stayed missing forever (KB #276153).

A test that only pins `success=True` cannot catch this — that path was always fine.
The regression case is specifically `success=False, queued=True`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class _Result:
    """Stand-in for DispatchResult."""

    def __init__(self, success=False, response="", queued=False, queue_id=None, error=None):
        self.success = success
        self.response = response
        self.queued = queued
        self.queue_id = queue_id
        self.error = error


def _cursor_cm(row=None, rows=None):
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *a):
            return False

    return _CM(), cur


# ---------------------------------------------------------------------------
# cluster_dispatch passthroughs
# ---------------------------------------------------------------------------


def test_queued_dispatch_text_forwards_job_id_and_prefer_agent():
    """Without these the translation path loses its bridge-job progress linkage."""
    from services.cluster_dispatch import queued_dispatch_text

    dispatcher = MagicMock()
    dispatcher.request_work.return_value = _Result(success=True, response=" done ")

    with patch("tools.department_hq.services.department_dispatcher.get_dispatcher", return_value=dispatcher):
        out = queued_dispatch_text(
            capability="translate",
            prompt="p",
            job_id=4242,
            prefer_agent="C.O.D.E.X.",
            model_override="gemma3:12b",
        )

    assert out == "done"
    kwargs = dispatcher.request_work.call_args.kwargs
    assert kwargs["job_id"] == 4242
    assert kwargs["prefer_agent"] == "C.O.D.E.X."
    assert kwargs["model_override"] == "gemma3:12b"


def test_queued_dispatch_text_defaults_keep_existing_callers_unchanged():
    """job_id/prefer_agent are additive — pre-existing callers must be unaffected."""
    from services.cluster_dispatch import queued_dispatch_text

    dispatcher = MagicMock()
    dispatcher.request_work.return_value = _Result(success=True, response="x")

    with patch("tools.department_hq.services.department_dispatcher.get_dispatcher", return_value=dispatcher):
        queued_dispatch_text(capability="classify", prompt="p")

    kwargs = dispatcher.request_work.call_args.kwargs
    assert kwargs["job_id"] is None
    assert kwargs["prefer_agent"] is None


# ---------------------------------------------------------------------------
# THE regression: a queued batch must still produce translations
# ---------------------------------------------------------------------------


def test_batch_translate_does_not_discard_a_queued_dispatch():
    """THE #5626 case. Old code returned "" here and lost every key."""
    import ai_bridge.translation_service as ts

    strings = [("nav.home", "Home", ""), ("nav.back", "Back", "")]
    payload = '[{"n": 1, "t": "בית"}, {"n": 2, "t": "חזור"}]'

    with (
        patch.object(ts, "_queued_dispatch_text", return_value=payload) as qd,
        patch.object(ts, "store_translations", return_value=None),
        patch.object(ts, "get_glossary", return_value=[]),
    ):
        results = ts.batch_translate(strings, "he")

    assert qd.called, "batch_translate must route through the queue-aware helper"
    assert [r["success"] for r in results] == [True, True]
    assert [r["translation"] for r in results] == ["בית", "חזור"]


def test_batch_translate_uses_queue_aware_helper_not_bare_dispatch():
    """Guard against a future refactor silently reinstating the drop-on-queue path."""
    import inspect

    import ai_bridge.translation_service as ts

    src = inspect.getsource(ts.batch_translate)
    assert "_queued_dispatch_text(" in src
    assert '_dispatch("translate"' not in src, "bare _dispatch drops queued work (KB #276153)"


# ---------------------------------------------------------------------------
# ar/he/de model pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["ar", "he", "de"])
def test_rtl_and_german_pin_to_gemma(lang):
    """mistral:7b garbles RTL scripts — these must be deterministic, not luck."""
    import ai_bridge.translation_service as ts

    assert ts._MODEL_BY_LANGUAGE.get(lang) == "gemma3:12b"


@pytest.mark.parametrize("lang", ["fr", "es", "pt", "zh"])
def test_other_languages_are_not_pinned(lang):
    """Everything else keeps normal capability routing (model_override=None)."""
    import ai_bridge.translation_service as ts

    assert ts._MODEL_BY_LANGUAGE.get(lang) is None


def test_batch_translate_passes_the_pin_for_hebrew():
    import ai_bridge.translation_service as ts

    with (
        patch.object(ts, "_queued_dispatch_text", return_value="[]") as qd,
        patch.object(ts, "store_translations", return_value=None),
        patch.object(ts, "get_glossary", return_value=[]),
    ):
        ts.batch_translate([("k", "Hello", "")], "he")

    assert qd.call_args.kwargs["model_override"] == "gemma3:12b"


def test_batch_translate_sends_no_pin_for_french():
    import ai_bridge.translation_service as ts

    with (
        patch.object(ts, "_queued_dispatch_text", return_value="[]") as qd,
        patch.object(ts, "store_translations", return_value=None),
        patch.object(ts, "get_glossary", return_value=[]),
    ):
        ts.batch_translate([("k", "Hello", "")], "fr")

    assert qd.call_args.kwargs["model_override"] is None


# ---------------------------------------------------------------------------
# drip producer gating
# ---------------------------------------------------------------------------


def test_drip_is_off_by_default():
    """Merging must never silently start spending GPU."""
    from tools.consciousness.jobs import translate_backlog_drip

    with patch("services.work_control_service.is_enabled", return_value=False) as gate:
        assert translate_backlog_drip() == {"skipped": "disabled"}

    # default=False is the load-bearing half — assert it explicitly
    assert gate.call_args.kwargs.get("default") is False


def test_drip_backs_off_when_dispatch_pipe_is_saturated():
    """Adding to a queue that is not draining is how #4536 happened."""
    from tools.consciousness.jobs import translate_backlog_drip

    with (
        patch("services.work_control_service.is_enabled", return_value=True),
        patch("services.welfare_governance_service.in_flight_over_cap", return_value=True) as cap,
        patch("ai_bridge.translation_service.batch_translate") as bt,
    ):
        assert translate_backlog_drip() == {"skipped": "in_flight_over_cap"}

    assert cap.call_args.args[0] == "batch_translate"
    bt.assert_not_called()


def _drip_cursor(*, picker=None, keys=25, persisted=25):
    """Serve the drip's three queries in order: rotate-pick → claim → verify-persisted.

    (Targets come from SUPPORTED_LANGUAGES, not a query — 'ai' has no rows and a
    table-derived list would exclude the one language most in need of filling.)
    """
    cur = MagicMock()
    key_rows = [{"key": f"k{i}", "english_text": "Home", "context": None} for i in range(keys)]
    cur.fetchall.side_effect = [key_rows]  # 2. claimed keys
    cur.fetchone.side_effect = [
        picker if picker is not None else {"language": "he", "missing": 475},  # 1. rotation pick
        {"n": persisted},  # 3. how many actually landed
    ]
    cm = MagicMock()
    cm.__enter__ = lambda _s: (MagicMock(), cur)
    cm.__exit__ = lambda *_a: False
    return cm, cur


def test_drip_claims_a_bounded_slice_and_translates_it():
    from tools.consciousness import jobs

    cm, cur = _drip_cursor()
    with (
        patch("services.work_control_service.is_enabled", return_value=True),
        patch("services.welfare_governance_service.in_flight_over_cap", return_value=False),
        patch("database.get_db_cursor", return_value=cm),
        patch(
            "ai_bridge.translation_service.batch_translate",
            return_value=[{"key": f"k{i}", "success": True} for i in range(25)],
        ) as bt,
    ):
        out = jobs.translate_backlog_drip()

    assert out["language"] == "he"
    assert out["claimed"] == 25
    assert out["translated"] == 25
    assert out["persisted"] == 25
    assert out["storage_failed"] is False
    assert out["remaining"] == 450
    assert bt.call_args.args[1] == "he"


def test_drip_rotates_instead_of_ranking_by_backlog_size():
    """'ai' (AI Semantic — a REAL target: machine-readable output for agents and
    scrapers) starts at ~6,900 missing vs he 475. Ranking by "furthest behind" would
    hand it every cycle for ~3 days while no human language gained a single key —
    measured on the first live cycle, 2026-08-15. Rotation serves whoever has waited
    longest, and NULLS FIRST means a never-started language begins rather than being
    deferred forever."""
    import inspect

    from tools.consciousness import jobs

    src = inspect.getsource(jobs.translate_backlog_drip)
    assert "last_progress ASC NULLS FIRST" in src, "must rotate by wait time"
    assert "ORDER BY missing DESC" not in src, "must NOT rank by backlog size — 'ai' would starve the rest"
    # 'ai' must remain a legitimate target
    assert "SUPPORTED_LANGUAGES" in src


def test_drip_reports_zero_when_nothing_actually_persisted():
    """THE storage-boundary case: the model returns text, store_translations fails
    (e.g. DB auth), batch_translate still logs '(stored)'. Trusting its count would
    report 25 translated against an unchanged table — #5626 all over again."""
    from tools.consciousness import jobs

    cm, _cur = _drip_cursor(persisted=0)
    with (
        patch("services.work_control_service.is_enabled", return_value=True),
        patch("services.welfare_governance_service.in_flight_over_cap", return_value=False),
        patch("database.get_db_cursor", return_value=cm),
        patch(
            "ai_bridge.translation_service.batch_translate",
            return_value=[{"key": f"k{i}", "success": True} for i in range(25)],
        ),
    ):
        out = jobs.translate_backlog_drip()

    assert out["translated"] == 25, "the model did return translations"
    assert out["persisted"] == 0
    assert out["storage_failed"] is True
    assert out["remaining"] == 475, "backlog must NOT shrink on unpersisted work"


def test_drip_reports_empty_backlog_without_dispatching():
    from tools.consciousness.jobs import translate_backlog_drip

    cm = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    cm.__enter__ = lambda _s: (MagicMock(), cur)
    cm.__exit__ = lambda *_a: False

    with (
        patch("services.work_control_service.is_enabled", return_value=True),
        patch("services.welfare_governance_service.in_flight_over_cap", return_value=False),
        patch("database.get_db_cursor", return_value=cm),
        patch("ai_bridge.translation_service.batch_translate") as bt,
    ):
        out = translate_backlog_drip()

    assert out["remaining"] == 0
    bt.assert_not_called()
