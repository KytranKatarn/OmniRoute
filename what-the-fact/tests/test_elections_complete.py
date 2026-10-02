"""Elections completion: seats-vs-votes, curated history, municipal seeds, who-governs
gating, and the verification tool. Run: python3 tests/test_elections_complete.py"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

from shared.city_identity import CANONICAL_CITIES  # noqa: E402
from shared.election_calendar import (  # noqa: E402
    ValidationError, calendar_view, classify, curated_history, problems, seats_vs_votes,
    validate_calendar_update, validate_history_row)

TODAY = dt.date(2026, 10, 1)


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValidationError:
        return True
    return False


# ── seats vs votes ─────────────────────────────────────────────────────────────
def test_seats_vs_votes_arithmetic():
    sv = seats_vs_votes([{"party": "A", "seats": 60, "votes": 400}, {"party": "B", "seats": 40, "votes": 400},
                         {"party": "C", "seats": 0, "votes": 200}])
    a, b, c = sv["parties"]
    assert (a["seat_pct"], a["vote_pct"], a["gap"]) == (60.0, 40.0, 20.0)
    assert b["gap"] == 0.0 and c["gap"] == -20.0
    assert sv["total_seats"] == 100 and sv["total_votes"] == 1000


def test_tiny_seatless_parties_fold_into_other_and_are_reported_not_dropped():
    sv = seats_vs_votes([{"party": "A", "seats": 10, "votes": 996}, {"party": "Z", "seats": 0, "votes": 4}])
    assert [p["party"] for p in sv["parties"]] == ["A"] and sv["other_vote_pct"] == 0.4
    kept = seats_vs_votes([{"party": "A", "seats": 10, "votes": 800}, {"party": "Z", "seats": 0, "votes": 200}])
    assert [p["party"] for p in kept["parties"]] == ["A", "Z"]  # a big seatless party stays visible


def test_no_votes_means_no_table_not_a_division_by_zero():
    assert seats_vs_votes([]) == {} and seats_vs_votes([{"party": "A", "seats": 3, "votes": 0}]) == {}


# ── curated history ────────────────────────────────────────────────────────────
def test_curated_history_is_grouped_newest_first_and_capped():
    rows = [{"jurisdiction_code": "QC", "election_date": dt.date(2000 + y, 10, 1), "results": [
        {"party": "B", "seats": 3}, {"party": "A", "seats": 9}], "source_url": "https://x.y/z"} for y in range(1, 9)]
    h = curated_history(rows, last_n=5)["QC"]
    assert len(h) == 5 and h[0]["date"].year == 2008 and h[0]["results"][0]["party"] == "A"


# ── who governs is gated by verification ──────────────────────────────────────
def _row(**k):
    base = {"jurisdiction_code": "QC", "jurisdiction": "Québec", "level": "provincial", "last_election": dt.date(2022, 10, 3),
            "next_latest_date": dt.date(2026, 10, 5), "rule": "r", "source_url": None, "verified_at": dt.datetime(2026, 9, 1),
            "government_party": "CAQ", "head_of_government": "X"}
    base.update(k)
    return base


def test_office_holder_withheld_until_verified():
    assert classify(_row(verified_at=None), TODAY)["head_of_government"] is None
    assert classify(_row(), TODAY)["government_party"] == "CAQ"


def test_unverified_alert_is_compressed_for_many_rows():
    rows = [_row(jurisdiction_code="MUN-%02d" % i, verified_at=None) for i in range(30)]
    msg = [m for m in problems(rows, TODAY) if "unverified" in m][0]
    assert "30 row(s)" in msg and "+22 more" in msg and len(msg) < 200


# ── migration seeds ────────────────────────────────────────────────────────────
def test_municipal_seeds_are_exactly_the_cities_the_site_tracks_and_carry_no_dates():
    sql = (ROOT / "migrations" / "086_elections_complete.sql").read_text(encoding="utf-8")
    assert set(re.findall(r"'MUN-([a-z-]+)'", sql)) == set(CANONICAL_CITIES)
    seed = sql[sql.index("INSERT INTO parliament.election_calendar"):]
    assert not re.search(r"\d{4}-\d{2}-\d{2}", seed.split("ON CONFLICT")[0])
    assert re.search(r"source_url\s+text NOT NULL CHECK \(source_url <> ''\)", sql)  # no source, no row


# ── validators + the CLI ───────────────────────────────────────────────────────
def test_calendar_update_validation():
    ok = dict(last_election="2022-10-03", next_latest_date="2026-10-05", rule="s.129", source_url="https://a.b/c", today=TODAY)
    assert validate_calendar_update(**ok)["next_latest_date"] == dt.date(2026, 10, 5)
    for bad in (dict(source_url="http://a.b/c"), dict(source_url=""), dict(rule=" "),
                dict(next_latest_date="2022-01-01"), dict(next_latest_date="2026-09-30"),
                dict(last_election="2030-01-01"), dict(next_latest_date="2040-10-01")):
        assert raises(validate_calendar_update, **{**ok, **bad}), bad


def test_history_validation_requires_source_and_consistent_seats():
    ok = dict(election_date="2022-10-03", results=[{"party": "A", "seats": 90}, {"party": "B", "seats": 21}],
              source_url="https://a.b/c", seats_total=111, turnout_pct=66.1, today=TODAY)
    assert validate_history_row(**ok)["seats_total"] == 111
    for bad in (dict(source_url=""), dict(seats_total=110), dict(results=[]), dict(turnout_pct=0),
                dict(election_date="2030-01-01"), dict(results=[{"party": "", "seats": 1}])):
        assert raises(validate_history_row, **{**ok, **bad}), bad


def _cli():
    spec = importlib.util.spec_from_file_location("ea", ROOT / "scripts" / "elections_admin.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_cli_dry_run_by_default_and_refuses_without_a_source():
    cli = _cli()
    t = dt.date.today()
    base = ["verify", "QC", "--last", f"{t.year - 3}-10-03", "--next", f"{t.year + 1}-10-05", "--rule", "r"]
    assert cli.main(base + ["--source", "http://insecure"]) == 2            # refused
    assert cli.main(base + ["--source", "https://ok.example/qc"]) == 0      # dry run: no DB touched
    assert cli.main(["add-history", "QC", "--date", "2022-10-03", "--results", "not json", "--source", "https://x.y/z"]) == 2


# ── the page ───────────────────────────────────────────────────────────────────
def _render(**kw):
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block meta %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(str(ROOT / "consumer" / "templates"))]))
    rows = calendar_view([_row(), _row(jurisdiction_code="MUN-toronto", jurisdiction="Toronto", level="municipal",
                                       province_code="ON", verified_at=None)], TODAY)
    ctx = dict(rows=rows, available=True, next_up=None, verified_count=1, total=2, history=[],
               seats_votes=None, curated_history=None, names={})
    ctx.update(kw)
    return env.get_template("elections.html").render(**ctx)


def test_page_has_municipal_table_and_hides_unverified_office_holders():
    h = _render()
    assert 'id="municipal"' in h and "Toronto" in h and "Date being verified" in h
    assert "X &middot; CAQ" in h  # verified QC row shows who governs
    assert "have not been added yet" not in h


def test_page_renders_seats_vs_votes_and_curated_history():
    sv = seats_vs_votes([{"party": "Liberal", "seats": 160, "votes": 5000}, {"party": "NDP", "seats": 25, "votes": 3000}])
    sv.update(ge=44, date=dt.date(2021, 9, 20))
    ch = curated_history([{"jurisdiction_code": "QC", "election_date": dt.date(2022, 10, 3), "turnout_pct": 66.1,
                           "results": [{"party": "CAQ", "seats": 90}], "source_url": "https://a.b/c"}])
    h = _render(seats_votes=sv, curated_history=ch, names={"QC": "Québec"})
    assert "Federal result" in h and "44th general election" in h and "pts" in h
    assert "CAQ 90" in h and "Québec" in h and "Each row links to the article" in h


def test_page_discloses_missing_provincial_history_instead_of_hiding_it():
    assert "has not been published yet" in _render()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
