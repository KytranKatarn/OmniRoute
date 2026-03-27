"""Federal data ingestion — Open Canada CKAN + OpenParliament.ca."""
import json
import time
import requests
from datetime import datetime, timezone
from db import get_db
from ingest.coords import get_coords

OPEN_CANADA_BASE = "https://open.canada.ca/data/en/api/3/action"
OPEN_PARLIAMENT_BASE = "https://api.openparliament.ca"
REQUEST_DELAY = 2  # seconds between API calls


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_ingest(conn, source, fetched, inserted, status, error=None):
    conn.execute(
        "INSERT INTO ingest_log (source, records_fetched, records_inserted, "
        "status, error_message, started_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source, fetched, inserted, status, error, _now_iso(), _now_iso()),
    )
    conn.commit()


def ingest_contracts():
    """Pull federal contracts from Open Canada CKAN."""
    conn = get_db()
    try:
        url = (
            f"{OPEN_CANADA_BASE}/package_search"
            "?q=contracts&fq=organization:tbs-sct"
            "&rows=100&sort=metadata_modified+desc"
        )
        resp = requests.get(url, timeout=30, headers={"User-Agent": "WATCH/1.0"})
        resp.raise_for_status()
        data = resp.json()
        results = data.get("result", {}).get("results", [])

        inserted = 0
        for pkg in results:
            title = pkg.get("title", "Untitled contract")
            raw_id = pkg.get("id", "")
            dept = pkg.get("organization", {}).get("title", "Government of Canada")
            date = pkg.get("metadata_modified", _now_iso())[:10]
            lon, lat = get_coords("canada", "federal")

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO civic_events "
                    "(event_type, level, jurisdiction, title, department, "
                    "lat, lon, source_url, source_name, raw_id, event_date, "
                    "ingested_at, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "contract", "federal", "Canada", title, dept,
                        lat, lon,
                        f"https://open.canada.ca/data/en/dataset/{raw_id}",
                        "open_canada", raw_id, date, _now_iso(),
                        json.dumps({"notes": pkg.get("notes", "")[:500]}),
                    ),
                )
                inserted += 1
            except Exception:
                continue

        conn.commit()
        _log_ingest(conn, "open_canada_contracts", len(results), inserted, "ok")
        return inserted
    except Exception as e:
        _log_ingest(conn, "open_canada_contracts", 0, 0, "error", str(e))
        return 0
    finally:
        conn.close()


def ingest_bills():
    """Pull bills from OpenParliament.ca."""
    conn = get_db()
    try:
        url = f"{OPEN_PARLIAMENT_BASE}/bills/?format=json&limit=50"
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "WATCH/1.0",
            "Accept": "application/json",
        })
        resp.raise_for_status()
        data = resp.json()
        bills = data.get("objects", [])

        inserted = 0
        for bill in bills:
            bill_number = bill.get("number", "")
            name = bill.get("name", {})
            title = name.get("en", "") if isinstance(name, dict) else str(name)
            if not title:
                title = f"Bill {bill_number}"
            session = bill.get("session", "")
            introduced = bill.get("introduced", "")
            sponsor_info = bill.get("sponsor_politician", {})
            sponsor = sponsor_info.get("name", "") if isinstance(sponsor_info, dict) else ""
            status = bill.get("status", {})
            status_en = status.get("en", "introduced") if isinstance(status, dict) else str(status)
            bill_url = bill.get("url", "")
            if bill_url and not bill_url.startswith("http"):
                bill_url = f"https://openparliament.ca{bill_url}"

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO parliament_bills "
                    "(bill_number, title, sponsor, status, introduced_date, "
                    "last_activity_date, session, source_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        bill_number, title, sponsor, status_en,
                        introduced, introduced, session, bill_url,
                    ),
                )
                inserted += 1
            except Exception:
                continue

            # Also insert as civic_event for map layer
            lon, lat = get_coords("canada", "federal")
            conn.execute(
                "INSERT OR IGNORE INTO civic_events "
                "(event_type, level, jurisdiction, title, "
                "lat, lon, source_url, source_name, raw_id, event_date, "
                "ingested_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "bill", "federal", "Canada", title,
                    lat, lon, bill_url, "openparliament",
                    f"bill-{bill_number}-{session}",
                    introduced or _now_iso()[:10], _now_iso(),
                    json.dumps({"bill_number": bill_number, "sponsor": sponsor,
                                "status": status_en}),
                ),
            )

        conn.commit()
        _log_ingest(conn, "openparliament_bills", len(bills), inserted, "ok")
        time.sleep(REQUEST_DELAY)
        return inserted
    except Exception as e:
        _log_ingest(conn, "openparliament_bills", 0, 0, "error", str(e))
        return 0
    finally:
        conn.close()


def ingest_votes():
    """Pull recent votes from OpenParliament.ca."""
    conn = get_db()
    try:
        url = f"{OPEN_PARLIAMENT_BASE}/votes/?format=json&limit=30"
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "WATCH/1.0",
            "Accept": "application/json",
        })
        resp.raise_for_status()
        data = resp.json()
        votes = data.get("objects", [])

        inserted = 0
        for vote in votes:
            vote_number = vote.get("number", 0)
            bill_url = vote.get("bill_url", "")
            bill_number = bill_url.split("/")[-2] if bill_url else ""
            desc = vote.get("description", {})
            description = desc.get("en", "") if isinstance(desc, dict) else str(desc)
            result = vote.get("result", "unknown")
            yeas = vote.get("yea_total", 0)
            nays = vote.get("nay_total", 0)
            paired = vote.get("paired_total", 0)
            vote_date = vote.get("date", _now_iso()[:10])
            session = vote.get("session", "")
            vote_url = vote.get("url", "")
            if vote_url and not vote_url.startswith("http"):
                vote_url = f"https://openparliament.ca{vote_url}"

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO parliament_votes "
                    "(vote_number, bill_number, description, result, "
                    "yeas, nays, paired, vote_date, session, source_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        vote_number, bill_number, description, result,
                        yeas, nays, paired, vote_date, session, vote_url,
                    ),
                )
                inserted += 1
            except Exception:
                continue

            # Also insert as civic_event
            lon, lat = get_coords("canada", "federal")
            conn.execute(
                "INSERT OR IGNORE INTO civic_events "
                "(event_type, level, jurisdiction, title, "
                "lat, lon, source_url, source_name, raw_id, event_date, "
                "ingested_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "vote", "federal", "Canada",
                    f"Vote #{vote_number}: {description[:100]}",
                    lat, lon, vote_url, "openparliament",
                    f"vote-{vote_number}-{session}",
                    vote_date, _now_iso(),
                    json.dumps({"result": result, "yeas": yeas, "nays": nays,
                                "bill_number": bill_number}),
                ),
            )

        conn.commit()
        _log_ingest(conn, "openparliament_votes", len(votes), inserted, "ok")
        time.sleep(REQUEST_DELAY)
        return inserted
    except Exception as e:
        _log_ingest(conn, "openparliament_votes", 0, 0, "error", str(e))
        return 0
    finally:
        conn.close()


def run_federal_ingest():
    """Run all federal ingestion jobs. Called by agent loop or CLI."""
    print(f"[W.A.T.C.H.] Starting federal ingest at {_now_iso()}")
    contracts = ingest_contracts()
    time.sleep(REQUEST_DELAY)
    bills = ingest_bills()
    votes = ingest_votes()
    print(
        f"[W.A.T.C.H.] Federal ingest complete: "
        f"{contracts} contracts, {bills} bills, {votes} votes"
    )
    return {"contracts": contracts, "bills": bills, "votes": votes}


if __name__ == "__main__":
    run_federal_ingest()
