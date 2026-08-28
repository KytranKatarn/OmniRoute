"""Unit tests for services.signal_calendar_live_service (Phase 1)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest


def _mock_cursor(rows=None):
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.fetchone.return_value = None
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    cm = _CM()
    cm.cursor = cur
    return cm


@pytest.fixture
def svc():
    from services import signal_calendar_live_service

    return signal_calendar_live_service


class TestWeekBoundaries:
    def test_compute_week_returns_monday_through_sunday(self, svc):
        # 2026-05-04 is a Monday
        wk_start, wk_end = svc.compute_week(date(2026, 5, 4))
        assert wk_start == date(2026, 5, 4)
        assert wk_end == date(2026, 5, 10)

    def test_compute_week_for_thursday_walks_back_to_monday(self, svc):
        wk_start, wk_end = svc.compute_week(date(2026, 5, 7))  # Thursday
        assert wk_start == date(2026, 5, 4)
        assert wk_end == date(2026, 5, 10)

    def test_compute_week_for_sunday_walks_back_to_monday(self, svc):
        wk_start, wk_end = svc.compute_week(date(2026, 5, 10))  # Sunday
        assert wk_start == date(2026, 5, 4)
        assert wk_end == date(2026, 5, 10)


class TestLanguageDetection:
    def test_detects_french_from_action_data_language(self, svc):
        ad = {"language": "fr", "content": "..."}
        assert svc.detect_lang(action_data=ad, reason="") == "fr"

    def test_detects_english_from_action_data(self, svc):
        ad = {"language": "en", "content": "..."}
        assert svc.detect_lang(action_data=ad, reason="") == "en"

    def test_detects_french_from_quebec_marker_in_reason(self, svc):
        reason = "📣 ⚜️ Français québécois: bonjour"
        assert svc.detect_lang(action_data={}, reason=reason) == "fr"

    def test_detects_french_from_francais_word(self, svc):
        reason = "Some Français content"
        assert svc.detect_lang(action_data={}, reason=reason) == "fr"

    def test_defaults_to_english_when_unclear(self, svc):
        assert svc.detect_lang(action_data={}, reason="some draft") == "en"

    def test_handles_none_action_data(self, svc):
        assert svc.detect_lang(action_data=None, reason="some draft") == "en"


class TestGetWeekView:
    def test_empty_week_returns_seven_days(self, svc):
        with patch("services.signal_calendar_live_service.get_db_cursor", return_value=_mock_cursor(rows=[])):
            out = svc.get_week_view(account="company", week_start=date(2026, 5, 4))
        assert out["account"] == "company"
        assert out["week_start"] == "2026-05-04"
        assert len(out["days"]) == 7
        assert all(d["posts"] == [] for d in out["days"])
        # Every day has the right shape
        assert out["days"][0]["date"] == "2026-05-04"
        assert out["days"][6]["date"] == "2026-05-10"

    def test_groups_posts_by_date_and_classifies(self, svc):
        rows = [
            {
                "id": 1111,
                "status": "executed",
                "post_type": "company",
                "action_data": {"language": "en", "content": "test", "post_type": "company"},
                "execution_result": {"success": True},
                "reason": "🇨🇦 English: ...",
                "created_at": datetime(2026, 5, 4, 13, 0),
                "approved_at": datetime(2026, 5, 4, 13, 12),
                "executed_at": datetime(2026, 5, 4, 16, 4),
                "telegram_message_id": 2583,
                "post_log_status": "posted",
                "linkedin_url": "https://www.linkedin.com/feed/update/x",
            },
            {
                "id": 1112,
                "status": "executed",
                "post_type": "company",
                "action_data": {"language": "fr", "content": "test fr", "post_type": "company"},
                "execution_result": {"success": False, "_status": "timeout"},
                "reason": "⚜️ Français québécois: ...",
                "created_at": datetime(2026, 5, 4, 14, 1),
                "approved_at": None,
                "executed_at": datetime(2026, 5, 4, 14, 3),
                "telegram_message_id": 2586,
                "post_log_status": None,
                "linkedin_url": None,
            },
        ]
        with patch("services.signal_calendar_live_service.get_db_cursor", return_value=_mock_cursor(rows=rows)):
            out = svc.get_week_view(account="company", week_start=date(2026, 5, 4))

        # Day 0 should have 2 posts; the rest 0
        assert len(out["days"][0]["posts"]) == 2
        assert sum(len(d["posts"]) for d in out["days"]) == 2

        post_en = next(p for p in out["days"][0]["posts"] if p["lang"] == "en")
        post_fr = next(p for p in out["days"][0]["posts"] if p["lang"] == "fr")
        assert post_en["status"] == "posted"
        assert post_en["approval_id"] == 1111
        assert post_en["telegram_message_id"] == 2583
        assert post_fr["status"] == "failed"
        assert post_fr["approval_id"] == 1112

    def test_today_flag_set_correctly(self, svc):
        from datetime import date as _date

        # Mock today to be 2026-05-06 (Wednesday in the test week)
        with patch("services.signal_calendar_live_service.date") as mock_date:
            mock_date.today.return_value = _date(2026, 5, 6)
            mock_date.side_effect = lambda *a, **kw: _date(*a, **kw)
            with patch("services.signal_calendar_live_service.get_db_cursor", return_value=_mock_cursor(rows=[])):
                out = svc.get_week_view(account="company", week_start=_date(2026, 5, 4))
        assert out["today"] == "2026-05-06"
        # Day 2 (Wed) should be today; rest not
        assert out["days"][2]["is_today"] is True
        assert sum(1 for d in out["days"] if d["is_today"]) == 1


class TestRowToPost:
    def test_row_to_post_includes_full_content(self):
        """Phase 3: response must carry full content for modal display."""
        from services.signal_calendar_live_service import _row_to_post

        long_text = "X" * 500  # well over the 200-char preview cap
        row = {
            "id": 99,
            "status": "executed",
            "action_data": {"post_type": "company", "language": "en", "content": long_text},
            "execution_result": {"success": True},
            "reason": "[TEST]",
            "created_at": datetime(2026, 5, 4, 13, 0),
            "approved_at": None,
            "executed_at": None,
            "telegram_message_id": None,
            "post_type": "company",
            "post_log_status": None,
            "post_url": None,
        }
        post = _row_to_post(row)
        assert post["content"] == long_text
        assert len(post["preview"]) <= 203  # preview still truncated (200 + "...")
