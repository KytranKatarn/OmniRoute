"""Canada Gazette RSS ingestion — regulations and public notices."""
import json
import feedparser
from datetime import datetime, timezone
from db import get_db

GAZETTE_FEEDS = {
    "part1": {
        "url": "https://gazette.gc.ca/rss/part1-eng.xml",
        "part": "Part I",
        "type": "proposed",
    },
    "part2": {
        "url": "https://gazette.gc.ca/rss/part2-eng.xml",
        "part": "Part II",
        "type": "enacted",
    },
    "part3": {
        "url": "https://gazette.gc.ca/rss/part3-eng.xml",
        "part": "Part III",
        "type": "act",
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


def _ingest_feed(feed_key, config):
    conn = get_db()
    try:
        feed = feedparser.parse(config["url"])
        entries = feed.entries
        inserted = 0

        for entry in entries:
            title = entry.get("title", "Untitled")
            link = entry.get("link", "")
            summary = entry.get("summary", "")[:500]
            published = entry.get("published", "")
            if published:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(published)
                    pub_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    pub_date = _now_iso()[:10]
            else:
                pub_date = _now_iso()[:10]

            raw_id = link or f"{feed_key}-{title[:50]}"

            # Insert into regulations table
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO regulations "
                    "(title, gazette_part, reg_type, department, description, "
                    "source_url, published_date, ingested_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (title, config["part"], config["type"], "",
                     summary, link, pub_date, _now_iso()),
                )
            except Exception:
                pass

            # Also insert as legal_event
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO legal_events "
                    "(event_type, title, description, source_url, source_name, "
                    "category, published_date, ingested_at, raw_id, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "regulation", title, summary, link,
                        "canada_gazette", config["type"],
                        pub_date, _now_iso(), raw_id,
                        json.dumps({"gazette_part": config["part"], "reg_type": config["type"]}),
                    ),
                )
                inserted += 1
            except Exception:
                continue

        conn.commit()
        _log_ingest(conn, f"gazette_{feed_key}", len(entries), inserted, "ok")
        return inserted
    except Exception as e:
        _log_ingest(conn, f"gazette_{feed_key}", 0, 0, "error", str(e))
        return 0
    finally:
        conn.close()


def run_gazette_ingest():
    print(f"[G.A.V.E.L.] Starting Canada Gazette ingest at {_now_iso()}")
    results = {}
    for key, config in GAZETTE_FEEDS.items():
        results[key] = _ingest_feed(key, config)
    total = sum(results.values())
    print(f"[G.A.V.E.L.] Gazette ingest complete: {total} total — {results}")
    return results
