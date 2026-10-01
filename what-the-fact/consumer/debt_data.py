"""Pure view-model for /debt — no DB, no Flask (so it is unit-testable).

Input: rows from market_watch.fiscal_federal_annual / _quarterly, loaded by
ingest/market/fiscal_federal.py from Statistics Canada. Every number the page
shows is derived here from those rows; nothing is typed in.

Honesty rules this module enforces:
  * Years are CALENDAR years on Statistics Canada's government-finance-statistics
    basis. They are NOT Public Accounts fiscal years and the page says so.
  * Net debt is Statistics Canada's "net financial worth" with the sign flipped
    (liabilities minus financial assets). It is a different measure from the
    Public Accounts "accumulated deficit", so the two are never labelled alike.
  * A ratio is only computed when BOTH inputs exist for that year; otherwise None
    (rendered as "—"), never zero.
  * The current year is shown separately as YEAR TO DATE, from whole quarters
    only, compared with the SAME quarters a year earlier. Quarterly flows are not
    seasonally adjusted, so a quarter is never compared with a different quarter
    and a partial year is never ranked against full years.
"""

from __future__ import annotations

from typing import Iterable

WINDOW_YEARS = 11  # latest year + ten before it, as the design's "ten fiscal years"

REVENUE_PARTS = [
    ("taxes_income", "Income taxes"),
    ("taxes_goods_services", "Taxes on goods and services"),
    ("taxes_trade", "Taxes on international trade"),
    ("social_contributions", "Social contributions (EI, etc.)"),
]
EXPENSE_PARTS = [
    ("social_benefits", "Social benefits"),
    ("grants_expense", "Grants (transfers to provinces, people, organizations)"),
    ("compensation", "Compensation of employees"),
    ("interest", "Interest on the debt"),
    ("goods_services", "Use of goods and services"),
    ("subsidies", "Subsidies"),
    ("fixed_capital", "Consumption of fixed capital"),
]


def _b(v_millions):
    return None if v_millions is None else v_millions / 1000.0


def _ratio(num, den):
    if num is None or den in (None, 0):
        return None
    return num / den * 100.0


def _index_annual(rows: Iterable[dict]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for r in rows:
        out.setdefault(int(r["ref_year"]), {})[r["item_key"]] = float(r["value_millions"])
    return out


def _index_quarterly(rows: Iterable[dict]) -> dict[tuple[int, int], dict[str, float]]:
    out: dict[tuple[int, int], dict[str, float]] = {}
    for r in rows:
        d = r["ref_quarter"]
        out.setdefault((d.year, (d.month - 1) // 3 + 1), {})[r["item_key"]] = float(r["value_millions"])
    return out


def year_row(year: int, d: dict[str, float]) -> dict:
    nfw = d.get("net_financial_worth")
    net_debt = None if nfw is None else -nfw
    gdp = d.get("gdp_nominal")
    rev, exp = d.get("revenue"), d.get("expense")
    return {
        "year": year,
        "revenue": _b(rev),
        "expense": _b(exp),
        # Net lending/borrowing is the headline balance (it includes capital); fall back to
        # revenue - expense only if it is genuinely absent, and say which was used.
        "balance": _b(d["net_lending"]) if "net_lending" in d else (_b(rev - exp) if rev is not None and exp is not None else None),
        "net_debt": _b(net_debt),
        "liabilities": _b(d.get("liabilities")),
        "interest": _b(d.get("interest")),
        "gdp": _b(gdp),
        "net_debt_gdp": _ratio(net_debt, gdp),
        "balance_gdp": _ratio(d.get("net_lending"), gdp),
        "interest_share": _ratio(d.get("interest"), rev),
        "parts": d,
    }


def _breakdown(d: dict[str, float], total_key: str, parts: list[tuple[str, str]]) -> list[dict]:
    total = d.get(total_key)
    if not total:
        return []
    rows = []
    used = 0.0
    for key, label in parts:
        v = d.get(key)
        if v is None:
            continue
        used += v
        rows.append({"label": label, "value": _b(v), "share": v / total * 100.0})
    other = total - used
    # "Everything else" is the arithmetic remainder (grants-in, other revenue, other expense...).
    # A small negative remainder would be a rounding/definition artefact; show it only if material.
    if abs(other) / total > 0.005:
        rows.append({"label": "Everything else", "value": _b(other), "share": other / total * 100.0})
    rows.sort(key=lambda r: -r["value"])
    return rows


def year_to_date(quarterly: dict[tuple[int, int], dict[str, float]], last_annual_year: int | None):
    """Whole quarters of the newest year, vs the same quarters one year earlier.

    Returns None when there is nothing newer than the annual table, or when the newest
    year is already complete AND covered by the annual series."""
    if not quarterly:
        return None
    cur_year = max(y for y, _ in quarterly)
    qs = sorted(q for y, q in quarterly if y == cur_year)
    if not qs:
        return None
    if len(qs) == 4 and last_annual_year is not None and cur_year <= last_annual_year:
        return None
    # require a contiguous run starting at Q1, otherwise "year to date" would be a lie
    if qs != list(range(1, len(qs) + 1)):
        return None
    prev = cur_year - 1
    if any((prev, q) not in quarterly for q in qs):
        prev_ok = False
    else:
        prev_ok = True

    def tot(year, key):
        vals = [quarterly[(year, q)].get(key) for q in qs]
        return None if any(v is None for v in vals) else sum(vals)

    def delta(a, b):
        return None if a is None or b is None else a - b

    metrics = {}
    for key in ("revenue", "expense", "net_lending", "interest"):
        cur = tot(cur_year, key)
        old = tot(prev, key) if prev_ok else None
        metrics[key] = {"value": _b(cur), "year_ago": _b(old), "change": _b(delta(cur, old)),
                        "change_pct": _ratio(delta(cur, old), abs(old)) if old else None}
    last_q = (cur_year, qs[-1])
    nfw_now = quarterly[last_q].get("net_financial_worth")
    nfw_ago = quarterly.get((prev, qs[-1]), {}).get("net_financial_worth")
    nd_now = None if nfw_now is None else -nfw_now
    nd_ago = None if nfw_ago is None else -nfw_ago
    month_end = {1: "March", 2: "June", 3: "September", 4: "December"}[qs[-1]]
    return {
        "year": cur_year,
        "quarters": qs,
        "label": ("first quarter" if qs == [1] else f"first {len(qs)} quarters"),
        "through": f"{month_end} {cur_year}",
        "metrics": metrics,
        "net_debt": _b(nd_now),
        "net_debt_year_ago": _b(nd_ago),
        "net_debt_change": _b(None if nd_now is None or nd_ago is None else nd_now - nd_ago),
        "comparable": prev_ok,
        "prev_year": prev,
    }


QUARTER_WINDOW = 8
_QLABEL = {1: "Jan–Mar", 2: "Apr–Jun", 3: "Jul–Sep", 4: "Oct–Dec"}


def quarter_rows(quarterly: dict[tuple[int, int], dict[str, float]]) -> list[dict]:
    """Newest quarters first. Each carries its own year-ago quarter so the reader sees
    like-for-like change (flows are not seasonally adjusted; Q1 always differs from Q2)."""
    keys = sorted(quarterly)[-QUARTER_WINDOW:]
    out = []
    for (y, q) in reversed(keys):
        d = quarterly[(y, q)]
        ago = quarterly.get((y - 1, q), {})

        def yoy(key):
            a, b = d.get(key), ago.get(key)
            return None if a is None or b is None else _b(a - b)

        nfw = d.get("net_financial_worth")
        out.append({
            "label": f"Q{q} {y}", "span": f"{_QLABEL[q]} {y}", "year": y, "quarter": q,
            "revenue": _b(d.get("revenue")), "expense": _b(d.get("expense")),
            "balance": _b(d.get("net_lending")), "interest": _b(d.get("interest")),
            "net_debt": None if nfw is None else _b(-nfw),
            "revenue_yoy": yoy("revenue"), "expense_yoy": yoy("expense"),
            "balance_yoy": yoy("net_lending"),
        })
    return out


def _direction(now, then, lower_is_better=True, tol=0.05):
    """'improved' | 'worsened' | 'about the same' | None — pure sign logic, no judgement of size."""
    if now is None or then is None:
        return None
    if abs(now - then) <= tol:
        return "about the same"
    better = (now < then) if lower_is_better else (now > then)
    return "improved" if better else "worsened"


def verdict(rows: list[dict]) -> list[dict]:
    """'Better or worse?' as three separate measures, each vs the year before AND vs
    the last pre-pandemic year (2019) — because the honest answer depends on which."""
    if not rows:
        return []
    by = {r["year"]: r for r in rows}
    latest = rows[-1]
    prior = by.get(latest["year"] - 1)
    base = by.get(2019)
    out = []
    specs = [
        ("Deficit as a share of GDP", "balance_gdp", False, "{:+.1f}% of GDP", "A larger surplus (or smaller deficit) is better."),
        ("Net debt as a share of GDP", "net_debt_gdp", True, "{:.1f}% of GDP", "A falling ratio means the economy is outgrowing the debt."),
        ("Interest as a share of revenue", "interest_share", True, "{:.1f}% of revenue", "The share of every tax dollar that goes to lenders."),
    ]
    for title, key, lower_better, fmt, note in specs:
        now = latest.get(key)
        if now is None:
            continue
        p, b = (prior or {}).get(key), (base or {}).get(key)
        out.append({
            "title": title, "note": note, "now": fmt.format(now), "year": latest["year"],
            "vs_prior": {"year": prior["year"], "value": None if p is None else fmt.format(p),
                         "word": _direction(now, p, lower_better)} if prior else None,
            "vs_base": {"year": 2019, "value": None if b is None else fmt.format(b),
                        "word": _direction(now, b, lower_better)} if base else None,
        })
    return out


def build(annual_rows: list[dict], quarterly_rows: list[dict]) -> dict | None:
    """Returns None when the ingest has not loaded anything yet (page shows an honest empty state)."""
    annual = _index_annual(annual_rows)
    # a year only counts if it carries the page's spine
    years = sorted(y for y, d in annual.items() if "revenue" in d and "expense" in d)
    if not years:
        return None
    window = years[-WINDOW_YEARS:]
    rows = [year_row(y, annual[y]) for y in window]
    latest = rows[-1]
    quarterly = _index_quarterly(quarterly_rows)
    return {
        "rows": rows,
        "latest": latest,
        "first_year": window[0],
        "revenue_breakdown": _breakdown(annual[window[-1]], "revenue", REVENUE_PARTS),
        "expense_breakdown": _breakdown(annual[window[-1]], "expense", EXPENSE_PARTS),
        "verdict": verdict(rows),
        "ytd": year_to_date(quarterly, years[-1]),
        "quarters": quarter_rows(quarterly),
    }
