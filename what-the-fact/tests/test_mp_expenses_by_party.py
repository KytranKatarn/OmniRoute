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
