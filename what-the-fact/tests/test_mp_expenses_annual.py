"""House ANNUAL expense reports (FY2010-FY2015): parser, checksum, loader, migration.

Fixtures are real member pages, one per layout that occurs: plain header, riding wrapped mid-word with a part-year 'From..to'
line, a part-year member whose status precedes the riding, a page with travel-points columns and a wrapped category label,
and a vacant seat.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from ingest.parliament import mp_expenses_annual as an

FX = Path(__file__).resolve().parent / "fixtures" / "mp_annual"
MIG = Path(__file__).resolve().parent.parent / "migrations" / "099_mp_expenses_annual.sql"


def _fx(name: str) -> str:
    return (FX / f"{name}.txt").read_text(encoding="utf-8")


def _one(name: str):
    blocks = an.split_members(_fx(name))
    assert len(blocks) == 1, "a fixture is exactly one member page"
    return an.parse_member_block(blocks[0])


def test_plain_page_matches_the_hand_summed_categories():
    r = _one("fy2010_albrecht_plain")
    assert r["name"] == "Albrecht, Harold" and r["status"] == "Active" and r["riding"] == "Kitchener-Conestoga"
    assert r["salaries"] == 212325.80 and r["total"] == 500466.79
    assert r["travel"] == round(43643.72 + 7117.01 + 25468.00, 2)                     # three cat-2 lines
    assert r["hospitality"] == 8850.66
    # contracts = advertising 12,664.71 + printing (15,901.43 + 87,251.71 + 5,992.44) + offices
    assert r["contracts"] == round(r["total"] - r["salaries"] - r["travel"] - r["hospitality"], 2)
    assert {"1", "2", "3", "4", "5", "6"} <= set(r["detail"])


def test_riding_wrapped_mid_word_and_a_part_year_status():
    r = _one("fy2010_armstrong_wrapped_riding")
    assert r["status"] == "NEB" and r["name"] == "Armstrong, Scott"
    assert "Cumberland-Colchester" in r["riding"] and "usquodoboit" in r["riding"]     # wrapped, kept (matched by riding key later)


def test_part_year_member_whose_status_precedes_the_riding():
    r = _one("fy2012_abbott_part_year")
    assert r["status"] == "NSR" and r["name"] == "Abbott, Hon. Jim" and r["riding"].startswith("Kootenay")


def test_points_columns_and_a_wrapped_category_label_do_not_leak_into_the_money():
    r = _one("fy2014_albas_points_cols")
    assert r["total"] == 355746.36 and r["salaries"] == 192430.65
    # 'Member 7,681.98 41,439.88 25.50 3.00 - 49,121.86': the LAST number is the total, never a points column
    assert 49121.86 in [d["cad"] for d in r["detail"]["2"]] and 25.50 not in [d["cad"] for d in r["detail"]["2"]]
    labels = [d["line"] for d in r["detail"]["6"]]
    assert any(l.startswith("Informatics and telecommunication equipment") and "purchases" in l for l in labels)


def test_a_vacant_seat_is_counted_on_its_own_not_as_a_rejection():
    recs, rejected, vacant = an.parse_report(_fx("fy2010_vacant"))
    assert (len(recs), rejected, vacant) == (0, 0, 1)


def test_a_page_that_does_not_add_up_is_rejected_not_loaded():
    bad = _fx("fy2010_albrecht_plain").replace("500,466.79", "500,566.79")
    recs, rejected, vacant = an.parse_report(bad)
    assert (len(recs), rejected) == (0, 1)


def test_whole_report_counts_each_kind_of_page():
    text_ = "\n".join(_fx(n) for n in ("fy2010_albrecht_plain", "fy2010_vacant", "fy2012_abbott_part_year"))
    recs, rejected, vacant = an.parse_report(text_)
    assert (len(recs), rejected, vacant) == (2, 0, 1)


def test_money_dash_is_zero_and_fiscal_dates_follow_the_year_the_fy_ends():
    assert an._money("-") == 0.0 and an._money("1,234.50") == 1234.50
    assert an.fy_dates(2010) == (an.date(2009, 4, 1), an.date(2010, 3, 31))
    assert set(an.ANNUAL_CODES) == {2010, 2011, 2012, 2013, 2014, 2015}


def test_migration_states_its_rules_and_stays_re_runnable():
    sql = MIG.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS parliament.mp_expenses_annual" in sql and "UNIQUE (mp_id, fiscal_year)" in sql
    assert "CREATE OR REPLACE VIEW parliament.v_mp_expenses_annual_by_party" in sql
    assert "period_start + 182" in sql and "party_changed_in_year" in sql and "wind_down" in sql
    assert "INSERT INTO public.schema_migrations" in sql and "ON CONFLICT (version) DO NOTHING" in sql


# ---- loader against an in-memory database ---------------------------------------------------------------------------------

LIST_HTML = ('<table><tr><td><a class="ReportSelectionMemberLink" href="2011-2012/1">Abbott, Hon. Jim</a></td>'
             '<td>Kootenay-Columbia</td><td>British Columbia</td><td>Conservative</td></tr></table>')


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")

    @event.listens_for(eng, "connect")
    def _fns(dbapi, _rec):                       # the loader's ON CONFLICT clause calls Postgres now()
        dbapi.create_function("now", 0, lambda: "2026-10-07 00:00:00")
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


def _run(eng, **kw):
    def get(url, timeout=60):
        return LIST_HTML.encode() if "expenditurebymember" in url else b"pdf"
    return an.run_annual_sync(eng, fy_from=2012, fy_to=2012, sleep=0, get=get,
                              pdf_text=lambda _b: _fx("fy2012_abbott_part_year"), **kw)


def test_loader_stores_the_member_year_with_the_published_caucus_and_is_resumable(engine):
    s1 = _run(engine)
    assert (s1["reports"], s1["stored"], s1["rejected_pages"]) == (1, 1, 0)
    with engine.connect() as c:
        row = c.execute(text("SELECT mp_id, fiscal_year, status, caucus, total_cad, period_start FROM parliament.mp_expenses_annual")).one()
    assert row[:4] == (7, 2012, "NSR", "Conservative") and row[5] == "2011-04-01" and row[4] > 0
    s2 = _run(engine)
    assert (s2["stored"], s2["skipped_existing"]) == (0, 1)


def test_an_unmatched_name_is_counted_never_guessed(engine):
    with engine.begin() as c:
        c.execute(text("DELETE FROM parliament.mps"))
    s = _run(engine)
    assert s["stored"] == 0 and s["unmatched"] == {"Abbott, Hon. Jim": 1} and s.get("error")
