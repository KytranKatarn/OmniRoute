"""Pure view-model for /global — no DB, no Flask.

Input: market_watch.oda_canada_annual (OECD DAC1, Canada, C$ millions / percent), the
federal expense series already loaded for /debt (StatCan, C$ millions), and optionally the
Gov Watch contracts bridge (Global Affairs' OWN contract signings).

Honesty rules enforced here:
  * Only years where ALL three OECD series exist are shown (the grant-equivalent measure and
    its bilateral / GNI-share companions only line up from 2018). Older years use a different
    basis and are never spliced on.
  * Multilateral = total - bilateral, DERIVED and labelled so; it is not an OECD figure.
  * Share of federal spending divides OECD ODA by StatCan federal expense. Both are calendar
    years, but they are different statistical systems, so the ratio is approximate and the page
    says "about". It is None when either side is missing for a year.
  * The latest year PUBLISHED is reported as such, never as 'current'.
"""

from __future__ import annotations

from typing import Iterable

OWN_DEPT = "Global Affairs Canada"


def _bd(millions):
    return None if millions is None else millions / 1000.0


def _index(rows: Iterable[dict]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for r in rows:
        out.setdefault(int(r["ref_year"]), {})[r["item_key"]] = float(r["value"])
    return out


def build(oda_rows: list[dict], expense_rows: list[dict] | None = None,
          contract_rows: list[dict] | None = None, today_year: int | None = None) -> dict | None:
    oda = _index(oda_rows)
    years = sorted(y for y, d in oda.items() if {"oda_ge", "bilateral_ge", "oda_gni_pct"} <= d.keys())
    if not years:
        return None
    exp = {int(r["ref_year"]): float(r["value_millions"]) for r in (expense_rows or []) if r["item_key"] == "expense"}
    rows = []
    for y in years:
        d = oda[y]
        total, bi = d["oda_ge"], d["bilateral_ge"]
        multi = total - bi
        e = exp.get(y)
        rows.append({
            "year": y, "total": _bd(total), "bilateral": _bd(bi), "multilateral": _bd(multi),
            "bilateral_share": bi / total * 100.0 if total else None,
            "gni_pct": d["oda_gni_pct"],
            "federal_share": (total / e * 100.0) if e else None,
        })
    latest = rows[-1]
    prior = rows[-2] if len(rows) > 1 else None
    change = None
    if prior and prior["total"]:
        change = {"year": prior["year"], "abs": latest["total"] - prior["total"],
                  "pct": (latest["total"] - prior["total"]) / prior["total"] * 100.0}
    peak = max(rows, key=lambda r: r["total"])
    own = None
    if contract_rows:
        mine = [r for r in contract_rows if r["title_en"] == OWN_DEPT]
        by_year = {int(r["year"]): r for r in mine}
        ly = max((y for y in by_year if today_year is None or y < today_year), default=None)
        if ly is not None:
            r = by_year[ly]
            own = {"year": ly, "n": int(r["n_contracts"]), "value": float(r["signed_value"]) / 1e9}
    return {"rows": rows, "latest": latest, "change": change, "peak": peak,
            "first_year": years[0], "own_contracts": own,
            "gap": (today_year - latest["year"]) if today_year else None}
