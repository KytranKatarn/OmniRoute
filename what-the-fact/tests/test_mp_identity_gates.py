"""A name or riding match is only accepted for a person who could have incurred the cost.

Real failures this pins: Candice Hoeppner's FY2009-12 expenses landed on Jake Hoeppner (in the seat 1997-2000) because the matcher
takes a LONE surname candidate whatever the given name; 2020-22 costs of the then-MP landed on namesakes first elected in 2023/2025
(Ben Carr, Gurbux Saini, Eric Lefebvre, Parm Bains); and 'Cummins, John' (retired 2011) became Kerry-Lynne Findlay through the
RIDING fallback, which took whoever held the riding without asking whether the surname agreed.
"""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from ingest.parliament import mp_expenses as mx
from ingest.parliament import mp_expenses_annual as an

FX = Path(__file__).resolve().parent / "fixtures" / "mp_annual"
T = {1: [(date(1997, 9, 22), date(2000, 10, 22))],                                       # Jake Hoeppner
     2: [(date(2008, 11, 18), date(2015, 10, 19))],                                      # Candice Hoeppner (not on the roster below)
     3: [(date(2023, 6, 19), None)],                                                     # Ben Carr
     4: [(date(2004, 10, 4), date(2008, 9, 7)), (date(2008, 11, 18), None)],
     5: [(date(2011, 5, 2), date(2015, 10, 19))],                                        # Kerry-Lynne Findlay
     6: []}                                                                              # no recorded terms at all


def test_seat_plausible_rejects_a_namesake_who_was_not_in_the_seat():
    fy10 = (date(2009, 4, 1), date(2010, 3, 31))
    assert not mx.seat_plausible(1, *fy10, T)                                           # Jake: left 2000, nine years before
    assert not mx.seat_plausible(3, date(2020, 4, 1), date(2020, 6, 30), T)             # Ben Carr: first seat 2023
    assert mx.seat_plausible(3, date(2023, 7, 1), date(2023, 9, 30), T) and mx.seat_plausible(4, *fy10, T)


def test_seat_plausible_allows_the_gap_between_election_and_opening_and_late_claims():
    # elected 2008-10-14, term recorded from 2008-11-18 (opening): a quarter that ENDS before it still counts
    assert mx.seat_plausible(4, date(2008, 7, 1), date(2008, 9, 30), {4: [(date(2008, 11, 18), None)]})
    # a first seat 200+ days after the period ended is not that gap
    assert not mx.seat_plausible(3, date(2022, 7, 1), date(2022, 9, 30), T)
    # a claim 2 years after leaving office is a late claim, 9 years is not
    assert mx.seat_plausible(5, date(2017, 10, 1), date(2017, 12, 31), T)
    assert not mx.seat_plausible(5, date(2024, 10, 1), date(2024, 12, 31), T)


def test_seat_plausible_fails_open_on_what_it_cannot_know():
    q = (date(2020, 4, 1), date(2020, 6, 30))
    assert mx.seat_plausible(6, *q, T) and mx.seat_plausible(99, *q, T)                  # no terms / unknown MP: unknowable, not wrong
    assert mx.seat_plausible(1, *q, None) and mx.seat_plausible(1, *q, {})              # no index: no gate


def test_riding_fallback_requires_the_surname_to_agree_or_be_unknown():
    fam_idx = {"cummins": [{"id": 10, "given": {"john"}}], "findlay": [{"id": 5, "given": {"kerry-lynne"}}]}
    fam_of = mx.family_of_index(fam_idx)
    assert fam_of == {10: "cummins", 5: "findlay"}
    assert not mx.riding_fallback_ok("Cummins,  John", 5, fam_idx, fam_of)              # the replacement MP is a DIFFERENT person
    assert mx.riding_fallback_ok("Findlay, Kerry-Lynne", 5, fam_idx, fam_of)            # same surname: fine
    assert mx.riding_fallback_ok("Thomas, Rachael", 5, fam_idx, fam_of)                 # unknown surname (married name): fine
    assert not mx.riding_fallback_ok("Findlay, Kerry-Lynne", None, fam_idx, fam_of)      # no holder: nothing to accept


def test_quarter_dates_are_the_fiscal_quarters():
    assert mx.quarter_dates(2025, 1) == (date(2024, 4, 1), date(2024, 6, 30))
    assert mx.quarter_dates(2025, 4) == (date(2025, 1, 1), date(2025, 3, 31))


# ---- the annual loader end to end ------------------------------------------------------------------------------------------

LIST_HTML = ('<table><tr><td><a class="ReportSelectionMemberLink" href="2011-2012/1">Abbott, Hon. Jim</a></td>'
             '<td>Kootenay-Columbia</td><td>British Columbia</td><td>Conservative</td></tr></table>')


@pytest.fixture
def engine():
    import sqlite3
    eng = create_engine("sqlite://", connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})        # DATE columns come back as dates, as in Postgres

    @event.listens_for(eng, "connect")
    def _fns(dbapi, _rec):
        dbapi.create_function("now", 0, lambda: "2026-10-08 00:00:00")
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("CREATE TABLE parliament.mps (id INTEGER, name TEXT, family_name TEXT, slug TEXT)"))
        c.execute(text("CREATE TABLE parliament.mp_terms (mp_id INTEGER, riding TEXT, start_date DATE, end_date DATE)"))
        c.execute(text("""CREATE TABLE parliament.mp_expenses_annual (id INTEGER PRIMARY KEY AUTOINCREMENT, mp_id INTEGER,
            fiscal_year INTEGER, period_start DATE, period_end DATE, name_as_published TEXT, status TEXT, constituency TEXT,
            caucus TEXT, salaries_cad REAL, travel_cad REAL, hospitality_cad REAL, contracts_cad REAL, total_cad REAL,
            detail TEXT, source_code TEXT, source_url TEXT, synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (mp_id, fiscal_year))"""))
        c.execute(text("INSERT INTO parliament.mps VALUES (7, 'Jim Abbott', 'Abbott', 'jim-abbott')"))
    return eng


def _run(eng):
    def get(url, timeout=60):
        return LIST_HTML.encode() if "expenditurebymember" in url else b"pdf"
    return an.run_annual_sync(eng, fy_from=2012, fy_to=2012, sleep=0, get=get,
                              pdf_text=lambda _b: (FX / "fy2012_abbott_part_year.txt").read_text(encoding="utf-8"))


def _term(eng, mp, riding, start, end):
    with eng.begin() as c:
        c.execute(text("INSERT INTO parliament.mp_terms VALUES (:m, :r, :s, :e)"), {"m": mp, "r": riding, "s": start, "e": end})


def test_a_lone_surname_match_to_someone_not_in_the_seat_is_rejected_and_left_unmatched(engine):
    _term(engine, 7, "Kootenay—Columbia", date(1993, 1, 1), date(2000, 10, 22))        # the namesake predecessor, long gone
    s = _run(engine)
    assert s["stored"] == 0 and sum(s["implausible"].values()) == 1 and "Abbott" in list(s["implausible"])[0]
    assert list(s["unmatched"]) and "Abbott" in list(s["unmatched"])[0]


def test_the_same_person_in_the_seat_is_stored(engine):
    _term(engine, 7, "Kootenay—Columbia", date(1993, 1, 1), date(2012, 1, 1))
    s = _run(engine)
    assert s["stored"] == 1 and not s["implausible"]


def test_the_riding_fallback_will_not_substitute_a_different_person(engine):
    """Name says Abbott (not in the seat), the riding's holder is Findlay: a different, unmatched person — never Findlay."""
    with engine.begin() as c:
        c.execute(text("INSERT INTO parliament.mps VALUES (9, 'Kerry-Lynne Findlay', 'Findlay', 'kerry-lynne-findlay')"))
    _term(engine, 7, "Kootenay—Columbia", date(1993, 1, 1), date(2000, 10, 22))
    _term(engine, 9, "Kootenay—Columbia", date(2011, 5, 2), date(2015, 10, 19))
    s = _run(engine)
    assert s["stored"] == 0 and s["matched_by_riding"] == 0 and s["implausible"]
