# OmniRoute Quota Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make throttling on OmniRoute-fronted providers (currently `opencode-zen`) visible via a Telegram alert and a DHQ dashboard card, by reading OmniRoute's own `call_logs` and classifying each call's `error_type`.

**Architecture:** A new service module reads `call_logs` (same read-only sqlite mount `omniroute_telemetry.py` already uses) on a 15-minute schedule, excludes a known keep-alive row shape, computes a throttle rate per upstream provider, and writes one snapshot row per provider per scan to a new table. A status-read function exposes the latest snapshot in a shape mirroring `weekly_budget_status()` (routing-hint-ready, unconsumed this phase). Alerting compares consecutive snapshots and fires via the platform's own `telegram_service` on a confirmed transition into "exhausted."

**Tech Stack:** Python 3, `sqlite3` (stdlib), psycopg2 via `database.get_db_cursor`, APScheduler (already wired in `ai_bridge/agent_loop.py`), Flask/Jinja2 for the dashboard card, vanilla JS (matches `department-hq.js`'s existing style — no framework).

**Spec:** `docs/superpowers/specs/2026-09-19-omniroute-quota-awareness-design.md`

## Global Constraints

- No dispatch/routing behavior change — `get_quota_status()` is built and exposed, nothing calls it to change routing in this phase.
- No unification with the groq/cerebras/cohere/qwen3_cloud budget system — separate systems, matching return shapes only.
- No Contractors tab rename.
- Reuse the exact read-only mount `omniroute_telemetry.py` already has (`OMNIROUTE_DB_PATH` env var, default `/omniroute-data/storage.sqlite`) — no new mount, no new credential.
- Alerting uses the platform's own `services/telegram_service.send_system(title, message)` — NOT Phase 1's independent Citadel/SSH path (spec §6: this is a hub-local computation with no off-hub-redundancy need).
- The digest-fold-in idea from the spec's original §5/§7 step 4 wording is DROPPED per an owner decision made during planning (`kin_welfare_digest` is severity-gated and stays silent on healthy days — folding in would make quota visibility depend on unrelated welfare state). This plan implements Telegram alert + dashboard card only.
- Branch + PR, never main. 2 failures → STOP and ask.

---

### Task 1: `omniroute_quota_snapshots` table

**Files:**
- Create: `database/migrations/484_omniroute_quota_snapshots.sql`

**Interfaces:**
- Produces: table `omniroute_quota_snapshots(id, provider, window_hours, total_calls, throttled_calls, rate, status, created_at)` — every later task reads/writes this table under these exact column names.

- [ ] **Step 1: Write the migration**

```sql
-- 484_omniroute_quota_snapshots.sql
-- OmniRoute Quota Awareness (Deep Space Nine phase 2). One row per upstream
-- provider per scan (every 15 min, see omniroute_quota_service.py), so the
-- dashboard card and alert logic have a real trend, not just a point-in-time
-- read. Idempotent.
CREATE TABLE IF NOT EXISTS omniroute_quota_snapshots (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(100) NOT NULL,
    window_hours INTEGER NOT NULL,
    total_calls INTEGER NOT NULL,
    throttled_calls INTEGER NOT NULL,
    rate NUMERIC(6,4),
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_omniroute_quota_provider_created
    ON omniroute_quota_snapshots(provider, created_at DESC);
```

- [ ] **Step 2: Apply it and verify**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/484_omniroute_quota_snapshots.sql`
Expected: `CREATE TABLE` then `CREATE INDEX`, no errors. Then:
Run: `docker exec archie_database psql -U archie -d archie -c "\d omniroute_quota_snapshots"`
Expected: shows all 8 columns and the index.

- [ ] **Step 3: Commit**

```bash
git add database/migrations/484_omniroute_quota_snapshots.sql
git commit -m "feat(db): add omniroute_quota_snapshots table (DS9 phase 2, task 1)"
```

---

### Task 2: `scan_quota_status()` — read, exclude, aggregate, write

**Files:**
- Create: `platform_v2/services/omniroute_quota_service.py`
- Test: `platform_v2/tests/test_omniroute_quota_service.py`

**Interfaces:**
- Consumes: `omniroute_quota_snapshots` table (Task 1). `database.get_db_cursor` (existing platform helper — `with get_db_cursor(commit=True) as (conn, cur): ...`).
- Produces: `scan_quota_status(window_hours: int | None = None) -> dict` returning `{"ok": bool, "providers": list[dict], "error": str | None}`, where each provider dict is `{"provider": str, "window_hours": int, "total": int, "throttled": int, "rate": float | None, "status": str}`. Later tasks (3, 4, 5) call this function and rely on this exact return shape.
- Produces: `_is_keepalive_row(row) -> bool` and `_status_for_rate(rate: float | None) -> str` — Task 3 reuses `_status_for_rate`.

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_omniroute_quota_service.py
import os
import sqlite3
import tempfile

import pytest


CALL_LOGS_SCHEMA = """
CREATE TABLE call_logs (
    id TEXT, timestamp TEXT, status INTEGER, provider TEXT,
    requested_model TEXT, tokens_in INTEGER, tokens_out INTEGER,
    error_type TEXT
);
"""


@pytest.fixture
def sqlite_path(tmp_path, monkeypatch):
    path = tmp_path / "storage.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(CALL_LOGS_SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setenv("OMNIROUTE_DB_PATH", str(path))
    return str(path)


def _insert(path, rows):
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO call_logs (id, timestamp, status, provider, requested_model, "
        "tokens_in, tokens_out, error_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_keepalive_row_excluded(sqlite_path):
    from services.omniroute_quota_service import _is_keepalive_row
    import sqlite3

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    _insert(sqlite_path, [("1", "2026-09-19T00:00:00Z", 200, "opencode-zen", None, 0, 0, None)])
    row = conn.execute("SELECT * FROM call_logs WHERE id='1'").fetchone()
    assert _is_keepalive_row(row) is True
    conn.close()


def test_real_refusal_not_excluded(sqlite_path):
    from services.omniroute_quota_service import _is_keepalive_row
    import sqlite3

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    _insert(
        sqlite_path,
        [("1", "2026-09-19T00:00:00Z", 429, "opencode-zen", "opencode/big-pickle", 0, 0, "rate_limited")],
    )
    row = conn.execute("SELECT * FROM call_logs WHERE id='1'").fetchone()
    assert _is_keepalive_row(row) is False


def test_status_bands():
    from services.omniroute_quota_service import _status_for_rate

    assert _status_for_rate(None) == "unknown"
    assert _status_for_rate(0.0) == "ok"
    assert _status_for_rate(0.29) == "ok"
    assert _status_for_rate(0.30) == "degraded"
    assert _status_for_rate(0.69) == "degraded"
    assert _status_for_rate(0.70) == "exhausted"
    assert _status_for_rate(1.0) == "exhausted"


def test_scan_quota_status_computes_rate_and_writes_snapshot(sqlite_path, monkeypatch):
    from services import omniroute_quota_service as svc

    now = "2026-09-19T12:00:00Z"
    _insert(
        sqlite_path,
        [
            # keep-alive, excluded
            ("k1", now, 200, "opencode-zen", None, 0, 0, None),
            # 3 real calls: 2 throttled, 1 ok
            ("r1", now, 429, "opencode-zen", "opencode/big-pickle", 0, 0, "rate_limited"),
            ("r2", now, 200, "opencode-zen", "opencode/big-pickle", 12, 40, None),
            ("r3", now, 503, "opencode-zen", "opencode/big-pickle", 0, 0, "quota_exhausted"),
        ],
    )

    written = []

    class FakeCursor:
        def execute(self, sql, params=None):
            written.append((sql.strip().split()[0], params))

        def fetchone(self):
            return None

    class FakeConn:
        def __enter__(self):
            return self, FakeCursor()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(svc, "get_db_cursor", lambda commit=True: FakeConn())
    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: default)
    monkeypatch.setattr(svc, "_get_setting_float", lambda key, default: default)

    result = svc.scan_quota_status(window_hours=24)

    assert result["ok"] is True
    assert len(result["providers"]) == 1
    p = result["providers"][0]
    assert p["provider"] == "opencode-zen"
    assert p["total"] == 3  # keep-alive excluded
    assert p["throttled"] == 2
    assert p["rate"] == pytest.approx(2 / 3)
    assert p["status"] == "degraded"  # 0.667 >= 0.30 default... actually check band
    assert any(w[0] == "INSERT" for w in written)


def test_scan_quota_status_missing_db_fails_open(monkeypatch, tmp_path):
    from services import omniroute_quota_service as svc

    monkeypatch.setenv("OMNIROUTE_DB_PATH", str(tmp_path / "does-not-exist.sqlite"))
    result = svc.scan_quota_status(window_hours=24)
    assert result["ok"] is False
    assert result["providers"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_omniroute_quota_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.omniroute_quota_service'`

- [ ] **Step 3: Write the implementation**

```python
# platform_v2/services/omniroute_quota_service.py
"""Compute OmniRoute throttle-rate status per upstream provider.

Deep Space Nine phase 2 (quota awareness). Reads call_logs directly -- NOT
task_execution_log -- because omniroute_telemetry.py's collector deliberately
drops every row where tokens_in==0 and tokens_out==0 ("a refused call is not
inference"), and a quota-exhausted or rate-limited call is exactly that shape.
See docs/superpowers/specs/2026-09-19-omniroute-quota-awareness-design.md §3.

Writes one snapshot row per provider per scan to omniroute_quota_snapshots so
the dashboard card and alert logic (Tasks 4-5) have a real trend, not just a
point-in-time read.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

OMNIROUTE_DB = os.getenv("OMNIROUTE_DB_PATH", "/omniroute-data/storage.sqlite")
THROTTLE_ERROR_TYPES = ("quota_exhausted", "rate_limited")


def _is_keepalive_row(row) -> bool:
    """A recurring OmniRoute-internal keep-alive/model-refresh ping, not a real
    call of ours -- observed hourly on opencode-zen with this exact shape.
    Excluded by exact match, not by a blanket "0 tokens = refused" rule: a
    genuine throttle IS a 0-token row, so the exclusion must be narrow."""
    return (
        row["status"] == 200
        and (row["tokens_in"] or 0) == 0
        and (row["tokens_out"] or 0) == 0
        and row["error_type"] is None
        and row["requested_model"] is None
    )


def _get_setting_int(key: str, default: int) -> int:
    """Read an int tunable from platform_settings (no-deploy retunable)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row["value"] not in (None, ""):
            return int(row["value"])
    except Exception:
        logger.warning("omniroute_quota: bad/missing int setting %s, using default %s", key, default)
    return default


def _get_setting_float(key: str, default: float) -> float:
    """Read a float tunable from platform_settings (no-deploy retunable)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row["value"] not in (None, ""):
            return float(row["value"])
    except Exception:
        logger.warning("omniroute_quota: bad/missing float setting %s, using default %s", key, default)
    return default


def _status_for_rate(rate: Optional[float]) -> str:
    """rate is None (no calls in window) -> 'unknown': an idle provider isn't a
    healthy one, it's just unmeasured (spec §8)."""
    if rate is None:
        return "unknown"
    degraded_at = _get_setting_float("omniroute_quota:degraded_threshold", 0.30)
    exhausted_at = _get_setting_float("omniroute_quota:exhausted_threshold", 0.70)
    if rate >= exhausted_at:
        return "exhausted"
    if rate >= degraded_at:
        return "degraded"
    return "ok"


def scan_quota_status(window_hours: Optional[int] = None) -> Dict[str, Any]:
    """Read call_logs for the window, exclude keep-alive rows, group by
    provider, write one snapshot row per provider. Fail-open: any error
    leaves prior snapshots standing and writes nothing new (a counting bug
    must never manufacture a false alert)."""
    window_hours = window_hours if window_hours is not None else _get_setting_int(
        "omniroute_quota:window_hours", 24
    )

    if not os.path.exists(OMNIROUTE_DB):
        logger.warning("omniroute_quota: call_logs not found at %s", OMNIROUTE_DB)
        return {"ok": False, "error": "call_logs unreachable", "providers": []}

    try:
        conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT provider, status, tokens_in, tokens_out, error_type, requested_model "
            "FROM call_logs WHERE timestamp >= datetime('now', ?)",
            (f"-{window_hours} hours",),
        )
        rows = cur.fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        # Schema drift (renamed/missing column) fails loud, writes nothing --
        # same precedent as omniroute_telemetry.py.
        logger.error("omniroute_quota: call_logs schema mismatch: %s", e)
        return {"ok": False, "error": str(e), "providers": []}
    except Exception as e:
        logger.error("omniroute_quota: scan failed: %s", e)
        return {"ok": False, "error": str(e), "providers": []}

    per_provider: Dict[str, Dict[str, int]] = {}
    for row in rows:
        if _is_keepalive_row(row):
            continue
        provider = row["provider"] or "unknown"
        bucket = per_provider.setdefault(provider, {"total": 0, "throttled": 0})
        bucket["total"] += 1
        if row["error_type"] in THROTTLE_ERROR_TYPES:
            bucket["throttled"] += 1

    results: List[Dict[str, Any]] = []
    with get_db_cursor(commit=True) as (conn, cur):
        for provider, counts in per_provider.items():
            rate = counts["throttled"] / counts["total"] if counts["total"] else None
            status = _status_for_rate(rate)
            cur.execute(
                """INSERT INTO omniroute_quota_snapshots
                   (provider, window_hours, total_calls, throttled_calls, rate, status)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (provider, window_hours, counts["total"], counts["throttled"], rate, status),
            )
            results.append(
                {
                    "provider": provider,
                    "window_hours": window_hours,
                    "total": counts["total"],
                    "throttled": counts["throttled"],
                    "rate": rate,
                    "status": status,
                }
            )

    return {"ok": True, "providers": results, "error": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_omniroute_quota_service.py -v`
Expected: PASS (5 tests). If `test_scan_quota_status_computes_rate_and_writes_snapshot`'s status assertion fails, compute 2/3 = 0.667 against the default bands (degraded_at=0.30, exhausted_at=0.70) — 0.667 is `>= 0.30` and `< 0.70`, so the correct expected status is `"degraded"`, not `"exhausted"`. Fix the assertion in the test to `assert p["status"] == "degraded"` and rerun.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/omniroute_quota_service.py platform_v2/tests/test_omniroute_quota_service.py
git commit -m "feat(omniroute-quota): scan_quota_status() reads call_logs, excludes keep-alive rows (DS9 phase 2, task 2)"
```

---

### Task 3: `get_quota_status()` — the routing-hint read interface

**Files:**
- Modify: `platform_v2/services/omniroute_quota_service.py`
- Test: `platform_v2/tests/test_omniroute_quota_service.py`

**Interfaces:**
- Consumes: `omniroute_quota_snapshots` table (Task 1), `_status_for_rate` (Task 2, for band-boundary consistency in tests only).
- Produces: `get_quota_status(provider: str | None = None) -> dict | list[dict]` — single-provider dict when `provider` given, else a list of one dict per known provider (latest snapshot only). Shape: `{"provider": str, "window_hours": int | None, "total": int, "throttled": int, "rate": float | None, "status": str, "last_scan_at": str | None}`. Tasks 4 and 5 call this with and without `provider`.

- [ ] **Step 1: Write the failing tests**

```python
# append to platform_v2/tests/test_omniroute_quota_service.py

def test_get_quota_status_unknown_provider_returns_unknown(monkeypatch):
    from services import omniroute_quota_service as svc

    class FakeCursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return None

    class FakeConn:
        def __enter__(self):
            return self, FakeCursor()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(svc, "get_db_cursor", lambda commit=False: FakeConn())
    result = svc.get_quota_status(provider="nonexistent")
    assert result["status"] == "unknown"
    assert result["total"] == 0


def test_get_quota_status_shapes_a_real_row(monkeypatch):
    from services import omniroute_quota_service as svc
    from datetime import datetime, timezone

    fake_row = {
        "provider": "opencode-zen",
        "window_hours": 24,
        "total_calls": 10,
        "throttled_calls": 4,
        "rate": 0.4,
        "status": "degraded",
        "created_at": datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
    }

    class FakeCursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return fake_row

    class FakeConn:
        def __enter__(self):
            return self, FakeCursor()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(svc, "get_db_cursor", lambda commit=False: FakeConn())
    result = svc.get_quota_status(provider="opencode-zen")
    assert result["provider"] == "opencode-zen"
    assert result["rate"] == 0.4
    assert result["status"] == "degraded"
    assert result["last_scan_at"] == "2026-09-19T12:00:00+00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_omniroute_quota_service.py -v -k get_quota_status`
Expected: FAIL — `AttributeError: module 'services.omniroute_quota_service' has no attribute 'get_quota_status'`

- [ ] **Step 3: Write the implementation**

Append to `platform_v2/services/omniroute_quota_service.py`:

```python
def get_quota_status(provider: Optional[str] = None) -> Any:
    """Read the LATEST snapshot per provider. Returns a dict for one provider
    or a list of dicts for all known providers.

    This is the routing-hint interface for a future phase: shaped to mirror
    ai_bridge/external_providers.py's weekly_budget_status() so a future
    dispatch/combo-selection guard could consume it with no data-layer
    changes. Nothing calls it for that purpose in this phase."""
    if provider:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT provider, window_hours, total_calls, throttled_calls,
                          rate, status, created_at
                   FROM omniroute_quota_snapshots
                   WHERE provider = %s ORDER BY created_at DESC LIMIT 1""",
                (provider,),
            )
            row = cur.fetchone()
        if not row:
            return {
                "provider": provider,
                "window_hours": None,
                "total": 0,
                "throttled": 0,
                "rate": None,
                "status": "unknown",
                "last_scan_at": None,
            }
        return _row_to_status(row)

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT DISTINCT ON (provider) provider, window_hours, total_calls,
                      throttled_calls, rate, status, created_at
               FROM omniroute_quota_snapshots
               ORDER BY provider, created_at DESC"""
        )
        rows = cur.fetchall()
    return [_row_to_status(r) for r in rows]


def _row_to_status(row) -> Dict[str, Any]:
    created_at = row["created_at"]
    return {
        "provider": row["provider"],
        "window_hours": row["window_hours"],
        "total": row["total_calls"],
        "throttled": row["throttled_calls"],
        "rate": float(row["rate"]) if row["rate"] is not None else None,
        "status": row["status"],
        "last_scan_at": created_at.isoformat() if created_at else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_omniroute_quota_service.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/omniroute_quota_service.py platform_v2/tests/test_omniroute_quota_service.py
git commit -m "feat(omniroute-quota): get_quota_status() routing-hint read interface (DS9 phase 2, task 3)"
```

---

### Task 4: Schedule the scan job (log-only, no alert yet) + live verification

**Files:**
- Modify: `platform_v2/tools/department_hq/jobs.py` (both the job function AND its scheduler registration — `omniroute_telemetry`'s own `scheduler.add_job(...)` call lives inside `register_department_hq_jobs()` in this same file, around line 2020; this task's registration is a sibling entry in that same function, not a separate file)

**Interfaces:**
- Consumes: `scan_quota_status()` (Task 2).
- Produces: job id `"omniroute_quota_scan"`, function `omniroute_quota_scan_job()` in `jobs.py` — Task 5 extends this same function to add alerting.

- [ ] **Step 1: Add the job function**

Add to `platform_v2/tools/department_hq/jobs.py`, near `omniroute_telemetry_collect` (around line 1111):

```python
def omniroute_quota_scan_job():
    """Deep Space Nine phase 2: compute OmniRoute throttle rate per upstream
    provider, every 15 min. Pure read (call_logs, read-only mount) + a bounded
    insert (omniroute_quota_snapshots) -- no LLM, no dispatch, nothing on the
    inference path.
    """
    try:
        from services.omniroute_quota_service import scan_quota_status

        result = scan_quota_status()
        if result.get("ok"):
            for p in result["providers"]:
                logger.info(
                    "omniroute_quota: %s status=%s rate=%s (%s/%s)",
                    p["provider"], p["status"],
                    f"{p['rate']:.0%}" if p["rate"] is not None else "n/a",
                    p["throttled"], p["total"],
                )
        else:
            logger.warning("omniroute_quota: scan failed: %s", result.get("error"))
    except Exception:
        logger.exception("omniroute_quota_scan_job failed")
```

- [ ] **Step 2: Register the job**

Inside `register_department_hq_jobs(scheduler, flask_app)` in `platform_v2/tools/department_hq/jobs.py` (this is the SAME function that registers `omniroute_telemetry`, around line 2020 — no import needed since `omniroute_quota_scan_job` is defined earlier in this same file), add a sibling `scheduler.add_job(...)` call right after the existing `omniroute_telemetry` registration block:

```python
    # OmniRoute quota awareness (Deep Space Nine phase 2) — every 15 min.
    # Reads call_logs directly (NOT task_execution_log — see
    # platform_v2/services/omniroute_quota_service.py's module docstring for
    # why) and writes a throttle-rate snapshot per upstream provider.
    scheduler.add_job(
        with_ctx(omniroute_quota_scan_job),
        trigger=CronTrigger(minute="*/15", timezone="America/Toronto"),
        id="omniroute_quota_scan",
        name="DHQ: OmniRoute Quota Scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 3: Restart and verify live**

Run: `docker restart archie_platform`
Wait ~30s, then run: `docker logs archie_platform --since 2m | grep omniroute_quota`
Expected: no errors on startup (the job registers cleanly). It won't fire for up to 15 min on the cron schedule — trigger it once by hand to confirm real output:

Run:
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.omniroute_quota_service import scan_quota_status
import json
print(json.dumps(scan_quota_status(), indent=2, default=str))
"
```
Expected: `"ok": true`, at least one provider (`opencode-zen`) with a `status` and `rate` field. Sanity-check the rate roughly matches the live measurement taken during design (spec §1: ~59% over the last 500 calls) — it won't match exactly (different window: 24h vs a fixed 500-row sample) but should be in a broadly similar high range given the ongoing throttling.

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT * FROM omniroute_quota_snapshots ORDER BY created_at DESC LIMIT 5;"`
Expected: the manual run's insert(s) visible.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/jobs.py
git commit -m "feat(omniroute-quota): schedule 15-min scan job, log-only (DS9 phase 2, task 4)"
```

---

### Task 5: Telegram alerting on confirmed throttle transitions

**Files:**
- Modify: `platform_v2/services/omniroute_quota_service.py`
- Modify: `platform_v2/tools/department_hq/jobs.py`
- Test: `platform_v2/tests/test_omniroute_quota_service.py`

**Interfaces:**
- Consumes: `omniroute_quota_snapshots` table (written by Task 2's `scan_quota_status`), `services.telegram_service.send_system(title: str, message: str = "", **kwargs) -> dict` (existing platform function, confirmed signature).
- Produces: `check_and_alert() -> None` in `omniroute_quota_service.py`, called from `omniroute_quota_scan_job()` right after `scan_quota_status()`.

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_omniroute_quota_service.py`:

```python
def test_check_and_alert_fires_on_confirmed_exhaustion(monkeypatch):
    from services import omniroute_quota_service as svc

    # Two most-recent scans: both "exhausted" (K=2 confirmed). The scan
    # BEFORE those two was NOT exhausted -- this is a genuine transition.
    snapshot_rows = {
        ("provider",): [{"provider": "opencode-zen"}],
    }
    recent_rows = [{"status": "exhausted", "rate": 0.85}, {"status": "exhausted", "rate": 0.80}]
    prior_row = {"status": "degraded"}

    calls = {"select_kind": []}

    class FakeCursor:
        def execute(self, sql, params=None):
            if "DISTINCT provider" in sql:
                calls["select_kind"].append("providers")
            elif "OFFSET" in sql:
                calls["select_kind"].append("prior")
            else:
                calls["select_kind"].append("recent")

        def fetchall(self):
            return [{"provider": "opencode-zen"}]

        def fetchone(self):
            kind = calls["select_kind"][-1]
            return prior_row if kind == "prior" else None

    class FakeConn:
        def __enter__(self):
            return self, FakeCursor()

        def __exit__(self, *a):
            return False

    # Simplify: patch the two query helpers directly instead of the raw cursor,
    # since the exact SQL shape is an implementation detail.
    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: 2)
    monkeypatch.setattr(svc, "_recent_snapshots", lambda provider, limit: recent_rows)
    monkeypatch.setattr(svc, "_snapshot_before", lambda provider, offset: prior_row)
    monkeypatch.setattr(svc, "_all_providers_with_snapshots", lambda: ["opencode-zen"])

    sent = []
    monkeypatch.setattr(
        "services.telegram_service.send_system",
        lambda title, message="", **kw: sent.append((title, message)) or {"ok": True},
    )

    svc.check_and_alert()

    assert len(sent) == 1
    assert "exhausted" in sent[0][0].lower()
    assert "opencode-zen" in sent[0][0]


def test_check_and_alert_silent_when_not_confirmed(monkeypatch):
    from services import omniroute_quota_service as svc

    # Only 1 of 2 required confirmations is "exhausted" -- must NOT alert.
    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: 2)
    monkeypatch.setattr(
        svc, "_recent_snapshots", lambda provider, limit: [{"status": "exhausted", "rate": 0.8}, {"status": "ok", "rate": 0.1}]
    )
    monkeypatch.setattr(svc, "_snapshot_before", lambda provider, offset: {"status": "ok"})
    monkeypatch.setattr(svc, "_all_providers_with_snapshots", lambda: ["opencode-zen"])

    sent = []
    monkeypatch.setattr(
        "services.telegram_service.send_system",
        lambda title, message="", **kw: sent.append((title, message)) or {"ok": True},
    )

    svc.check_and_alert()

    assert sent == []


def test_check_and_alert_fires_recovery_once(monkeypatch):
    from services import omniroute_quota_service as svc

    # Was exhausted before, now confirmed NOT exhausted -> one recovery alert.
    monkeypatch.setattr(svc, "_get_setting_int", lambda key, default: 2)
    monkeypatch.setattr(
        svc, "_recent_snapshots", lambda provider, limit: [{"status": "ok", "rate": 0.1}, {"status": "degraded", "rate": 0.35}]
    )
    monkeypatch.setattr(svc, "_snapshot_before", lambda provider, offset: {"status": "exhausted"})
    monkeypatch.setattr(svc, "_all_providers_with_snapshots", lambda: ["opencode-zen"])

    sent = []
    monkeypatch.setattr(
        "services.telegram_service.send_system",
        lambda title, message="", **kw: sent.append((title, message)) or {"ok": True},
    )

    svc.check_and_alert()

    assert len(sent) == 1
    assert "recovered" in sent[0][0].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_omniroute_quota_service.py -v -k check_and_alert`
Expected: FAIL — `AttributeError: module 'services.omniroute_quota_service' has no attribute 'check_and_alert'`

- [ ] **Step 3: Write the implementation**

Append to `platform_v2/services/omniroute_quota_service.py`:

```python
def _all_providers_with_snapshots() -> List[str]:
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT DISTINCT provider FROM omniroute_quota_snapshots")
        return [r["provider"] for r in cur.fetchall()]


def _recent_snapshots(provider: str, limit: int) -> List[Dict[str, Any]]:
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT status, rate FROM omniroute_quota_snapshots
               WHERE provider = %s ORDER BY created_at DESC LIMIT %s""",
            (provider, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def _snapshot_before(provider: str, offset: int) -> Optional[Dict[str, Any]]:
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT status FROM omniroute_quota_snapshots
               WHERE provider = %s ORDER BY created_at DESC LIMIT 1 OFFSET %s""",
            (provider, offset),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def check_and_alert() -> None:
    """Compare each provider's most recent K snapshots to what came before;
    alert on a CONFIRMED (K consecutive) transition into 'exhausted', and once
    on recovery out of it. Uses the platform's own telegram_service, not Phase
    1's independent Citadel path -- this is a hub-local computation with no
    off-hub-redundancy need (spec §6). One alert per transition, never spammed
    every cycle."""
    from services.telegram_service import send_system

    confirm_k = _get_setting_int("omniroute_quota:confirm_k", 2)

    for provider in _all_providers_with_snapshots():
        recent = _recent_snapshots(provider, confirm_k)
        if len(recent) < confirm_k:
            continue  # not enough history yet to confirm anything

        prior = _snapshot_before(provider, confirm_k)
        was_exhausted_before = bool(prior and prior["status"] == "exhausted")
        all_exhausted_now = all(r["status"] == "exhausted" for r in recent)

        if all_exhausted_now and not was_exhausted_before:
            rate = recent[0]["rate"]
            send_system(
                title=f"⚠️ OmniRoute quota: {provider} exhausted",
                message=(
                    f"{provider} has been throttled "
                    f"({rate:.0%} of calls) for {confirm_k} consecutive scans."
                ),
            )
        elif was_exhausted_before and not all_exhausted_now and recent[0]["status"] != "exhausted":
            send_system(
                title=f"✅ OmniRoute quota: {provider} recovered",
                message=f"{provider} is no longer throttled (current: {recent[0]['status']}).",
            )
```

Then modify `omniroute_quota_scan_job()` in `jobs.py` (Task 4) to call it:

```python
def omniroute_quota_scan_job():
    """Deep Space Nine phase 2: compute OmniRoute throttle rate per upstream
    provider, every 15 min, and alert on a confirmed transition into
    'exhausted'. Pure read (call_logs, read-only mount) + a bounded insert
    (omniroute_quota_snapshots) -- no LLM, no dispatch, nothing on the
    inference path.
    """
    try:
        from services.omniroute_quota_service import check_and_alert, scan_quota_status

        result = scan_quota_status()
        if result.get("ok"):
            for p in result["providers"]:
                logger.info(
                    "omniroute_quota: %s status=%s rate=%s (%s/%s)",
                    p["provider"], p["status"],
                    f"{p['rate']:.0%}" if p["rate"] is not None else "n/a",
                    p["throttled"], p["total"],
                )
            check_and_alert()
        else:
            logger.warning("omniroute_quota: scan failed: %s", result.get("error"))
    except Exception:
        logger.exception("omniroute_quota_scan_job failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_omniroute_quota_service.py -v`
Expected: PASS (10 tests total).

- [ ] **Step 5: Restart and verify live (does NOT require actually waiting for a real exhaustion transition)**

Run: `docker restart archie_platform`
Run: `docker logs archie_platform --since 1m | grep -i error`
Expected: clean restart, no import errors.

Given `opencode-zen` is measurably already throttled (spec §1), the FIRST two real scans after this deploy are likely to both land on `"exhausted"` or `"degraded"` — check whether a real alert fires within ~30 minutes:

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT provider, status, rate, created_at FROM omniroute_quota_snapshots ORDER BY created_at DESC LIMIT 10;"`

If two consecutive real rows show `status='exhausted'`, confirm a Telegram message actually arrived (this is the real drill the spec's §9 step 5 asks for — using the already-throttled provider as the live test case, mirroring how Phase 1 used its own already-broken credential as its drill).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/omniroute_quota_service.py platform_v2/tools/department_hq/jobs.py platform_v2/tests/test_omniroute_quota_service.py
git commit -m "feat(omniroute-quota): Telegram alert on confirmed throttle transitions (DS9 phase 2, task 5)"
```

---

### Task 6: DHQ Contractors tab dashboard card

**Files:**
- Modify: `platform_v2/tools/department_hq/contractor_routes.py`
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

**Interfaces:**
- Consumes: `get_quota_status()` (Task 3), the existing `register_contractor_routes(bp, admin_required)` pattern, the existing `tabLoaders` map and `loadContractors()` function in `department-hq.js`.
- Produces: `GET /api/contractors/omniroute-quota` (JSON), div `#omniroute-quota-status` in the Contractors panel, JS function `loadOmniRouteQuota()`.

- [ ] **Step 1: Add the backend route**

Add to `platform_v2/tools/department_hq/contractor_routes.py`, inside `register_contractor_routes`:

```python
    @bp.route("/api/contractors/omniroute-quota", methods=["GET"])
    @login_required
    def get_omniroute_quota():
        """Deep Space Nine phase 2: current throttle-rate status per OmniRoute
        upstream provider, for the Contractors tab card."""
        try:
            from services.omniroute_quota_service import get_quota_status

            providers = get_quota_status()
            return jsonify({"success": True, "providers": providers})
        except Exception as e:
            logger.error("get_omniroute_quota failed: %s", e)
            return jsonify({"success": False, "error": "quota status unavailable", "providers": []}), 502
```

- [ ] **Step 2: Add the template markup**

In `platform_v2/tools/department_hq/templates/department_hq.html`, add right after the opening of `<div class="dhq-panel" id="panel-contractors">` (before the existing `contractors-summary` div, so it reads first):

```html
      <div class="dhq-card">
        <h3>OmniRoute Quota (Deep Space Nine)</h3>
        <p style="font-size:0.85rem;color:var(--dhq-text-dim);">Throttle rate per upstream provider, last 24h. Visibility only — does not change routing.</p>
        <div id="omniroute-quota-status">Loading…</div>
      </div>
```

- [ ] **Step 3: Add the JS loader**

Add to `platform_v2/tools/department_hq/static/js/department-hq.js`, near `loadContractors()`:

```javascript
function omniRouteQuotaColor(status) {
  if (status === 'ok') return '#10b981';
  if (status === 'degraded') return '#f59e0b';
  if (status === 'exhausted') return '#ef4444';
  return '#6b7280'; /* unknown */
}

function renderOmniRouteQuota(providers) {
  var box = document.getElementById('omniroute-quota-status');
  if (!box) return;
  if (!providers.length) {
    box.textContent = 'No data yet — first scan runs within 15 minutes of deploy.';
    return;
  }
  var html = '';
  providers.forEach(function (p) {
    var pct = p.rate != null ? Math.round(p.rate * 100) + '%' : 'n/a';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--dhq-border)">'
      + '<span>' + p.provider + '</span>'
      + '<span style="color:' + omniRouteQuotaColor(p.status) + ';font-weight:600">' + p.status.toUpperCase() + ' (' + pct + ', ' + p.throttled + '/' + p.total + ')</span>'
      + '</div>';
  });
  box.innerHTML = html;
}

function loadOmniRouteQuota() {
  fetch('/tools/department-hq/api/contractors/omniroute-quota', { cache: 'no-cache' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.success) {
        var box = document.getElementById('omniroute-quota-status');
        if (box) box.textContent = d.error || 'Unavailable';
        return;
      }
      renderOmniRouteQuota(d.providers || []);
    })
    .catch(function () {
      var box = document.getElementById('omniroute-quota-status');
      if (box) box.textContent = 'Could not load quota status.';
    });
}
```

Then wire it into the existing `loadContractors()` function so it loads alongside the rest of the tab — add this line at the start of `loadContractors()`'s body (around line 7072):

```javascript
  loadOmniRouteQuota();
```

- [ ] **Step 4: Manual verification (UI change — no automated test for markup/JS in this codebase's existing pattern)**

Run: `docker restart archie_platform`

Then, using a real authenticated browser session (Playwright, matching this session's established verification pattern — log in as the `claude` platform account per `reference_claude-platform-login.md`, navigate to `/tools/department-hq`, click the Contractors tab), confirm:
- The "OmniRoute Quota (Deep Space Nine)" card renders.
- `#omniroute-quota-status` shows at least the `opencode-zen` row with a status color and percentage (not "Loading…" stuck, not an error).
- Zero console errors on the page.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/contractor_routes.py platform_v2/tools/department_hq/templates/department_hq.html platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(omniroute-quota): DHQ Contractors tab dashboard card (DS9 phase 2, task 6)"
```

---

## Final Note

This plan deliberately does NOT include a task for folding into `kin_welfare_digest` — see "Global Constraints" above for why that was dropped during planning. If a periodic (not alert-triggered) summary is wanted later, it should be its own small, independent scheduled note to A.R.C.H.I.E.'s inbox (`director_report_service.submit_via_inbox`), not entangled with K.I.N.'s severity-gated welfare pipeline.
