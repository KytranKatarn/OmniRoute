# Compliance Auto-Remediation → Repair Bay Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the silent tier-1 compliance auto-apply path (Job #58) with a Repair Bay approval flow. Every failing rule becomes a card the admin approves via 3 buttons. Both manual click and Sunday maintenance-window paths go through a single `_safe_execute_fix` gate that snapshots pre-state, applies the fix, runs a 4-check health gate, and rolls back on failure.

**Architecture:** One new module (`compliance_safe_exec.py`) owns the safety gate. Job #58 becomes a pure enqueuer. New Job #62 is the only auto-applier, runs Sundays 03:00 EDT, caps at 5 fixes, and only picks rules explicitly flagged `auto_apply_queued=true`. Rollback coverage is limited to `sysctl`/`file_line`/`service` fix types — `command` types always require manual click.

**Tech Stack:** Python 3.11, Flask Blueprints, APScheduler, PostgreSQL 16, psycopg2, existing `run_qa_suite()` service, existing `compliance_service.apply_fix_approved()`, existing Telegram bot (`ai_bridge/agent_loop.py` helpers).

**Spec:** `docs/superpowers/specs/2026-04-11-compliance-repair-bay-approval-design.md`

**Branch:** `fix/gate-auto-remediation-job` (already active, has interim PR #34)

---

## Task 1: DB migration — `compliance_rule_auto_approvals` table

**Files:**
- Create: `database/migrations/316_compliance_rule_auto_approvals.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 316: compliance_rule_auto_approvals
-- Supports opt-in per-rule auto-apply and per-rule exemptions for
-- the Repair Bay compliance approval flow (spec 2026-04-11).

CREATE TABLE IF NOT EXISTS compliance_rule_auto_approvals (
    rule_id         VARCHAR(100) PRIMARY KEY,
    pack_id         VARCHAR(100) NOT NULL,
    status          VARCHAR(20)  NOT NULL
                    CHECK (status IN ('allow','exempt')),
    approved_by     INTEGER REFERENCES users(id),
    approved_at     TIMESTAMP DEFAULT now(),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_comp_auto_approvals_status
    ON compliance_rule_auto_approvals(status);
```

- [ ] **Step 2: Apply migration to live DB**

Run:
```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/316_compliance_rule_auto_approvals.sql
```

Expected output:
```
CREATE TABLE
CREATE INDEX
```

- [ ] **Step 3: Verify idempotency**

Run the same command a second time. Expected: no error, `NOTICE: relation "compliance_rule_auto_approvals" already exists, skipping`.

- [ ] **Step 4: Verify schema**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c "\d compliance_rule_auto_approvals"
```

Expected: 6 columns (rule_id, pack_id, status, approved_by, approved_at, notes), PK on rule_id, CHECK constraint on status, index on status.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/316_compliance_rule_auto_approvals.sql
git commit -m "feat(compliance): migration 316 — compliance_rule_auto_approvals table"
```

---

## Task 2: P.R.O.B.E. smoke suite

**Files:**
- Create: `platform_v2/qa_suites/compliance-smoke.yaml`

- [ ] **Step 1: Find existing qa_suite format**

Run:
```bash
ls platform_v2/qa_suites/ 2>/dev/null || find platform_v2 -name '*.yaml' -path '*qa*' | head -5
```

Expected: if no qa_suites dir exists, create one. Otherwise, read one existing file to match format exactly. If P.R.O.B.E. suites live elsewhere, run `grep -rn "run_qa_suite" platform_v2/services/ platform_v2/tools/ | head -5` to find the loader and adapt format.

- [ ] **Step 2: Write the suite (generic format, adapt if loader differs)**

```yaml
name: compliance-smoke
description: 15-second health canary for compliance auto-apply safety gate
owner: V.I.G.I.L.
timeout_seconds: 30
steps:
  - name: dashboard-health
    type: http_get
    url: http://localhost:3000/health
    expect_status: 200
  - name: security-network-loads
    type: http_get
    url: http://localhost:3000/tools/security-network
    expect_status: [200, 302]
    auth: admin
  - name: repair-bay-loads
    type: http_get
    url: http://localhost:3000/tools/repair-bay
    expect_status: [200, 302]
    auth: admin
  - name: dashboard-loads
    type: http_get
    url: http://localhost:3000/tools/dashboard
    expect_status: [200, 302]
    auth: admin
```

- [ ] **Step 3: Run the suite manually**

Run:
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from services.probe_service import run_qa_suite
result = run_qa_suite('compliance-smoke')
print(result)
"
```

Expected: `{'status': 'passed', ...}`. If the service name differs, grep for `def run_qa_suite` in `platform_v2/services/` and `platform_v2/tools/probe*/` to find the right entry point.

- [ ] **Step 4: If suite format was wrong, fix and re-run**

If step 3 errors, the loader rejected the format. Read one known-good suite in the repo, copy its exact structure, and adapt this suite to match.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/qa_suites/compliance-smoke.yaml
git commit -m "feat(compliance): add P.R.O.B.E. compliance-smoke suite"
```

---

## Task 3: `compliance_safe_exec.py` — snapshot + rollback helpers

**Files:**
- Create: `platform_v2/tools/security_network/compliance_safe_exec.py`

- [ ] **Step 1: Create module skeleton with imports and logger**

```python
"""Compliance safe-execution gate.

Single code path for applying any compliance fix:
  snapshot → apply → health gate → rollback on failure.

Used by both:
  - Repair Bay manual-click flow (proposal_routes.proposals_execute)
  - Sunday maintenance-window auto-apply (jobs.run_auto_apply_window)

Only fix types (sysctl, file_line, service) are supported — command
types are rejected here and must be run via the existing
compliance_service.apply_fix code path after an admin click.
"""

import hashlib
import json
import logging
import subprocess
from typing import Any, Dict, Optional, Tuple

from database import get_db_cursor

logger = logging.getLogger(__name__)

SAFE_FIX_TYPES = frozenset(("sysctl", "file_line", "service"))
HEALTH_GATE_WAIT_SECONDS = 10
COMPLIANCE_SYSCTL_CONF = "/etc/sysctl.d/99-compliance.conf"
```

- [ ] **Step 2: Write `_snapshot_sysctl`**

```python
def _snapshot_sysctl(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    """Read current sysctl value so we can restore it on rollback.

    fix_def example: {"type": "sysctl", "param": "net.ipv4.ip_forward", "value": "0"}
    """
    param = fix_def.get("param")
    if not param:
        raise ValueError(f"sysctl fix_def missing 'param': {fix_def}")

    result = subprocess.run(
        ["sysctl", "-n", param],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to read sysctl {param}: {result.stderr}")

    return {
        "fix_type": "sysctl",
        "param": param,
        "prev_value": result.stdout.strip(),
        "had_compliance_conf": _file_exists(COMPLIANCE_SYSCTL_CONF),
    }


def _file_exists(path: str) -> bool:
    import os
    return os.path.exists(path)
```

- [ ] **Step 3: Write `_snapshot_file`**

```python
def _snapshot_file(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot a file before editing so we can restore byte-exact on rollback.

    fix_def example: {"type": "file_line", "path": "/etc/ssh/sshd_config",
                      "line": "X11Forwarding no", "restart_service": "sshd"}
    """
    path = fix_def.get("path")
    if not path:
        raise ValueError(f"file_line fix_def missing 'path': {fix_def}")

    try:
        with open(path, "rb") as fh:
            content = fh.read()
        sha = hashlib.sha256(content).hexdigest()
        existed = True
    except FileNotFoundError:
        content = b""
        sha = ""
        existed = False

    return {
        "fix_type": "file_line",
        "path": path,
        "prev_content": content,
        "prev_sha256": sha,
        "existed": existed,
        "restart_service": fix_def.get("restart_service"),
    }
```

- [ ] **Step 4: Write `_snapshot_service`**

```python
def _snapshot_service(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot systemd service enabled/active state.

    fix_def example: {"type": "service", "service": "avahi-daemon",
                      "action": "disable"}
    """
    svc = fix_def.get("service")
    if not svc:
        raise ValueError(f"service fix_def missing 'service': {fix_def}")

    enabled = subprocess.run(
        ["systemctl", "is-enabled", svc],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    active = subprocess.run(
        ["systemctl", "is-active", svc],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()

    return {
        "fix_type": "service",
        "service": svc,
        "prev_enabled": enabled,
        "prev_active": active,
    }
```

- [ ] **Step 5: Write `_snapshot(fix_def)` dispatcher**

```python
def _snapshot(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    fix_type = fix_def.get("type")
    if fix_type == "sysctl":
        return _snapshot_sysctl(fix_def)
    if fix_type == "file_line":
        return _snapshot_file(fix_def)
    if fix_type == "service":
        return _snapshot_service(fix_def)
    raise ValueError(
        f"Unsupported fix_type for safe execution: {fix_type}. "
        f"Supported: {SAFE_FIX_TYPES}"
    )
```

- [ ] **Step 6: Write `_rollback_sysctl`**

```python
def _rollback_sysctl(snap: Dict[str, Any]) -> None:
    param = snap["param"]
    prev = snap["prev_value"]
    logger.warning("Rolling back sysctl %s → %s", param, prev)
    subprocess.run(
        ["sysctl", "-w", f"{param}={prev}"],
        check=True, timeout=5,
    )
    # The compliance auto-apply path writes /etc/sysctl.d/99-compliance.conf.
    # If the file did not exist before the fix, remove it so the change
    # does not persist across reboot.
    if not snap.get("had_compliance_conf") and _file_exists(COMPLIANCE_SYSCTL_CONF):
        import os
        os.remove(COMPLIANCE_SYSCTL_CONF)
        logger.warning("Removed %s", COMPLIANCE_SYSCTL_CONF)
```

- [ ] **Step 7: Write `_rollback_file`**

```python
def _rollback_file(snap: Dict[str, Any]) -> None:
    path = snap["path"]
    logger.warning("Rolling back file %s (sha=%s)", path, snap["prev_sha256"][:8])
    if not snap["existed"]:
        import os
        if _file_exists(path):
            os.remove(path)
        return
    with open(path, "wb") as fh:
        fh.write(snap["prev_content"])
    svc = snap.get("restart_service")
    if svc:
        subprocess.run(
            ["systemctl", "restart", svc],
            check=True, timeout=10,
        )
```

- [ ] **Step 8: Write `_rollback_service`**

```python
def _rollback_service(snap: Dict[str, Any]) -> None:
    svc = snap["service"]
    prev_enabled = snap["prev_enabled"]
    prev_active = snap["prev_active"]
    logger.warning(
        "Rolling back service %s → enabled=%s active=%s",
        svc, prev_enabled, prev_active,
    )
    if prev_enabled == "enabled":
        subprocess.run(["systemctl", "enable", svc], check=False, timeout=10)
    else:
        subprocess.run(["systemctl", "disable", svc], check=False, timeout=10)
    if prev_active == "active":
        subprocess.run(["systemctl", "start", svc], check=False, timeout=10)
    else:
        subprocess.run(["systemctl", "stop", svc], check=False, timeout=10)
```

- [ ] **Step 9: Write `_rollback(snap)` dispatcher**

```python
def _rollback(snap: Dict[str, Any]) -> None:
    fix_type = snap["fix_type"]
    if fix_type == "sysctl":
        return _rollback_sysctl(snap)
    if fix_type == "file_line":
        return _rollback_file(snap)
    if fix_type == "service":
        return _rollback_service(snap)
    raise ValueError(f"Cannot roll back unknown fix_type: {fix_type}")
```

- [ ] **Step 10: Commit**

```bash
git add platform_v2/tools/security_network/compliance_safe_exec.py
git commit -m "feat(compliance): safe_exec snapshot + rollback helpers"
```

---

## Task 4: `compliance_safe_exec.py` — health gate + orchestrator

**Files:**
- Modify: `platform_v2/tools/security_network/compliance_safe_exec.py` (append)

- [ ] **Step 1: Write `_count_containers`**

```python
def _count_containers() -> int:
    result = subprocess.run(
        ["docker", "ps", "-q"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker ps failed: {result.stderr}")
    return len([ln for ln in result.stdout.splitlines() if ln.strip()])
```

- [ ] **Step 2: Write `_curl_ok`**

```python
def _curl_ok(url: str, timeout: int = 5) -> bool:
    result = subprocess.run(
        ["curl", "-f", "-sS", "-m", str(timeout), url],
        capture_output=True, timeout=timeout + 2,
    )
    return result.returncode == 0


def _docker_exec_curl_ok(container: str, url: str, timeout: int = 5) -> bool:
    result = subprocess.run(
        ["docker", "exec", container, "curl", "-f", "-sS", "-m", str(timeout), url],
        capture_output=True, timeout=timeout + 5,
    )
    return result.returncode == 0
```

- [ ] **Step 3: Write `_run_probe_smoke`**

```python
def _run_probe_smoke() -> Tuple[bool, str]:
    """Run the compliance-smoke P.R.O.B.E. suite. Returns (passed, detail)."""
    try:
        from services.probe_service import run_qa_suite  # type: ignore
    except ImportError:
        # Fallback: search for the service under a different module path.
        try:
            from tools.probe.service import run_qa_suite  # type: ignore
        except ImportError:
            logger.error("run_qa_suite not importable — treating as FAIL")
            return False, "run_qa_suite import failed"

    try:
        result = run_qa_suite("compliance-smoke")
    except Exception as exc:
        logger.error("compliance-smoke suite raised: %s", exc)
        return False, f"suite error: {exc}"

    status = (result or {}).get("status", "unknown")
    return status == "passed", json.dumps(result)[:500]
```

- [ ] **Step 4: Write `_health_gate`**

```python
def _health_gate(baseline_container_count: int) -> Tuple[bool, str]:
    """All four checks must pass. Returns (ok, first_failure_detail)."""
    if not _curl_ok("http://localhost:3000/health", timeout=5):
        return False, "dashboard /health not reachable"

    current = _count_containers()
    if current != baseline_container_count:
        return False, f"container count changed: {baseline_container_count} → {current}"

    if not _docker_exec_curl_ok("archie_platform", "https://www.google.com", timeout=5):
        return False, "container → internet reachability failed (forwarding broken?)"

    probe_ok, probe_detail = _run_probe_smoke()
    if not probe_ok:
        return False, f"P.R.O.B.E. compliance-smoke failed: {probe_detail}"

    return True, "all checks green"
```

- [ ] **Step 5: Write `_load_proposal`**

```python
def _load_proposal(proposal_id: int) -> Dict[str, Any]:
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, category, status, metadata
               FROM improvement_proposals
               WHERE id = %s""",
            (proposal_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"proposal {proposal_id} not found")
        meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        return {
            "id": row["id"],
            "category": row["category"],
            "status": row["status"],
            "metadata": meta,
        }
```

- [ ] **Step 6: Write `_mark_proposal`**

```python
def _mark_proposal(proposal_id: int, status: str, note: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE improvement_proposals
               SET status = %s,
                   reviewed_at = NOW(),
                   metadata = metadata || %s::jsonb
               WHERE id = %s""",
            (status, json.dumps({"safe_exec_note": note}), proposal_id),
        )
```

- [ ] **Step 7: Write `_fire_rollback_failed_alert`**

```python
def _fire_rollback_failed_alert(rule_id: str, snap: Dict[str, Any], detail: str) -> None:
    """Best-effort Telegram alert when rollback itself fails.
    Never raises — rollback-failed is already the worst case."""
    try:
        from ai_bridge.agent_loop import _send_telegram  # type: ignore
    except ImportError:
        logger.error("Cannot import _send_telegram — %s rollback_failed: %s", rule_id, detail)
        return
    try:
        msg = (
            f"🚨 COMPLIANCE ROLLBACK FAILED\n"
            f"Rule: {rule_id}\n"
            f"Snapshot: {json.dumps({k: str(v)[:80] for k, v in snap.items()})}\n"
            f"Detail: {detail}\n\n"
            f"MANUAL INTERVENTION REQUIRED."
        )
        _send_telegram(msg)
    except Exception as exc:
        logger.error("Failed to send rollback-failed telegram: %s", exc)
```

- [ ] **Step 8: Write the orchestrator `_safe_execute_fix`**

```python
def _safe_execute_fix(proposal_id: int, user_id: int) -> Dict[str, Any]:
    """Single safety gate for compliance fixes.

    Returns: {success: bool, status: str, detail: str, proposal_id: int}
    """
    import time
    from tools.security_network import compliance_service

    proposal = _load_proposal(proposal_id)
    if proposal["category"] != "compliance_fix":
        return {"success": False, "status": "not_compliance_fix",
                "detail": f"category={proposal['category']}", "proposal_id": proposal_id}

    meta = proposal["metadata"]
    rule_id = meta.get("rule_id")
    scan_id = meta.get("scan_id")
    fix_def = meta.get("fix_def") or {}
    fix_type = fix_def.get("type")

    if fix_type not in SAFE_FIX_TYPES:
        return {
            "success": False,
            "status": "rejected",
            "detail": f"fix_type={fix_type} not in {sorted(SAFE_FIX_TYPES)}",
            "proposal_id": proposal_id,
        }

    # 1. Snapshot
    try:
        snap = _snapshot(fix_def)
    except Exception as exc:
        _mark_proposal(proposal_id, "failed", f"snapshot error: {exc}")
        return {"success": False, "status": "snapshot_failed",
                "detail": str(exc), "proposal_id": proposal_id}

    baseline_containers = _count_containers()

    # 2. Apply via existing code path
    try:
        apply_result = compliance_service.apply_fix_approved(scan_id, rule_id, user_id)
    except Exception as exc:
        logger.error("apply_fix_approved raised for %s: %s", rule_id, exc)
        apply_result = {"success": False, "error": str(exc)}

    if not apply_result.get("success"):
        _mark_proposal(proposal_id, "failed",
                       f"apply_fix_approved returned {apply_result.get('error', 'unknown')}")
        return {"success": False, "status": "apply_failed",
                "detail": apply_result.get("error", "unknown"),
                "proposal_id": proposal_id}

    # 3. Wait, then run health gate
    time.sleep(HEALTH_GATE_WAIT_SECONDS)
    ok, detail = _health_gate(baseline_containers)

    if ok:
        _mark_proposal(proposal_id, "resolved", "safe_exec green")
        return {"success": True, "status": "resolved",
                "detail": "health gate green", "proposal_id": proposal_id}

    # 4. Health failed — roll back
    logger.error("Health gate failed after applying %s: %s — rolling back", rule_id, detail)
    try:
        _rollback(snap)
    except Exception as rb_exc:
        _mark_proposal(proposal_id, "rollback_failed",
                       f"apply ok but rollback raised: {rb_exc}")
        _fire_rollback_failed_alert(rule_id, snap, f"{detail} / rollback raised: {rb_exc}")
        return {"success": False, "status": "rollback_failed",
                "detail": str(rb_exc), "proposal_id": proposal_id}

    # Rollback ran — re-check health
    time.sleep(HEALTH_GATE_WAIT_SECONDS)
    ok2, detail2 = _health_gate(baseline_containers)
    if ok2:
        _mark_proposal(proposal_id, "rolled_back", f"health gate failed ({detail}); rollback green")
        return {"success": False, "status": "rolled_back",
                "detail": detail, "proposal_id": proposal_id}

    _mark_proposal(proposal_id, "rollback_failed",
                   f"health still red after rollback: {detail2}")
    _fire_rollback_failed_alert(rule_id, snap, f"post-rollback health red: {detail2}")
    return {"success": False, "status": "rollback_failed",
            "detail": detail2, "proposal_id": proposal_id}
```

- [ ] **Step 9: Commit**

```bash
git add platform_v2/tools/security_network/compliance_safe_exec.py
git commit -m "feat(compliance): safe_exec health gate + orchestrator"
```

---

## Task 5: `compliance_service.py` additions

**Files:**
- Modify: `platform_v2/tools/security_network/compliance_service.py`

- [ ] **Step 1: Add `set_rule_auto_approval`**

Append near the other public functions (after `list_remediation_plans` around line 1462):

```python
def set_rule_auto_approval(rule_id: str, status: str, user_id: int, notes: str = "") -> Dict[str, Any]:
    """Upsert a row in compliance_rule_auto_approvals.

    status: 'allow' | 'exempt'
    """
    if status not in ("allow", "exempt"):
        return {"success": False, "error": f"invalid status: {status}"}

    # Look up pack_id from any loaded rule pack
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT p.pack_id
               FROM compliance_rule_packs p,
                    jsonb_array_elements(p.rules) r
               WHERE r->>'rule_id' = %s
               LIMIT 1""",
            (rule_id,),
        )
        row = cur.fetchone()
        pack_id = (row["pack_id"] if row else None) or "unknown"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO compliance_rule_auto_approvals
                 (rule_id, pack_id, status, approved_by, notes)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (rule_id) DO UPDATE
                 SET status = EXCLUDED.status,
                     approved_by = EXCLUDED.approved_by,
                     approved_at = NOW(),
                     notes = EXCLUDED.notes""",
            (rule_id, pack_id, status, user_id, notes),
        )
    return {"success": True, "rule_id": rule_id, "status": status}
```

- [ ] **Step 2: Add `get_rule_auto_approval`**

```python
def get_rule_auto_approval(rule_id: str) -> Optional[Dict[str, Any]]:
    """Return dict with status/approved_by/approved_at, or None if not set."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT rule_id, pack_id, status, approved_by, approved_at, notes
               FROM compliance_rule_auto_approvals
               WHERE rule_id = %s""",
            (rule_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return dict(row)
```

- [ ] **Step 3: Add `is_rule_exempt`**

```python
def is_rule_exempt(rule_id: str) -> bool:
    entry = get_rule_auto_approval(rule_id)
    return bool(entry and entry.get("status") == "exempt")


def is_rule_auto_allowed(rule_id: str) -> bool:
    entry = get_rule_auto_approval(rule_id)
    return bool(entry and entry.get("status") == "allow")
```

- [ ] **Step 4: Verify imports at top of file include `Optional`**

Run:
```bash
grep -n "from typing" platform_v2/tools/security_network/compliance_service.py | head -3
```

If `Optional` is not imported, add it: `from typing import Optional, Dict, Any`.

- [ ] **Step 5: Smoke-test the new functions inside the container**

Run:
```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from tools.security_network import compliance_service
print(compliance_service.set_rule_auto_approval('TEST-RULE-1', 'exempt', 1, 'plan test'))
print(compliance_service.get_rule_auto_approval('TEST-RULE-1'))
print('is_exempt:', compliance_service.is_rule_exempt('TEST-RULE-1'))
print(compliance_service.set_rule_auto_approval('TEST-RULE-1', 'allow', 1, ''))
print('is_allowed:', compliance_service.is_rule_auto_allowed('TEST-RULE-1'))
"
```

Expected: 4 result dicts printed, `is_exempt: True` then `is_allowed: True`.

- [ ] **Step 6: Clean up the test row**

```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM compliance_rule_auto_approvals WHERE rule_id='TEST-RULE-1';"
```

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/security_network/compliance_service.py
git commit -m "feat(compliance): rule auto-approval CRUD helpers"
```

---

## Task 6: `jobs.py` — rename Job #58 to enqueuer, add Job #62 window

**Files:**
- Modify: `platform_v2/tools/security_network/jobs.py`

- [ ] **Step 1: Replace the body of `run_auto_remediation` with enqueue logic**

Find the current `run_auto_remediation` function (currently starts at line 482 and contains the env kill-switch added earlier today plus the silent apply loop). Replace the entire function with:

```python
def run_compliance_enqueue():
    """Job #58 (renamed from run_auto_remediation 2026-04-11).

    Reads the latest compliance scan results and creates a Repair Bay
    proposal (improvement_proposals, category='compliance_fix') for every
    failing rule that is not exempt, not blocklisted, and does not already
    have an open proposal. Does NOT apply anything — apply happens only
    via explicit admin click or the Sunday window job (#62).
    """
    import json as _json
    from tools.security_network.compliance_service import (
        get_latest_scores,
        get_scan_results,
        is_rule_exempt,
        is_rule_auto_allowed,
        _is_rule_blocked,
    )
    from database import get_db_cursor
    from psycopg2.extras import Json

    try:
        scores = get_latest_scores()
        if not scores or not scores.get("scan_id"):
            return
        scan_id = scores["scan_id"]
        results = get_scan_results(scan_id, status="fail")
        if not results:
            return

        # Build rule_id → (fix_def, pack_id, risk_level, severity)
        rule_lookup = {}
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT pack_id, rules FROM compliance_rule_packs")
            for pack_row in cur.fetchall():
                rules = pack_row["rules"] if isinstance(pack_row["rules"], list) else _json.loads(pack_row["rules"])
                for rule in rules:
                    rid = rule.get("rule_id", "")
                    rule_lookup[rid] = {
                        "pack_id": pack_row["pack_id"],
                        "fix_def": rule.get("fix", {}),
                        "severity": rule.get("severity", "medium"),
                    }

        created = 0
        skipped_exempt = 0
        skipped_blocked = 0
        skipped_existing = 0
        skipped_unknown = 0

        SAFE_TYPES = {"sysctl", "file_line", "service"}

        with get_db_cursor(commit=True) as (conn, cur):
            for result in results:
                rule_id = result.get("rule_id", "")
                if not rule_id:
                    continue

                if is_rule_exempt(rule_id):
                    skipped_exempt += 1
                    continue

                blocked, _bl = _is_rule_blocked(rule_id)
                if blocked:
                    skipped_blocked += 1
                    continue  # Job #61 handles blocklisted rules via F.O.R.G.E. plan

                lookup = rule_lookup.get(rule_id)
                if not lookup:
                    skipped_unknown += 1
                    continue

                # Dedupe: skip if an open proposal already exists for this rule
                cur.execute(
                    """SELECT 1 FROM improvement_proposals
                       WHERE category = 'compliance_fix'
                         AND status = 'pending_approval'
                         AND metadata->>'rule_id' = %s
                       LIMIT 1""",
                    (rule_id,),
                )
                if cur.fetchone():
                    skipped_existing += 1
                    continue

                fix_def = lookup["fix_def"]
                fix_type = fix_def.get("type")
                auto_queued = (
                    is_rule_auto_allowed(rule_id)
                    and fix_type in SAFE_TYPES
                )

                metadata = {
                    "source": "compliance_enqueue",
                    "scan_id": scan_id,
                    "rule_id": rule_id,
                    "pack_id": lookup["pack_id"],
                    "fix_def": fix_def,
                    "fix_type": fix_type,
                    "severity": lookup["severity"],
                    "auto_apply_queued": auto_queued,
                }

                cur.execute(
                    """INSERT INTO improvement_proposals
                           (title, description, category, priority, status,
                            risk_level, metadata, proposed_at)
                       VALUES (%s, %s, 'compliance_fix', %s, 'pending_approval',
                               %s, %s, NOW())""",
                    (
                        f"Compliance fix pending: {rule_id}",
                        f"Compliance rule {rule_id} failed in scan {scan_id}. "
                        f"Approve in Repair Bay (fix_type={fix_type}).",
                        lookup["severity"],
                        lookup["severity"],
                        Json(metadata),
                    ),
                )
                created += 1

        logger.info(
            "compliance_enqueue: created=%d skipped_existing=%d "
            "skipped_exempt=%d skipped_blocked=%d skipped_unknown=%d",
            created, skipped_existing, skipped_exempt, skipped_blocked, skipped_unknown,
        )
    except Exception as exc:
        logger.error("compliance_enqueue failed: %s", exc)


# Compatibility alias — keep old name bound so any existing scheduler
# registration or external reference still works during the transition.
run_auto_remediation = run_compliance_enqueue
```

- [ ] **Step 2: Add the Sunday window job `run_auto_apply_window`**

Add this below `run_compliance_enqueue`:

```python
def run_auto_apply_window():
    """Job #62 — Sunday 03:00 EDT compliance auto-apply window.

    Picks up to 5 compliance_fix proposals where
    metadata.auto_apply_queued=true, re-verifies fix_type is in the safe
    set, and runs each through compliance_safe_exec._safe_execute_fix.
    Sends a Telegram digest at the end.
    """
    import datetime as _dt
    from database import get_db_cursor
    from tools.security_network.compliance_safe_exec import (
        _safe_execute_fix,
        SAFE_FIX_TYPES,
    )

    try:
        from ai_bridge.agent_loop import _send_telegram  # type: ignore
    except ImportError:
        def _send_telegram(msg):  # type: ignore
            logger.info("TELEGRAM (no sender): %s", msg)

    max_fixes = 5
    picked: list = []

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT id, metadata
                   FROM improvement_proposals
                   WHERE category = 'compliance_fix'
                     AND status = 'pending_approval'
                     AND (metadata->>'auto_apply_queued')::boolean IS TRUE
                   ORDER BY proposed_at ASC
                   LIMIT %s""",
                (max_fixes,),
            )
            rows = cur.fetchall()

        for row in rows:
            meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
            fix_type = (meta.get("fix_def") or {}).get("type")
            if fix_type not in SAFE_FIX_TYPES:
                logger.info(
                    "auto_apply_window: skipping proposal %s — fix_type=%s ineligible",
                    row["id"], fix_type,
                )
                continue
            picked.append(row["id"])

        results = []
        for pid in picked:
            try:
                r = _safe_execute_fix(pid, user_id=0)
            except Exception as exc:
                r = {"success": False, "status": "error", "detail": str(exc), "proposal_id": pid}
            results.append(r)

        # Digest
        total = len(results)
        ok = sum(1 for r in results if r.get("success"))
        failed = total - ok
        if total == 0:
            msg = f"🛠 Compliance window {_dt.datetime.now():%Y-%m-%d %H:%M}: no auto-queued fixes."
        else:
            detail_lines = [
                f"  • {r.get('status','?')} — proposal #{r.get('proposal_id')}: {r.get('detail','')[:80]}"
                for r in results
            ]
            msg = (
                f"🛠 Compliance window {_dt.datetime.now():%Y-%m-%d %H:%M}\n"
                f"Applied: {ok}/{total} | Failed: {failed}\n"
                + "\n".join(detail_lines)
            )
        _send_telegram(msg)
        logger.info("auto_apply_window summary: %s", msg.replace("\n", " | "))
    except Exception as exc:
        logger.error("auto_apply_window failed: %s", exc)
```

- [ ] **Step 3: Register Job #62 with the scheduler**

In `register_security_jobs` (near line 1664 where Job #58 is registered), add right after the existing Job #58 block:

```python
    # --- Sunday maintenance-window auto-apply (Job #62, 2026-04-11) ---
    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        with_ctx(run_auto_apply_window),
        trigger=CronTrigger(
            day_of_week="sun", hour=3, minute=0, timezone="America/Toronto"
        ),
        id="agent_compliance_auto_apply_window",
        name="Agent Loop: Compliance Auto-Apply Window",
        replace_existing=True,
        misfire_grace_time=900,  # 15-minute grace
    )
```

Also update the comment header around line 15 from `run_auto_remediation (Job #58, every 6h)` to
`run_compliance_enqueue (Job #58, every 6h) + run_auto_apply_window (Job #62, Sun 03:00 EDT)`.

- [ ] **Step 4: Restart platform and verify jobs registered**

```bash
docker compose restart archie_platform
sleep 10
docker logs archie_platform 2>&1 | grep -E "compliance_enqueue|auto_apply_window|Job #58|Job #62" | tail -10
```

Expected: no stacktraces, and on the next 6h boundary the `compliance_enqueue` job fires. If not visible immediately, manually invoke:

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from tools.security_network.jobs import run_compliance_enqueue, run_auto_apply_window
run_compliance_enqueue()
print('enqueue OK')
run_auto_apply_window()
print('window OK')
"
```

Expected: both print OK, no exceptions.

- [ ] **Step 5: Verify proposals were created**

```bash
docker exec archie_database psql -U archie -d archie -c \
"SELECT id, LEFT(title,50), metadata->>'rule_id' AS rule, metadata->>'fix_type' AS fix_type, metadata->>'auto_apply_queued' AS auto FROM improvement_proposals WHERE category='compliance_fix' AND status='pending_approval' ORDER BY id DESC LIMIT 5;"
```

Expected: a few rows with rule_id set, fix_type populated, and `auto='false'` for all (since nobody has run `apply_and_allow` yet).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/security_network/jobs.py
git commit -m "feat(compliance): Job #58 → enqueuer, Job #62 auto-apply window"
```

---

## Task 7: Proposal routes — wire execute + `/compliance-action`

**Files:**
- Modify: `platform_v2/tools/repair_bay/proposal_routes.py`

- [ ] **Step 1: Read the existing `proposals_execute` implementation**

Run:
```bash
sed -n '78,110p' platform_v2/tools/repair_bay/proposal_routes.py
```

Note the current behavior so the compliance branch preserves it for non-compliance categories.

- [ ] **Step 2: Branch `proposals_execute` on category**

Replace the body of `proposals_execute(proposal_id)` with:

```python
    @bp.route("/api/proposals/<int:proposal_id>/execute", methods=["POST"])
    @login_required
    @admin_required
    def proposals_execute(proposal_id):
        from database import get_db_cursor
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT category FROM improvement_proposals WHERE id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "not found"}), 404

        category = row["category"] if isinstance(row, dict) else row[0]

        if category == "compliance_fix":
            from tools.security_network.compliance_safe_exec import _safe_execute_fix
            result = _safe_execute_fix(proposal_id, user_id=current_user.id)
            status_code = 200 if result.get("success") else 500
            return jsonify(result), status_code

        # Existing non-compliance path — preserve current behavior.
        # (Copy the original body below this line verbatim.)
        return _legacy_proposal_execute(proposal_id)
```

Extract the original body of `proposals_execute` into a private helper function `_legacy_proposal_execute(proposal_id)` at module level (just above the `register_proposal_routes` definition) so the compliance branch and the legacy branch do not interfere.

- [ ] **Step 3: Add the new `/compliance-action` endpoint**

Inside `register_proposal_routes` (same scope as `proposals_execute`), add:

```python
    @bp.route("/api/proposals/<int:proposal_id>/compliance-action", methods=["POST"])
    @login_required
    @admin_required
    def proposals_compliance_action(proposal_id):
        """Handle the three Repair Bay compliance card buttons.

        Body: {"action": "apply_once" | "apply_and_allow" | "exempt"}
        """
        from database import get_db_cursor
        from tools.security_network import compliance_service
        from tools.security_network.compliance_safe_exec import _safe_execute_fix

        action = (request.get_json(silent=True) or {}).get("action")
        if action not in ("apply_once", "apply_and_allow", "exempt"):
            return jsonify({"success": False, "error": "bad action"}), 400

        # Load rule_id from proposal metadata
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT category, metadata FROM improvement_proposals
                   WHERE id = %s""",
                (proposal_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "not found"}), 404
        if (row["category"] if isinstance(row, dict) else row[0]) != "compliance_fix":
            return jsonify({"success": False, "error": "not a compliance_fix proposal"}), 400

        meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
        rule_id = meta.get("rule_id")
        if not rule_id:
            return jsonify({"success": False, "error": "proposal missing rule_id"}), 500

        if action == "exempt":
            compliance_service.set_rule_auto_approval(rule_id, "exempt", current_user.id, "exempted from Repair Bay card")
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE improvement_proposals
                       SET status = 'resolved',
                           reviewed_at = NOW(),
                           metadata = metadata || '{"resolved_by":"exempt"}'::jsonb
                       WHERE id = %s""",
                    (proposal_id,),
                )
            return jsonify({"success": True, "action": "exempt", "rule_id": rule_id})

        if action == "apply_and_allow":
            compliance_service.set_rule_auto_approval(rule_id, "allow", current_user.id, "approved via Repair Bay")

        # apply_once and apply_and_allow both run the fix now
        result = _safe_execute_fix(proposal_id, user_id=current_user.id)
        result["action"] = action
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code
```

- [ ] **Step 4: Verify the imports at the top of the file include `request`, `jsonify`, `current_user`**

Run:
```bash
head -30 platform_v2/tools/repair_bay/proposal_routes.py
```

If any are missing, add:
```python
from flask import request, jsonify
from flask_login import current_user, login_required
```

- [ ] **Step 5: Restart and smoke-test with curl**

```bash
docker compose restart archie_platform
sleep 8
curl -sS -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" \
  -d '{"action":"exempt"}' \
  http://localhost:3000/api/proposals/1/compliance-action
```

Expected: `302` (redirect to login — endpoint exists, auth works) or `404/400` if proposal id 1 is not a compliance_fix. Either proves the route registered. 500 means a stacktrace — check `docker logs archie_platform --tail 30`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/repair_bay/proposal_routes.py
git commit -m "feat(compliance): proposal routes — safe_exec branch + compliance-action"
```

---

## Task 8: Frontend — 3 buttons on the compliance card modal

**Files:**
- Modify: `platform_v2/static/js/security-network-app.js`

- [ ] **Step 1: Find the current compliance-card modal renderer**

Run:
```bash
grep -n "compliance\|Plan Generated\|plan_id" platform_v2/static/js/security-network-app.js | head -20
```

Identify the function that renders the compliance-rule modal (likely `renderComplianceRuleModal` or similar near line 4647 where the "Plan Generated" button lives).

- [ ] **Step 2: Add the 3-button row inside that modal's footer**

Inside the render function, after the existing "Ask F.O.R.G.E. for a Custom Plan" button, add:

```javascript
// Repair Bay action buttons (2026-04-11 Repair Bay approval flow)
if (ruleData.proposal_id) {
  const actions = document.createElement('div');
  actions.className = 'sn-compliance-actions';
  actions.style.cssText = 'display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;';

  const mkBtn = (label, action, accent) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = 'lcars-btn';
    b.style.cssText = `background:${accent};color:#000;font-weight:600;padding:8px 14px;border:none;border-radius:4px;cursor:pointer;`;
    b.onclick = async () => {
      b.disabled = true;
      b.textContent = '...';
      try {
        const resp = await fetch(`/api/proposals/${ruleData.proposal_id}/compliance-action`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({action}),
        });
        const data = await resp.json();
        if (data.success) {
          b.textContent = '✓ ' + (data.action || action);
          b.style.background = '#22d3ee';
          setTimeout(() => window.location.reload(), 1500);
        } else {
          b.textContent = '✗ ' + (data.status || 'failed');
          b.style.background = '#ef4444';
          console.error('compliance-action failed:', data);
        }
      } catch (e) {
        b.textContent = '✗ error';
        b.style.background = '#ef4444';
        console.error(e);
      }
    };
    return b;
  };

  actions.appendChild(mkBtn('Apply Once', 'apply_once', '#fbbf24'));
  actions.appendChild(mkBtn('Apply + Always Allow', 'apply_and_allow', '#10b981'));
  actions.appendChild(mkBtn('Dismiss (Mark Exempt)', 'exempt', '#8b5cf6'));

  // Append to whatever the modal footer element is (likely `footer` or `bmFooter`)
  (footer || document.querySelector('.bm-footer')).appendChild(actions);
}
```

**Note to implementer:** `ruleData` and `footer` are placeholder names for whatever variables the existing render function uses. Preserve the existing variable names from the surrounding code — the contract is: render 3 buttons that POST to `/api/proposals/<id>/compliance-action`.

- [ ] **Step 3: Ensure the modal renderer receives `proposal_id`**

Backend must include it in the payload used by this modal. Grep for the compliance-rule detail endpoint:

```bash
grep -n "compliance.*rule\|rule_detail\|compliance_modal" platform_v2/tools/security_network/compliance_routes.py | head
```

If the current endpoint does not return the proposal_id for a given rule_id, add a subquery:

```python
# In the rule-detail route (or wherever the modal data is assembled):
cur.execute(
    """SELECT id FROM improvement_proposals
       WHERE category = 'compliance_fix'
         AND status = 'pending_approval'
         AND metadata->>'rule_id' = %s
       ORDER BY proposed_at DESC LIMIT 1""",
    (rule_id,),
)
pr_row = cur.fetchone()
rule_data["proposal_id"] = (pr_row[0] if pr_row else None)
```

- [ ] **Step 4: Restart + browser-verify**

```bash
docker compose restart archie_platform
```

Then in a browser at `http://192.168.1.200:3000/tools/security-network`:
1. Open the compliance tab
2. Click a failing rule
3. Confirm the 3 buttons appear in the modal
4. Click "Dismiss (Mark Exempt)" on a non-critical rule (e.g. V-238202 if it's failing) and verify the card is gone on next scan

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/security-network-app.js platform_v2/tools/security_network/compliance_routes.py
git commit -m "feat(compliance): Repair Bay action buttons on compliance card modal"
```

---

## Task 9: Remove env kill-switch + final verification

**Files:**
- Modify: `platform_v2/tools/security_network/jobs.py`

- [ ] **Step 1: Verify env gate is already gone**

The kill-switch lived in the original `run_auto_remediation` body replaced in Task 6 step 1. Double-check:

```bash
grep -n "COMPLIANCE_AUTO_REMEDIATION_ENABLED" platform_v2/tools/security_network/jobs.py
```

Expected: no output. If any remain, delete them.

- [ ] **Step 2: Search whole repo for stale references**

```bash
grep -rn "COMPLIANCE_AUTO_REMEDIATION_ENABLED" --include='*.py' . 2>/dev/null
```

Expected: no output (except possibly the spec/plan docs — those are fine).

- [ ] **Step 3: End-to-end green-path verification**

Run a real compliance-fix flow against a harmless sysctl rule (`CIS-3.1.2` — `net.ipv4.conf.all.send_redirects=0`). Do this in two steps: (a) create a test proposal, (b) execute it.

```bash
# (a) Find the current scan_id and manually enqueue CIS-3.1.2 as a proposal
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from tools.security_network.jobs import run_compliance_enqueue
run_compliance_enqueue()
"
docker exec archie_database psql -U archie -d archie -c \
"SELECT id FROM improvement_proposals WHERE category='compliance_fix' AND status='pending_approval' AND metadata->>'rule_id'='CIS-3.1.2' ORDER BY id DESC LIMIT 1;"
```

Note the returned `id` as `<PID>`.

```bash
# (b) Execute it via the safe_exec orchestrator
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from tools.security_network.compliance_safe_exec import _safe_execute_fix
r = _safe_execute_fix(<PID>, user_id=1)
print(r)
"
```

Expected:
```python
{'success': True, 'status': 'resolved', 'detail': 'health gate green', 'proposal_id': <PID>}
```

Verify the sysctl actually changed:
```bash
sudo sysctl -n net.ipv4.conf.all.send_redirects
```
Expected: `0`.

- [ ] **Step 4: Rollback-path verification**

Temporarily force the health gate to fail. Add this env var to the platform container:

```bash
docker exec archie_platform bash -c "export FORCE_HEALTH_GATE_FAIL=1"
```

*Alternative — inject the failure directly in a python REPL without restarting:*

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/platform_v2')
from tools.security_network import compliance_safe_exec as se
# Monkey-patch the health gate for a one-shot rollback test
orig = se._health_gate
se._health_gate = lambda _b: (False, 'forced-fail-for-test')

# Reset sysctl to 1 first so the fix has something to change
import subprocess
subprocess.run(['sysctl', '-w', 'net.ipv4.conf.all.send_redirects=1'], check=True)

# Pick a fresh pending CIS-3.1.2 proposal or create one
from database import get_db_cursor
with get_db_cursor(commit=False) as (conn, cur):
    cur.execute(\"SELECT id FROM improvement_proposals WHERE category='compliance_fix' AND status='pending_approval' AND metadata->>'rule_id'='CIS-3.1.2' ORDER BY id DESC LIMIT 1\")
    row = cur.fetchone()
pid = row['id'] if row else None
print('testing rollback on proposal', pid)
print(se._safe_execute_fix(pid, user_id=1))
se._health_gate = orig  # restore
"
```

Expected result dict: `{'success': False, 'status': 'rolled_back', ...}`.

Verify sysctl was restored:
```bash
sudo sysctl -n net.ipv4.conf.all.send_redirects
```
Expected: `1` (the pre-fix value).

- [ ] **Step 5: Commit the cleanup**

```bash
git add -u
git commit --allow-empty -m "test(compliance): verify end-to-end green + rollback paths"
```

(Empty commit is a tag point for the verification — nothing new to stage here unless step 1/2 found a stale reference.)

- [ ] **Step 6: Push branch and update PR #34**

```bash
git push origin fix/gate-auto-remediation-job
gh pr edit 34 --title "fix(compliance): Repair Bay approval flow for auto-remediation" \
  --body-file /dev/stdin <<'EOF'
## Summary
Replaces the interim env kill-switch with a full Repair Bay approval flow for compliance auto-remediation.

- Every failing compliance rule is enqueued as an improvement_proposal (`category='compliance_fix'`) by Job #58 (renamed `run_compliance_enqueue`). No silent apply.
- Admin approves in Repair Bay via 3 buttons: `Apply once`, `Apply + always allow`, `Dismiss (mark exempt)`.
- New Job #62 `run_auto_apply_window` fires Sundays 03:00 EDT, processes up to 5 rules previously flagged `apply_and_allow`, restricted to `sysctl`/`file_line`/`service` fix types.
- Both entry points route through `compliance_safe_exec._safe_execute_fix`: snapshot → apply → 4-check health gate (dashboard / container count / container→internet / P.R.O.B.E. `compliance-smoke`) → rollback on failure.
- Rollback-failed scenarios fire an immediate Telegram alert.
- `COMPLIANCE_AUTO_REMEDIATION_ENABLED` env kill-switch removed.

## Spec + Plan
- Spec: `docs/superpowers/specs/2026-04-11-compliance-repair-bay-approval-design.md`
- Plan: `docs/superpowers/plans/2026-04-11-compliance-repair-bay-approval.md`

## Test plan
- [x] Migration 316 applies idempotently
- [x] Green path: CIS-3.1.2 apply → health green → proposal resolved → sysctl changed
- [x] Rollback path: forced health-gate fail → rollback → sysctl restored → proposal rolled_back
- [ ] Manual Repair Bay UI click for each of the 3 buttons
- [ ] Sunday window job runs in dry-run at an arbitrary time (manual invocation)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 7: Sanity-check remaining acceptance criteria from the spec**

Walk §9 of the spec file and tick off each box in the PR description as you confirm it. Any unchecked items become a follow-up task.

---

## Self-review checklist (run before handing off)

1. **Spec coverage** — every item in spec §9 mapped to a task? ✓ (Tasks 1-9 cover all 8 criteria)
2. **Placeholders** — no TBD/TODO in any step. One callout in Task 8 step 2 where `ruleData` / `footer` names depend on existing code; the implementer is instructed to preserve existing variable names, which is a legitimate integration constraint, not a placeholder.
3. **Type consistency** — `_safe_execute_fix` signature and return shape is consistent across Tasks 4/6/7. Table name `compliance_rule_auto_approvals` is consistent across Tasks 1/5/6/7. Function names `set_rule_auto_approval` / `get_rule_auto_approval` / `is_rule_exempt` / `is_rule_auto_allowed` consistent Tasks 5/6/7.
4. **Rollback test coverage** — Task 9 step 4 exercises the `rolled_back` path but not `rollback_failed`. Rationale: the latter requires failing rollback itself, which on a real system would cost real damage to verify. Leaving that path covered only by logs + a Telegram alert contract, which is acceptable for v1.
