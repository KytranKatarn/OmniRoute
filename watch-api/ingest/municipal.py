"""Municipal data ingestion — Toronto, Montreal CKAN APIs."""
import json
import time
import requests
from datetime import datetime, timezone
from db import get_db
from ingest.coords import get_coords

REQUEST_DELAY = 2

CITIES = {
    "toronto": {
        "url": "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_search?q=contracts+OR+budget&rows=100&sort=metadata_modified+desc",
        "source": "toronto_opendata",
        "base_url": "https://open.toronto.ca/dataset",
    },
    "montreal": {
        "url": "https://donnees.montreal.ca/api/3/action/package_search?q=contrats+OR+budget&rows=100&sort=metadata_modified+desc",
        "source": "montreal_opendata",
        "base_url": "https://donnees.montreal.ca/dataset",
    },
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


def _ingest_city(city_name, config):
    """Generic CKAN ingestion for a city."""
    conn = get_db()
    source = config["source"]
    try:
        resp = requests.get(
            config["url"], timeout=30, headers={"User-Agent": "WATCH/1.0"}
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("result", {}).get("results", [])

        inserted = 0
        for pkg in results:
            title = pkg.get("title", "Untitled")
            raw_id = pkg.get("id", "")
            dept = pkg.get("organization", {}).get("title", city_name.title())
            date = pkg.get("metadata_modified", _now_iso())[:10]
            notes = pkg.get("notes", "")[:500] if pkg.get("notes") else ""
            lon, lat = get_coords(city_name, "municipal")

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO civic_events "
                    "(event_type, level, jurisdiction, title, department, "
                    "description, lat, lon, source_url, source_name, raw_id, "
                    "event_date, ingested_at, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "contract",
                        "municipal",
                        city_name.title(),
                        title,
                        dept,
                        notes[:200],
                        lat,
                        lon,
                        f"{config['base_url']}/{raw_id}",
                        source,
                        raw_id,
                        date,
                        _now_iso(),
                        json.dumps({"city": city_name, "notes": notes[:300]}),
                    ),
                )
                inserted += 1
            except Exception:
                continue

        conn.commit()
        _log_ingest(conn, source, len(results), inserted, "ok")
        return inserted
    except Exception as e:
        _log_ingest(conn, source, 0, 0, "error", str(e))
        return 0
    finally:
        conn.close()


def run_municipal_ingest():
    """Run all municipal ingestion jobs."""
    print(f"[W.A.T.C.H.] Starting municipal ingest at {_now_iso()}")
    results = {}
    for city, config in CITIES.items():
        count = _ingest_city(city, config)
        results[city] = count
        time.sleep(REQUEST_DELAY)
    total = sum(results.values())
    print(f"[W.A.T.C.H.] Municipal ingest complete: {total} total — {results}")
    return results


if __name__ == "__main__":
    run_municipal_ingest()
