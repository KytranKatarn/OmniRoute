# Canadian Civic Intelligence — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the W.A.T.C.H. civic API service with federal data ingestion, plus 3 new Canadian civic map layers on thenews.kytranempowerment.com.

**Architecture:** Flask API in Docker container (`kytran_watch_api`, port 8099) with SQLite DB. Ingests federal data from Open Canada CKAN + OpenParliament.ca APIs. Serves normalized civic events to Kytran News map layers via REST endpoints with CORS. Three new IIFE layer modules (contracts, parliament, spending) follow the existing layer pattern.

**Tech Stack:** Python 3.12 (Flask, requests, sqlite3), Docker, vanilla JS (deck.gl ScatterplotLayer), Hostinger static deploy.

**Spec:** `docs/superpowers/specs/2026-03-27-canadian-civic-intelligence-design.md`

---

## File Structure

### W.A.T.C.H. API (`watch-api/`)

| File | Responsibility |
|------|---------------|
| `watch-api/Dockerfile` | Python 3.12 Alpine container |
| `watch-api/docker-compose.yml` | Container config, port 8099->8080, resource limits |
| `watch-api/requirements.txt` | Flask, requests |
| `watch-api/app.py` | Flask app, CORS middleware, route registration |
| `watch-api/db.py` | SQLite connection helper, schema init |
| `watch-api/schema.sql` | All CREATE TABLE + INDEX statements |
| `watch-api/routes/health.py` | GET /health endpoint |
| `watch-api/routes/events.py` | GET /api/events, /api/stats endpoints |
| `watch-api/routes/contracts.py` | GET /api/contracts endpoint |
| `watch-api/routes/parliament.py` | GET /api/parliament/bills, /votes, /debates |
| `watch-api/routes/spending.py` | GET /api/spending endpoint |
| `watch-api/ingest/federal.py` | Open Canada CKAN + OpenParliament ingestion |
| `watch-api/ingest/coords.py` | Canadian coordinate mapping (provinces, cities) |

### Kytran News layers (`website/thenews.kytranempowerment.com/`)

| File | Responsibility |
|------|---------------|
| `js/layers/contracts.js` | Gov Contracts map layer (IIFE) |
| `js/layers/parliament.js` | Parliament map layer (IIFE) |
| `js/layers/spending.js` | Public Spending map layer (IIFE) |
| `data/fallback-contracts.json` | Fallback contract data |
| `data/fallback-parliament.json` | Fallback parliament data |
| `data/fallback-spending.json` | Fallback spending data |
| `js/config.js` | Add WATCH_API, layer defs, intervals, fallbacks |
| `index.html` | Add layer toggles, script tags, legend items |
| `js/app.js` | Add init calls for 3 new layers |

---

## Task 1: W.A.T.C.H. API — Docker scaffold + DB schema

**Files:**
- Create: `watch-api/Dockerfile`
- Create: `watch-api/docker-compose.yml`
- Create: `watch-api/requirements.txt`
- Create: `watch-api/schema.sql`
- Create: `watch-api/db.py`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["python3", "app.py"]
```

Save to `watch-api/Dockerfile`.

- [ ] **Step 2: Create requirements.txt**

```
flask==3.1.0
requests==2.32.3
```

Save to `watch-api/requirements.txt`.

- [ ] **Step 3: Create docker-compose.yml**

```yaml
services:
  watch-api:
    build: .
    container_name: kytran_watch_api
    restart: unless-stopped
    ports:
      - "8099:8080"
    volumes:
      - watch_data:/app/data
    mem_limit: 128m
    cpus: 0.5
    read_only: true
    tmpfs:
      - /tmp

volumes:
  watch_data:
```

Save to `watch-api/docker-compose.yml`.

- [ ] **Step 4: Create schema.sql**

```sql
CREATE TABLE IF NOT EXISTS civic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    level TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    amount REAL,
    department TEXT,
    vendor TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    source_url TEXT,
    source_name TEXT,
    raw_id TEXT,
    event_date TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    metadata TEXT,
    UNIQUE(raw_id, source_name)
);

CREATE TABLE IF NOT EXISTS parliament_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_number TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    sponsor TEXT,
    status TEXT,
    introduced_date TEXT,
    last_activity_date TEXT,
    session TEXT,
    source_url TEXT,
    UNIQUE(bill_number, session)
);

CREATE TABLE IF NOT EXISTS parliament_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vote_number INTEGER,
    bill_number TEXT,
    description TEXT,
    result TEXT,
    yeas INTEGER,
    nays INTEGER,
    paired INTEGER,
    vote_date TEXT NOT NULL,
    session TEXT,
    source_url TEXT
);

CREATE TABLE IF NOT EXISTS spending_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    department TEXT NOT NULL,
    category TEXT,
    amount REAL NOT NULL,
    fiscal_year TEXT,
    description TEXT,
    source_url TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    records_fetched INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_civic_events_type ON civic_events(event_type);
CREATE INDEX IF NOT EXISTS idx_civic_events_level ON civic_events(level);
CREATE INDEX IF NOT EXISTS idx_civic_events_jurisdiction ON civic_events(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_civic_events_date ON civic_events(event_date);
CREATE INDEX IF NOT EXISTS idx_spending_jurisdiction ON spending_records(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_bills_status ON parliament_bills(status);
CREATE INDEX IF NOT EXISTS idx_ingest_log_source ON ingest_log(source);
```

Save to `watch-api/schema.sql`.

- [ ] **Step 5: Create db.py**

```python
"""W.A.T.C.H. database — SQLite connection + schema init."""
import os
import sqlite3

DB_PATH = os.environ.get("WATCH_DB_PATH", "/app/data/watch.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.close()
```

Save to `watch-api/db.py`.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add watch-api/Dockerfile watch-api/docker-compose.yml watch-api/requirements.txt watch-api/schema.sql watch-api/db.py
git commit -m "feat(watch): scaffold W.A.T.C.H. API — Dockerfile, schema, db helper"
```

---

## Task 2: W.A.T.C.H. API — Flask app + health endpoint

**Files:**
- Create: `watch-api/app.py`
- Create: `watch-api/routes/__init__.py`
- Create: `watch-api/routes/health.py`

- [ ] **Step 1: Create routes/__init__.py**

```python
"""Route registration for W.A.T.C.H. API."""
```

Save to `watch-api/routes/__init__.py`.

- [ ] **Step 2: Create health route**

```python
"""GET /health — service health check."""
import os
from flask import Blueprint, jsonify
from db import get_db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
def health():
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM civic_events"
        ).fetchone()
        last_ingest = conn.execute(
            "SELECT source, completed_at, status FROM ingest_log "
            "ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        db_path = os.environ.get("WATCH_DB_PATH", "/app/data/watch.db")
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        return jsonify({
            "status": "ok",
            "service": "W.A.T.C.H. Civic API",
            "events_count": row["cnt"],
            "last_ingest": {
                "source": last_ingest["source"] if last_ingest else None,
                "completed_at": last_ingest["completed_at"] if last_ingest else None,
                "status": last_ingest["status"] if last_ingest else None,
            },
            "db_size_bytes": db_size,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
```

Save to `watch-api/routes/health.py`.

- [ ] **Step 3: Create Flask app**

```python
"""W.A.T.C.H. — Watchdog for Accountability, Transparency, Civic Health.

Lightweight Flask API serving Canadian civic data (contracts, parliament, spending).
"""
import http.server
from flask import Flask
from db import init_db
from routes.health import health_bp

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def create_app():
    init_db()
    app.register_blueprint(health_bp)
    return app


if __name__ == "__main__":
    create_app()
    print("W.A.T.C.H. API running on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
```

Save to `watch-api/app.py`.

- [ ] **Step 4: Build and test container**

```bash
cd /mnt/archie_brain/watch-api
docker compose build
docker compose up -d
sleep 3
curl -s http://localhost:8099/health | python3 -m json.tool
```

Expected: `{"status": "ok", "service": "W.A.T.C.H. Civic API", "events_count": 0, ...}`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add watch-api/app.py watch-api/routes/__init__.py watch-api/routes/health.py
git commit -m "feat(watch): Flask app with /health endpoint"
```

---

## Task 3: W.A.T.C.H. API — Canadian coordinates module

**Files:**
- Create: `watch-api/ingest/__init__.py`
- Create: `watch-api/ingest/coords.py`

- [ ] **Step 1: Create ingest/__init__.py**

```python
"""W.A.T.C.H. data ingestion modules."""
```

Save to `watch-api/ingest/__init__.py`.

- [ ] **Step 2: Create coords.py**

```python
"""Canadian coordinate mapping — provinces, territories, and major cities."""

# Federal capital
FEDERAL_COORDS = (-75.70, 45.42)

# Provincial/territorial capitals
PROVINCE_COORDS = {
    "canada": (-75.70, 45.42),
    "ontario": (-79.38, 43.65),
    "british columbia": (-123.12, 49.28),
    "alberta": (-113.49, 53.54),
    "quebec": (-71.21, 46.81),
    "manitoba": (-97.14, 49.90),
    "saskatchewan": (-104.62, 50.45),
    "nova scotia": (-63.57, 44.65),
    "new brunswick": (-66.65, 45.96),
    "newfoundland and labrador": (-52.71, 47.56),
    "prince edward island": (-63.13, 46.24),
    "northwest territories": (-114.37, 62.45),
    "yukon": (-135.05, 60.72),
    "nunavut": (-68.52, 63.75),
}

# Province abbreviation mapping
PROVINCE_ABBREV = {
    "on": "ontario", "bc": "british columbia", "ab": "alberta",
    "qc": "quebec", "mb": "manitoba", "sk": "saskatchewan",
    "ns": "nova scotia", "nb": "new brunswick",
    "nl": "newfoundland and labrador", "pe": "prince edward island",
    "nt": "northwest territories", "yt": "yukon", "nu": "nunavut",
}

# Major city coordinates
CITY_COORDS = {
    "toronto": (-79.38, 43.65),
    "vancouver": (-123.12, 49.28),
    "montreal": (-73.57, 45.50),
    "ottawa": (-75.70, 45.42),
    "calgary": (-114.07, 51.05),
    "edmonton": (-113.49, 53.54),
    "winnipeg": (-97.14, 49.90),
    "halifax": (-63.57, 44.65),
    "victoria": (-123.37, 48.43),
    "quebec city": (-71.21, 46.81),
    "saskatoon": (-106.67, 52.13),
    "regina": (-104.62, 50.45),
    "st. john's": (-52.71, 47.56),
    "fredericton": (-66.65, 45.96),
    "charlottetown": (-63.13, 46.24),
    "whitehorse": (-135.05, 60.72),
    "yellowknife": (-114.37, 62.45),
    "iqaluit": (-68.52, 63.75),
}

import random


def get_coords(jurisdiction, level="federal"):
    """Return (lon, lat) for a jurisdiction with slight jitter to avoid stacking."""
    key = jurisdiction.lower().strip()

    if level == "municipal":
        base = CITY_COORDS.get(key)
    elif level == "provincial":
        base = PROVINCE_COORDS.get(key) or PROVINCE_COORDS.get(
            PROVINCE_ABBREV.get(key, "")
        )
    else:
        base = FEDERAL_COORDS

    if not base:
        base = FEDERAL_COORDS

    jitter_lon = (random.random() - 0.5) * 1.5
    jitter_lat = (random.random() - 0.5) * 1.5
    return (base[0] + jitter_lon, base[1] + jitter_lat)
```

Save to `watch-api/ingest/coords.py`.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add watch-api/ingest/__init__.py watch-api/ingest/coords.py
git commit -m "feat(watch): Canadian coordinate mapping for all provinces, territories, cities"
```

---

## Task 4: W.A.T.C.H. API — Federal data ingestion (Open Canada + OpenParliament)

**Files:**
- Create: `watch-api/ingest/federal.py`

- [ ] **Step 1: Create federal.py**

```python
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
```

Save to `watch-api/ingest/federal.py`.

- [ ] **Step 2: Test ingestion manually**

```bash
cd /mnt/archie_brain/watch-api
docker compose exec watch-api python3 -c "from ingest.federal import run_federal_ingest; print(run_federal_ingest())"
```

Expected: `{'contracts': N, 'bills': N, 'votes': N}` where N > 0.

- [ ] **Step 3: Verify data landed in DB**

```bash
docker compose exec watch-api python3 -c "
from db import get_db
conn = get_db()
for t in ['civic_events', 'parliament_bills', 'parliament_votes', 'ingest_log']:
    row = conn.execute(f'SELECT COUNT(*) as c FROM {t}').fetchone()
    print(f'{t}: {row[\"c\"]} rows')
conn.close()
"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add watch-api/ingest/federal.py
git commit -m "feat(watch): federal data ingestion — Open Canada contracts + OpenParliament bills/votes"
```

---

## Task 5: W.A.T.C.H. API — Events + Stats + Contracts + Parliament endpoints

**Files:**
- Create: `watch-api/routes/events.py`
- Create: `watch-api/routes/contracts.py`
- Create: `watch-api/routes/parliament.py`
- Create: `watch-api/routes/spending.py`
- Modify: `watch-api/app.py` — register new blueprints

- [ ] **Step 1: Create events.py**

```python
"""GET /api/events and /api/stats — unified civic event feed."""
from flask import Blueprint, jsonify, request
from db import get_db

events_bp = Blueprint("events", __name__)


@events_bp.route("/api/events")
def get_events():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        event_type = request.args.get("type")
        if event_type:
            types = event_type.split(",")
            placeholders = ",".join("?" for _ in types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(types)

        level = request.args.get("level")
        if level:
            clauses.append("level = ?")
            params.append(level)

        region = request.args.get("region")
        if region:
            clauses.append("(jurisdiction LIKE ? OR jurisdiction LIKE ?)")
            params.extend([f"%{region}%", f"%{region}%"])

        timespan = request.args.get("timespan", "30d")
        days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(timespan, 30)
        clauses.append(f"event_date >= date('now', '-{days} days')")

        limit = min(int(request.args.get("limit", 100)), 500)
        offset = int(request.args.get("offset", 0))

        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM civic_events WHERE {where} "
            f"ORDER BY event_date DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@events_bp.route("/api/stats")
def get_stats():
    conn = get_db()
    try:
        contracts = conn.execute(
            "SELECT COUNT(*) as c FROM civic_events WHERE event_type='contract'"
        ).fetchone()["c"]
        bills_active = conn.execute(
            "SELECT COUNT(*) as c FROM parliament_bills WHERE status NOT IN ('defeated', 'royal_assent')"
        ).fetchone()["c"]
        votes_recent = conn.execute(
            "SELECT COUNT(*) as c FROM parliament_votes WHERE vote_date >= date('now', '-30 days')"
        ).fetchone()["c"]
        spending_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM spending_records"
        ).fetchone()["total"]

        return jsonify({
            "contracts": contracts,
            "bills_active": bills_active,
            "votes_recent": votes_recent,
            "spending_total": spending_total,
        })
    finally:
        conn.close()
```

Save to `watch-api/routes/events.py`.

- [ ] **Step 2: Create contracts.py**

```python
"""GET /api/contracts — filtered contract search."""
from flask import Blueprint, jsonify, request
from db import get_db

contracts_bp = Blueprint("contracts", __name__)


@contracts_bp.route("/api/contracts")
def get_contracts():
    conn = get_db()
    try:
        clauses = ["event_type = 'contract'"]
        params = []

        level = request.args.get("level")
        if level:
            clauses.append("level = ?")
            params.append(level)

        jurisdiction = request.args.get("jurisdiction")
        if jurisdiction:
            clauses.append("jurisdiction LIKE ?")
            params.append(f"%{jurisdiction}%")

        department = request.args.get("department")
        if department:
            clauses.append("department LIKE ?")
            params.append(f"%{department}%")

        min_amount = request.args.get("min_amount")
        if min_amount:
            clauses.append("amount >= ?")
            params.append(float(min_amount))

        max_amount = request.args.get("max_amount")
        if max_amount:
            clauses.append("amount <= ?")
            params.append(float(max_amount))

        timespan = request.args.get("timespan", "30d")
        days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(timespan, 30)
        clauses.append(f"event_date >= date('now', '-{days} days')")

        limit = min(int(request.args.get("limit", 50)), 500)
        offset = int(request.args.get("offset", 0))

        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM civic_events WHERE {where} "
            f"ORDER BY event_date DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
```

Save to `watch-api/routes/contracts.py`.

- [ ] **Step 3: Create parliament.py**

```python
"""GET /api/parliament/* — bills, votes, debates."""
from flask import Blueprint, jsonify, request
from db import get_db

parliament_bp = Blueprint("parliament", __name__)


@parliament_bp.route("/api/parliament/bills")
def get_bills():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        status = request.args.get("status")
        if status:
            clauses.append("status = ?")
            params.append(status)

        keyword = request.args.get("keyword")
        if keyword:
            clauses.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        limit = min(int(request.args.get("limit", 20)), 100)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM parliament_bills WHERE {where} "
            f"ORDER BY last_activity_date DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@parliament_bp.route("/api/parliament/votes")
def get_votes():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        bill = request.args.get("bill")
        if bill:
            clauses.append("bill_number = ?")
            params.append(bill)

        recent = request.args.get("recent")
        if recent == "true":
            clauses.append("vote_date >= date('now', '-30 days')")

        limit = min(int(request.args.get("limit", 20)), 100)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM parliament_votes WHERE {where} "
            f"ORDER BY vote_date DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
```

Save to `watch-api/routes/parliament.py`.

- [ ] **Step 4: Create spending.py**

```python
"""GET /api/spending — spending records search."""
from flask import Blueprint, jsonify, request
from db import get_db

spending_bp = Blueprint("spending", __name__)


@spending_bp.route("/api/spending")
def get_spending():
    conn = get_db()
    try:
        clauses = ["1=1"]
        params = []

        level = request.args.get("level")
        if level:
            clauses.append("level = ?")
            params.append(level)

        jurisdiction = request.args.get("jurisdiction")
        if jurisdiction:
            clauses.append("jurisdiction LIKE ?")
            params.append(f"%{jurisdiction}%")

        department = request.args.get("department")
        if department:
            clauses.append("department LIKE ?")
            params.append(f"%{department}%")

        fiscal_year = request.args.get("fiscal_year")
        if fiscal_year:
            clauses.append("fiscal_year = ?")
            params.append(fiscal_year)

        category = request.args.get("category")
        if category:
            clauses.append("category = ?")
            params.append(category)

        min_amount = request.args.get("min_amount")
        if min_amount:
            clauses.append("amount >= ?")
            params.append(float(min_amount))

        limit = min(int(request.args.get("limit", 50)), 500)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT * FROM spending_records WHERE {where} "
            f"ORDER BY amount DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()
```

Save to `watch-api/routes/spending.py`.

- [ ] **Step 5: Register all blueprints in app.py**

Add to `watch-api/app.py` in the `create_app()` function, after the health blueprint registration:

```python
from routes.events import events_bp
from routes.contracts import contracts_bp
from routes.parliament import parliament_bp
from routes.spending import spending_bp
```

And in `create_app()`:

```python
    app.register_blueprint(events_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(parliament_bp)
    app.register_blueprint(spending_bp)
```

- [ ] **Step 6: Rebuild and test endpoints**

```bash
cd /mnt/archie_brain/watch-api
docker compose build && docker compose up -d
sleep 3
curl -s http://localhost:8099/api/events?limit=3 | python3 -m json.tool | head -20
curl -s http://localhost:8099/api/stats | python3 -m json.tool
curl -s http://localhost:8099/api/contracts?limit=3 | python3 -m json.tool | head -20
curl -s http://localhost:8099/api/parliament/bills?limit=3 | python3 -m json.tool | head -20
curl -s http://localhost:8099/api/parliament/votes?limit=3 | python3 -m json.tool | head -20
```

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git add watch-api/routes/events.py watch-api/routes/contracts.py watch-api/routes/parliament.py watch-api/routes/spending.py watch-api/app.py
git commit -m "feat(watch): REST endpoints — /api/events, /api/contracts, /api/parliament/*, /api/spending, /api/stats"
```

---

## Task 6: W.A.T.C.H. API — Ingestion CLI + auto-run on startup

**Files:**
- Modify: `watch-api/app.py` — add CLI ingest command and startup trigger

- [ ] **Step 1: Add startup ingestion to app.py**

Add to `watch-api/app.py` after the `create_app()` function and before `if __name__`:

```python
import threading

def _background_ingest():
    """Run initial data ingestion in background thread on startup."""
    import time
    time.sleep(5)  # let Flask fully start
    try:
        from ingest.federal import run_federal_ingest
        run_federal_ingest()
    except Exception as e:
        print(f"[W.A.T.C.H.] Startup ingest failed: {e}")
```

Update the `if __name__` block:

```python
if __name__ == "__main__":
    create_app()
    # Run initial ingest in background
    t = threading.Thread(target=_background_ingest, daemon=True)
    t.start()
    print("W.A.T.C.H. API running on :8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
```

- [ ] **Step 2: Add manual ingest endpoint**

Add to `watch-api/routes/health.py`:

```python
@health_bp.route("/ingest/federal", methods=["POST"])
def trigger_federal_ingest():
    try:
        from ingest.federal import run_federal_ingest
        result = run_federal_ingest()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
```

- [ ] **Step 3: Rebuild, restart, verify data populates**

```bash
cd /mnt/archie_brain/watch-api
docker compose build && docker compose up -d
sleep 20  # wait for background ingest
curl -s http://localhost:8099/api/stats | python3 -m json.tool
curl -s http://localhost:8099/api/events?limit=3 | python3 -m json.tool | head -20
```

Expected: stats shows contracts > 0, bills_active > 0, votes_recent > 0.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add watch-api/app.py watch-api/routes/health.py
git commit -m "feat(watch): background ingestion on startup + POST /ingest/federal trigger"
```

---

## Task 7: Kytran News — Config + fallback data for 3 new layers

**Files:**
- Modify: `website/thenews.kytranempowerment.com/js/config.js`
- Create: `website/thenews.kytranempowerment.com/data/fallback-contracts.json`
- Create: `website/thenews.kytranempowerment.com/data/fallback-parliament.json`
- Create: `website/thenews.kytranempowerment.com/data/fallback-spending.json`

- [ ] **Step 1: Update config.js — add WATCH_API, layer defs, intervals, fallbacks**

Add after the `CORS_PROXY_ALT` line:

```javascript
    /* W.A.T.C.H. Civic Intelligence API */
    var WATCH_API = 'https://civic.kytranempowerment.com/api';
```

Add to the `LAYERS` object after the `social` entry:

```javascript
        contracts:  { label: 'Gov Contracts',   color: '#00bfa5', icon: 'briefcase', default: false },
        parliament: { label: 'Parliament',      color: '#ffd740', icon: 'landmark',  default: false },
        spending:   { label: 'Public Spending', color: '#69f0ae', icon: 'dollar',    default: false },
```

Add to the `INTERVALS` object:

```javascript
        contracts:  600000,   /* 10 min */
        parliament: 600000,   /* 10 min */
        spending:   600000,   /* 10 min */
```

Add to the `FALLBACKS` object:

```javascript
        contracts:  'data/fallback-contracts.json',
        parliament: 'data/fallback-parliament.json',
        spending:   'data/fallback-spending.json',
```

Add `WATCH_API` to the return object:

```javascript
        WATCH_API: WATCH_API,
```

- [ ] **Step 2: Create fallback-contracts.json**

```json
[
  {"id":1,"event_type":"contract","level":"federal","jurisdiction":"Canada","title":"IT Modernization — Shared Services Canada","department":"Shared Services Canada","vendor":"CGI Group","amount":45000000,"lat":45.42,"lon":-75.70,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-15","metadata":"{\"notes\":\"Multi-year IT infrastructure modernization\"}"},
  {"id":2,"event_type":"contract","level":"federal","jurisdiction":"Canada","title":"Naval vessel maintenance — Irving Shipbuilding","department":"National Defence","vendor":"Irving Shipbuilding","amount":120000000,"lat":44.65,"lon":-63.57,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-10","metadata":"{\"notes\":\"Halifax-class frigate maintenance\"}"},
  {"id":3,"event_type":"contract","level":"federal","jurisdiction":"Canada","title":"Highway infrastructure — Trans-Canada expansion","department":"Transport Canada","vendor":"Aecon Group","amount":78000000,"lat":43.65,"lon":-79.38,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-08","metadata":"{\"notes\":\"Ontario section expansion\"}"},
  {"id":4,"event_type":"contract","level":"federal","jurisdiction":"Canada","title":"Health Canada vaccine procurement","department":"Health Canada","vendor":"Moderna Canada","amount":200000000,"lat":45.50,"lon":-73.57,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-05","metadata":"{\"notes\":\"Annual vaccine supply agreement\"}"},
  {"id":5,"event_type":"contract","level":"federal","jurisdiction":"Canada","title":"CBC digital platform upgrade","department":"Canadian Heritage","vendor":"Accenture","amount":15000000,"lat":45.42,"lon":-75.70,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-01","metadata":"{\"notes\":\"Streaming platform modernization\"}"}
]
```

Save to `website/thenews.kytranempowerment.com/data/fallback-contracts.json`.

- [ ] **Step 3: Create fallback-parliament.json**

```json
[
  {"id":101,"event_type":"bill","level":"federal","jurisdiction":"Canada","title":"Bill C-42: Digital Privacy Protection Act","lat":45.42,"lon":-75.70,"source_url":"https://openparliament.ca/bills/44-1/C-42/","source_name":"openparliament","event_date":"2026-03-20","metadata":"{\"bill_number\":\"C-42\",\"sponsor\":\"MP Jane Doe\",\"status\":\"committee\"}"},
  {"id":102,"event_type":"bill","level":"federal","jurisdiction":"Canada","title":"Bill C-55: Clean Energy Transition Act","lat":45.50,"lon":-75.60,"source_url":"https://openparliament.ca/bills/44-1/C-55/","source_name":"openparliament","event_date":"2026-03-18","metadata":"{\"bill_number\":\"C-55\",\"sponsor\":\"MP John Smith\",\"status\":\"introduced\"}"},
  {"id":103,"event_type":"vote","level":"federal","jurisdiction":"Canada","title":"Vote #145: Budget Implementation Act — Passed 180-120","lat":45.35,"lon":-75.80,"source_url":"https://openparliament.ca/votes/44-1/145/","source_name":"openparliament","event_date":"2026-03-15","metadata":"{\"result\":\"passed\",\"yeas\":180,\"nays\":120,\"bill_number\":\"C-38\"}"},
  {"id":104,"event_type":"vote","level":"federal","jurisdiction":"Canada","title":"Vote #142: Carbon Tax Amendment — Defeated 140-170","lat":45.48,"lon":-75.65,"source_url":"https://openparliament.ca/votes/44-1/142/","source_name":"openparliament","event_date":"2026-03-12","metadata":"{\"result\":\"defeated\",\"yeas\":140,\"nays\":170,\"bill_number\":\"C-51\"}"},
  {"id":105,"event_type":"bill","level":"federal","jurisdiction":"Canada","title":"Bill S-15: Senate Reform Act","lat":45.40,"lon":-75.75,"source_url":"https://openparliament.ca/bills/44-1/S-15/","source_name":"openparliament","event_date":"2026-03-10","metadata":"{\"bill_number\":\"S-15\",\"sponsor\":\"Senator A. Brown\",\"status\":\"introduced\"}"}
]
```

Save to `website/thenews.kytranempowerment.com/data/fallback-parliament.json`.

- [ ] **Step 4: Create fallback-spending.json**

```json
[
  {"id":201,"event_type":"spending","level":"federal","jurisdiction":"Canada","title":"National Defence — Operating budget Q1","department":"National Defence","amount":5200000000,"lat":45.42,"lon":-75.70,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-01","metadata":"{\"category\":\"operating\",\"fiscal_year\":\"2025-2026\"}"},
  {"id":202,"event_type":"spending","level":"federal","jurisdiction":"Canada","title":"Health Canada — Transfer payments to provinces","department":"Health Canada","amount":3800000000,"lat":45.50,"lon":-75.60,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-01","metadata":"{\"category\":\"transfer\",\"fiscal_year\":\"2025-2026\"}"},
  {"id":203,"event_type":"spending","level":"federal","jurisdiction":"Canada","title":"Transport Canada — Infrastructure grants","department":"Transport Canada","amount":1200000000,"lat":45.35,"lon":-75.80,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-01","metadata":"{\"category\":\"grants\",\"fiscal_year\":\"2025-2026\"}"},
  {"id":204,"event_type":"spending","level":"federal","jurisdiction":"Canada","title":"IRCC — Settlement services","department":"Immigration, Refugees and Citizenship Canada","amount":890000000,"lat":43.65,"lon":-79.38,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-01","metadata":"{\"category\":\"operating\",\"fiscal_year\":\"2025-2026\"}"},
  {"id":205,"event_type":"spending","level":"federal","jurisdiction":"Canada","title":"Environment Canada — Capital projects","department":"Environment and Climate Change Canada","amount":450000000,"lat":45.48,"lon":-75.65,"source_url":"https://open.canada.ca","source_name":"open_canada","event_date":"2026-03-01","metadata":"{\"category\":\"capital\",\"fiscal_year\":\"2025-2026\"}"}
]
```

Save to `website/thenews.kytranempowerment.com/data/fallback-spending.json`.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add website/thenews.kytranempowerment.com/js/config.js website/thenews.kytranempowerment.com/data/fallback-contracts.json website/thenews.kytranempowerment.com/data/fallback-parliament.json website/thenews.kytranempowerment.com/data/fallback-spending.json
git commit -m "feat(news): config + fallback data for 3 Canadian civic layers"
```

---

## Task 8: Kytran News — Layer JS modules (contracts, parliament, spending)

**Files:**
- Create: `website/thenews.kytranempowerment.com/js/layers/contracts.js`
- Create: `website/thenews.kytranempowerment.com/js/layers/parliament.js`
- Create: `website/thenews.kytranempowerment.com/js/layers/spending.js`

- [ ] **Step 1: Create contracts.js**

```javascript
/* ==========================================================================
   Kytran News — Government Contracts Layer
   W.A.T.C.H. civic data — contract awards by jurisdiction
   ========================================================================== */

var Contracts = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('contracts');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'contracts') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('contracts', refresh, Config.INTERVALS.contracts || 600000);
    }

    function refresh() {
        var timespan = App.getTimeRange();
        var url = Config.WATCH_API + '/events?type=contract&timespan=' + (timespan || '30d') + '&limit=200';
        Fetcher.get(url, {
            sourceKey: 'contracts',
            fallbackUrl: Config.FALLBACKS.contracts,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.contracts || 600000
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('contracts', _data.length);
            EventBus.emit('data:contracts:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('contracts');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'contracts',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var amt = d.amount || 0;
                if (amt > 100000000) return 40000;
                if (amt > 10000000) return 28000;
                if (amt > 1000000) return 18000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.level === 'federal') return [0, 191, 165, 200];
                if (d.level === 'provincial') return [0, 191, 165, 150];
                return [0, 191, 165, 100];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('contracts', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
```

Save to `website/thenews.kytranempowerment.com/js/layers/contracts.js`.

- [ ] **Step 2: Create parliament.js**

```javascript
/* ==========================================================================
   Kytran News — Parliament Layer
   W.A.T.C.H. civic data — bills, votes, debates in Ottawa + capitals
   ========================================================================== */

var Parliament = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('parliament');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'parliament') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('parliament', refresh, Config.INTERVALS.parliament || 600000);
    }

    function refresh() {
        var timespan = App.getTimeRange();
        var url = Config.WATCH_API + '/events?type=bill,vote,debate&timespan=' + (timespan || '30d') + '&limit=200';
        Fetcher.get(url, {
            sourceKey: 'parliament',
            fallbackUrl: Config.FALLBACKS.parliament,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.parliament || 600000
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('parliament', _data.length);
            EventBus.emit('data:parliament:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('parliament');
            KytranMap.removeLayer('parliament-pulse');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'parliament',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.event_type === 'vote') return 22000;
                if (d.event_type === 'bill') return 16000;
                return 12000;
            },
            getFillColor: function (d) {
                if (d.event_type === 'vote') return [255, 215, 64, 220];
                if (d.event_type === 'bill') return [255, 215, 64, 170];
                return [255, 215, 64, 120];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 20,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('parliament', layer);
    }

    function renderPulse() {
        var votes = _data.filter(function (d) { return d.event_type === 'vote'; });
        if (!_visible || votes.length === 0) { KytranMap.removeLayer('parliament-pulse'); return; }

        var now = Date.now();
        var pulseLayer = new deck.ScatterplotLayer({
            id: 'parliament-pulse',
            data: votes,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return 20000 * (1 + cycle * 2);
            },
            stroked: true,
            filled: false,
            getLineColor: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return [255, 215, 64, Math.floor(180 * (1 - cycle))];
            },
            getLineWidth: 2,
            lineWidthMinPixels: 1,
            radiusMinPixels: 5,
            radiusMaxPixels: 40,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('parliament-pulse', pulseLayer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
```

Save to `website/thenews.kytranempowerment.com/js/layers/parliament.js`.

- [ ] **Step 3: Create spending.js**

```javascript
/* ==========================================================================
   Kytran News — Public Spending Layer
   W.A.T.C.H. civic data — government spending by department/jurisdiction
   ========================================================================== */

var Spending = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('spending');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'spending') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('spending', refresh, Config.INTERVALS.spending || 600000);
    }

    function refresh() {
        var timespan = App.getTimeRange();
        var url = Config.WATCH_API + '/events?type=spending&timespan=' + (timespan || '30d') + '&limit=200';
        Fetcher.get(url, {
            sourceKey: 'spending',
            fallbackUrl: Config.FALLBACKS.spending,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.spending || 600000
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('spending', _data.length);
            EventBus.emit('data:spending:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('spending');
            return;
        }

        var CATEGORY_COLORS = {
            capital:  [33, 150, 243, 180],
            operating: [105, 240, 174, 180],
            grants:   [255, 235, 59, 180],
            transfer: [255, 152, 0, 180]
        };

        var layer = new deck.ScatterplotLayer({
            id: 'spending',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var amt = d.amount || 0;
                if (amt > 1000000000) return 45000;
                if (amt > 100000000) return 32000;
                if (amt > 10000000) return 20000;
                return 12000;
            },
            getFillColor: function (d) {
                var meta = {};
                try { meta = JSON.parse(d.metadata || '{}'); } catch (e) {}
                return CATEGORY_COLORS[meta.category] || [105, 240, 174, 150];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('spending', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
```

Save to `website/thenews.kytranempowerment.com/js/layers/spending.js`.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add website/thenews.kytranempowerment.com/js/layers/contracts.js website/thenews.kytranempowerment.com/js/layers/parliament.js website/thenews.kytranempowerment.com/js/layers/spending.js
git commit -m "feat(news): 3 Canadian civic map layers — contracts, parliament, spending"
```

---

## Task 9: Kytran News — Wire layers into HTML + app.js

**Files:**
- Modify: `website/thenews.kytranempowerment.com/index.html`
- Modify: `website/thenews.kytranempowerment.com/js/app.js`

- [ ] **Step 1: Add layer toggle HTML to sidebar**

In `index.html`, after the `social` layer toggle label (search for `data-layer="social"`), add:

```html

            <label class="layer-toggle" data-layer="contracts" style="--layer-color: #00bfa5">
                <div class="layer-toggle__dot"></div>
                <div class="layer-toggle__switch"></div>
                <span class="layer-toggle__label">Gov Contracts</span>
                <span class="layer-toggle__count">0</span>
            </label>

            <label class="layer-toggle" data-layer="parliament" style="--layer-color: #ffd740">
                <div class="layer-toggle__dot"></div>
                <div class="layer-toggle__switch"></div>
                <span class="layer-toggle__label">Parliament</span>
                <span class="layer-toggle__count">0</span>
            </label>

            <label class="layer-toggle" data-layer="spending" style="--layer-color: #69f0ae">
                <div class="layer-toggle__dot"></div>
                <div class="layer-toggle__switch"></div>
                <span class="layer-toggle__label">Public Spending</span>
                <span class="layer-toggle__count">0</span>
            </label>
```

- [ ] **Step 2: Add script tags**

In `index.html`, after the `<script src="js/layers/social.js?v=2"></script>` line, add:

```html
<script src="js/layers/contracts.js?v=2"></script>
<script src="js/layers/parliament.js?v=2"></script>
<script src="js/layers/spending.js?v=2"></script>
```

- [ ] **Step 3: Add legend items**

In `index.html`, after the last `map-legend__item` (Protest), add:

```html
            <div class="map-legend__item">
                <span class="map-legend__dot" style="background:#00bfa5"></span> Contract
            </div>
            <div class="map-legend__item">
                <span class="map-legend__dot" style="background:#ffd740"></span> Parliament
            </div>
            <div class="map-legend__item">
                <span class="map-legend__dot" style="background:#69f0ae"></span> Spending
            </div>
```

- [ ] **Step 4: Add init calls to app.js**

In `app.js`, after the `if (typeof Social !== 'undefined') Social.init();` line (around line 223), add:

```javascript
        if (typeof Contracts !== 'undefined') Contracts.init();
        if (typeof Parliament !== 'undefined') Parliament.init();
        if (typeof Spending !== 'undefined') Spending.init();
```

- [ ] **Step 5: Add Parliament.renderPulse to animation loop**

In `app.js`, find the animation loop where `Conflicts.renderPulse` and `Cyber.renderPulse` are called, add:

```javascript
                Parliament.renderPulse && Parliament.renderPulse();
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add website/thenews.kytranempowerment.com/index.html website/thenews.kytranempowerment.com/js/app.js
git commit -m "feat(news): wire 3 civic layers — toggles, scripts, legend, init, pulse"
```

---

## Task 10: Deploy + NPM proxy + end-to-end test

**Files:**
- No new files — deployment and configuration

- [ ] **Step 1: Set up NPM proxy for civic.kytranempowerment.com**

In NPM Proxy Manager (http://192.168.1.200:81), create a new proxy host:
- Domain: `civic.kytranempowerment.com`
- Forward hostname: `192.168.1.200`
- Forward port: `8099`
- Enable SSL with Let's Encrypt
- Force SSL

Alternatively, if DNS is already set up, the proxy host may already exist. Verify with:

```bash
docker exec nginx-proxy-manager grep -r "civic.kytran" /data/nginx/ 2>/dev/null
```

- [ ] **Step 2: Add DNS record for civic subdomain**

Using Hostinger DNS API or AdGuard DNS, add an A record:
- `civic.kytranempowerment.com` -> `142.169.21.199`

Verify: `dig +short civic.kytranempowerment.com`

- [ ] **Step 3: Deploy thenews to Hostinger**

```bash
cd /mnt/archie_brain/website/thenews.kytranempowerment.com
tar -czf /tmp/thenews_deploy.tar.gz --exclude='.git' --exclude='node_modules' .
```

Then deploy via Hostinger API: `hosting_deployStaticWebsite` with domain `thenews.kytranempowerment.com`.

- [ ] **Step 4: Browser test — verify layers appear**

Navigate to `https://thenews.kytranempowerment.com` in Playwright. Check:
- 3 new layer toggles visible in sidebar (Gov Contracts, Parliament, Public Spending)
- Toggle each layer ON — verify dots appear on map (at least from fallback data)
- Click a dot — verify detail panel shows event info
- Console has 0 errors related to civic layers

- [ ] **Step 5: API test — verify W.A.T.C.H. endpoints**

```bash
curl -s https://civic.kytranempowerment.com/health | python3 -m json.tool
curl -s https://civic.kytranempowerment.com/api/stats | python3 -m json.tool
curl -s https://civic.kytranempowerment.com/api/events?limit=5 | python3 -m json.tool
```

- [ ] **Step 6: Final commit with version bump**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "feat: Canadian Civic Intelligence Phase 1 — W.A.T.C.H. API + 3 map layers on Kytran News"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Docker scaffold + DB schema | Dockerfile, docker-compose, schema.sql, db.py |
| 2 | Flask app + health endpoint | app.py, routes/health.py |
| 3 | Canadian coordinates module | ingest/coords.py |
| 4 | Federal data ingestion | ingest/federal.py |
| 5 | REST API endpoints (events, contracts, parliament, spending) | routes/*.py |
| 6 | Startup ingestion + manual trigger | app.py, routes/health.py |
| 7 | Config + fallback data for 3 layers | config.js, fallback-*.json |
| 8 | Layer JS modules | contracts.js, parliament.js, spending.js |
| 9 | Wire into HTML + app.js | index.html, app.js |
| 10 | Deploy + NPM proxy + e2e test | Infrastructure + verification |
