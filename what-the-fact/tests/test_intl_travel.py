"""intl_travel: committee + IIA report parsing, overlap with the senator's own Travel rows, and the no-double-count
contract. Fixtures are REAL report text (pypdf output) from the 2026-10-06 backfill, not hand-written samples."""
import contextlib
import datetime as dt
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import intl_travel as it  # noqa: E402

FX = os.path.join(os.path.dirname(__file__), "fixtures", "intl_travel")
D = Decimal


def fx(name: str) -> str:
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------------------------- committee reports

@pytest.mark.parametrize("fixture, label, total, foreign", [
    ("committee_berlin.txt", "Berlin", "48988.60", True),
    ("committee_rome.txt", "Rome", "44515.61", True),
    ("committee_colorado.txt", "Colorado Springs", "34658.03", True),        # foreign only from the PDF text
    ("committee_washington.txt", "Washington D.C", "32033.91", True),
    ("committee_london_cancelled.txt", "London", "1790.00", True),           # "London" is ambiguous: text decides
    ("committee_guelph_domestic.txt", "Guelph, ON", "12767.74", False),
    ("committee_newfoundland_spaced.txt", "Newfoundland", "79529.99", False),  # total printed as "$26, 446.15"
])
def test_committee_report_total_and_foreignness(fixture, label, total, foreign):
    r = it.parse_committee_report(fx(fixture), label)
    assert r["total"] == D(total)
    assert r["is_foreign"] is foreign


def test_a_grand_total_split_across_lines_is_repaired():
    """Oslo's PDF breaks the figure: "$3,\\n725.43". Reading it as $3 would silently under-count the trip."""
    assert it.parse_committee_report(fx("committee_oslo_split_total.txt"), "Oslo")["total"] == D("13322.53")


def test_committee_dates():
    r = it.parse_committee_report(fx("committee_berlin.txt"), "Berlin")
    assert (r["start"], r["end"]) == (dt.date(2023, 9, 14), dt.date(2023, 9, 16))


def test_an_ambiguous_day_month_date_is_left_unknown_not_guessed():
    """Colorado Springs prints "8/2/2023 – 10/2/2023": 8 Feb or Aug 2 cannot be told apart."""
    r = it.parse_committee_report(fx("committee_colorado.txt"), "Colorado Springs")
    assert r["start"] is None and r["end"] is None


def test_a_cancelled_trip_is_flagged():
    assert it.parse_committee_report(fx("committee_london_cancelled.txt"), "London")["cancelled"] is True
    assert it.parse_committee_report(fx("committee_berlin.txt"), "Berlin")["cancelled"] is False


def test_a_cancellation_fee_footnote_is_not_a_cancelled_committee_trip():
    """Same trap as the IIA footnote ("Travel cancellation expenses" on a trip that ran), committee parser."""
    assert it.parse_committee_report(fx("iia_new_format.txt"), "Washington D.C")["cancelled"] is False


def test_unreadable_report_has_no_total_rather_than_zero():
    assert it.parse_committee_report("not a report", "Berlin")["total"] is None


def test_committee_links_keep_travel_and_drop_hospitality():
    frag = ('<a href="/ProActiveDisclosure/Committees/en/2023/4/AEFA-Travel-Berlin-E.pdf">x</a>'
            '<a href="/ProActiveDisclosure/Committees/en/2023/4/AEFA-Hosp-Committee Meeting-E.pdf">y</a>'
            '<a href="/ProActiveDisclosure/Committees/en/2023/4/SOCI-Travel-N.B._and_P.E.I.-E.pdf">z</a>')
    assert it.committee_links(frag) == [
        ("/ProActiveDisclosure/Committees/en/2023/4/AEFA-Travel-Berlin-E.pdf", "AEFA", "Berlin"),
        ("/ProActiveDisclosure/Committees/en/2023/4/SOCI-Travel-N.B._and_P.E.I.-E.pdf", "SOCI", "N.B. and P.E.I."),
    ]


# ---------------------------------------------------------------------------------------------- IIA reports

def test_iia_new_layout():
    r = it.parse_iia_report(fx("iia_new_format.txt"))
    assert r["total"] == D("8393.79")
    assert r["senators"] == [("Andrew Cardozo", D("60.00")), ("Suze Youance", D("1367.05"))]   # MPs/staff excluded


def test_iia_old_layout_takes_the_first_expenditure_total_and_ignores_mps():
    r = it.parse_iia_report(fx("iia_old_format.txt"))
    assert r["total"] == D("75005.60")        # a LATER "Total Cost per Expenditure Type" re-totals the individuals
    assert [n for n, _ in r["senators"]] == ["René Cormier", "Leo Housakos"]
    assert dict(r["senators"])["Leo Housakos"] == D("5252.14")


@pytest.mark.parametrize("fixture, total", [
    ("iia_fiscal_year_rows.txt", "57291.40"),       # one row per fiscal year; the delegation is the "Total" row
    ("iia_multi_association.txt", "37384.67"),      # one row per association; the delegation is the "Total" row
    ("iia_spaced_numbers.txt", "38707.66"),         # participant count on its own line; "2, 565.73" style spacing
    ("iia_footnoted_names.txt", "61400.31"),
])
def test_iia_total_across_the_layouts_seen_in_the_backfill(fixture, total):
    """194 real reports used at least five layouts; the first parser read 30 of them as 'no total'."""
    assert it.parse_iia_report(fx(fixture))["total"] == D(total)


def test_senator_lines_survive_footnote_markers_and_spaced_numbers():
    r = it.parse_iia_report(fx("iia_footnoted_names.txt"))
    names = dict(r["senators"])
    assert names["Brian Francis"] == D("660.00")            # "Hon. Brian Francis, Senator1, 2  660.00 0.00 0.00 660.00"
    assert names["Claude Carignan"] == D("9130.34")
    sp = dict(it.parse_iia_report(fx("iia_spaced_numbers.txt"))["senators"])
    assert sp["Rosemary Moodie"] == D("5862.92")
    assert not any("M.P." in n or "Staff" in n for n in names)          # MPs and staff never counted as senators


def test_a_cancellation_footnote_does_not_cancel_the_delegation():
    """The CPAM Washington report carries "Travel cancellation expenses" for one person on a trip that ran."""
    r = it.parse_iia_report(fx("iia_new_format.txt"))
    assert r["cancelled"] is False
    assert r["covered_elsewhere"] is True       # per diems "covered by another parliamentary budget"


def test_iia_index_parses_english_french_and_missing_report_links():
    items = it.parse_iia_index(fx("iia_index_snippet.html"))
    by_acr = {i["acr"]: i for i in items}
    assert by_acr["CPAM"]["start"] == dt.date(2026, 3, 17) and by_acr["CPAM"]["url"].endswith("/14102653")
    assert by_acr["CAPF"]["start"] == dt.date(2025, 1, 21)              # "21 - 24 janvier 2025"
    assert by_acr["CACN"]["start"] == dt.date(2022, 11, 20)             # "Novembre 20 - 25, 2022"
    assert by_acr["CAPF"]["url"] == ""                                  # listed with no report yet: kept, not dropped


@pytest.mark.parametrize("raw, expected", [
    ("March 17 - 19, 2026", dt.date(2026, 3, 17)),
    ("Sept 14 - 16, 2022", dt.date(2022, 9, 14)),
    ("October 18 , 2024", dt.date(2024, 10, 18)),
    ("April 19 -  23 , 2022", dt.date(2022, 4, 19)),
    ("November 28 - December 2, 2023", dt.date(2023, 11, 28)),
    ("21 - 24 janvier 2025", dt.date(2025, 1, 21)),
    ("someday", None),
])
def test_event_dates(raw, expected):
    assert it.parse_event_date(raw) == expected


# ------------------------------------------------------------------------------------------ senator names

def test_senator_display_names_resolve_across_given_family_splits():
    fam = {"cormier": [("rene", 1)], "al zaibak": [("mohammad", 2)], "smith": [("ann", 3), ("bob", 4)]}
    full = {"rene cormier": 1}
    assert it.match_senator_display("René Cormier", fam, full) == 1          # accent folds via the roster's own norm
    assert it.match_senator_display("Mohammad Al Zaibak", fam, full) == 2    # multi-word family name
    assert it.match_senator_display("Nobody Known", fam, full) is None


# ----------------------------------------------------------------------------------------------- overlap

class _Conn:
    def __init__(self, rows=None):
        self.rows, self.calls, self.inserts = rows or [], [], []

    def execute(self, sql, params=None):
        s = str(sql)
        self.calls.append((s, params))
        if "INSERT INTO parliament.intl_travel_senators" in s:
            self.inserts.append(params)
        class R:
            def __init__(r, rows): r.rows = rows
            def fetchall(r): return r.rows
            def scalar(r): return 99
        return R(self.rows if "senate_travel_trips" in s else [])


def test_find_overlap_uses_the_senator_id_and_a_date_window_not_a_name():
    c = _Conn([(7, D("6010.86")), (8, D("100.00"))])
    ids, cad = it.find_overlap(c, 12, dt.date(2023, 4, 3))
    assert ids == [7, 8] and cad == D("6110.86")
    sql, params = c.calls[0]
    assert "senator_id = :s" in sql and "traveller_kind = 'senator'" in sql and "is_international IS NOT FALSE" in sql
    assert params["s"] == 12
    assert params["a"] == dt.date(2023, 3, 30) and params["b"] == dt.date(2023, 4, 15)


class _Engine:
    def __init__(self, conn): self.conn = conn
    def begin(self): return contextlib.nullcontext(self.conn)


def _ev(start):
    return {"source": "iia", "source_ref": "1", "body": "CANA", "title": "t", "destination": "Paris, France",
            "event_start": start, "event_end": None, "report_period": None, "is_foreign": True,
            "delegation_total_cad": D("100"), "senator_total_cad": D("60"), "n_senators": 3, "cancelled": False,
            "source_url": "u"}


def test_each_senator_line_is_classified_in_not_in_or_unmatched():
    class Sel(_Conn):  # senator 1 has a leg in the window, senator 2 does not, senator None did not resolve
        def execute(self, sql, params=None):
            if "FROM parliament.senate_travel_trips" in str(sql):
                self.calls.append((str(sql), params))
                rows = [(5, D("500.00"))] if params["s"] == 1 else []
                return type("R", (), {"fetchall": lambda s: rows})()
            return super().execute(sql, params)
    c = Sel()
    it._store_event(_Engine(c), _ev(dt.date(2023, 4, 3)), [
        {"name": "A", "amount": D("10"), "senator_id": 1},
        {"name": "B", "amount": D("20"), "senator_id": 2},
        {"name": "C", "amount": D("30"), "senator_id": None}])
    assert [(i["n"], i["o"]) for i in c.inserts] == [
        ("A", "in_expense_travel"), ("B", "not_in_expense_travel"), ("C", "unmatched_senator")]
    assert c.inserts[0]["ids"] == [5] and c.inserts[0]["oc"] == D("500.00")


def test_an_undated_event_never_claims_a_senator_is_new_spending():
    """No start date -> no window -> cannot prove it is absent from the senator's own Travel: unmatched, not additive."""
    c = _Conn()
    it._store_event(_Engine(c), _ev(None), [{"name": "A", "amount": D("10"), "senator_id": 1}])
    assert c.inserts[0]["o"] == "unmatched_senator"


def test_the_by_year_view_never_adds_overlapping_lines_to_the_total():
    """In-expense IIA lines are shown separately; ONLY not_in_expense feeds the additive component."""
    sql = open(os.path.join(os.path.dirname(__file__), "..", "migrations", "091_intl_travel.sql"), encoding="utf-8").read()
    add = sql.split("SELECT extract(year FROM e.event_start)::int, 'iia_senators_not_in_expenses'")[1].split("UNION ALL")[0]
    assert "s.overlap = 'not_in_expense_travel'" in add
    assert "unmatched_senator" not in add and "= 'in_expense_travel'" not in add    # unmatched is its own component
    shown = sql.split("SELECT extract(year FROM e.event_start)::int, 'iia_senators_in_expenses'")[1]
    assert "s.overlap = 'in_expense_travel'" in shown      # visible, but its own component — never summed in


# ----------------------------------------------------------------------------------------------- misc

def test_quarters_since():
    assert it._quarters_since(dt.date(2025, 11, 20), dt.date(2026, 2, 3)) == [(2025, 4), (2026, 1)]
    assert it._quarters_since(dt.date(2026, 2, 1), dt.date(2026, 2, 3)) == [(2026, 1)]


def test_an_empty_run_is_an_error_but_no_new_reports_is_not(monkeypatch):
    logged = []

    class E:
        def begin(self):
            class C:
                def execute(s, sql, p=None): logged.append(p)
            return contextlib.nullcontext(C())
    monkeypatch.setattr(it, "_sync", lambda *a, **k: {"committee_pages": 0, "iia_listed": 0})
    assert it.run_intl_travel_sync(E())["error"]
    monkeypatch.setattr(it, "_sync", lambda *a, **k: {"committee_pages": 3, "iia_listed": 200, "iia_events": 0,
                                                       "committee_events": 0})
    assert "error" not in it.run_intl_travel_sync(E())
