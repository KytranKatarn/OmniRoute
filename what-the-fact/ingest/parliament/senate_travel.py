"""senate_travel.py — itemized Senate travel (one row per trip leg) from the Senate's own disclosures.

parliament.senator_expenses keeps ONE quarterly travel total per senator. That cannot check a claim like
"65 senators spent $1,850,420 on international travel between 2023-01-16 and 2026-03-17" — the window needs
trip dates and the question needs a destination. The Senate publishes both behind each travel amount in
its quarterly summary:

    GET /umbraco/surface/ProActiveAjax/GetProActiveData
        ?displayFor=Details&Member=Senators&Expense=Travel&MemberId=<id>&Year=<Y>&Quarter=<Q>&Lang=en

an HTML table: Traveller | Start | End | Itinerary | Purpose | Air Bus Train | Other Ground Transp. |
Per Diems | Accom. | Other | Total Amount (before tax), followed by designated travellers (a second person
accompanying the senator), "Sub-total" lines and a "Grand Total".

HOW IT STAYS HONEST
  * Every (senator, quarter) is REPLACED as a set in one transaction — the Senate amends reports — and a
    fetch or parse failure leaves the existing rows untouched. It never deletes on a failure.
  * Every (senator, quarter) is RECONCILED: the parsed rows must add up to the Senate's own "Grand Total"
    and to the figure on the quarterly summary link. The result is stored (senate_travel_checks) and
    mismatches are reported, because a quarter that does not reconcile is a quarter we may have mis-parsed.
  * Designated travellers are kept in their own traveller_kind so a figure can be stated with or without
    them and is never double-counted.
  * is_international comes from shared/travel_places.classify_itinerary and is NULL, never "domestic", when
    a place is unrecognised or ambiguous.

Run: python -m ingest.parliament.senate_travel [--quarters N] [--since-year Y]
Weekly from run.py after senator_expenses (default: the latest 2 quarters). Backfill: --quarters 24.
"""
from __future__ import annotations

import datetime
import html as _html
import logging
import re
import time
import urllib.parse
from decimal import Decimal

from sqlalchemy import text

from ingest.parliament import senator_expenses as se
from ingest.parliament._retry import fetch_with_retry
from shared.travel_places import classify_itinerary

logger = logging.getLogger("wtf-ingest.senate_travel")

TASK = "senate_travel"
_COLS = 11  # Traveller, Start, End, Itinerary, Purpose, Air, Ground, Per diems, Accom., Other, Total
_TOLERANCE = Decimal("0.02")

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TRAVEL_LINK = re.compile(
    r'<a[^>]+href="[^"]*Expense=Travel&amp;MemberId=(\d+)&amp;Year=(\d{4})&amp;Quarter=([1-4])[^"]*"[^>]*>([^<]*)</a>',
    re.I,
)


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _money(s: str) -> Decimal | None:
    v = se._parse_dollar(s)
    return None if v is None else Decimal(str(v)).quantize(Decimal("0.01"))


def _date(s: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def _kind(label: str, senator_label: str | None) -> str:
    low = (label or "").lower()
    if "designated" in low:
        return "designated"
    if senator_label is None or label == senator_label:
        return "senator"
    return "other"


# ------------------------------------------------------------------------------------------- parsing

def travel_links(fragment: str) -> list[tuple[int, int, int, str]]:
    """[(member_id, year, quarter, summary_amount_text)] for every Travel amount link on the summary."""
    return [(int(m), int(y), int(q), _txt(a)) for m, y, q, a in _TRAVEL_LINK.findall(fragment)]


def summary_names_to_member_ids(fragment: str) -> dict[str, int]:
    """{"Family, Given": member_id} — the row's name cell paired with its Travel link."""
    out: dict[str, int] = {}
    for row in _ROW.findall(fragment):
        link = _TRAVEL_LINK.search(row)
        if not link:
            continue
        cells = [_txt(c) for c in _CELL.findall(row)]
        if cells and "," in cells[0]:
            out[cells[0]] = int(link.group(1))
    return out


def parse_travel_detail(fragment: str) -> dict:
    """Parse one senator-quarter detail page.

    -> {"trips": [..], "grand_total": Decimal|None, "bad_rows": int}
    Each trip: traveller_name, traveller_kind, trip_start, trip_end, itinerary, purpose, the five cost
    columns, total_cad. A blank Traveller cell continues the previous traveller; a leg whose Traveller cell
    is a label ("Designated Traveller") switches kind. Rows with a bad date or total are COUNTED, not
    silently dropped, so reconciliation can fail loudly.
    """
    trips: list[dict] = []
    grand: Decimal | None = None
    bad = 0
    current_name: str | None = None
    senator_label: str | None = None
    for row in _ROW.findall(fragment):
        cells = [_txt(c) for c in _CELL.findall(row)]
        if not cells:
            continue
        head = cells[0].lower()
        if head == "traveller" and len(cells) >= _COLS:
            continue  # header
        if head.startswith("grand total"):
            grand = _money(cells[-1])
            continue
        if head.startswith("sub-total") or len(cells) < _COLS:
            continue
        label = cells[0]
        if label:
            current_name = label
            if senator_label is None and "designated" not in label.lower():
                senator_label = label
        start, end = _date(cells[1]), _date(cells[2])
        total = _money(cells[10])
        if start is None or total is None:
            bad += 1
            continue
        trips.append({
            "traveller_name": current_name,
            "traveller_kind": _kind(current_name or "", senator_label),
            "trip_start": start,
            "trip_end": end,
            "itinerary": cells[3],
            "purpose": cells[4],
            "air_bus_train_cad": _money(cells[5]),
            "ground_cad": _money(cells[6]),
            "per_diem_cad": _money(cells[7]),
            "accommodation_cad": _money(cells[8]),
            "other_cad": _money(cells[9]),
            "total_cad": total,
        })
    return {"trips": trips, "grand_total": grand, "bad_rows": bad}


def reconcile(parsed: dict, summary_amount: Decimal | None) -> dict:
    """Do the parsed rows add up to the Senate's own grand total (and to the summary link amount)?"""
    rows_total = sum((t["total_cad"] for t in parsed["trips"]), Decimal("0.00"))
    grand = parsed["grand_total"]
    ok = parsed["bad_rows"] == 0
    if grand is not None:
        ok = ok and abs(rows_total - grand) <= _TOLERANCE
    if summary_amount is not None:
        ok = ok and abs(rows_total - summary_amount) <= _TOLERANCE
    return {"rows_total": rows_total, "grand_total": grand, "summary_amount": summary_amount,
            "reconciled": ok, "row_count": len(parsed["trips"])}


# ------------------------------------------------------------------------------------------- fetching

def _fetch_detail(member_id: int, year: int, quarter: int) -> str:
    params = {"displayFor": "Details", "Member": "Senators", "Expense": "Travel",
              "MemberId": str(member_id), "Year": str(year), "Quarter": str(quarter), "Lang": "en"}
    url = se._DATA_URL + "?" + urllib.parse.urlencode(params)
    return fetch_with_retry(lambda: se._get(url), label=f"senate_travel {member_id} {year}Q{quarter}").decode(
        "utf-8", errors="ignore")


def _detail_url(member_id: int, year: int, quarter: int) -> str:
    return (f"{se._BASE}/en/proactive/summary/details/#?Member=Senators&Expense=Travel"
            f"&MemberId={member_id}&Year={year}&Quarter={quarter}")


# ------------------------------------------------------------------------------------------- storing

def _store(engine, sid: int, period: str, parsed: dict, check: dict, source_url: str) -> int:
    """Replace this senator-quarter's rows as a set, in ONE transaction. Returns rows written."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM parliament.senate_travel_trips WHERE senator_id=:s AND period=:p"),
                  {"s": sid, "p": period})
        for seq, t in enumerate(parsed["trips"], start=1):
            intl, basis = classify_itinerary(t["itinerary"])
            c.execute(text("""
                INSERT INTO parliament.senate_travel_trips
                    (senator_id, period, seq, traveller_name, traveller_kind, trip_start, trip_end,
                     itinerary, purpose, air_bus_train_cad, ground_cad, per_diem_cad, accommodation_cad,
                     other_cad, total_cad, is_international, intl_basis, source_url)
                VALUES
                    (:s, :p, :seq, :tn, :tk, :ts, :te, :it, :pu, :a, :g, :pd, :ac, :o, :tot, :intl, :basis, :url)
            """), {"s": sid, "p": period, "seq": seq, "tn": t["traveller_name"], "tk": t["traveller_kind"],
                   "ts": t["trip_start"], "te": t["trip_end"], "it": t["itinerary"], "pu": t["purpose"],
                   "a": t["air_bus_train_cad"], "g": t["ground_cad"], "pd": t["per_diem_cad"],
                   "ac": t["accommodation_cad"], "o": t["other_cad"], "tot": t["total_cad"],
                   "intl": intl, "basis": basis, "url": source_url})
        c.execute(text("""
            INSERT INTO parliament.senate_travel_checks
                (senator_id, period, rows_total_cad, grand_total_cad, summary_travel_cad, reconciled, row_count)
            VALUES (:s, :p, :rt, :gt, :st, :ok, :n)
            ON CONFLICT (senator_id, period) DO UPDATE SET
                rows_total_cad=EXCLUDED.rows_total_cad, grand_total_cad=EXCLUDED.grand_total_cad,
                summary_travel_cad=EXCLUDED.summary_travel_cad, reconciled=EXCLUDED.reconciled,
                row_count=EXCLUDED.row_count, checked_at=now()
        """), {"s": sid, "p": period, "rt": check["rows_total"], "gt": check["grand_total"],
               "st": check["summary_amount"], "ok": check["reconciled"], "n": check["row_count"]})
    return len(parsed["trips"])


# ------------------------------------------------------------------------------------------- sync

def _sync(engine, max_quarters: int, since_year: int | None) -> dict:
    first = se._fetch_fragment()
    quarters = se._available_quarters(first)
    if since_year is not None:
        quarters = [(y, q) for (y, q) in quarters if y >= since_year]
    quarters = quarters[:max_quarters]
    if not quarters:
        return {"error": "no quarters found in the Senate dropdown"}
    fam_idx, full_idx = se._load_senator_index(engine)
    if not fam_idx:
        return {"error": "senator roster is empty — nothing to match"}

    stats = {"quarters": 0, "senators": 0, "trips": 0, "unreconciled": [], "fetch_failed": 0, "unmatched": set()}
    for (year, quarter) in quarters:
        period = f"{year}-Q{quarter}"
        try:
            fragment = se._fetch_fragment(year, quarter)
        except Exception as exc:
            logger.warning("senate_travel: summary %s failed: %s", period, exc)
            stats["fetch_failed"] += 1
            continue
        ids = summary_names_to_member_ids(fragment)
        amounts = {(m, y, q): a for m, y, q, a in travel_links(fragment)}
        stats["quarters"] += 1
        for name, member_id in ids.items():
            sid = se._match_senator(name, fam_idx, full_idx)
            if not sid:
                stats["unmatched"].add(name)
                continue
            try:
                detail = _fetch_detail(member_id, year, quarter)
                parsed = parse_travel_detail(detail)
            except Exception as exc:
                logger.warning("senate_travel: detail %s %s failed (rows left untouched): %s", name, period, exc)
                stats["fetch_failed"] += 1
                time.sleep(se._SLEEP)
                continue
            check = reconcile(parsed, _money(amounts.get((member_id, year, quarter), "")))
            if not parsed["trips"] and check["summary_amount"] in (None, Decimal("0.00")):
                time.sleep(se._SLEEP)
                continue
            stats["trips"] += _store(engine, sid, period, parsed, check, _detail_url(member_id, year, quarter))
            stats["senators"] += 1
            if not check["reconciled"]:
                stats["unreconciled"].append(f"{name} {period}")
                logger.warning("senate_travel: %s %s does NOT reconcile: rows=%s grand=%s summary=%s bad=%s",
                               name, period, check["rows_total"], check["grand_total"],
                               check["summary_amount"], parsed["bad_rows"])
            time.sleep(se._SLEEP)
    stats["unmatched"] = sorted(stats["unmatched"])
    return stats


def run_senate_travel_sync(engine, max_quarters: int = 2, since_year: int | None = None) -> dict:
    """Public entry point. SELF-LOGS to parliament.ingest_log (task='senate_travel') like the other syncs,
    so the drift guard watches it. An empty run is an error, never a quiet success."""
    t0 = time.time()
    try:
        result = _sync(engine, max_quarters, since_year)
    except Exception as exc:
        logger.exception("senate_travel sync crashed: %s", exc)
        result = {"error": str(exc)}
    if not result.get("error") and not result.get("trips"):
        result = {**result, "error": "no senate travel rows fetched"}
    try:
        with engine.begin() as c:
            if result.get("error"):
                c.execute(text("INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                          {"t": TASK, "e": str(result["error"])[:500]})
            else:
                c.execute(text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                               "VALUES (:t, :f, :u)"),
                          {"t": TASK, "f": result.get("senators", 0), "u": result.get("trips", 0)})
    except Exception as exc:
        logger.error("senate_travel: could not write ingest_log: %s", exc)
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--quarters", type=int, default=2)
    ap.add_argument("--since-year", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run_senate_travel_sync(se._get_engine(), max_quarters=args.quarters, since_year=args.since_year))
