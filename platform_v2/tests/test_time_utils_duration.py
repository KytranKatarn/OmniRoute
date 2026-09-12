"""Tests for services.time_utils.format_duration — compact millisecond rendering."""

import pytest

from services import time_utils as tu


def test_milliseconds_fractional_below_one_second():
    assert tu.format_duration(0) == "0ms"
    assert tu.format_duration(500) == "500ms"
    assert tu.format_duration(999) == "999ms"


def test_one_decimal_second_below_a_minute():
    assert tu.format_duration(1000) == "1.0s"
    assert tu.format_duration(1500) == "1.5s"
    assert tu.format_duration(59999) == "1m"


def test_minutes_with_remaining_seconds():
    assert tu.format_duration(60000) == "1m"
    assert tu.format_duration(65000) == "1m 5s"
    assert tu.format_duration(125000) == "2m 5s"


def test_whole_minutes_omit_seconds():
    assert tu.format_duration(120000) == "2m"
    assert tu.format_duration(3600000) == "60m"


def test_negative_input_raises_value_error():
    with pytest.raises(ValueError):
        tu.format_duration(-1)
    with pytest.raises(ValueError):
        tu.format_duration(-1000)
