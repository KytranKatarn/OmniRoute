"""Senators' quarterly expenditure reports Sept 2010 - June 2016: the PDF row reader, the name matcher, the loader, the migration.

Fixtures are the frozen TEXT RUNS (y, x, text) of real one-page PDFs, one per layout that occurs (the PDFs themselves are not committed; pypdf is not
needed to run these tests): 2010 (all five amounts in a single text run), 2012 (the staff/office
header is garbled so only two headers are legible), 2013 (a NEGATIVE living figure — a repayment), 2015 and 2016 (current layout).
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from ingest.parliament import senate_legacy as sl

FX = Path(__file__).resolve().parent / "fixtures" / "senate_legacy"
MIG = Path(__file__).resolve().parent.parent / "migrations" / "102_senator_expenses_legacy.sql"


import json

_FRAGS = json.loads((FX / "fragments.json").read_text(encoding="utf-8"))      # the text runs of the real PDFs, frozen (pypdf-free)


def _row(name: str):
    return sl.parse_fragments([tuple(f) for f in _FRAGS[name]])


def test_2015_layout_maps_each_amount_to_its_column():
    r = _row("2015-05-31_DoyleN")
    assert r["name"] == "DOYLE, HON. NORMAN E." and r["layout_ok"]
    # read off the page: Staff&Office 28,453.81 | Hospitality 13.69 | Living 4,762.97 | Travel 2a 17,606.75 | Travel 2b 0.00
    assert (r["office"], r["hospitality"], r["living"], r["travel_regular"], r["travel_other"]) == (28453.81, 13.69, 4762.97, 17606.75, 0.0)
    assert r["total"] == round(28453.81 + 13.69 + 4762.97 + 17606.75, 2)


def test_a_negative_figure_is_kept_as_a_repayment_not_dropped():
    r = _row("2013-05-31_DuffyM")
    assert r["living"] == -17126.12 and r["office"] == 35396.98 and r["layout_ok"]
    assert r["total"] == round(35396.98 + 187.43 - 17126.12 + 3808.54 + 759.40, 2)


def test_2010_layout_with_all_five_amounts_in_one_text_run():
    r = _row("2010-11-30_DuffyM")
    assert r is not None and r["name"] == "HON. MICHAEL DUFFY"
    assert [r[c] for c in sl.COLUMNS] == [32581.97, 769.37, 3793.45, 17587.11, 1073.37]


def test_2012_layout_with_a_garbled_header_still_reads_in_order():
    r = _row("2012-05-31_AndreA")
    assert [r[c] for c in sl.COLUMNS] == [33023.65, 156.72, 3660.91, 13922.22, 0.0] and r["layout_ok"]


def test_a_page_that_is_not_a_report_row_is_none_never_a_guess():
    assert sl.parse_fragments([]) is None
    assert sl.parse_fragments([(10.0, 10.0, "just a title")]) is None
    runs = [tuple(f) for f in _FRAGS["2015-05-31_DoyleN"] if f[2] != "13.69"]                  # four amounts, not five
    assert sl.parse_fragments(runs) is None
    assert sl.parse_pdf(b"not a pdf") is None


def test_names_normalise_across_the_three_published_forms():
    assert sl.normalise_name("DOYLE, HON. NORMAN E.") == ("Doyle", "Norman E.")
    assert sl.normalise_name("HON. DUFFY, MICHAEL") == ("Duffy", "Michael")
    assert sl.normalise_name("HON. RAYNELL ANDREYCHUK") == (None, "Raynell Andreychuk")      # no comma: the matcher tries each split


def test_match_published_tries_each_family_split_for_a_given_family_form():
    fam = {"andreychuk": [("raynell", 1)], "martin": [("paul", 2)], "de bané": [("pierre", 3)]}
    assert sl.match_published("HON. RAYNELL ANDREYCHUK", fam, {}) == 1
    assert sl.match_published("ANDREYCHUK, HON. RAYNELL", fam, {}) == 1
    assert sl.match_published("HON. NOBODY KNOWN", fam, {}) is None


def test_periods_are_the_senates_own_23_and_contiguous():
    from datetime import date, timedelta
    ps = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in sl.PERIODS]
    assert len(ps) == 23 and ps[0][0] == date(2010, 9, 1) and ps[-1][1] == date(2016, 6, 30)
    assert all(b[0] == a[1] + timedelta(days=1) for a, b in zip(ps, ps[1:]))                  # no gap, no overlap
    assert (ps[-1][1] - ps[-1][0]).days > 100 and all(80 < (e - s).days < 95 for s, e in ps[:-1])    # only the last is 4 months


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")

    @event.listens_for(eng, "connect")
    def _fns(dbapi, _rec):
        dbapi.create_function("now", 0, lambda: "2026-10-08 00:00:00")
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("CREATE TABLE parliament.senators (id INTEGER PRIMARY KEY, slug TEXT, name TEXT, given_name TEXT, family_name TEXT)"))
        c.execute(text("""CREATE TABLE parliament.senator_expenses_legacy (id INTEGER PRIMARY KEY AUTOINCREMENT, senator_id INTEGER,
            name_as_published TEXT, period_start DATE, period_end DATE, office_cad REAL, hospitality_cad REAL, living_cad REAL,
            travel_regular_cad REAL, travel_other_cad REAL, travel_cad REAL, total_cad REAL, source_code TEXT, source_url TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE (period_end, source_code))"""))
        c.execute(text("INSERT INTO parliament.senators VALUES (1,'doyle-norman','Norman E. Doyle','Norman E.','Doyle')"))
    return eng


def _run(eng, files: dict, codes: list, **kw):
    def get(url, timeout=60):
        return files.get(url)
    parse = lambda b: _row(b.decode()) if b != b"%PDF-1.3 garbage" else None          # noqa: E731
    return sl.run_legacy_sync(eng, "2015-03-01", "2015-05-31", sleep=0, get=get, codes=codes, parse=parse, **kw)


def test_loader_stores_five_amounts_with_period_dates_and_is_resumable(engine):
    url = sl.url_for("2015-05-31", "DoyleN")
    codes = [{"code": "DoyleN", "family": "DOYLE"}, {"code": "NobodyX", "family": "NOBODY"}]
    st = _run(engine, {url: b"2015-05-31_DoyleN"}, codes)
    assert st["stored"] == 1 and st["not_found"] == 1 and not st["unparsed"] and not st["bad_layout"]
    assert st["per_period"]["2015-05-31"]["senators"] == 1
    with engine.connect() as c:
        r = c.execute(text("SELECT senator_id, period_start, period_end, office_cad, living_cad, travel_cad, total_cad FROM parliament.senator_expenses_legacy")).one()
    assert r[0] == 1 and str(r[1]) == "2015-03-01" and str(r[2]) == "2015-05-31"
    assert (r[3], r[4], r[5]) == (28453.81, 4762.97, 17606.75) and r[6] == round(28453.81 + 13.69 + 4762.97 + 17606.75, 2)
    assert _run(engine, {url: b"2015-05-31_DoyleN"}, codes)["stored"] == 1             # upsert, no duplicate row
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.senator_expenses_legacy")).scalar() == 1


def test_a_code_reused_by_a_different_senator_is_not_attributed_to_the_discovered_one(engine):
    url = sl.url_for("2015-05-31", "DoyleN")
    st = _run(engine, {url: b"2015-05-31_DoyleN"}, [{"code": "DoyleN", "family": "SMITH"}])
    assert st["stored"] == 0 and st["name_mismatch"] and "DOYLE" in st["name_mismatch"][0]


def test_an_unmatched_senator_is_kept_by_published_name_with_a_null_id(engine):
    url = sl.url_for("2015-05-31", "DoyleN")
    with engine.begin() as c:
        c.execute(text("DELETE FROM parliament.senators"))
    st = _run(engine, {url: b"2015-05-31_DoyleN"}, [{"code": "DoyleN", "family": "DOYLE"}])
    assert st["stored"] == 1 and st["unmatched_senator"] == {"DOYLE, HON. NORMAN E.": 1}
    with engine.connect() as c:
        assert c.execute(text("SELECT senator_id FROM parliament.senator_expenses_legacy")).scalar() is None


def test_unreadable_files_are_counted_not_stored(engine):
    url = sl.url_for("2015-05-31", "DoyleN")
    st = _run(engine, {url: b"%PDF-1.3 garbage"}, [{"code": "DoyleN", "family": "DOYLE"}])
    assert st["stored"] == 0 and st["unparsed"] == ["2015-05-31/DoyleN"] and st.get("error")


def test_migration_is_own_table_nullable_senator_no_delete_and_no_own_transaction():
    sql = MIG.read_text(encoding="utf-8")
    assert "parliament.senator_expenses_legacy" in sql and "UNIQUE (period_end, source_code)" in sql
    assert "senator_id         INTEGER       REFERENCES parliament.senators(id) ON DELETE SET NULL" in sql      # nullable: no stub roster rows
    assert "REVOKE DELETE, TRUNCATE" in sql and "GRANT SELECT, INSERT, UPDATE" in sql
    assert "\nBEGIN;" not in sql and "COMMIT;" not in sql and "'102'" in sql
