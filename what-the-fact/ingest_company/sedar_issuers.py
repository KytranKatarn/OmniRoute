"""SEDAR+ reporting-issuers parser for the Entity-Graph company layer (Phase 1).

⚠️ The SEDAR+ export CANNOT be automated. sedarplus.ca is Radware + hCaptcha walled
and its ToU prohibits scraping; critically, the warmed `364-sedarplus` browser
profile does NOT transfer to an automated launch — a headless Playwright reusing it
is STILL served the Radware block page (verified 2026-06-26, KB #275934/#275935).
So the reporting-issuers CSV is obtained by a HUMAN (own browser, or a download-
enabled noVNC session) solving one hCaptcha + clicking Export — quarterly; the list
is slow-moving. This module parses that human-exported CSV into issuer IDENTITY
records for the graph ingest (Slice D).

Export columns (verified from a real export):
  Name, Number, Reporting jurisdictions (determined by regulator),
  Principal jurisdiction, Type, In default, Active cease trade order
`Number` is the strong external key → entity_external_ids key_type='sedar_issuer'.
SEDAR = identity ONLY (no NAICS); sector comes from TMX (tmx_sector.py).
"""

from __future__ import annotations

import csv
import io

PRODUCT = "market-watch"
SEDAR_KEY_TYPE = "sedar_issuer"

# Issuer `Type` values that are NOT operating companies (excluded from the
# benchmark universe). The export is dominated by investment funds.
NON_OPERATING_TYPES = frozenset({"investment fund"})

_TRUE = {"yes", "true", "y", "1"}


def is_operating_issuer(issuer_type: str) -> bool:
    return (issuer_type or "").strip().lower() not in NON_OPERATING_TYPES


def _split_jurisdictions(s: str) -> list:
    return [j.strip() for j in (s or "").replace(";", ",").split(",") if j.strip()]


def parse_sedar_export(data) -> list:
    """Parse a SEDAR+ reporting-issuers export (CSV str/bytes) -> issuer records.

    Each record: name, sedar_number, type, reporting_jurisdictions (list),
    principal_jurisdiction, in_default (bool), cease_trade (bool).
    Rows missing a name or number are dropped. Tolerant to column-header wording.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", "ignore")
    rows = list(csv.DictReader(io.StringIO(data)))
    cols = list(rows[0].keys()) if rows else []

    def find(*needles):
        for c in cols:
            cl = c.strip().lower()
            if any(n in cl for n in needles):
                return c
        return None

    c_name = find("name")
    c_num = find("number")
    c_type = find("type")
    c_rj = find("reporting jurisd")
    c_pj = find("principal jurisd")
    c_def = find("in default", "default")
    c_cto = find("cease trade")

    out = []
    for r in rows:
        name = (r.get(c_name) or "").strip()
        num = str(r.get(c_num) if c_num else "").strip()
        if not name or not num:
            continue
        out.append({
            "name": name,
            "sedar_number": num,
            "type": (r.get(c_type) or "").strip() if c_type else "",
            "reporting_jurisdictions": _split_jurisdictions(r.get(c_rj) if c_rj else ""),
            "principal_jurisdiction": (r.get(c_pj) or "").strip() if c_pj else "",
            "in_default": (str(r.get(c_def) or "").strip().lower() in _TRUE),
            "cease_trade": (str(r.get(c_cto) or "").strip().lower() in _TRUE),
        })
    return out


def operating_issuers(records) -> list:
    """Keep only operating companies (drops investment funds)."""
    return [r for r in records if is_operating_issuer(r["type"])]


def load_sedar_export(path: str) -> list:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return parse_sedar_export(fh.read())


if __name__ == "__main__":  # manual: run against a human-exported CSV
    import collections
    import sys
    if len(sys.argv) != 2:
        print("usage: python3 -m ingest_company.sedar_issuers <export.csv>")
        sys.exit(1)
    recs = load_sedar_export(sys.argv[1])
    ops = operating_issuers(recs)
    print(f"rows={len(recs)} operating={len(ops)}")
    print("by type:", dict(collections.Counter(r["type"] for r in recs).most_common(12)))
    nums = [r["sedar_number"] for r in recs]
    print(f"distinct issuer numbers: {len(set(nums))}/{len(nums)}")
