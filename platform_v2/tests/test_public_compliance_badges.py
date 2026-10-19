"""Public compliance data must describe persisted scan evidence accurately."""

from contextlib import contextmanager
from datetime import datetime, timezone

import public_api


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return self.rows


def _install_rows(monkeypatch, rows):
    cursor = _Cursor(rows)

    @contextmanager
    def fake_db_cursor():
        yield None, cursor

    monkeypatch.setattr(public_api, "get_db_cursor", fake_db_cursor)
    return cursor


def test_public_badges_use_complete_persisted_scan_and_exclude_na_from_rate(monkeypatch):
    cursor = _install_rows(
        monkeypatch,
        [
            {
                "pack_id": "test-pack",
                "display_name": "Test Pack",
                "passing_rules": 8,
                "evaluated_rules": 10,
                "not_applicable_rules": 3,
                "manual_rules": 2,
                "scan_completed_at": datetime(2026, 10, 18, tzinfo=timezone.utc),
                "previous_scan_completed_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
            }
        ],
    )

    result = public_api._fetch_compliance_badges()

    assert "persisted.result_count = cs.total_rules" in cursor.query
    assert "cs.completed_at IS NOT NULL" in cursor.query
    assert "sr.status IN ('pass', 'fail', 'error')" in cursor.query
    assert "previous.pack_ids = latest.pack_ids" in cursor.query
    assert result["available"] is True
    assert result["badges"][0]["score"] == 80.0
    assert result["badges"][0]["evaluated_rules"] == 10
    assert result["badges"][0]["not_applicable_rules"] == 3
    assert result["framework_count"] == 1
    assert result["evaluated_rules"] == 10
    assert result["previous_scan"] == "2026-10-17T00:00:00+00:00"


def test_public_badges_report_unavailable_when_no_complete_scan(monkeypatch):
    cursor = _install_rows(monkeypatch, [])

    result = public_api._fetch_compliance_badges()

    assert "persisted.result_count = cs.total_rules" in cursor.query
    assert result == {
        "badges": [],
        "available": False,
        "framework_count": 0,
        "evaluated_rules": 0,
        "last_scan": None,
        "previous_scan": None,
    }
