from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tools.email_manager.human_sla_service import (
    compute_response_seconds,
    within_sla_pct,
    fmt_duration,
)


def _dt(h=0, m=0, s=0):
    return datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc) + timedelta(hours=h, minutes=m, seconds=s)


def test_compute_response_seconds_basic():
    received = _dt()
    assert compute_response_seconds(received, received + timedelta(minutes=5)) == 300
    assert compute_response_seconds(received, received + timedelta(hours=2)) == 7200


def test_compute_response_seconds_none_and_negative():
    received = _dt()
    assert compute_response_seconds(None, received) is None
    assert compute_response_seconds(received, None) is None
    # reply before source (clock skew) -> None, not a negative number
    assert compute_response_seconds(received, received - timedelta(minutes=1)) is None


def test_within_sla_pct():
    # target 3600s (1h): 3 of 4 within
    assert within_sla_pct([60, 1800, 3600, 7200], 3600) == 75.0
    assert within_sla_pct([100, 200], 3600) == 100.0
    assert within_sla_pct([], 3600) is None
    assert within_sla_pct([None, None], 3600) is None  # no timed replies
    assert within_sla_pct([None, 60], 3600) == 100.0  # ignores None


def test_fmt_duration():
    assert fmt_duration(None) == "—"
    assert fmt_duration(45) == "45s"
    assert fmt_duration(125) == "2m"
    assert fmt_duration(3600) == "1h"
    assert fmt_duration(9000) == "2h 30m"
