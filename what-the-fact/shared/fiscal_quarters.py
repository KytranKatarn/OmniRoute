"""Chronological ordering for the MP-expenses period labels.

``parliament.mp_expenses.period`` is written by ``ingest/parliament/mp_expenses._quarter_label``:
the number is the FISCAL quarter and the year is the CALENDAR year the quarter starts in.

    Q1 = Apr-Jun   Q2 = Jul-Sep   Q3 = Oct-Dec   (year = that calendar year)
    Q4 = Jan-Mar                                   (year = that calendar year, i.e. the END of the fiscal year)

So within one label year the real order is Q4, Q1, Q2, Q3 — Jan-Mar comes FIRST. Sorting the label as
text puts 2026-Q4 (Jan-Mar 2026) above 2026-Q1 (Apr-Jun 2026), and 2025-Q4 (Jan-Mar 2025) above
2025-Q3 (Oct-Dec 2025). Anything that asks for "the latest N quarters" with ``ORDER BY period DESC``
therefore shows them out of date order and can drop the wrong quarter at the LIMIT.

The expression below is plain ANSI (SUBSTR / CAST / CASE / LIKE) so it runs unchanged on Postgres and
SQLite — the test exercises it on SQLite. A value that is not ``YYYY-Qn`` sorts last instead of raising.
"""

CHRONO_KEY_SQL = (
    "(CASE WHEN period LIKE '____-Q_' "
    "THEN CAST(SUBSTR(period, 1, 4) AS INTEGER) * 10 "
    "+ CASE SUBSTR(period, 7, 1) WHEN '4' THEN 0 ELSE CAST(SUBSTR(period, 7, 1) AS INTEGER) END "
    "ELSE -1 END)"
)

# Newest first. ``period DESC`` is the tiebreak so malformed labels (key -1) still order deterministically.
CHRONO_DESC_SQL = f"{CHRONO_KEY_SQL} DESC, period DESC"


def period_start(period: str):
    """First calendar day of a ``YYYY-Qn`` expense period (n = FISCAL quarter), or None if malformed.

    Q1 -> Apr 1, Q2 -> Jul 1, Q3 -> Oct 1, Q4 -> Jan 1 (the year is the calendar year the quarter starts in).
    Mirrors the SQL in migration 095 (parliament.v_mp_expenses_by_party); a live check compares the two.
    """
    import re
    from datetime import date
    m = re.fullmatch(r"(\d{4})-Q([1-4])", period or "")
    if not m:
        return None
    return date(int(m.group(1)), {"1": 4, "2": 7, "3": 10, "4": 1}[m.group(2)], 1)
