"""Itemized Senate travel: parse, reconcile against the Senate's own grand total, classify, store safely.

Why this exists (2026-10-06): a National Post / CTF claim — "65 senators spent $1,850,420 on international
travel between 2023-01-16 and 2026-03-17" — could not be checked, because we held one quarterly travel TOTAL
per senator (domestic + international + designated travellers together). The Senate publishes the itemized
trips behind each total; this ingests them. The fixture below is the real shape of that page
(Senator Adler, Apr-Jun 2026, grand total $18,831.54 — the same figure as the summary link).
"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import senate_travel as st  # noqa: E402
from shared.travel_places import classify_itinerary  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _tr(*cells):
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


HEADER = ("<tr>" + "".join(f"<th>{h}</th>" for h in [
    "Traveller", "Start Date", "End Date", "Itinerary", "Purpose", "Air Bus Train",
    "Other Ground Transp.", "Per Diems", "Accom.", "Other", "Total Amount (before tax)"]) + "</tr>")

W = "Winnipeg - Ottawa - Winnipeg"
DETAIL = "<table>" + HEADER + "".join([
    _tr("Adler, Charles S.", "2026-04-14", "2026-04-16", W, "Senate sitting", "$2,273.68", "$147.20", "$270.77", "$0.00", "$0.00", "$2,691.65"),
    _tr("", "2026-04-21", "2026-04-24", W, "Senate sitting", "$2,273.68", "$139.85", "$270.77", "$0.00", "$0.00", "$2,684.30"),
    _tr("", "2026-04-28", "2026-04-30", W, "Senate sitting", "$2,273.68", "$145.21", "$270.77", "$0.00", "$0.00", "$2,689.66"),
    _tr("", "2026-05-04", "2026-05-08", W, "Senate sitting", "$1,809.17", "$143.64", "$156.73", "$0.00", "$0.00", "$2,109.54"),
    _tr("", "2026-05-25", "2026-05-28", W, "Senate sitting", "$2,273.68", "$134.68", "$244.31", "$0.00", "$0.00", "$2,652.67"),
    _tr("", "2026-06-01", "2026-06-04", W, "Senate sitting", "$2,273.68", "$142.62", "$244.31", "$0.00", "$0.00", "$2,660.61"),
    _tr("Sub-total", "$15,488.43"),
    _tr("Designated Traveller", "2026-04-21", "2026-04-24", "Vancouver - Ottawa - Vancouver", "To join / accompany senator",
        "$3,296.83", "$0.00", "$46.28", "$0.00", "$0.00", "$3,343.11"),
    _tr("Sub-total", "$3,343.11"),
    _tr("Grand Total", "$18,831.54"),
]) + "</table>"


# ------------------------------------------------------------------------------------------ parsing

def test_parses_every_leg_and_the_grand_total():
    p = st.parse_travel_detail(DETAIL)
    assert len(p["trips"]) == 7 and p["bad_rows"] == 0
    assert p["grand_total"] == Decimal("18831.54")
    first = p["trips"][0]
    assert first["trip_start"].isoformat() == "2026-04-14" and first["trip_end"].isoformat() == "2026-04-16"
    assert first["itinerary"] == W and first["purpose"] == "Senate sitting"
    assert first["air_bus_train_cad"] == Decimal("2273.68") and first["total_cad"] == Decimal("2691.65")


def test_blank_traveller_cell_continues_the_previous_traveller():
    p = st.parse_travel_detail(DETAIL)
    assert {t["traveller_name"] for t in p["trips"][:6]} == {"Adler, Charles S."}
    assert [t["traveller_kind"] for t in p["trips"][:6]] == ["senator"] * 6


def test_designated_traveller_is_kept_separate_not_folded_into_the_senator():
    last = st.parse_travel_detail(DETAIL)["trips"][-1]
    assert last["traveller_kind"] == "designated" and last["total_cad"] == Decimal("3343.11")


def test_subtotal_and_header_rows_are_not_trips():
    p = st.parse_travel_detail(DETAIL)
    assert all(t["trip_start"] is not None for t in p["trips"])
    assert not any("total" in (t["traveller_name"] or "").lower() for t in p["trips"])


# --------------------------------------------------------------------------------------- reconciling

def test_reconciles_against_the_grand_total_and_the_summary_amount():
    r = st.reconcile(st.parse_travel_detail(DETAIL), Decimal("18831.54"))
    assert r["reconciled"] and r["rows_total"] == Decimal("18831.54") and r["row_count"] == 7


def test_a_dropped_row_breaks_reconciliation():
    broken = DETAIL.replace(_tr("", "2026-05-04", "2026-05-08", W, "Senate sitting", "$1,809.17", "$143.64", "$156.73", "$0.00", "$0.00", "$2,109.54"), "")
    r = st.reconcile(st.parse_travel_detail(broken), Decimal("18831.54"))
    assert not r["reconciled"] and r["rows_total"] == Decimal("16722.00")


def test_summary_mismatch_breaks_reconciliation_even_when_rows_match_the_grand_total():
    assert not st.reconcile(st.parse_travel_detail(DETAIL), Decimal("18000.00"))["reconciled"]


def test_an_unparseable_row_is_counted_and_fails_reconciliation_not_silently_dropped():
    bad = DETAIL.replace("2026-04-21</td><td>2026-04-24</td><td>Winnipeg", "not-a-date</td><td>2026-04-24</td><td>Winnipeg", 1)
    p = st.parse_travel_detail(bad)
    assert p["bad_rows"] == 1 and not st.reconcile(p, Decimal("18831.54"))["reconciled"]


def test_the_bad_row_guard_stands_on_its_own_when_there_is_no_grand_total_or_summary_to_compare():
    """Without this the bad-row check is masked by the grand-total mismatch it usually causes."""
    p = st.parse_travel_detail(DETAIL.replace("2026-04-21</td><td>2026-04-24</td><td>Winnipeg", "bad</td><td>2026-04-24</td><td>Winnipeg", 1))
    p["grand_total"] = None
    assert p["bad_rows"] == 1
    assert not st.reconcile(p, None)["reconciled"]


def test_penny_rounding_tolerance():
    p = st.parse_travel_detail(DETAIL)
    p["grand_total"] = Decimal("18831.55")
    assert st.reconcile(p, None)["reconciled"]
    p["grand_total"] = Decimal("18832.00")
    assert not st.reconcile(p, None)["reconciled"]


# ------------------------------------------------------------------------------- summary extraction

SUMMARY = (
    "<table>"
    '<tr><td>Adler, Charles S.</td><td>x</td><td>x</td><td>$1.00</td><td>$2.00</td><td>$3.00</td>'
    '<td><a href="/en/proactive/summary/details/#?Member=Senators&amp;Expense=Travel&amp;MemberId=235185&amp;Year=2026&amp;Quarter=2" class="proactive-table__amount-link">$18,831.54</a></td><td>N/A</td></tr>'
    '<tr><td>Dasko, Donna</td><td>x</td><td>x</td><td>$1.00</td><td>$2.00</td><td>$3.00</td>'
    '<td><a href="/en/proactive/summary/details/#?Member=Senators&amp;Expense=Travel&amp;MemberId=218927&amp;Year=2026&amp;Quarter=2">$9,000.00</a></td><td>N/A</td></tr>'
    '<tr><td>NoTravel, Nobody</td><td>x</td><td>x</td><td>$1</td><td>$2</td><td>$3</td><td>$0.00</td><td>N/A</td></tr>'
    "</table>")


def test_summary_rows_pair_names_with_member_ids_and_skip_zero_travel_rows():
    assert st.summary_names_to_member_ids(SUMMARY) == {"Adler, Charles S.": 235185, "Dasko, Donna": 218927}
    assert st.travel_links(SUMMARY)[0] == (235185, 2026, 2, "$18,831.54")


# ---------------------------------------------------------------------------------------- classifier

@pytest.mark.parametrize("itinerary,expected", [
    ("Winnipeg - Ottawa - Winnipeg", False),
    ("Ottawa - Strasbourg - Ottawa", True),
    ("Montréal - Ottawa - Montréal", False),
    ("Ottawa - Washington, DC - Ottawa", True),
    ("Halifax - Brussels - Halifax", True),
    ("Ottawa - Xyzville - Ottawa", None),          # unrecognised -> review, NEVER domestic
    ("Ottawa - London - Ottawa", None),             # ambiguous (London ON / UK)
    ("Ottawa - Kingston - Ottawa", None),           # ambiguous (Kingston ON / Jamaica)
    ("Toronto - Ottawa - Strasbourg - Ottawa", True),
    ("Xyzville - Strasbourg", True),                # a known foreign leg wins over an unknown one
    ("", None),
])
def test_international_is_three_valued_and_never_guessed(itinerary, expected):
    assert classify_itinerary(itinerary)[0] is expected


def test_basis_says_why():
    assert classify_itinerary("Ottawa - Strasbourg - Ottawa")[1] == "foreign:Strasbourg"
    assert classify_itinerary("Ottawa - Xyzville - Ottawa")[1] == "unreviewed:Xyzville"
    assert "(ambiguous)" in classify_itinerary("Ottawa - London - Ottawa")[1]
    assert classify_itinerary("Winnipeg - Ottawa - Winnipeg")[1] == "canadian"


# ------------------------------------------------------------------------------------------ storing

class _Conn:
    def __init__(self, log):
        self.log = log

    def execute(self, stmt, params=None):
        self.log.append((" ".join(str(stmt).split())[:60], params))


class _Engine:
    def __init__(self):
        self.log, self.begins = [], 0

    def begin(self):
        engine = self

        class _Ctx:
            def __enter__(self_inner):
                engine.begins += 1
                return _Conn(engine.log)

            def __exit__(self_inner, *a):
                return False
        return _Ctx()


def test_store_replaces_the_quarter_as_a_set_in_one_transaction_and_records_the_check():
    eng = _Engine()
    parsed = st.parse_travel_detail(DETAIL)
    n = st._store(eng, 7, "2026-Q2", parsed, st.reconcile(parsed, Decimal("18831.54")), "https://x")
    assert n == 7 and eng.begins == 1
    stmts = [s for s, _ in eng.log]
    assert stmts[0].startswith("DELETE FROM parliament.senate_travel_trips")      # delete FIRST
    assert sum(s.startswith("INSERT INTO parliament.senate_travel_trips") for s in stmts) == 7
    assert stmts[-1].startswith("INSERT INTO parliament.senate_travel_checks")
    inserted = [p for s, p in eng.log if s.startswith("INSERT INTO parliament.senate_travel_trips")]
    assert [p["seq"] for p in inserted] == list(range(1, 8))
    assert all(p["intl"] is False and p["basis"] == "canadian" for p in inserted)


def test_a_failed_detail_fetch_never_touches_existing_rows(monkeypatch):
    eng = _Engine()
    monkeypatch.setattr(st.se, "_fetch_fragment", lambda *a: SUMMARY)
    monkeypatch.setattr(st.se, "_available_quarters", lambda f: [(2026, 2)])
    monkeypatch.setattr(st.se, "_load_senator_index", lambda e: ({"adler": [("charles s", 7)], "dasko": [("donna", 8)]}, {}))
    monkeypatch.setattr(st.time, "sleep", lambda s: None)

    def boom(*a):
        raise OSError("sencanada.ca unreachable")
    monkeypatch.setattr(st, "_fetch_detail", boom)
    res = st._sync(eng, 1, None)
    assert eng.begins == 0 and res["trips"] == 0 and res["fetch_failed"] == 2   # nothing deleted, nothing written


def test_sync_stores_and_flags_a_quarter_that_does_not_reconcile(monkeypatch):
    eng = _Engine()
    monkeypatch.setattr(st.se, "_fetch_fragment", lambda *a: SUMMARY)
    monkeypatch.setattr(st.se, "_available_quarters", lambda f: [(2026, 2)])
    monkeypatch.setattr(st.se, "_load_senator_index", lambda e: ({"adler": [("charles s", 7)], "dasko": [("donna", 8)]}, {}))
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    monkeypatch.setattr(st, "_fetch_detail", lambda m, y, q: DETAIL)   # Dasko's summary says $9,000 but rows total 18,831.54
    res = st._sync(eng, 1, None)
    assert res["senators"] == 2 and res["trips"] == 14
    assert res["unreconciled"] == ["Dasko, Donna 2026-Q2"]


def test_empty_run_is_an_error_row_not_a_quiet_success(monkeypatch):
    eng = _Engine()
    monkeypatch.setattr(st, "_sync", lambda *a: {"trips": 0, "senators": 0})
    res = st.run_senate_travel_sync(eng)
    assert "error" in res
    logged = [p for s, p in eng.log if s.startswith("INSERT INTO parliament.ingest_log")]
    assert logged and logged[0]["t"] == "senate_travel" and "e" in logged[0]


def test_success_logs_a_heartbeat(monkeypatch):
    eng = _Engine()
    monkeypatch.setattr(st, "_sync", lambda *a: {"trips": 14, "senators": 2})
    st.run_senate_travel_sync(eng)
    logged = [p for s, p in eng.log if s.startswith("INSERT INTO parliament.ingest_log")]
    assert logged[0] == {"t": "senate_travel", "f": 2, "u": 14}


# -------------------------------------------------------------------------------- wiring + migration

def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_migration_ends_with_its_ledger_line_and_grants_wtfuser():
    sql = _read("migrations/090_senate_travel_trips.sql")
    assert "CREATE TABLE IF NOT EXISTS parliament.senate_travel_trips" in sql
    assert "CREATE TABLE IF NOT EXISTS parliament.senate_travel_checks" in sql
    assert "GRANT ALL ON parliament.senate_travel_trips" in sql
    assert "INSERT INTO public.schema_migrations" in sql and "'090'" in sql and "ON CONFLICT (version) DO NOTHING" in sql
    assert "CHECK (traveller_kind IN ('senator', 'designated', 'other'))" in sql
    assert "is_international  boolean," in sql  # nullable on purpose


def test_drift_guard_watches_it_but_does_not_require_it_before_the_first_run():
    from ingest.parliament import drift_guard
    assert "senate_travel" in drift_guard._MAX_AGE_DAYS
    assert "senate_travel" not in drift_guard._REQUIRED_TASKS


def test_weekly_run_calls_it_after_the_senator_expenses_sync():
    run = _read("ingest/run.py")
    assert run.index("run_senator_expenses_sync(engine)") < run.index("run_senate_travel_sync(engine)")


# ------------------------------------------------------------------ classifier extension (2026-10-06 backfill)

@pytest.mark.parametrize("itinerary, expected", [
    ("Ottawa - Jackson, USA - Halifax", True),                  # a country tail beats an ambiguous name
    ("Toronto – London, England – Belfast, Northern Ireland – London, England – Toronto", True),
    ("Charlottetown, PE - Siem Reap, KH - Charlottetown, PE", True),
    ("Ottawa - Sydney, NS - Ottawa", False),                    # a Canadian province tail RESOLVES an ambiguous name
    ("Ottawa - Victoria, BC - Ottawa", False),
    ("Ottawa - Sydney - Ottawa", None),                         # no tail: still never auto-classified
    ("Halifax - Boise, USA - Halifax", True),
    ("Ottawa - Bozeman, MT, USA - Ottawa", True),
    ("Whitehorse - Haines Junction - Whitehorse - Carcross - Skagway - Whitehorse", True),
    ("Cheticamp - Personal - Ottawa - Montreal - Ottawa - Cheticamp", False),   # "Personal" is not a place
    ("Personal", None),                                         # nothing but a marker: nothing to classify
    ("Ottawa -", False),                                        # trailing separator artefact
    ("Halifax - Fergus - Halifax", False),                      # small Canadian town from the real backfill
    ("Ottawa - Xyzville - Ottawa", None),                       # still unrecognised -> review
    ("Saskatoon - Muenster - Saskatoon", None),                 # exists in SK AND Germany, no tail
])
def test_extended_classifier(itinerary, expected):
    assert classify_itinerary(itinerary)[0] is expected


def test_extension_adds_no_place_to_two_lists():
    """A name in CANADIAN_TOWNS that is also AMBIGUOUS or foreign would be classified by whichever rule runs first."""
    from shared import travel_places as tp
    assert not (tp.CANADIAN_TOWNS & tp.AMBIGUOUS)
    assert not (tp.CANADIAN_TOWNS & (tp.FOREIGN | tp.FOREIGN_EXTRA))
    assert not (tp.FOREIGN_EXTRA & tp.AMBIGUOUS)


def test_reclassify_updates_only_what_changed():
    class _R:
        def fetchall(self):
            return [(1, "Halifax - Fergus - Halifax", None, "unreviewed:Fergus"),            # now False
                    (2, "Ottawa - Strasbourg - Ottawa", True, "foreign:Strasbourg"),         # unchanged
                    (3, "Ottawa - Jackson, USA - Halifax", None, "unreviewed:Jackson")]      # now True
    class _C:
        def __init__(self): self.updates = []
        def execute(self, sql, params=None):
            if params: self.updates.append(params)
            return _R()
    class _E:
        def __init__(self): self.c = _C()
        def begin(self):
            import contextlib
            return contextlib.nullcontext(self.c)
    e = _E()
    out = st.reclassify(e)
    assert out == {"None->False": 1, "None->True": 1}
    assert sorted(u["id"] for u in e.c.updates) == [1, 3]
