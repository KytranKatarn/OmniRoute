"""Unit tests for DOC service DB helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


def _mock_cursor(row=None, rows=None):
    """Return a context-manager mock for get_db_cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    cm = _CM()
    cm.cursor = cur
    return cm


def test_log_symptoms_persists_symptoms_as_json_array():
    from tools.doc.services import doc_service as svc

    logged_at = datetime(2026, 6, 11, 14, 30, 0)
    cm = _mock_cursor(row=(42, logged_at))

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.log_symptoms(
            user_id=7,
            symptoms="fatigue",
            severity=4,
            notes="After lunch",
        )

    assert result == {"id": 42, "logged_at": "2026-06-11T14:30:00"}
    sql, params = cm.cursor.execute.call_args.args
    assert "INSERT INTO health_symptom_logs" in sql
    assert params[0] == 7
    assert params[1].adapted == ["fatigue"]
    assert params[2:] == (4, "After lunch")


def test_get_symptom_history_applies_limit_and_shapes_rows():
    from tools.doc.services import doc_service as svc

    logged_at = datetime(2026, 6, 11, 14, 30, 0)
    cm = _mock_cursor(rows=[(42, ["fatigue"], 4, "After lunch", logged_at)])

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.get_symptom_history(user_id=7, limit=3)

    assert result == [
        {
            "id": 42,
            "symptoms": ["fatigue"],
            "severity": 4,
            "notes": "After lunch",
            "logged_at": "2026-06-11T14:30:00",
        }
    ]
    sql, params = cm.cursor.execute.call_args.args
    assert "LIMIT %s" in sql
    assert params == (7, 3)


def test_add_medication_requires_name_argument():
    from tools.doc.services import doc_service as svc

    with pytest.raises(TypeError):
        svc.add_medication(user_id=7)


def test_add_medication_inserts_medication_and_returns_created_timestamp():
    from tools.doc.services import doc_service as svc

    cm = _mock_cursor(row=(99, datetime(2026, 6, 11, 15, 0, 0)))

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.add_medication(
            user_id=7,
            name="Loratadine",
            dosage="10 mg",
            frequency="Daily",
            start_date="2026-06-11",
        )

    assert result == {"id": 99, "created_at": "2026-06-11T15:00:00"}
    sql, params = cm.cursor.execute.call_args.args
    assert "INSERT INTO health_medications" in sql
    assert params == (7, "Loratadine", "10 mg", "Daily", "2026-06-11")


def test_update_medication_updates_only_whitelisted_fields():
    from tools.doc.services import doc_service as svc

    cm = _mock_cursor()
    cm.cursor.rowcount = 1

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.update_medication(
            med_id=99,
            user_id=7,
            updates={
                "name": "Ignored",
                "dosage": "20 mg",
                "frequency": "Nightly",
                "active": False,
                "created_at": "ignored",
            },
        )

    assert result == {"updated": True}
    sql, params = cm.cursor.execute.call_args.args
    assert "dosage = %s" in sql
    assert "frequency = %s" in sql
    assert "active = %s" in sql
    assert "name = %s" not in sql
    assert "created_at = %s" not in sql
    assert params == ["20 mg", "Nightly", False, 99, 7]


def test_get_health_stats_uses_30_day_window():
    from tools.doc.services import doc_service as svc

    fixed_now = datetime(2026, 6, 11, 12, 0, 0)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    cm = _mock_cursor()
    cm.cursor.fetchone.side_effect = [
        (2,),
        (4,),
        (fixed_now - timedelta(days=5),),
    ]

    with patch.object(svc, "get_db_cursor", return_value=cm), patch.object(
        svc,
        "datetime",
        FixedDatetime,
    ):
        result = svc.get_health_stats(user_id=7)

    assert result == {
        "active_medications": 2,
        "symptom_logs_30d": 4,
        "days_since_last_log": 5,
    }
    execute_calls = cm.cursor.execute.call_args_list
    assert len(execute_calls) == 3
    count_30d_sql, count_30d_params = execute_calls[1].args
    assert "logged_at >= %s" in count_30d_sql
    assert count_30d_params == (7, fixed_now - timedelta(days=30))


def test_get_medications_filters_active_by_default_and_can_include_all():
    from tools.doc.services import doc_service as svc

    cm_active = _mock_cursor(rows=[])
    with patch.object(svc, "get_db_cursor", return_value=cm_active):
        assert svc.get_medications(user_id=7) == []

    active_sql, active_params = cm_active.cursor.execute.call_args.args
    assert "active = TRUE" in active_sql
    assert active_params == (7,)

    cm_all = _mock_cursor(rows=[])
    with patch.object(svc, "get_db_cursor", return_value=cm_all):
        assert svc.get_medications(user_id=7, active_only=False) == []

    all_sql, all_params = cm_all.cursor.execute.call_args.args
    assert "active = TRUE" not in all_sql
    assert all_params == (7,)


def test_update_medication_rejects_non_whitelisted_only_updates():
    from tools.doc.services import doc_service as svc

    cm = _mock_cursor()

    with patch.object(svc, "get_db_cursor", return_value=cm):
        result = svc.update_medication(
            med_id=99,
            user_id=7,
            updates={"name": "Ignored"},
        )

    assert result == {"updated": False, "error": "No valid fields to update"}
    cm.cursor.execute.assert_not_called()
