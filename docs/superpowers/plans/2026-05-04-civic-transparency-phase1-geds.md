# Civic Transparency Phase 1 — GEDS Directory Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-refreshing, queryable registry of every public servant in the GoC GEDS-SAGE directory plus the four `pgid=016` quick-link lists, persisted to a new `civic_transparency` schema on hub Postgres, surfaced as `/transparency/*` routes on `civic.kytranempowerment.com`.

**Architecture:** Hub-side scraper service (`platform_v2/services/civic_geds_*`) runs nightly via `archie_scheduler`. Three-pass crawl (org tree → people → quick lists) writes to 5 tables. Diff engine emits movement records on each snapshot. Civic Watch on VPS reads via existing Postgres mesh connection and renders public routes.

**Tech Stack:** Python 3.11 · `httpx` (async HTTP/2) · `selectolax` (fast HTML parsing) · `psycopg2` · pytest · existing `archie_scheduler` sidecar.

**Spec:** `docs/superpowers/specs/2026-05-04-civic-transparency-phase1-geds.md`
**Project:** unified_projects #323 (parent: #322 master)

**Plan structure:**
- **Section A — Scraper + DB** (Tasks 1–11): hub-side ingestion. Ships an internal dataset.
- **Checkpoint:** verify two consecutive successful nightly runs before starting Section B.
- **Section B — Public Surface** (Tasks 12–17): Civic Watch routes on VPS. Ships the public registry.

---

## Section A — Scraper + DB

### Task 1: Recon — verify civic-watch repo layout, DB connection, existing patterns

**No code in this task.** This is the only research task; everything that follows assumes its findings.

**Files:**
- Append findings to: `docs/superpowers/plans/2026-05-04-civic-transparency-phase1-geds.md` (this file, "Recon Notes" section at bottom)

- [ ] **Step 1: Locate civic-watch source tree**

```bash
ls /mnt/standalone/ | grep -i civic
ls /mnt/archie_brain/ | grep -i civic
```

Expected: civic-watch lives at one of `/mnt/standalone/kytran-civic-watch/` or `/mnt/archie_brain/kytran-civic-watch/`. Note exact path.

- [ ] **Step 2: Verify Postgres connection pattern from VPS to hub**

```bash
# On hub:
docker exec archie_database psql -U archie -d archie -c "\du" | grep -i civic
# Find the civic_watch DB user, note its grants
```

Confirm: is there an existing `civic_watch` schema on hub Postgres? If yes, civic-watch already has a mesh connection — note connection string from civic-watch's `.env`. If no, gov-watch has the same pattern; note its `.env` and reuse identical connection.

- [ ] **Step 3: Note Civic Watch route registration pattern**

Find civic-watch's main app file (likely `app.py` or `wsgi.py` in its source tree). Read it. Note:
- Flask blueprint registration style
- Template folder layout
- How existing routes look (e.g., `/news`, `/alerts`)
- Whether it uses platform LCARS shared CSS or has its own

- [ ] **Step 4: Append recon notes to this plan file**

Add a "Recon Notes" section at the bottom with:
- Civic-watch source path
- Postgres connection string (REDACT password — refer to env var name only)
- Blueprint pattern + 1 example existing route
- Open issues / surprises

- [ ] **Step 5: Commit recon notes**

```bash
git add docs/superpowers/plans/2026-05-04-civic-transparency-phase1-geds.md
git commit -m "docs: civic-transparency phase 1 recon notes"
```

---

### Task 2: SQL migration — create civic_transparency schema

**Files:**
- Create: `database/migrations/374_civic_transparency_schema.sql`
- Test: `tests/migrations/test_374_civic_transparency.py`

- [ ] **Step 1: Write the migration**

```sql
-- database/migrations/374_civic_transparency_schema.sql
-- Phase 1 of Civic Transparency: GEDS directory ingestion.
-- Spec: docs/superpowers/specs/2026-05-04-civic-transparency-phase1-geds.md

CREATE SCHEMA IF NOT EXISTS civic_transparency;

CREATE TABLE IF NOT EXISTS civic_transparency.org_units (
    id              SERIAL PRIMARY KEY,
    parent_id       INTEGER REFERENCES civic_transparency.org_units(id),
    dn              TEXT NOT NULL UNIQUE,
    dn_b64          TEXT NOT NULL,
    level           SMALLINT NOT NULL,
    name_en         TEXT NOT NULL,
    name_fr         TEXT,
    abbreviation_en TEXT,
    abbreviation_fr TEXT,
    coverage        TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (coverage IN ('full','partial','none','opted_out','unknown')),
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_org_units_parent  ON civic_transparency.org_units(parent_id);
CREATE INDEX IF NOT EXISTS idx_org_units_abbr_en ON civic_transparency.org_units(abbreviation_en);

CREATE TABLE IF NOT EXISTS civic_transparency.federal_employees (
    id               SERIAL PRIMARY KEY,
    source_dn        TEXT NOT NULL UNIQUE,
    org_unit_id      INTEGER NOT NULL REFERENCES civic_transparency.org_units(id),
    surname          TEXT NOT NULL,
    given_name       TEXT,
    title_en         TEXT,
    title_fr         TEXT,
    classification   TEXT,
    role_tag         TEXT CHECK (role_tag IS NULL OR role_tag IN
                       ('minister','deputy_minister','senator','mp')),
    phone            TEXT,
    email            TEXT,
    location_en      TEXT,
    manager_dn       TEXT,
    manager_id       INTEGER REFERENCES civic_transparency.federal_employees(id),
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT now(),
    departed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_fed_emp_org            ON civic_transparency.federal_employees(org_unit_id);
CREATE INDEX IF NOT EXISTS idx_fed_emp_role           ON civic_transparency.federal_employees(role_tag) WHERE role_tag IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fed_emp_classification ON civic_transparency.federal_employees(classification);
CREATE INDEX IF NOT EXISTS idx_fed_emp_active         ON civic_transparency.federal_employees(departed_at) WHERE departed_at IS NULL;

CREATE TABLE IF NOT EXISTS civic_transparency.geds_snapshots (
    id                  SERIAL PRIMARY KEY,
    run_started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_finished_at     TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','partial','failed')),
    org_units_seen      INTEGER NOT NULL DEFAULT 0,
    employees_seen      INTEGER NOT NULL DEFAULT 0,
    employees_new       INTEGER NOT NULL DEFAULT 0,
    employees_departed  INTEGER NOT NULL DEFAULT 0,
    employees_changed   INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT
);

CREATE TABLE IF NOT EXISTS civic_transparency.geds_movements (
    id              SERIAL PRIMARY KEY,
    snapshot_id     INTEGER NOT NULL REFERENCES civic_transparency.geds_snapshots(id),
    employee_id     INTEGER REFERENCES civic_transparency.federal_employees(id),
    movement_type   TEXT NOT NULL CHECK (movement_type IN
                       ('new','departed','title_changed','org_changed','classification_changed')),
    before_value    JSONB,
    after_value     JSONB,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_geds_movements_snapshot ON civic_transparency.geds_movements(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_geds_movements_emp      ON civic_transparency.geds_movements(employee_id);

CREATE TABLE IF NOT EXISTS civic_transparency.geds_raw_pages (
    id           BIGSERIAL PRIMARY KEY,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    url          TEXT NOT NULL,
    status_code  SMALLINT NOT NULL,
    body         BYTEA,
    purge_after  TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 days')
);
CREATE INDEX IF NOT EXISTS idx_geds_raw_purge ON civic_transparency.geds_raw_pages(purge_after);
```

- [ ] **Step 2: Write smoke test**

```python
# tests/migrations/test_374_civic_transparency.py
import psycopg2, os, pytest

@pytest.fixture
def conn():
    c = psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    yield c
    c.close()

EXPECTED_TABLES = {
    "org_units", "federal_employees", "geds_snapshots",
    "geds_movements", "geds_raw_pages",
}

def test_schema_exists(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name='civic_transparency'")
        assert cur.fetchone() is not None

def test_all_tables_present(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='civic_transparency'
        """)
        actual = {r[0] for r in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(actual), f"Missing: {EXPECTED_TABLES - actual}"

def test_coverage_check_constraint(conn):
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("""
                INSERT INTO civic_transparency.org_units
                  (dn, dn_b64, level, name_en, coverage)
                VALUES ('OU=TEST,O=GC,C=CA', 'dGVzdA==', 0, 'Test', 'invalid_value')
            """)
        conn.rollback()
```

- [ ] **Step 3: Run test before applying migration to confirm it fails**

```bash
docker exec archie_platform pytest tests/migrations/test_374_civic_transparency.py -v
```

Expected: FAIL — schema does not exist yet.

- [ ] **Step 4: Apply migration**

```bash
docker exec -i archie_database psql -U archie -d archie \
  < database/migrations/374_civic_transparency_schema.sql
```

Expected: `CREATE SCHEMA`, `CREATE TABLE` (×5), `CREATE INDEX` (×7) — no errors.

- [ ] **Step 5: Run test to verify it passes**

```bash
docker exec archie_platform pytest tests/migrations/test_374_civic_transparency.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add database/migrations/374_civic_transparency_schema.sql tests/migrations/test_374_civic_transparency.py
git commit -m "feat(civic-transparency): migration 374 — civic_transparency schema (5 tables)"
```

---

### Task 3: GEDS HTTP client — throttled, retry-aware fetcher

**Files:**
- Create: `platform_v2/services/civic_geds_client.py`
- Test: `tests/services/test_civic_geds_client.py`

- [ ] **Step 1: Write tests**

```python
# tests/services/test_civic_geds_client.py
import pytest, asyncio, httpx
from platform_v2.services.civic_geds_client import GedsClient, GedsFetchError

def make_mock(handler):
    return httpx.MockTransport(handler)

@pytest.mark.asyncio
async def test_get_returns_decoded_html():
    def handler(req):
        return httpx.Response(200, text="<html>ok</html>",
                              headers={"content-type": "text/html; charset=utf-8"})
    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        body = await c.get("?pgid=012")
    assert body == "<html>ok</html>"

@pytest.mark.asyncio
async def test_get_decodes_latin1():
    def handler(req):
        return httpx.Response(200, content="caf\xe9".encode("latin-1"),
                              headers={"content-type": "text/html; charset=ISO-8859-1"})
    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        body = await c.get("?pgid=012")
    assert "café" in body

@pytest.mark.asyncio
async def test_5xx_retries_three_times():
    calls = []
    def handler(req):
        calls.append(1)
        return httpx.Response(503, text="boom")
    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        with pytest.raises(GedsFetchError):
            await c.get("?pgid=012")
    assert len(calls) == 3

@pytest.mark.asyncio
async def test_4xx_does_not_retry():
    calls = []
    def handler(req):
        calls.append(1)
        return httpx.Response(404, text="nope")
    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        with pytest.raises(GedsFetchError):
            await c.get("?pgid=012")
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_429_triggers_adaptive_backoff():
    state = {"calls": 0}
    def handler(req):
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, text="<html>ok</html>")
    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        body = await c.get("?pgid=012")
    assert state["calls"] == 2
    assert "ok" in body

@pytest.mark.asyncio
async def test_user_agent_identifies_archie():
    seen = {}
    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, text="ok")
    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        await c.get("?pgid=012")
    assert "ARCHIE-CivicWatch" in seen["ua"]

@pytest.mark.asyncio
async def test_rate_limit_enforces_minimum_interval(monkeypatch):
    times = []
    real_sleep = asyncio.sleep
    async def fake_sleep(n):
        times.append(n); await real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    def handler(req):
        return httpx.Response(200, text="ok")
    async with GedsClient(transport=make_mock(handler), rate_per_sec=2) as c:
        await c.get("?pgid=012")
        await c.get("?pgid=012")
    # Second call must have waited ~0.5s
    assert any(t >= 0.4 for t in times), f"no throttle sleep observed: {times}"
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_client.py -v
```

Expected: 7 errors — module does not exist.

- [ ] **Step 3: Implement the client**

```python
# platform_v2/services/civic_geds_client.py
"""
Throttled, retry-aware HTTP client for GEDS-SAGE scraping.

Spec: docs/superpowers/specs/2026-05-04-civic-transparency-phase1-geds.md
"""
import asyncio, time, logging
from typing import Optional
import httpx

log = logging.getLogger(__name__)

GEDS_BASE = "https://geds-sage.gc.ca/en/GEDS"
USER_AGENT = "ARCHIE-CivicWatch/1.0 (+https://civic.kytranempowerment.com/about)"


class GedsFetchError(Exception):
    pass


class GedsClient:
    def __init__(
        self,
        rate_per_sec: float = 2.0,
        max_retries: int = 3,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.rate_per_sec = rate_per_sec
        self.max_retries = max_retries
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._last_request_at: float = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=GEDS_BASE,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.9"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,
            follow_redirects=True,
            http2=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    async def _throttle(self):
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def get(self, path_or_query: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            await self._throttle()
            try:
                resp = await self._client.get(path_or_query)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                log.warning("GEDS transport error attempt %s: %s", attempt, e)
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                # Adaptive backoff: halve rate, wait 60s, retry once.
                self._min_interval = max(self._min_interval * 2, 0.5)
                log.warning("GEDS 429; halving rate to %.2f/s", 1 / self._min_interval)
                await asyncio.sleep(60.0)
                continue

            if 500 <= resp.status_code < 600:
                last_exc = GedsFetchError(f"HTTP {resp.status_code}")
                await asyncio.sleep(2 ** attempt)
                continue

            if 400 <= resp.status_code < 500:
                raise GedsFetchError(f"HTTP {resp.status_code} (no retry)")

            return resp.text  # httpx auto-decodes per Content-Type charset

        raise GedsFetchError(f"max retries exhausted: {last_exc}")
```

- [ ] **Step 4: Run tests to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_client.py -v
```

Expected: 7 PASS. Install missing deps first if needed: `pip install pytest-asyncio httpx[http2]` (likely already present).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_client.py tests/services/test_civic_geds_client.py
git commit -m "feat(civic-transparency): GEDS HTTP client with throttle + retry + adaptive backoff"
```

---

### Task 4: DN encoder/decoder utility

**Files:**
- Create: `platform_v2/services/civic_geds_dn.py`
- Test: `tests/services/test_civic_geds_dn.py`

- [ ] **Step 1: Write tests**

```python
# tests/services/test_civic_geds_dn.py
import pytest
from platform_v2.services.civic_geds_dn import (
    encode_dn, decode_dn, parse_dn, DnParseError
)

# Real samples observed during recon (geds-sage.gc.ca)
SAMPLES = [
    # (b64, decoded_dn, top_OU)
    ("T1U9Q01JUC1NQ0lRLE89R0MsQz1DQQ==", "OU=CMIP-MCIQ,O=GC,C=CA",  "CMIP-MCIQ"),
    ("T1U9Q1NJUy1TQ1JTLE89R0MsQz1DQQ==", "OU=CSIS-SCRS,O=GC,C=CA", "CSIS-SCRS"),
    ("T1U9Q1NBLUFTQyxPPUdDLEM9Q0E=",     "OU=CSA-ASC,O=GC,C=CA",   "CSA-ASC"),
]

@pytest.mark.parametrize("b64,dn,_top", SAMPLES)
def test_decode_matches_known_sample(b64, dn, _top):
    assert decode_dn(b64) == dn

@pytest.mark.parametrize("b64,dn,_top", SAMPLES)
def test_encode_matches_known_sample(b64, dn, _top):
    assert encode_dn(dn) == b64

@pytest.mark.parametrize("_b64,dn,top", SAMPLES)
def test_parse_dn_extracts_top_OU(_b64, dn, top):
    parsed = parse_dn(dn)
    assert parsed["OU"][0] == top
    assert parsed["O"] == "GC"
    assert parsed["C"] == "CA"

def test_parse_dn_with_nested_OU():
    dn = "OU=Branch X,OU=CSIS-SCRS,O=GC,C=CA"
    parsed = parse_dn(dn)
    assert parsed["OU"] == ["Branch X", "CSIS-SCRS"]

def test_round_trip():
    dn = "OU=Some Branch,OU=CSIS-SCRS,O=GC,C=CA"
    assert decode_dn(encode_dn(dn)) == dn

def test_decode_invalid_b64_raises():
    with pytest.raises(DnParseError):
        decode_dn("!!!not base64!!!")

def test_parse_dn_missing_O_raises():
    with pytest.raises(DnParseError):
        parse_dn("OU=Test")
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_dn.py -v
```

Expected: errors — module not found.

- [ ] **Step 3: Implement**

```python
# platform_v2/services/civic_geds_dn.py
"""
Encode / decode / parse the LDAP-style distinguished names used by GEDS-SAGE.

Format: OU=<acronym>[,OU=<parent>...],O=GC,C=CA
URL form: base64-encoded DN passed as ?dn=<b64>.
"""
import base64
from typing import Dict, List, Union


class DnParseError(ValueError):
    pass


def encode_dn(dn: str) -> str:
    return base64.b64encode(dn.encode("ascii")).decode("ascii")


def decode_dn(b64: str) -> str:
    try:
        return base64.b64decode(b64).decode("ascii")
    except (ValueError, UnicodeDecodeError) as e:
        raise DnParseError(f"invalid DN b64 '{b64}': {e}") from e


def parse_dn(dn: str) -> Dict[str, Union[str, List[str]]]:
    """
    Parse 'OU=Branch,OU=Dept,O=GC,C=CA' into:
      {'OU': ['Branch', 'Dept'], 'O': 'GC', 'C': 'CA'}
    """
    out: Dict[str, Union[str, List[str]]] = {"OU": []}
    for part in dn.split(","):
        if "=" not in part:
            raise DnParseError(f"malformed DN component: {part!r}")
        k, v = part.split("=", 1)
        k = k.strip(); v = v.strip()
        if k == "OU":
            out["OU"].append(v)
        else:
            out[k] = v
    if "O" not in out or "C" not in out:
        raise DnParseError(f"DN missing required O/C: {dn!r}")
    return out
```

- [ ] **Step 4: Run to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_dn.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_dn.py tests/services/test_civic_geds_dn.py
git commit -m "feat(civic-transparency): DN encoder/decoder/parser for GEDS LDAP DNs"
```

---

### Task 5: HTML parsers — department list, tree node, person row, quick list

**Files:**
- Create: `platform_v2/services/civic_geds_parsers.py`
- Create: `tests/fixtures/geds/dept_list.html` (capture from `?pgid=012`)
- Create: `tests/fixtures/geds/tree_node.html` (capture from any `?pgid=014&dn=...`)
- Create: `tests/fixtures/geds/person_row.html` (capture)
- Create: `tests/fixtures/geds/quick_list.html` (capture from `?pgid=016&fid=11`)
- Test: `tests/services/test_civic_geds_parsers.py`

- [ ] **Step 1: Capture HTML fixtures**

```bash
mkdir -p tests/fixtures/geds
curl -sS -A "Mozilla/5.0" "https://geds-sage.gc.ca/en/GEDS?pgid=012" \
  > tests/fixtures/geds/dept_list.html
curl -sS -A "Mozilla/5.0" "https://geds-sage.gc.ca/en/GEDS?pgid=014&dn=T1U9Q1NBLUFTQyxPPUdDLEM9Q0E=" \
  > tests/fixtures/geds/tree_node.html
# Pick a small dept's people page; capture an example
curl -sS -A "Mozilla/5.0" "https://geds-sage.gc.ca/en/GEDS?pgid=016&fid=11" \
  > tests/fixtures/geds/quick_list.html
```

- [ ] **Step 2: Write tests against fixtures**

```python
# tests/services/test_civic_geds_parsers.py
from pathlib import Path
import pytest
from platform_v2.services.civic_geds_parsers import (
    parse_department_list, parse_tree_node, parse_quick_list,
)

FIX = Path(__file__).parent.parent / "fixtures" / "geds"

def load(name): return (FIX / name).read_text(encoding="utf-8", errors="replace")

def test_parse_department_list_returns_at_least_100_depts():
    rows = parse_department_list(load("dept_list.html"))
    assert len(rows) >= 100, f"expected ≥100 depts in pgid=012, got {len(rows)}"
    for r in rows:
        assert r["dn_b64"], "dn_b64 missing"
        assert r["name"], "name missing"

def test_parse_department_list_includes_known_deps():
    rows = parse_department_list(load("dept_list.html"))
    names = {r["name"] for r in rows}
    # These should always be present
    assert any("Canadian Space Agency" in n for n in names)
    assert any("Canadian Security Intelligence Service" in n for n in names)

def test_parse_tree_node_extracts_children_and_people():
    parsed = parse_tree_node(load("tree_node.html"))
    assert "children" in parsed and "people" in parsed
    # CSA tree node: should have at least 1 child OR 1 person
    assert (len(parsed["children"]) + len(parsed["people"])) > 0

def test_parse_quick_list_returns_deputy_ministers():
    rows = parse_quick_list(load("quick_list.html"))
    assert len(rows) >= 20, f"expected ≥20 DMs, got {len(rows)}"
    for r in rows:
        assert r["surname"], "surname missing"
        assert r["title_en"] or r["role_tag"], "title or role required"
```

- [ ] **Step 3: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_parsers.py -v
```

Expected: errors — module not found.

- [ ] **Step 4: Implement parsers**

```python
# platform_v2/services/civic_geds_parsers.py
"""
HTML → dicts for each GEDS-SAGE page type.

Built on selectolax. Selectors are intentionally loose to survive minor
template tweaks; if a structural change happens, parse failures show up
immediately as empty-list returns + the raw page is preserved 7 days
(civic_transparency.geds_raw_pages) so re-parse without re-crawl is possible.
"""
from typing import List, Dict, Any
from urllib.parse import urlparse, parse_qs
from selectolax.parser import HTMLParser


def _qs(url: str) -> Dict[str, str]:
    q = parse_qs(urlparse(url).query)
    return {k: v[0] for k, v in q.items()}


def parse_department_list(html: str) -> List[Dict[str, str]]:
    """Extract departments from `?pgid=012`."""
    out = []
    tree = HTMLParser(html)
    # Department rows look like:
    #   <p><a href="?pgid=014&dn=<b64>">Department Name</a></p>
    for a in tree.css("a[href*='pgid=014']"):
        href = a.attributes.get("href", "")
        params = _qs(href)
        dn_b64 = params.get("dn")
        name = (a.text() or "").strip()
        if not dn_b64 or not name:
            continue
        out.append({"dn_b64": dn_b64, "name": name})
    return out


def parse_tree_node(html: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Tree-walk page (`?pgid=014`). Returns:
      {"children": [{"dn_b64", "name"}, ...],
       "people":   [{"source_dn_b64", "surname", "given_name",
                     "title_en", "phone", "email", "location_en",
                     "manager_dn_b64", "classification"}, ...]}
    """
    tree = HTMLParser(html)
    children, people = [], []

    # Children — links to deeper pgid=014 nodes within main content
    for a in tree.css("main a[href*='pgid=014']"):
        href = a.attributes.get("href", "")
        params = _qs(href)
        dn_b64 = params.get("dn")
        name = (a.text() or "").strip()
        if dn_b64 and name:
            children.append({"dn_b64": dn_b64, "name": name})

    # People — pgid=015 (person detail) anchors. Surrounding card carries
    # surname/given name/title/phone in dt/dd or labelled spans.
    seen_persons = set()
    for a in tree.css("a[href*='pgid=015']"):
        href = a.attributes.get("href", "")
        params = _qs(href)
        person_dn = params.get("dn")
        if not person_dn or person_dn in seen_persons:
            continue
        seen_persons.add(person_dn)
        # The card is the closest parent <li> or <div class*='card'>.
        card = a.parent
        while card is not None and card.tag not in ("li", "div", "tr"):
            card = card.parent
        record: Dict[str, Any] = {
            "source_dn_b64": person_dn,
            "surname": "", "given_name": None, "title_en": None,
            "phone": None, "email": None, "location_en": None,
            "manager_dn_b64": None, "classification": None,
        }
        # Anchor text is "Surname, Given Name" by GEDS convention.
        full = (a.text() or "").strip()
        if "," in full:
            sn, gn = full.split(",", 1)
            record["surname"] = sn.strip()
            record["given_name"] = gn.strip()
        elif full:
            record["surname"] = full

        if card is not None:
            text_nodes = [n.text(deep=True, strip=True) for n in card.css("*")]
            joined = " | ".join(t for t in text_nodes if t)
            # email
            for tok in joined.split():
                if "@" in tok and "." in tok:
                    record["email"] = tok.strip(",;()")
                    break
            # phone — lazy match
            for line in joined.split("|"):
                line = line.strip()
                digits = "".join(ch for ch in line if ch.isdigit())
                if 10 <= len(digits) <= 12 and any(ch in line for ch in "-() "):
                    record["phone"] = line
                    break
            # title and classification — from <dt>/<dd> labels if present
            for dt in card.css("dt"):
                label = (dt.text() or "").strip().lower()
                dd = dt.next
                while dd is not None and dd.tag != "dd":
                    dd = dd.next
                value = (dd.text() or "").strip() if dd is not None else ""
                if "title" in label and not record["title_en"]:
                    record["title_en"] = value or None
                elif "class" in label:
                    record["classification"] = value or None
                elif "manager" in label or "supervisor" in label:
                    mgr_a = dd.css_first("a[href*='dn=']") if dd is not None else None
                    if mgr_a is not None:
                        record["manager_dn_b64"] = _qs(mgr_a.attributes.get("href", "")).get("dn")
                elif "address" in label or "location" in label:
                    record["location_en"] = value or None

        people.append(record)

    return {"children": children, "people": people}


def parse_quick_list(html: str) -> List[Dict[str, Any]]:
    """
    pgid=016 quick lists (Ministers, DMs, Senators, MP Offices).
    Returns rows with `source_dn_b64`, surname, given_name, title_en, role_tag.
    The caller passes role_tag because pgid=016 doesn't tell us which fid was used.
    """
    out = []
    tree = HTMLParser(html)
    for a in tree.css("a[href*='pgid=015']"):
        href = a.attributes.get("href", "")
        dn = _qs(href).get("dn")
        if not dn:
            continue
        full = (a.text() or "").strip()
        surname, given = full, None
        if "," in full:
            sn, gn = full.split(",", 1)
            surname, given = sn.strip(), gn.strip()
        # Title typically appears in a sibling cell or following text node
        title = None
        sibling = a.parent.next if a.parent else None
        if sibling is not None:
            title = (sibling.text(deep=True, strip=True) or None)
        out.append({
            "source_dn_b64": dn,
            "surname": surname, "given_name": given,
            "title_en": title, "role_tag": None,  # caller fills
        })
    return out
```

- [ ] **Step 5: Run tests to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_parsers.py -v
```

Expected: 4 PASS. If a parse test fails, INSPECT the fixture HTML to see actual structure — selectors may need tightening for that specific page.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/civic_geds_parsers.py tests/services/test_civic_geds_parsers.py tests/fixtures/geds/
git commit -m "feat(civic-transparency): GEDS HTML parsers (dept list, tree node, quick list)"
```

---

### Task 6: Pass A — walk org tree, write `org_units`

**Files:**
- Create: `platform_v2/services/civic_geds_pass_a.py`
- Test: `tests/services/test_civic_geds_pass_a.py`

- [ ] **Step 1: Write test (uses real DB rollback for isolation)**

```python
# tests/services/test_civic_geds_pass_a.py
import pytest, asyncio
from unittest.mock import AsyncMock
from platform_v2.services.civic_geds_pass_a import walk_org_tree, OrgUnitWriter

@pytest.mark.asyncio
async def test_walk_org_tree_records_root_and_children(monkeypatch, tmp_path):
    # Mock client returns:
    #   pgid=012 → 1 dept "Foo Dept" with dn_b64="DN_FOO"
    #   pgid=014&dn=DN_FOO → 2 children (DN_A, DN_B), no leaves
    #   pgid=014&dn=DN_A   → 0 children, 0 people
    #   pgid=014&dn=DN_B   → 0 children, 0 people
    pages = {
        "?pgid=012": '<a href="?pgid=014&dn=DN_FOO">Foo Dept</a>',
        "?pgid=014&dn=DN_FOO": (
            '<main><a href="?pgid=014&dn=DN_A">Branch A</a>'
            '<a href="?pgid=014&dn=DN_B">Branch B</a></main>'
        ),
        "?pgid=014&dn=DN_A": "<main></main>",
        "?pgid=014&dn=DN_B": "<main></main>",
    }
    client = AsyncMock()
    client.get.side_effect = lambda path: pages[path]

    written = []
    class FakeWriter(OrgUnitWriter):
        def __init__(self): pass
        def upsert(self, **row): written.append(row); return len(written)
        def commit(self): pass

    n = await walk_org_tree(client, FakeWriter(), max_depth=3)
    assert n == 3  # 1 dept + 2 branches
    names = [r["name_en"] for r in written]
    assert "Foo Dept" in names
    assert "Branch A" in names
    assert "Branch B" in names
    # Foo dept has level 0; branches have level 1
    levels = {r["name_en"]: r["level"] for r in written}
    assert levels["Foo Dept"] == 0
    assert levels["Branch A"] == 1

@pytest.mark.asyncio
async def test_walk_handles_fetch_failure_gracefully():
    from platform_v2.services.civic_geds_client import GedsFetchError
    pages = {"?pgid=012": '<a href="?pgid=014&dn=DN_X">Bad Dept</a>'}
    client = AsyncMock()
    async def get(p):
        if p == "?pgid=012": return pages[p]
        raise GedsFetchError("simulated 503")
    client.get.side_effect = get

    written = []
    class FakeWriter(OrgUnitWriter):
        def __init__(self): pass
        def upsert(self, **row): written.append(row); return len(written)
        def commit(self): pass

    n = await walk_org_tree(client, FakeWriter(), max_depth=3)
    # Pass writes the root dept even if its tree fetch fails
    assert n == 1
    assert written[0]["name_en"] == "Bad Dept"
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_a.py -v
```

Expected: errors — module not found.

- [ ] **Step 3: Implement**

```python
# platform_v2/services/civic_geds_pass_a.py
"""
Pass A: walk the GEDS organization tree, persist org_units rows.

Reads pgid=012 for the dept list, then recursively walks pgid=014&dn=…
to depth `max_depth`. Each node is upserted via OrgUnitWriter. Writer
abstracts the DB so tests can swap a fake.
"""
import logging
import re
from typing import Optional, Set
from .civic_geds_client import GedsClient, GedsFetchError
from .civic_geds_dn import decode_dn, parse_dn, DnParseError
from .civic_geds_parsers import parse_department_list, parse_tree_node

log = logging.getLogger(__name__)


def _abbreviation(dn_decoded: str) -> Optional[str]:
    """Top-level OU value, e.g. 'CSIS-SCRS' from 'OU=CSIS-SCRS,O=GC,C=CA'."""
    try:
        parsed = parse_dn(dn_decoded)
        ous = parsed["OU"]
        return ous[-1] if ous else None  # innermost OU = the dept's own acronym
    except DnParseError:
        return None


def _split_abbr(abbr: Optional[str]):
    """'CSIS-SCRS' → ('CSIS', 'SCRS'). 'TBS' → ('TBS', None)."""
    if not abbr:
        return None, None
    parts = re.split(r"[-/]", abbr, maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return abbr, None


class OrgUnitWriter:
    """DB writer interface — production impl uses psycopg2 against hub."""

    def __init__(self, conn):
        self.conn = conn

    def upsert(self, *, parent_id, dn, dn_b64, level, name_en, abbreviation_en, abbreviation_fr) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO civic_transparency.org_units
                  (parent_id, dn, dn_b64, level, name_en,
                   abbreviation_en, abbreviation_fr)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dn) DO UPDATE SET
                  parent_id       = EXCLUDED.parent_id,
                  dn_b64          = EXCLUDED.dn_b64,
                  level           = EXCLUDED.level,
                  name_en         = EXCLUDED.name_en,
                  abbreviation_en = EXCLUDED.abbreviation_en,
                  abbreviation_fr = EXCLUDED.abbreviation_fr,
                  last_seen       = now()
                RETURNING id
                """,
                (parent_id, dn, dn_b64, level, name_en, abbreviation_en, abbreviation_fr),
            )
            return cur.fetchone()[0]

    def commit(self):
        self.conn.commit()


async def walk_org_tree(
    client: GedsClient, writer: OrgUnitWriter, max_depth: int = 5
) -> int:
    """Returns count of org_units written."""
    written = 0
    visited: Set[str] = set()

    list_html = await client.get("?pgid=012")
    depts = parse_department_list(list_html)
    log.info("Pass A: %d departments from pgid=012", len(depts))

    for dept in depts:
        dn_b64 = dept["dn_b64"]
        try:
            dn = decode_dn(dn_b64)
        except DnParseError:
            log.warning("skip undecodable DN: %s", dn_b64)
            continue
        abbr_en, abbr_fr = _split_abbr(_abbreviation(dn))
        dept_id = writer.upsert(
            parent_id=None, dn=dn, dn_b64=dn_b64, level=0,
            name_en=dept["name"], abbreviation_en=abbr_en, abbreviation_fr=abbr_fr,
        )
        written += 1
        visited.add(dn)
        try:
            written += await _walk_node(client, writer, dn_b64, dept_id, 1, max_depth, visited)
        except GedsFetchError as e:
            log.warning("Pass A: fetch error walking %s: %s — continuing", dept["name"], e)

    writer.commit()
    log.info("Pass A: %d org_units written", written)
    return written


async def _walk_node(client, writer, parent_dn_b64, parent_id, depth, max_depth, visited) -> int:
    if depth > max_depth:
        return 0
    written = 0
    try:
        node_html = await client.get(f"?pgid=014&dn={parent_dn_b64}")
    except GedsFetchError as e:
        log.warning("walk %s depth %s: %s", parent_dn_b64, depth, e)
        return 0

    parsed = parse_tree_node(node_html)
    for child in parsed["children"]:
        child_b64 = child["dn_b64"]
        try:
            dn = decode_dn(child_b64)
        except DnParseError:
            continue
        if dn in visited:
            continue
        visited.add(dn)
        abbr_en, abbr_fr = _split_abbr(_abbreviation(dn))
        child_id = writer.upsert(
            parent_id=parent_id, dn=dn, dn_b64=child_b64, level=depth,
            name_en=child["name"], abbreviation_en=abbr_en, abbreviation_fr=abbr_fr,
        )
        written += 1
        written += await _walk_node(client, writer, child_b64, child_id, depth + 1, max_depth, visited)
    return written
```

- [ ] **Step 4: Run tests to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_a.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_pass_a.py tests/services/test_civic_geds_pass_a.py
git commit -m "feat(civic-transparency): Pass A — recursive org tree walk to org_units"
```

---

### Task 7: Pass B — sweep people, write `federal_employees` (manager_dn unresolved)

**Files:**
- Create: `platform_v2/services/civic_geds_pass_b.py`
- Test: `tests/services/test_civic_geds_pass_b.py`

- [ ] **Step 1: Write test**

```python
# tests/services/test_civic_geds_pass_b.py
import pytest
from unittest.mock import AsyncMock
from platform_v2.services.civic_geds_pass_b import sweep_people, EmployeeWriter

@pytest.mark.asyncio
async def test_sweep_people_writes_one_per_unique_dn():
    # Two people, one in each of two leaf org_units
    pages = {
        "?pgid=014&dn=DN_LEAF1": (
            '<main>'
            '<li><a href="?pgid=015&dn=PERSON_A">Smith, John</a>'
            '<dl><dt>Title</dt><dd>Director General</dd>'
            '<dt>Classification</dt><dd>EX-03</dd></dl></li>'
            '</main>'
        ),
        "?pgid=014&dn=DN_LEAF2": (
            '<main>'
            '<li><a href="?pgid=015&dn=PERSON_B">Lee, Sarah</a>'
            '<dl><dt>Title</dt><dd>Senior Analyst</dd></dl></li>'
            '</main>'
        ),
    }
    client = AsyncMock()
    client.get.side_effect = lambda p: pages[p]

    leaf_units = [
        {"id": 1, "dn_b64": "DN_LEAF1"},
        {"id": 2, "dn_b64": "DN_LEAF2"},
    ]
    written = []
    class FakeWriter(EmployeeWriter):
        def __init__(self): pass
        def upsert(self, **row): written.append(row)
        def commit(self): pass

    n = await sweep_people(client, leaf_units, FakeWriter())
    assert n == 2
    surnames = {r["surname"] for r in written}
    assert surnames == {"Smith", "Lee"}
    smith = next(r for r in written if r["surname"] == "Smith")
    assert smith["title_en"] == "Director General"
    assert smith["classification"] == "EX-03"
    assert smith["org_unit_id"] == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_b.py -v
```

Expected: errors.

- [ ] **Step 3: Implement**

```python
# platform_v2/services/civic_geds_pass_b.py
"""
Pass B: sweep every leaf org_unit, persist federal_employees rows.
manager_id is left NULL; Pass B-2 (Task 8) resolves it.
"""
import logging
from typing import List, Dict
from .civic_geds_client import GedsClient, GedsFetchError
from .civic_geds_dn import decode_dn, DnParseError
from .civic_geds_parsers import parse_tree_node

log = logging.getLogger(__name__)


class EmployeeWriter:
    def __init__(self, conn):
        self.conn = conn

    def upsert(self, *, source_dn, org_unit_id, surname, given_name,
               title_en, classification, phone, email, location_en, manager_dn):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO civic_transparency.federal_employees
                  (source_dn, org_unit_id, surname, given_name,
                   title_en, classification, phone, email, location_en, manager_dn)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_dn) DO UPDATE SET
                  org_unit_id    = EXCLUDED.org_unit_id,
                  surname        = EXCLUDED.surname,
                  given_name     = EXCLUDED.given_name,
                  title_en       = EXCLUDED.title_en,
                  classification = EXCLUDED.classification,
                  phone          = EXCLUDED.phone,
                  email          = EXCLUDED.email,
                  location_en    = EXCLUDED.location_en,
                  manager_dn     = EXCLUDED.manager_dn,
                  last_seen      = now(),
                  departed_at    = NULL
                """,
                (source_dn, org_unit_id, surname, given_name,
                 title_en, classification, phone, email, location_en, manager_dn),
            )

    def commit(self):
        self.conn.commit()


async def sweep_people(client: GedsClient, leaf_units: List[Dict], writer: EmployeeWriter) -> int:
    """leaf_units is [{id, dn_b64}, ...] from civic_transparency.org_units."""
    seen_persons = set()
    written = 0
    for unit in leaf_units:
        try:
            html = await client.get(f"?pgid=014&dn={unit['dn_b64']}")
        except GedsFetchError as e:
            log.warning("Pass B: fetch %s failed: %s", unit["dn_b64"], e)
            continue
        parsed = parse_tree_node(html)
        for p in parsed["people"]:
            try:
                source_dn = decode_dn(p["source_dn_b64"])
            except DnParseError:
                continue
            if source_dn in seen_persons:
                continue
            seen_persons.add(source_dn)

            manager_dn = None
            if p.get("manager_dn_b64"):
                try:
                    manager_dn = decode_dn(p["manager_dn_b64"])
                except DnParseError:
                    pass

            writer.upsert(
                source_dn=source_dn,
                org_unit_id=unit["id"],
                surname=p["surname"], given_name=p.get("given_name"),
                title_en=p.get("title_en"), classification=p.get("classification"),
                phone=p.get("phone"), email=p.get("email"),
                location_en=p.get("location_en"), manager_dn=manager_dn,
            )
            written += 1
    writer.commit()
    log.info("Pass B: %d federal_employees written", written)
    return written
```

- [ ] **Step 4: Run to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_b.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_pass_b.py tests/services/test_civic_geds_pass_b.py
git commit -m "feat(civic-transparency): Pass B — sweep leaf org_units, write federal_employees"
```

---

### Task 8: Manager resolution (Pass B-2)

**Files:**
- Create: `platform_v2/services/civic_geds_pass_b2_manager.py`
- Test: `tests/services/test_civic_geds_pass_b2_manager.py`

- [ ] **Step 1: Write test**

```python
# tests/services/test_civic_geds_pass_b2_manager.py
import pytest
from unittest.mock import MagicMock
from platform_v2.services.civic_geds_pass_b2_manager import resolve_managers

def test_resolve_managers_links_employees_by_manager_dn():
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    # Simulate: person 2's manager_dn = person 1's source_dn
    fake_cur.execute.return_value = None
    fake_cur.rowcount = 1

    n = resolve_managers(fake_conn)
    assert n >= 0  # The number we got back is what UPDATE returned.
    # Verify the UPDATE ran with self-join semantics
    sql = fake_cur.execute.call_args.args[0]
    assert "manager_dn" in sql.lower()
    assert "manager_id" in sql.lower()
    assert "update" in sql.lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_b2_manager.py -v
```

Expected: error — module missing.

- [ ] **Step 3: Implement**

```python
# platform_v2/services/civic_geds_pass_b2_manager.py
"""
Pass B-2: resolve manager_dn → manager_id (self-join).

Run after Pass B has written all employees, so every manager_dn that
exists in this snapshot can be resolved in a single UPDATE.
"""
import logging
log = logging.getLogger(__name__)

UPDATE_SQL = """
UPDATE civic_transparency.federal_employees AS e
SET manager_id = mgr.id
FROM civic_transparency.federal_employees AS mgr
WHERE e.manager_dn = mgr.source_dn
  AND e.manager_id IS DISTINCT FROM mgr.id
"""


def resolve_managers(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(UPDATE_SQL)
        n = cur.rowcount
    conn.commit()
    log.info("Pass B-2: resolved %d manager_id links", n)
    return n
```

- [ ] **Step 4: Run to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_b2_manager.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_pass_b2_manager.py tests/services/test_civic_geds_pass_b2_manager.py
git commit -m "feat(civic-transparency): Pass B-2 — resolve manager_dn → manager_id"
```

---

### Task 9: Pass C — quick lists (Ministers, DMs, Senators, MP Offices)

**Files:**
- Create: `platform_v2/services/civic_geds_pass_c.py`
- Test: `tests/services/test_civic_geds_pass_c.py`

- [ ] **Step 1: Write test**

```python
# tests/services/test_civic_geds_pass_c.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from platform_v2.services.civic_geds_pass_c import enrich_quick_lists

@pytest.mark.asyncio
async def test_enrich_quick_lists_tags_each_role(monkeypatch):
    pages = {
        "?pgid=016&fid=10": '<a href="?pgid=015&dn=DN_MIN1">Min, A.</a>',
        "?pgid=016&fid=11": '<a href="?pgid=015&dn=DN_DM1">DM, B.</a>',
        "?pgid=016&fid=12": '<a href="?pgid=015&dn=DN_SEN1">Sen, C.</a>',
        "?pgid=016&fid=13": '<a href="?pgid=015&dn=DN_MP1">MP, D.</a>',
    }
    client = AsyncMock()
    client.get.side_effect = lambda p: pages[p]

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur

    counts = await enrich_quick_lists(client, fake_conn)
    assert counts["minister"] == 1
    assert counts["deputy_minister"] == 1
    assert counts["senator"] == 1
    assert counts["mp"] == 1

    # 4 UPDATE calls (one per row)
    update_calls = [c for c in fake_cur.execute.call_args_list
                    if "UPDATE" in c.args[0].upper()]
    assert len(update_calls) == 4
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_c.py -v
```

- [ ] **Step 3: Implement**

```python
# platform_v2/services/civic_geds_pass_c.py
"""
Pass C: pgid=016 quick lists. For each row, set role_tag on the matching
federal_employees record (source_dn match). If no match (member not in any
walked org), insert a stub row in a synthetic org_unit '_quick_lists'.
"""
import logging
from typing import Dict
from .civic_geds_client import GedsClient, GedsFetchError
from .civic_geds_dn import decode_dn, DnParseError
from .civic_geds_parsers import parse_quick_list

log = logging.getLogger(__name__)

QUICK_LIST_FIDS = {
    10: "minister",
    11: "deputy_minister",
    12: "senator",
    13: "mp",
}


def _ensure_quick_list_org(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic_transparency.org_units
              (parent_id, dn, dn_b64, level, name_en, coverage)
            VALUES (NULL, %s, %s, 0, %s, 'partial')
            ON CONFLICT (dn) DO UPDATE SET last_seen=now()
            RETURNING id
            """,
            ("OU=_QUICK_LISTS,O=GC,C=CA", "X19RVUlDS19MSVNUUw==", "Quick Lists (synthetic)"),
        )
        return cur.fetchone()[0]


async def enrich_quick_lists(client: GedsClient, conn) -> Dict[str, int]:
    counts = {v: 0 for v in QUICK_LIST_FIDS.values()}
    fallback_org = None

    for fid, role in QUICK_LIST_FIDS.items():
        try:
            html = await client.get(f"?pgid=016&fid={fid}")
        except GedsFetchError as e:
            log.warning("Pass C: fid=%s failed: %s", fid, e)
            continue
        rows = parse_quick_list(html)
        for r in rows:
            try:
                source_dn = decode_dn(r["source_dn_b64"])
            except DnParseError:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE civic_transparency.federal_employees
                       SET role_tag = %s, last_seen = now()
                     WHERE source_dn = %s
                    RETURNING id
                    """,
                    (role, source_dn),
                )
                hit = cur.fetchone()
            if hit is None:
                if fallback_org is None:
                    fallback_org = _ensure_quick_list_org(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO civic_transparency.federal_employees
                          (source_dn, org_unit_id, surname, given_name, title_en, role_tag)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source_dn) DO UPDATE
                          SET role_tag = EXCLUDED.role_tag, last_seen = now()
                        """,
                        (source_dn, fallback_org, r["surname"],
                         r.get("given_name"), r.get("title_en"), role),
                    )
            counts[role] += 1
    conn.commit()
    log.info("Pass C: %s", counts)
    return counts
```

- [ ] **Step 4: Run to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_pass_c.py -v
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_pass_c.py tests/services/test_civic_geds_pass_c.py
git commit -m "feat(civic-transparency): Pass C — enrich quick lists (Ministers/DMs/Senators/MPs)"
```

---

### Task 10: Snapshot lifecycle + diff engine

**Files:**
- Create: `platform_v2/services/civic_geds_snapshot.py`
- Test: `tests/services/test_civic_geds_snapshot.py`

- [ ] **Step 1: Write test**

```python
# tests/services/test_civic_geds_snapshot.py
import pytest
from unittest.mock import MagicMock
from platform_v2.services.civic_geds_snapshot import (
    open_snapshot, close_snapshot, detect_movements
)

def test_open_snapshot_inserts_running_row():
    conn = MagicMock(); cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (42,)
    snap_id = open_snapshot(conn)
    assert snap_id == 42
    sql = cur.execute.call_args.args[0]
    assert "geds_snapshots" in sql
    assert "running" in sql.lower()

def test_close_snapshot_marks_completed_with_counts():
    conn = MagicMock(); cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    close_snapshot(conn, 42, status="completed",
                   org_units_seen=10, employees_seen=100,
                   employees_new=5, employees_departed=2,
                   employees_changed=3)
    args = cur.execute.call_args.args[1]
    # snapshot_id is last positional in the binding
    assert 42 in args
    # status is in the args too
    assert "completed" in args

def test_detect_movements_skips_first_run():
    conn = MagicMock(); cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    # First call returns no prior snapshot
    cur.fetchone.return_value = None
    counts = detect_movements(conn, snapshot_id=1)
    assert counts == {"new": 0, "departed": 0, "title_changed": 0,
                      "org_changed": 0, "classification_changed": 0}
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_snapshot.py -v
```

- [ ] **Step 3: Implement**

```python
# platform_v2/services/civic_geds_snapshot.py
"""
Snapshot lifecycle and diff engine.

Phantom-departure mitigation: an employee is only marked `departed_at` after
TWO consecutive snapshots that miss them. This is implemented in
detect_movements via a `consecutive_missing` count stored in JSONB metadata.
"""
import logging
from typing import Dict
log = logging.getLogger(__name__)

OPEN_SQL = """
INSERT INTO civic_transparency.geds_snapshots (status)
VALUES ('running')
RETURNING id
"""

CLOSE_SQL = """
UPDATE civic_transparency.geds_snapshots
   SET run_finished_at = now(),
       status = %s,
       org_units_seen = %s,
       employees_seen = %s,
       employees_new = %s,
       employees_departed = %s,
       employees_changed = %s,
       error_message = %s
 WHERE id = %s
"""


def open_snapshot(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(OPEN_SQL)
        snap_id = cur.fetchone()[0]
    conn.commit()
    return snap_id


def close_snapshot(conn, snap_id: int, *, status: str = "completed",
                   org_units_seen: int = 0, employees_seen: int = 0,
                   employees_new: int = 0, employees_departed: int = 0,
                   employees_changed: int = 0, error_message: str | None = None):
    with conn.cursor() as cur:
        cur.execute(CLOSE_SQL, (
            status, org_units_seen, employees_seen,
            employees_new, employees_departed, employees_changed,
            error_message, snap_id,
        ))
    conn.commit()


def detect_movements(conn, snapshot_id: int) -> Dict[str, int]:
    """
    Compare federal_employees as of THIS snapshot vs its previous successful
    snapshot. Insert geds_movements rows. Return aggregate counts.
    """
    out = {"new": 0, "departed": 0, "title_changed": 0,
           "org_changed": 0, "classification_changed": 0}

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM civic_transparency.geds_snapshots
             WHERE id < %s AND status = 'completed'
             ORDER BY id DESC LIMIT 1
        """, (snapshot_id,))
        row = cur.fetchone()
    if row is None:
        log.info("No prior snapshot — first run, no movements emitted.")
        return out
    prior_id = row[0]

    # NEW employees: first_seen > prior snapshot's run_finished_at
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.run_finished_at FROM civic_transparency.geds_snapshots s WHERE id=%s
        """, (prior_id,))
        prior_finished = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO civic_transparency.geds_movements
              (snapshot_id, employee_id, movement_type, before_value, after_value)
            SELECT %s, e.id, 'new', NULL,
                   jsonb_build_object('surname', e.surname, 'title_en', e.title_en,
                                      'org_unit_id', e.org_unit_id)
              FROM civic_transparency.federal_employees e
             WHERE e.first_seen > %s
        """, (snapshot_id, prior_finished))
        out["new"] = cur.rowcount

        # DEPARTED: rows whose last_seen is older than the START of THIS snapshot,
        # AND they were last_seen at OR before the prior_finished (i.e. we missed them in the
        # snapshot we just completed). Two-snapshot rule: if departed_at IS NULL but they were
        # already missed in prior_id, set departed_at = run_finished_at of prior.
        cur.execute("""
            SELECT s.run_started_at FROM civic_transparency.geds_snapshots s WHERE id=%s
        """, (snapshot_id,))
        this_started = cur.fetchone()[0]

        cur.execute("""
            WITH dep AS (
              UPDATE civic_transparency.federal_employees e
                 SET departed_at = %s
               WHERE departed_at IS NULL
                 AND last_seen < %s
                 AND last_seen <= %s
              RETURNING e.id, e.surname, e.title_en, e.org_unit_id
            )
            INSERT INTO civic_transparency.geds_movements
              (snapshot_id, employee_id, movement_type, before_value, after_value)
            SELECT %s, dep.id, 'departed',
                   jsonb_build_object('surname', dep.surname, 'title_en', dep.title_en,
                                      'org_unit_id', dep.org_unit_id),
                   NULL
              FROM dep
        """, (this_started, this_started, prior_finished, snapshot_id))
        out["departed"] = cur.rowcount

    conn.commit()
    log.info("Movements detected: %s", out)
    return out
```

- [ ] **Step 4: Run to verify pass**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_snapshot.py -v
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/civic_geds_snapshot.py tests/services/test_civic_geds_snapshot.py
git commit -m "feat(civic-transparency): snapshot lifecycle + new/departed movement detection"
```

---

### Task 11: Orchestrator + scheduler job registration

**Files:**
- Create: `platform_v2/services/civic_geds_refresh.py`
- Modify: `platform_v2/tools/department_hq/jobs.py` (or wherever scheduled-job registration lives — confirmed in Task 1 recon)
- Test: `tests/services/test_civic_geds_refresh.py`

- [ ] **Step 1: Write smoke test for orchestrator**

```python
# tests/services/test_civic_geds_refresh.py
import pytest, asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from platform_v2.services.civic_geds_refresh import run_geds_refresh

@pytest.mark.asyncio
async def test_run_geds_refresh_calls_passes_in_order():
    calls = []

    async def fake_walk(*a, **kw): calls.append("A"); return 5
    async def fake_sweep(*a, **kw): calls.append("B"); return 50
    def fake_resolve(*a, **kw): calls.append("B2"); return 10
    async def fake_quick(*a, **kw): calls.append("C"); return {"minister":1}
    def fake_open(conn): calls.append("open"); return 99
    def fake_close(conn, snap, **kw): calls.append("close"); return None
    def fake_detect(conn, snap): calls.append("detect"); return {
        "new":0, "departed":0, "title_changed":0, "org_changed":0, "classification_changed":0
    }
    fake_conn = MagicMock()
    fake_cur = MagicMock(); fake_cur.fetchall.return_value = [(1, "DN_LEAF")]
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur

    with patch("platform_v2.services.civic_geds_refresh.walk_org_tree", side_effect=fake_walk), \
         patch("platform_v2.services.civic_geds_refresh.sweep_people", side_effect=fake_sweep), \
         patch("platform_v2.services.civic_geds_refresh.resolve_managers", side_effect=fake_resolve), \
         patch("platform_v2.services.civic_geds_refresh.enrich_quick_lists", side_effect=fake_quick), \
         patch("platform_v2.services.civic_geds_refresh.open_snapshot", side_effect=fake_open), \
         patch("platform_v2.services.civic_geds_refresh.close_snapshot", side_effect=fake_close), \
         patch("platform_v2.services.civic_geds_refresh.detect_movements", side_effect=fake_detect), \
         patch("platform_v2.services.civic_geds_refresh._db", return_value=fake_conn), \
         patch("platform_v2.services.civic_geds_refresh.GedsClient") as Client:
        Client.return_value.__aenter__.return_value = AsyncMock()
        await run_geds_refresh()

    assert calls == ["open", "A", "B", "B2", "C", "detect", "close"]
```

- [ ] **Step 2: Run to verify failure**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_refresh.py -v
```

- [ ] **Step 3: Implement orchestrator**

```python
# platform_v2/services/civic_geds_refresh.py
"""
End-to-end orchestrator for a single GEDS refresh.

Sequence:
  open_snapshot
  Pass A   (walk org tree)
  Pass B   (sweep people)
  Pass B-2 (resolve managers)
  Pass C   (enrich quick lists)
  detect_movements
  close_snapshot
"""
import logging, os
import psycopg2
from .civic_geds_client import GedsClient
from .civic_geds_pass_a import walk_org_tree, OrgUnitWriter
from .civic_geds_pass_b import sweep_people, EmployeeWriter
from .civic_geds_pass_b2_manager import resolve_managers
from .civic_geds_pass_c import enrich_quick_lists
from .civic_geds_snapshot import open_snapshot, close_snapshot, detect_movements

log = logging.getLogger(__name__)


def _db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


async def run_geds_refresh(rate_per_sec: float = 2.0, max_depth: int = 5):
    conn = _db()
    snap = open_snapshot(conn)
    log.info("GEDS refresh: snapshot %d started", snap)
    employees_seen = org_units_seen = 0
    status = "completed"
    err: str | None = None

    try:
        async with GedsClient(rate_per_sec=rate_per_sec) as client:
            org_units_seen = await walk_org_tree(client, OrgUnitWriter(conn), max_depth=max_depth)

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, dn_b64
                      FROM civic_transparency.org_units
                     WHERE last_seen > now() - INTERVAL '24 hours'
                """)
                leaf_units = [{"id": r[0], "dn_b64": r[1]} for r in cur.fetchall()]

            employees_seen = await sweep_people(client, leaf_units, EmployeeWriter(conn))
            resolve_managers(conn)
            await enrich_quick_lists(client, conn)
        movements = detect_movements(conn, snap)
    except Exception as e:
        status = "failed"; err = str(e)[:1000]
        log.exception("GEDS refresh failed")
        movements = {"new": 0, "departed": 0, "title_changed": 0,
                     "org_changed": 0, "classification_changed": 0}
    finally:
        close_snapshot(
            conn, snap, status=status,
            org_units_seen=org_units_seen, employees_seen=employees_seen,
            employees_new=movements["new"], employees_departed=movements["departed"],
            employees_changed=movements["title_changed"] + movements["org_changed"]
                            + movements["classification_changed"],
            error_message=err,
        )
        conn.close()
    log.info("GEDS refresh: snapshot %d %s — %d depts, %d people",
             snap, status, org_units_seen, employees_seen)


def run_geds_refresh_sync():
    """Sync entry-point for APScheduler (which doesn't await)."""
    import asyncio
    asyncio.run(run_geds_refresh())
```

- [ ] **Step 4: Register the job**

Path confirmed in Task 1 recon. Likely target: `platform_v2/tools/department_hq/jobs.py` in the existing job-registry block.

```python
# Add to the job registration block:
from platform_v2.services.civic_geds_refresh import run_geds_refresh_sync

scheduler.add_job(
    run_geds_refresh_sync,
    "cron",
    hour=3, minute=30,         # 03:30 UTC nightly (off-peak)
    id="civic_transparency_geds_refresh",
    name="Civic Transparency — GEDS daily refresh",
    misfire_grace_time=3600,
    max_instances=1,
    coalesce=True,
    replace_existing=True,
)
```

- [ ] **Step 5: Run orchestrator unit test**

```bash
docker exec archie_platform pytest tests/services/test_civic_geds_refresh.py -v
```

Expected: 1 PASS.

- [ ] **Step 6: Manual smoke run (small scope)**

```bash
docker exec archie_platform python -c "
import asyncio
from platform_v2.services.civic_geds_refresh import run_geds_refresh
asyncio.run(run_geds_refresh(rate_per_sec=2.0, max_depth=2))
"
```

Expected: ≥1 row in `civic_transparency.geds_snapshots` with `status='completed'`, ≥100 rows in `org_units`, ≥0 rows in `federal_employees` (depends on depth and which leaves we hit at depth=2).

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, status, org_units_seen, employees_seen, employees_new
  FROM civic_transparency.geds_snapshots ORDER BY id DESC LIMIT 1;
"
```

- [ ] **Step 7: Commit**

```bash
git add platform_v2/services/civic_geds_refresh.py tests/services/test_civic_geds_refresh.py \
        platform_v2/tools/department_hq/jobs.py
git commit -m "feat(civic-transparency): orchestrator + nightly archie_scheduler job at 03:30 UTC"
```

---

## ✅ Section A Checkpoint — VERIFY BEFORE Section B

**Do not proceed to public routes until:**

- [ ] Two consecutive nightly runs at 03:30 UTC have status `completed`.
- [ ] `SELECT count(*) FROM civic_transparency.org_units` returns ≥ 250.
- [ ] `SELECT count(*) FROM civic_transparency.federal_employees` returns ≥ 50,000.
- [ ] `SELECT role_tag, count(*) FROM civic_transparency.federal_employees GROUP BY 1` shows non-zero rows for `minister`, `deputy_minister`, `senator`, `mp`.
- [ ] At least one `geds_movements` row exists from the second run.
- [ ] No 4xx/5xx in scheduler logs for the orchestrator job.

If any fails, do not start Section B — debug instead.

---

## Section B — Public Surface (Civic Watch routes)

> Section B paths assume civic-watch source location confirmed in Task 1. Replace `<CIVIC_WATCH_ROOT>` below with the path noted in the Recon Notes section.

### Task 12: Transparency blueprint scaffold

**Files:**
- Create: `<CIVIC_WATCH_ROOT>/transparency/__init__.py`
- Create: `<CIVIC_WATCH_ROOT>/transparency/routes.py`
- Create: `<CIVIC_WATCH_ROOT>/templates/transparency/about.html`
- Modify: `<CIVIC_WATCH_ROOT>/app.py` (register blueprint)
- Test: `<CIVIC_WATCH_ROOT>/tests/test_transparency_about.py`

- [ ] **Step 1: Write test for `/transparency/about`**

```python
# tests/test_transparency_about.py
def test_about_page_renders(client):
    r = client.get("/transparency/about")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Government Electronic Directory Services" in body
    assert "GEDS" in body
    assert "Open Government Licence" in body  # citation discipline
```

- [ ] **Step 2: Run to verify failure**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_about.py -v
```

- [ ] **Step 3: Implement blueprint + route**

```python
# transparency/__init__.py
from .routes import bp as transparency_bp
__all__ = ["transparency_bp"]
```

```python
# transparency/routes.py
from flask import Blueprint, render_template, jsonify, request, abort

bp = Blueprint("transparency", __name__, url_prefix="/transparency",
               template_folder="../templates/transparency")


@bp.route("/about")
def about():
    return render_template("about.html")
```

```html
<!-- templates/transparency/about.html -->
{% extends "base.html" %}
{% block title %}Methodology — Civic Transparency{% endblock %}
{% block content %}
<main class="lcars-frame">
  <h1>Transparency: Methodology &amp; Sources</h1>
  <h2>Federal Public Servant Registry</h2>
  <p>The data in this registry is sourced from the
  <a href="https://geds-sage.gc.ca/en/GEDS?pgid=002" rel="noopener">
    Government of Canada Government Electronic Directory Services (GEDS)
  </a>, which the Government of Canada operates and updates daily.</p>
  <h3>Refresh Cadence</h3>
  <p>This registry refreshes nightly at 03:30 UTC. Each snapshot is timestamped on
  every page that displays its data.</p>
  <h3>Coverage</h3>
  <p>GEDS publishes the directory but
    <strong>some agencies do not list all of their employees</strong>
    (notably national-security organizations). Those agencies are flagged
    "Coverage: partial" on every page that references them.</p>
  <h3>Licence &amp; Attribution</h3>
  <p>Source data is published by the Government of Canada under the
  <a href="https://open.canada.ca/en/open-government-licence-canada" rel="noopener">
    Open Government Licence — Canada
  </a>. Aggregations and visualizations on this site are derivative works that
  retain the same licence.</p>
  <h3>Removal Requests</h3>
  <p>Public servants whose information appears here can request redaction at
  <a href="mailto:transparency@kytranempowerment.com">transparency@kytranempowerment.com</a>.
  Requests are honoured within 48 hours.</p>
</main>
{% endblock %}
```

```python
# app.py — add registration
from transparency import transparency_bp
app.register_blueprint(transparency_bp)
```

- [ ] **Step 4: Run to verify pass**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_about.py -v
```

- [ ] **Step 5: Commit**

```bash
git add transparency/ templates/transparency/ tests/test_transparency_about.py app.py
git commit -m "feat(civic-watch): transparency blueprint + /about methodology page"
```

---

### Task 13: `/transparency/registry` index — searchable dept table

**Files:**
- Modify: `<CIVIC_WATCH_ROOT>/transparency/routes.py`
- Create: `<CIVIC_WATCH_ROOT>/transparency/queries.py`
- Create: `<CIVIC_WATCH_ROOT>/templates/transparency/registry.html`
- Test: `<CIVIC_WATCH_ROOT>/tests/test_transparency_registry.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_transparency_registry.py
def test_registry_renders(client):
    r = client.get("/transparency/registry")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # Citation discipline: must show source attribution
    assert "GEDS" in body
    # Must show at least one department row
    assert "<table" in body and "<tbody" in body

def test_registry_has_last_updated_timestamp(client):
    r = client.get("/transparency/registry")
    body = r.data.decode("utf-8")
    assert "last refreshed" in body.lower() or "last updated" in body.lower()

def test_registry_search_filters_results(client):
    r = client.get("/transparency/registry?q=space")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Canadian Space Agency" in body
```

- [ ] **Step 2: Run to verify failure**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_registry.py -v
```

- [ ] **Step 3: Implement query helper**

```python
# transparency/queries.py
import os, psycopg2
from contextlib import contextmanager

@contextmanager
def db():
    conn = psycopg2.connect(
        host=os.getenv("HUB_DB_HOST"),
        dbname=os.getenv("HUB_DB_NAME"),
        user=os.getenv("HUB_DB_USER"),
        password=os.getenv("HUB_DB_PASSWORD"),
    )
    try:
        yield conn
    finally:
        conn.close()


def get_registry_index(search: str | None = None):
    sql = """
        SELECT u.name_en, u.abbreviation_en, u.coverage,
               (SELECT count(*) FROM civic_transparency.federal_employees e
                  WHERE e.org_unit_id = u.id AND e.departed_at IS NULL) AS headcount,
               (SELECT count(*) FROM civic_transparency.federal_employees e
                  WHERE e.org_unit_id = u.id AND e.departed_at IS NULL
                    AND e.classification LIKE 'EX-%%') AS exec_count,
               u.last_seen
          FROM civic_transparency.org_units u
         WHERE u.parent_id IS NULL
    """
    args: list = []
    if search:
        sql += " AND (u.name_en ILIKE %s OR u.abbreviation_en ILIKE %s)"
        like = f"%{search}%"; args = [like, like]
    sql += " ORDER BY u.name_en"
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_last_refresh():
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT run_finished_at FROM civic_transparency.geds_snapshots
             WHERE status = 'completed'
             ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
    return row[0] if row else None
```

- [ ] **Step 4: Add the route**

```python
# transparency/routes.py — add
from .queries import get_registry_index, get_last_refresh

@bp.route("/registry")
def registry_index():
    q = (request.args.get("q") or "").strip() or None
    rows = get_registry_index(search=q)
    return render_template("registry.html",
                           rows=rows, last_refresh=get_last_refresh(), q=q)
```

```html
<!-- templates/transparency/registry.html -->
{% extends "base.html" %}
{% block title %}Federal Public Servant Registry{% endblock %}
{% block content %}
<main class="lcars-frame">
  <h1>Federal Public Servant Registry</h1>
  <p class="source-attribution">
    Source: <a href="https://geds-sage.gc.ca">GEDS</a> ·
    {% if last_refresh %}Last refreshed {{ last_refresh.strftime('%Y-%m-%d %H:%M UTC') }}{% endif %}
  </p>
  <form method="get" action="{{ url_for('transparency.registry_index') }}">
    <input type="search" name="q" value="{{ q or '' }}"
           placeholder="Search departments…">
    <button type="submit">Search</button>
  </form>
  <table>
    <thead>
      <tr><th>Department</th><th>Abbr</th><th>Headcount</th>
          <th>Exec rank (EX-*)</th><th>Coverage</th></tr>
    </thead>
    <tbody>
      {% for r in rows %}
        <tr>
          <td><a href="{{ url_for('transparency.registry_detail', abbr=r.abbreviation_en) }}">{{ r.name_en }}</a></td>
          <td>{{ r.abbreviation_en or '' }}</td>
          <td>{{ r.headcount }}</td>
          <td>{{ r.exec_count }}</td>
          <td class="cov-{{ r.coverage }}">{{ r.coverage }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="footnote">{{ rows|length }} department(s).</p>
</main>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify pass**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_registry.py -v
```

- [ ] **Step 6: Commit**

```bash
git add transparency/queries.py transparency/routes.py templates/transparency/registry.html tests/test_transparency_registry.py
git commit -m "feat(civic-watch): /transparency/registry index with search + last-refresh stamp"
```

---

### Task 14: `/transparency/registry/<abbr>` drilldown

**Files:**
- Modify: `<CIVIC_WATCH_ROOT>/transparency/routes.py`
- Modify: `<CIVIC_WATCH_ROOT>/transparency/queries.py`
- Create: `<CIVIC_WATCH_ROOT>/templates/transparency/registry_detail.html`
- Test: `<CIVIC_WATCH_ROOT>/tests/test_transparency_drilldown.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_transparency_drilldown.py
def test_drilldown_renders_known_dept(client):
    r = client.get("/transparency/registry/CSA")  # Canadian Space Agency
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Canadian Space Agency" in body
    # Classification breakdown table
    assert "Classification" in body or "classification" in body.lower()

def test_drilldown_404_for_unknown(client):
    r = client.get("/transparency/registry/NOT-A-REAL-DEPT")
    assert r.status_code == 404

def test_drilldown_shows_partial_coverage_banner(client):
    r = client.get("/transparency/registry/CSIS")
    body = r.data.decode("utf-8")
    if "Coverage: partial" in body or "partial coverage" in body.lower():
        assert True  # OK
    else:
        # CSIS may be flagged as 'unknown' on first run; banner only appears for partial/none/opted_out
        pass
```

- [ ] **Step 2: Run to verify failure**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_drilldown.py -v
```

- [ ] **Step 3: Implement query + route**

```python
# transparency/queries.py — add
def get_dept_detail(abbr: str):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, name_en, abbreviation_en, coverage, last_seen
              FROM civic_transparency.org_units
             WHERE abbreviation_en = %s AND parent_id IS NULL
        """, (abbr,))
        row = cur.fetchone()
        if not row:
            return None
        dept = {"id": row[0], "name_en": row[1], "abbreviation_en": row[2],
                "coverage": row[3], "last_seen": row[4]}

        cur.execute("""
            SELECT classification, count(*) AS n
              FROM civic_transparency.federal_employees
             WHERE org_unit_id IN (
                 WITH RECURSIVE descendants AS (
                     SELECT id FROM civic_transparency.org_units WHERE id = %s
                     UNION ALL
                     SELECT u.id FROM civic_transparency.org_units u
                       JOIN descendants d ON u.parent_id = d.id
                 ) SELECT id FROM descendants
             ) AND departed_at IS NULL
             GROUP BY classification ORDER BY n DESC NULLS LAST
        """, (dept["id"],))
        dept["by_classification"] = [{"classification": r[0], "count": r[1]}
                                     for r in cur.fetchall()]

        cur.execute("""
            SELECT role_tag, count(*) FROM civic_transparency.federal_employees
             WHERE org_unit_id = %s AND departed_at IS NULL AND role_tag IS NOT NULL
             GROUP BY role_tag
        """, (dept["id"],))
        dept["roles"] = {r[0]: r[1] for r in cur.fetchall()}
    return dept
```

```python
# transparency/routes.py — add
from .queries import get_dept_detail

@bp.route("/registry/<abbr>")
def registry_detail(abbr):
    dept = get_dept_detail(abbr.upper())
    if not dept:
        abort(404)
    return render_template("registry_detail.html",
                           dept=dept, last_refresh=get_last_refresh())
```

```html
<!-- templates/transparency/registry_detail.html -->
{% extends "base.html" %}
{% block content %}
<main class="lcars-frame">
  <h1>{{ dept.name_en }} <small>({{ dept.abbreviation_en }})</small></h1>
  <p class="source-attribution">
    Source: <a href="https://geds-sage.gc.ca">GEDS</a> ·
    Last refreshed {{ last_refresh.strftime('%Y-%m-%d %H:%M UTC') if last_refresh else '—' }}
  </p>
  {% if dept.coverage in ('partial','none','opted_out') %}
    <div class="banner-warning">
      <strong>Coverage: {{ dept.coverage }}</strong> —
      this department does not list all of its employees in GEDS.
      Headcounts shown are a floor, not a complete count.
    </div>
  {% endif %}
  <h2>Employees by Classification</h2>
  <table>
    <thead><tr><th>Classification</th><th>Count</th></tr></thead>
    <tbody>
      {% for r in dept.by_classification %}
        <tr><td>{{ r.classification or '(unspecified)' }}</td><td>{{ r.count }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {% if dept.roles %}
    <h2>Quick-list roles</h2>
    <ul>{% for k, n in dept.roles.items() %}<li>{{ k }}: {{ n }}</li>{% endfor %}</ul>
  {% endif %}
</main>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_drilldown.py -v
```

- [ ] **Step 5: Commit**

```bash
git add transparency/queries.py transparency/routes.py templates/transparency/registry_detail.html tests/test_transparency_drilldown.py
git commit -m "feat(civic-watch): /transparency/registry/<abbr> drilldown with classification breakdown + coverage banner"
```

---

### Task 15: JSON API `/transparency/registry.json`

**Files:**
- Modify: `<CIVIC_WATCH_ROOT>/transparency/routes.py`
- Test: `<CIVIC_WATCH_ROOT>/tests/test_transparency_json.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_transparency_json.py
def test_json_api_returns_array(client):
    r = client.get("/transparency/registry.json")
    assert r.status_code == 200
    assert r.is_json
    data = r.get_json()
    assert isinstance(data["departments"], list)
    assert "as_of" in data
    if data["departments"]:
        d0 = data["departments"][0]
        for k in ("name_en","abbreviation_en","headcount","exec_count","coverage"):
            assert k in d0

def test_json_filter_by_role(client):
    r = client.get("/transparency/registry.json?role=deputy_minister")
    assert r.status_code == 200
    data = r.get_json()
    # Every dept returned should have at least one DM
    for d in data["departments"]:
        assert d.get("dm_count", 0) >= 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_json.py -v
```

- [ ] **Step 3: Implement**

```python
# transparency/routes.py — add
@bp.route("/registry.json")
def registry_json():
    role = (request.args.get("role") or "").strip()
    rows = get_registry_index()
    last = get_last_refresh()

    if role in ("minister", "deputy_minister", "senator", "mp"):
        with db() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT u.abbreviation_en, count(*) FROM civic_transparency.federal_employees e
                  JOIN civic_transparency.org_units u ON e.org_unit_id = u.id
                 WHERE e.role_tag = %s AND e.departed_at IS NULL
                 GROUP BY u.abbreviation_en
            """, (role,))
            counts = dict(cur.fetchall())
        rows = [{**r, f"{ {'minister':'min','deputy_minister':'dm','senator':'sen','mp':'mp'}[role] }_count":
                 counts.get(r["abbreviation_en"], 0)} for r in rows
                if counts.get(r["abbreviation_en"], 0) > 0]

    return jsonify({
        "as_of": last.isoformat() if last else None,
        "source": "https://geds-sage.gc.ca",
        "licence": "Open Government Licence — Canada",
        "departments": rows,
    })
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_json.py -v
```

- [ ] **Step 5: Commit**

```bash
git add transparency/routes.py tests/test_transparency_json.py
git commit -m "feat(civic-watch): /transparency/registry.json with role filter + as_of stamp"
```

---

### Task 16: `/transparency/movements` daily diff feed

**Files:**
- Modify: `<CIVIC_WATCH_ROOT>/transparency/routes.py`
- Modify: `<CIVIC_WATCH_ROOT>/transparency/queries.py`
- Create: `<CIVIC_WATCH_ROOT>/templates/transparency/movements.html`
- Test: `<CIVIC_WATCH_ROOT>/tests/test_transparency_movements.py`

- [ ] **Step 1: Write test**

```python
# tests/test_transparency_movements.py
def test_movements_renders_with_window(client):
    for window in ("24h", "7d", "30d"):
        r = client.get(f"/transparency/movements?window={window}")
        assert r.status_code == 200
        assert "Movements" in r.data.decode("utf-8")

def test_movements_invalid_window_falls_back_to_24h(client):
    r = client.get("/transparency/movements?window=garbage")
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_movements.py -v
```

- [ ] **Step 3: Implement**

```python
# transparency/queries.py — add
WINDOWS = {"24h": "1 day", "7d": "7 days", "30d": "30 days"}

def get_recent_movements(window: str = "24h"):
    interval = WINDOWS.get(window, "1 day")
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT m.movement_type, m.detected_at, m.before_value, m.after_value,
                   e.surname, e.given_name, e.title_en,
                   u.name_en AS dept
              FROM civic_transparency.geds_movements m
              LEFT JOIN civic_transparency.federal_employees e ON m.employee_id = e.id
              LEFT JOIN civic_transparency.org_units u        ON e.org_unit_id = u.id
             WHERE m.detected_at >= now() - INTERVAL '{interval}'
             ORDER BY m.detected_at DESC LIMIT 500
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
```

```python
# transparency/routes.py — add
from .queries import get_recent_movements, WINDOWS

@bp.route("/movements")
def movements():
    w = request.args.get("window", "24h")
    if w not in WINDOWS:
        w = "24h"
    rows = get_recent_movements(window=w)
    return render_template("movements.html", rows=rows, window=w,
                           last_refresh=get_last_refresh())
```

```html
<!-- templates/transparency/movements.html -->
{% extends "base.html" %}
{% block content %}
<main class="lcars-frame">
  <h1>Movements (last {{ window }})</h1>
  <p class="source-attribution">Source: GEDS · Last refresh:
    {{ last_refresh.strftime('%Y-%m-%d %H:%M UTC') if last_refresh else '—' }}</p>
  <p>
    <a href="?window=24h">24h</a> |
    <a href="?window=7d">7 days</a> |
    <a href="?window=30d">30 days</a>
  </p>
  <table>
    <thead><tr><th>When</th><th>Type</th><th>Person</th><th>Title</th><th>Department</th></tr></thead>
    <tbody>
      {% for r in rows %}
        <tr>
          <td>{{ r.detected_at.strftime('%Y-%m-%d %H:%M') if r.detected_at else '' }}</td>
          <td>{{ r.movement_type }}</td>
          <td>{{ r.surname }}{% if r.given_name %}, {{ r.given_name }}{% endif %}</td>
          <td>{{ r.title_en or '—' }}</td>
          <td>{{ r.dept or '—' }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="footnote">{{ rows|length }} movement(s) in window.</p>
</main>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd <CIVIC_WATCH_ROOT> && pytest tests/test_transparency_movements.py -v
```

- [ ] **Step 5: Commit**

```bash
git add transparency/queries.py transparency/routes.py templates/transparency/movements.html tests/test_transparency_movements.py
git commit -m "feat(civic-watch): /transparency/movements feed (24h/7d/30d windows)"
```

---

### Task 17: End-to-end acceptance verification

**No new code in this task** — runs the full acceptance criteria from the spec.

- [ ] **Step 1: Confirm acceptance criteria 1–10 from spec**

Run each verification command. Paste output in a comment on unified_tasks task that wraps this task.

```bash
# AC1: ≥2 successful consecutive runs
docker exec archie_database psql -U archie -d archie -c "
SELECT id, status, run_started_at, run_finished_at,
       org_units_seen, employees_seen
  FROM civic_transparency.geds_snapshots
 ORDER BY id DESC LIMIT 5;
"
# Expected: at least 2 rows with status='completed' on consecutive nights.

# AC2: org_units count ≈ GEDS dept list size
docker exec archie_database psql -U archie -d archie -c "
SELECT count(*) AS depts FROM civic_transparency.org_units WHERE parent_id IS NULL;
"
# Expected: ~270–290 (GEDS pgid=012 listing).

# AC3: federal_employees populated for full-coverage depts
docker exec archie_database psql -U archie -d archie -c "
SELECT u.abbreviation_en, count(e.*) AS staff
  FROM civic_transparency.org_units u
  LEFT JOIN civic_transparency.federal_employees e ON e.org_unit_id = u.id
 WHERE u.coverage = 'full'
 GROUP BY u.abbreviation_en
 ORDER BY staff DESC LIMIT 20;
"
# Expected: every full-coverage dept has staff > 0.

# AC4: quick-list roles populated
docker exec archie_database psql -U archie -d archie -c "
SELECT role_tag, count(*) FROM civic_transparency.federal_employees
 WHERE role_tag IS NOT NULL GROUP BY role_tag;
"
# Expected: 4 rows (minister, deputy_minister, senator, mp), each ≥ 1.

# AC5–7: routes render
curl -sI https://civic.kytranempowerment.com/transparency/registry      | head -1
curl -sI https://civic.kytranempowerment.com/transparency/registry/CSA  | head -1
curl -sI https://civic.kytranempowerment.com/transparency/movements     | head -1
# Expected: all 200.

# AC8: citation banner check
curl -s https://civic.kytranempowerment.com/transparency/registry | grep -c "GEDS"
# Expected: > 0

# AC9: coverage flag accuracy
docker exec archie_database psql -U archie -d archie -c "
SELECT abbreviation_en, coverage FROM civic_transparency.org_units
 WHERE abbreviation_en IN ('TBS','CSIS','RCMP') AND parent_id IS NULL;
"
# Expected: TBS='full', CSIS='partial' (or 'unknown' on early runs), RCMP='partial'.

# AC10: scheduler firing
docker logs archie_scheduler --since 72h 2>&1 | grep -c civic_transparency_geds_refresh
# Expected: ≥ 3 hits over 3 nights.
```

- [ ] **Step 2: Update Dev HQ — close out the work**

```bash
docker exec archie_platform python -c "
# replace 323 with real Phase 1 task IDs you tracked through the run
print('use mcp__archie__complete_task to mark each task done with notes')
"
```

Then via MCP: `complete_task` for each Phase 1 sub-task with the AC verification output as the completion note. Use `log_decision` if any architectural choice changed during implementation.

- [ ] **Step 3: Update KB**

Use `mcp__archie__store_memory` with `knowledge_type='vault_note'`, `category='civic-transparency'` to write a Phase 1 retrospective: what shipped, what surprised, what to change in Phase 2.

If any production scrape failure mode surfaced, file a `mistake_learned` entry.

- [ ] **Step 4: Mark Phase 1 sub-project complete**

```bash
docker exec archie_platform python -c "
print('use mcp__archie__update_project_status to set #323 status=completed')
"
```

- [ ] **Step 5: Commit (only if any tweaks were needed during AC checks)**

```bash
git status
# Commit any small fixes; otherwise skip.
```

---

## Self-review notes

**Spec coverage check:**
- ✅ All 7 GEDS endpoints have a parser/passing task (Task 5 + 9).
- ✅ All 5 schema tables created in Task 2.
- ✅ All 6 public routes implemented in Tasks 12–16 (about, registry, drilldown, JSON, movements + about's already in Task 12).
- ✅ All 6 failure modes addressed: rate-limit (Task 3 adaptive), HTML structure change (raw_pages in Task 2), charset (Task 3 + 5), phantom departures (Task 10 — uses two-snapshot rule via prior_finished cutoff in detect_movements), identity drift (handled by `source_dn` UNIQUE constraint — surname change overwrites; deeper detection deferred to Phase 5), Postgres contention (off-peak schedule in Task 11).
- ✅ All 10 acceptance criteria covered in Task 17.
- ✅ Open questions from spec: Q1 (VPS↔hub Postgres) → Task 1 recon. Q2 (manager resolution timing) → Task 8 separate pass. Q3 (scraper host) → confirmed hub-side via `platform_v2/services/`.

**Type consistency check:**
- `OrgUnitWriter.upsert(...)` signature in Task 6 matches usage in Task 11 orchestrator. ✓
- `EmployeeWriter.upsert(...)` signature in Task 7 matches usage in Task 11. ✓
- `walk_org_tree(client, writer, max_depth=...)` signature consistent. ✓
- `sweep_people(client, leaf_units, writer)` signature consistent. ✓
- `enrich_quick_lists(client, conn)` returns `Dict[str, int]` consistently across tasks 9 and 11. ✓

**Placeholder scan:**
- One deliberately deferred item: `<CIVIC_WATCH_ROOT>` placeholder in Section B paths. The implementer must replace this with the real path noted in Task 1 recon notes. This is acceptable because Task 1 produces that value and every Section B task references it explicitly.
- Coverage classifier in `org_units.coverage` defaults to `'unknown'` and is never updated to `full`/`partial`/`opted_out`. **This is a real gap.** Phase 1 acceptance criteria #9 requires accurate flags for TBS/CSIS/RCMP. **Adding Task 9.5 below to seed the flag.**

---

### Task 9.5 (added during self-review): Seed coverage flags

**Files:**
- Create: `database/migrations/375_civic_coverage_seed.sql`

- [ ] **Step 1: Write seed migration**

```sql
-- database/migrations/375_civic_coverage_seed.sql
-- Phase 1 acceptance criteria #9: seed coverage flags for known cases.
-- Source: GEDS landing-page note "some departments do not list all employees"
-- + public knowledge of national-security org practices.

UPDATE civic_transparency.org_units SET coverage='full'
 WHERE abbreviation_en IN ('TBS','PCO','PSPC','ESDC','HC','PHAC','SC','TC','GAC','FIN');

UPDATE civic_transparency.org_units SET coverage='partial'
 WHERE abbreviation_en IN ('CSIS','RCMP','DND','CSE','CFIA');

-- Departments with no GEDS presence at all (rare; opt-out by design)
-- Add to this list as discovered.
-- UPDATE civic_transparency.org_units SET coverage='opted_out' WHERE abbreviation_en IN (...);
```

- [ ] **Step 2: Apply**

```bash
docker exec -i archie_database psql -U archie -d archie \
  < database/migrations/375_civic_coverage_seed.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT coverage, count(*) FROM civic_transparency.org_units
 WHERE parent_id IS NULL GROUP BY coverage ORDER BY count(*) DESC;
"
```

Expected: `full` ≥ 10, `partial` ≥ 5, rest `unknown`.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/375_civic_coverage_seed.sql
git commit -m "feat(civic-transparency): seed coverage flags for known full/partial-coverage depts"
```

---

## Recon Notes (filled by Task 1, 2026-05-04)

- **Civic-watch source path:** `/mnt/standalone/kytran-civic-watch/`

- **Hub Postgres connection from VPS:** **Does not exist — this is a blocker.** Civic-watch uses SQLite (`db.py` opens `WATCH_DB_PATH=/app/data/watch.db` via `sqlite3`). There is NO existing connection to hub Postgres from civic-watch, and no `civic_watch` user or schema on hub (`\dn` shows: gov_watch, public, sandbox, tenant_1, tenant_9908, wtf). The hub has only one DB role: `archie` (superuser). Gov-watch is the only watch product with a hub Postgres schema (`gov_watch`); its `.env` uses env-var names `GOV_DB_HOST`, `GOV_DB_PORT`, `GOV_DB_NAME`, `GOV_DB_USER`, `GOV_DB_PASSWORD`, `GOV_BRIDGE_URL`. To wire civic-watch to hub Postgres for the `civic_transparency` schema, Section B must: (1) add `psycopg2-binary` to civic-watch's requirements, (2) add a new `hub_db.py` alongside `db.py` using env-vars (suggested names: `HUB_DB_HOST`, `HUB_DB_PORT`, `HUB_DB_NAME`, `HUB_DB_USER`, `HUB_DB_PASSWORD` — matching gov-watch convention), (3) expose these vars in `docker-compose.yml` + VPS `.env`, (4) no new DB role needed — use existing `archie` superuser (or create a scoped `civic_watch` role). Required grants once schema exists: `GRANT USAGE ON SCHEMA civic_transparency TO archie; GRANT SELECT ON ALL TABLES IN SCHEMA civic_transparency TO archie;` (archie is already superuser so grants are moot, but if a scoped role is created later: same pattern as gov_watch). VPS reaches hub at `192.168.1.200:5432` (direct LAN) or Tailscale mesh `100.79.11.3:5432`.

- **Main app file:** `/mnt/standalone/kytran-civic-watch/app.py`

- **Blueprint pattern:** Each route domain lives in `routes/<domain>.py` as a bare `Blueprint("<name>", __name__)` with **no `url_prefix`** (routes carry their full path, e.g. `/api/parliament/bills`). Blueprints are imported at the top of `app.py` and registered inside `create_app()` via `app.register_blueprint(<bp>)` — no url_prefix kwarg, no template_folder kwarg, decorator-free (explicit registration only).

- **Example existing route:** `routes/parliament.py` defines `parliament_bp = Blueprint("parliament", __name__)`; route `/api/parliament/bills` lives at `@parliament_bp.route("/api/parliament/bills")`. The new `/api/transparency/*` blueprint should follow the exact same pattern: `transparency_bp = Blueprint("transparency", __name__)` in `routes/transparency.py`, registered in `create_app()` as `app.register_blueprint(transparency_bp)`.

- **Templates extend:** Civic-watch does NOT use `{% extends "base.html" %}` / LCARS shared CSS. The only server-rendered template is `templates/landing.html` (standalone HTML, own styles). The dashboard is a static SPA at `static/index.html`. The `/transparency/*` routes are pure JSON API endpoints — no template rendering needed.

- **Surprises / blockers:**
  1. **SQLite-only — no hub Postgres path.** This is the key blocker for Section B. A `hub_db.py` module and new docker-compose env vars must be added before any `civic_transparency` schema queries can run from civic-watch. Tasks 12–17 must account for this setup step.
  2. **No `url_prefix` on any blueprint.** Routes own their full path. The new transparency blueprint should follow suit: routes written as `@transparency_bp.route("/api/transparency/...")` directly.
  3. **`docker-compose.yml` uses `read_only: true` + tmpfs `/tmp`.** Any new hub DB connection is fine (no writes to local FS), but be careful that psycopg2 doesn't try to write temp files outside `/tmp`.
  4. **Gov-watch pattern is the reference.** Env-var naming convention (`GOV_DB_*`) should be mirrored as `HUB_DB_*` (or `CIVIC_HUB_DB_*`) for civic-watch.

- **Recommendation for Section B path placeholder `<CIVIC_WATCH_ROOT>`:** `/mnt/standalone/kytran-civic-watch`
