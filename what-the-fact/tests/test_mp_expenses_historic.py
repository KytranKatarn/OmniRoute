"""House ANNUAL reports FY2002-FY2009 (totals only): parser layouts, vacant seats, the footnote trap, the checksum, the loader.

Fixtures are built in-test from real row shapes (the three layouts that occur), so a Total row can be computed to reconcile.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from ingest.parliament import mp_expenses_historic as h

MIG = Path(__file__).resolve().parent.parent / "migrations" / "100_mp_expenses_annual_totals_only.sql"


def _total_row(amounts_sum: int) -> str:
    """A Total row with 6 amounts that sum to `amounts_sum`."""
    parts = [amounts_sum // 6] * 5
    parts.append(amounts_sum - sum(parts))
    return "Total " + " ".join(f"${p:,}" for p in parts)


# FY2002 layout: name line, then riding + all amounts on one line.
POST = """MEMBERS’ OFFICE AND TRAVEL EXPENSES FOR 2001-2002
Abbott,  Jim
Kootenay--Columbia $205,942 $12,013 $11,800 $114,161 $1,665 $15,461 $2,168 $41
Alcock,  Reg
Winnipeg South $199,447 $139 $15,000 $120,006 $3,704 $23,470 $6,849
Vacant
Calgary Centre $50,000 $2,000 $3,000
"""
# FY2003-FY2007 layout: amounts + riding glued, the name, then a second amounts line; a vacant seat is a bare 'Vacant' line.
PRE = """PUBLIC DISCLOSURE OF INDIVIDUAL MEMBER'S EXPENDITURES FOR 2005-2006
$207,962 $33,601 $14,751 Gaspésie—Îles-de-la-Madeleine
Blais,  Raynald
$142,041 $11,871 $13,441 $6,044 $705 $4,729 $9,185
$198,300 $3,531 $23,787 Outremont
Vacant
$30,037 $8,449 $15,686 $1,975 $3,138 $251
$171,413 $647 $25,030 Gatineau
Boivin,  Françoise
$4,164 $7,228 $10,890 $3,261 $3,307 $4,750 $22,251
Travel, has been fully used.
$16,000
"""
# FY2009 layout: amounts, riding on its own line(s) (long ones WRAP), the name, amounts, a status that may be BLANK.
PRE09 = """PUBLIC DISCLOSURE OF INDIVIDUAL MEMBER'S EXPENDITURES FOR
$211,278 $37,714 $32,086
Montmorency - Charlevoix - Haute-Côte-
Nord
Gagnon,  Test
$44,534 $8,245 $8,718 $2,015 $1,304 $2,320$13,012
NE
$116,157 $2,694 $22,800
North Vancouver
Bell,  Don
$90,824 $10,915 $11,585 $1,308$14,538
$219,080 $16,770 $18,375
Richmond - Arthabaska
Bellavance,  André
$50,226 $10,369 $16,500 $1,220 $3,617 $2,444$29,923
"""


def _with_total(body: str, extra: int = 0) -> str:
    rep = h.parse_report(body + "Total $1 $1 $1 $1 $1 $1\n")                  # parse once just to learn the member sum
    return body + _total_row(rep["sum"] + extra) + "\n"


def test_post_layout_sums_every_amount_and_counts_the_vacant_seat():
    rep = h.parse_report(_with_total(POST))
    assert rep["style"] == "post" and rep["vacant"] == 1
    abbott = rep["members"][0]
    assert abbott["name"] == "Abbott,  Jim" and abbott["riding"] == "Kootenay--Columbia"
    assert abbott["total"] == 205942 + 12013 + 11800 + 114161 + 1665 + 15461 + 2168 + 41 and abbott["n_amounts"] == 8
    assert rep["sum"] == rep["printed_total"]


def test_pre_layout_pairs_the_amounts_around_the_name_and_a_vacant_seat_is_its_own_row():
    rep = h.parse_report(_with_total(PRE))
    assert rep["style"] == "pre" and rep["vacant"] == 1
    blais = rep["members"][0]
    assert blais["riding"] == "Gaspésie—Îles-de-la-Madeleine" and blais["n_amounts"] == 10
    assert blais["total"] == sum([207962, 33601, 14751, 142041, 11871, 13441, 6044, 705, 4729, 9185])
    assert rep["members"][1]["vacant"] and rep["members"][1]["total"] > 0     # the money against a vacant seat is in the printed total


def test_a_prose_footnote_with_a_comma_is_not_a_member():
    rep = h.parse_report(_with_total(PRE))
    assert [m["name"] for m in rep["members"]] == ["Blais,  Raynald", "Vacant", "Boivin,  Françoise"]
    assert h._is_name("Perron,  Gilles-A.")                      # a real name that ends in an initial IS a member
    assert not h._is_name("Travel, has been fully used.")


def test_fy2009_layout_wrapped_riding_glued_amounts_and_blank_status_neighbours():
    rep = h.parse_report(_with_total(PRE09))
    assert rep["style"] == "pre"
    by = {m["name"]: m for m in rep["members"]}
    assert by["Gagnon,  Test"]["riding"] == "Montmorency - Charlevoix - Haute-Côte- Nord" and by["Gagnon,  Test"]["status"] == "NE"
    assert by["Gagnon,  Test"]["total"] == sum([211278, 37714, 32086, 44534, 8245, 8718, 2015, 1304, 2320, 13012])   # '$2,320$13,012' split
    # Bell has a BLANK status, so Bellavance's amounts line follows his directly — it must not be swallowed into Bell
    assert by["Bell,  Don"]["total"] == sum([116157, 2694, 22800, 90824, 10915, 11585, 1308, 14538])
    assert by["Bellavance,  André"]["total"] == sum([219080, 16770, 18375, 50226, 10369, 16500, 1220, 3617, 2444, 29923])


def test_a_number_the_pdf_broke_is_rejoined():
    assert h._amounts("$3,386,76 3 $7,852,378") == [3386763, 7852378]
    assert h._amounts("Total $27,482, 069 $1") == [27482069, 1]


def test_total_row_wrapped_onto_a_second_line_is_added():
    lines = ["x", "Total $1,000,000 $1,000 $1,000 $1,000 $1,000 $1,000", "(*)  represents large rural constituencies", "$906,036 $3,743,526"]
    assert h.printed_total(lines) == 1_000_000 + 5000 + 906036 + 3743526


def test_checksum_rejects_a_year_that_does_not_add_up(tmp_path):
    rep = h.parse_report(_with_total(PRE, extra=50_000))
    assert abs(rep["sum"] - rep["printed_total"]) > h.RECONCILE_TOLERANCE


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")

    @event.listens_for(eng, "connect")
    def _fns(dbapi, _rec):
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
        c.execute(text("INSERT INTO parliament.mps VALUES (8, 'Reg Alcock', 'Alcock', 'reg-alcock')"))
    return eng


def _run(eng, body, **kw):
    return h.run_historic_sync(eng, fy_from=2002, fy_to=2002, sleep=0, get=lambda u, timeout=60: b"pdf", pdf_text=lambda _b: body, **kw)


def test_loader_stores_totals_only_with_null_categories_and_is_resumable(engine):
    st = _run(engine, _with_total(POST))
    assert st["stored"] == 2 and st["vacant"] == 1 and not st["unreconciled"] and not st["unmatched"]
    with engine.connect() as c:
        r = c.execute(text("SELECT fiscal_year, period_start, period_end, total_cad, salaries_cad, source_code, detail "
                           "FROM parliament.mp_expenses_annual WHERE mp_id=7")).one()
    assert r[0] == 2002 and str(r[1]) == "2001-04-01" and str(r[2]) == "2002-03-31"
    assert r[3] == 205942 + 12013 + 11800 + 114161 + 1665 + 15461 + 2168 + 41
    assert r[4] is None and r[5] == "hist-2001-2002"                                    # never a guessed category split
    # (the jsonb `detail` marker is not asserted here: sqlite casts it through a fake jsonb type; Postgres stores it as written)
    again = _run(engine, _with_total(POST))
    assert again["stored"] == 0 and again["skipped_existing"] == 2


def test_loader_refuses_a_year_that_does_not_reconcile_and_stores_nothing(engine):
    st = _run(engine, _with_total(POST, extra=75_000))
    assert st["stored"] == 0 and st["unreconciled"] and st["unreconciled"][0]["fy"] == 2002
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.mp_expenses_annual")).scalar() == 0


def test_loader_refuses_a_year_with_an_implausible_member_row(engine):
    bad = POST.replace("Alcock,  Reg\nWinnipeg South $199,447 $139 $15,000 $120,006 $3,704 $23,470 $6,849", "Alcock,  Reg\nWinnipeg South $199,447")
    st = _run(engine, _with_total(bad))
    assert st["stored"] == 0 and st["unreconciled"][0].get("suspect_rows")


def test_migration_makes_categories_nullable_and_does_not_call_unknown_status_partial():
    sql = MIG.read_text(encoding="utf-8")
    assert sql.count("DROP NOT NULL") == 4
    assert "(a.status IS NOT NULL AND a.status <> 'Active')" in sql
    assert "\nBEGIN;" not in sql and "COMMIT;" not in sql                       # the guarded runner supplies the transaction
    assert "'100'" in sql and "schema_migrations" in sql


def test_two_members_resolving_to_one_mp_id_is_a_collision_the_riding_settles(monkeypatch):
    """Two David Andersons sat in FY2002-FY2006. The name matched BOTH rows to 11840 (Cypress Hills); the Victoria row's riding
    belongs to 11839. Without the collision rule the second row overwrote the first (UNIQUE mp_id, fiscal_year)."""
    from datetime import date
    from ingest.parliament.mp_expenses_archive import _riding_key
    monkeypatch.setattr(h, "_match_mp", lambda name, f, u: 11840)
    idx = {_riding_key("Victoria"): [(date(1993, 1, 1), None, 11839)],
           _riding_key("Cypress Hills—Grasslands"): [(date(2000, 1, 1), None, 11840)]}
    recs = [{"name": "Anderson, Hon. David", "riding": "Victoria"}, {"name": "Anderson,  David", "riding": "Cypress Hills—Grasslands"}]
    out = {r["riding"]: (mp, how) for r, mp, how in h.resolve_ids(recs, {}, {}, idx, date(2005, 4, 1), date(2006, 3, 31))}
    assert out["Cypress Hills—Grasslands"][0] == 11840                       # its riding agrees: keeps the id
    assert out["Victoria"] == (11839, "riding-collision")                    # the other falls back to ITS riding's holder


def test_a_collision_with_no_riding_evidence_stays_unmatched_never_guessed(monkeypatch):
    from datetime import date
    monkeypatch.setattr(h, "_match_mp", lambda name, f, u: 5)
    recs = [{"name": "A,  X", "riding": "Nowhere One"}, {"name": "A,  Y", "riding": "Nowhere Two"}]
    out = h.resolve_ids(recs, {}, {}, {}, date(2005, 4, 1), date(2006, 3, 31))
    assert [mp for _r, mp, _h in out] == [None, None] and {how for _r, _m, how in out} == {"ambiguous"}


def test_a_name_match_with_a_turnover_riding_disagreement_but_no_collision_is_kept(monkeypatch):
    """FY2006 spans the January 2006 election, so the riding window can name the OUTGOING member. That alone is not a collision."""
    from datetime import date
    from ingest.parliament.mp_expenses_archive import _riding_key
    monkeypatch.setattr(h, "_match_mp", lambda name, f, u: 11826)
    idx = {_riding_key("Kitchener—Conestoga"): [(date(1993, 1, 1), None, 12411)]}
    (rec, mp, how), = h.resolve_ids([{"name": "Albrecht, Harold", "riding": "Kitchener—Conestoga"}], {}, {}, idx, date(2005, 4, 1), date(2006, 3, 31))
    assert (mp, how) == (11826, "name")


MIG101 = Path(__file__).resolve().parent.parent / "migrations" / "101_annual_view_first_stint_in_year.sql"


def test_migration_101_falls_back_to_the_first_stint_in_the_year_never_a_guess():
    sql = MIG101.read_text(encoding="utf-8")
    assert "'first_in_year'" in sql and "t.tier = 2" in sql
    assert "t0.start_date <= (a.period_end + 30)" in sql                 # the window is bounded: a later stint is not borrowed blindly
    assert "COALESCE(t.party, 'Unattributed')" in sql                    # no stint in the window -> still Unattributed
    assert "t0.start_date <= (a.period_start + 182)" in sql              # a midpoint stint still wins (tier 1)
    assert "ORDER BY x.tier" in sql
    assert "\nBEGIN;" not in sql and "COMMIT;" not in sql and "'101'" in sql


def test_an_ambiguous_name_with_no_riding_answer_is_settled_by_the_stint_overlapping_the_year():
    """Norman Doyle is stored as two records ('Norman E.' to 2004, 'Norman' 2004-2008). The name ties between them and the riding
    gives nothing in FY2006 (renamed) or FY2009 (two holders). Only 12074 has a stint overlapping each year."""
    from datetime import date
    fam = {"doyle": [{"id": 12073, "given": {"norman", "e."}}, {"id": 12074, "given": {"norman"}}]}
    terms = {12073: [(date(1997, 9, 22), date(2004, 5, 23))], 12074: [(date(2004, 10, 4), date(2005, 11, 29)), (date(2006, 4, 3), date(2008, 9, 7))]}
    rec = {"name": "Doyle,  Norman", "riding": "St. John's East"}
    for start, end in ((date(2005, 4, 1), date(2006, 3, 31)), (date(2008, 4, 1), date(2009, 3, 31))):
        (_r, mp, how), = h.resolve_ids([rec], fam, {}, {}, start, end, terms)
        assert (mp, how) == (12074, "name-term")
    # without term evidence it stays unmatched (the old behaviour) — never a guess
    (_r, mp, how), = h.resolve_ids([rec], fam, {}, {}, date(2005, 4, 1), date(2006, 3, 31), None)
    assert mp is None


def test_two_candidates_both_overlapping_the_year_stay_unmatched():
    from datetime import date
    fam = {"smith": [{"id": 1, "given": {"john"}}, {"id": 2, "given": {"john"}}]}
    terms = {1: [(date(2005, 1, 1), None)], 2: [(date(2005, 1, 1), None)]}
    (_r, mp, how), = h.resolve_ids([{"name": "Smith, John", "riding": "X"}], fam, {}, {}, date(2005, 4, 1), date(2006, 3, 31), terms)
    assert mp is None and how is None
