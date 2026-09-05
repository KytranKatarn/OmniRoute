"""CAD/USD exchange rate ingest — pure-transform + never-raise/heartbeat
contract tests (Batch 12).

Mirrors tests/test_boc_rates_heartbeat.py's FAKE engine pattern: no
database, no fixtures, no live network call. This module deliberately
does NOT touch ingest/run.py or ingest/parliament/drift_guard.py (a
parallel StatCan-indicators agent owns those shared files this batch),
so there are no drift-guard-registration or scheduling-wiring tests
here — those land in the coordinator's follow-up pass, same as
boc_rates.py's own history (manual script -> heartbeat -> scheduled).
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.market import fx_rates  # noqa: E402


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
                if "parliament.ingest_log" in s and p.get("t") == "fx_rates"]


# --- pure transform: raw Valet observations -> upsert rows -----------------

_SAMPLE_OBS = [
    {"d": "2026-09-03", "FXUSDCAD": {"v": "1.3789"}},
    {"d": "2026-09-04", "FXUSDCAD": {"v": "1.3840"}},
    # weekend/holiday gap — series key present but empty: must be skipped
    {"d": "2026-09-05", "FXUSDCAD": {}},
    # series key missing entirely: must also be skipped
    {"d": "2026-09-06"},
]


class TestBuildRows:
    def test_skips_rows_with_no_value(self):
        rows = fx_rates._build_rows(_SAMPLE_OBS)
        dates = [r["rate_date"].isoformat() for r in rows]
        assert dates == ["2026-09-03", "2026-09-04"]

    def test_never_fabricates_a_rate_for_a_gap(self):
        """A missing/null observation must be dropped, never interpolated
        or defaulted — a fabricated FX rate is worse than a missing one."""
        rows = fx_rates._build_rows(_SAMPLE_OBS)
        assert len(rows) == 2
        assert all(r["usd_cad"] > 0 for r in rows)

    def test_parses_real_sample_values(self):
        """Live-verified sample: 2026-09-04 = 1.3840, 2026-09-03 = 1.3789."""
        rows = fx_rates._build_rows(_SAMPLE_OBS)
        by_date = {r["rate_date"].isoformat(): r["usd_cad"] for r in rows}
        assert by_date["2026-09-04"] == 1.3840
        assert by_date["2026-09-03"] == 1.3789

    def test_rows_are_sorted_ascending_by_date(self):
        shuffled = [_SAMPLE_OBS[1], _SAMPLE_OBS[0]]
        rows = fx_rates._build_rows(shuffled)
        dates = [r["rate_date"] for r in rows]
        assert dates == sorted(dates)

    def test_empty_observations_yields_empty_rows(self):
        assert fx_rates._build_rows([]) == []


# --- run_fx_rates(): never-raise + heartbeat contract -----------------------

class TestRunFxRatesHeartbeat:
    def test_success_writes_a_success_heartbeat(self, monkeypatch):
        monkeypatch.setattr(fx_rates, "_fetch_observations", lambda: _SAMPLE_OBS)
        engine = _FakeEngine()
        result = fx_rates.run_fx_rates(engine)
        assert "error" not in result
        assert result["upserted"] >= 1
        assert result["current_rate"] == 1.3840
        assert result["current_as_of"] == "2026-09-04"
        hb = engine.heartbeats()
        assert len(hb) == 1
        stmt, params = hb[0]
        assert "records_fetched" in stmt
        assert "e" not in params  # success path has no error param

    def test_a_crashing_fetch_never_raises_and_writes_an_error_heartbeat(self, monkeypatch):
        """The CLI wrapper (ingest()) reads result['error']/result['upserted']
        directly, so a raised exception must populate result['error'] too —
        not just the heartbeat — or a manual run crashes with a bare
        KeyError instead of a clean 'ERROR: ...' message."""
        def _boom():
            raise ConnectionError("Valet API unreachable")
        monkeypatch.setattr(fx_rates, "_fetch_observations", _boom)
        engine = _FakeEngine()
        result = fx_rates.run_fx_rates(engine)  # must not raise
        assert "Valet API unreachable" in result.get("error", "")
        hb = engine.heartbeats()
        assert len(hb) == 1
        stmt, params = hb[0]
        assert "error" in stmt
        assert "Valet API unreachable" in params["e"]

    def test_empty_observations_writes_an_error_heartbeat_not_a_silent_success(self, monkeypatch):
        """An empty parse result must not be logged as a quiet success —
        that shape is exactly how boc_rates.py went unmonitored for months
        (no heartbeat at all looked identical to 'nothing changed')."""
        monkeypatch.setattr(fx_rates, "_fetch_observations", lambda: [])
        engine = _FakeEngine()
        result = fx_rates.run_fx_rates(engine)
        assert result.get("error")
        hb = engine.heartbeats()
        assert len(hb) == 1
        assert "error" in hb[0][0]

    def test_all_gaps_writes_an_error_heartbeat(self, monkeypatch):
        """Every observation being a gap (all null/missing) must also read
        as a failure, not silently succeed with zero rows."""
        monkeypatch.setattr(
            fx_rates, "_fetch_observations",
            lambda: [{"d": "2026-09-05", "FXUSDCAD": {}}],
        )
        engine = _FakeEngine()
        result = fx_rates.run_fx_rates(engine)
        assert result.get("error")


# --- schema shape sanity (upsert SQL text, no live DB) ----------------------

class TestUpsertSchema:
    def test_upsert_creates_the_documented_table_and_conflict_key(self):
        engine = _FakeEngine()
        fx_rates._upsert(engine, [{"rate_date": __import__("datetime").date(2026, 9, 4),
                                    "usd_cad": 1.3840}])
        sql_blob = " ".join(s for s, _ in engine.statements)
        assert "market_watch.fx_rates" in sql_blob
        assert "rate_date" in sql_blob and "usd_cad" in sql_blob
        assert "ON CONFLICT (rate_date)" in sql_blob
