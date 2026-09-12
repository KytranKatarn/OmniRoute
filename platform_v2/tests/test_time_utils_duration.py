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


def test_format_duration_rejects_non_integer():
    with pytest.raises((TypeError, ValueError)):
        tu.format_duration("abc")


def test_parse_duration_accepts_emitted_forms():
    assert tu.parse_duration("500ms") == 500
    assert tu.parse_duration("1.5s") == 1500
    assert tu.parse_duration("2m") == 120000
    assert tu.parse_duration("1m 5s") == 65000


def test_parse_duration_milliseconds_edge_cases():
    assert tu.parse_duration("0ms") == 0
    assert tu.parse_duration("999ms") == 999


def test_parse_duration_decimal_seconds():
    assert tu.parse_duration("1.0s") == 1000
    assert tu.parse_duration("59.9s") == 59900


def test_parse_duration_minutes_with_and_without_seconds():
    assert tu.parse_duration("1m") == 60000
    assert tu.parse_duration("2m 5s") == 125000
    assert tu.parse_duration("60m") == 3600000


def test_parse_duration_is_inverse_of_format_duration():
    for ms in range(0, 3_600_000):
        rendered = tu.format_duration(ms)
        assert tu.format_duration(tu.parse_duration(rendered)) == rendered


def test_parse_duration_rejects_unparseable_input():
    with pytest.raises(ValueError):
        tu.parse_duration("")
    with pytest.raises(ValueError):
        tu.parse_duration("   ")
    with pytest.raises(ValueError):
        tu.parse_duration("5")
    with pytest.raises(ValueError):
        tu.parse_duration("foo")
    with pytest.raises(ValueError):
        tu.parse_duration("1h")
    with pytest.raises(ValueError):
        tu.parse_duration("-500ms")
    with pytest.raises(ValueError):
        tu.parse_duration("2m 5x")
