"""Tests for run_geo_report."""
from unittest.mock import MagicMock, patch, call
import json


def _make_engine(rows=None):
    engine = MagicMock()
    conn_ctx = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows or []
    conn_ctx.__enter__ = MagicMock(return_value=conn)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn_ctx

    begin_ctx = MagicMock()
    begin_conn = MagicMock()
    begin_ctx.__enter__ = MagicMock(return_value=begin_conn)
    begin_ctx.__exit__ = MagicMock(return_value=False)
    engine.begin.return_value = begin_ctx
    return engine, conn, begin_conn


def test_geo_report_empty_db():
    """Empty DB produces a report with all provinces as news deserts."""
    from ingest.run import run_geo_report
    engine, conn, begin_conn = _make_engine(rows=[])
    run_geo_report(engine)
    begin_conn.execute.assert_called_once()
    # All 13 provinces should be news deserts when no articles
    args = begin_conn.execute.call_args
    params = args[0][1]  # second positional arg is the params dict
    deserts = json.loads(params["nd"])
    assert len(deserts) == 13


def test_geo_report_province_coverage():
    """Province coverage is counted correctly from rows."""
    from ingest.run import run_geo_report

    MockRow = MagicMock()
    MockRow.province_code = "ON"
    MockRow.outlet = "cbc_english"
    MockRow.cnt = 10

    engine, conn, begin_conn = _make_engine(rows=[MockRow])
    run_geo_report(engine)
    args = begin_conn.execute.call_args
    params = args[0][1]
    coverage = json.loads(params["pc"])
    assert coverage.get("ON") == 10
