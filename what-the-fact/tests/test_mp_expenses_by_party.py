"""The period -> date mapping used to attribute an expense to a party, and the migration's rules."""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.fiscal_quarters import period_start  # noqa: E402

SQL = open(os.path.join(os.path.dirname(__file__), "..", "migrations", "095_mp_expenses_by_party.sql"), encoding="utf-8").read()


def test_period_start_follows_the_fiscal_quarter_convention():
    assert period_start("2025-Q1") == date(2025, 4, 1)     # Apr-Jun
    assert period_start("2025-Q2") == date(2025, 7, 1)
    assert period_start("2025-Q3") == date(2025, 10, 1)
    assert period_start("2025-Q4") == date(2025, 1, 1)     # Jan-Mar of the SAME calendar year
    assert period_start("2026-Q4") == date(2026, 1, 1)


def test_malformed_periods_return_none_not_raise():
    for bad in ("", None, "2025", "2025-Q5", "25-Q1", "2025-q1"):
        assert period_start(bad) is None


def test_the_sql_encodes_the_same_month_mapping_as_python():
    m = re.search(r"CASE split_part\(e\.period, '-Q', 2\) WHEN '1' THEN (\d+) WHEN '2' THEN (\d+) WHEN '3' THEN (\d+) ELSE (\d+) END", SQL)
    assert m, "month mapping not found in the migration"
    assert tuple(int(x) for x in m.groups()) == tuple(period_start(f"2025-Q{q}").month for q in (1, 2, 3, 4))


def test_the_migration_keeps_its_promises():
    assert "COALESCE(t.party, 'Unattributed')" in SQL          # nothing dropped, totals reconcile
    assert "party_changed_in_quarter" in SQL                    # a split quarter is visible
    assert "s.q_start + 45" in SQL or "(s.q_start + 45)" in SQL # midpoint rule
    assert "NOT sitting" in SQL                                  # retired MPs are counted and shown separately
    assert "ON CONFLICT (version) DO NOTHING" in SQL


SQL96 = open(os.path.join(os.path.dirname(__file__), "..", "migrations", "096_mp_expenses_wind_down.sql"), encoding="utf-8").read()


def test_wind_down_costs_fall_back_to_the_last_party_and_are_labelled():
    assert "'wind_down'" in SQL96 and "'in_term'" in SQL96 and "'none'" in SQL96
    # a covering stint must outrank a merely-earlier one, and the latest earlier stint wins among those
    assert "ORDER BY (t0.end_date IS NULL OR t0.end_date >= (s.q_start + 45)) DESC, t0.start_date DESC" in SQL96
    assert "t0.start_date <= (s.q_start + 45)" in SQL96


def test_096_only_appends_columns_so_095_consumers_keep_working():
    # inspect ONLY the first view's SELECT list (the later `) AS q_start` lateral alias must not count)
    start = SQL96.index("CREATE OR REPLACE VIEW parliament.v_mp_expenses_by_party")
    sel = SQL96[start:SQL96.index("FROM parliament.mp_expenses e", start)]
    sel = "\n".join(l.split("--")[0] for l in sel.splitlines())
    names = []
    for part in re.split(r",\s*(?![^()]*\))", sel[sel.index("SELECT") + 6:]):
        part = part.strip()
        m = re.search(r"\bAS\s+(\w+)\s*$", part, re.S)
        names.append(m.group(1) if m else part.split(".")[-1].strip())
    cols95 = ["expense_id", "mp_id", "mp_name", "sitting", "period", "q_start", "party",
              "party_changed_in_quarter", "travel_cad", "hospitality_cad", "contracts_cad", "salaries_cad", "total_cad"]
    assert names[:len(cols95)] == cols95, names           # 095's columns, same order, same positions
    assert names[len(cols95):] == ["attribution"]          # the only addition, appended LAST
    assert "ON CONFLICT (version) DO NOTHING" in SQL96
