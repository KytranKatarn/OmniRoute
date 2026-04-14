# C.R.E.E.D. Standalone Extraction — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone dockerized C.R.E.E.D. governance product that accepts events via REST API, scores compliance, and generates dashboards/reports/badges.

**Architecture:** Flask app following the KSO extraction pattern — `create_app()` factory, SQLite for auth/settings + Postgres sidecar for event data, LCARS themed dashboard, REST API at `/api/v1/`. A.R.C.H.I.E. is the first client via a reporter service.

**Tech Stack:** Python 3.12, Flask, SQLite + PostgreSQL 16, Docker, gunicorn, LCARS CSS, weasyprint (PDF reports)

**Reference:** KSO at `/mnt/archie_brain/kytran-server-manager/` is the template. Spec at `docs/superpowers/specs/2026-04-13-creed-governance-platform-design.md`.

---

## File Structure

```
/mnt/archie_brain/kytran-creed/
├── Dockerfile
├── docker-compose.yml
├── .env
├── .dockerignore
├── pyproject.toml
├── README.md
├── secrets/db_password.txt
├── data/                              # gitignored
├── tests/
│   ├── conftest.py                    # Flask test client, test DB
│   ├── test_health.py
│   ├── test_events_api.py
│   ├── test_scores_api.py
│   ├── test_badge_api.py
│   └── test_scoring_engine.py
└── kytran_creed/
    ├── app.py                         # create_app() factory
    ├── config.py                      # KCR_ env prefix
    ├── auth.py                        # Local auth + KytranAuth SSO
    ├── kytran_auth.py                 # Copy from KSO (shared SDK)
    ├── db.py                          # SQLite init + get_db()
    ├── models.py                      # Event, Score, AuditEntry dataclasses
    ├── routes/
    │   ├── __init__.py                # register_all_routes()
    │   ├── dashboard_routes.py        # GET / — LCARS dashboard
    │   ├── api_routes.py              # /api/v1/events, /api/v1/scores, /api/v1/audit
    │   ├── badge_routes.py            # /api/v1/badge/{type} — SVG badges
    │   └── report_routes.py           # /api/v1/report — PDF generation
    ├── services/
    │   ├── scoring_engine.py          # Calculate compliance scores from events
    │   ├── badge_service.py           # SVG badge generation
    │   └── report_service.py          # PDF report generation
    ├── templates/
    │   ├── base.html                  # LCARS base layout
    │   ├── dashboard.html             # Governance dashboard
    │   ├── login.html
    │   └── setup.html
    └── static/
        ├── css/creed.css              # LCARS theme
        └── js/creed.js
```

---

### Task 1: Scaffold repo, Dockerfile, docker-compose.yml

**Files:**
- Create: `kytran-creed/Dockerfile`
- Create: `kytran-creed/docker-compose.yml`
- Create: `kytran-creed/.env`
- Create: `kytran-creed/.dockerignore`
- Create: `kytran-creed/pyproject.toml`
- Create: `kytran-creed/secrets/db_password.txt`
- Create: `kytran-creed/.gitignore`

- [ ] **Step 1: Create directory and pyproject.toml**

```bash
mkdir -p /mnt/archie_brain/kytran-creed/secrets
mkdir -p /mnt/archie_brain/kytran-creed/data
mkdir -p /mnt/archie_brain/kytran-creed/kytran_creed
mkdir -p /mnt/archie_brain/kytran-creed/tests
```

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "kytran-creed"
version = "0.1.0"
description = "C.R.E.E.D. — Compliance, Rights & Ethical Enforcement Directive"
requires-python = ">=3.11"
dependencies = [
    "flask>=3.0",
    "flask-login>=0.6",
    "gunicorn>=21.2",
    "bcrypt>=4.0",
    "psycopg2-binary>=2.9",
    "requests>=2.31",
]

[project.scripts]
kytran-creed = "kytran_creed.app:main"
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
# Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser

WORKDIR /app
COPY pyproject.toml .
COPY kytran_creed/ kytran_creed/
RUN pip install --no-cache-dir .

RUN mkdir -p /data && chown appuser:appgroup /data
VOLUME ["/data"]

USER appuser

ENV KCR_HOST=0.0.0.0
ENV KCR_PORT=8086
ENV KCR_DATA_DIR=/data

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8086/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8086", "--workers", "2", "--timeout", "120", "kytran_creed.app:create_app()"]
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
# docker-compose.yml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    container_name: creed_postgres
    restart: unless-stopped
    read_only: true
    mem_limit: 512m
    cpus: 0.5
    tmpfs:
      - /tmp
      - /run/postgresql
    environment:
      POSTGRES_DB: creed
      POSTGRES_USER: creed
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    secrets:
      - db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U creed -d creed"]
      interval: 10s
      timeout: 5s
      retries: 5

  creed:
    build: .
    container_name: kytran_creed
    restart: unless-stopped
    mem_limit: 512m
    cpus: 0.5
    cap_drop:
      - ALL
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8086:8086"
    environment:
      KCR_SECRET_KEY: ${KCR_SECRET_KEY:-change-me-in-production}
      KCR_PORT: "8086"
      KCR_ADMIN_USER: ${KCR_ADMIN_USER:-admin}
      KCR_ADMIN_PASSWORD: ${KCR_ADMIN_PASSWORD:-}
      DB_HOST: creed_postgres
      DB_PORT: "5432"
      DB_NAME: creed
      DB_USER: creed
      DB_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - ./data:/data
    secrets:
      - db_password

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

- [ ] **Step 4: Create .env, .dockerignore, .gitignore, secrets**

`.env`:
```
KCR_SECRET_KEY=change-me-in-production
KCR_ADMIN_PASSWORD=creed-admin-2026
```

`.dockerignore`:
```
data/
.git/
.env
__pycache__/
*.pyc
tests/
```

`.gitignore`:
```
data/
__pycache__/
*.pyc
*.egg-info/
dist/
.env
secrets/db_password.txt
```

`secrets/db_password.txt`:
```
creed-db-2026
```

- [ ] **Step 5: Commit scaffold**

```bash
cd /mnt/archie_brain/kytran-creed
git init
git add -A
git commit -m "feat: scaffold kytran-creed repo with Docker + Tier 1 compliance"
```

---

### Task 2: Flask app factory, config, db, health endpoint

**Files:**
- Create: `kytran_creed/app.py`
- Create: `kytran_creed/config.py`
- Create: `kytran_creed/db.py`
- Create: `kytran_creed/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write health endpoint test**

```python
# tests/conftest.py
import pytest
import tempfile
import os

@pytest.fixture
def app():
    from kytran_creed.app import create_app
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app = create_app({"TESTING": True, "DB_PATH": db_path, "SECRET_KEY": "test"})
    yield app
    os.close(db_fd)
    os.unlink(db_path)

@pytest.fixture
def client(app):
    return app.test_client()
```

```python
# tests/test_health.py
def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "version" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/archie_brain/kytran-creed && python -m pytest tests/test_health.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kytran_creed'`

- [ ] **Step 3: Implement config.py**

```python
# kytran_creed/config.py
import os

class Config:
    SECRET_KEY = os.environ.get("KCR_SECRET_KEY", "change-me-in-production")
    DATA_DIR = os.environ.get("KCR_DATA_DIR", os.path.expanduser("~/.kytran-creed"))
    DB_PATH = os.path.join(DATA_DIR, "creed.db")
    HOST = os.environ.get("KCR_HOST", "0.0.0.0")
    PORT = int(os.environ.get("KCR_PORT", "8086"))
    DEBUG = os.environ.get("KCR_DEBUG", "false").lower() == "true"
    ADMIN_USER = os.environ.get("KCR_ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.environ.get("KCR_ADMIN_PASSWORD", "")
    # Postgres (optional — for event storage at scale)
    PG_HOST = os.environ.get("DB_HOST", "")
    PG_PORT = int(os.environ.get("DB_PORT", "5432"))
    PG_NAME = os.environ.get("DB_NAME", "creed")
    PG_USER = os.environ.get("DB_USER", "creed")
    PG_PASSWORD_FILE = os.environ.get("DB_PASSWORD_FILE", "")

    @classmethod
    def pg_password(cls):
        if cls.PG_PASSWORD_FILE and os.path.exists(cls.PG_PASSWORD_FILE):
            return open(cls.PG_PASSWORD_FILE).read().strip()
        return os.environ.get("DB_PASSWORD", "")
```

- [ ] **Step 4: Implement db.py**

```python
# kytran_creed/db.py
import sqlite3
import os
import logging

logger = logging.getLogger(__name__)
_db_path = None

def init_db(path):
    global _db_path
    _db_path = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            role TEXT DEFAULT 'viewer',
            display_name TEXT,
            email TEXT,
            sso_provider TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT UNIQUE NOT NULL,
            label TEXT,
            platform_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.close()
    logger.info("SQLite initialized at %s", path)

def get_db():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 5: Implement app.py with health endpoint**

```python
# kytran_creed/__init__.py
```

```python
# kytran_creed/app.py
import os
import logging
from flask import Flask, jsonify
from kytran_creed.config import Config
from kytran_creed.db import init_db

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

def create_app(config=None):
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    if config:
        app.config.update(config)
    else:
        app.config.from_object(Config)

    app.config.setdefault("SECRET_KEY", Config.SECRET_KEY)
    db_path = app.config.get("DB_PATH", Config.DB_PATH)
    init_db(db_path)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "version": __version__})

    return app

def main():
    app = create_app()
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd /mnt/archie_brain/kytran-creed && python -m pytest tests/test_health.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: Flask app factory with config, SQLite, and health endpoint"
```

---

### Task 3: Event ingestion API + Postgres storage

**Files:**
- Create: `kytran_creed/models.py`
- Create: `kytran_creed/routes/__init__.py`
- Create: `kytran_creed/routes/api_routes.py`
- Create: `kytran_creed/pg.py`
- Create: `tests/test_events_api.py`

- [ ] **Step 1: Write event ingestion test**

```python
# tests/test_events_api.py
import json

def test_post_event_returns_201(client):
    event = {
        "event_type": "agent_action",
        "source_platform": "archie",
        "agent_id": "agent-131",
        "agent_name": "Beacon-A",
        "category": "transparency",
        "severity": "info",
        "description": "Agent completed task with full audit trail",
    }
    resp = client.post("/api/v1/events", json=event)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    assert "event_id" in data

def test_post_event_missing_fields_returns_400(client):
    resp = client.post("/api/v1/events", json={"event_type": "agent_action"})
    assert resp.status_code == 400

def test_get_events_returns_list(client):
    # Post one event first
    event = {
        "event_type": "agent_action",
        "source_platform": "archie",
        "agent_id": "agent-1",
        "agent_name": "Test",
        "category": "safety",
        "severity": "info",
        "description": "Test event",
    }
    client.post("/api/v1/events", json=event)
    resp = client.get("/api/v1/events")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data["events"], list)
    assert len(data["events"]) >= 1

def test_get_audit_trail(client):
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "entries" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_events_api.py -v
```

Expected: FAIL — no route for `/api/v1/events`

- [ ] **Step 3: Implement models.py**

```python
# kytran_creed/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

VALID_EVENT_TYPES = {"agent_action", "decision", "violation", "welfare_check", "ethics_review"}
VALID_CATEGORIES = {"transparency", "fairness", "safety", "privacy", "accountability"}
VALID_SEVERITIES = {"info", "warning", "violation", "critical"}
REQUIRED_EVENT_FIELDS = {"event_type", "source_platform", "agent_id", "category", "severity", "description"}

@dataclass
class GovernanceEvent:
    event_type: str
    source_platform: str
    agent_id: str
    agent_name: str
    category: str
    severity: str
    description: str
    metadata: dict = field(default_factory=dict)
    timestamp: Optional[str] = None
    id: Optional[int] = None

    def validate(self) -> list[str]:
        errors = []
        for f in REQUIRED_EVENT_FIELDS:
            if not getattr(self, f, None):
                errors.append(f"Missing required field: {f}")
        if self.event_type and self.event_type not in VALID_EVENT_TYPES:
            errors.append(f"Invalid event_type: {self.event_type}")
        if self.category and self.category not in VALID_CATEGORIES:
            errors.append(f"Invalid category: {self.category}")
        if self.severity and self.severity not in VALID_SEVERITIES:
            errors.append(f"Invalid severity: {self.severity}")
        return errors
```

- [ ] **Step 4: Implement pg.py (Postgres connection for events)**

```python
# kytran_creed/pg.py
import os
import logging
import psycopg2
import psycopg2.extras
from kytran_creed.config import Config

logger = logging.getLogger(__name__)
_pg_available = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS governance_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    source_platform VARCHAR(100) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    agent_name VARCHAR(200),
    category VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    description TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_category ON governance_events(category);
CREATE INDEX IF NOT EXISTS idx_events_severity ON governance_events(severity);
CREATE INDEX IF NOT EXISTS idx_events_platform ON governance_events(source_platform);
CREATE INDEX IF NOT EXISTS idx_events_created ON governance_events(created_at);
"""

def init_pg():
    global _pg_available
    if not Config.PG_HOST:
        logger.info("No PG_HOST configured — using SQLite fallback for events")
        return False
    try:
        conn = _get_pg_conn()
        conn.cursor().execute(SCHEMA)
        conn.commit()
        conn.close()
        _pg_available = True
        logger.info("Postgres initialized at %s:%s/%s", Config.PG_HOST, Config.PG_PORT, Config.PG_NAME)
        return True
    except Exception as e:
        logger.warning("Postgres unavailable, falling back to SQLite: %s", e)
        return False

def _get_pg_conn():
    return psycopg2.connect(
        host=Config.PG_HOST,
        port=Config.PG_PORT,
        dbname=Config.PG_NAME,
        user=Config.PG_USER,
        password=Config.pg_password(),
    )

def get_pg():
    if not _pg_available:
        return None
    try:
        return _get_pg_conn()
    except Exception as e:
        logger.error("Postgres connection failed: %s", e)
        return None

def is_pg_available():
    return _pg_available
```

- [ ] **Step 5: Implement api_routes.py**

```python
# kytran_creed/routes/__init__.py
def register_all_routes(app):
    from kytran_creed.routes.api_routes import api_bp
    app.register_blueprint(api_bp)
```

```python
# kytran_creed/routes/api_routes.py
import json
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from kytran_creed.models import GovernanceEvent, REQUIRED_EVENT_FIELDS
from kytran_creed.pg import get_pg, is_pg_available
from kytran_creed.db import get_db

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/events", methods=["POST"])
def create_event():
    data = request.get_json(silent=True) or {}
    event = GovernanceEvent(
        event_type=data.get("event_type", ""),
        source_platform=data.get("source_platform", ""),
        agent_id=data.get("agent_id", ""),
        agent_name=data.get("agent_name", ""),
        category=data.get("category", ""),
        severity=data.get("severity", ""),
        description=data.get("description", ""),
        metadata=data.get("metadata", {}),
        timestamp=data.get("timestamp"),
    )
    errors = event.validate()
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    event_id = _store_event(event)
    return jsonify({"success": True, "event_id": event_id}), 201


@api_bp.route("/events", methods=["GET"])
def list_events():
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    category = request.args.get("category")
    severity = request.args.get("severity")

    pg = get_pg()
    if pg:
        try:
            cur = pg.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
            query = "SELECT * FROM governance_events WHERE 1=1"
            params = []
            if category:
                query += " AND category = %s"
                params.append(category)
            if severity:
                query += " AND severity = %s"
                params.append(severity)
            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur.execute(query, params)
            events = [dict(r) for r in cur.fetchall()]
            # Convert datetimes to strings
            for e in events:
                for k, v in e.items():
                    if isinstance(v, datetime):
                        e[k] = v.isoformat()
            pg.close()
            return jsonify({"events": events, "total": len(events)})
        except Exception as e:
            logger.error("PG query failed: %s", e)
            pg.close()

    # SQLite fallback
    db = get_db()
    try:
        query = "SELECT * FROM governance_events WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = db.execute(query, params).fetchall()
        events = [dict(r) for r in rows]
        return jsonify({"events": events, "total": len(events)})
    finally:
        db.close()


@api_bp.route("/audit", methods=["GET"])
def audit_trail():
    limit = request.args.get("limit", 100, type=int)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", [limit]
        ).fetchall()
        return jsonify({"entries": [dict(r) for r in rows]})
    finally:
        db.close()


def _store_event(event):
    pg = get_pg()
    if pg:
        try:
            cur = pg.cursor()
            cur.execute(
                """INSERT INTO governance_events
                   (event_type, source_platform, agent_id, agent_name, category, severity, description, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (event.event_type, event.source_platform, event.agent_id,
                 event.agent_name, event.category, event.severity,
                 event.description, json.dumps(event.metadata)),
            )
            event_id = cur.fetchone()[0]
            pg.commit()
            pg.close()
            return event_id
        except Exception as e:
            logger.error("PG insert failed, falling back to SQLite: %s", e)
            pg.close()

    # SQLite fallback
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO governance_events
               (event_type, source_platform, agent_id, agent_name, category, severity, description, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event.event_type, event.source_platform, event.agent_id,
             event.agent_name, event.category, event.severity,
             event.description, json.dumps(event.metadata)),
        )
        db.commit()
        return cur.lastrowid
    finally:
        db.close()
```

- [ ] **Step 6: Update db.py — add governance_events table to SQLite schema**

Add to the `init_db()` CREATE statements:

```sql
CREATE TABLE IF NOT EXISTS governance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    agent_name TEXT,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 7: Update app.py — register routes + init Postgres**

Add to `create_app()` after `init_db()`:

```python
from kytran_creed.pg import init_pg
from kytran_creed.routes import register_all_routes

init_pg()
register_all_routes(app)
```

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_events_api.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: event ingestion API with Postgres + SQLite fallback"
```

---

### Task 4: Scoring engine

**Files:**
- Create: `kytran_creed/services/scoring_engine.py`
- Create: `kytran_creed/services/__init__.py`
- Modify: `kytran_creed/routes/api_routes.py` — add `/api/v1/scores`
- Create: `tests/test_scoring_engine.py`
- Create: `tests/test_scores_api.py`

- [ ] **Step 1: Write scoring engine unit test**

```python
# tests/test_scoring_engine.py
from kytran_creed.services.scoring_engine import calculate_scores

def test_perfect_score_with_no_violations():
    events = [
        {"category": "transparency", "severity": "info"},
        {"category": "safety", "severity": "info"},
        {"category": "fairness", "severity": "info"},
    ]
    scores = calculate_scores(events)
    assert scores["overall"] >= 95.0
    assert "transparency" in scores["by_category"]

def test_violations_reduce_score():
    events = [
        {"category": "safety", "severity": "info"},
        {"category": "safety", "severity": "violation"},
        {"category": "safety", "severity": "critical"},
    ]
    scores = calculate_scores(events)
    assert scores["by_category"]["safety"] < 80.0

def test_empty_events_returns_baseline():
    scores = calculate_scores([])
    assert scores["overall"] == 100.0

def test_grade_assignment():
    events = [{"category": "transparency", "severity": "info"}] * 20
    scores = calculate_scores(events)
    assert scores["grade"] in ("A+", "A", "B+", "B", "C", "D", "F")
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement scoring engine**

```python
# kytran_creed/services/__init__.py
```

```python
# kytran_creed/services/scoring_engine.py
"""
Scoring engine for C.R.E.E.D. compliance.

Calculates compliance scores from governance events.
Each category starts at 100 and is penalized by violations/warnings.
Overall score is the weighted average across categories.
"""

SEVERITY_PENALTIES = {
    "info": 0,
    "warning": 2,
    "violation": 10,
    "critical": 25,
}

CATEGORIES = ["transparency", "fairness", "safety", "privacy", "accountability"]

GRADE_THRESHOLDS = [
    (95, "A+"), (90, "A"), (85, "B+"), (80, "B"), (70, "C"), (60, "D"),
]


def calculate_scores(events: list[dict]) -> dict:
    if not events:
        return {
            "overall": 100.0,
            "grade": "A+",
            "by_category": {c: 100.0 for c in CATEGORIES},
            "event_count": 0,
        }

    category_penalties = {c: 0.0 for c in CATEGORIES}
    category_counts = {c: 0 for c in CATEGORIES}

    for event in events:
        cat = event.get("category", "")
        sev = event.get("severity", "info")
        if cat in category_penalties:
            penalty = SEVERITY_PENALTIES.get(sev, 0)
            category_penalties[cat] += penalty
            category_counts[cat] += 1

    by_category = {}
    for cat in CATEGORIES:
        score = max(0.0, 100.0 - category_penalties[cat])
        by_category[cat] = round(score, 1)

    active_categories = [s for c, s in by_category.items() if category_counts.get(c, 0) > 0]
    overall = round(sum(active_categories) / len(active_categories), 1) if active_categories else 100.0

    grade = "F"
    for threshold, g in GRADE_THRESHOLDS:
        if overall >= threshold:
            grade = g
            break

    return {
        "overall": overall,
        "grade": grade,
        "by_category": by_category,
        "event_count": len(events),
    }
```

- [ ] **Step 4: Write scores API test**

```python
# tests/test_scores_api.py
def test_get_scores(client):
    # Post some events
    for sev in ["info", "info", "warning"]:
        client.post("/api/v1/events", json={
            "event_type": "agent_action",
            "source_platform": "test",
            "agent_id": "a1",
            "agent_name": "Test",
            "category": "safety",
            "severity": sev,
            "description": "test",
        })
    resp = client.get("/api/v1/scores")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "overall" in data
    assert "grade" in data
    assert "by_category" in data
```

- [ ] **Step 5: Add scores endpoint to api_routes.py**

Add to `api_routes.py`:

```python
from kytran_creed.services.scoring_engine import calculate_scores

@api_bp.route("/scores", methods=["GET"])
def get_scores():
    days = request.args.get("days", 30, type=int)
    events = _get_recent_events(days)
    scores = calculate_scores(events)
    return jsonify(scores)


def _get_recent_events(days=30):
    pg = get_pg()
    if pg:
        try:
            cur = pg.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
            cur.execute(
                "SELECT category, severity FROM governance_events WHERE created_at > NOW() - INTERVAL '%s days'",
                [days],
            )
            events = [dict(r) for r in cur.fetchall()]
            pg.close()
            return events
        except Exception as e:
            logger.error("PG query failed: %s", e)
            pg.close()

    db = get_db()
    try:
        rows = db.execute(
            "SELECT category, severity FROM governance_events WHERE created_at > datetime('now', ?)",
            [f"-{days} days"],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()
```

- [ ] **Step 6: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: scoring engine with category penalties and grade assignment"
```

---

### Task 5: SVG badge service

**Files:**
- Create: `kytran_creed/services/badge_service.py`
- Create: `kytran_creed/routes/badge_routes.py`
- Modify: `kytran_creed/routes/__init__.py`
- Create: `tests/test_badge_api.py`

- [ ] **Step 1: Write badge test**

```python
# tests/test_badge_api.py
def test_get_overall_badge_svg(client):
    resp = client.get("/api/v1/badge/overall")
    assert resp.status_code == 200
    assert resp.content_type == "image/svg+xml"
    assert b"<svg" in resp.data
    assert b"C.R.E.E.D." in resp.data

def test_get_category_badge(client):
    resp = client.get("/api/v1/badge/safety")
    assert resp.status_code == 200
    assert b"<svg" in resp.data

def test_invalid_badge_type_returns_404(client):
    resp = client.get("/api/v1/badge/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Implement badge_service.py**

```python
# kytran_creed/services/badge_service.py
"""SVG compliance badge generator. Same grading scale as KSO."""

BADGE_COLORS = {
    "A+": "#22c55e", "A": "#22c55e",  # green
    "B+": "#3b82f6", "B": "#3b82f6",  # blue
    "C": "#eab308",                     # yellow
    "D": "#f97316",                     # orange
    "F": "#ef4444",                     # red
}

BADGE_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="20">
  <linearGradient id="bg" x2="0" y2="100%%">
    <stop offset="0" stop-color="#555"/>
    <stop offset="1" stop-color="#333"/>
  </linearGradient>
  <rect rx="3" width="200" height="20" fill="url(#bg)"/>
  <rect rx="3" x="110" width="90" height="20" fill="{color}"/>
  <text x="6" y="14" fill="#fff" font-family="Arial,sans-serif" font-size="11">C.R.E.E.D. {label}</text>
  <text x="155" y="14" fill="#fff" font-family="Arial,sans-serif" font-size="11" text-anchor="middle">{grade} ({score}%%)</text>
</svg>"""

VALID_TYPES = {"overall", "transparency", "fairness", "safety", "privacy", "accountability"}


def generate_badge(badge_type: str, scores: dict) -> str | None:
    if badge_type not in VALID_TYPES:
        return None

    if badge_type == "overall":
        score = scores["overall"]
        grade = scores["grade"]
        label = "Overall"
    else:
        score = scores["by_category"].get(badge_type, 100.0)
        grade = _score_to_grade(score)
        label = badge_type.title()

    color = BADGE_COLORS.get(grade, "#6b7280")
    return BADGE_TEMPLATE.format(label=label, grade=grade, score=int(score), color=color)


def _score_to_grade(score: float) -> str:
    for threshold, grade in [(95, "A+"), (90, "A"), (85, "B+"), (80, "B"), (70, "C"), (60, "D")]:
        if score >= threshold:
            return grade
    return "F"
```

- [ ] **Step 3: Implement badge_routes.py**

```python
# kytran_creed/routes/badge_routes.py
from flask import Blueprint, Response, jsonify
from kytran_creed.services.badge_service import generate_badge, VALID_TYPES
from kytran_creed.services.scoring_engine import calculate_scores
from kytran_creed.routes.api_routes import _get_recent_events

badge_bp = Blueprint("badge", __name__, url_prefix="/api/v1")


@badge_bp.route("/badge/<badge_type>")
def get_badge(badge_type):
    if badge_type not in VALID_TYPES:
        return jsonify({"error": f"Invalid badge type. Valid: {sorted(VALID_TYPES)}"}), 404

    events = _get_recent_events(30)
    scores = calculate_scores(events)
    svg = generate_badge(badge_type, scores)
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "no-cache"})
```

- [ ] **Step 4: Register badge routes in __init__.py**

```python
# kytran_creed/routes/__init__.py
def register_all_routes(app):
    from kytran_creed.routes.api_routes import api_bp
    from kytran_creed.routes.badge_routes import badge_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(badge_bp)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: SVG compliance badge service with grade-based colors"
```

---

### Task 6: LCARS dashboard

**Files:**
- Create: `kytran_creed/routes/dashboard_routes.py`
- Create: `kytran_creed/templates/base.html`
- Create: `kytran_creed/templates/dashboard.html`
- Create: `kytran_creed/templates/login.html`
- Create: `kytran_creed/static/css/creed.css`
- Create: `kytran_creed/static/js/creed.js`
- Modify: `kytran_creed/routes/__init__.py`

This task creates the visual dashboard. The LCARS styling follows the platform pattern: elbow corners, segment bars, sci-fi fonts (Antonio, Orbitron, IBM Plex Mono). The dashboard shows live compliance scores, recent events, and category breakdowns.

- [ ] **Step 1: Create base.html (LCARS frame)**

Full LCARS base template with sidebar elbow, header bar, content frame. Include CSS/JS references, flash messages, and login/logout nav.

- [ ] **Step 2: Create dashboard.html**

Dashboard with: hero stats (overall score, grade, event count, agent count), category score cards, recent events table, severity breakdown chart area.

- [ ] **Step 3: Create login.html**

Simple LCARS-styled login form.

- [ ] **Step 4: Create creed.css**

LCARS theme with `--creed-accent: #8b5cf6` (purple, matching C.R.E.E.D.'s existing color), elbow corners, segment bars, responsive at 480/768/1024px.

- [ ] **Step 5: Create creed.js**

Dashboard JS: fetch `/api/v1/scores` and `/api/v1/events` on load, render into DOM, auto-refresh every 30s.

- [ ] **Step 6: Implement dashboard_routes.py**

```python
# kytran_creed/routes/dashboard_routes.py
from flask import Blueprint, render_template

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    return render_template("dashboard.html")
```

- [ ] **Step 7: Register dashboard routes, add login_manager**

Update `routes/__init__.py` to register `dashboard_bp`. Update `app.py` to add `flask_login` setup with `login_manager`.

- [ ] **Step 8: Browser test the dashboard**

```bash
# Start locally
cd /mnt/archie_brain/kytran-creed && python -m kytran_creed.app
# Open http://192.168.1.200:8086/ in browser
```

Verify: LCARS frame renders, scores display, events table loads.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: LCARS governance dashboard with live scores and event feed"
```

---

### Task 7: Local auth + admin seeding

**Files:**
- Create: `kytran_creed/auth.py`
- Modify: `kytran_creed/app.py`

- [ ] **Step 1: Implement auth.py**

Follow KSO pattern exactly: `User(UserMixin)`, `verify_password()` with bcrypt, `admin_required` decorator, `setup_required()`, `create_admin()`, login/logout routes.

- [ ] **Step 2: Update app.py**

Add `login_manager` init, `@login_manager.user_loader`, auto-seed admin from env vars, `@app.before_request` redirect to setup if no admin.

- [ ] **Step 3: Test login flow**

Start app, verify redirect to login, create admin, login, access dashboard.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: local auth with bcrypt, admin seeding, and login flow"
```

---

### Task 8: Docker build + deploy + register

**Files:**
- Modify: `/mnt/archie_brain/.claude/rules/operational-state.md`
- Create: `kytran-creed/README.md`

- [ ] **Step 1: Build and start containers**

```bash
cd /mnt/archie_brain/kytran-creed
docker compose up -d --build
```

- [ ] **Step 2: Verify health endpoint**

```bash
curl http://192.168.1.200:8086/health
```

Expected: `{"status": "ok", "version": "0.1.0"}`

- [ ] **Step 3: Verify event API end-to-end**

```bash
curl -X POST http://192.168.1.200:8086/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{"event_type":"agent_action","source_platform":"archie","agent_id":"agent-1","agent_name":"Test","category":"safety","severity":"info","description":"test"}'
```

Expected: `{"success": true, "event_id": 1}`

- [ ] **Step 4: Write README.md**

Quick-start install instructions, API overview, environment variables.

- [ ] **Step 5: Register in operational-state.md**

Add row:
```
| C.R.E.E.D. Governance | 8086 | creed.kytranempowerment.com | kytran_creed | Hub |
```

- [ ] **Step 6: Add DNS record + NPM proxy host**

Create `creed.kytranempowerment.com` A record at Hostinger, add NPM proxy host forwarding to 192.168.1.200:8086 with SSL.

- [ ] **Step 7: Commit all**

```bash
git add -A && git commit -m "feat: Docker deploy, README, and platform registration"
```

---

### Task 9: Complete project tasks in ARCHIE

- [ ] **Step 1: Complete platform tasks**

```
mcp complete_task 1811 — "Repo scaffolded with Docker + Tier 1 compliance"
mcp complete_task 1812 — "Event API + scoring engine implemented"
mcp complete_task 1813 — "LCARS dashboard + badges implemented"
mcp complete_task 1814 — "Auth implemented, SSO deferred to Tier 2"
mcp complete_task 1815 — "README written, API docs deferred to Phase 3"
```

- [ ] **Step 2: Log decision**

```
mcp log_decision — "C.R.E.E.D. standalone extracted as kytran-creed on port 8086"
```

---

## Verification Checklist

After all tasks:
- [ ] `docker compose up` starts both containers (postgres + creed)
- [ ] `/health` returns 200
- [ ] `POST /api/v1/events` stores events in Postgres
- [ ] `GET /api/v1/scores` returns compliance scores
- [ ] `GET /api/v1/badge/overall` returns SVG badge
- [ ] Dashboard renders with LCARS theme at 192.168.1.200:8086
- [ ] Login/logout works
- [ ] SSL works at creed.kytranempowerment.com (if NPM configured)
