"""
Tests for the Family Tree duplicate detection and merge guardrails.

Mocks get_db_cursor so these tests do not need a live database.

Run with:
    docker exec archie_platform python3 -m pytest tools/family_tree/tests/test_dedup_service.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure platform_v2 is on sys.path so imports resolve inside Docker
# ---------------------------------------------------------------------------
PLATFORM_DIR = Path(__file__).resolve().parents[3]  # platform_v2/
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from tools.family_tree.services import dedup_service


class _MockCursorContext:
    def __init__(self, rows):
        self.conn = MagicMock()
        self.cur = MagicMock()
        self.cur.fetchall.return_value = rows

    def __enter__(self):
        return self.conn, self.cur

    def __exit__(self, exc_type, exc, tb):
        return False


def _person(
    person_id,
    first_name,
    last_name,
    birth_date=None,
    birth_place=None,
    death_date=None,
    death_place=None,
):
    return {
        "id": person_id,
        "first_name": first_name,
        "last_name": last_name,
        "birth_date": birth_date,
        "birth_place": birth_place,
        "death_date": death_date,
        "death_place": death_place,
    }


def test_similarity_empty_strings():
    assert dedup_service._similarity("", "") == 1.0
    assert dedup_service._similarity("", "Jane Doe") == 0.0


def test_similarity_identical_strings():
    assert dedup_service._similarity("Jane Doe", "Jane Doe") == 1.0
    assert dedup_service._similarity("Jane Doe", "jane doe") == 1.0


def test_similarity_can_exceed_duplicate_threshold():
    score = dedup_service._similarity("Jane Doe born 1900 at Boston", "Jane Doe born 1900 at Bostn")

    assert score > dedup_service.SIMILARITY_THRESHOLD


def test_person_text_handles_none_fields():
    person = {
        "first_name": None,
        "last_name": None,
        "birth_date": None,
        "birth_place": None,
        "death_date": None,
        "death_place": None,
    }

    assert dedup_service._person_text(person) == " "


@pytest.mark.parametrize("rows", [[], [_person(1, "Jane", "Doe")]])
def test_find_duplicates_returns_empty_for_zero_or_one_person(rows):
    cursor_context = _MockCursorContext(rows)

    with patch.object(dedup_service, "get_db_cursor", return_value=cursor_context) as get_db_cursor:
        assert dedup_service.find_duplicates(user_id=42) == []

    get_db_cursor.assert_called_once_with()
    cursor_context.cur.execute.assert_called_once()
    assert cursor_context.cur.execute.call_args.args[1] == {"user_id": 42}


def test_find_duplicates_compares_ten_plus_persons_and_sorts_matches():
    rows = [
        _person(1, "Jane", "Doe", "1900-01-01", "Boston"),
        _person(2, "Jane", "Doe", "1900-01-01", "Boston"),
        _person(3, "Janet", "Doe", "1900-01-01", "Boston"),
        _person(4, "Victor", "North", "1911-02-03", "Quebec"),
        _person(5, "Helena", "West", "1912-03-04", "Lisbon"),
        _person(6, "Marco", "Stone", "1913-04-05", "Madrid"),
        _person(7, "Priya", "Lake", "1914-05-06", "Delhi"),
        _person(8, "Nora", "Field", "1915-06-07", "Dublin"),
        _person(9, "Oscar", "Reed", "1916-07-08", "Oslo"),
        _person(10, "Talia", "Bright", "1917-08-09", "Cairo"),
        _person(11, "Kwame", "Hill", "1918-09-10", "Accra"),
        _person(12, "Mei", "Chen", "1919-10-11", "Taipei"),
    ]
    cursor_context = _MockCursorContext(rows)

    with patch.object(dedup_service, "get_db_cursor", return_value=cursor_context):
        candidates = dedup_service.find_duplicates(user_id=42)

    assert len(rows) > 10
    assert candidates
    assert candidates[0]["person_a"]["id"] == 1
    assert candidates[0]["person_b"]["id"] == 2
    assert candidates[0]["score"] == 1.0
    assert all(c["score"] >= dedup_service.SIMILARITY_THRESHOLD for c in candidates)
    assert candidates == sorted(candidates, key=lambda c: c["score"], reverse=True)


def test_merge_persons_rejects_same_keep_and_merge_id_before_db_access():
    with patch.object(dedup_service, "get_db_cursor") as get_db_cursor:
        with pytest.raises(ValueError, match="keep_id and merge_id must differ"):
            dedup_service.merge_persons(user_id=42, keep_id=7, merge_id=7)

    get_db_cursor.assert_not_called()
