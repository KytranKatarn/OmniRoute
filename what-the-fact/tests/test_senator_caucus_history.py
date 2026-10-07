"""Senators' caucus by quarter, captured from the Senate expense summaries the sync already fetches.

The probe (2026-10-07) found each summary row names the senator's affiliation for THAT quarter: 40 quarters, 195 senators,
92 who changed. These tests run the REAL `_sync_senator_expenses` against fake Senate pages on sqlite.
"""
import os
import re
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, event, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import senator_expenses as se  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SQL = open(os.path.join(ROOT, "migrations", "098_senator_caucus.sql"), encoding="utf-8").read()


def test_short_names_cover_the_published_labels_and_unknowns_pass_through():
    assert se.caucus_short("Independent Senators Group") == "ISG"
    assert se.caucus_short("Conservative Party of Canada") == "Conservative"
    assert se.caucus_short("Canadian Senators Group") == "CSG"
    assert se.caucus_short("Progressive Senate Group") == "PSG"
    assert se.caucus_short("Non-affiliated") == "Non-affiliated"
    assert se.caucus_short("Some Future Group") == "Some Future Group"      # never dropped
    assert se.caucus_short(None) is None and se.caucus_short("") is None


def test_the_label_is_cleaned_of_markers_entities_and_spacing():
    assert se.caucus_label(["Gold, Marc", "Progressive  Senate Group *"]) == "Progressive Senate Group"
    assert se.caucus_label(["X, Y", "Qu&#xE9;bec Group"]) == "Québec Group"
    assert se.caucus_label(["X, Y"]) is None and se.caucus_label(["X, Y", "  "]) is None


def test_period_start_uses_calendar_quarters_unlike_the_house_labels():
    assert se.period_start("2018-Q1") == date(2018, 1, 1) and se.period_start("2018-Q4") == date(2018, 10, 1)
    assert se.period_start("2018-Q5") is None and se.period_start("") is None and se.period_start(None) is None


# ---- the real sync, on sqlite, against fake pages --------------------------------------------------------------------
@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    event.listen(eng, "connect", lambda c, _: c.create_function("now", 0, lambda: "now"))
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("""CREATE TABLE parliament.senators (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
            name TEXT, given_name TEXT, family_name TEXT, caucus TEXT, province TEXT, is_current BOOLEAN, synced_at TEXT DEFAULT 'x')"""))
        c.execute(text("""CREATE TABLE parliament.senator_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, senator_id INTEGER, period TEXT NOT NULL,
            travel_cad REAL, hospitality_cad REAL, contracts_cad REAL, office_cad REAL, living_cad REAL, total_cad REAL,
            source_url TEXT, synced_at TEXT, UNIQUE (senator_id, period))"""))
        c.execute(text("""CREATE TABLE parliament.senator_caucus_quarters (id INTEGER PRIMARY KEY AUTOINCREMENT, senator_id INTEGER NOT NULL,
            period TEXT NOT NULL, q_start TEXT NOT NULL, caucus TEXT NOT NULL, caucus_short TEXT, source_url TEXT, synced_at TEXT,
            UNIQUE (senator_id, period))"""))
        c.execute(text("INSERT INTO parliament.senators (slug, name, given_name, family_name, is_current) VALUES "
                       "('black-robert', 'Black, Robert', 'Robert', 'Black', 1), ('audette-michele', 'Audette, Michèle', 'Michèle', 'Audette', 1)"))
    return eng


def _row(name, caucus, total="1,000.00"):
    return [name, caucus, "Ontario", total, "0.00", "0.00", "0.00", "0.00"]


PAGES = {
    "p-2018Q1": [_row("Black, Robert", "Independent Senators Group"), _row("Audette, Mich&#xE8;le", "Independent Senators Group")],
    "p-2019Q3": [_row("Black, Robert", "Canadian Senators Group *"), _row("Audette, Mich&#xE8;le", "Progressive Senate Group")],
    "p-2019Q4": [_row("Black, Robert", "Canadian Senators Group")],
}


def _patch(monkeypatch):
    monkeypatch.setattr(se, "_fetch_fragment", lambda year=None, quarter=None: f"p-{year}Q{quarter}" if year else "p-2019Q4")
    monkeypatch.setattr(se, "_available_quarters", lambda frag: [(2019, 4), (2019, 3), (2018, 1)])
    monkeypatch.setattr(se, "_extract_rows", lambda frag: PAGES[frag])
    monkeypatch.setattr(se, "_SLEEP", 0)


def _caucus(eng, name):
    with eng.connect() as c:
        return c.execute(text("""SELECT q.period, q.caucus_short FROM parliament.senator_caucus_quarters q
            JOIN parliament.senators s ON s.id=q.senator_id WHERE s.name=:n ORDER BY q.q_start"""), {"n": name}).fetchall()


def test_the_sync_records_a_caucus_per_quarter_and_a_move_is_visible(engine, monkeypatch):
    _patch(monkeypatch)
    out = se._sync_senator_expenses(engine, max_quarters=10)
    assert out["caucus_rows"] == 5
    assert _caucus(engine, "Black, Robert") == [("2018-Q1", "ISG"), ("2019-Q3", "CSG"), ("2019-Q4", "CSG")]
    assert _caucus(engine, "Audette, Michèle") == [("2018-Q1", "ISG"), ("2019-Q3", "PSG")]   # entity-encoded name still matched


def test_the_sync_is_idempotent_for_caucus_rows(engine, monkeypatch):
    _patch(monkeypatch)
    se._sync_senator_expenses(engine, max_quarters=10)
    se._sync_senator_expenses(engine, max_quarters=10)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.senator_caucus_quarters")).scalar() == 5
        assert c.execute(text("SELECT count(*) FROM parliament.senator_expenses")).scalar() == 5


def test_a_changed_label_is_updated_not_duplicated(engine, monkeypatch):
    _patch(monkeypatch)
    se._sync_senator_expenses(engine, max_quarters=10)
    PAGES["p-2019Q4"][0][1] = "Non-affiliated"
    try:
        se._sync_senator_expenses(engine, max_quarters=10)
    finally:
        PAGES["p-2019Q4"][0][1] = "Canadian Senators Group"
    assert _caucus(engine, "Black, Robert")[-1] == ("2019-Q4", "Non-affiliated")


def test_a_row_without_an_affiliation_cell_records_no_caucus_but_keeps_the_expense(engine, monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setitem(PAGES, "p-2019Q4", [["Black, Robert", "", "Ontario", "10.00", "0", "0", "0", "0"]])
    se._sync_senator_expenses(engine, max_quarters=10)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.senator_caucus_quarters WHERE period='2019-Q4'")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM parliament.senator_expenses WHERE period='2019-Q4'")).scalar() == 1


# ---- the migration ---------------------------------------------------------------------------------------------------
def test_the_changes_view_finds_the_move_and_says_how_many_quarters_it_spans():
    view = re.search(r"CREATE OR REPLACE VIEW parliament\.v_senator_caucus_changes AS(.*?);\n", SQL, re.S).group(1)
    view = view.replace("extract(year FROM q_start)", "CAST(strftime('%Y', q_start) AS INTEGER)").replace(
        "extract(month FROM q_start)", "CAST(strftime('%m', q_start) AS INTEGER)").replace("::int", "")
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("CREATE TABLE parliament.senator_caucus_quarters (senator_id INT, period TEXT, q_start TEXT, caucus TEXT, caucus_short TEXT)"))
        c.execute(text("CREATE VIEW parliament.v_senator_caucus_changes AS" + view))
        for sid, period, qs, short in ((1, "2018-Q1", "2018-01-01", "ISG"), (1, "2019-Q3", "2019-07-01", "CSG"), (1, "2019-Q4", "2019-10-01", "CSG"),
                                       (2, "2018-Q1", "2018-01-01", "ISG"), (2, "2018-Q2", "2018-04-01", "ISG")):
            c.execute(text("INSERT INTO parliament.senator_caucus_quarters VALUES (:s,:p,:q,:short,:short)"), dict(s=sid, p=period, q=qs, short=short))
        rows = c.execute(text("SELECT senator_id, from_caucus, to_caucus, changed_in, quarters_between FROM parliament.v_senator_caucus_changes")).fetchall()
    assert rows == [(1, "ISG", "CSG", "2019-Q3", 6)]            # 2018-Q1 -> 2019-Q3 is 6 quarters apart: the move is somewhere in that window


def test_the_migration_states_its_rules():
    assert "Unattributed" in SQL and "c.period = e.period" in SQL        # nothing dropped; same calendar-quarter labels
    assert "2016-Q3" in SQL and "Wikidata" in SQL                        # the limit and why not Wikidata are on record
    assert "ON CONFLICT (version) DO NOTHING" in SQL and "UNIQUE (senator_id, period)" in SQL
