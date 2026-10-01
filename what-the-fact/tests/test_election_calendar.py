"""Election calendar: pure logic + a Jinja render (no DB, no pytest needed to run:
`python3 tests/test_election_calendar.py`)."""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

from shared.election_calendar import calendar_view, classify, problems  # noqa: E402

TODAY = dt.date(2026, 10, 1)
TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"


def row(code="QC", verified=dt.datetime(2026, 9, 1), nxt=dt.date(2026, 10, 5), level="provincial"):
    return {"jurisdiction_code": code, "jurisdiction": code + " name", "level": level,
            "last_election": dt.date(2022, 10, 3), "next_latest_date": nxt, "rule": "r",
            "source_url": None, "verified_at": verified}


def test_unverified_row_withholds_every_date():
    c = classify(row(verified=None), TODAY)
    assert c["status"] == "unverified"
    assert c["next_latest_date"] is None and c["last_election"] is None and c["days_until"] is None


def test_verified_upcoming_computes_days_at_read_time():
    assert classify(row(), TODAY)["days_until"] == 4


def test_passed_date_is_overdue_not_negative_days():
    c = classify(row(nxt=dt.date(2026, 9, 30)), TODAY)
    assert c["status"] == "overdue" and c["days_until"] is None


def test_election_day_itself_is_still_upcoming_zero():
    assert classify(row(nxt=TODAY), TODAY)["days_until"] == 0


def test_stale_verification_flagged_and_alarmed():
    r = row(verified=dt.datetime(2026, 1, 1))
    assert classify(r, TODAY)["stale"] is True
    assert any("re-verify" in m for m in problems([r], TODAY))


def test_problems_empty_only_when_everything_verified_fresh_and_ahead():
    assert problems([row()], TODAY) == []
    assert problems([], TODAY)  # empty table is a problem
    assert any("unverified" in m for m in problems([row(verified=None)], TODAY))
    assert any("PASSED" in m for m in problems([row(nxt=dt.date(2026, 9, 1))], TODAY))


def test_sorted_soonest_first_unshown_last():
    v = calendar_view([row("AA", nxt=dt.date(2028, 1, 1)), row("BB", verified=None),
                       row("CC", nxt=dt.date(2026, 10, 5))], TODAY)
    assert [r["code"] for r in v] == ["CC", "AA", "BB"]


def _render(rows, available=True):
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block meta %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL))]))
    v = calendar_view(rows, TODAY)
    up = [r for r in v if r["status"] == "upcoming"]
    return env.get_template("elections.html").render(
        rows=v, available=available, next_up=up[0] if up else None,
        verified_count=sum(1 for r in v if r["status"] != "unverified"), total=len(v))


def test_page_never_prints_an_unverified_date():
    html = _render([row("QC", verified=None, nxt=dt.date(2026, 10, 5))])
    assert "2026-10-05" not in html and "Date being verified" in html


def test_page_shows_verified_date_and_municipal_placeholder():
    html = _render([row("QC")])
    assert "2026-10-05" in html and ">4<" in html
    assert 'id="municipal"' in html and 'id="federal"' in html and 'id="provincial"' in html


def test_page_degrades_when_table_unreadable():
    assert "could not be read" in _render([], available=False)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
