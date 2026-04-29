"""Tests for persist.py save_geo and mark_ai_analyzed."""
from unittest.mock import MagicMock, patch


def _make_engine(execute_return=None):
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value = execute_return
    return engine, conn


def test_save_geo_no_article_id():
    from ingest.persist import save_geo
    engine, conn = _make_engine()
    save_geo(engine, 0, "wtf", {"province_code": "ON"})
    conn.execute.assert_not_called()


def test_save_geo_no_geo():
    from ingest.persist import save_geo
    engine, conn = _make_engine()
    save_geo(engine, 1, "wtf", {})
    conn.execute.assert_not_called()


def test_save_geo_calls_update():
    from ingest.persist import save_geo
    engine, conn = _make_engine()
    save_geo(engine, 5, "wtf", {"province_code": "ON", "city": "Toronto", "lat": 43.65, "lng": -79.38, "geo_scope": "municipal"})
    conn.execute.assert_called_once()


def test_mark_ai_analyzed_calls_update():
    from ingest.persist import mark_ai_analyzed
    engine, conn = _make_engine()
    mark_ai_analyzed(engine, 5, "wtf")
    conn.execute.assert_called_once()
