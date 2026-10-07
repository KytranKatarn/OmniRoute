"""House archive MP expenses: parsing, the 8 -> 4 category fold, the checksum guard, and the YTD -> quarterly rule."""
import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import mp_expenses_archive as ma  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "mp_archive")
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _txt(name):
    return open(os.path.join(FIX, name + ".txt"), encoding="utf-8").read()


def test_aboultaif_fy2019_q1_matches_hand_summed_categories():
    r = ma.parse_member_report(_txt("mer2019q1_aboultaif"))
    assert r["period_end"] == date(2018, 6, 30) and r["status"] == "Active" and r["riding"] == "Edmonton Manning"
    assert r["salaries"] == 49905.20
    assert r["hospitality"] == 706.45
    # travel = member 5,087.47 + designated 2,903.25 + dependants 0 + employees 1,485.41 + accommodation 0
    #          + per diem 1,651.45 + secondary residence 4,271.22
    assert r["travel"] == 15398.80
    # contracts = service contracts 0 + gifts 359.97 + advertising 2,285.00 + printing (2,831.52 + 3,392.28)
    #             + offices (9,005.65 + 100.00 + 965.42 + 795.13 + 174.02)
    assert r["contracts"] == 19908.99
    assert r["total"] == 85919.44
    assert round(r["salaries"] + r["travel"] + r["hospitality"] + r["contracts"], 2) == r["total"]


def test_ablonczy_fy2016_q2_and_the_status_line_with_an_honorific():
    r = ma.parse_member_report(_txt("mer2016q2_ablonczy"))
    assert r["period_end"] == date(2015, 9, 30) and r["status"] == "Active" and r["riding"] == "Calgary—Nose Hill"
    assert r["total"] == 175618.38 and r["salaries"] == 103613.85 and r["hospitality"] == 3220.16
    assert round(r["salaries"] + r["travel"] + r["hospitality"] + r["contracts"], 2) == r["total"]


def test_a_report_that_does_not_add_up_is_rejected_not_loaded():
    t = _txt("mer2019q1_aboultaif").replace("Total 70,987.82 14,931.62 5.00 1.00 - 85,919.44",
                                            "Total 70,987.82 14,931.62 5.00 1.00 - 85,000.00")
    assert ma.parse_member_report(t) is None


def test_garbage_and_missing_pieces_return_none():
    assert ma.parse_member_report("") is None
    assert ma.parse_member_report("MEMBERS’ EXPENDITURES REPORT\nApril 1, 2018 to June 30, 2018\nno table") is None


def test_money_handles_dash_negatives_and_thousands():
    assert ma._money("-") == 0.0 and ma._money("12,094.86") == 12094.86
    assert ma._money("(1,234.00)") == -1234.0 and ma._money("-1,234.00") == -1234.0


def test_member_list_parses_wrapped_names_and_dedupes():
    html = '''<table><tbody>
    <tr class="odd"><td /><td><a class="ReportSelectionMemberLink" href="mer2019q1/10010">Aboultaif,\r\n  Ziad</a></td>
      <td>Edmonton Manning</td><td>Alberta</td><td>Conservative</td></tr>
    <tr class="even"><td /><td><a class="ReportSelectionMemberLink" href="mer2019q1/10010">Aboultaif, Ziad</a></td>
      <td>Edmonton Manning</td><td>Alberta</td><td>Conservative</td></tr>
    <tr><td /><td><a class="ReportSelectionMemberLink" href="mer2019q1/10020">Albas, Dan</a></td>
      <td>Central Okanagan</td><td>British Columbia</td><td>Conservative</td></tr></tbody></table>'''
    got = ma.parse_member_list(html)
    assert [g["path"] for g in got] == ["mer2019q1/10010", "mer2019q1/10020"]
    assert got[0]["name"] == "Aboultaif, Ziad" and got[0]["caucus"] == "Conservative" and got[0]["province"] == "Alberta"


def test_report_codes_cover_the_known_archive_and_labels_follow_mp_expenses():
    assert ma.REPORT_CODES[(2019, 3)] == "mer2019q3-a" and ma.REPORT_CODES[(2020, 2)] == "mer2020q2-1023"
    assert ma.REPORT_CODES[(2021, 1)] == "mer2021q1-1041"        # fills Apr-Jun 2020, before the current site starts
    assert (2015, 2) not in ma.REPORT_CODES                      # not found; must not be guessed
    assert ma._quarter_label(2019, 1) == "2018-Q1" and ma._quarter_label(2019, 4) == "2019-Q4"


# ---- the view's differencing rule, mirrored here and cross-checked against live data when applied ----------------

def quarterly(rows, loaded_reports):
    """Mirror of parliament.v_mp_expenses_archive_quarterly. rows: {(mp, fy, fq): ytd_total}."""
    out = {}
    for (mp, fy, fq), ytd in rows.items():
        prev = rows.get((mp, fy, fq - 1))
        if fq == 1:
            out[(mp, fy, fq)] = ytd
        elif prev is not None:
            out[(mp, fy, fq)] = round(ytd - prev, 2)
        elif (fy, fq - 1) in loaded_reports:
            out[(mp, fy, fq)] = ytd                        # not in the previous report => not yet a member
    return out


def test_aboultaif_fy2019_ytd_differences_to_the_quarterly_figures():
    ytd = {(1, 2019, q): v for q, v in ((1, 85919.44), (2, 184491.60), (3, 283120.24), (4, 399495.59))}
    got = quarterly(ytd, {(2019, 1), (2019, 2), (2019, 3), (2019, 4)})
    assert [got[(1, 2019, q)] for q in (1, 2, 3, 4)] == [85919.44, 98572.16, 98628.64, 116375.35]


def test_a_missing_predecessor_report_is_omitted_not_guessed():
    got = quarterly({(1, 2015, 1): 100.0, (1, 2015, 3): 300.0}, {(2015, 1), (2015, 3)})   # FY2015 Q2 report absent
    assert (1, 2015, 3) not in got and got[(1, 2015, 1)] == 100.0


def test_a_member_newly_elected_mid_year_takes_their_whole_ytd():
    got = quarterly({(1, 2016, 1): 50.0, (2, 2016, 3): 40.0}, {(2016, 1), (2016, 2)})
    assert got[(2, 2016, 3)] == 40.0                         # report Q2 is loaded and does not list member 2


def test_the_migration_states_the_same_three_rules():
    sql = open(os.path.join(ROOT, "migrations", "097_mp_expenses_archive.sql"), encoding="utf-8").read()
    assert "a.ytd_total_cad       - COALESCE(p.ytd_total_cad, 0)" in sql
    assert "WHERE a.fq = 1" in sql and "p.id IS NOT NULL" in sql
    assert "r.fiscal_year = a.fiscal_year AND r.fq = a.fq - 1" in sql          # predecessor report loaded
    assert "'house_archive'" in sql and "e.source" in sql
    assert "ON CONFLICT (version) DO NOTHING" in sql


def test_pdf_extraction_matches_the_stored_text_fixture_when_pypdf_is_present():
    pypdf = pytest.importorskip("pypdf")      # parsing is covered above WITHOUT pypdf; this only guards extraction drift
    for name in ("mer2019q1_aboultaif", "mer2016q2_ablonczy"):
        data = open(os.path.join(FIX, name + ".pdf"), "rb").read()
        assert re.sub(r"\s+", " ", ma._pdf_text(data)) == re.sub(r"\s+", " ", _txt(name))


def test_quarter_end_follows_the_fiscal_calendar():
    assert ma.quarter_end(2019, 1) == date(2018, 6, 30) and ma.quarter_end(2019, 3) == date(2018, 12, 31)
    assert ma.quarter_end(2019, 4) == date(2019, 3, 31) and ma.quarter_end(2021, 1) == date(2020, 6, 30)


def test_riding_match_uses_overlap_so_a_member_who_left_mid_quarter_still_matches():
    idx = {ma._riding_key("Lethbridge"): [(date(2015, 10, 19), date(2025, 4, 28), 7)],
           ma._riding_key("Leeds—Grenville—Thousand Islands and Rideau Lakes"): [(date(2004, 6, 28), date(2018, 5, 2), 9)]}
    q1, q2 = ma.quarter_start(2019, 1), ma.quarter_end(2019, 1)             # Apr 1 .. Jun 30 2018
    assert ma.match_by_riding(idx, "Lethbridge", q1, q2) == 7
    assert ma.match_by_riding(idx, "leeds-grenville-thousand islands and rideau lakes", q1, q2) == 9   # died 2 May 2018
    assert ma.match_by_riding(idx, "Lethbridge", date(2009, 1, 1), date(2009, 3, 31)) is None          # nobody held it then
    assert ma.match_by_riding(idx, None, q1, q2) is None


def test_riding_match_refuses_when_two_people_overlap_instead_of_guessing():
    k = ma._riding_key("Somewhere")
    idx = {k: [(date(2010, 1, 1), date(2015, 5, 15), 1), (date(2015, 5, 16), None, 2)]}
    assert ma.match_by_riding(idx, "Somewhere", date(2015, 4, 1), date(2015, 6, 30)) is None           # handover inside the quarter
    assert ma.match_by_riding(idx, "Somewhere", date(2015, 7, 1), date(2015, 9, 30)) == 2


def test_quarter_start_follows_the_fiscal_calendar():
    assert ma.quarter_start(2019, 1) == date(2018, 4, 1) and ma.quarter_start(2019, 4) == date(2019, 1, 1)
