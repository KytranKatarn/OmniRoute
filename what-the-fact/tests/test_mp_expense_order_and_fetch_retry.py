"""MP expense quarters list newest-first IN DATE ORDER, and the ourcommons.ca fetches survive a blip.

2026-10-06 audit of two failed drift-guard feeds found two separate things:

1. ``consumer/routes.py`` listed expenses with ``ORDER BY period DESC``. The label is
   "<calendar year>-Q<fiscal quarter>" and Q4 = Jan-Mar, so as text 2025-Q4 (Jan-Mar 2025) sorted ABOVE
   2025-Q3 (Oct-Dec 2025), and the LIMIT 12 cut at the wrong quarter.
2. mp_expenses and committees each made ONE request with no retry, so a short ourcommons.ca outage became
   a ``last run FAILED`` row and a page.
"""
import io
import os
import sqlite3
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import _retry, committees, mp_expenses  # noqa: E402
from shared import fiscal_quarters  # noqa: E402

# ---------------------------------------------------------------------------- period ordering

# Apr-Jun 2026 .. Jan-Mar 2024, in true chronological order, newest first.
CHRONOLOGICAL = [
    "2026-Q1",  # Apr-Jun 2026  (FY2027 Q1)
    "2026-Q4",  # Jan-Mar 2026  (FY2026 Q4)
    "2025-Q3",  # Oct-Dec 2025
    "2025-Q2",  # Jul-Sep 2025
    "2025-Q1",  # Apr-Jun 2025
    "2025-Q4",  # Jan-Mar 2025
    "2024-Q3",
    "2024-Q2",
    "2024-Q1",
    "2024-Q4",
]


def _ordered(periods, limit=None):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE mp_expenses (period TEXT)")
    db.executemany("INSERT INTO mp_expenses VALUES (?)", [(p,) for p in periods])
    sql = "SELECT period FROM mp_expenses ORDER BY " + fiscal_quarters.CHRONO_DESC_SQL
    if limit:
        sql += f" LIMIT {limit}"
    return [r[0] for r in db.execute(sql)]


def test_periods_come_back_in_date_order_whatever_the_insert_order():
    assert _ordered(sorted(CHRONOLOGICAL)) == CHRONOLOGICAL
    assert _ordered(list(reversed(CHRONOLOGICAL))) == CHRONOLOGICAL


def test_the_old_text_order_really_was_wrong():
    """Pins the defect: if this stops failing the fix is no longer exercising anything."""
    text_order = sorted(CHRONOLOGICAL, reverse=True)
    assert text_order != CHRONOLOGICAL
    assert text_order.index("2025-Q4") < text_order.index("2025-Q3")  # Jan-Mar 2025 above Oct-Dec 2025


def test_newest_row_is_the_latest_quarter_not_the_highest_label():
    assert _ordered(CHRONOLOGICAL)[0] == "2026-Q1"  # Apr-Jun 2026, not 2026-Q4 (Jan-Mar 2026)


def test_limit_keeps_the_newest_quarters():
    kept = _ordered(CHRONOLOGICAL, limit=5)
    assert kept == ["2026-Q1", "2026-Q4", "2025-Q3", "2025-Q2", "2025-Q1"]


def test_malformed_label_sorts_last_instead_of_raising():
    assert _ordered(["2026-Q1", "garbage", "2025-Q3"])[-1] == "garbage"


def test_the_mp_page_query_uses_the_shared_ordering():
    src = open(os.path.join(os.path.dirname(__file__), "..", "consumer", "routes.py"), encoding="utf-8").read()
    start = src.index("FROM parliament.mp_expenses\n                WHERE mp_id = :mp_id")
    window = src[start - 400:start + 400]
    assert "CHRONO_DESC_SQL" in window
    assert "ORDER BY period DESC" not in window


# ---------------------------------------------------------------------------- retry helper

@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(_retry.time, "sleep", lambda s: calls.append(s))
    return calls


def _http(code):
    return urllib.error.HTTPError("https://x", code, "msg", {}, io.BytesIO(b""))


def _flaky(*failures, result="ok"):
    state = {"n": 0}

    def fn():
        state["n"] += 1
        if state["n"] <= len(failures):
            raise failures[state["n"] - 1]
        return result

    return fn, state


def test_recovers_from_a_transient_403(sleeps):
    fn, st = _flaky(_http(403))
    assert _retry.fetch_with_retry(fn) == "ok"
    assert st["n"] == 2 and sleeps == [2.0]


@pytest.mark.parametrize("exc", [_http(503), urllib.error.URLError("reset"), TimeoutError("t"), ConnectionResetError("c")])
def test_other_transient_failures_are_retried(sleeps, exc):
    fn, st = _flaky(exc, exc)
    assert _retry.fetch_with_retry(fn) == "ok"
    assert st["n"] == 3 and sleeps == [2.0, 6.0]


def test_a_404_is_an_answer_and_is_not_retried(sleeps):
    fn, st = _flaky(_http(404))
    with pytest.raises(urllib.error.HTTPError) as ei:
        _retry.fetch_with_retry(fn)
    assert ei.value.code == 404 and st["n"] == 1 and sleeps == []


def test_a_non_network_error_is_not_retried(sleeps):
    fn, st = _flaky(ValueError("parse"))
    with pytest.raises(ValueError):
        _retry.fetch_with_retry(fn)
    assert st["n"] == 1 and sleeps == []


def test_gives_up_after_three_attempts_and_re_raises_the_original(sleeps):
    fn, st = _flaky(_http(403), _http(403), _http(403), _http(403))
    with pytest.raises(urllib.error.HTTPError) as ei:
        _retry.fetch_with_retry(fn)
    assert ei.value.code == 403 and st["n"] == 3 and sleeps == [2.0, 6.0]


# ---------------------------------------------------------------------------- wiring: the real fetchers

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_seq(monkeypatch, module, *outcomes):
    calls = {"n": 0}

    def fake(req, timeout=None):
        calls["n"] += 1
        out = outcomes[min(calls["n"], len(outcomes)) - 1]
        if isinstance(out, BaseException):
            raise out
        return _Resp(out)

    monkeypatch.setattr(module.urllib.request, "urlopen", fake)
    return calls


def test_committees_fetch_survives_one_403(monkeypatch, sleeps):
    calls = _urlopen_seq(monkeypatch, committees, _http(403), b"<html>list</html>")
    assert committees._fetch("https://www.ourcommons.ca/Committees/en/List") == "<html>list</html>"
    assert calls["n"] == 2


def test_committees_permanent_404_still_fails_fast(monkeypatch, sleeps):
    calls = _urlopen_seq(monkeypatch, committees, _http(404))
    with pytest.raises(urllib.error.HTTPError):
        committees._fetch("https://www.ourcommons.ca/Committees/en/AMAD")
    assert calls["n"] == 1 and sleeps == []


def test_mp_expenses_get_survives_a_timeout(monkeypatch, sleeps):
    calls = _urlopen_seq(monkeypatch, mp_expenses, TimeoutError("slow"), b"csv-bytes")
    assert mp_expenses._get("https://www.ourcommons.ca/ProactiveDisclosure/en/members/2026/1") == b"csv-bytes"
    assert calls["n"] == 2


def test_mp_expenses_get_gives_up_and_the_caller_sees_the_error(monkeypatch, sleeps):
    _urlopen_seq(monkeypatch, mp_expenses, _http(503))
    with pytest.raises(urllib.error.HTTPError) as ei:
        mp_expenses._get("https://www.ourcommons.ca/ProactiveDisclosure/en/members/2026/1")
    assert ei.value.code == 503
