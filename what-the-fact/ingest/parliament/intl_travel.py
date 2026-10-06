"""intl_travel.py — senators' international travel from the Senate COMMITTEE and IIA disclosures.

A senator's own Travel table (senate_travel.py) is one of THREE places foreign travel is disclosed. This module
ingests the other two, as PDFs, and records how each overlaps the first (migration 091):

  committee  sencanada.ca/ProActiveDisclosure/Committees/en/<Y>/<Q>/<COMM>-Travel-<place>-E.pdf
             one group total per trip (senators + staff + interpreters) — no per-senator amount
  iia        parl.ca/DocumentViewer/en/IIA/financial-report/<id>   (Parliamentary Diplomacy delegations)
             a delegation total AND one line per parliamentarian — senator lines are kept individually

DOUBLE COUNTING is the hazard: an IIA delegation can contain a trip already in the senator's own Travel rows.
Every IIA senator line is matched to that senator's legs by senator_id + date window and stored as
'in_expense_travel' (already counted — do not add), 'not_in_expense_travel' (additive) or 'unmatched_senator'
(reported, never silently added). A name that cannot be resolved is never assumed to be new spending.

Parsing is pure (text in, dict out) so it is tested on real report text; only the sync touches the network.
"""
from __future__ import annotations

import datetime as dt
import html as _html
import io
import logging
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from decimal import Decimal

from sqlalchemy import text

from ingest.parliament import senator_expenses as se
from ingest.parliament._retry import fetch_with_retry
from shared.travel_places import _FOREIGN_WORDS, classify_itinerary

logger = logging.getLogger("wtf-ingest.intl_travel")

TASK = "intl_travel"
IIA_INDEX = "https://www.parl.ca/diplomacy/en/organizations/financial-disclosure"
SENATE_COMMITTEE_BASE = se._BASE
# An IIA senator line counts as "already in the senator's own Travel rows" when one of that senator's legs
# STARTS within this window around the delegation start (the Senate files the leg under the senator's
# departure date, which can precede the meeting by a few days and follow it by a long itinerary).
OVERLAP_DAYS_BEFORE = 4
OVERLAP_DAYS_AFTER = 12
_SLEEP = 0.4

_MONEY = r"[\d,]*\d\.\d\d"


# ----------------------------------------------------------------------------------------------- helpers

def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _num(s: str) -> Decimal:
    return Decimal(s.replace(",", "").replace("$", "").strip())


def _flat(raw: str) -> str:
    """One line; repair numbers the PDF text layer split across lines/spaces ("$3,\\n725.43", "$26, 446.15")."""
    t = re.sub(r"\s+", " ", raw or "")
    t = re.sub(r"(\d,)\s+(\d)", r"\1\2", t)
    return re.sub(r"\$\s+(\d)", r"$\1", t)


_MONTHS: dict[str, int] = {}
for _i, (_e, _f) in enumerate(zip(
        "january february march april may june july august september october november december".split(),
        "janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre".split()), 1):
    _MONTHS[_e] = _i
    _MONTHS[_f] = _i
_MONTHS["sept"] = 9


def _mon(word: str) -> int | None:
    return _MONTHS.get(_fold(word))


def parse_event_date(raw: str) -> dt.date | None:
    """Start date of an IIA index entry: "March 17 - 19, 2026", "November 19 - 21, 2021", "21 - 24 janvier 2025",
    "Sept 14 - 16, 2022", "October 18 , 2024". None if it cannot be read (never a guess)."""
    d = re.sub(r"\s+", " ", (raw or "").strip()).replace(" ,", ",").replace(" - ", "-").replace("- ", "-")
    for pat, order in (
        (r"^([^\W\d]+) (\d+)(?:-(?:[^\W\d]+ )?\d+)?,? (\d{4})", (1, 2, 3)),     # Month D[-D], YYYY
        (r"^([^\W\d]+) (\d+),? (\d{4})-", (1, 2, 3)),                            # Month D, YYYY - Month D, YYYY
        (r"^(\d+)(?:-\d+)? ([^\W\d]+) (\d{4})", (2, 1, 3)),                      # D[-D] mois YYYY
        (r"^(\d+) ([^\W\d]+) (\d{4})-", (2, 1, 3)),                              # D mois YYYY - ...
    ):
        m = re.match(pat, d)
        if m and _mon(m.group(order[0])):
            try:
                return dt.date(int(m.group(order[2])), _mon(m.group(order[0])), int(m.group(order[1])))
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------------------- committee reports

_COMMITTEE_PATH = re.compile(r"/ProActiveDisclosure/Committees/en/(\d{4})/([1-4])/([A-Z]{3,6})-Travel-(.+)-E\.pdf$")
_CANADA_MARK = re.compile(
    r"\b(canada|ontario|quebec|nova scotia|new brunswick|manitoba|saskatchewan|alberta|british columbia|"
    r"newfoundland|labrador|yukon|nunavut|northwest territories|n\s?b|p\s?e\s?i|on|qc|ns|sk|ab|bc|mb)\b")


def parse_committee_report(raw: str, label: str = "") -> dict:
    """-> {total, start, end, is_foreign, cancelled}. `label` is the place in the file name ("Berlin")."""
    t = _flat(raw)
    gt = re.search(r"grand total((?:\s*\$" + _MONEY + r"){5})", t, re.I)
    total = _num(re.findall(_MONEY, gt.group(1))[-1]) if gt else None

    iso = re.findall(r"\b(20\d\d-\d\d-\d\d)\b", t)
    start = end = None
    if iso:
        start = dt.date.fromisoformat(iso[0])
        end = dt.date.fromisoformat(iso[1]) if len(iso) > 1 else start
    else:  # "8/2/2023" — day/month or month/day cannot be told apart, so only an unambiguous pair is taken
        dm = re.findall(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", t)
        parsed = []
        for a, b, y in dm[:2]:
            a, b = int(a), int(b)
            if a > 12 and b <= 12:
                parsed.append(dt.date(int(y), b, a))
            elif b > 12 and a <= 12:
                parsed.append(dt.date(int(y), a, b))
            else:
                parsed = []
                break
        if len(parsed) == 2:
            start, end = parsed

    place, _ = classify_itinerary(label)
    if place is True or _FOREIGN_WORDS.search(_fold(t)):
        foreign = True
    elif place is False:
        foreign = False
    else:
        foreign = False if _CANADA_MARK.search(_fold(label) + " " + _fold(t)) else None
    return {"total": total, "start": start, "end": end, "is_foreign": foreign,
            "cancelled": bool(re.search(r"\b(trip|delegation|meeting|event|visit) (was |has been )?cancel", t, re.I))}


def committee_links(fragment: str) -> list[tuple[str, str, str]]:
    """(path, committee code, place label) for every TRAVEL report on a Senate committee-disclosure page."""
    out = []
    for href in sorted(set(re.findall(r'href="(/ProActiveDisclosure/Committees/[^"]+\.pdf)"', fragment))):
        path = _html.unescape(href)
        m = _COMMITTEE_PATH.search(path)
        if m:
            out.append((path, m.group(3), m.group(4).replace("_", " ")))
    return out


# ---------------------------------------------------------------------------------------------- IIA index

def parse_iia_index(page: str) -> list[dict]:
    """Delegations on the IIA financial-disclosure page: acr, date text, start date, title, location, report url."""
    items = []
    for blk in re.findall(r'<li class="panel panel-accordion activities-reports-list-item">(.*?)</li>', page, re.S):
        def g(p, blk=blk):
            m = re.search(p, blk, re.S)
            return m.group(1) if m else ""
        strip = lambda x: _html.unescape(re.sub(r"<[^>]+>", "", x)).strip()  # noqa: E731
        ps = [strip(x) for x in re.findall(r"<p>(.*?)</p>", blk, re.S)]
        date = _html.unescape(g(r'list-item-date">(.*?)</p>')).strip()
        items.append({
            "acr": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", g(r'list-item-acronym">(.*?)<i '))).strip(),
            "date": date, "start": parse_event_date(date), "title": strip(g(r"<h3>(.*?)</h3>")),
            "loc": ps[0] if ps else "",
            "url": g(r'href="(https://www\.parl\.ca/DocumentViewer/en/IIA/financial-report/\d+)"'),
        })
    return items


_SENATOR_LINE = re.compile(
    r"^(?:Hon\.?|Honourable|L['’]hon\.?)?\s*(.*?),?\s*S[eé]nat(?:or|eur|rice)\w*(?:\d+,?\s*)*\s*(" + _MONEY + r")"
    r"(?:\s+" + _MONEY + r")*\s*$", re.I)


def _repair_line(ln: str) -> str:
    """"2, 565.73" -> "2,565.73": the text layer sometimes spaces a thousands separator."""
    return re.sub(r"(\d,)\s+(\d)", r"\1\2", ln.strip())


def _iia_total(lines: list[str]) -> Decimal | None:
    """The DELEGATION total. Reports come in several layouts; every one is tried, and a report that fits none
    returns None (the caller records it as unparsed) rather than a guess."""
    for ln in lines:                         # (a) "Total Cost per Expenditure Type … <total>" — FIRST one is the
        if re.match(r"^Total Cost per Expenditure Type", ln):    # delegation; a later one re-totals the individuals
            n = re.findall(_MONEY, ln)
            if n:
                return _num(n[-1])
    for k, ln in enumerate(lines):           # (b) a "Participants … Total" header, then the figures
        if not ("Participants" in ln and "Transportation" in ln and "Total" in ln):   # "Fiscal year Participants …" too
            continue
        rows = []
        for nxt in lines[k + 1:k + 12]:
            if re.match(r"^(Individual Expenditures|Names\b|Group Expenditures)", nxt):
                break
            if len(re.findall(_MONEY, nxt)) >= 5:        # participants may sit on the previous line, so don't need them
                rows.append(nxt)
        totals = [r for r in rows if re.match(r"^Total\b", r, re.I)]    # multi-association tables end in a Total row
        pick = totals[-1] if totals else (rows[0] if len(rows) == 1 else None)
        if pick:
            return _num(re.findall(_MONEY, pick)[-1])
    return None


def parse_iia_report(raw: str) -> dict:
    """-> {total, senators: [(name, amount)], covered_elsewhere, cancelled}. Handles the report layouts seen in
    the 2023-2026 backfill (194 reports)."""
    lines = [_repair_line(ln) for ln in (raw or "").split("\n")]
    total = _iia_total(lines)
    senators = []
    for ln in lines:
        m = _SENATOR_LINE.match(ln)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" ,")
            senators.append((name, _num(re.findall(_MONEY, ln)[-1])))
    flat = _flat(raw)
    return {"total": total, "senators": senators,
            "covered_elsewhere": bool(re.search(r"another parliamentary budget", flat, re.I)),
            # NOT bare "cancel": a footnote "Travel cancellation expenses" describes ONE person's fee on a trip that ran.
            "cancelled": bool(re.search(r"\b(trip|delegation|meeting|event|visit) (was |has been )?cancel", flat, re.I))}


def match_senator_display(name: str, fam_idx, full_idx) -> int | None:
    """Resolve "René Cormier" / "Pierre J. Dalphond" / "Mohammad Al Zaibak" to a roster id by trying every
    given|family split. None if nothing — or more than one senator — fits (never a guess)."""
    toks = [t for t in re.split(r"\s+", re.sub(r"^(hon\.?|dr\.?|mr\.?|ms\.?|mrs\.?)\s+", "", (name or "").strip(), flags=re.I)) if t]
    found = set()
    for k in range(1, len(toks)):
        sid = se._match_senator(f"{' '.join(toks[k:])}, {' '.join(toks[:k])}", fam_idx, full_idx)
        if sid:
            found.add(sid)
    if len(found) == 1:
        return found.pop()
    if found:
        return None                        # more than one senator fits: never pick one
    # The PDF text layer sometimes splits a name ("Marie-H élène"): compare with spaces/hyphens removed.
    squash = lambda x: re.sub(r"[\s\-]+", "", se._norm_name(x))     # noqa: E731
    want = squash(name)
    hits = {sid for fam, lst in fam_idx.items() for giv, sid in lst
            if want in (squash(giv + fam), squash(fam + giv))}
    return hits.pop() if len(hits) == 1 else None


# --------------------------------------------------------------------------------------------- network/DB

def _get_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": se._HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # ingest image only (requirements-ingest.txt)
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def _fetch_pdf(url: str, label: str) -> str:
    data = fetch_with_retry(lambda: _get_bytes(url), label=label)
    if data[:4] != b"%PDF":
        raise ValueError(f"{label}: not a PDF")
    return _pdf_text(data)


def _committee_fragment(year: int, quarter: int) -> str:
    q = urllib.parse.urlencode({"displayFor": "Summary", "Member": "Committees", "Lang": "en",
                                "Year": str(year), "Quarter": str(quarter)})
    return fetch_with_retry(lambda: se._get(se._DATA_URL + "?" + q), label=f"committees {year}Q{quarter}").decode(
        "utf-8", errors="ignore")


def _quarters_since(since: dt.date, today: dt.date | None = None) -> list[tuple[int, int]]:
    today = today or dt.date.today()
    out, y, q = [], since.year, (since.month - 1) // 3 + 1
    while (y, q) <= (today.year, (today.month - 1) // 3 + 1):
        out.append((y, q))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def find_overlap(conn, senator_id: int, start: dt.date) -> tuple[list[int], Decimal]:
    """The senator's own Travel legs that START around this delegation (foreign or not-yet-classified) and the
    cost system 1 already holds for them."""
    rows = conn.execute(text("""
        SELECT id, total_cad FROM parliament.senate_travel_trips
         WHERE senator_id = :s AND traveller_kind = 'senator' AND is_international IS NOT FALSE
           AND trip_start BETWEEN :a AND :b
    """), {"s": senator_id, "a": start - dt.timedelta(days=OVERLAP_DAYS_BEFORE),
           "b": start + dt.timedelta(days=OVERLAP_DAYS_AFTER)}).fetchall()
    return [r[0] for r in rows], sum((r[1] for r in rows), Decimal("0.00"))


def _store_event(engine, ev: dict, senators: list[dict]) -> None:
    """Replace one (source, source_ref) event and its senator lines as a set, in ONE transaction."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM parliament.intl_travel_events WHERE source=:s AND source_ref=:r"),
                  {"s": ev["source"], "r": ev["source_ref"]})
        eid = c.execute(text("""
            INSERT INTO parliament.intl_travel_events
                (source, source_ref, body, title, destination, event_start, event_end, report_period, is_foreign,
                 delegation_total_cad, senator_total_cad, n_senators, cancelled, source_url)
            VALUES (:source, :source_ref, :body, :title, :destination, :event_start, :event_end, :report_period,
                    :is_foreign, :delegation_total_cad, :senator_total_cad, :n_senators, :cancelled, :source_url)
            RETURNING id"""), ev).scalar()
        for s in senators:
            overlap_ids, overlap_cad, status = [], None, "unmatched_senator"
            if s["senator_id"] and ev["event_start"]:
                overlap_ids, overlap_cad = find_overlap(c, s["senator_id"], ev["event_start"])
                status = "in_expense_travel" if overlap_ids else "not_in_expense_travel"
            c.execute(text("""
                INSERT INTO parliament.intl_travel_senators
                    (event_id, senator_id, name_as_published, amount_cad, overlap, overlap_leg_ids, overlap_cad)
                VALUES (:e, :sid, :n, :a, :o, :ids, :oc)"""),
                {"e": eid, "sid": s["senator_id"], "n": s["name"], "a": s["amount"], "o": status,
                 "ids": overlap_ids or None, "oc": overlap_cad})


def _known_refs(engine, source: str) -> set[str]:
    with engine.connect() as c:
        return {r[0] for r in c.execute(text("SELECT source_ref FROM parliament.intl_travel_events WHERE source=:s"),
                                        {"s": source})}


def _sync_committees(engine, since: dt.date, refresh: bool, stats: dict) -> None:
    known = set() if refresh else _known_refs(engine, "committee")
    for (year, quarter) in _quarters_since(since):
        try:
            links = committee_links(_committee_fragment(year, quarter))
        except Exception as exc:
            logger.warning("intl_travel: committee page %sQ%s failed: %s", year, quarter, exc)
            stats["fetch_failed"] += 1
            continue
        stats["committee_pages"] += 1
        for path, code, label in links:
            if path in known:
                continue
            url = SENATE_COMMITTEE_BASE + urllib.parse.quote(path)
            try:
                rep = parse_committee_report(_fetch_pdf(url, f"committee {path}"), label)
            except Exception as exc:
                logger.warning("intl_travel: committee report %s failed: %s", path, exc)
                stats["fetch_failed"] += 1
                continue
            if rep["total"] is None:
                stats["unparsed"].append(path)
                continue
            _store_event(engine, {
                "source": "committee", "source_ref": path, "body": code, "title": None, "destination": label,
                "event_start": rep["start"], "event_end": rep["end"], "report_period": f"{year}-Q{quarter}",
                "is_foreign": rep["is_foreign"], "delegation_total_cad": rep["total"], "senator_total_cad": None,
                "n_senators": None, "cancelled": rep["cancelled"], "source_url": url}, [])
            stats["committee_events"] += 1
            time.sleep(_SLEEP)


def _is_foreign_location(loc: str) -> bool | None:
    if not loc:
        return None
    return not re.search(r"\bcanada\b", _fold(loc))


def _sync_iia(engine, since: dt.date, refresh: bool, stats: dict) -> None:
    page = fetch_with_retry(lambda: _get_bytes(IIA_INDEX), label="iia index").decode("utf-8", errors="ignore")
    items = parse_iia_index(page)
    stats["iia_listed"] = len(items)
    if not items:
        raise RuntimeError("IIA index parsed to zero delegations — page layout changed?")
    known = set() if refresh else _known_refs(engine, "iia")
    fam_idx, full_idx = se._load_senator_index(engine)
    for it in items:
        if not it["url"] or not it["start"] or it["start"] < since:
            continue
        ref = it["url"].rsplit("/", 1)[1]
        if ref in known:
            continue
        try:
            rep = parse_iia_report(_fetch_pdf(it["url"], f"iia {ref}"))
        except Exception as exc:
            logger.warning("intl_travel: IIA report %s failed: %s", ref, exc)
            stats["fetch_failed"] += 1
            continue
        if rep["total"] is None:
            stats["unparsed"].append(ref)
            continue
        sens = [{"name": n, "amount": a, "senator_id": match_senator_display(n, fam_idx, full_idx)}
                for n, a in rep["senators"]]
        _store_event(engine, {
            "source": "iia", "source_ref": ref, "body": it["acr"], "title": it["title"], "destination": it["loc"],
            "event_start": it["start"], "event_end": None, "report_period": None,
            "is_foreign": _is_foreign_location(it["loc"]), "delegation_total_cad": rep["total"],
            "senator_total_cad": sum((s["amount"] for s in sens), Decimal("0.00")) if sens else Decimal("0.00"),
            "n_senators": len(sens), "cancelled": rep["cancelled"], "source_url": it["url"]}, sens)
        stats["iia_events"] += 1
        stats["unmatched_senators"] += sum(1 for s in sens if not s["senator_id"])
        time.sleep(_SLEEP)


def _sync(engine, since: dt.date, refresh: bool = False) -> dict:
    stats = {"committee_pages": 0, "committee_events": 0, "iia_listed": 0, "iia_events": 0,
             "unmatched_senators": 0, "fetch_failed": 0, "unparsed": []}
    _sync_committees(engine, since, refresh, stats)
    _sync_iia(engine, since, refresh, stats)
    return stats


def run_intl_travel_sync(engine, since: dt.date | None = None, refresh: bool = False) -> dict:
    """Public entry point. SELF-LOGS to parliament.ingest_log (task='intl_travel'). Weekly default looks back
    ~150 days (the IIA publishes within 60 days; committees by quarter); the backfill is a CLI --since.
    "No NEW reports" is a healthy run; a dead index or a committee page that never loaded is an error."""
    t0 = time.time()
    since = since or (dt.date.today() - dt.timedelta(days=150))
    try:
        result = _sync(engine, since, refresh)
    except Exception as exc:
        logger.exception("intl_travel sync crashed: %s", exc)
        result = {"error": str(exc)}
    if not result.get("error") and not result.get("committee_pages"):
        result = {**result, "error": "no committee disclosure page could be read"}
    try:
        with engine.begin() as c:
            if result.get("error"):
                c.execute(text("INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                          {"t": TASK, "e": str(result["error"])[:500]})
            else:
                c.execute(text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                               "VALUES (:t, :f, :u)"),
                          {"t": TASK, "f": result.get("iia_listed", 0) + result.get("committee_pages", 0),
                           "u": result.get("iia_events", 0) + result.get("committee_events", 0)})
    except Exception as exc:
        logger.error("intl_travel: could not write ingest_log: %s", exc)
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=dt.date.fromisoformat, default=None, help="YYYY-MM-DD (backfill: 2023-01-01)")
    ap.add_argument("--refresh", action="store_true", help="re-fetch reports already stored")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(run_intl_travel_sync(se._get_engine(), since=args.since, refresh=args.refresh))
