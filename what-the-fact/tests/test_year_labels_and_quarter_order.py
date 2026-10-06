"""Page labels name the span of their data from the data, and "latest quarter" is chronological.

2026-10-06 review of the WTF pages for 2026/2027 found:
  * /crtc, /ethics and /rates carried literal year ranges in their copy ("2024–2026", "2015–2026", "2000–2026") —
    still saying 2026 in 2027. They now render `year_span`, computed from the rows.
  * /cost's data-coverage row took MIN/MAX of the quarter LABEL text, so the latest MP quarter showed as 2026-Q4
    (Jan-Mar 2026) when it is 2026-Q1 (Apr-Jun 2026) — labels are "<calendar year>-Q<fiscal quarter>", Q4 = Jan-Mar.
  * a minister's current department was picked with ORDER BY period DESC: the same text-order trap.
"""
import os
import re
import sys

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import cost  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------------------------------------ year span

def test_year_span_from_the_data():
    from consumer.routes import _year_span
    assert _year_span([2024, 2026, 2025]) == "2024–2026"
    assert _year_span([2026, 2026]) == "2026"
    assert _year_span([None, 2019, None]) == "2019"
    assert _year_span([]) == "" and _year_span([None]) == ""
    assert _year_span(["2015", 2027]) == "2015–2027"      # a string year from a driver still works


@pytest.mark.parametrize("template", ["crtc.html", "ethics.html", "rates.html"])
def test_no_literal_year_range_is_left_in_the_copy(template):
    src = _read("consumer", "templates", template)
    assert not re.search(r"\b20\d\d\s*[–-]\s*20\d\d\b", src), f"{template} still hardcodes a year range"
    assert "year_span" in src


def test_every_page_route_passes_year_span():
    src = _read("consumer", "routes.py")
    for fn in ("crtc_decisions", "ethics_rulings", "boc_rates"):
        body = src.split(f"def {fn}(")[1].split("\n@bp.")[0]
        assert "year_span=" in body, f"{fn} does not pass year_span"


# ---------------------------------------------------------------------------- chronological coverage (sqlite)

@pytest.fixture
def conn():
    eng = create_engine("sqlite://")
    with eng.connect() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("CREATE TABLE parliament.mp_expenses (period TEXT)"))
        c.execute(text("CREATE TABLE parliament.minister_travel (mp_id INT, period TEXT, owner_org TEXT)"))
        c.execute(text("CREATE TABLE parliament.senator_expenses (period TEXT)"))
        yield c


def test_mp_coverage_reports_the_chronologically_latest_quarter_not_the_text_max(conn):
    for p in ("2020-Q2", "2025-Q3", "2025-Q4", "2026-Q4", "2026-Q1"):     # 2026-Q4 = Jan-Mar, 2026-Q1 = Apr-Jun
        conn.execute(text("INSERT INTO parliament.mp_expenses VALUES (:p)"), {"p": p})
    cov = cost.series_coverage(conn, "parliament.mp_expenses")
    assert cov == {"rows": 5, "first": "2020-Q2", "last": "2026-Q1"}
    assert conn.execute(text("SELECT MAX(period) FROM parliament.mp_expenses")).scalar() == "2026-Q4"   # the old, wrong answer


def test_senator_coverage_keeps_plain_text_order_because_its_labels_are_calendar_quarters(conn):
    for p in ("2021-Q2", "2026-Q1", "2026-Q2"):
        conn.execute(text("INSERT INTO parliament.senator_expenses VALUES (:p)"), {"p": p})
    assert cost.series_coverage(conn, "parliament.senator_expenses") == {"rows": 3, "first": "2021-Q2", "last": "2026-Q2"}


def test_ministerial_coverage_uses_the_house_fiscal_labels(conn):
    for p in ("2025-Q3", "2026-Q4", "2026-Q1", "2026-Q2"):
        conn.execute(text("INSERT INTO parliament.minister_travel VALUES (1, :p, 'X')"), {"p": p})
    assert cost.series_coverage(conn, "parliament.minister_travel")["last"] == "2026-Q2"


def test_a_ministers_current_department_is_the_one_from_their_latest_quarter(conn):
    rows = [(1, "2026-Q4", "Old Dept"),     # Jan-Mar 2026 — text order would rank this LAST-quarter-of-the-year
            (1, "2026-Q1", "New Dept"),     # Apr-Jun 2026 — after a mid-year move
            (1, "2025-Q3", "Older Dept"),
            (2, "2026-Q1", "Other Minister's Dept")]
    for r in rows:
        conn.execute(text("INSERT INTO parliament.minister_travel VALUES (:m, :p, :o)"), {"m": r[0], "p": r[1], "o": r[2]})
    assert conn.execute(text(cost._LATEST_ORG_SQL), {"mid": 1}).scalar() == "New Dept"
    assert conn.execute(text(cost._LATEST_ORG_SQL), {"mid": 99}).scalar() is None


def test_the_batched_department_lookup_orders_chronologically_too():
    src = _read("ingest", "parliament", "cost.py")
    block = src.split("SELECT DISTINCT ON (mp_id) mp_id, owner_org")[1][:260]
    assert "CHRONO_DESC_SQL" in block and "period DESC" not in block.replace("CHRONO_DESC_SQL", "")
