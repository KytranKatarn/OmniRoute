"""Unit tests for Therapy service validation and annotations."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from tools.therapy.services import therapy_service as svc  # noqa: E402


@pytest.mark.parametrize(
    ("func", "args"),
    [
        (svc.log_mood, (0, 5)),
        (svc.get_mood_history, ("1",)),
        (svc.log_session, (None,)),
        (svc.get_session_history, (True,)),
        (svc.get_therapy_stats, (-1,)),
        (svc.schedule_session, (0, "Session", "2026-06-11T14:30:00")),
        (svc.get_ai_context, ("1",)),
    ],
)
def test_therapy_service_rejects_invalid_user_id_before_io(func, args):
    with patch.object(svc, "get_db_cursor") as get_db_cursor:
        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            func(*args)

    get_db_cursor.assert_not_called()


@pytest.mark.parametrize(
    ("func", "limit"),
    [
        (svc.get_mood_history, 0),
        (svc.get_mood_history, 101),
        (svc.get_mood_history, "30"),
        (svc.get_session_history, 0),
        (svc.get_session_history, 101),
        (svc.get_session_history, "20"),
    ],
)
def test_therapy_history_rejects_invalid_limit_before_io(func, limit):
    with patch.object(svc, "get_db_cursor") as get_db_cursor:
        with pytest.raises(ValueError, match="limit must be an integer between 1 and 100"):
            func(1, limit=limit)

    get_db_cursor.assert_not_called()


def test_therapy_service_functions_have_return_type_hints():
    assert svc.log_mood.__annotations__["user_id"] is int
    assert svc.log_mood.__annotations__["return"] is dict
    assert svc.get_mood_history.__annotations__["user_id"] is int
    assert svc.get_mood_history.__annotations__["limit"] is int
    assert svc.get_mood_history.__annotations__["return"] == list[dict]
    assert svc.log_session.__annotations__["user_id"] is int
    assert svc.log_session.__annotations__["return"] is dict
    assert svc.get_session_history.__annotations__["user_id"] is int
    assert svc.get_session_history.__annotations__["limit"] is int
    assert svc.get_session_history.__annotations__["return"] == list[dict]
    assert svc.get_therapy_stats.__annotations__["user_id"] is int
    assert svc.get_therapy_stats.__annotations__["return"] is dict
    assert svc.schedule_session.__annotations__["user_id"] is int
    assert svc.schedule_session.__annotations__["return"] is dict
