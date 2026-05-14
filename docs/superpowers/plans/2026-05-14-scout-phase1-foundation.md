# S.C.O.U.T. Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a working archie_scraper container (port 4243) with browser pool, job queue, 3 MVP skills, and a DHQ Scout tab that surfaces job status to operators.

**Architecture:** Flask + Playwright Chromium in a new Docker container. scout_jobs table holds the queue — a background worker thread claims pending rows, claims a browser slot, runs the matching skill, stores results. DHQ Scout tab (mirrors S.I.G.N.A.L. pattern) shows overview + jobs list with approve/reject actions.

**Tech Stack:** Python 3.11, Flask 3.0, Playwright 1.44, psycopg2, PostgreSQL scout_jobs table, docker-compose, Jinja2 + vanilla JS (DHQ pattern)

---

## File Map

**New — archie-scraper/**
```
archie-scraper/
├── Dockerfile
├── requirements.txt
├── database.py          DB connection context manager
├── app.py               Flask app + route handlers
├── browser_pool.py      3-slot Chromium pool, claim/release
├── proxy_selector.py    Egress tier selection by domain
├── screenshot_store.py  Save PNGs to /mnt/screenshots/{job_id}/
├── job_worker.py        Polls scout_jobs, dispatches to pool
└── skills/
    ├── __init__.py
    ├── web_scrape.py
    ├── ux_audit.py
    └── procurement_sync.py
```

**New — platform_v2/**
```
platform_v2/tools/department_hq/scout_routes.py
platform_v2/static/js/scout.js
```

**New — database/migrations/**
```
database/migrations/380_scout_jobs.sql
```

**Modified**
```
docker-compose.yml                                 add archie_scraper service
platform_v2/tools/department_hq/__init__.py        register_scout_routes call
platform_v2/templates/tools/department_hq.html     add Scout tab button + panel
```

---

## Task 1: DB Migration — scout_jobs table

**Files:**
- Create: `database/migrations/380_scout_jobs.sql`

- [ ] **Step 1: Write the migration**

```sql
-- database/migrations/380_scout_jobs.sql
CREATE TABLE IF NOT EXISTS scout_jobs (
    id              SERIAL PRIMARY KEY,
    job_type        VARCHAR(50) NOT NULL,
    target_url      TEXT NOT NULL,
    params          JSONB DEFAULT '{}',
    egress_tier     INTEGER DEFAULT 1,
    egress_ip       VARCHAR(50),
    status          VARCHAR(20) DEFAULT 'pending'
                    CHECK (status IN ('pending','running','completed','failed',
                                      'needs_review','approved','rejected')),
    requested_by    VARCHAR(100),
    agent_id        INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    data            JSONB,
    screenshots     JSONB DEFAULT '[]',
    network_log     JSONB DEFAULT '[]',
    findings        TEXT,
    error_log       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     VARCHAR(100),
    auto_approve    BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_scout_jobs_status
    ON scout_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scout_jobs_type
    ON scout_jobs(job_type, status);
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /path/to/database/migrations/380_scout_jobs.sql
```

Expected: `CREATE TABLE` + `CREATE INDEX` x2, no errors.

- [ ] **Step 3: Verify table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d scout_jobs"
```

Expected: table with 20 columns including id, job_type, status, auto_approve.

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/scout-phase1
git add database/migrations/380_scout_jobs.sql
git commit -m "feat(scout): add scout_jobs migration — job queue table"
```

---

## Task 2: archie-scraper — Scaffold (Dockerfile + requirements + database.py)

**Files:**
- Create: `archie-scraper/Dockerfile`
- Create: `archie-scraper/requirements.txt`
- Create: `archie-scraper/database.py`
- Create: `archie-scraper/tests/__init__.py`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
# archie-scraper/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget curl gnupg2 libglib2.0-0 libnss3 libnspr4 \
    libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

EXPOSE 4243
CMD ["python", "app.py"]
```

- [ ] **Step 2: Create requirements.txt**

```text
flask==3.0.3
playwright==1.44.0
psycopg2-binary==2.9.9
pillow==10.3.0
```

- [ ] **Step 3: Create database.py**

```python
# archie-scraper/database.py
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras


@contextmanager
def get_db():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 4: Create tests/__init__.py** (empty)

```bash
mkdir -p archie-scraper/tests
touch archie-scraper/tests/__init__.py
```

- [ ] **Step 5: Write and run smoke test**

```python
# archie-scraper/tests/test_database.py
import os
import pytest

os.environ.setdefault("DB_HOST", "archie_database")
os.environ.setdefault("DB_NAME", "archie")
os.environ.setdefault("DB_USER", "archie")
os.environ.setdefault("DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

from database import get_db


def test_scout_jobs_table_exists():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM scout_jobs")
            row = cur.fetchone()
    assert row["cnt"] >= 0
```

Run (from inside the archie_platform container which shares the DB):

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/mnt/archie_brain/archie-scraper')
from database import get_db
with get_db() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) as cnt FROM scout_jobs')
        print('scout_jobs rows:', cur.fetchone()['cnt'])
"
```

Expected: `scout_jobs rows: 0`

- [ ] **Step 6: Commit**

```bash
git add archie-scraper/
git commit -m "feat(scout): archie-scraper scaffold — Dockerfile, requirements, database.py"
```

---

## Task 3: Browser Pool

**Files:**
- Create: `archie-scraper/browser_pool.py`
- Create: `archie-scraper/tests/test_browser_pool.py`

- [ ] **Step 1: Write the failing test**

```python
# archie-scraper/tests/test_browser_pool.py
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["SCOUT_POOL_SIZE"] = "2"
os.environ["SCOUT_VPS_SOCKS"] = ""
os.environ["SCOUT_PROXY_URL"] = ""

from unittest.mock import MagicMock, patch


def _patched_pool():
    """Return a BrowserPool with Playwright mocked out."""
    with patch("browser_pool.sync_playwright") as mock_pw_cls:
        mock_pw = MagicMock()
        mock_pw_cls.return_value.start.return_value = mock_pw
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_ctx = MagicMock()
        mock_browser.new_context.return_value = mock_ctx
        mock_page = MagicMock()
        mock_ctx.new_page.return_value = mock_page
        import importlib, browser_pool
        importlib.reload(browser_pool)
        pool = browser_pool.BrowserPool()
        return pool, mock_ctx, mock_page


def test_pool_initializes_with_correct_size():
    pool, _, _ = _patched_pool()
    assert pool.size == 2
    assert pool.available_count() == 2


def test_claim_and_release_cycle():
    pool, _, mock_page = _patched_pool()
    assert pool.available_count() == 2
    slot_id, page = pool.claim(egress_tier=1)
    assert pool.available_count() == 1
    pool.release(slot_id, page)
    assert pool.available_count() == 2
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd archie-scraper && python -m pytest tests/test_browser_pool.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'BrowserPool' from 'browser_pool'`

- [ ] **Step 3: Implement browser_pool.py**

```python
# archie-scraper/browser_pool.py
import logging
import os
import threading

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

POOL_SIZE = int(os.getenv("SCOUT_POOL_SIZE", "3"))


class BrowserPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[int, str] = {i: "free" for i in range(self.size)}
        self._pw = sync_playwright().start()
        self._browsers: dict = {}
        self._contexts: dict = {}
        self._slot_proxy: dict[int, str | None] = {
            0: None,
            1: os.getenv("SCOUT_VPS_SOCKS") or None,
            2: os.getenv("SCOUT_PROXY_URL") or None,
        }
        self._init_pool()

    def _init_pool(self) -> None:
        for slot_id in range(self.size):
            proxy = self._slot_proxy.get(slot_id)
            browser = self._pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx_opts: dict = {"viewport": {"width": 1280, "height": 800}}
            if proxy:
                ctx_opts["proxy"] = {"server": proxy}
            context = browser.new_context(**ctx_opts)
            self._browsers[slot_id] = browser
            self._contexts[slot_id] = context
            logger.info("Pool slot %d ready (proxy=%s)", slot_id, proxy or "direct")

    def claim(self, egress_tier: int = 1) -> tuple[int, any]:
        preferred = max(0, min(egress_tier - 1, self.size - 1))
        order = [preferred] + [i for i in range(self.size) if i != preferred]
        with self._lock:
            for slot_id in order:
                if self._slots[slot_id] == "free":
                    self._slots[slot_id] = "busy"
                    page = self._contexts[slot_id].new_page()
                    return slot_id, page
        raise RuntimeError("No browser slots available — all busy")

    def release(self, slot_id: int, page: any) -> None:
        page.close()
        with self._lock:
            self._slots[slot_id] = "free"

    def available_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._slots.values() if s == "free")

    def status(self) -> dict:
        with self._lock:
            return {"pool_size": self.size, "slots": dict(self._slots)}

    @property
    def size(self) -> int:
        return POOL_SIZE
```

- [ ] **Step 4: Run test — verify it passes**

```bash
cd archie-scraper && python -m pytest tests/test_browser_pool.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add archie-scraper/browser_pool.py archie-scraper/tests/test_browser_pool.py
git commit -m "feat(scout): browser_pool.py — 3-slot Chromium pool with claim/release"
```

---

## Task 4: Proxy Selector + Screenshot Store

**Files:**
- Create: `archie-scraper/proxy_selector.py`
- Create: `archie-scraper/screenshot_store.py`
- Create: `archie-scraper/tests/test_proxy_selector.py`

- [ ] **Step 1: Write proxy selector test**

```python
# archie-scraper/tests/test_proxy_selector.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from proxy_selector import select_egress


def test_gc_ca_routes_to_tier1():
    assert select_egress("https://canadabuys.canada.ca/en/tenders") == 1


def test_canada_ca_routes_to_tier1():
    assert select_egress("https://open.canada.ca/data") == 1


def test_explicit_tier_overrides_domain():
    assert select_egress("https://canadabuys.canada.ca/tenders", requested_tier=2) == 2


def test_unknown_domain_defaults_to_tier1():
    assert select_egress("https://httpbin.org/get") == 1


def test_gouv_qc_routes_to_tier1():
    assert select_egress("https://seao.ca/openweb/index.do") == 1
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd archie-scraper && python -m pytest tests/test_proxy_selector.py -v 2>&1 | head -5
```

Expected: `ImportError: No module named 'proxy_selector'`

- [ ] **Step 3: Implement proxy_selector.py**

```python
# archie-scraper/proxy_selector.py
from urllib.parse import urlparse

_GOV_SUFFIXES = (
    ".gc.ca",
    ".canada.ca",
    ".gouv.qc.ca",
    ".seao.ca",
    ".bcbid.gov.bc.ca",
    ".canlii.org",
    ".tpsgc-pwgsc.gc.ca",
)


def select_egress(target_url: str, requested_tier: int = None) -> int:
    if requested_tier is not None:
        return requested_tier
    try:
        domain = urlparse(target_url).netloc.lower()
    except Exception:
        return 1
    for suffix in _GOV_SUFFIXES:
        if domain.endswith(suffix) or domain == suffix.lstrip("."):
            return 1
    return 1  # safe default: hub residential
```

- [ ] **Step 4: Implement screenshot_store.py**

```python
# archie-scraper/screenshot_store.py
import os
from pathlib import Path

SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "/mnt/screenshots")


def save_screenshot(job_id: int, step: str, page) -> str:
    """Take full-page screenshot, return relative path string."""
    job_dir = Path(SCREENSHOT_DIR) / str(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / f"{step}.png"
    page.screenshot(path=str(path), full_page=True)
    return f"{job_id}/{step}.png"


def screenshot_entry(step: str, path: str, caption: str = "") -> dict:
    return {"step": step, "path": path, "caption": caption}
```

- [ ] **Step 5: Run tests**

```bash
cd archie-scraper && python -m pytest tests/test_proxy_selector.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add archie-scraper/proxy_selector.py archie-scraper/screenshot_store.py \
        archie-scraper/tests/test_proxy_selector.py
git commit -m "feat(scout): proxy_selector.py + screenshot_store.py"
```

---

## Task 5: Job Worker

**Files:**
- Create: `archie-scraper/job_worker.py`
- Create: `archie-scraper/tests/test_job_worker.py`

- [ ] **Step 1: Write failing test**

```python
# archie-scraper/tests/test_job_worker.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock, patch


def _make_worker():
    pool = MagicMock()
    page = MagicMock()
    pool.claim.return_value = (0, page)
    from job_worker import JobWorker
    return JobWorker(pool), pool, page


def test_enqueue_inserts_pending_row():
    with patch("job_worker.get_db") as mock_db_ctx:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": 42}
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_db_ctx.return_value.__enter__ = lambda s: mock_conn
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        worker, _, _ = _make_worker()
        job_id = worker.enqueue(
            job_type="web_scrape",
            target_url="https://example.com",
            params={},
            egress_tier=1,
            requested_by="test",
        )
        assert job_id == 42
        sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO scout_jobs" in sql


def test_unknown_job_type_fails_without_claiming_pool():
    with patch("job_worker.get_db") as mock_db_ctx:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {
            "id": 99,
            "job_type": "nonexistent_skill",
            "target_url": "https://example.com",
            "params": {},
            "egress_tier": 1,
            "requested_by": "test",
        }
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_db_ctx.return_value.__enter__ = lambda s: mock_conn
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        worker, pool, _ = _make_worker()
        worker._process_next()
        pool.claim.assert_not_called()
```

- [ ] **Step 2: Run test — verify fails**

```bash
cd archie-scraper && python -m pytest tests/test_job_worker.py -v 2>&1 | head -5
```

Expected: `ImportError: No module named 'job_worker'`

- [ ] **Step 3: Implement job_worker.py**

```python
# archie-scraper/job_worker.py
import importlib
import json
import logging
import threading
import time
import traceback

import psycopg2.extras

from database import get_db
from proxy_selector import select_egress

logger = logging.getLogger(__name__)

SKILL_MAP = {
    "web_scrape": "skills.web_scrape",
    "ux_audit": "skills.ux_audit",
    "procurement_sync": "skills.procurement_sync",
}
_POLL_INTERVAL = 5


class JobWorker:
    def __init__(self, pool):
        self.pool = pool
        self._running = False

    def start(self) -> None:
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True, name="scout-worker")
        t.start()
        logger.info("JobWorker started, polling every %ds", _POLL_INTERVAL)

    def enqueue(
        self,
        job_type: str,
        target_url: str,
        params: dict,
        egress_tier: int,
        requested_by: str,
    ) -> int:
        auto_approve = job_type in ("web_scrape", "procurement_sync")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO scout_jobs
                       (job_type, target_url, params, egress_tier,
                        requested_by, status, auto_approve)
                       VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                       RETURNING id""",
                    (
                        job_type,
                        target_url,
                        json.dumps(params),
                        egress_tier,
                        requested_by,
                        auto_approve,
                    ),
                )
                return cur.fetchone()["id"]

    def _loop(self) -> None:
        while self._running:
            try:
                self._process_next()
            except Exception:
                logger.exception("JobWorker loop error")
            time.sleep(_POLL_INTERVAL)

    def _process_next(self) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scout_jobs
                       SET status = 'running', started_at = NOW()
                       WHERE id = (
                           SELECT id FROM scout_jobs
                           WHERE status = 'pending'
                           ORDER BY created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id, job_type, target_url, params,
                                 egress_tier, requested_by""",
                )
                row = cur.fetchone()
        if not row:
            return

        job_id = row["id"]
        logger.info(
            "Processing job #%d type=%s url=%s",
            job_id,
            row["job_type"],
            row["target_url"],
        )

        module_path = SKILL_MAP.get(row["job_type"])
        if not module_path:
            self._fail(job_id, f"Unknown job_type: {row['job_type']!r}")
            return

        params = (
            row["params"]
            if isinstance(row["params"], dict)
            else json.loads(row["params"] or "{}")
        )
        tier = select_egress(row["target_url"], row["egress_tier"])
        slot_id, page = None, None
        try:
            slot_id, page = self.pool.claim(egress_tier=tier)
            skill_mod = importlib.import_module(module_path)
            result = skill_mod.run(
                page=page,
                url=row["target_url"],
                params=params,
                job_id=job_id,
            )
            self._complete(job_id, result, tier)
        except Exception:
            self._fail(job_id, traceback.format_exc())
        finally:
            if slot_id is not None and page is not None:
                self.pool.release(slot_id, page)

    def _complete(self, job_id: int, result: dict, egress_tier: int) -> None:
        status = "approved" if result.get("auto_approve") else "needs_review"
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scout_jobs
                       SET status = %s, completed_at = NOW(), egress_tier = %s,
                           data = %s, screenshots = %s,
                           network_log = %s, findings = %s
                       WHERE id = %s""",
                    (
                        status,
                        egress_tier,
                        psycopg2.extras.Json(result.get("data")),
                        psycopg2.extras.Json(result.get("screenshots", [])),
                        psycopg2.extras.Json(result.get("network_log", [])),
                        result.get("findings", ""),
                        job_id,
                    ),
                )
        logger.info("Job #%d completed → %s", job_id, status)

    def _fail(self, job_id: int, error: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scout_jobs
                       SET status = 'failed', completed_at = NOW(),
                           error_log = %s
                       WHERE id = %s""",
                    (error[:4000], job_id),
                )
        logger.error("Job #%d failed", job_id)
```

- [ ] **Step 4: Create skills/__init__.py**

```bash
touch archie-scraper/skills/__init__.py
```

- [ ] **Step 5: Run tests**

```bash
cd archie-scraper && python -m pytest tests/test_job_worker.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add archie-scraper/job_worker.py archie-scraper/skills/__init__.py \
        archie-scraper/tests/test_job_worker.py
git commit -m "feat(scout): job_worker.py — polls scout_jobs, dispatches to browser pool"
```

---

## Task 6: Flask App

**Files:**
- Create: `archie-scraper/app.py`

- [ ] **Step 1: Create app.py**

```python
# archie-scraper/app.py
import logging
import os

from flask import Flask, jsonify, request

from browser_pool import BrowserPool
from database import get_db
from job_worker import JobWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
pool = BrowserPool()
worker = JobWorker(pool)


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "pool_size": pool.size,
            "slots_available": pool.available_count(),
        }
    )


@app.route("/jobs", methods=["POST"])
def submit_job():
    data = request.get_json(silent=True) or {}
    job_type = (data.get("job_type") or "").strip()
    target_url = (data.get("target_url") or "").strip()
    if not job_type or not target_url:
        return jsonify({"error": "job_type and target_url required"}), 400
    job_id = worker.enqueue(
        job_type=job_type,
        target_url=target_url,
        params=data.get("params") or {},
        egress_tier=int(data.get("egress_tier") or 1),
        requested_by=data.get("requested_by") or "api",
    )
    return jsonify({"job_id": job_id, "status": "pending"}), 201


@app.route("/jobs/<int:job_id>")
def get_job(job_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM scout_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@app.route("/jobs")
def list_jobs():
    status = request.args.get("status")
    with get_db() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """SELECT id, job_type, target_url, status, created_at,
                              egress_tier, requested_by, findings
                       FROM scout_jobs WHERE status = %s
                       ORDER BY created_at DESC LIMIT 50""",
                    (status,),
                )
            else:
                cur.execute(
                    """SELECT id, job_type, target_url, status, created_at,
                              egress_tier, requested_by, findings
                       FROM scout_jobs ORDER BY created_at DESC LIMIT 50"""
                )
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/pool/status")
def pool_status():
    return jsonify(pool.status())


if __name__ == "__main__":
    worker.start()
    app.run(host="0.0.0.0", port=4243, debug=False)
```

- [ ] **Step 2: Commit**

```bash
git add archie-scraper/app.py
git commit -m "feat(scout): Flask app — /health /jobs /pool/status endpoints"
```

---

## Task 7: Skill — web_scrape.py

**Files:**
- Create: `archie-scraper/skills/web_scrape.py`
- Create: `archie-scraper/tests/test_skills.py`

- [ ] **Step 1: Write failing test**

```python
# archie-scraper/tests/test_skills.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock


def _make_page(texts: list[str]) -> MagicMock:
    page = MagicMock()
    page.goto.return_value = None
    page.wait_for_selector.return_value = None
    els = [MagicMock(inner_text=MagicMock(return_value=t)) for t in texts]
    page.query_selector_all.return_value = els
    return page


def test_web_scrape_extracts_text():
    from skills.web_scrape import run
    page = _make_page(["Tender A", "Tender B", "Tender C"])
    result = run(
        page=page,
        url="https://example.com",
        params={"selectors": {"tenders": "tr.tender"}},
        job_id=1,
    )
    assert result["data"]["tenders"] == ["Tender A", "Tender B", "Tender C"]
    assert result["auto_approve"] is True
    assert "findings" in result


def test_web_scrape_respects_max_items():
    from skills.web_scrape import run
    page = _make_page([f"Item {i}" for i in range(10)])
    result = run(
        page=page,
        url="https://example.com",
        params={"selectors": {"items": "li"}, "max_items": 3},
        job_id=2,
    )
    assert len(result["data"]["items"]) == 3
```

- [ ] **Step 2: Run test — verify fails**

```bash
cd archie-scraper && python -m pytest tests/test_skills.py -v 2>&1 | head -5
```

Expected: `ImportError: No module named 'skills.web_scrape'`

- [ ] **Step 3: Implement web_scrape.py**

```python
# archie-scraper/skills/web_scrape.py
"""Skill: web_scrape — General selector-based page extraction."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        selectors  dict  field_name -> CSS selector
        wait_for   str   CSS selector to wait for before extracting (optional)
        max_items  int   limit per selector (default 100)
    """
    selectors = params.get("selectors") or {}
    wait_for = params.get("wait_for")
    max_items = int(params.get("max_items") or 100)

    page.goto(url, wait_until="networkidle", timeout=30000)
    if wait_for:
        page.wait_for_selector(wait_for, timeout=10000)

    data: dict = {}
    for field, selector in selectors.items():
        els = page.query_selector_all(selector)[:max_items]
        data[field] = [el.inner_text().strip() for el in els]

    total = sum(len(v) for v in data.values())
    findings = f"Extracted {total} items across {len(selectors)} selectors from {url}"
    logger.info("[web_scrape] job #%d: %s", job_id, findings)

    return {
        "data": data,
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 4: Run test — verify passes**

```bash
cd archie-scraper && python -m pytest tests/test_skills.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add archie-scraper/skills/web_scrape.py archie-scraper/tests/test_skills.py
git commit -m "feat(scout): skill web_scrape — selector-based page extraction"
```

---

## Task 8: Skill — ux_audit.py

**Files:**
- Modify: `archie-scraper/tests/test_skills.py` (append test)
- Create: `archie-scraper/skills/ux_audit.py`

- [ ] **Step 1: Append failing test to test_skills.py**

```python
def test_ux_audit_returns_screenshots_and_not_auto_approved():
    from unittest.mock import patch
    from skills.ux_audit import run

    page = MagicMock()
    page.title.return_value = "Test Site"
    page.query_selector_all.return_value = [
        MagicMock(inner_text=MagicMock(return_value="Welcome"))
    ]

    with patch("skills.ux_audit.save_screenshot", return_value="1/desktop_homepage.png"), \
         patch("skills.ux_audit.screenshot_entry",
               return_value={"step": "desktop_homepage",
                              "path": "1/desktop_homepage.png", "caption": "Desktop homepage"}):
        result = run(page=page, url="https://example.com", params={}, job_id=1)

    assert result["auto_approve"] is False
    assert len(result["screenshots"]) >= 1
    assert "Test Site" in result["findings"]
    assert result["data"]["title"] == "Test Site"
```

- [ ] **Step 2: Run test — verify fails**

```bash
cd archie-scraper && python -m pytest tests/test_skills.py::test_ux_audit_returns_screenshots_and_not_auto_approved -v 2>&1 | head -5
```

Expected: `ImportError: No module named 'skills.ux_audit'`

- [ ] **Step 3: Implement ux_audit.py**

```python
# archie-scraper/skills/ux_audit.py
"""Skill: ux_audit — Multi-viewport screenshot walk-through."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        viewport  str  "WIDTHxHEIGHT" (default "1280x800")
    """
    viewport_str = params.get("viewport") or "1280x800"
    w, h = (int(x) for x in viewport_str.split("x"))

    screenshots = []
    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

    # Desktop
    page.set_viewport_size({"width": w, "height": h})
    page.goto(url, wait_until="networkidle", timeout=45000)
    path = save_screenshot(job_id, "desktop_homepage", page)
    screenshots.append(screenshot_entry("desktop_homepage", path, "Desktop homepage"))

    title = page.title()
    h1s = [el.inner_text().strip() for el in page.query_selector_all("h1")]

    # Mobile
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="networkidle", timeout=30000)
    path = save_screenshot(job_id, "mobile_homepage", page)
    screenshots.append(screenshot_entry("mobile_homepage", path, "Mobile (390px)"))

    findings_parts = [f"Title: {title}", f"H1s: {', '.join(h1s) or 'none found'}"]
    if console_errors:
        findings_parts.append(
            f"Console errors ({len(console_errors)}): {'; '.join(console_errors[:3])}"
        )

    logger.info(
        "[ux_audit] job #%d: %d screenshots, %d console errors",
        job_id,
        len(screenshots),
        len(console_errors),
    )

    return {
        "data": {
            "title": title,
            "h1s": h1s,
            "console_errors": console_errors[:10],
            "viewports_tested": [f"{w}x{h}", "390x844"],
        },
        "screenshots": screenshots,
        "network_log": [],
        "findings": "\n".join(findings_parts),
        "auto_approve": False,
    }
```

- [ ] **Step 4: Run all skill tests**

```bash
cd archie-scraper && python -m pytest tests/test_skills.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add archie-scraper/skills/ux_audit.py archie-scraper/tests/test_skills.py
git commit -m "feat(scout): skill ux_audit — multi-viewport screenshot audit"
```

---

## Task 9: Skill — procurement_sync.py

**Files:**
- Modify: `archie-scraper/tests/test_skills.py` (append test)
- Create: `archie-scraper/skills/procurement_sync.py`

- [ ] **Step 1: Append failing test**

```python
def test_procurement_sync_returns_tenders_auto_approved():
    from unittest.mock import patch
    from skills.procurement_sync import run

    page = MagicMock()
    row1 = MagicMock()
    row1.inner_text.return_value = "AI Services | PSPC | Deadline: 2026-06-01"
    link1 = MagicMock()
    link1.get_attribute.return_value = "/en/tender/12345"
    row1.query_selector_all.return_value = [link1]
    page.query_selector_all.return_value = [row1]
    page.query_selector.return_value = None  # no next-page button

    with patch("skills.procurement_sync.save_screenshot", return_value="1/tenders_page_1.png"), \
         patch("skills.procurement_sync.screenshot_entry",
               return_value={"step": "tenders_page_1", "path": "1/tenders_page_1.png", "caption": ""}):
        result = run(page=page, url="https://canadabuys.canada.ca", params={"max_pages": 1}, job_id=1)

    assert result["auto_approve"] is True
    assert len(result["data"]["tenders"]) >= 1
    assert result["data"]["tenders"][0]["text"] == "AI Services | PSPC | Deadline: 2026-06-01"
```

- [ ] **Step 2: Run test — verify fails**

```bash
cd archie-scraper && python -m pytest tests/test_skills.py::test_procurement_sync_returns_tenders_auto_approved -v 2>&1 | head -5
```

Expected: `ImportError: No module named 'skills.procurement_sync'`

- [ ] **Step 3: Implement procurement_sync.py**

```python
# archie-scraper/skills/procurement_sync.py
"""Skill: procurement_sync — CanadaBuys tender listings via real browser."""
import logging

from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://canadabuys.canada.ca/en/tender-opportunities"
_TENDER_SELECTORS = [
    "table tbody tr",
    ".tender-item",
    "[class*='tender-row']",
    "[class*='opportunity']",
]
_NEXT_SELECTORS = [
    "a[rel='next']",
    ".pagination-next a",
    "a:has-text('Next')",
    "[aria-label='Next page']",
]


def run(page, url: str, params: dict, job_id: int) -> dict:
    """
    params:
        max_pages  int  pages to paginate (default 3)
    """
    max_pages = int(params.get("max_pages") or 3)
    target = url or _DEFAULT_URL

    tenders: list[dict] = []
    screenshots = []
    pages_scraped = 0

    page.goto(target, wait_until="networkidle", timeout=45000)
    path = save_screenshot(job_id, "tenders_page_1", page)
    screenshots.append(screenshot_entry("tenders_page_1", path, "CanadaBuys page 1"))

    for page_num in range(1, max_pages + 1):
        pages_scraped = page_num
        rows: list = []
        for selector in _TENDER_SELECTORS:
            rows = page.query_selector_all(selector)
            if rows:
                break

        for row in rows:
            text = row.inner_text().strip()
            if not text or len(text) < 10:
                continue
            links = row.query_selector_all("a")
            href = links[0].get_attribute("href") if links else None
            tenders.append({"text": text[:500], "url": href, "page": page_num})

        if page_num >= max_pages:
            break
        next_btn = None
        for sel in _NEXT_SELECTORS:
            try:
                next_btn = page.query_selector(sel)
                if next_btn:
                    break
            except Exception:
                continue
        if not next_btn:
            break
        next_btn.click()
        page.wait_for_load_state("networkidle", timeout=15000)

    findings = (
        f"Found {len(tenders)} tenders across {pages_scraped} page(s) from {target}"
    )
    logger.info("[procurement_sync] job #%d: %s", job_id, findings)

    return {
        "data": {"tenders": tenders, "source": target, "pages_scraped": pages_scraped},
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
```

- [ ] **Step 4: Run all skill tests**

```bash
cd archie-scraper && python -m pytest tests/ -v
```

Expected: all tests pass (7+ total)

- [ ] **Step 5: Commit**

```bash
git add archie-scraper/skills/procurement_sync.py archie-scraper/tests/test_skills.py
git commit -m "feat(scout): skill procurement_sync — CanadaBuys browser scraper"
```

---

## Task 10: Docker Integration

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Find where archie_browser is defined**

```bash
grep -n "archie_browser" docker-compose.yml | head -5
```

Note the line number so you know where to insert the new service block.

- [ ] **Step 2: Add archie_scraper service block**

Add immediately after the closing of the `archie_browser:` service block:

```yaml
  archie_scraper:
    build:
      context: ./archie-scraper
      dockerfile: Dockerfile
    container_name: archie_scraper
    restart: unless-stopped
    ports:
      - "4243:4243"
    environment:
      - DB_HOST=archie_database
      - DB_NAME=archie
      - DB_USER=archie
      - DB_PASSWORD=${DB_PASSWORD}
      - SCOUT_POOL_SIZE=3
      - SCOUT_VPS_SOCKS=socks5://100.64.0.2:1080
      - SCOUT_PROXY_URL=${SCOUT_PROXY_URL:-}
      - SCREENSHOT_DIR=/mnt/screenshots
    volumes:
      - /mnt/data2/scout/screenshots:/mnt/screenshots
    networks:
      - archie_net
    depends_on:
      - archie_database
      - archie_platform
    mem_limit: 2g
    dns:
      - 192.168.1.200
      - 1.1.1.1
```

- [ ] **Step 3: Create screenshot directory**

```bash
mkdir -p /mnt/data2/scout/screenshots
chmod 755 /mnt/data2/scout/screenshots
```

- [ ] **Step 4: Build and start**

```bash
docker compose build archie_scraper 2>&1 | tail -5
docker compose up -d archie_scraper
docker logs archie_scraper --tail=20
```

Expected: No errors. Log shows `Pool slot 0 ready (proxy=direct)` × 3 and `JobWorker started`.

- [ ] **Step 5: Verify health from within platform network**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json
r = urllib.request.urlopen('http://archie_scraper:4243/health', timeout=5)
print(json.loads(r.read()))
"
```

Expected: `{'status': 'ok', 'pool_size': 3, 'slots_available': 3}`

- [ ] **Step 6: Submit test job and verify completion**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json, time
payload = json.dumps({
    'job_type': 'web_scrape',
    'target_url': 'https://httpbin.org/html',
    'params': {'selectors': {'headings': 'h1'}},
    'requested_by': 'smoke_test',
}).encode()
req = urllib.request.Request('http://archie_scraper:4243/jobs', data=payload)
req.add_header('Content-Type', 'application/json')
r = urllib.request.urlopen(req, timeout=10)
job = json.loads(r.read())
print('Submitted job:', job)
time.sleep(15)
r2 = urllib.request.urlopen(f'http://archie_scraper:4243/jobs/{job[\"job_id\"]}', timeout=5)
d = json.loads(r2.read())
print('Status:', d['status'], '| Findings:', d.get('findings'))
"
```

Expected: `Status: approved | Findings: Extracted ...`

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(scout): add archie_scraper to docker-compose — port 4243, 2GB mem"
```

---

## Task 11: DHQ Scout Routes

**Files:**
- Create: `platform_v2/tools/department_hq/scout_routes.py`

- [ ] **Step 1: Create scout_routes.py**

```python
# platform_v2/tools/department_hq/scout_routes.py
"""DHQ Scout tab — mirrors social_routes.py (S.I.G.N.A.L.) pattern."""
import json
import logging
import urllib.request

from flask import jsonify, request

from database import get_db_cursor

logger = logging.getLogger(__name__)

_SCRAPER_BASE = "http://archie_scraper:4243"


def _scraper_post(path: str, body: dict) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(f"{_SCRAPER_BASE}{path}", data=payload)
    req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as exc:
        return {"error": str(exc)}


def _scraper_get(path: str) -> dict:
    try:
        r = urllib.request.urlopen(f"{_SCRAPER_BASE}{path}", timeout=5)
        return json.loads(r.read())
    except Exception as exc:
        return {"error": str(exc)}


def register_scout_routes(bp, admin_required):

    @bp.route("/api/scout/overview")
    @admin_required
    def api_scout_overview():
        pool = _scraper_get("/pool/status")
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, COUNT(*) AS cnt FROM scout_jobs GROUP BY status"
            )
            counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
            cur.execute(
                """SELECT id, job_type, target_url, status, created_at, findings
                   FROM scout_jobs ORDER BY created_at DESC LIMIT 5"""
            )
            recent = [dict(r) for r in cur.fetchall()]
        return jsonify({"pool": pool, "job_counts": counts, "recent_jobs": recent})

    @bp.route("/api/scout/jobs")
    @admin_required
    def api_scout_jobs():
        status_filter = request.args.get("status")
        job_type_filter = request.args.get("job_type")
        limit = min(int(request.args.get("limit") or 50), 200)
        clauses, params = [], []
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        if job_type_filter:
            clauses.append("job_type = %s")
            params.append(job_type_filter)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT id, job_type, target_url, status, egress_tier,
                           created_at, completed_at, requested_by, findings, auto_approve
                    FROM scout_jobs {where}
                    ORDER BY created_at DESC LIMIT %s""",
                params + [limit],
            )
            jobs = [dict(r) for r in cur.fetchall()]
        return jsonify({"jobs": jobs, "total": len(jobs)})

    @bp.route("/api/scout/jobs/<int:job_id>")
    @admin_required
    def api_scout_job_detail(job_id):
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM scout_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))

    @bp.route("/api/scout/jobs/<int:job_id>/approve", methods=["POST"])
    @admin_required
    def api_scout_approve(job_id):
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE scout_jobs
                   SET status = 'approved', reviewed_at = NOW(), reviewed_by = 'admin'
                   WHERE id = %s AND status = 'needs_review'
                   RETURNING id""",
                (job_id,),
            )
            updated = cur.fetchone()
        if not updated:
            return jsonify({"error": "not found or not in needs_review state"}), 400
        return jsonify({"success": True, "job_id": job_id, "status": "approved"})

    @bp.route("/api/scout/jobs/<int:job_id>/reject", methods=["POST"])
    @admin_required
    def api_scout_reject(job_id):
        data = request.get_json(silent=True) or {}
        note = (data.get("note") or "")[:500]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE scout_jobs
                   SET status = 'rejected', reviewed_at = NOW(),
                       reviewed_by = 'admin', error_log = %s
                   WHERE id = %s AND status = 'needs_review'
                   RETURNING id""",
                (f"Rejected: {note}", job_id),
            )
            updated = cur.fetchone()
        if not updated:
            return jsonify({"error": "not found or not in needs_review state"}), 400
        return jsonify({"success": True, "job_id": job_id, "status": "rejected"})

    @bp.route("/api/scout/run-now", methods=["POST"])
    @admin_required
    def api_scout_run_now():
        data = request.get_json(silent=True) or {}
        job_type = (data.get("job_type") or "procurement_sync").strip()
        target_url = (
            data.get("target_url")
            or "https://canadabuys.canada.ca/en/tender-opportunities"
        )
        result = _scraper_post(
            "/jobs",
            {
                "job_type": job_type,
                "target_url": target_url,
                "params": data.get("params") or {},
                "requested_by": "dhq_manual",
            },
        )
        return jsonify(result)

    @bp.route("/api/scout/pool")
    @admin_required
    def api_scout_pool():
        return jsonify(_scraper_get("/pool/status"))
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/department_hq/scout_routes.py
git commit -m "feat(scout): DHQ scout_routes.py — overview, jobs, approve/reject, run-now"
```

---

## Task 12: Register Scout Routes in DHQ

**Files:**
- Modify: `platform_v2/tools/department_hq/__init__.py`

- [ ] **Step 1: Find where social_routes is registered**

```bash
grep -n "register_social_routes\|from .social" \
  platform_v2/tools/department_hq/__init__.py
```

Note the exact line.

- [ ] **Step 2: Add scout registration immediately after that line**

```python
from .scout_routes import register_scout_routes
register_scout_routes(bp, admin_required)
```

- [ ] **Step 3: Restart platform and verify no import errors**

```bash
docker compose restart archie_platform
sleep 5
docker logs archie_platform --tail=30 2>&1 | grep -iE "scout|error|import"
```

Expected: No errors mentioning scout. Platform starts healthy.

- [ ] **Step 4: Hit a scout endpoint to confirm routing**

```bash
docker exec archie_platform python3 -c "
import urllib.request
# The endpoint requires auth so we expect 302 redirect, not 404
try:
    urllib.request.urlopen('http://localhost:3000/tools/department-hq/api/scout/pool', timeout=3)
except urllib.error.HTTPError as e:
    print('HTTP', e.code, '— route exists' if e.code in (302, 401, 403) else 'UNEXPECTED')
except Exception as e:
    print('Error:', e)
"
```

Expected: `HTTP 302 — route exists` (redirects to login, meaning the route is registered)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/__init__.py
git commit -m "feat(scout): register_scout_routes in DHQ __init__"
```

---

## Task 13: DHQ Scout Tab — Template + JS

**Files:**
- Modify: `platform_v2/templates/tools/department_hq.html`
- Create: `platform_v2/static/js/scout.js`

- [ ] **Step 1: Find the S.I.G.N.A.L. tab button pattern**

```bash
grep -n "data-tab=\"social\"\|panel-social" \
  platform_v2/templates/tools/department_hq.html | head -5
```

Note the exact line numbers for the tab button and panel div.

- [ ] **Step 2: Add Scout tab button**

Immediately after the S.I.G.N.A.L. tab button, add:

```html
<button class="dhq-tab-btn" data-tab="scout" onclick="switchTab('scout')">
  S.C.O.U.T.
</button>
```

- [ ] **Step 3: Add Scout panel div**

Immediately after the `id="panel-social"` closing div, add:

```html
<div id="panel-scout" class="dhq-tab-panel" style="display:none;">
  <div class="dhq-panel-header">
    <h3>S.C.O.U.T. — Field Data Correspondent</h3>
    <div>
      <button onclick="scoutRunNow('procurement_sync')" class="dhq-btn dhq-btn-primary">
        Run Procurement Sync
      </button>
      <button onclick="scoutRefresh()" class="dhq-btn">Refresh</button>
    </div>
  </div>
  <div id="scout-overview" class="dhq-section">
    <div id="scout-pool-status">Loading pool...</div>
    <div id="scout-job-counts"></div>
  </div>
  <div class="scout-subtabs">
    <button class="scout-subtab-btn active" data-panel="jobs"
            onclick="scoutSubtab(this,'jobs')">All Jobs</button>
    <button class="scout-subtab-btn" data-panel="reports"
            onclick="scoutSubtab(this,'reports')">Reports (Review)</button>
    <button class="scout-subtab-btn" data-panel="procurement"
            onclick="scoutSubtab(this,'procurement')">Procurement</button>
  </div>
  <div id="scout-panel-jobs" class="scout-subtab-panel">
    <table class="dhq-table">
      <thead>
        <tr>
          <th>ID</th><th>Type</th><th>URL</th><th>Status</th>
          <th>Egress</th><th>Created</th><th>Findings</th>
        </tr>
      </thead>
      <tbody id="scout-jobs-tbody"></tbody>
    </table>
  </div>
  <div id="scout-panel-reports" class="scout-subtab-panel" style="display:none;">
    <p class="dhq-hint">Jobs awaiting review before client delivery.</p>
    <div id="scout-reports-list"></div>
  </div>
  <div id="scout-panel-procurement" class="scout-subtab-panel" style="display:none;">
    <div id="scout-procurement-list"></div>
  </div>
</div>
```

- [ ] **Step 4: Create scout.js — safe DOM manipulation, no raw innerHTML with untrusted data**

```javascript
// platform_v2/static/js/scout.js
'use strict';

function _esc(str) {
  const d = document.createElement('div');
  d.textContent = String(str == null ? '' : str);
  return d.innerHTML;
}

function _badgeClass(status) {
  const map = {
    pending: 'scout-badge-pending',
    running: 'scout-badge-running',
    completed: 'scout-badge-ok',
    approved: 'scout-badge-ok',
    needs_review: 'scout-badge-warn',
    failed: 'scout-badge-err',
    rejected: 'scout-badge-err',
  };
  return map[status] || '';
}

async function loadScoutTab() {
  await Promise.all([_loadScoutOverview(), _loadScoutJobs()]);
}

async function _loadScoutOverview() {
  try {
    const r = await fetch('/tools/department-hq/api/scout/overview');
    const d = await r.json();
    const pool = d.pool || {};
    const el = document.getElementById('scout-pool-status');
    if (el) {
      el.textContent =
        'Browser Pool: ' +
        (pool.slots_available ?? '?') +
        '/' +
        (pool.pool_size ?? '?') +
        ' slots free';
    }
    const countEl = document.getElementById('scout-job-counts');
    if (countEl) {
      countEl.textContent = '';
      Object.entries(d.job_counts || {}).forEach(([s, n]) => {
        const span = document.createElement('span');
        span.className = 'scout-badge ' + _badgeClass(s);
        span.textContent = s + ': ' + n;
        countEl.appendChild(span);
        countEl.appendChild(document.createTextNode(' '));
      });
    }
  } catch (e) {
    const el = document.getElementById('scout-pool-status');
    if (el) el.textContent = 'Pool unavailable';
  }
}

async function _loadScoutJobs(status) {
  const qs = status ? '?status=' + encodeURIComponent(status) : '';
  try {
    const r = await fetch('/tools/department-hq/api/scout/jobs' + qs);
    const d = await r.json();
    const tbody = document.getElementById('scout-jobs-tbody');
    if (!tbody) return;
    tbody.textContent = '';
    (d.jobs || []).forEach(function (job) {
      const tr = document.createElement('tr');
      [
        job.id,
        job.job_type,
        job.target_url,
        job.status,
        'Tier ' + job.egress_tier,
        (job.created_at || '').slice(0, 16),
        (job.findings || '').slice(0, 80),
      ].forEach(function (val) {
        const td = document.createElement('td');
        td.textContent = String(val == null ? '' : val);
        if (val === job.status) {
          const span = document.createElement('span');
          span.className = 'scout-badge ' + _badgeClass(job.status);
          span.textContent = job.status;
          td.textContent = '';
          td.appendChild(span);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error('Scout jobs load failed:', e);
  }
}

async function scoutRunNow(jobType) {
  const btn = event.currentTarget;
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = 'Running...';
  try {
    const r = await fetch('/tools/department-hq/api/scout/run-now', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_type: jobType }),
    });
    const d = await r.json();
    if (d.job_id) {
      alert('Job #' + d.job_id + ' queued. Check Jobs tab.');
      await _loadScoutJobs();
    } else {
      alert('Error: ' + (d.error || JSON.stringify(d)));
    }
  } catch (e) {
    alert('Request failed: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function scoutRefresh() {
  await Promise.all([_loadScoutOverview(), _loadScoutJobs()]);
}

function scoutSubtab(btn, name) {
  document.querySelectorAll('.scout-subtab-panel').forEach(function (p) {
    p.style.display = 'none';
  });
  document.querySelectorAll('.scout-subtab-btn').forEach(function (b) {
    b.classList.remove('active');
  });
  const panel = document.getElementById('scout-panel-' + name);
  if (panel) panel.style.display = '';
  btn.classList.add('active');
  const statusMap = { reports: 'needs_review', procurement: 'approved' };
  _loadScoutJobs(statusMap[name]);
}
```

- [ ] **Step 5: Include scout.js in department_hq.html**

Find where other DHQ JS files are included (e.g., `<script src="/static/js/social.js">`) and add:

```html
<script src="/static/js/scout.js"></script>
```

- [ ] **Step 6: Wire tab loader**

In department_hq.html, find the JS `loaders` object (maps tab name to load function) and add:

```javascript
'scout': loadScoutTab,
```

- [ ] **Step 7: Restart and verify in browser**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/department-hq` → S.C.O.U.T. tab → verify pool status and job table render without JS errors in browser console.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/templates/tools/department_hq.html \
        platform_v2/static/js/scout.js
git commit -m "feat(scout): DHQ Scout tab — overview, jobs table, approve/reject, run-now"
```

---

## Task 14: End-to-End Verification + PR

- [ ] **Step 1: Submit procurement_sync via DHQ Run Now button**

Log in at `http://192.168.1.200:3000/tools/department-hq`, go to Scout tab, click "Run Procurement Sync".

Expected: Alert `Job #N queued`.

- [ ] **Step 2: Wait and verify auto-approval**

Wait 60 seconds, refresh Jobs tab.

Expected: Job appears with `status: approved`. Findings shows tender count.

- [ ] **Step 3: Submit ux_audit and test review flow**

```bash
docker exec archie_platform python3 -c "
import urllib.request, json
payload = json.dumps({
    'job_type': 'ux_audit',
    'target_url': 'https://canadabuys.canada.ca',
    'params': {},
    'requested_by': 'e2e_test',
}).encode()
req = urllib.request.Request('http://archie_scraper:4243/jobs', data=payload)
req.add_header('Content-Type', 'application/json')
r = urllib.request.urlopen(req, timeout=10)
print('Submitted:', json.loads(r.read()))
"
```

Wait 60s. Check DHQ Scout → Reports subtab. Expected: Job with `needs_review` status.

- [ ] **Step 4: Approve the report**

In DHQ Scout → Reports, click Approve. Expected: Status changes to `approved`.

- [ ] **Step 5: Verify screenshots on disk**

```bash
ls -la /mnt/data2/scout/screenshots/
```

Expected: subdirectory per job_id containing `.png` files.

- [ ] **Step 6: Create PR**

```bash
git push -u origin feat/scout-phase1
gh pr create \
  --title "feat(scout): Phase 1 — archie_scraper container + DHQ Scout tab" \
  --body "$(cat <<'EOF'
## Summary
- New archie_scraper container (port 4243): Flask + Playwright Chromium, 3-slot browser pool
- scout_jobs DB table (migration 380) with approval workflow
- 3 MVP skills: web_scrape, ux_audit, procurement_sync
- DHQ Scout tab (mirrors S.I.G.N.A.L.): overview, jobs table, approve/reject, run-now
- Multi-egress: Tier 1 hub residential, Tier 2 VPS SOCKS5, Tier 3 external proxy

## Test Plan
- [ ] archie_scraper /health returns 200 with pool_size=3
- [ ] POST /jobs queues job, worker picks it up within 5s
- [ ] web_scrape extracts from httpbin.org
- [ ] procurement_sync scrapes CanadaBuys, status approved
- [ ] ux_audit produces screenshots, status needs_review
- [ ] Approve in DHQ changes status to approved
- [ ] Screenshots present in /mnt/data2/scout/screenshots/

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage — Phase 1:**

| Spec Requirement | Task |
|---|---|
| scout_jobs table + indexes | Task 1 |
| Dockerfile + requirements + database.py | Task 2 |
| BrowserPool — 3 slots, claim/release | Task 3 |
| proxy_selector — gov domain → Tier 1 | Task 4 |
| screenshot_store — save PNG, return path | Task 4 |
| job_worker — poll, dispatch, complete, fail | Task 5 |
| Flask API — /health /jobs /pool/status | Task 6 |
| Skill: web_scrape | Task 7 |
| Skill: ux_audit | Task 8 |
| Skill: procurement_sync | Task 9 |
| docker-compose.yml — archie_scraper service | Task 10 |
| DHQ scout_routes.py | Task 11 |
| Register routes in __init__ | Task 12 |
| DHQ Scout tab HTML + JS | Task 13 |
| End-to-end verification | Task 14 |

**Deferred to later plans:**
- 20 remaining skills → Plan 2
- KBS kbs_scout plugin + /scout CLI skill → Plan 3
- Dynamic fleet node egress discovery, agent loop jobs, gov-watch wiring → Plan 4
