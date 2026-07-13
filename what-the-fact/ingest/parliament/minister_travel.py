"""minister_travel.py — ministerial (departmental) travel & hospitality ingest.

The cost the MP budget does NOT capture. parliament.mp_expenses is a member's House of
Commons office budget; a cabinet minister's DEPARTMENTAL travel (government aircraft, official
trips) and hospitality are borne by the department/PCO and disclosed separately under the
federal proactive-publication regime. That is why the PM shows ~$0 travel in mp_expenses — his
official travel never touches his MP budget. This ingest fills that gap so a minister's cost can
be shown as MP-budget PLUS the centrally-borne ministerial travel/hospitality (a separate line).

Source: open.canada.ca TBS proactive disclosure (CKAN) — one consolidated CSV each for Travel
(~70MB) and Hospitality (~28MB), covering senior officials across ALL of government:
  Travel      dataset 009f9a49-c2d9-4d29-a6d4-1a228da335ce  (travelq.csv)
  Hospitality dataset b9f51ef4-4605-4ef2-8231-62a2edda1b54  (hospitalityq.csv)

Durability + resilience (same discipline as the rebuilt mp_expenses.py):
  * Resource URLs are RESOLVED from CKAN package_show at run time (not hardcoded) — survives a
    resource re-publish.
  * The big CSVs are STREAMED row-by-row (never loaded whole — the 16MB-cap lesson, KB gov-watch).
  * Only rows that (a) name-match a parliament.mps row AND (b) carry a minister-level title are
    kept — a DM/CEO who merely shares a surname is excluded. Matching reuses mp_expenses' family
    -name matcher (DRY).
  * FAIL LOUD: writes a parliament.ingest_log row every run; a zero-upsert run returns an error
    and logs ERROR, so a future source change surfaces instead of freezing silently.

Aggregates itemized trips/events to the fiscal quarter ('YYYY-Qn', the SAME key as mp_expenses)
and upserts parliament.minister_travel (migration 041). Runs weekly from run_parliament_sync().
"""
import csv
import datetime
import io
import json
import logging
import urllib.request
from urllib.parse import urlparse

from sqlalchemy import text

from ingest.parliament.mp_expenses import _build_mp_index, _match_mp, _parse_dollar

logger = logging.getLogger("wtf-ingest.minister_travel")

_CKAN = "https://open.canada.ca/data/api/action/package_show?id="
_DATASETS = {
    "travel": ("009f9a49-c2d9-4d29-a6d4-1a228da335ce", "travelq.csv"),
    "hospitality": ("b9f51ef4-4605-4ef2-8231-62a2edda1b54", "hospitalityq.csv"),
}
_HEADERS = {
    "User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)",
    "Accept-Encoding": "identity",   # never gzip — we stream + parse as plain text
}
# a cabinet minister's disclosed title contains 'minister' but NOT these (which are officials,
# not members of the ministry).
_NON_MINISTER = ("deputy", "associate", "assistant", "parliamentary secretary", "chief of staff")

# SSRF guard: this ingest fetches whatever resource URL CKAN's package_show hands back, and it
# runs inside wtf-ingest (which can reach the mesh/DB). Only ever fetch government open-data over
# HTTPS — validate scheme + host so a compromised/unexpected catalog entry can't redirect the
# fetch at an internal address (file://, http://100.64.x, a hub service, etc.).
_ALLOWED_HOST_SUFFIXES = (".canada.ca", ".gc.ca")


def _is_allowed_url(url: str) -> bool:
    try:
        p = urlparse(url or "")
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme == "https" and (host == "open.canada.ca" or host.endswith(_ALLOWED_HOST_SUFFIXES))


def _ckan_csv_url(dataset_id: str, filename: str):
    """Resolve the current download URL of a dataset's main CSV resource, or None."""
    try:
        req = urllib.request.Request(_CKAN + dataset_id, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            pkg = json.loads(r.read()).get("result", {})
    except Exception as exc:
        logger.warning("minister_travel: CKAN package_show failed for %s: %s", dataset_id, exc)
        return None
    csvs = [res for res in pkg.get("resources", [])
            if (res.get("format", "").lower() == "csv") and (res.get("url"))]
    # prefer the exact consolidated file (…/travelq.csv), never the '-nil' companion
    exact = [c for c in csvs if c["url"].lower().rstrip("/").endswith(filename) and "nil" not in c["url"].lower()]
    chosen = (exact or [c for c in csvs if "nil" not in c["url"].lower()] or csvs)
    url = chosen[0]["url"] if chosen else None
    if url and not _is_allowed_url(url):
        logger.warning("minister_travel: rejecting non-allowlisted resource URL %s", url)
        return None
    return url


def _stream_rows(url: str):
    """Yield CSV dict rows from a (large) URL, streamed — never buffers the whole file."""
    if not _is_allowed_url(url):
        raise ValueError(f"refusing to fetch non-allowlisted URL: {url}")
    req = urllib.request.Request(url, headers=_HEADERS)
    resp = urllib.request.urlopen(req, timeout=120)
    try:
        wrapper = io.TextIOWrapper(resp, encoding="utf-8-sig", errors="ignore")
        for row in csv.DictReader(wrapper):
            yield row
    finally:
        resp.close()


def _date_to_period(date_str: str):
    """'YYYY-MM-DD' -> fiscal-quarter key 'YYYY-Qn' matching mp_expenses._quarter_label.
    Apr-Jun -> Q1, Jul-Sep -> Q2, Oct-Dec -> Q3, Jan-Mar -> Q4 (of the calendar year)."""
    try:
        d = datetime.date.fromisoformat((date_str or "")[:10])
    except ValueError:
        return None
    m = d.month
    if 4 <= m <= 6:
        return f"{d.year}-Q1"
    if 7 <= m <= 9:
        return f"{d.year}-Q2"
    if 10 <= m <= 12:
        return f"{d.year}-Q3"
    return f"{d.year}-Q4"   # Jan-Mar


def _is_minister_title(title: str) -> bool:
    t = (title or "").lower()
    return "minister" in t and not any(x in t for x in _NON_MINISTER)


def _accumulate(url, kind, fam_idx, full_idx, agg):
    """Stream one CSV; fold minister-matched rows into agg[(mp_id, period)]. Returns rows scanned."""
    scanned = 0
    amt_field = "total"
    for row in _stream_rows(url):
        scanned += 1
        if not _is_minister_title(row.get("title_en") or row.get("title_fr")):
            continue
        mp_id = _match_mp(row.get("name") or "", fam_idx, full_idx)
        if not mp_id:
            continue
        period = _date_to_period(row.get("start_date") or row.get("end_date"))
        if not period:
            continue
        amt = _parse_dollar(row.get(amt_field)) or 0.0
        cell = agg.setdefault((mp_id, period), {
            "travel": 0.0, "hospitality": 0.0, "trips": 0, "events": 0,
            "title": None, "owner_org": None,
        })
        if kind == "travel":
            cell["travel"] += amt
            cell["trips"] += 1
        else:
            cell["hospitality"] += amt
            cell["events"] += 1
        cell["title"] = (row.get("title_en") or cell["title"])
        cell["owner_org"] = (row.get("owner_org_title") or cell["owner_org"])
    return scanned


def run_minister_travel_sync(engine) -> dict:
    """Ingest ministerial travel + hospitality, aggregated per (minister, quarter). Idempotent.
    ALWAYS writes a parliament.ingest_log row; a zero-upsert run returns an error + logs ERROR."""
    fam_idx, full_idx = _build_mp_index(engine)
    agg: dict = {}
    scanned = {}
    problems = []

    for kind, (dataset_id, filename) in _DATASETS.items():
        url = _ckan_csv_url(dataset_id, filename)
        if not url:
            problems.append(f"{kind}:no-url")
            continue
        try:
            scanned[kind] = _accumulate(url, kind, fam_idx, full_idx, agg)
        except Exception as exc:
            problems.append(f"{kind}:stream-fail")
            logger.warning("minister_travel: %s stream failed: %s", kind, exc)

    upserted = 0
    if agg:
        with engine.begin() as c:
            for (mp_id, period), v in agg.items():
                c.execute(text("""
                    INSERT INTO parliament.minister_travel
                        (mp_id, period, travel_cad, hospitality_cad, total_cad,
                         trips, events, title, owner_org)
                    VALUES (:mid, :period, :trav, :hosp, :total, :trips, :events, :title, :org)
                    ON CONFLICT (mp_id, period) DO UPDATE SET
                        travel_cad      = EXCLUDED.travel_cad,
                        hospitality_cad = EXCLUDED.hospitality_cad,
                        total_cad       = EXCLUDED.total_cad,
                        trips           = EXCLUDED.trips,
                        events          = EXCLUDED.events,
                        title           = EXCLUDED.title,
                        owner_org       = EXCLUDED.owner_org,
                        synced_at       = NOW()
                """), {
                    "mid": mp_id, "period": period,
                    "trav": round(v["travel"], 2), "hosp": round(v["hospitality"], 2),
                    "total": round(v["travel"] + v["hospitality"], 2),
                    "trips": v["trips"], "events": v["events"],
                    "title": v["title"], "org": v["owner_org"],
                })
                upserted += 1

    result = {
        "rows_scanned": scanned,
        "ministers": len({mid for mid, _ in agg}),
        "upserted": upserted,
        "problems": problems,
    }
    if upserted == 0:
        result["error"] = (
            "minister_travel upserted 0 rows — CKAN source/schema may have changed "
            f"(problems={problems})"
        )
        logger.error(result["error"])

    try:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted, error) "
                "VALUES ('minister_travel', :f, :u, :e)"
            ), {"f": sum(scanned.values()), "u": upserted, "e": result.get("error")})
    except Exception as exc:
        logger.warning("minister_travel: ingest_log write failed: %s", exc)

    logger.info("minister_travel: %s", result)
    return result


if __name__ == "__main__":
    import os
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    print(run_minister_travel_sync(eng))
