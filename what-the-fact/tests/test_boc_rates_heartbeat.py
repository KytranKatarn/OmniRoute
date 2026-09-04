"""Guard: BoC overnight rate ingest must be OBSERVABLE and SCHEDULED (#6272,
Batch 9 economy scoping).

The old script (python -m ingest.market.boc_rates) was a one-off manual
backfill on 2026-05-18 with no scheduled follow-up and NO parliament.
ingest_log heartbeat at all — the same "unmonitored while appearing
monitored" shape as the weekly_digest bug (#6233) this file's fixtures are
borrowed from. It went ~5 months stale (last row 2026-04-01) before this
session's /economy design-handoff scoping pass caught it by reading the
table directly, not by any dashboard signal.

These tests use a FAKE engine on purpose (same pattern as
test_weekly_digest_heartbeat.py): no database, no fixtures, no network.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.market import boc_rates  # noqa: E402
from ingest.parliament import drift_guard  # noqa: E402


class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    def execute(self, stmt, params=None):
        self._sink.append((str(stmt), dict(params or {})))

        class _Result:
            rowcount = 1
        return _Result()


class _FakeEngine:
    """Captures every statement executed through engine.begin()."""

    def __init__(self):
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        sink = self.statements

        class _Ctx:
            def __enter__(self_inner):
                return _FakeConn(sink)

            def __exit__(self_inner, *a):
                return False
        return _Ctx()

    def heartbeats(self):
        return [(s, p) for s, p in self.statements
                if "parliament.ingest_log" in s and p.get("t") == "boc_rates"]


# --- pure transform: raw Valet observations -> upsert rows -----------------

_SAMPLE_OBS = [
    {"d": "2026-01-01", "V122514": {"v": "2.500"}},
    {"d": "2026-02-01", "V122514": {"v": "2.250"}},
    # a row with no value at all — must be skipped, not crash
    {"d": "2026-02-15", "V122514": {}},
    # a row missing the series key entirely
    {"d": "2026-03-01"},
]


class TestBuildRows:
    def test_skips_rows_with_no_value(self):
        rows = boc_rates._build_rows(_SAMPLE_OBS)
        dates = [r["decision_date"].isoformat() for r in rows]
        assert dates == ["2026-01-01", "2026-02-01"]

    def test_computes_basis_point_changes(self):
        rows = boc_rates._build_rows(_SAMPLE_OBS)
        assert rows[0]["change_bps"] is None  # first row has no prior rate
        assert rows[1]["change_bps"] == -25  # 2.25 - 2.50 = -0.25 -> -25bps

    def test_empty_observations_yields_empty_rows(self):
        assert boc_rates._build_rows([]) == []


# --- run_boc_rates(): never-raise + heartbeat contract ----------------------

class TestRunBocRatesHeartbeat:
    def test_success_writes_a_success_heartbeat(self, monkeypatch):
        monkeypatch.setattr(boc_rates, "_fetch_observations", lambda: _SAMPLE_OBS)
        engine = _FakeEngine()
        result = boc_rates.run_boc_rates(engine)
        assert "error" not in result
        assert result["upserted"] >= 1
        hb = engine.heartbeats()
        assert len(hb) == 1
        stmt, params = hb[0]
        assert "records_fetched" in stmt
        assert "e" not in params  # success path has no error param

    def test_a_crashing_fetch_never_raises_and_writes_an_error_heartbeat(self, monkeypatch):
        """The CLI wrapper (ingest()) reads result['error']/result['upserted']
        directly, so a raised exception must populate result['error'] too —
        not just the heartbeat — or a manual run crashes with a bare KeyError
        instead of a clean 'ERROR: ...' message."""
        def _boom():
            raise ConnectionError("Valet API unreachable")
        monkeypatch.setattr(boc_rates, "_fetch_observations", _boom)
        engine = _FakeEngine()
        result = boc_rates.run_boc_rates(engine)  # must not raise
        assert "Valet API unreachable" in result.get("error", "")
        hb = engine.heartbeats()
        assert len(hb) == 1
        stmt, params = hb[0]
        assert "error" in stmt
        assert "Valet API unreachable" in params["e"]

    def test_empty_observations_writes_an_error_heartbeat_not_a_silent_success(self, monkeypatch):
        """An empty parse result must not be logged as a quiet success — that
        is exactly the shape that let this task go unmonitored the first
        time (no heartbeat AT ALL looked identical to 'nothing changed')."""
        monkeypatch.setattr(boc_rates, "_fetch_observations", lambda: [])
        engine = _FakeEngine()
        result = boc_rates.run_boc_rates(engine)
        assert result.get("error")
        hb = engine.heartbeats()
        assert len(hb) == 1
        assert "error" in hb[0][0]


# --- drift_guard registration: mirrors test_the_new_elections_task_is_wired_end_to_end ---

class TestDriftGuardRegistration:
    def test_boc_rates_is_watched_and_required(self):
        assert "boc_rates" in drift_guard._MAX_AGE_DAYS
        assert "boc_rates" in drift_guard._REQUIRED_TASKS

    def test_boc_rates_has_a_heartbeat_writer(self):
        src = (ROOT / "ingest" / "market" / "boc_rates.py").read_text(encoding="utf-8")
        assert "parliament.ingest_log" in src
        assert '"boc_rates"' in src

    def test_boc_rates_is_actually_scheduled(self):
        """Registered but never called is exactly the trap this whole file
        exists to catch — assert the scheduler module calls it, not just
        that the ingest function exists."""
        run_py = (ROOT / "ingest" / "run.py").read_text(encoding="utf-8")
        assert "run_boc_rates" in run_py

    def test_boc_rates_uses_the_same_weekly_cadence_key_as_elections(self):
        """It shares _last_elections_week's %G-W%V key rather than inventing
        its own — both fire once per ISO week, same as the source's ~8/year
        decision cadence warrants."""
        run_py = (ROOT / "ingest" / "run.py").read_text(encoding="utf-8")
        start = run_py.index("if _last_boc_week != ")
        end = run_py.index("_last_boc_week = ", start)
        block = run_py[start:end]
        assert "_elec_week" in block
