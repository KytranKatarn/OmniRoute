# Autonomous Deploy Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `deploy_static` and `deploy_vps` as Department HQ capabilities so B.A.S.E. (agent_id=139) autonomously deploys Hostinger sites and VPS Docker products — replacing all manual Claude deploy steps.

**Architecture:** New `deploy_service.py` implements risk classification → Backup Manager snapshot → execute → verify → retry/rollback. Two capabilities added to `CAPABILITY_DEPARTMENT_MAP`. Translation orchestrator dispatches deploy after bundle export. Repair Bay routes become thin wrappers.

**Tech Stack:** Python, Flask, APScheduler, subprocess (SSH rsync), requests (Hostinger REST API), PostgreSQL, existing Backup Manager service.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `platform_v2/database/migrations/173_deploy_capabilities.sql` | Create | Seed deploy_static + deploy_vps skills on B.A.S.E. |
| `platform_v2/services/deploy_service.py` | Create | Full deploy pipeline: risk check, backup, execute, verify, retry, rollback |
| `platform_v2/tests/test_deploy_service.py` | Create | Unit + integration tests |
| `platform_v2/tools/department_hq/services/department_coordinator.py:45` | Modify | Add deploy_static + deploy_vps to CAPABILITY_DEPARTMENT_MAP |
| `platform_v2/tools/department_hq/services/department_dispatcher.py:97` | Modify | Same 2 capabilities |
| `platform_v2/tools/consciousness/translation_scanners/orchestrator.py` | Modify | Dispatch deploy_static after _export_bundle() |
| `platform_v2/tools/repair_bay/deploy_routes.py` | Modify | Wrap /api/deploy/execute to call dispatch() |

---

### Task 1: DB Migration — Seed B.A.S.E. Deploy Skills

**Files:**
- Create: `platform_v2/database/migrations/173_deploy_capabilities.sql`

- [ ] **Step 1: Write the migration.**

```sql
-- 173_deploy_capabilities.sql
-- Seeds deploy_static + deploy_vps skills on B.A.S.E. (id=139)
-- Part of Autonomous Deploy Pipeline (Project #292, 2026-04-28)

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES
    (139, 'deploy_static', 5, NULL),
    (139, 'deploy_vps',    5, NULL)
ON CONFLICT (agent_id, skill_name) DO UPDATE
    SET proficiency_level = EXCLUDED.proficiency_level;

-- Add capabilities to CAPABILITY_DEPARTMENT_MAP reference table (if it exists as a DB table)
-- Note: CAPABILITY_DEPARTMENT_MAP is currently in Python code, not DB.
-- This migration only handles agent_skills.
```

- [ ] **Step 2: Run migration.**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "$(cat platform_v2/database/migrations/173_deploy_capabilities.sql)"
```

Expected output: `INSERT 0 2`

- [ ] **Step 3: Verify.**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT a.name, s.skill_name, s.proficiency_level
FROM agents a JOIN agent_skills s ON s.agent_id = a.id
WHERE a.id = 139 AND s.skill_name IN ('deploy_static','deploy_vps');"
```

Expected:
```
   name   |  skill_name   | proficiency_level
----------+---------------+------------------
 B.A.S.E. | deploy_static |                 5
 B.A.S.E. | deploy_vps    |                 5
```

- [ ] **Step 4: Commit.**

```bash
git checkout -b feat/autonomous-deploy-pipeline
git add platform_v2/database/migrations/173_deploy_capabilities.sql
git commit -m "feat(db): migration 173 — seed deploy_static + deploy_vps on B.A.S.E."
```

---

### Task 2: CAPABILITY_DEPARTMENT_MAP — Add Deploy Capabilities

**Files:**
- Modify: `platform_v2/tools/department_hq/services/department_coordinator.py` (line ~45)
- Modify: `platform_v2/tools/department_hq/services/department_dispatcher.py` (line ~97)

First, confirm the exact line numbers:
```bash
grep -n "CAPABILITY_DEPARTMENT_MAP\|'translate'\|'visual_design'" \
  /mnt/archie_brain/platform_v2/tools/department_hq/services/department_coordinator.py | head -5
```

- [ ] **Step 1: Write failing test.**

Create `platform_v2/tests/test_deploy_service.py`:

```python
"""Tests for the Autonomous Deploy Pipeline (Project #292).

Run: docker exec archie_platform python -m pytest tests/test_deploy_service.py -v
"""
from __future__ import annotations


class TestCapabilityRouting:
    def test_deploy_static_routes_to_operations(self):
        from tools.department_hq.services.department_coordinator import (
            DepartmentCoordinator,
        )
        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        dept = coord.resolve_department("deploy_static")
        assert dept == "Operations & Infrastructure", f"Got: {dept}"

    def test_deploy_vps_routes_to_operations(self):
        from tools.department_hq.services.department_coordinator import (
            DepartmentCoordinator,
        )
        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        dept = coord.resolve_department("deploy_vps")
        assert dept == "Operations & Infrastructure", f"Got: {dept}"
```

- [ ] **Step 2: Run — expect FAIL.**

```bash
docker exec archie_platform python -m pytest \
  tests/test_deploy_service.py::TestCapabilityRouting -v 2>&1 | tail -5
```

Expected: `AssertionError: Got: Engineering & Technology` (currently unmapped)

- [ ] **Step 3: Add to CAPABILITY_DEPARTMENT_MAP in coordinator.py.**

Find the `CAPABILITY_DEPARTMENT_MAP` dict and add after the existing `Operations & Infrastructure` entries:

```python
# Operations & Infrastructure — deploy capabilities
"deploy_static": "Operations & Infrastructure",
"deploy_vps": "Operations & Infrastructure",
```

- [ ] **Step 4: Add same entries to dispatcher.py CAPABILITY_DEPARTMENT_MAP.**

```python
"deploy_static": "Operations & Infrastructure",
"deploy_vps": "Operations & Infrastructure",
```

- [ ] **Step 5: Run tests — both should pass.**

```bash
docker exec archie_platform python -m pytest \
  tests/test_deploy_service.py::TestCapabilityRouting -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit.**

```bash
git add platform_v2/tools/department_hq/services/department_coordinator.py \
        platform_v2/tools/department_hq/services/department_dispatcher.py \
        platform_v2/tests/test_deploy_service.py
git commit -m "feat(dispatcher): add deploy_static + deploy_vps to CAPABILITY_DEPARTMENT_MAP"
```

---

### Task 3: deploy_service.py — Risk Classification + Hostinger Execute

**Files:**
- Create: `platform_v2/services/deploy_service.py`

First, check what Hostinger credentials are in .env:
```bash
grep -i "hostinger\|HOSTING" /mnt/archie_brain/platform_v2/.env | head -5
```

If `HOSTINGER_API_TOKEN` (or similar) is not set, the service must raise a clear error.

- [ ] **Step 1: Add failing tests for risk classification.**

Add to `platform_v2/tests/test_deploy_service.py`:

```python
class TestRiskClassification:
    def test_json_only_is_auto(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["data/translations.json"]) == "auto"

    def test_js_only_is_auto(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["static/js/i18n.js"]) == "auto"

    def test_css_html_are_auto(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["style.css", "index.html"]) == "auto"

    def test_python_file_requires_approval(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["app.py"]) == "approval_required"

    def test_dockerfile_requires_approval(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["Dockerfile"]) == "approval_required"

    def test_mixed_files_requires_approval(self):
        from services.deploy_service import classify_risk
        # Even one risky file → approval
        assert classify_risk(["data/translations.json", "Dockerfile"]) == "approval_required"

    def test_empty_list_is_auto(self):
        from services.deploy_service import classify_risk
        assert classify_risk([]) == "auto"
```

- [ ] **Step 2: Run — expect ImportError.**

```bash
docker exec archie_platform python -m pytest \
  tests/test_deploy_service.py::TestRiskClassification -v 2>&1 | tail -5
```

Expected: `ImportError: No module named 'services.deploy_service'`

- [ ] **Step 3: Create deploy_service.py with risk classification.**

```python
"""deploy_service.py — Autonomous deploy pipeline for B.A.S.E. (agent_id=139).

Capabilities: deploy_static (Hostinger zip), deploy_vps (SSH rsync + docker rebuild).

Pipeline per deploy:
  1. classify_risk(changed_files) → 'auto' | 'approval_required'
  2. snapshot_current(domain) → backup_id   [Backup Manager]
  3. execute_deploy(capability, context)
  4. verify_deploy(verify_url, is_translation)
  5. On failure: retry once → restore snapshot → alert + Repair Bay proposal
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent_loop")

# File extensions that are safe to auto-deploy (no approval needed)
AUTO_SAFE_EXTENSIONS = frozenset([".json", ".js", ".css", ".html", ".svg", ".ico", ".txt", ".xml"])

# File names/patterns that always require approval
APPROVAL_REQUIRED_PATTERNS = frozenset([
    "dockerfile", "docker-compose", ".py", ".sql", ".sh", ".env",
])

RETRY_DELAY_SECONDS = 120
VERIFY_WAIT_SECONDS = 8

# VPS connection — credentials from .env
VPS_HOST = os.getenv("REPAIR_BAY_VPS_HOST", "kytran@76.13.107.109")
VPS_KEY = os.getenv("REPAIR_BAY_VPS_KEY", "/home/kytran/.ssh/repair_bay_deploy")

# Hostinger API
HOSTINGER_API_TOKEN = os.getenv("HOSTINGER_API_TOKEN", "")
HOSTINGER_API_BASE = "https://developers.hostinger.com/api/hosting/v1"

# VPS container service map — from KB #261506
VPS_SERVICE_MAP = {
    "kytran_gov_watch":  {"dir": "/opt/archie-products/gov-watch/",    "service": "kytran-gov-watch", "verify_path": "/static/data/translations.json"},
    "kytran_watch_api":  {"dir": "/opt/archie-products/civic-watch/",  "service": "watch-api",        "verify_path": "/data/translations.json"},
    "kytran_legal_api":  {"dir": "/opt/archie-products/legal-watch/",  "service": "legal-api",        "verify_path": "/data/translations.json"},
    "kytran_market_api": {"dir": "/opt/kytran-market-watch/",          "service": None,               "verify_path": "/static/data/translations.json"},
    "wtf_consumer":      {"dir": "/opt/archie-products/what-the-fact/","service": "wtf-consumer",     "verify_path": "/static/data/translations.json"},
    "wtf_tech":          {"dir": "/opt/archie-products/what-the-fact/","service": "wtf-tech",         "verify_path": "/static/data/translations.json"},
}

# Domain → source path for static sites
STATIC_SITE_MAP = {
    "kytranempowerment.com": "/mnt/archie_brain/website/kytranempowerment.com",
    "creed-ai.org": "/mnt/standalone/websites/creed-ai.org",
}


@dataclass
class DeployResult:
    success: bool
    domain: str
    capability: str
    http_status: Optional[int] = None
    error: Optional[str] = None
    backup_id: Optional[int] = None
    retried: bool = False
    rolled_back: bool = False
    metadata: dict = field(default_factory=dict)


def classify_risk(changed_files: list[str]) -> str:
    """Return 'auto' if all files are safe static types, else 'approval_required'."""
    for f in changed_files:
        name_lower = Path(f).name.lower()
        suffix_lower = Path(f).suffix.lower()
        if suffix_lower not in AUTO_SAFE_EXTENSIONS:
            return "approval_required"
        for pattern in APPROVAL_REQUIRED_PATTERNS:
            if pattern in name_lower:
                return "approval_required"
    return "auto"
```

- [ ] **Step 4: Run tests — all 7 should pass.**

```bash
docker exec archie_platform python -m pytest \
  tests/test_deploy_service.py::TestRiskClassification -v
```

Expected: `7 passed`

- [ ] **Step 5: Add Hostinger execute function to deploy_service.py.**

```python
def _deploy_static_hostinger(domain: str, source_path: str) -> bool:
    """Zip full source_path and deploy to Hostinger. Returns True on success."""
    import requests

    if not HOSTINGER_API_TOKEN:
        raise EnvironmentError("HOSTINGER_API_TOKEN not set in .env")

    # 1. Create zip
    ts = int(time.time())
    zip_path = f"/tmp/{domain.replace('.', '_')}_deploy_{ts}.zip"
    excludes = {".git", ".github", "*.bak*", "__pycache__"}

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        src = Path(source_path)
        for fpath in src.rglob("*"):
            if fpath.is_file():
                rel = fpath.relative_to(src)
                if not any(part.startswith(".git") for part in rel.parts):
                    zf.write(fpath, rel)

    # 2. Resolve username from Hostinger API
    headers = {"Authorization": f"Bearer {HOSTINGER_API_TOKEN}"}
    websites_resp = requests.get(f"{HOSTINGER_API_BASE}/websites", headers=headers, timeout=30)
    websites_resp.raise_for_status()
    websites = websites_resp.json().get("data", [])
    username = next((w["username"] for w in websites if w["domain"] == domain), None)
    if not username:
        raise ValueError(f"Domain {domain} not found in Hostinger account")

    # 3. Upload zip
    with open(zip_path, "rb") as f:
        upload_resp = requests.post(
            f"{HOSTINGER_API_BASE}/websites/{username}/deploy",
            headers=headers,
            files={"file": (f"{domain}_deploy_{ts}.zip", f, "application/zip")},
            timeout=120,
        )
    upload_resp.raise_for_status()

    # 4. Clean up
    try:
        os.unlink(zip_path)
    except OSError:
        pass

    return upload_resp.json().get("deploy", {}).get("status") in ("success", "accepted", "queued")
```

- [ ] **Step 6: Add VPS execute function.**

```python
def _deploy_vps(container_name: str, changed_files: list[str], source_dir: str) -> bool:
    """Rsync changed files to VPS and rebuild container. Returns True on success."""
    info = VPS_SERVICE_MAP.get(container_name)
    if not info:
        raise ValueError(f"Unknown VPS container: {container_name}. Add to VPS_SERVICE_MAP.")

    target_dir = info["dir"]
    service = info["service"]

    # 1. Rsync changed files
    for rel_path in changed_files:
        src_file = os.path.join(source_dir, rel_path)
        target_subdir = os.path.dirname(os.path.join(target_dir, rel_path))
        rsync_cmd = [
            "rsync", "-az",
            "-e", f"ssh -i {VPS_KEY} -o StrictHostKeyChecking=no -o BatchMode=yes",
            "--mkpath",
            src_file,
            f"{VPS_HOST}:{target_subdir}/",
        ]
        result = subprocess.run(rsync_cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            logger.error("[DeployVPS] rsync failed: %s", result.stderr.decode())
            return False

    # 2. Docker compose rebuild
    if service:
        rebuild_cmd = (
            f"cd {target_dir} && "
            f"docker compose up -d --build --no-deps {service}"
        )
    else:
        rebuild_cmd = f"cd {target_dir} && docker compose up -d --build"

    ssh_cmd = [
        "ssh", "-i", VPS_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        VPS_HOST,
        rebuild_cmd,
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, timeout=180)
    if result.returncode != 0:
        logger.error("[DeployVPS] docker rebuild failed: %s", result.stderr.decode())
        return False

    logger.info("[DeployVPS] %s rebuilt OK", container_name)
    return True
```

- [ ] **Step 7: Commit.**

```bash
git add platform_v2/services/deploy_service.py platform_v2/tests/test_deploy_service.py
git commit -m "feat(deploy): deploy_service — risk classification + Hostinger + VPS execute"
```

---

### Task 4: deploy_service.py — Verify + Retry + Backup Manager

**Files:**
- Modify: `platform_v2/services/deploy_service.py`

First, check Backup Manager's API for creating a file snapshot:
```bash
grep -n "def.*backup\|def.*snapshot\|def create" \
  /mnt/archie_brain/platform_v2/tools/backup_manager/routes.py 2>/dev/null | head -10
grep -rn "def.*create.*backup\|def.*snapshot" \
  /mnt/archie_brain/platform_v2/tools/backup_manager/ --include="*.py" | head -10
```

- [ ] **Step 1: Add failing tests.**

Add to `test_deploy_service.py`:

```python
from unittest.mock import MagicMock, patch


class TestVerifyDeploy:
    def test_http_200_passes(self):
        from services.deploy_service import verify_deploy
        with patch("services.deploy_service._http_get_status", return_value=200):
            with patch("services.deploy_service._count_mock_values", return_value=0):
                assert verify_deploy("https://kytranempowerment.com/", True) is True

    def test_http_404_fails(self):
        from services.deploy_service import verify_deploy
        with patch("services.deploy_service._http_get_status", return_value=404):
            assert verify_deploy("https://kytranempowerment.com/", False) is False

    def test_mock_values_present_fails(self):
        from services.deploy_service import verify_deploy
        with patch("services.deploy_service._http_get_status", return_value=200):
            with patch("services.deploy_service._count_mock_values", return_value=5):
                assert verify_deploy("https://kytranempowerment.com/data/translations.json", True) is False


class TestClassifyRiskEdgeCases:
    def test_migration_sql_requires_approval(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["database/migrations/173_foo.sql"]) == "approval_required"

    def test_sh_script_requires_approval(self):
        from services.deploy_service import classify_risk
        assert classify_risk(["scripts/deploy.sh"]) == "approval_required"
```

- [ ] **Step 2: Run — expect failures.**

```bash
docker exec archie_platform python -m pytest \
  tests/test_deploy_service.py::TestVerifyDeploy -v 2>&1 | tail -5
```

Expected: `ImportError` on `verify_deploy`

- [ ] **Step 3: Add verify + HTTP helpers to deploy_service.py.**

```python
def _http_get_status(url: str) -> int:
    """Return HTTP status code for url, or 0 on connection error."""
    try:
        import urllib.request
        resp = urllib.request.urlopen(url, timeout=10)
        return resp.status
    except Exception:
        return 0


def _count_mock_values(translations_url: str) -> int:
    """Fetch translations.json and count Mock* values. Returns 0 if unreachable."""
    try:
        import urllib.request, json
        resp = urllib.request.urlopen(translations_url, timeout=10)
        data = json.loads(resp.read())
        count = 0
        for lang, keys in data.items():
            if isinstance(keys, dict):
                count += sum(1 for v in keys.values() if str(v).startswith("Mock"))
        return count
    except Exception:
        return 0


def verify_deploy(verify_url: str, is_translation: bool) -> bool:
    """Return True if deploy succeeded: HTTP 200 + 0 Mock values (if translation)."""
    status = _http_get_status(verify_url)
    if status != 200:
        logger.warning("[DeployVerify] HTTP %d for %s", status, verify_url)
        return False
    if is_translation:
        mocks = _count_mock_values(verify_url)
        if mocks > 0:
            logger.warning("[DeployVerify] %d Mock values found at %s", mocks, verify_url)
            return False
    return True
```

- [ ] **Step 4: Add Backup Manager snapshot function.**

Check how to call Backup Manager programmatically. If no Python API exists, store a simple JSON record in knowledge_base as a pre-deploy snapshot:

```python
def snapshot_current(domain: str, verify_url: str) -> Optional[int]:
    """Fetch current live translations.json and store as KB vault_note.

    Returns knowledge_base id, or None if fetch fails.
    """
    import json as _json
    try:
        import urllib.request
        resp = urllib.request.urlopen(verify_url, timeout=10)
        content = resp.read().decode()
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO knowledge_base
                   (memory_type, title, content, category, tags, importance_score, created_at)
                   VALUES ('vault_note', %s, %s, 'deploy-snapshot',
                           ARRAY['deploy-snapshot', 'pre-deploy', %s], 0.5, NOW())
                   RETURNING id""",
                (
                    f"Pre-deploy snapshot: {domain}",
                    content,
                    domain.replace(".", "_"),
                ),
            )
            kb_id = cur.fetchone()["id"]
            logger.info("[DeploySnapshot] Stored pre-deploy snapshot kb_id=%d for %s", kb_id, domain)
            return kb_id
    except Exception:
        logger.exception("[DeploySnapshot] Failed to snapshot %s", domain)
        return None


def restore_snapshot(backup_kb_id: int, source_path: str, filename: str) -> bool:
    """Restore translations.json from KB snapshot to source_path/filename."""
    try:
        from database import get_db_cursor
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT content FROM knowledge_base WHERE id = %s",
                (backup_kb_id,),
            )
            row = cur.fetchone()
        if not row:
            logger.error("[DeployRestore] Snapshot kb_id=%d not found", backup_kb_id)
            return False
        dest = os.path.join(source_path, filename)
        with open(dest, "w") as f:
            f.write(row["content"])
        logger.info("[DeployRestore] Restored from kb_id=%d to %s", backup_kb_id, dest)
        return True
    except Exception:
        logger.exception("[DeployRestore] Failed to restore kb_id=%d", backup_kb_id)
        return False
```

- [ ] **Step 5: Add the main run_deploy_pipeline() function.**

```python
def run_deploy_pipeline(capability: str, context: dict) -> DeployResult:
    """Execute full deploy pipeline: classify → snapshot → execute → verify → retry/rollback.

    context keys:
      domain        (str) — domain name or VPS container name
      source_path   (str) — local source directory
      changed_files (list[str]) — relative paths of changed files
      verify_url    (str) — URL to verify after deploy
      is_translation (bool, optional) — if True, also check for Mock values (default False)
    """
    domain = context.get("domain", "unknown")
    source_path = context.get("source_path", "")
    changed_files = context.get("changed_files", [])
    verify_url = context.get("verify_url", "")
    is_translation = context.get("is_translation", False)

    result = DeployResult(success=False, domain=domain, capability=capability)

    # Step 1 — Risk classification
    risk = classify_risk(changed_files)
    if risk == "approval_required":
        logger.info("[DeployPipeline] %s requires Telegram approval (risky files: %s)", domain, changed_files)
        try:
            from ai_bridge.agent_loop import request_approval
            request_approval(
                action_type="cloud_throughput_escalation",
                action_data={"domain": domain, "changed_files": changed_files, "capability": capability},
                reason=f"Deploy to {domain} includes non-static files. Approve?",
                requested_by="deploy_service",
                tier=2,
            )
        except Exception:
            logger.exception("[DeployPipeline] Approval request failed for %s", domain)
        result.error = "Pending Telegram approval"
        return result

    # Step 2 — Pre-deploy backup
    if verify_url:
        result.backup_id = snapshot_current(domain, verify_url)

    # Step 3 — Execute
    def _execute() -> bool:
        if capability == "deploy_static":
            return _deploy_static_hostinger(domain, source_path)
        elif capability == "deploy_vps":
            container = context.get("container_name", domain)
            return _deploy_vps(container, changed_files, source_path)
        else:
            raise ValueError(f"Unknown deploy capability: {capability}")

    try:
        ok = _execute()
    except Exception as e:
        ok = False
        result.error = str(e)
        logger.exception("[DeployPipeline] Execute failed for %s", domain)

    # Step 4 — Verify
    if ok and verify_url:
        time.sleep(VERIFY_WAIT_SECONDS)
        ok = verify_deploy(verify_url, is_translation)
        if not ok:
            result.error = "Verification failed (HTTP or Mock values)"

    # Step 5 — Retry once on failure
    if not ok and not result.retried:
        logger.info("[DeployPipeline] Retrying %s in %ds...", domain, RETRY_DELAY_SECONDS)
        time.sleep(RETRY_DELAY_SECONDS)
        result.retried = True
        try:
            ok = _execute()
        except Exception as e:
            ok = False
            result.error = str(e)
        if ok and verify_url:
            time.sleep(VERIFY_WAIT_SECONDS)
            ok = verify_deploy(verify_url, is_translation)

    # Step 6 — On double failure: restore + alert
    if not ok:
        if result.backup_id and "translations.json" in changed_files[0] if changed_files else False:
            restore_snapshot(result.backup_id, source_path, changed_files[0])
            result.rolled_back = True
        _alert_and_propose(domain, capability, result.error or "Unknown error")
        result.success = False
        return result

    result.success = True
    result.metadata["backed_up_kb_id"] = result.backup_id
    logger.info("[DeployPipeline] ✅ %s deployed successfully", domain)
    return result


def _alert_and_propose(domain: str, capability: str, error: str) -> None:
    """Send Telegram alert and create Repair Bay failed proposal."""
    try:
        from services.telegram_service import send_system
        send_system(
            f"🚨 Deploy failed: {domain}\n"
            f"Capability: {capability}\n"
            f"Error: {error}\n"
            f"Repair Bay proposal created."
        )
    except Exception:
        logger.warning("[DeployPipeline] Telegram alert failed for %s", domain)

    try:
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO repair_proposals
                   (title, description, file_path, category, priority, status, proposed_by)
                   VALUES (%s, %s, %s, 'deploy_failure', 'high', 'proposed', 'deploy_service')
                   ON CONFLICT DO NOTHING""",
                (
                    f"Deploy failed: {domain}",
                    f"Capability {capability} failed for {domain}. Error: {error}",
                    domain,
                ),
            )
    except Exception:
        logger.warning("[DeployPipeline] Failed to create Repair Bay proposal for %s", domain)
```

**Note:** Check the exact table name for Repair Bay proposals:
```bash
docker exec archie_database psql -U archie -d archie -c "\dt" | grep -i proposal
```
Use the actual table name if different from `repair_proposals`.

- [ ] **Step 6: Run all deploy_service tests.**

```bash
docker exec archie_platform python -m pytest tests/test_deploy_service.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit.**

```bash
git add platform_v2/services/deploy_service.py platform_v2/tests/test_deploy_service.py
git commit -m "feat(deploy): verify, retry, Backup Manager snapshot, rollback, alert pipeline"
```

---

### Task 5: Wire Translation Orchestrator + Repair Bay Routes

**Files:**
- Modify: `platform_v2/tools/consciousness/translation_scanners/orchestrator.py`
- Modify: `platform_v2/tools/repair_bay/deploy_routes.py`

- [ ] **Step 1: Find the _export_bundle call in orchestrator.py.**

```bash
grep -n "_export_bundle\|EXTERNAL_SCAN_SOURCES\|website_kytran\|website_creed" \
  /mnt/archie_brain/platform_v2/tools/consciousness/translation_scanners/orchestrator.py | head -10
```

- [ ] **Step 2: Add domain map constants at top of orchestrator.py.**

Add after the existing `EXTERNAL_SCAN_SOURCES` definition:

```python
# Maps external scan source labels to their deploy context.
# Used to auto-dispatch deploy_static after bundle export.
_DEPLOY_CONTEXT_BY_LABEL: dict[str, dict] = {
    "website_kytranempowerment": {
        "domain": "kytranempowerment.com",
        "source_path": "/mnt/archie_brain/website/kytranempowerment.com",
        "changed_files": ["data/translations.json"],
        "verify_url": "https://kytranempowerment.com/data/translations.json",
        "is_translation": True,
    },
    "website_creed": {
        "domain": "creed-ai.org",
        "source_path": "/mnt/standalone/websites/creed-ai.org",
        "changed_files": ["data/translations.json"],
        "verify_url": "https://creed-ai.org/data/translations.json",
        "is_translation": True,
    },
}
```

- [ ] **Step 3: Dispatch deploy after successful bundle export in orchestrator.py.**

Find the `_export_bundle` call in `run_translation_coverage_scan()`:

```python
# Before (existing):
        try:
            count = _export_bundle(label, bundle_path)
            if count is not None:
                totals["bundles_written"] += 1
        except Exception as e:
            logger.warning("[TranslationScan] bundle export failed for %s: %s", label, e)
```

Replace with:

```python
        try:
            count = _export_bundle(label, bundle_path)
            if count is not None:
                totals["bundles_written"] += 1
                # Auto-dispatch deploy for known external sites
                if label in _DEPLOY_CONTEXT_BY_LABEL:
                    try:
                        from tools.department_hq.services.department_dispatcher import dispatch
                        deploy_ctx = _DEPLOY_CONTEXT_BY_LABEL[label]
                        deploy_ctx["reason"] = f"Translation bundle export complete for {label}"
                        dispatch(
                            capability="deploy_static",
                            context=deploy_ctx,
                            module_id="translation_scanner",
                        )
                        logger.info("[TranslationScan] deploy_static dispatched for %s", label)
                    except Exception:
                        logger.exception("[TranslationScan] deploy dispatch failed for %s", label)
        except Exception as e:
            logger.warning("[TranslationScan] bundle export failed for %s: %s", label, e)
```

- [ ] **Step 4: Update Repair Bay deploy_routes.py.**

Find `/api/deploy/execute` or equivalent route. Read it:

```bash
grep -n "def.*deploy\|@.*route\|execute" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/deploy_routes.py | head -15
```

Wrap the existing execution to use dispatch:

```python
# Add to the execute endpoint, replacing direct execution with dispatch:
from tools.department_hq.services.department_dispatcher import dispatch

result = dispatch(
    capability=payload.get("capability", "deploy_static"),
    context=payload,
    module_id="repair_bay",
)
return jsonify({"success": result.success, "result": result.metadata})
```

**Note:** Check the existing route's exact payload shape before modifying. Don't break existing callers.

- [ ] **Step 5: Restart and verify import chain.**

```bash
docker compose restart archie_platform
docker logs archie_platform --tail 20 2>&1 | grep -i "error\|import\|deploy"
```

- [ ] **Step 6: Commit.**

```bash
git add \
  platform_v2/tools/consciousness/translation_scanners/orchestrator.py \
  platform_v2/tools/repair_bay/deploy_routes.py
git commit -m "feat(deploy): wire translation orchestrator + Repair Bay routes to dispatch deploy"
```

---

### Task 6: Final Tests + PR

**Files:**
- Modify: `platform_v2/tests/test_deploy_service.py` (add integration smoke test)

- [ ] **Step 1: Add integration smoke test.**

```python
class TestDeployPipelineSmoke:
    def test_auto_risk_static_files(self):
        """Full pipeline smoke: auto-risk path should not request Telegram approval."""
        from services.deploy_service import run_deploy_pipeline
        from unittest.mock import patch, MagicMock

        mock_execute = MagicMock(return_value=True)
        mock_verify = MagicMock(return_value=True)
        mock_snapshot = MagicMock(return_value=999)

        with (
            patch("services.deploy_service._deploy_static_hostinger", mock_execute),
            patch("services.deploy_service.verify_deploy", mock_verify),
            patch("services.deploy_service.snapshot_current", mock_snapshot),
        ):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "kytranempowerment.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["data/translations.json"],
                    "verify_url": "https://kytranempowerment.com/data/translations.json",
                    "is_translation": True,
                },
            )

        assert result.success is True
        assert result.backup_id == 999
        assert result.retried is False
        assert result.rolled_back is False
        mock_execute.assert_called_once()
        mock_verify.assert_called_once()

    def test_risky_files_do_not_execute(self):
        """Dockerfile in changed_files must NOT call execute — must request approval."""
        from services.deploy_service import run_deploy_pipeline
        from unittest.mock import patch, MagicMock

        mock_execute = MagicMock()
        mock_approval = MagicMock()

        with (
            patch("services.deploy_service._deploy_static_hostinger", mock_execute),
            patch("services.deploy_service.snapshot_current", return_value=None),
            patch("ai_bridge.agent_loop.request_approval", mock_approval),
        ):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "kytranempowerment.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["Dockerfile"],
                    "verify_url": "",
                },
            )

        assert result.success is False
        assert "approval" in (result.error or "").lower()
        mock_execute.assert_not_called()

    def test_retry_on_first_failure(self):
        """On first execute failure, pipeline retries once."""
        from services.deploy_service import run_deploy_pipeline
        from unittest.mock import patch, MagicMock, call

        call_count = {"n": 0}
        def flaky_execute(*a, **kw):
            call_count["n"] += 1
            return call_count["n"] > 1  # fail first, succeed second

        with (
            patch("services.deploy_service._deploy_static_hostinger", side_effect=flaky_execute),
            patch("services.deploy_service.verify_deploy", return_value=True),
            patch("services.deploy_service.snapshot_current", return_value=None),
            patch("services.deploy_service.time.sleep"),  # skip the 120s delay
        ):
            result = run_deploy_pipeline(
                capability="deploy_static",
                context={
                    "domain": "test.com",
                    "source_path": "/tmp/fake",
                    "changed_files": ["data/translations.json"],
                    "verify_url": "https://test.com/data/translations.json",
                },
            )

        assert result.success is True
        assert result.retried is True
        assert call_count["n"] == 2
```

- [ ] **Step 2: Run full test suite.**

```bash
docker exec archie_platform python -m pytest tests/test_deploy_service.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Push and create PR.**

```bash
git add platform_v2/tests/test_deploy_service.py
git commit -m "test(deploy): integration smoke tests — auto-risk, risky gate, retry"

git push origin feat/autonomous-deploy-pipeline
gh pr create \
  --title "feat(deploy): Autonomous Deploy Pipeline — B.A.S.E. owns Hostinger + VPS deploys (Project #292)" \
  --body "## What ships
- Migration 173: deploy_static + deploy_vps skills on B.A.S.E. (agent_id=139)
- CAPABILITY_DEPARTMENT_MAP: both capabilities → Operations & Infrastructure
- services/deploy_service.py: risk check, Hostinger zip deploy, VPS SSH rsync+rebuild, verify, retry, rollback
- orchestrator.py: auto-dispatch deploy_static after _export_bundle() for KE.com + creed-ai.org
- deploy_routes.py: thin wrapper calling dispatch()

## After this PR
R.O.S.E.T.T.A. translates → B.A.S.E. deploys → zero Claude involvement.
VPS SSH key already installed (Task #2389). Telegram approval gate for risky files.

## Test
\`\`\`
docker exec archie_platform python -m pytest tests/test_deploy_service.py -v
\`\`\`" \
  --base main
```

---

## Success Criteria

- `python -m pytest tests/test_deploy_service.py -v` — all tests pass
- `classify_risk(["data/translations.json"])` → `"auto"`
- `classify_risk(["Dockerfile"])` → `"approval_required"`
- B.A.S.E. has deploy_static + deploy_vps Lv5 in agent_skills
- Translation orchestrator dispatches deploy_static after _export_bundle() for KE.com + creed-ai.org
- All deploys visible in `unified_tasks` with B.A.S.E. as agent
