"""Federal election history on /elections + the tolerant GE45 ingest path.
Run without pytest: python3 tests/test_election_history.py"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

from shared.election_calendar import federal_history  # noqa: E402

TPL = ROOT / "consumer" / "templates"


def rows(ge, date, **parties):
    return [{"ge_number": ge, "election_date": date, "party": p, "seats": n} for p, n in parties.items()]


def test_lists_last_five_known_elections_newest_first_and_marks_gaps():
    db = rows(44, dt.date(2021, 9, 20), Liberal=160, Conservative=119) + \
         rows(43, dt.date(2019, 10, 21), Liberal=157, Conservative=121)
    h = federal_history(db)
    assert [e["ge"] for e in h] == [45, 44, 43, 42, 41]
    assert [e["status"] for e in h] == ["not_held", "held", "held", "not_held", "not_held"]
    assert h[1]["seats"] == 279 and h[1]["parties"][0] == ("Liberal", 160)


def test_nothing_is_invented_for_missing_elections():
    e = federal_history([])[0]
    assert e["parties"] == [] and e["seats"] == 0 and e["status"] == "not_held"


def test_new_ingest_appears_without_code_change():
    h = federal_history(rows(45, dt.date(2025, 4, 28), Liberal=1))
    assert h[0]["ge"] == 45 and h[0]["status"] == "held"


def test_parties_ordered_by_seats_then_name():
    h = federal_history(rows(44, None, B=5, A=5, C=9))
    assert next(e for e in h if e["ge"] == 44)["parties"] == [("C", 9), ("A", 5), ("B", 5)]


def _render(history):
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block meta %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL))]))
    return env.get_template("elections.html").render(
        rows=[], available=True, next_up=None, verified_count=0, total=0, history=history)


def test_page_renders_held_and_not_held_rows_and_provincial_disclosure():
    html = _render(federal_history(rows(44, dt.date(2021, 9, 20), Liberal=160)))
    assert "Liberal 160" in html and "Results not held" in html
    assert 'href="/races?ge=44"' in html and "has not been published yet" in html
    assert "45th general election" in html and "42nd general election" in html and "41st general election" in html


def test_page_degrades_when_history_unreadable():
    assert "history could not be read" in _render(None)


# ── ingest: optional elections never alarm ────────────────────────────────────
def _ingest(find_result, optional):
    if "sqlalchemy" not in sys.modules:
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:  # bare environment: the module only needs `text` at import time
            sys.modules["sqlalchemy"] = types.SimpleNamespace(text=lambda x: x)
    import ingest.elections.results as r
    logged = []
    r.find_table = lambda ge, label="table 12": find_result
    r._heartbeat = lambda engine, task, out, exc: logged.append((out, exc))
    out = r.run_election_results(None, 45, optional=optional)
    return out, logged


def test_unpublished_optional_election_is_skipped_not_an_error():
    out, logged = _ingest({"error": "no table 12 resource found for GE45"}, True)
    assert out.get("skipped") and "error" not in out and logged[0][1] is None


def test_unpublished_required_election_still_alarms():
    out, _ = _ingest({"error": "no table 12 resource found for GE45"}, False)
    assert out.get("error")


def test_non_fetchable_host_is_skipped_only_when_optional():
    e = {"error": "GE45 table 12 is hosted on elections.ca, which is not fetchable"}
    assert "skipped" in _ingest(e, True)[0] and "error" in _ingest(e, False)[0]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
