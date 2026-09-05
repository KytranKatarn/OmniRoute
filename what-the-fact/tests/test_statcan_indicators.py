"""Guard: StatCan indicator ingest (CPI/unemployment/GDP/housing-starts, #6272
Batch 12) never fabricates a value and always reports its heartbeat honestly.

Mirrors test_boc_rates_heartbeat.py's pattern: a FAKE engine, no database, no
fixtures, no network. WDS-shaped payloads are synthesized inline from the real
shape observed live 2026-09-04 (POST getDataFromVectorsAndLatestNPeriods).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.market import statcan_indicators as sc  # noqa: E402


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
                if "parliament.ingest_log" in s and p.get("t") == "statcan_indicators"]

    def upserts(self):
        return [(s, p) for s, p in self.statements
                if "market_watch.economic_indicators" in s and "INSERT INTO" in s]


# --- real-shaped WDS payloads (observed live 2026-09-04) -------------------

def _wds_point(ref_per, value, release_time="2026-08-17T08:30"):
    return {
        "refPer": ref_per,
        "refPer2": "",
        "value": value,
        "decimals": 1,
        "releaseTime": release_time,
    }


def _wds_success(vector_id, points):
    return {
        "status": "SUCCESS",
        "object": {"responseStatusCode": 0, "productId": 0, "vectorId": vector_id,
                    "vectorDataPoint": points},
    }


def _wds_failed(vector_id):
    return {
        "status": "FAILED",
        "object": {"responseStatusCode": 3, "productId": 0, "vectorId": vector_id,
                    "vectorDataPoint": []},
    }


_FULL_PAYLOAD = [
    _wds_success(41690973, [_wds_point("2026-06-01", 169.0), _wds_point("2026-07-01", 169.9)]),
    _wds_success(2062815, [_wds_point("2026-07-01", 6.4), _wds_point("2026-08-01", 6.4)]),
    _wds_success(65201210, [_wds_point("2026-05-01", 2363056.0), _wds_point("2026-06-01", 2369309.0)]),
    _wds_success(52300157, [_wds_point("2026-06-01", 240.773), _wds_point("2026-07-01", 229.074)]),
]


# --- pure transform: _build_rows never fabricates ---------------------------

class TestBuildRows:
    def test_parses_all_four_indicators_from_a_healthy_response(self):
        rows, errors = sc._build_rows(_FULL_PAYLOAD)
        assert errors == []
        keys = {r["indicator_key"] for r in rows}
        assert keys == {"cpi_index", "unemployment_rate", "gdp_level", "housing_starts_saar"}
        assert len(rows) == 8

    def test_stores_raw_values_not_percentages(self):
        rows, _ = sc._build_rows(_FULL_PAYLOAD)
        cpi = [r for r in rows if r["indicator_key"] == "cpi_index" and r["ref_date"].isoformat() == "2026-07-01"][0]
        assert cpi["value"] == 169.9
        gdp = [r for r in rows if r["indicator_key"] == "gdp_level" and r["ref_date"].isoformat() == "2026-06-01"][0]
        assert gdp["value"] == 2369309.0

    def test_a_failed_vector_is_skipped_not_fabricated(self):
        payload = [
            _wds_success(41690973, [_wds_point("2026-07-01", 169.9)]),
            _wds_failed(2062815),
        ]
        rows, errors = sc._build_rows(payload)
        keys = {r["indicator_key"] for r in rows}
        assert keys == {"cpi_index"}
        assert any("unemployment_rate" in e for e in errors)

    def test_a_vector_with_no_data_points_is_skipped_not_fabricated(self):
        payload = [_wds_success(41690973, [])]
        rows, errors = sc._build_rows(payload)
        assert rows == []
        assert any("cpi_index" in e and "no data points" in e for e in errors)

    def test_an_unparseable_point_is_skipped_within_an_otherwise_good_vector(self):
        payload = [_wds_success(41690973, [
            {"refPer": "2026-07-01", "value": None, "releaseTime": "2026-08-17T08:30"},
            _wds_point("2026-08-01", 170.1),
        ])]
        rows, errors = sc._build_rows(payload)
        assert len(rows) == 1
        assert rows[0]["ref_date"].isoformat() == "2026-08-01"
        assert errors == []

    def test_an_unrecognized_vector_id_is_recorded_not_silently_dropped(self):
        payload = [_wds_success(999999999, [_wds_point("2026-07-01", 1.0)])]
        rows, errors = sc._build_rows(payload)
        assert rows == []
        assert any("999999999" in e for e in errors)

    def test_empty_payload_yields_empty_rows_and_no_errors(self):
        rows, errors = sc._build_rows([])
        assert rows == []
        assert errors == []

    def test_table_id_and_vector_id_are_stamped_onto_every_row(self):
        rows, _ = sc._build_rows(_FULL_PAYLOAD)
        cpi = next(r for r in rows if r["indicator_key"] == "cpi_index")
        assert cpi["vector_id"] == 41690973
        assert cpi["table_id"] == "18-10-0004-01"


class TestReleaseTime:
    def test_naive_release_time_is_interpreted_as_eastern(self):
        dt = sc._parse_release_time("2026-08-17T08:30")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset() is not None

    def test_missing_release_time_is_none_not_fabricated(self):
        assert sc._parse_release_time(None) is None
        assert sc._parse_release_time("") is None

    def test_garbage_release_time_is_none_not_raised(self):
        assert sc._parse_release_time("not-a-timestamp") is None


# --- run_statcan_indicators(): never-raise + heartbeat contract ------------

class TestRunStatcanIndicatorsHeartbeat:
    def test_success_writes_a_success_heartbeat(self, monkeypatch):
        monkeypatch.setattr(sc, "_fetch_indicators", lambda: _FULL_PAYLOAD)
        engine = _FakeEngine()
        result = sc.run_statcan_indicators(engine)
        assert "error" not in result
        assert result["upserted"] >= 1
        assert set(result["latest"].keys()) == {
            "cpi_index", "unemployment_rate", "gdp_level", "housing_starts_saar"
        }
        hb = engine.heartbeats()
        assert len(hb) == 1
        stmt, params = hb[0]
        assert "records_fetched" in stmt
        assert "e" not in params

    def test_a_crashing_fetch_never_raises_and_writes_an_error_heartbeat(self, monkeypatch):
        def _boom():
            raise ConnectionError("WDS API unreachable")
        monkeypatch.setattr(sc, "_fetch_indicators", _boom)
        engine = _FakeEngine()
        result = sc.run_statcan_indicators(engine)  # must not raise
        assert "WDS API unreachable" in result.get("error", "")
        hb = engine.heartbeats()
        assert len(hb) == 1
        stmt, params = hb[0]
        assert "error" in stmt
        assert "WDS API unreachable" in params["e"]

    def test_all_vectors_failing_writes_an_error_heartbeat_not_a_silent_success(self, monkeypatch):
        monkeypatch.setattr(sc, "_fetch_indicators",
                             lambda: [_wds_failed(v["vector_id"]) for v in sc._INDICATORS])
        engine = _FakeEngine()
        result = sc.run_statcan_indicators(engine)
        assert result.get("error")
        hb = engine.heartbeats()
        assert len(hb) == 1
        assert "error" in hb[0][0]

    def test_a_partial_failure_still_upserts_the_good_indicators_and_reports_success(self, monkeypatch):
        """One dead vector must not discard the three healthy ones — the
        heartbeat stays a SUCCESS (real rows landed) with the miss surfaced
        via partial_errors, not swallowed and not escalated to a hard error."""
        payload = [
            _wds_success(41690973, [_wds_point("2026-07-01", 169.9)]),
            _wds_failed(2062815),
            _wds_success(65201210, [_wds_point("2026-06-01", 2369309.0)]),
            _wds_success(52300157, [_wds_point("2026-07-01", 229.074)]),
        ]
        monkeypatch.setattr(sc, "_fetch_indicators", lambda: payload)
        engine = _FakeEngine()
        result = sc.run_statcan_indicators(engine)
        assert "error" not in result
        assert "unemployment_rate" not in result["latest"]
        assert "partial_errors" in result
        hb = engine.heartbeats()
        assert len(hb) == 1
        assert "records_fetched" in hb[0][0]

    def test_upsert_uses_the_composite_conflict_key(self, monkeypatch):
        monkeypatch.setattr(sc, "_fetch_indicators", lambda: _FULL_PAYLOAD)
        engine = _FakeEngine()
        sc.run_statcan_indicators(engine)
        upserts = engine.upserts()
        assert len(upserts) == 8
        stmt, _ = upserts[0]
        assert "ON CONFLICT (indicator_key, ref_date)" in stmt


class TestScopeDiscipline:
    """This module must not reach into shared scheduling/guard files — the
    coordinator wires those after both Batch 12 ingest PRs land. Checked by
    absence of an actual coupling (import/call), not by string-matching the
    module's own docstring, which explains that boundary in prose."""

    def test_does_not_import_drift_guard(self):
        src = (ROOT / "ingest" / "market" / "statcan_indicators.py").read_text(encoding="utf-8")
        assert "import drift_guard" not in src
        assert "from ingest.parliament" not in src

    def test_run_py_is_untouched_by_this_change(self):
        """statcan_indicators.py must not itself call into run.py's scheduling
        — wiring the weekly/daily cadence is the coordinator's job."""
        src = (ROOT / "ingest" / "market" / "statcan_indicators.py").read_text(encoding="utf-8")
        assert "ingest.run" not in src

    def test_has_a_cli_entry_point(self):
        src = (ROOT / "ingest" / "market" / "statcan_indicators.py").read_text(encoding="utf-8")
        assert "__main__" in src
        assert "def ingest()" in src
