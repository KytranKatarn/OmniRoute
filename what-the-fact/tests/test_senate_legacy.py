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
        c.execute(text("CREATE TABLE parliament.senators (id INTEGER PRIMARY KEY, slug TEXT, name TEXT, given_name TEXT, family_name TEXT, appointed_at DATE)"))
        c.execute(text("""CREATE TABLE parliament.senator_expenses_legacy (id INTEGER PRIMARY KEY AUTOINCREMENT, senator_id INTEGER,
            name_as_published TEXT, name_key TEXT, period_start DATE, period_end DATE, office_cad REAL, hospitality_cad REAL, living_cad REAL,
            travel_regular_cad REAL, travel_other_cad REAL, travel_cad REAL, total_cad REAL, source_code TEXT, source_url TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE (period_end, source_code))"""))
        c.execute(text("INSERT INTO parliament.senators (id, slug, name, given_name, family_name) VALUES (1,'doyle-norman','Norman E. Doyle','Norman E.','Doyle')"))
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


def _row_runs(cells, name="HON THANH HAI NGO"):
    """A report page: header runs, the Quarter row built from `cells` [(x, text)], and a printed name."""
    y = 319.3
    return ([(536.6, 89.5, name), (y, 44.5, "Quarter / Trimestre"), (368.7, 158.0, "Staff & Office("), (356.5, 284.0, "Hospitality / Accueil"),
             (409.2, 400.0, "Living Expenses in the"), (368.7, 523.0, "Regular Travel /("), (368.7, 634.0, "Other Travel(")]
            + [(y, x, t) for x, t in cells])


def test_an_amount_split_into_one_character_runs_at_the_same_x_is_rejoined():
    """Real: NgoT 2013-02-28 prints the travel-other cell as '3','2',',','5','4','2','.','36' and the travel cell as '0.','00'."""
    cells = [(192, "26,020.50"), (317, "0.00"), (438, "0.00"), (546, "0."), (546, "00"),
             (652, "3"), (652, "2"), (652, ","), (652, "5"), (652, "4"), (652, "2"), (652, "."), (652, "36")]
    r = sl.parse_fragments(_row_runs(cells))
    assert [r[c] for c in sl.COLUMNS] == [26020.50, 0.0, 0.0, 0.0, 32542.36] and r["layout_ok"]


def test_a_title_printed_without_the_period_is_still_a_name():
    r = sl.parse_fragments(_row_runs([(192, "12,530.02"), (312, "102.43"), (429, "5,388.40"), (546, "2,288.42"), (663, "0.00")], "HON DIANE BELLEMARE"))
    assert r["name"] == "HON DIANE BELLEMARE" and r["office"] == 12530.02
    assert sl.normalise_name("HON DIANE BELLEMARE") == (None, "Diane Bellemare")


def test_two_amounts_are_not_glued_together_just_because_they_share_a_run():
    r = sl.parse_fragments(_row_runs([(192, "1,000.00 2.50"), (429, "3.00"), (546, "4.00"), (652, "5.00")]))
    assert [r[c] for c in sl.COLUMNS] == [1000.0, 2.5, 3.0, 4.0, 5.0]


# --- the 11 recoverable "unparsed" PDFs (2026-10-09 audit): real text runs, expected values read off the page -------------------------------


def test_a_footnote_asterisk_at_an_amounts_x_is_a_marker_not_part_of_it():
    """Real: DuffyM / WalliP 2014-02-28 print '*' footnote markers on the Quarter row; one sits at the SAME x as a figure ('-2,599.30','*'),
    which glued into '-2,599.30*' and failed the amount pattern -> only four amounts -> the file was dropped. The summed totals equal the
    rows the earlier (looser) parse had stored: Duffy -1,224.31, Wallin 2,141.38."""
    d = _row("2014-02-28_DuffyM")
    assert [d[c] for c in sl.COLUMNS] == [1374.99, 0.0, 0.0, -2599.30, 0.0] and d["total"] == -1224.31 and d["layout_ok"]
    w = _row("2014-02-28_WalliP")
    assert [w[c] for c in sl.COLUMNS] == [1934.06, 0.0, 1941.76, -1734.44, 0.0] and w["total"] == 2141.38 and w["layout_ok"]


@pytest.mark.parametrize("fixture, expected", [
    # '0.' at x=544.9 + '00' at 552.5, and '1','9',',','938','.3','8' over 651.6-656.6
    ("2013-05-31_NgoT", [40998.68, 551.02, 0.0, 0.0, 19938.38]),
    # '0','.','00' at 525.7/530.8/533.3 and the minus sign as its OWN run: '-','6',',','045','.5','4'
    ("2013-08-31_LeBreM", [41230.02, 0.0, 0.0, 0.0, -6045.54]),
    # '0','.0','0' at 529/534/541.6 and '8',',982','.','04' at 645.5/650.6
    ("2015-02-28_MunsoJ", [35928.64, 2649.20, 0.0, 0.0, 8982.04]),
])
def test_an_amount_split_across_runs_at_nearby_but_unequal_x_is_rejoined(fixture, expected):
    """Kerning shifts the pieces of one amount by a few points, so the exact-x join missed them (the widest in-amount shift is 7.6pt)."""
    r = _row(fixture)
    assert [r[c] for c in sl.COLUMNS] == expected and r["layout_ok"]


def test_two_whole_amounts_closer_than_the_join_gap_are_cut_apart_at_their_decimals():
    """Runs 8pt apart land in one cell, but an amount ends at its first '.dd', so '1,000.00' + '2.50' are two amounts, not one invented figure.
    (They used to be refused; the whole-row reader needs no distance rule to tell them apart.)"""
    r = sl.parse_fragments(_row_runs([(192, "1,000.00"), (200, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5.00")]))
    assert [r[c] for c in sl.COLUMNS] == [1000.0, 2.5, 3.0, 4.0, 5.0]


def test_a_wide_gap_still_separates_neighbouring_columns():
    r = sl.parse_fragments(_row_runs([(192, "1.00"), (255, "2.00"), (319, "3.00"), (435, "4.00"), (546, "5.00")]))
    assert [r[c] for c in sl.COLUMNS] == [1.0, 2.0, 3.0, 4.0, 5.0]


# --- name_key: the same person printed in different forms groups; different people never do ---------------------------------------------------------------


def test_name_key_is_the_same_for_every_printed_form_of_one_person():
    assert sl.name_key("CHAPUT, HON. MARIA") == sl.name_key("HON. MARIA CHAPUT") == "chaput maria"
    assert sl.name_key("ENVERGA JR., HON. TOBIAS C.") == sl.name_key("HON. TOBIAS C. ENVERGA") == "enverga tobias"
    assert sl.name_key("HON. ROD A.A. ZIMMER") == sl.name_key("ZIMMER, HON. ROD A.A.")
    assert sl.name_key("HON. ANDRÉE CHAMPAGNE") == sl.name_key("CHAMPAGNE, HON. ANDREE")                # accents fold
    assert sl.name_key("HON. MARIE-P.POULIN(CHARETTE)") == sl.name_key("POULIN, HON. MARIE-P. (CHARETTE)")


def test_name_key_never_merges_different_people_or_invents_a_link():
    assert sl.name_key("HON. DAVID ANGUS") != sl.name_key("HON. DAVID BRALEY")
    assert sl.name_key("HON. PIERRE CLAUDE NOLIN") != sl.name_key("HON. PIERRE NOLIN")      # a real extra word: visible, not guessed
    assert sl.name_key(None) is None and sl.name_key("") is None and sl.name_key("HON.") is None


def test_a_jr_suffix_on_the_family_name_does_not_defeat_the_roster_match():
    assert sl.normalise_name("ENVERGA JR., HON. TOBIAS C.") == ("Enverga", "Tobias C.")
    fam = {"enverga": [("tobias c. jr.", 166)]}
    assert sl.match_published("ENVERGA JR., HON. TOBIAS C.", fam, {}) == 166


def test_the_loader_stores_the_name_key_and_an_unmatched_senator_still_gets_one(engine):
    url = sl.url_for("2015-05-31", "DoyleN")
    with engine.begin() as c:
        c.execute(text("DELETE FROM parliament.senators"))
    _run(engine, {url: b"2015-05-31_DoyleN"}, [{"code": "DoyleN", "family": "DOYLE"}])
    with engine.connect() as c:
        r = c.execute(text("SELECT senator_id, name_key FROM parliament.senator_expenses_legacy")).one()
    assert r[0] is None and r[1] == "doyle norman"


MIG103 = Path(__file__).resolve().parent.parent / "migrations" / "103_senator_expenses_legacy_name_key.sql"


def test_migration_103_is_additive_idempotent_and_widens_no_privilege():
    sql = MIG103.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS name_key TEXT" in sql and "CREATE INDEX IF NOT EXISTS" in sql
    assert "\nBEGIN;" not in sql and "COMMIT;" not in sql and "'103'" in sql
    assert "GRANT" not in sql and "DROP" not in sql and "DELETE" not in sql.replace("DELETE and", "")


# --- UNDER-joining is the dangerous direction: a dropped fragment must refuse the row, never produce a wrong-but-valid figure ----------------------


@pytest.mark.parametrize("fixture, expected", [
    # '6,' '0' (x=428.7) '00' (441.4) '.' (451.5) '00' (454.0): 12.7pt between '0' and '00'. A 12pt gap read this as 00.00 = ZERO; it is 6,000.00.
    ("2013-05-31_StewaC", [30209.04, 113.58, 6000.00, 10243.90, 150.27]),
    # '5,9' (645.5) '35' (658.1) '.' (668.3) '30' (670.8): a 12pt gap dropped '5,9' and read 35.30; it is 5,935.30.
    ("2014-05-31_NgoT", [43259.48, 1133.28, 0.0, 0.0, 5935.30]),
    # '2,041' (432.6) then '.58' (455.3): 22.7pt, the widest in-amount shift seen.
    ("2013-05-31_WallaJ", [34291.92, 0.0, 2041.58, 14019.01, 0.0]),
])
def test_an_amount_whose_pieces_are_spread_wide_is_read_whole_not_as_a_valid_looking_fragment(fixture, expected):
    r = _row(fixture)
    assert [r[c] for c in sl.COLUMNS] == expected and r["layout_ok"]


@pytest.mark.parametrize("fixture, expected", [
    # '00 804' is ONE run (the end of 0.00 fused with the start of the next amount); '.','56' sit 100pt on
    ("2013-02-28_WhiteV", [22269.14, 807.50, 0.0, 0.0, 804.56]),
    # '0 4,' (x=550) + '86','7.','9','2' (x=654): 4,867.92. The old reader kept ONLY '867.92' and stored it.
    ("2013-05-31_WhiteV", [19447.99, 771.30, 0.0, 0.0, 4867.92]),
    # '00 4' (x=523) + ',','683','.','40' (x=650): 4,683.40, stored as 683.40
    ("2014-02-28_CoolsA", [24846.67, 62.85, 0.0, 0.0, 4683.40]),
    # '966.07 4' fuses living with the start of travel; ',','842','.','99' follow: 4,842.99, stored as 842.99
    ("2016-06-30_BoisvP", [48440.32, 343.77, 7966.07, 4842.99, 435.50]),
    # '0 1,0' (x=530) + '05' (x=658) '.' '7','8': 1,005.78
    ("2014-11-30_LeBreM", [36916.01, 0.0, 0.0, 0.0, 1005.78]),
    # one run holds the label, the first amount and the START of the second ('2,'); the rest are loose pieces plus a 3-amount run
    ("2012-08-31_MeredD", [48990.41, 2763.54, 7935.55, 14629.06, 977.85]),
    # '1' (522.6) '6' ',' '511' '.' '67 301' (527.7) then '.','60' (663): 16,511.67 and 301.60 — the second starts inside the first's run
    ("2014-08-31_MerceT", [40542.73, 188.50, 6325.64, 16511.67, 301.60]),
    ("2014-05-31_MerceT", [40123.09, 368.74, 4227.10, 20407.48, 715.58]),
    ("2014-05-31_WallaJ", [5201.68, 0.0, 5205.85, 4996.49, 0.0]),
    ("2014-05-31_ChareM", [30426.18, 768.39, 0.0, 0.0, 5730.22]),
    ("2014-08-31_WhiteV", [18904.76, 0.0, 0.0, 0.0, 172.64]),
    # '0.00 0' + '.0' '0' + '0.00': a zero amount whose '0' sits at the end of the previous run
    ("2016-06-30_ChareM", [3112.61, 0.0, 0.0, 0.0, 0.0]),
])
def test_an_amount_that_ends_in_the_next_cells_run_is_read_whole(fixture, expected):
    """Real PDFs, every expected figure read off a RENDERED image of the page (2026-10-12), not off the extracted text. The old cell-by-cell
    reader either refused these or kept the tail of the amount: three of them are in the database wrong by $4,000 (migration 104)."""
    r = _row(fixture)
    assert r is not None and r["layout_ok"] and [r[c] for c in sl.COLUMNS] == expected


def test_a_fragment_is_merged_into_the_amount_it_belongs_to_never_dropped():
    """'5,9' (x=652) and '35.30' (x=700) are one amount, 5,935.30 — the shape that once read 35.30 with the '5,9' silently ignored."""
    cells = [(192, "1,000.00"), (312, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5,9"), (700, "35.30")]
    r = sl.parse_fragments(_row_runs(cells))
    assert [r[c] for c in sl.COLUMNS] == [1000.0, 2.5, 3.0, 4.0, 5935.30]


@pytest.mark.parametrize("cells", [
    # a fragment that cannot join the next amount ('5,9' + '2.50' = '5,92.50' breaks thousands grouping): '5,' is left over -> refuse
    [(192, "1,000.00"), (312, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5,9"), (700, "2.50")],
    # a lone fragment with nothing to join
    [(192, "1,000.00"), (312, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5.00"), (700, "9,")],
    # text on the row that is not an amount at all
    [(192, "1,000.00"), (312, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5.00"), (700, "see note")],
    # six amounts
    [(192, "1,000.00"), (312, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5.00"), (700, "6.00")],
    # an amount with no decimals is not an amount
    [(192, "1,000.00"), (312, "2.50"), (429, "3.00"), (546, "4.00"), (652, "5")],
])
def test_a_row_with_text_that_is_not_part_of_an_amount_is_refused_never_guessed(cells):
    assert sl.parse_fragments(_row_runs(cells)) is None


def test_a_negative_amount_split_across_cells_keeps_its_sign():
    """'-' own run, then pieces in the next cell: -6,045.54 (2013-08-31 LeBreM prints the minus as a separate run)."""
    cells = [(192, "41,230.02"), (312, "0.00"), (429, "0.00"), (546, "0.00"), (652, "-"), (656, "6"), (656, ","), (656, "045"), (670, ".5"), (670, "4")]
    r = sl.parse_fragments(_row_runs(cells))
    assert r["travel_other"] == -6045.54 and r["office"] == 41230.02


# --- migration 104: six stored rows that lost their leading digits ---------------------------------------------------------------------------

MIG104 = Path(__file__).resolve().parent.parent / "migrations" / "104_senator_expenses_legacy_leading_digit_corrections.sql"

_WRONG_ROWS = [   # (period_end, code, office, hosp, living, travel_regular, travel_other) as the OLD reader stored them
    ("2013-11-30", "CoolsA", 37712.00, 0.0, 0.0, 0.0, 3951.03),
    ("2015-08-31", "NgoT", 40578.65, 431.82, 0.0, 0.0, 940.03),
    ("2016-06-30", "LovelS", 48836.75, 112.30, 5846.59, 71.32, 622.61),
    ("2013-05-31", "WhiteV", 19447.99, 771.30, 0.0, 0.0, 867.92),
    ("2014-02-28", "CoolsA", 24846.67, 62.85, 0.0, 0.0, 683.40),
    ("2016-06-30", "BoisvP", 48440.32, 343.77, 7966.07, 842.99, 435.50),
]
_RIGHT = {  # what the PDF prints, read off the rendered page
    ("2013-11-30", "CoolsA"): (0.0, 13951.03), ("2015-08-31", "NgoT"): (0.0, 13940.03), ("2016-06-30", "LovelS"): (6571.32, 622.61),
    ("2013-05-31", "WhiteV"): (0.0, 4867.92), ("2014-02-28", "CoolsA"): (0.0, 4683.40), ("2016-06-30", "BoisvP"): (4842.99, 435.50),
}


def _apply_104(eng):
    """Run the migration's UPDATEs (portable SQL); the ledger INSERT targets public.schema_migrations, which sqlite has no schema for."""
    sql = MIG104.read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    for stmt in [x.strip() for x in body.split(";") if x.strip().upper().startswith("UPDATE")]:
        with eng.begin() as c:
            c.execute(text(stmt))


def _seed_104(eng):
    with eng.begin() as c:
        for pe, code, o, h, l, tr, to in _WRONG_ROWS + [("2014-05-31", "NgoT", 43259.48, 1133.28, 0.0, 0.0, 5935.30)]:     # last = an already-right control
            c.execute(text("INSERT INTO parliament.senator_expenses_legacy (name_as_published, period_end, office_cad, hospitality_cad, living_cad, "
                           "travel_regular_cad, travel_other_cad, travel_cad, total_cad, source_code) VALUES ('x', :pe, :o, :h, :l, :tr, :to, :t, :tot, :code)"),
                      {"pe": pe, "o": o, "h": h, "l": l, "tr": tr, "to": to, "t": round(tr + to, 2), "tot": round(o + h + l + tr + to, 2), "code": code})


def _rows(eng):
    with eng.connect() as c:
        return {(r[0], r[1]): r[2:] for r in c.execute(text(
            "SELECT period_end, source_code, travel_regular_cad, travel_other_cad, travel_cad, total_cad, office_cad, hospitality_cad, living_cad "
            "FROM parliament.senator_expenses_legacy"))}


def test_migration_104_corrects_each_row_to_the_printed_figure_and_rederives_the_sums(engine):
    _seed_104(engine)
    _apply_104(engine)
    rows = _rows(engine)
    for (pe, code, o, h, l, *_), (tr, to) in zip(_WRONG_ROWS, [_RIGHT[(r[0], r[1])] for r in _WRONG_ROWS]):
        got_tr, got_to, got_travel, got_total = rows[(pe, code)][:4]
        assert (got_tr, got_to) == (tr, to), (pe, code)
        assert got_travel == pytest.approx(tr + to) and got_total == pytest.approx(o + h + l + tr + to), (pe, code)


def test_migration_104_is_idempotent_and_never_touches_a_row_that_is_already_right(engine):
    _seed_104(engine)
    _apply_104(engine)
    once = _rows(engine)
    _apply_104(engine)
    assert _rows(engine) == once                                                                    # second run: no change
    assert once[("2014-05-31", "NgoT")][1] == 5935.30                                              # the control row was never matched


def test_migration_104_is_a_noop_when_the_loader_already_wrote_the_right_value(engine):
    """Loader first, migration second (or the reverse) must end in the same place: the guard matches the WRONG value only."""
    _seed_104(engine)
    with engine.begin() as c:
        c.execute(text("UPDATE parliament.senator_expenses_legacy SET travel_other_cad = 4867.92, travel_cad = 4867.92, total_cad = 25087.21 "
                       "WHERE period_end = '2013-05-31' AND source_code = 'WhiteV'"))
    _apply_104(engine)
    assert _rows(engine)[("2013-05-31", "WhiteV")][1:4] == (4867.92, 4867.92, 25087.21)


def test_migration_104_never_overwrites_a_value_other_than_the_known_wrong_one(engine):
    """The guard is the safety: a row someone already corrected by hand to a DIFFERENT figure is left alone."""
    _seed_104(engine)
    with engine.begin() as c:
        c.execute(text("UPDATE parliament.senator_expenses_legacy SET travel_other_cad = 9999.99 WHERE period_end = '2013-05-31' AND source_code = 'WhiteV'"))
    _apply_104(engine)
    assert _rows(engine)[("2013-05-31", "WhiteV")][1] == 9999.99


def test_migration_104_is_update_only_guarded_and_logs_itself():
    sql = MIG104.read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert body.count("UPDATE parliament.senator_expenses_legacy") == 6
    assert all("AND travel_" in chunk.split("WHERE")[1] for chunk in body.split("UPDATE")[1:] if "WHERE" in chunk)     # each guards the wrong value
    assert "\nBEGIN;" not in sql and "COMMIT;" not in sql and "'104'" in sql
    assert "GRANT" not in body and "DROP" not in body and "DELETE" not in body and "TRUNCATE" not in body


# --- the identity gate: the family-name matcher must not attach a retired senator to an unrelated sitting namesake -------------------------


@pytest.mark.parametrize("published, roster_given, agrees", [
    ("BLACK, HON. DOUGLAS JOHN", "Robert", False),            # Doug Black (2013-) vs Robert Black (2018-): the live misattribution
    ("HON. DENNIS PATTERSON", "Rebecca", False),               # Dennis vs Rebecca Patterson
    ("HON. VERNON DARRYL WHITE", "Judy", False),               # Vern vs Judy White
    ("SMITH, HON. DAVID P.", "Larry W.", False),                # two Smiths that were merged into one profile
    ("SMITH, HON. LARRY", "Larry W.", True),
    ("HON. HECTOR DANIEL LANG", "Daniel", True),               # goes by a middle name
    ("ANDREYCHUK, HON. RAYNELL", "A. Raynell", True),          # the roster carries an initial first
    ("VERNER, HON. JOS\u00c9E", "Jos\u00e9e", True),             # accents
    ("HERVIEUX-PAYETTE, HON. CELINE", "C\u00e9line", True),
    ("LOVELACE NICHOLAS, HON. S.M.", "Sandra M.", True),       # a leading initial
    ("POULIN(CHARETTE), HON.MARIE-P.", "Marie-P.", True),
    ("HON. MICHAEL DUFFY", "Mike", False),                     # a nickname: fail closed, never link on a guess
    ("HON. DON MEREDITH", None, False),                        # nothing to compare: not an agreement
])
def test_given_agrees(published, roster_given, agrees):
    assert sl.given_agrees(published, roster_given) is agrees


def test_plausible_link_needs_the_roster_row_and_a_period_after_the_appointment():
    from datetime import date
    assert not sl.plausible_link("HON. DON MEREDITH", None, date(2013, 5, 31))                      # unknown roster entry
    assert not sl.plausible_link("HON. DON MEREDITH", ("Don", date(2012, 12, 1)), date(2011, 5, 31))   # period ends before appointment
    assert sl.plausible_link("HON. DON MEREDITH", ("Don", date(2012, 12, 1)), date(2013, 5, 31))
    assert sl.plausible_link("HON. DON MEREDITH", ("Don", "2012-12-01"), date(2013, 5, 31))          # sqlite hands back text
    assert sl.plausible_link("HON. DON MEREDITH", ("Don", None), date(2011, 5, 31))                   # appointment unknown: not a reason to refuse


def _namesake_engine(engine, senator_id, name, given, family, appointed):
    with engine.begin() as c:
        c.execute(text("INSERT INTO parliament.senators VALUES (:i, :s, :n, :g, :f, :a)"),
                  {"i": senator_id, "s": name.lower().replace(" ", "-"), "n": name, "g": given, "f": family, "a": appointed})


def _syn(monkeypatch, key, published):
    cells = [(192, "1.00"), (312, "2.00"), (429, "3.00"), (546, "4.00"), (652, "5.00")]
    monkeypatch.setitem(_FRAGS, key, [list(f) for f in _row_runs(cells, published)])


def test_the_loader_does_not_link_a_retired_senator_to_a_sitting_namesake(engine, monkeypatch):
    _namesake_engine(engine, 2, "Robert Black", "Robert", "Black", "2018-02-15")
    _syn(monkeypatch, "syn_BlackD", "BLACK, HON. DOUGLAS JOHN")
    # the root cause, pinned: the shared family-name matcher WOULD have linked him to Robert
    from ingest.parliament.senator_expenses import _load_senator_index

    fam_idx, full_idx = _load_senator_index(engine)
    assert sl.match_published("BLACK, HON. DOUGLAS JOHN", fam_idx, full_idx) == 2
    st = _run(engine, {sl.url_for("2015-05-31", "BlackD"): b"syn_BlackD"}, [{"code": "BlackD", "family": "BLACK"}])
    assert st["stored"] == 1 and len(st["implausible_link"]) == 1 and "2015-05-31/BlackD" in st["implausible_link"][0]
    with engine.connect() as c:
        sid, nk = c.execute(text("SELECT senator_id, name_key FROM parliament.senator_expenses_legacy")).one()
    assert sid is None and nk == sl.name_key("BLACK, HON. DOUGLAS JOHN")                           # kept under his OWN name, not Robert's


def test_the_loader_still_links_a_senator_known_by_a_middle_name(engine, monkeypatch):
    _namesake_engine(engine, 3, "Daniel Lang", "Daniel", "Lang", "2009-01-01")
    _syn(monkeypatch, "syn_LangH", "LANG, HON. HECTOR DANIEL")
    st = _run(engine, {sl.url_for("2015-05-31", "LangH"): b"syn_LangH"}, [{"code": "LangH", "family": "LANG"}])
    assert st["stored"] == 1 and st["implausible_link"] == []
    with engine.connect() as c:
        assert c.execute(text("SELECT senator_id FROM parliament.senator_expenses_legacy")).scalar() == 3


def test_the_loader_does_not_link_a_period_that_ends_before_the_roster_senators_appointment(engine, monkeypatch):
    _namesake_engine(engine, 4, "Don Meredith", "Don", "Meredith", "2018-01-01")
    _syn(monkeypatch, "syn_MeredD", "HON. DON MEREDITH")
    st = _run(engine, {sl.url_for("2015-05-31", "MeredD"): b"syn_MeredD"}, [{"code": "MeredD", "family": "MEREDITH"}])
    assert st["stored"] == 1 and len(st["implausible_link"]) == 1
    with engine.connect() as c:
        assert c.execute(text("SELECT senator_id FROM parliament.senator_expenses_legacy")).scalar() is None
