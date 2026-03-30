"""Canada Gazette RSS ingestion — regulations and public notices."""
import json
import requests
import feedparser
from datetime import datetime, timezone
from db import get_db

GAZETTE_FEEDS = {
    "part1": {
        "url": "https://gazette.gc.ca/rss/p1-eng.xml",
        "part": "Part I",
        "type": "proposed",
    },
    "part2": {
        "url": "https://gazette.gc.ca/rss/p2-eng.xml",
        "part": "Part II",
        "type": "enacted",
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


def _fetch_entries(url):
    """Fetch feed entries — direct feedparser with requests fallback for CORS proxy."""
    # Try direct feedparser first (works for server-side requests)
    try:
        raw = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; GavelBot/1.0)"})
        raw.raise_for_status()
        feed = feedparser.parse(raw.content)
        if feed.entries:
            return [
                {
                    "title": e.get("title", "Untitled"),
                    "link": e.get("link", ""),
                    "summary": e.get("summary", "")[:500],
                    "published": e.get("published", ""),
                }
                for e in feed.entries
            ]
    except Exception:
        pass
    # Fallback: rss2json proxy
    try:
        proxy_url = f"https://api.rss2json.com/v1/api.json?rss_url={url}"
        resp = requests.get(proxy_url, timeout=15)
        data = resp.json()
        if data.get("status") == "ok" and "items" in data:
            return [
                {
                    "title": item.get("title", "Untitled"),
                    "link": item.get("link", ""),
                    "summary": item.get("description", "")[:500],
                    "published": item.get("pubDate", ""),
                }
                for item in data["items"]
            ]
    except Exception:
        pass
    return []


def _ingest_feed(feed_key, config):
    conn = get_db()
    try:
        entries = _fetch_entries(config["url"])
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
        print(f"[G.A.V.E.L.] gazette_{feed_key}: {len(entries)} fetched, {inserted} inserted")
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
