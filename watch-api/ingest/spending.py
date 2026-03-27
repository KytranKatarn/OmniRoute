"""Federal spending data ingestion — GC InfoBase Expenditures by Standard Object."""
import csv
import io
import json
import requests
from datetime import datetime, timezone
from db import get_db
from ingest.coords import get_coords

SPENDING_CSV_URL = (
    "https://open.canada.ca/data/dataset/a35cf382-690c-4221-a971-cf0fd189a46f"
    "/resource/27e54a33-3c39-42a9-8d58-46dd37c527e5/download/eso_eac_en.csv"
)

# Map standard object categories to simpler categories
CATEGORY_MAP = {
    "Personnel": "operating",
    "Transportation and communications": "operating",
    "Information": "operating",
    "Professional and special services": "operating",
    "Rentals": "operating",
    "Purchased repair and maintenance": "operating",
    "Utilities, materials and supplies": "operating",
    "Acquisition of land, buildings and works": "capital",
    "Acquisition of machinery and equipment": "capital",
    "Transfer payments": "transfer",
    "Public debt charges": "operating",
    "Other subsidies and payments": "grants",
}


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


def ingest_federal_spending():
    """Pull federal spending from GC InfoBase CSV and aggregate by department + fiscal year."""
    conn = get_db()
    try:
        resp = requests.get(SPENDING_CSV_URL, timeout=60, headers={"User-Agent": "WATCH/1.0"})
        resp.raise_for_status()

        # Parse CSV (handle BOM — may be double-encoded or raw UTF-8 BOM bytes)
        raw = resp.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        # Normalize column names (strip quotes, whitespace, BOM remnants)
        reader.fieldnames = [f.strip().strip('"').strip('\ufeff').strip() for f in reader.fieldnames]

        # Aggregate by department + fiscal year (sum across categories)
        dept_totals = {}  # key: (org_name, fy) -> {total, categories}
        row_count = 0
        for row in reader:
            row_count += 1
            org = row.get("org_name", "").strip()
            fy = row.get("fy_ef", "").strip()
            cat_raw = row.get("sobj_en", "").strip()
            amount_str = row.get("expenditures", "0").strip()

            if not org or not fy:
                continue

            try:
                amount = float(amount_str)
            except (ValueError, TypeError):
                continue

            if amount <= 0:
                continue

            category = CATEGORY_MAP.get(cat_raw, "operating")
            key = (org, fy)
            if key not in dept_totals:
                dept_totals[key] = {"total": 0, "categories": {}}
            dept_totals[key]["total"] += amount
            dept_totals[key]["categories"][category] = (
                dept_totals[key]["categories"].get(category, 0) + amount
            )

        # Only insert latest 3 fiscal years to keep data manageable
        all_years = sorted(set(fy for _, fy in dept_totals.keys()), reverse=True)
        recent_years = set(all_years[:3])

        inserted = 0
        for (org, fy), data in dept_totals.items():
            if fy not in recent_years:
                continue

            total = data["total"]
            # Find dominant category
            dominant_cat = max(data["categories"], key=data["categories"].get) if data["categories"] else "operating"
            lon, lat = get_coords("canada", "federal")

            # Insert into spending_records
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO spending_records "
                    "(level, jurisdiction, department, category, amount, "
                    "fiscal_year, description, source_url, ingested_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "federal", "Canada", org, dominant_cat, total, fy,
                        f"{org} — total expenditures for {fy}",
                        "https://open.canada.ca/data/en/dataset/a35cf382-690c-4221-a971-cf0fd189a46f",
                        _now_iso(),
                    ),
                )
            except Exception:
                continue

            # Also insert as civic_event for map layer
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO civic_events "
                    "(event_type, level, jurisdiction, title, department, "
                    "amount, lat, lon, source_url, source_name, raw_id, "
                    "event_date, ingested_at, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "spending", "federal", "Canada",
                        f"{org} — ${total:,.0f} ({fy})",
                        org, total, lat, lon,
                        "https://open.canada.ca/data/en/dataset/a35cf382-690c-4221-a971-cf0fd189a46f",
                        "gc_infobase", f"spending-{org}-{fy}",
                        f"{fy[:4]}-04-01",  # Fiscal year starts April 1
                        _now_iso(),
                        json.dumps({"category": dominant_cat, "fiscal_year": fy,
                                    "breakdown": {k: round(v, 2) for k, v in data["categories"].items()}}),
                    ),
                )
                inserted += 1
            except Exception:
                continue

        conn.commit()
        _log_ingest(conn, "gc_infobase_spending", row_count, inserted, "ok")
        print(f"[W.A.T.C.H.] Spending ingest: {row_count} CSV rows -> {inserted} records ({len(recent_years)} fiscal years)")
        return inserted
    except Exception as e:
        _log_ingest(conn, "gc_infobase_spending", 0, 0, "error", str(e))
        print(f"[W.A.T.C.H.] Spending ingest failed: {e}")
        return 0
    finally:
        conn.close()


def run_spending_ingest():
    """Run all spending ingestion jobs."""
    print(f"[W.A.T.C.H.] Starting spending ingest at {_now_iso()}")
    federal = ingest_federal_spending()
    print(f"[W.A.T.C.H.] Spending ingest complete: {federal} records")
    return {"federal_spending": federal}


if __name__ == "__main__":
    run_spending_ingest()
