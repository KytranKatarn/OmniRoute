"""Canadian legal news from GDELT DOC API."""
import json
import requests
from datetime import datetime, timezone
from db import get_db

GDELT_LEGAL_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=(law OR regulation OR court OR legal OR legislation) sourcecountry:CA"
    "&mode=artlist&format=json&maxrecords=50&timespan=7d"
)

REQUEST_DELAY = 6  # GDELT rate limit


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


def _parse_gdelt_date(s):
    if not s or len(s) < 8:
        return _now_iso()[:10]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _categorize(title):
    t = title.lower()
    if any(w in t for w in ("court", "judge", "ruling", "verdict", "sentence", "trial")):
        return "court"
    if any(w in t for w in ("regulation", "gazette", "regulatory", "compliance")):
        return "regulatory"
    if any(w in t for w in ("bill", "legislation", "parliament", "law passed")):
        return "legislation"
    if any(w in t for w in ("privacy", "pipeda", "data protection", "law 25")):
        return "privacy"
    return "general"


def run_legal_news_ingest():
    conn = get_db()
    try:
        print(f"[G.A.V.E.L.] Starting legal news ingest at {_now_iso()}")
        resp = requests.get(GDELT_LEGAL_URL, timeout=30, headers={"User-Agent": "LegalWatch/1.0"})
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])

        inserted = 0
        for a in articles:
            title = a.get("title", "")
            url = a.get("url", "")
            domain = a.get("domain", "")
            seen = a.get("seendate", "")
            pub_date = _parse_gdelt_date(seen)
            category = _categorize(title)
            raw_id = url or f"gdelt-{title[:50]}"

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO legal_events "
                    "(event_type, title, description, source_url, source_name, "
                    "category, published_date, ingested_at, raw_id, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "news", title, "", url, domain,
                        category, pub_date, _now_iso(), raw_id,
                        json.dumps({"domain": domain, "language": a.get("language", "")}),
                    ),
                )
                inserted += 1
            except Exception:
                continue

        conn.commit()
        _log_ingest(conn, "gdelt_legal_news", len(articles), inserted, "ok")
        print(f"[G.A.V.E.L.] Legal news ingest: {len(articles)} articles -> {inserted} new")
        return {"articles": len(articles), "inserted": inserted}
    except Exception as e:
        _log_ingest(conn, "gdelt_legal_news", 0, 0, "error", str(e))
        print(f"[G.A.V.E.L.] Legal news ingest failed: {e}")
        return {"error": str(e)}
    finally:
        conn.close()
