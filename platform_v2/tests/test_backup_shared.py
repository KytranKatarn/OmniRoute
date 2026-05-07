"""Tests for _shared.py helpers — specifically _safe_serialize_val."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import datetime


def test_safe_serialize_val_normal_datetime():
    from tools.backup_manager._shared import _safe_serialize_val

    dt = datetime.datetime(2024, 5, 7, 12, 0, 0)
    result = _safe_serialize_val(dt)
    assert result == "'2024-05-07T12:00:00'"


def test_safe_serialize_val_none():
    from tools.backup_manager._shared import _safe_serialize_val

    assert _safe_serialize_val(None) == "NULL"


def test_safe_serialize_val_bool():
    from tools.backup_manager._shared import _safe_serialize_val

    assert _safe_serialize_val(True) == "TRUE"
    assert _safe_serialize_val(False) == "FALSE"


def test_safe_serialize_val_int():
    from tools.backup_manager._shared import _safe_serialize_val

    assert _safe_serialize_val(42) == "42"


def test_safe_serialize_val_string_with_quotes():
    from tools.backup_manager._shared import _safe_serialize_val

    result = _safe_serialize_val("it's a test")
    assert result == "'it''s a test'"


def test_safe_serialize_val_overflow_returns_null():
    """_safe_serialize_val must return NULL (not crash) when isoformat raises."""
    from tools.backup_manager._shared import _safe_serialize_val
    import datetime as _dt

    class BadDatetime(_dt.datetime):
        def isoformat(self, *args, **kwargs):
            raise ValueError("year 58317 is out of range")

    bad = BadDatetime(2024, 1, 1)
    result = _safe_serialize_val(bad)
    assert result.startswith("NULL"), f"Expected NULL, got: {result!r}"


def test_backup_database_python_row_serialization_no_crash():
    """Verify _safe_serialize_val (used by backup_database_python) handles out-of-range datetimes."""
    import datetime as _dt
    from tools.backup_manager._shared import _safe_serialize_val

    class BadDatetime(_dt.datetime):
        def isoformat(self, *args, **kwargs):
            raise ValueError("year 58317 is out of range")

    # Confirm _safe_serialize_val (used in backup_database_python) handles this
    bad = BadDatetime(2024, 1, 1)
    result = _safe_serialize_val(bad)
    assert result.startswith("NULL"), f"Expected NULL for bad datetime, got: {result!r}"

    # Also confirm normal datetimes still serialize correctly
    good = _dt.datetime(2026, 5, 7, 12, 0, 0)
    good_result = _safe_serialize_val(good)
    assert good_result == "'2026-05-07T12:00:00'", f"Normal datetime broken: {good_result!r}"

    print("PASS: out-of-range datetime -> NULL, normal datetime -> ISO string")
