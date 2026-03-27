# Repair Bay v2 — F.O.R.G.E. Auto-Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Repair Bay with automated Dependabot vulnerability ingestion, agent-delegated remediation, S.H.I.E.L.D. compliance gating, CodeRabbit absorption, and a unified repair queue UI.

**Architecture:** New agent loop job polls GitHub Dependabot API every 6h, F.O.R.G.E. triages alerts into a `repair_queue` table, delegates fixes to Engineering staff agents via Bridge dispatch, and S.H.I.E.L.D. validates before auto-merge. UI gets a unified Repair Queue landing tab plus Vulnerabilities and Reviews tabs.

**Tech Stack:** Python/Flask, PostgreSQL, GitHub REST API, APScheduler, Bridge Dispatcher, LCARS CSS

**Spec:** `docs/superpowers/specs/2026-03-27-repair-bay-v2-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `platform_v2/tools/dev_pipeline/services/dependabot_service.py` | Poll GitHub Dependabot API, discover manifests, create repair queue entries |
| `platform_v2/tools/dev_pipeline/services/forge_triage.py` | Triage alerts, determine fix strategy, delegate via Bridge |
| `platform_v2/tools/dev_pipeline/services/shield_gate.py` | S.H.I.E.L.D. compliance validation before merge |
| `platform_v2/tools/dev_pipeline/repair_routes.py` | REST endpoints for repair queue UI |
| `database/migrations/300_repair_queue.sql` | New tables: repair_queue, manifest_registry |
| `tests/test_dependabot_service.py` | Tests for Dependabot polling and manifest discovery |
| `tests/test_forge_triage.py` | Tests for triage logic and fix strategy |
| `tests/test_shield_gate.py` | Tests for compliance gate |
| `tests/test_repair_routes.py` | Tests for repair queue API endpoints |

### Modified Files
| File | Change |
|------|--------|
| `platform_v2/tools/dev_pipeline/services/github_service.py` | Add 3 functions: `get_dependabot_alerts()`, `dismiss_dependabot_alert()`, `get_coderabbit_reviews()` |
| `platform_v2/tools/dev_pipeline/__init__.py` | Register `repair_routes` |
| `platform_v2/mcp_server/tools/forge_tools.py` | Add `forge_scan_vulns` tool, extend `forge_health` and `forge_stats` |
| `ai_bridge/agent_loop.py` | Register `dependabot_scan` job (every 6h) |
| `platform_v2/templates/tools/dev_pipeline.html` | Add Repair Queue, Vulnerabilities, Reviews tabs |

### Deleted Files
| File | Reason |
|------|--------|
| `platform_v2/templates/tools/coderabbit.html` | Orphaned — useful parts absorbed into dev_pipeline.html |

---

## Task 1: Database Migration — repair_queue and manifest_registry

**Files:**
- Create: `database/migrations/300_repair_queue.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 300_repair_queue.sql
-- Repair Bay v2: repair_queue + manifest_registry tables
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS repair_queue (
    id SERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL CHECK (source IN ('dependabot', 'scan', 'coderabbit')),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    package_name VARCHAR(255),
    manifest_path VARCHAR(500),
    alert_number INTEGER,
    advisory_id VARCHAR(50),
    vulnerable_range VARCHAR(100),
    fix_version VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'fixed', 'failed', 'escalated', 'dismissed')),
    proposal_id INTEGER,
    assigned_agent VARCHAR(100),
    pr_number INTEGER,
    attempts INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    dismiss_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repair_queue_source_alert
    ON repair_queue(source, alert_number) WHERE alert_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_repair_queue_status ON repair_queue(status);
CREATE INDEX IF NOT EXISTS idx_repair_queue_severity ON repair_queue(severity);

CREATE TABLE IF NOT EXISTS manifest_registry (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL UNIQUE,
    manifest_type VARCHAR(20) NOT NULL
        CHECK (manifest_type IN ('pip', 'npm', 'go', 'ruby', 'cargo')),
    last_scanned_at TIMESTAMP,
    package_count INTEGER DEFAULT 0,
    alert_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/300_repair_queue.sql
```

Expected: `CREATE TABLE` x2, `CREATE INDEX` x3

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt repair_queue" -c "\dt manifest_registry"
```

Expected: Both tables listed

- [ ] **Step 4: Commit**

```bash
git add database/migrations/300_repair_queue.sql
git commit -m "feat(repair-bay): add repair_queue + manifest_registry tables"
```

---

## Task 2: GitHub Service — Dependabot API Functions

**Files:**
- Modify: `platform_v2/tools/dev_pipeline/services/github_service.py`
- Create: `tests/test_dependabot_service.py`

- [ ] **Step 1: Write failing tests for Dependabot API functions**

Create `tests/test_dependabot_service.py`:

```python
"""Tests for Dependabot API functions in github_service."""
import pytest
from unittest.mock import patch, MagicMock


def _mock_api_get(success_data):
    """Helper to mock _api_get returning (True, data)."""
    return patch(
        "tools.dev_pipeline.services.github_service._api_get",
        return_value=(True, success_data),
    )


class TestGetDependabotAlerts:
    def test_returns_open_alerts(self):
        from tools.dev_pipeline.services.github_service import get_dependabot_alerts

        mock_alerts = [
            {
                "number": 81,
                "security_vulnerability": {
                    "severity": "medium",
                    "package": {"name": "requests", "ecosystem": "pip"},
                    "vulnerable_version_range": "< 2.33.0",
                    "first_patched_version": {"identifier": "2.33.0"},
                },
                "security_advisory": {
                    "summary": "Insecure Temp File Reuse",
                    "ghsa_id": "GHSA-xxxx-yyyy",
                },
                "dependency": {"manifest_path": "requirements.txt"},
                "state": "open",
            }
        ]
        with _mock_api_get(mock_alerts):
            result = get_dependabot_alerts(state="open")
            assert result["success"] is True
            assert len(result["alerts"]) == 1
            assert result["alerts"][0]["number"] == 81

    def test_handles_api_failure(self):
        from tools.dev_pipeline.services.github_service import get_dependabot_alerts

        with patch(
            "tools.dev_pipeline.services.github_service._api_get",
            return_value=(False, {"error": "rate limited"}),
        ):
            result = get_dependabot_alerts()
            assert result["success"] is False


class TestDismissDependabotAlert:
    def test_dismisses_alert(self):
        from tools.dev_pipeline.services.github_service import dismiss_dependabot_alert

        with patch(
            "tools.dev_pipeline.services.github_service._api_patch",
            return_value=(True, {"state": "dismissed"}),
        ):
            result = dismiss_dependabot_alert(81, "fix_started")
            assert result["success"] is True


class TestGetCoderabbitReviews:
    def test_returns_review_comments(self):
        from tools.dev_pipeline.services.github_service import get_coderabbit_reviews

        mock_comments = [
            {"user": {"login": "coderabbitai[bot]"}, "body": "Fix: use parameterized query"},
            {"user": {"login": "someone"}, "body": "LGTM"},
        ]
        with _mock_api_get(mock_comments):
            result = get_coderabbit_reviews(42)
            assert result["success"] is True
            assert len(result["reviews"]) == 1
            assert "parameterized" in result["reviews"][0]["body"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_dependabot_service.py -v
```

Expected: FAIL — `ImportError` or `AttributeError` (functions don't exist yet)

- [ ] **Step 3: Implement the three functions in github_service.py**

Add to the end of `platform_v2/tools/dev_pipeline/services/github_service.py`:

```python
def get_dependabot_alerts(state: str = "open") -> Dict:
    """Fetch Dependabot alerts from GitHub API."""
    ok, data = _api_get("/dependabot/alerts", params={"state": state, "per_page": 100})
    if not ok:
        return {"success": False, "error": data.get("error", "API request failed")}
    alerts = []
    for alert in data:
        vuln = alert.get("security_vulnerability", {})
        alerts.append({
            "number": alert.get("number"),
            "severity": vuln.get("severity", "unknown"),
            "package_name": vuln.get("package", {}).get("name"),
            "ecosystem": vuln.get("package", {}).get("ecosystem"),
            "vulnerable_range": vuln.get("vulnerable_version_range"),
            "fix_version": (vuln.get("first_patched_version") or {}).get("identifier"),
            "summary": alert.get("security_advisory", {}).get("summary"),
            "advisory_id": alert.get("security_advisory", {}).get("ghsa_id"),
            "manifest_path": alert.get("dependency", {}).get("manifest_path"),
            "state": alert.get("state"),
        })
    return {"success": True, "alerts": alerts, "count": len(alerts)}


def dismiss_dependabot_alert(alert_number: int, reason: str = "fix_started") -> Dict:
    """Dismiss a Dependabot alert."""
    ok, data = _api_patch(
        f"/dependabot/alerts/{alert_number}",
        data={"state": "dismissed", "dismissed_reason": reason},
    )
    if not ok:
        return {"success": False, "error": data.get("error", "Dismiss failed")}
    return {"success": True, "alert_number": alert_number, "state": "dismissed"}


def get_coderabbit_reviews(pr_number: int) -> Dict:
    """Fetch CodeRabbit review comments from a PR."""
    ok, data = _api_get(f"/pulls/{pr_number}/comments")
    if not ok:
        return {"success": False, "error": data.get("error", "Failed to fetch reviews")}
    reviews = [
        {"body": c.get("body", ""), "created_at": c.get("created_at"), "path": c.get("path")}
        for c in data
        if "coderabbit" in (c.get("user", {}).get("login", "")).lower()
    ]
    return {"success": True, "reviews": reviews, "count": len(reviews)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_dependabot_service.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/dev_pipeline/services/github_service.py tests/test_dependabot_service.py
git commit -m "feat(repair-bay): add Dependabot + CodeRabbit API functions to github_service"
```

---

## Task 3: Dependabot Service — Polling and Manifest Discovery

**Files:**
- Create: `platform_v2/tools/dev_pipeline/services/dependabot_service.py`
- Modify: `tests/test_dependabot_service.py`

- [ ] **Step 1: Write failing tests for dependabot_service**

Append to `tests/test_dependabot_service.py`:

```python
class TestDiscoverManifests:
    def test_finds_requirements_txt(self, tmp_path):
        from tools.dev_pipeline.services.dependabot_service import discover_manifests

        (tmp_path / "requirements.txt").write_text("flask==3.1.0\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "requirements.txt").write_text("requests==2.31.0\n")

        results = discover_manifests(str(tmp_path))
        assert len(results) == 2
        assert all(r["manifest_type"] == "pip" for r in results)

    def test_finds_package_json(self, tmp_path):
        from tools.dev_pipeline.services.dependabot_service import discover_manifests

        (tmp_path / "package.json").write_text('{"dependencies": {}}')
        results = discover_manifests(str(tmp_path))
        assert len(results) == 1
        assert results[0]["manifest_type"] == "npm"


class TestPollAndIngest:
    def test_creates_repair_queue_entries(self):
        from tools.dev_pipeline.services.dependabot_service import poll_and_ingest

        mock_alerts = {
            "success": True,
            "alerts": [
                {
                    "number": 81,
                    "severity": "medium",
                    "package_name": "requests",
                    "ecosystem": "pip",
                    "vulnerable_range": "< 2.33.0",
                    "fix_version": "2.33.0",
                    "summary": "Insecure Temp File",
                    "advisory_id": "GHSA-xxxx",
                    "manifest_path": "requirements.txt",
                    "state": "open",
                },
            ],
            "count": 1,
        }
        with patch(
            "tools.dev_pipeline.services.dependabot_service.get_dependabot_alerts",
            return_value=mock_alerts,
        ), patch(
            "tools.dev_pipeline.services.dependabot_service.get_db_cursor"
        ) as mock_db:
            mock_cur = MagicMock()
            mock_conn = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_cur.fetchone.return_value = None  # no existing entry

            result = poll_and_ingest()
            assert result["success"] is True
            assert result["new_alerts"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_dependabot_service.py::TestDiscoverManifests -v
```

Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement dependabot_service.py**

Create `platform_v2/tools/dev_pipeline/services/dependabot_service.py`:

```python
"""Dependabot alert polling, manifest discovery, and repair queue ingestion."""

import os
import logging
from pathlib import Path
from typing import Dict, List

from database import get_db_cursor
from tools.dev_pipeline.services.github_service import get_dependabot_alerts

logger = logging.getLogger(__name__)

MANIFEST_PATTERNS = {
    "requirements.txt": "pip",
    "pyproject.toml": "pip",
    "package.json": "npm",
    "go.mod": "go",
    "Gemfile": "ruby",
    "Cargo.toml": "cargo",
}

REPO_ROOT = "/mnt/archie_brain"


def discover_manifests(root_path: str = REPO_ROOT) -> List[Dict]:
    """Walk the repo and find all dependency manifest files."""
    manifests = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox"}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            if fname in MANIFEST_PATTERNS:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root_path)
                manifests.append({
                    "file_path": rel_path,
                    "manifest_type": MANIFEST_PATTERNS[fname],
                })
    return manifests


def sync_manifest_registry(manifests: List[Dict] = None) -> Dict:
    """Update manifest_registry table with discovered manifests."""
    if manifests is None:
        manifests = discover_manifests()
    with get_db_cursor(commit=True) as (conn, cur):
        for m in manifests:
            cur.execute(
                """INSERT INTO manifest_registry (file_path, manifest_type)
                   VALUES (%s, %s)
                   ON CONFLICT (file_path) DO UPDATE SET last_scanned_at = NOW()""",
                (m["file_path"], m["manifest_type"]),
            )
    return {"success": True, "count": len(manifests)}


def poll_and_ingest() -> Dict:
    """Poll Dependabot API and ingest new alerts into repair_queue."""
    alerts_result = get_dependabot_alerts(state="open")
    if not alerts_result["success"]:
        logger.error("Dependabot poll failed: %s", alerts_result.get("error"))
        return {"success": False, "error": alerts_result.get("error")}

    new_count = 0
    skipped = 0

    with get_db_cursor(commit=True) as (conn, cur):
        for alert in alerts_result["alerts"]:
            cur.execute(
                "SELECT id FROM repair_queue WHERE source = 'dependabot' AND alert_number = %s",
                (alert["number"],),
            )
            if cur.fetchone():
                skipped += 1
                continue

            cur.execute(
                """INSERT INTO repair_queue
                   (source, severity, package_name, manifest_path,
                    alert_number, advisory_id, vulnerable_range, fix_version, status)
                   VALUES ('dependabot', %s, %s, %s, %s, %s, %s, %s, 'pending')""",
                (
                    alert["severity"],
                    alert["package_name"],
                    alert["manifest_path"],
                    alert["number"],
                    alert["advisory_id"],
                    alert["vulnerable_range"],
                    alert["fix_version"],
                ),
            )
            new_count += 1

    logger.info("Dependabot poll: %d new, %d skipped", new_count, skipped)
    return {
        "success": True,
        "new_alerts": new_count,
        "skipped": skipped,
        "total_polled": alerts_result["count"],
    }


def get_repair_queue(status: str = None, severity: str = None, source: str = None) -> Dict:
    """Fetch repair queue entries with optional filters."""
    query = "SELECT * FROM repair_queue WHERE 1=1"
    params = []
    if status:
        query += " AND status = %s"
        params.append(status)
    if severity:
        query += " AND severity = %s"
        params.append(severity)
    if source:
        query += " AND source = %s"
        params.append(source)
    query += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC"

    with get_db_cursor() as (conn, cur):
        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    return {"success": True, "items": rows, "count": len(rows)}


def update_repair_item(item_id: int, **fields) -> Dict:
    """Update a repair queue item."""
    allowed = {"status", "assigned_agent", "pr_number", "attempts", "dismiss_reason", "last_attempt_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return {"success": False, "error": "No valid fields to update"}

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [item_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE repair_queue SET {set_clause}, updated_at = NOW() WHERE id = %s",
            values,
        )
    return {"success": True, "id": item_id}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_dependabot_service.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/dev_pipeline/services/dependabot_service.py tests/test_dependabot_service.py
git commit -m "feat(repair-bay): dependabot polling service + manifest discovery"
```

---

## Task 4: F.O.R.G.E. Triage — Fix Strategy and Bridge Dispatch

**Files:**
- Create: `platform_v2/tools/dev_pipeline/services/forge_triage.py`
- Create: `tests/test_forge_triage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_forge_triage.py`:

```python
"""Tests for F.O.R.G.E. triage logic."""
import pytest
from unittest.mock import patch, MagicMock


class TestDetermineFixStrategy:
    def test_simple_bump(self):
        from tools.dev_pipeline.services.forge_triage import determine_fix_strategy

        alert = {
            "package_name": "requests",
            "fix_version": "2.33.0",
            "vulnerable_range": "< 2.33.0",
            "severity": "medium",
            "manifest_path": "requirements.txt",
        }
        strategy = determine_fix_strategy(alert)
        assert strategy["action"] == "version_bump"
        assert strategy["target_version"] == "2.33.0"

    def test_no_fix_available(self):
        from tools.dev_pipeline.services.forge_triage import determine_fix_strategy

        alert = {
            "package_name": "legacy-lib",
            "fix_version": None,
            "vulnerable_range": ">= 0",
            "severity": "high",
            "manifest_path": "requirements.txt",
        }
        strategy = determine_fix_strategy(alert)
        assert strategy["action"] == "no_fix"

    def test_major_version_escalates(self):
        from tools.dev_pipeline.services.forge_triage import determine_fix_strategy

        alert = {
            "package_name": "flask",
            "fix_version": "4.0.0",
            "vulnerable_range": "< 4.0.0",
            "severity": "high",
            "manifest_path": "requirements.txt",
        }
        with patch(
            "tools.dev_pipeline.services.forge_triage._get_current_version",
            return_value="3.1.0",
        ):
            strategy = determine_fix_strategy(alert)
            assert strategy["action"] == "major_upgrade"


class TestTriageAlert:
    def test_creates_repair_entry_and_dispatches(self):
        from tools.dev_pipeline.services.forge_triage import triage_alert

        alert = {
            "id": 1,
            "package_name": "requests",
            "fix_version": "2.33.0",
            "vulnerable_range": "< 2.33.0",
            "severity": "medium",
            "manifest_path": "requirements.txt",
        }
        with patch(
            "tools.dev_pipeline.services.forge_triage.update_repair_item"
        ) as mock_update, patch(
            "tools.dev_pipeline.services.forge_triage._dispatch_fix"
        ) as mock_dispatch:
            mock_dispatch.return_value = {"success": True}
            result = triage_alert(alert)
            assert result["success"] is True
            assert mock_update.called
            assert mock_dispatch.called
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_forge_triage.py -v
```

Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement forge_triage.py**

Create `platform_v2/tools/dev_pipeline/services/forge_triage.py`:

```python
"""F.O.R.G.E. triage: determine fix strategy and dispatch to Engineering agents."""

import re
import logging
from typing import Dict, Optional

from tools.dev_pipeline.services.dependabot_service import update_repair_item

logger = logging.getLogger(__name__)


def _get_current_version(package_name: str, manifest_path: str) -> Optional[str]:
    """Read current pinned version from a manifest file."""
    try:
        full_path = f"/mnt/archie_brain/{manifest_path}"
        with open(full_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                match = re.match(
                    rf"^{re.escape(package_name)}\s*[=~<>!]+\s*([\d.]+)",
                    line,
                    re.IGNORECASE,
                )
                if match:
                    return match.group(1)
    except (FileNotFoundError, PermissionError):
        pass
    return None


def _is_major_upgrade(current: str, target: str) -> bool:
    """Check if target is a major version bump from current."""
    if not current or not target:
        return False
    try:
        cur_major = int(current.split(".")[0])
        tgt_major = int(target.split(".")[0])
        return tgt_major > cur_major
    except (ValueError, IndexError):
        return False


def determine_fix_strategy(alert: Dict) -> Dict:
    """Determine how to fix a vulnerability alert.

    Returns: {"action": "version_bump"|"major_upgrade"|"no_fix", ...}
    """
    fix_version = alert.get("fix_version")

    if not fix_version:
        return {
            "action": "no_fix",
            "reason": "No patched version available",
            "package": alert.get("package_name"),
        }

    current = _get_current_version(
        alert["package_name"], alert.get("manifest_path", "")
    )

    if _is_major_upgrade(current, fix_version):
        return {
            "action": "major_upgrade",
            "package": alert["package_name"],
            "current_version": current,
            "target_version": fix_version,
            "reason": f"Major version upgrade {current} -> {fix_version} requires review",
        }

    return {
        "action": "version_bump",
        "package": alert["package_name"],
        "current_version": current,
        "target_version": fix_version,
        "manifest_path": alert.get("manifest_path"),
    }


def _dispatch_fix(alert: Dict, strategy: Dict) -> Dict:
    """Dispatch fix to an Engineering staff agent via Bridge."""
    try:
        from bridge_dispatcher import get_dispatcher

        prompt = (
            f"Fix vulnerability in {strategy['package']}: "
            f"bump from {strategy.get('current_version', 'unknown')} "
            f"to {strategy['target_version']} in {strategy.get('manifest_path')}. "
            f"Update the version pin, run tests, and report results."
        )
        dispatcher = get_dispatcher()
        result = dispatcher.dispatch(
            capability="code_fix",
            prompt=prompt,
            module_id="repair_bay",
            system_prompt=(
                "You are an Engineering staff agent working for F.O.R.G.E. "
                "Fix the dependency vulnerability by bumping the version in the manifest file. "
                "Verify the fix doesn't break imports or tests."
            ),
        )
        return {"success": result.success, "response": result.response}
    except Exception as e:
        logger.error("Bridge dispatch failed: %s", e)
        return {"success": False, "error": str(e)}


def triage_alert(alert: Dict) -> Dict:
    """Triage a single repair queue item."""
    item_id = alert["id"]
    strategy = determine_fix_strategy(alert)

    if strategy["action"] == "no_fix":
        update_repair_item(item_id, status="dismissed", dismiss_reason="no_fix_available")
        logger.info("Alert %d dismissed: no fix for %s", item_id, alert.get("package_name"))
        return {"success": True, "action": "dismissed", "reason": strategy["reason"]}

    if strategy["action"] == "major_upgrade":
        update_repair_item(item_id, status="escalated")
        logger.info("Alert %d escalated: major upgrade for %s", item_id, alert.get("package_name"))
        return {"success": True, "action": "escalated", "reason": strategy["reason"]}

    # version_bump — dispatch to staff agent
    update_repair_item(item_id, status="in_progress", assigned_agent="F.O.R.G.E.")
    dispatch_result = _dispatch_fix(alert, strategy)

    if dispatch_result["success"]:
        return {"success": True, "action": "dispatched", "strategy": strategy}
    else:
        update_repair_item(item_id, status="failed")
        return {"success": False, "action": "dispatch_failed", "error": dispatch_result.get("error")}


def triage_pending_queue() -> Dict:
    """Triage all pending items in the repair queue."""
    from tools.dev_pipeline.services.dependabot_service import get_repair_queue

    pending = get_repair_queue(status="pending")
    if not pending["success"]:
        return pending

    results = {"dispatched": 0, "escalated": 0, "dismissed": 0, "failed": 0}
    for item in pending["items"]:
        result = triage_alert(item)
        action = result.get("action", "failed")
        if action in results:
            results[action] += 1

    return {"success": True, **results}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_forge_triage.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/dev_pipeline/services/forge_triage.py tests/test_forge_triage.py
git commit -m "feat(repair-bay): F.O.R.G.E. triage logic + Bridge dispatch for fixes"
```

---

## Task 5: S.H.I.E.L.D. Compliance Gate

**Files:**
- Create: `platform_v2/tools/dev_pipeline/services/shield_gate.py`
- Create: `tests/test_shield_gate.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_shield_gate.py`:

```python
"""Tests for S.H.I.E.L.D. compliance gate."""
import pytest
from unittest.mock import patch, MagicMock


class TestValidateFix:
    def test_passes_clean_fix(self):
        from tools.dev_pipeline.services.shield_gate import validate_fix

        fix_report = {
            "repair_item_id": 1,
            "pr_number": 42,
            "package_name": "requests",
            "old_version": "2.31.0",
            "new_version": "2.33.0",
            "test_passed": True,
            "files_changed": ["requirements.txt"],
            "diff_lines": 2,
        }
        result = validate_fix(fix_report)
        assert result["approved"] is True

    def test_rejects_failing_tests(self):
        from tools.dev_pipeline.services.shield_gate import validate_fix

        fix_report = {
            "repair_item_id": 1,
            "pr_number": 42,
            "package_name": "requests",
            "old_version": "2.31.0",
            "new_version": "2.33.0",
            "test_passed": False,
            "files_changed": ["requirements.txt"],
            "diff_lines": 2,
        }
        result = validate_fix(fix_report)
        assert result["approved"] is False
        assert "test" in result["reason"].lower()

    def test_rejects_suspicious_diff(self):
        from tools.dev_pipeline.services.shield_gate import validate_fix

        fix_report = {
            "repair_item_id": 1,
            "pr_number": 42,
            "package_name": "requests",
            "old_version": "2.31.0",
            "new_version": "2.33.0",
            "test_passed": True,
            "files_changed": ["requirements.txt", ".env", "secrets.json"],
            "diff_lines": 50,
        }
        result = validate_fix(fix_report)
        assert result["approved"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_shield_gate.py -v
```

Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement shield_gate.py**

Create `platform_v2/tools/dev_pipeline/services/shield_gate.py`:

```python
"""S.H.I.E.L.D. compliance gate -- validates fixes before auto-merge."""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

SUSPICIOUS_FILES = {".env", "secrets.json", "credentials.json", ".secrets", "id_rsa", "id_ed25519"}
MAX_BUMP_DIFF_LINES = 20
MANIFEST_FILES = {
    "requirements.txt", "pyproject.toml", "package.json",
    "package-lock.json", "go.mod", "go.sum", "Gemfile", "Gemfile.lock",
    "Cargo.toml", "Cargo.lock",
}


def _check_tests_passed(report: Dict) -> tuple:
    if not report.get("test_passed", False):
        return False, "Tests failed -- fix must pass full test suite before merge"
    return True, ""


def _check_suspicious_files(report: Dict) -> tuple:
    changed = set(report.get("files_changed", []))
    suspicious = changed & SUSPICIOUS_FILES
    if suspicious:
        return False, f"Suspicious files in diff: {', '.join(suspicious)} -- possible secret exposure"
    return True, ""


def _check_diff_scope(report: Dict) -> tuple:
    changed = set(report.get("files_changed", []))
    diff_lines = report.get("diff_lines", 0)
    non_manifest = {f for f in changed if f.split("/")[-1] not in MANIFEST_FILES}
    if non_manifest:
        return False, f"Non-manifest files changed: {', '.join(non_manifest)} -- scope exceeds version bump"
    if diff_lines > MAX_BUMP_DIFF_LINES:
        return False, f"Diff too large ({diff_lines} lines) for a version bump -- review manually"
    return True, ""


def validate_fix(report: Dict) -> Dict:
    """Run S.H.I.E.L.D. validation checks on a proposed fix.

    Args:
        report: Dict with keys: repair_item_id, pr_number, package_name,
                old_version, new_version, test_passed, files_changed, diff_lines

    Returns: {"approved": bool, "reason": str, "checks": [...]}
    """
    checks = []
    all_passed = True

    for check_fn in [_check_tests_passed, _check_suspicious_files, _check_diff_scope]:
        passed, reason = check_fn(report)
        check_name = check_fn.__name__.replace("_check_", "")
        checks.append({"check": check_name, "passed": passed, "reason": reason})
        if not passed:
            all_passed = False

    result = {
        "approved": all_passed,
        "repair_item_id": report.get("repair_item_id"),
        "pr_number": report.get("pr_number"),
        "checks": checks,
    }

    if not all_passed:
        failed = [c for c in checks if not c["passed"]]
        result["reason"] = failed[0]["reason"]
        logger.warning(
            "S.H.I.E.L.D. REJECTED fix for %s (PR #%s): %s",
            report.get("package_name"), report.get("pr_number"), result["reason"],
        )
    else:
        result["reason"] = "All checks passed"
        logger.info(
            "S.H.I.E.L.D. APPROVED fix for %s (PR #%s)",
            report.get("package_name"), report.get("pr_number"),
        )

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_shield_gate.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/dev_pipeline/services/shield_gate.py tests/test_shield_gate.py
git commit -m "feat(repair-bay): S.H.I.E.L.D. compliance gate for auto-merge validation"
```

---

## Task 6: Agent Loop Job — Dependabot Scan Registration

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Add the dependabot scan function**

Find `_run_proactive_scan` in `ai_bridge/agent_loop.py` and add nearby:

```python
def _run_dependabot_scan(self):
    """Agent Loop Job: Poll Dependabot alerts and triage pending repairs."""
    try:
        from tools.dev_pipeline.services.dependabot_service import (
            poll_and_ingest,
            sync_manifest_registry,
        )
        from tools.dev_pipeline.services.forge_triage import triage_pending_queue

        sync_manifest_registry()
        poll_result = poll_and_ingest()
        if not poll_result["success"]:
            logger.error("Dependabot poll failed: %s", poll_result.get("error"))
            return

        triage_result = triage_pending_queue()

        self._log_autonomy_action(
            action_type="dependabot_scan",
            details={
                "new_alerts": poll_result.get("new_alerts", 0),
                "dispatched": triage_result.get("dispatched", 0),
                "escalated": triage_result.get("escalated", 0),
                "dismissed": triage_result.get("dismissed", 0),
            },
            success=True,
        )
        logger.info(
            "Dependabot scan complete: %d new, %d dispatched, %d escalated",
            poll_result.get("new_alerts", 0),
            triage_result.get("dispatched", 0),
            triage_result.get("escalated", 0),
        )
    except Exception as e:
        logger.error("Dependabot scan job failed: %s", e)
        self._log_autonomy_action(
            action_type="dependabot_scan",
            details={"error": str(e)},
            success=False,
        )
```

- [ ] **Step 2: Register the job in the scheduler**

Find the section with `add_job` calls (near other 6h jobs like compliance scan). Add:

```python
self.scheduler.add_job(
    with_app_context(self._run_dependabot_scan),
    trigger=IntervalTrigger(hours=6),
    id="dependabot_scan",
    name="Agent Loop: Dependabot Vulnerability Scan",
    replace_existing=True,
)
```

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(repair-bay): register dependabot_scan agent loop job (every 6h)"
```

---

## Task 7: Repair Queue REST Routes

**Files:**
- Create: `platform_v2/tools/dev_pipeline/repair_routes.py`
- Modify: `platform_v2/tools/dev_pipeline/__init__.py`

- [ ] **Step 1: Create repair_routes.py**

Create `platform_v2/tools/dev_pipeline/repair_routes.py`:

```python
"""REST routes for the Repair Queue UI."""

import logging
from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_repair_routes(bp, admin_required):
    """Register repair queue routes on the dev_pipeline blueprint."""

    @bp.route("/api/repair/queue")
    @admin_required
    def repair_queue_list():
        from tools.dev_pipeline.services.dependabot_service import get_repair_queue

        status = request.args.get("status")
        severity = request.args.get("severity")
        source = request.args.get("source")
        result = get_repair_queue(status=status, severity=severity, source=source)
        return jsonify(result)

    @bp.route("/api/repair/queue/<int:item_id>", methods=["PATCH"])
    @admin_required
    def repair_queue_update(item_id):
        from tools.dev_pipeline.services.dependabot_service import update_repair_item

        data = request.get_json() or {}
        result = update_repair_item(item_id, **data)
        return jsonify(result)

    @bp.route("/api/repair/queue/<int:item_id>/triage", methods=["POST"])
    @admin_required
    def repair_queue_triage(item_id):
        from tools.dev_pipeline.services.dependabot_service import get_repair_queue
        from tools.dev_pipeline.services.forge_triage import triage_alert

        queue = get_repair_queue()
        item = next((i for i in queue["items"] if i["id"] == item_id), None)
        if not item:
            return jsonify({"success": False, "error": "Item not found"}), 404
        result = triage_alert(item)
        return jsonify(result)

    @bp.route("/api/repair/poll", methods=["POST"])
    @admin_required
    def repair_poll_now():
        from tools.dev_pipeline.services.dependabot_service import poll_and_ingest

        result = poll_and_ingest()
        return jsonify(result)

    @bp.route("/api/repair/manifests")
    @admin_required
    def repair_manifests():
        from tools.dev_pipeline.services.dependabot_service import discover_manifests

        manifests = discover_manifests()
        return jsonify({"success": True, "manifests": manifests, "count": len(manifests)})

    @bp.route("/api/repair/stats")
    @admin_required
    def repair_stats():
        from tools.dev_pipeline.services.dependabot_service import get_repair_queue

        all_items = get_repair_queue()
        if not all_items["success"]:
            return jsonify(all_items)
        items = all_items["items"]
        stats = {"total": len(items), "by_status": {}, "by_severity": {}, "by_source": {}}
        for item in items:
            for key in ["status", "severity", "source"]:
                bucket = f"by_{key}"
                val = item.get(key, "unknown")
                stats[bucket][val] = stats[bucket].get(val, 0) + 1
        return jsonify({"success": True, "stats": stats})
```

- [ ] **Step 2: Register routes in __init__.py**

Add to `platform_v2/tools/dev_pipeline/__init__.py`, after the `register_github_routes` line:

```python
from .repair_routes import register_repair_routes
register_repair_routes(dev_pipeline_bp, admin_required)
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/dev_pipeline/repair_routes.py platform_v2/tools/dev_pipeline/__init__.py
git commit -m "feat(repair-bay): repair queue REST routes + registration"
```

---

## Task 8: MCP Tool Extensions

**Files:**
- Modify: `platform_v2/mcp_server/tools/forge_tools.py`

- [ ] **Step 1: Read current forge_tools.py**

Read `platform_v2/mcp_server/tools/forge_tools.py` to find exact insertion points.

- [ ] **Step 2: Add forge_scan_vulns handler**

Add after the existing handlers:

```python
def forge_scan_vulns_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger on-demand Dependabot poll + manifest discovery."""
    from tools.dev_pipeline.services.dependabot_service import (
        poll_and_ingest,
        sync_manifest_registry,
        get_repair_queue,
    )

    manifests = sync_manifest_registry()
    poll = poll_and_ingest()
    queue = get_repair_queue()

    return {
        "success": True,
        "manifests_discovered": manifests.get("count", 0),
        "new_alerts": poll.get("new_alerts", 0) if poll.get("success") else 0,
        "queue_depth": queue.get("count", 0) if queue.get("success") else 0,
        "poll_error": poll.get("error") if not poll.get("success") else None,
    }
```

- [ ] **Step 3: Extend forge_health_handler**

Add inside `forge_health_handler`, after existing health checks:

```python
try:
    from tools.dev_pipeline.services.dependabot_service import get_repair_queue
    queue = get_repair_queue()
    health_data["repair_queue_depth"] = queue.get("count", 0) if queue.get("success") else "error"
except Exception:
    health_data["repair_queue_depth"] = "unavailable"
```

- [ ] **Step 4: Extend forge_stats_handler**

Add inside `forge_stats_handler`, after existing stats:

```python
try:
    from tools.dev_pipeline.services.dependabot_service import get_repair_queue
    queue = get_repair_queue()
    items = queue.get("items", []) if queue.get("success") else []
    stats_data["vulnerabilities"] = {
        "total": len(items),
        "pending": sum(1 for i in items if i.get("status") == "pending"),
        "fixed": sum(1 for i in items if i.get("status") == "fixed"),
        "failed": sum(1 for i in items if i.get("status") == "failed"),
        "escalated": sum(1 for i in items if i.get("status") == "escalated"),
    }
except Exception:
    stats_data["vulnerabilities"] = "unavailable"
```

- [ ] **Step 5: Register the new tool**

Add in `register_forge_tools()`:

```python
register_tool(
    name="forge_scan_vulns",
    category="forge",
    description="Scan for dependency vulnerabilities -- polls Dependabot, discovers manifests, reports repair queue status.",
    input_schema={"type": "object", "properties": {}},
    handler=forge_scan_vulns_handler,
    requires_permission="write",
)
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/mcp_server/tools/forge_tools.py
git commit -m "feat(repair-bay): add forge_scan_vulns MCP tool + extend health/stats"
```

---

## Task 9: UI — Repair Queue + Vulnerabilities + Reviews Tabs

**Files:**
- Modify: `platform_v2/templates/tools/dev_pipeline.html`

This task requires reading the current template to understand the exact tab structure, then adding three new tabs with their content panels and JavaScript. The implementation must follow the existing tab switching pattern in the template.

- [ ] **Step 1: Read current dev_pipeline.html tab structure**

```bash
cd /mnt/archie_brain && grep -n "subtab\|tab-content\|switchTab\|data-tab" platform_v2/templates/tools/dev_pipeline.html | head -40
```

Identify the tab navigation pattern and content panel IDs.

- [ ] **Step 2: Add three new tab buttons to navigation**

Add before existing tabs, making "Repair Queue" the default active:
- Repair Queue (shield-alert icon)
- Vulnerabilities (bug icon)
- Reviews (message-square icon)

Remove `active` class from the previous default tab.

- [ ] **Step 3: Add Repair Queue content panel**

Add a `tab-content` div with:
- Filter controls row (severity, source, status dropdowns + Poll Now button)
- Stats summary row
- Table with columns: Severity, Source, Package, Manifest, Status, Agent, Actions
- Empty state with shield-check icon

- [ ] **Step 4: Add Vulnerabilities content panel**

Add a `tab-content` div with:
- Dependabot alerts list (card-style, severity-colored)
- Discovered manifests list

- [ ] **Step 5: Add Reviews content panel**

Add a `tab-content` div with:
- PR review list from forge PRs endpoint
- Empty state

- [ ] **Step 6: Add JavaScript for data loading**

Add functions:
- `switchRepairTab(tabId)` — tab switching + lazy data loading
- `loadRepairQueue()` — fetch `/api/repair/queue` and `/api/repair/stats`, render table
- `triageItem(id)` — POST to `/api/repair/queue/{id}/triage`
- `dismissItem(id)` — PATCH to `/api/repair/queue/{id}` with status=dismissed
- `pollNow()` — POST to `/api/repair/poll`, refresh queue
- `loadVulnerabilities()` — fetch Dependabot source items + manifests
- `loadReviews()` — fetch forge PRs
- DOMContentLoaded handler to load repair queue on page open

**Important:** Use `textContent` for user-supplied text. Use DOM creation methods or template literals with escaped values from our own API for structured HTML. Follow the existing JS patterns in the template.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/templates/tools/dev_pipeline.html
git commit -m "feat(repair-bay): unified repair queue + vulnerabilities + reviews tabs in UI"
```

---

## Task 10: Delete Orphaned coderabbit.html

**Files:**
- Delete: `platform_v2/templates/tools/coderabbit.html`

- [ ] **Step 1: Verify no routes reference coderabbit.html**

```bash
cd /mnt/archie_brain && grep -r "coderabbit" platform_v2/ --include="*.py" -l
```

Expected: No route files reference it

- [ ] **Step 2: Delete the file**

```bash
git rm platform_v2/templates/tools/coderabbit.html
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: delete orphaned coderabbit.html (absorbed into Repair Bay)"
```

---

## Task 11: Deploy and Verify

**Files:** None (deployment + testing)

- [ ] **Step 1: Restart the platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Check logs for errors**

```bash
docker logs archie_platform --tail 50 2>&1 | grep -i error
```

Expected: No import errors or registration failures

- [ ] **Step 3: Verify repair queue API**

```bash
curl -s http://192.168.1.200:3000/tools/dev-pipeline/api/repair/stats | python3 -m json.tool
```

Expected: JSON with `success: true` and stats

- [ ] **Step 4: Verify MCP tool**

Call `forge_scan_vulns` via MCP to trigger first poll.

- [ ] **Step 5: Browser test — Repair Bay UI**

Navigate to `http://192.168.1.200:3000/tools/dev-pipeline` and verify:
- Repair Queue tab loads as default
- Filters work (severity, source, status)
- Poll Now button triggers Dependabot fetch
- Vulnerabilities tab shows alert details + manifests
- Reviews tab shows PR list

- [ ] **Step 6: Verify agent loop job registered**

```bash
curl -s http://192.168.1.200:3000/api/agent-loop/status | python3 -m json.tool | grep dependabot
```

Expected: `dependabot_scan` job listed

- [ ] **Step 7: Final push**

```bash
git push
```

- [ ] **Step 8: Log completion in Dev HQ**

Use MCP tools:
- `complete_task` with verification notes
- `log_decision` for architectural choice (Dependabot polling vs webhooks)
- `update_project_understanding` for Repair Bay project
