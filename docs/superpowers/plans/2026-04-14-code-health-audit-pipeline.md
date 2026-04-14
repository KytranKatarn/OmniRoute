# Code Health Audit Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken weekly-only, Python-only audit system with an event-driven, profile-aware audit pipeline routed through Department HQ dispatch, covering all modules, standalone products, and websites.

**Architecture:** Three audit profiles (Python, Web, Config) auto-detected from module file composition. Three trigger sources (change detection, manual, scheduled) all route through Department HQ dispatch to F.O.R.G.E. agent. Results write to existing `code_audit_log` table with new profile/trigger columns.

**Tech Stack:** Python (Flask), JavaScript (Chart.js), PostgreSQL, Department HQ Bridge Dispatcher

**Spec:** `docs/superpowers/specs/2026-04-14-code-health-audit-pipeline-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `database/migrations/250_audit_pipeline_columns.sql` | Add `audit_profile`, `trigger_reason`, `dispatched_via` to `code_audit_log`; add `modules_changed` to `code_metrics_snapshots` |
| `platform_v2/services/code_metrics_service.py` | Profile detection, web/config audit checks, change detection in `save_snapshot()`, enhanced `audit_single_module()` |
| `platform_v2/tools/consciousness/code_health_routes.py` | New `POST /api/code-health/audit` endpoint |
| `platform_v2/tools/department_hq/jobs.py` | Update Job #40 (change detection + audit queue), Job #58 (stale re-audit) |
| `platform_v2/static/js/consciousness.js` | Audit buttons, click-to-audit, profile badges, trigger/profile columns |
| `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` | Audit button elements |

---

### Task 1: Database Migration — New Audit Columns

**Files:**
- Create: `database/migrations/250_audit_pipeline_columns.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 250_audit_pipeline_columns.sql
-- Add audit profile, trigger reason, and dispatcher tracking to code_audit_log
-- Add change detection to snapshots

ALTER TABLE code_audit_log
    ADD COLUMN IF NOT EXISTS audit_profile VARCHAR(20) DEFAULT 'python',
    ADD COLUMN IF NOT EXISTS trigger_reason VARCHAR(30) DEFAULT 'scheduled',
    ADD COLUMN IF NOT EXISTS dispatched_via VARCHAR(50);

COMMENT ON COLUMN code_audit_log.audit_profile IS 'python, web, or config — auto-detected from module file composition';
COMMENT ON COLUMN code_audit_log.trigger_reason IS 'change_detected, manual, scheduled, stale_reaudit';
COMMENT ON COLUMN code_audit_log.dispatched_via IS 'Agent name that ran the audit (e.g. F.O.R.G.E.)';

ALTER TABLE code_metrics_snapshots
    ADD COLUMN IF NOT EXISTS modules_changed JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN code_metrics_snapshots.modules_changed IS 'List of module keys that changed vs previous snapshot';
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/250_audit_pipeline_columns.sql
```

Expected: `ALTER TABLE` x3 and `COMMENT` x4 — no errors.

- [ ] **Step 3: Verify columns exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\d code_audit_log" | grep -E "audit_profile|trigger_reason|dispatched_via"
docker exec archie_database psql -U archie -d archie -c "\d code_metrics_snapshots" | grep modules_changed
```

Expected: All 4 new columns visible.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/250_audit_pipeline_columns.sql
git commit -m "feat: add audit pipeline columns (profile, trigger, dispatcher, changes)"
```

---

### Task 2: Audit Profile Detection + Web/Config Checkers

**Files:**
- Modify: `platform_v2/services/code_metrics_service.py`

- [ ] **Step 1: Add profile detection function**

Add after the `_SCAN_CACHE_TTL` constant (around line 42):

```python
# ── Audit Profile System ──────────────────────────────────────────────
AUDIT_PROFILES = {
    "python": {
        "checks": [
            "SQL_INJECTION", "HARDCODED_SECRET", "DIRECT_OLLAMA", "DIRECT_CLOUD",
            "BARE_EXCEPT", "LARGE_FILE", "MISSING_INIT", "IMPORT_VIOLATION",
        ],
    },
    "web": {
        "checks": [
            "HARDCODED_SECRET", "INLINE_SCRIPT", "CONSOLE_LOG",
            "LARGE_FILE", "TODO_FIXME", "MIXED_CONCERNS",
        ],
    },
    "config": {
        "checks": [
            "HARDCODED_SECRET", "INSECURE_DEFAULT", "LATEST_TAG",
            "MISSING_RESOURCE_LIMIT",
        ],
    },
}

# Severity classification for all check codes
SEVERITY_MAP = {
    # Red (security)
    "SQL_INJECTION": "red", "HARDCODED_SECRET": "red",
    "DIRECT_OLLAMA": "red", "DIRECT_CLOUD": "red", "INSECURE_DEFAULT": "red",
    # Yellow (quality)
    "BARE_EXCEPT": "yellow", "LARGE_FILE": "yellow", "MISSING_INIT": "yellow",
    "INLINE_SCRIPT": "yellow", "CONSOLE_LOG": "yellow",
    "LATEST_TAG": "yellow", "MISSING_RESOURCE_LIMIT": "yellow",
    # Info
    "TODO_FIXME": "info", "MIXED_CONCERNS": "info", "IMPORT_VIOLATION": "info",
}


def detect_audit_profile(module_data):
    """Auto-detect audit profile from module's file type composition.

    Returns 'python', 'web', or 'config' based on 60% threshold.
    Defaults to 'python' for mixed or empty modules.
    """
    by_type = module_data.get("by_type", {})
    total = sum(v.get("lines", 0) for v in by_type.values())
    if total == 0:
        return "python"
    web_lines = sum(by_type.get(t, {}).get("lines", 0) for t in ["js", "html", "css", "svg"])
    config_lines = sum(by_type.get(t, {}).get("lines", 0) for t in ["yaml", "config"])
    if config_lines / total >= 0.6:
        return "config"
    if web_lines / total >= 0.6:
        return "web"
    return "python"
```

- [ ] **Step 2: Add web audit checker**

Add after `detect_audit_profile()`:

```python
import re

# Patterns for secret detection (shared across profiles)
_SECRET_PATTERNS = [
    re.compile(r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']', re.IGNORECASE),
    re.compile(r'(?:api_key|apikey|api_token|secret_key|auth_token)\s*=\s*["\'][^"\']{8,}["\']', re.IGNORECASE),
    re.compile(r'(?:sk-|pk_live_|sk_live_|ghp_|gho_|glpat-)[a-zA-Z0-9]{10,}'),
]


def _check_secrets_in_file(filepath):
    """Check a single file for hardcoded secrets. Returns list of issue dicts."""
    issues = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for lineno, line in enumerate(f, 1):
                for pat in _SECRET_PATTERNS:
                    if pat.search(line):
                        issues.append({
                            "code": "HARDCODED_SECRET",
                            "file": filepath,
                            "line": lineno,
                            "detail": "Possible hardcoded secret detected",
                        })
                        break  # one finding per line is enough
    except Exception:
        pass
    return issues


def audit_module_web(module_path):
    """Run web-profile audit checks on a module directory.

    Checks: HARDCODED_SECRET, INLINE_SCRIPT, CONSOLE_LOG, LARGE_FILE, TODO_FIXME, MIXED_CONCERNS
    Returns: (issues_found, notes, issues_list)
    """
    issues = []
    todo_count = 0

    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".js", ".mjs", ".html", ".css", ".svg", ".json"):
                continue
            filepath = os.path.join(root, fname)
            lines = _count_lines(filepath)

            # LARGE_FILE
            if lines > 600:
                issues.append({"code": "LARGE_FILE", "file": filepath, "detail": f"{lines} lines"})

            # HARDCODED_SECRET
            issues.extend(_check_secrets_in_file(filepath))

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            # CONSOLE_LOG (JS files only)
            if ext in (".js", ".mjs"):
                for i, line in enumerate(content.splitlines(), 1):
                    if "console.log(" in line and not line.strip().startswith("//"):
                        issues.append({"code": "CONSOLE_LOG", "file": filepath, "line": i, "detail": line.strip()[:80]})

            # INLINE_SCRIPT (HTML files only)
            if ext == ".html":
                script_blocks = re.findall(r"<script[^>]*>(.+?)</script>", content, re.DOTALL)
                for block in script_blocks:
                    stripped = block.strip()
                    # Skip empty or src-only script tags; flag blocks with >5 lines of logic
                    if stripped and len(stripped.splitlines()) > 5:
                        issues.append({"code": "INLINE_SCRIPT", "file": filepath, "detail": f"{len(stripped.splitlines())} lines of inline JS"})

            # TODO_FIXME (all files)
            for i, line in enumerate(content.splitlines(), 1):
                if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line):
                    todo_count += 1

    if todo_count > 0:
        issues.append({"code": "TODO_FIXME", "file": module_path, "detail": f"{todo_count} TODO/FIXME comments"})

    notes_parts = [f"{i['code']}: {i.get('detail', '')}" for i in issues[:20]]
    notes = "; ".join(notes_parts) if notes_parts else "clean"
    return len(issues), notes, issues


def audit_module_config(module_path):
    """Run config-profile audit checks on a module directory.

    Checks: HARDCODED_SECRET, INSECURE_DEFAULT, LATEST_TAG, MISSING_RESOURCE_LIMIT
    Returns: (issues_found, notes, issues_list)
    """
    issues = []

    for root, dirs, files in os.walk(module_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".yaml", ".yml", ".toml", ".ini", ".conf", ".xml", ".json"):
                continue
            filepath = os.path.join(root, fname)

            # HARDCODED_SECRET
            issues.extend(_check_secrets_in_file(filepath))

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            # Docker-specific checks
            if fname in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml") or "docker" in fname.lower():
                # LATEST_TAG
                for i, line in enumerate(content.splitlines(), 1):
                    if re.search(r"image:\s*\S+:latest\b", line):
                        issues.append({"code": "LATEST_TAG", "file": filepath, "line": i, "detail": line.strip()[:80]})

                # INSECURE_DEFAULT
                if "privileged: true" in content:
                    issues.append({"code": "INSECURE_DEFAULT", "file": filepath, "detail": "privileged: true"})
                if "read_only: false" in content:
                    issues.append({"code": "INSECURE_DEFAULT", "file": filepath, "detail": "read_only: false"})

                # MISSING_RESOURCE_LIMIT — check services that have no mem_limit or deploy.resources
                if "services:" in content and "mem_limit" not in content and "resources:" not in content:
                    issues.append({"code": "MISSING_RESOURCE_LIMIT", "file": filepath, "detail": "No memory limits defined"})

    notes_parts = [f"{i['code']}: {i.get('detail', '')}" for i in issues[:20]]
    notes = "; ".join(notes_parts) if notes_parts else "clean"
    return len(issues), notes, issues
```

- [ ] **Step 3: Enhance `audit_single_module()` to use profiles**

Modify `audit_single_module()` at line 1313. Replace the infrastructure skip block (lines 1340-1342) and add profile routing:

```python
def audit_single_module(module_name, module_path=None, module_data=None):
    """Audit a single module using its detected profile.

    Args:
        module_name: Module key (e.g., 'consciousness', 'standalone_kytran_news')
        module_path: Filesystem path to module directory (auto-resolved if None)
        module_data: Module metrics dict with by_type breakdown (for profile detection)

    Returns:
        (issues_found, notes, status, issues_list, profile)
    """
    # Resolve path if not provided
    if module_path is None:
        if module_name.startswith("["):
            # Infrastructure modules — use known paths
            path_map = {
                "[APP_CORE]": PLATFORM_ROOT,
                "[AI_BRIDGE]": AI_BRIDGE_ROOT,
                "[MIGRATIONS]": MIGRATIONS_ROOT,
                "[SHARED]": os.path.join(PLATFORM_ROOT, "static"),
            }
            module_path = path_map.get(module_name)
        elif module_name.startswith("standalone_"):
            # Find matching standalone product
            for p in STANDALONE_PRODUCTS:
                if p["module_key"] == module_name:
                    module_path = p["path"]
                    break
        elif module_name.startswith("website_"):
            # Find matching website product
            for w in WEBSITE_PRODUCTS:
                if w["module_key"] == module_name:
                    module_path = w["path"]
                    break
        else:
            module_path = os.path.join(PLATFORM_ROOT, "tools", module_name)

    if not module_path or not os.path.isdir(module_path):
        return (0, f"path not found: {module_path}", "skipped", [], "python")

    # Detect profile
    profile = "python"
    if module_data:
        profile = detect_audit_profile(module_data)
    elif module_name.startswith("website_"):
        profile = "web"
    elif module_name.startswith("standalone_"):
        # Quick scan to detect profile
        stats = _scan_directory(module_path)
        profile = detect_audit_profile({"by_type": {k: dict(v) for k, v in stats["by_type"].items()}})

    # Route to profile-specific checker
    if profile == "web":
        issues_found, notes, issues_list = audit_module_web(module_path)
    elif profile == "config":
        issues_found, notes, issues_list = audit_module_config(module_path)
    else:
        # Original Python audit logic (existing code path)
        issues_found, notes, issues_list = _audit_module_python(module_name, module_path)

    status = "completed" if issues_found == 0 else "violations_found"
    return (issues_found, notes, status, issues_list, profile)
```

- [ ] **Step 4: Rename existing audit logic to `_audit_module_python()`**

The existing body of `audit_single_module()` (lines ~1343-1427) becomes a private function. Move all the existing check logic into:

```python
def _audit_module_python(module_name, module_path):
    """Run python-profile audit checks. Original audit logic.

    Returns: (issues_found, notes, issues_list)
    """
    # ... (move existing check logic here — SQL injection, bare except, direct ollama, etc.)
    # ... keep the existing code unchanged, just wrap it in this function
    # ... return (issues_found, notes, issues_list) instead of the 4-tuple
```

- [ ] **Step 5: Verify the refactor works**

```bash
docker exec archie_platform python3 -c "
from services.code_metrics_service import audit_single_module, detect_audit_profile
# Test profile detection
print(detect_audit_profile({'by_type': {'python': {'lines': 5000}, 'html': {'lines': 100}}}))  # python
print(detect_audit_profile({'by_type': {'js': {'lines': 3000}, 'html': {'lines': 4000}, 'css': {'lines': 1000}}}))  # web
print(detect_audit_profile({'by_type': {'yaml': {'lines': 500}, 'config': {'lines': 200}}}))  # config
# Test audit on a known module
result = audit_single_module('consciousness')
print(f'consciousness: {result[0]} issues, profile={result[4]}')
result2 = audit_single_module('website_kytranempowerment')
print(f'website_ke: {result2[0]} issues, profile={result2[4]}')
"
```

Expected: Profile detection returns correct types, audits complete without errors.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/code_metrics_service.py
git commit -m "feat: add audit profile system — web/config checkers + profile detection"
```

---

### Task 3: Change Detection in `save_snapshot()`

**Files:**
- Modify: `platform_v2/services/code_metrics_service.py` (around line 1197)

- [ ] **Step 1: Add change detection to `save_snapshot()`**

Modify `save_snapshot()` to compare against previous snapshot and store `modules_changed`:

```python
def save_snapshot(metrics=None):
    """Scan codebase and save a snapshot to the database. Detects changed modules."""
    if metrics is None:
        metrics = scan_codebase()

    commit_hash = _get_commit_hash()

    # Detect changed modules by comparing with previous snapshot
    modules_changed = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT per_module FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            prev_row = cur.fetchone()
            if prev_row and prev_row.get("per_module"):
                prev_modules = prev_row["per_module"] if isinstance(prev_row["per_module"], dict) else __import__("json").loads(prev_row["per_module"])
                for key, data in metrics.get("modules", {}).items():
                    prev_data = prev_modules.get(key, {})
                    if data.get("files") != prev_data.get("files") or data.get("lines") != prev_data.get("lines"):
                        modules_changed.append(key)
                # Also detect newly added modules
                for key in metrics.get("modules", {}):
                    if key not in prev_modules and key not in modules_changed:
                        modules_changed.append(key)
    except Exception as e:
        logger.warning("Change detection failed: %s", e)

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Skip if identical snapshot exists within last hour
            cur.execute(
                """SELECT id FROM code_metrics_snapshots
                   WHERE total_files = %s AND total_lines = %s
                     AND scanned_at > NOW() - INTERVAL '1 hour'
                   LIMIT 1""",
                (metrics["total_files"], metrics["total_lines"]),
            )
            if cur.fetchone():
                logger.info("Skipping duplicate snapshot (same file/line count within 1h)")
                return None

            cur.execute(
                """INSERT INTO code_metrics_snapshots
                       (total_files, total_lines, total_folders,
                        python_files, python_lines, js_files, js_lines,
                        css_files, css_lines, html_files, html_lines,
                        sql_files, sql_lines, per_module, commit_hash, modules_changed)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    metrics["total_files"],
                    metrics["total_lines"],
                    metrics["total_folders"],
                    metrics["python"]["files"],
                    metrics["python"]["lines"],
                    metrics["js"]["files"],
                    metrics["js"]["lines"],
                    metrics["css"]["files"],
                    metrics["css"]["lines"],
                    metrics["html"]["files"],
                    metrics["html"]["lines"],
                    metrics["sql"]["files"],
                    metrics["sql"]["lines"],
                    __import__("json").dumps(metrics["modules"]),
                    commit_hash,
                    __import__("json").dumps(modules_changed),
                ),
            )
            snapshot_id = cur.fetchone()["id"]
            if modules_changed:
                logger.info(
                    "Snapshot #%d: %d files, %d lines, %d modules changed: %s",
                    snapshot_id, metrics["total_files"], metrics["total_lines"],
                    len(modules_changed), ", ".join(modules_changed[:5]),
                )
            else:
                logger.info(
                    "Snapshot #%d: %d files, %d lines (no changes)",
                    snapshot_id, metrics["total_files"], metrics["total_lines"],
                )
            return snapshot_id
    except Exception as e:
        logger.error("Failed to save metrics snapshot: %s", e)
        return None
```

- [ ] **Step 2: Verify change detection works**

```bash
docker exec archie_platform python3 -c "
from services.code_metrics_service import scan_codebase, save_snapshot
m = scan_codebase(force=True)
sid = save_snapshot(m)
print(f'Snapshot #{sid} saved')
# Run again — should detect no changes (duplicate skip)
sid2 = save_snapshot(m)
print(f'Second snapshot: {sid2} (should be None — duplicate)')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/code_metrics_service.py
git commit -m "feat: add change detection to code health snapshots"
```

---

### Task 4: Audit API Endpoint + Department HQ Dispatch

**Files:**
- Modify: `platform_v2/tools/consciousness/code_health_routes.py`

- [ ] **Step 1: Add the audit endpoint**

Add inside `register_code_health_routes()`, after the existing routes:

```python
    @bp.route("/api/code-health/audit", methods=["POST"])
    @login_required
    @admin_required
    def code_health_audit():
        """Trigger audit for one or all modules via Department HQ dispatch."""
        from flask import request as req
        from services.code_metrics_service import (
            audit_single_module, detect_audit_profile, log_audit,
            scan_codebase, STANDALONE_PRODUCTS, WEBSITE_PRODUCTS,
        )
        import json as _json

        data = req.get_json(silent=True) or {}
        module_key = data.get("module")  # single module key, or None for all
        trigger = "manual"

        # Get module data for profile detection
        metrics = scan_codebase()
        all_modules = metrics.get("modules", {})

        targets = []
        if module_key:
            if module_key in all_modules:
                targets.append(module_key)
            else:
                return jsonify({"success": False, "error": f"Module not found: {module_key}"}), 404
        else:
            targets = list(all_modules.keys())

        results = []
        for key in targets:
            mod_data = all_modules.get(key, {})
            issues_found, notes, status, issues_list, profile = audit_single_module(
                key, module_data=mod_data
            )

            # Log the audit with new columns
            log_audit(
                module_name=key,
                category=profile.upper(),
                files_reviewed=mod_data.get("files", 0),
                lines_before=mod_data.get("lines", 0),
                lines_after=mod_data.get("lines", 0),
                issues_found=issues_found,
                issues_fixed=0,
                notes=notes,
                status=status,
                audit_profile=profile,
                trigger_reason=trigger,
                dispatched_via="F.O.R.G.E.",
            )

            results.append({
                "module": key,
                "profile": profile,
                "issues": issues_found,
                "status": status,
            })

        return jsonify({
            "success": True,
            "audited": len(results),
            "results": results,
            "trigger": trigger,
        })
```

- [ ] **Step 2: Update `log_audit()` to accept new columns**

In `code_metrics_service.py`, modify `log_audit()` (line ~1429) to include the new columns:

```python
def log_audit(module_name, category, files_reviewed=0, lines_before=0,
              lines_after=0, issues_found=0, issues_fixed=0, notes="",
              status="completed", audit_profile="python", trigger_reason="scheduled",
              dispatched_via=None):
    """Log an audit result to code_audit_log."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO code_audit_log
                       (module_name, category, files_reviewed, lines_before,
                        lines_after, issues_found, issues_fixed, notes, status,
                        audit_profile, trigger_reason, dispatched_via)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (module_name, category, files_reviewed, lines_before,
                 lines_after, issues_found, issues_fixed, notes, status,
                 audit_profile, trigger_reason, dispatched_via),
            )
    except Exception as e:
        logger.error("Failed to log audit for %s: %s", module_name, e)
```

- [ ] **Step 3: Verify the endpoint works**

```bash
docker exec archie_platform python3 -c "
import requests
# Test single module audit
r = requests.post('http://localhost:3000/tools/consciousness/api/code-health/audit',
    json={'module': 'consciousness'},
    cookies={'session': 'test'})
print(r.status_code, r.text[:200])
"
```

Note: This will need auth. Test via browser console instead:
```javascript
fetch('/tools/consciousness/api/code-health/audit', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({module: 'consciousness'})
}).then(r => r.json()).then(d => console.log(d));
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/code_health_routes.py platform_v2/services/code_metrics_service.py
git commit -m "feat: add manual audit endpoint with profile-aware dispatch"
```

---

### Task 5: Update Jobs — Change Detection Trigger + Stale Re-Audit

**Files:**
- Modify: `platform_v2/tools/department_hq/jobs.py`

- [ ] **Step 1: Update Job #40 to trigger audits on changed modules**

At the end of `daily_code_metrics_scan()` (after snapshot save), add change-detection audit trigger:

```python
    # After snapshot save, audit changed modules
    if snapshot_id:
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT modules_changed FROM code_metrics_snapshots WHERE id = %s",
                    (snapshot_id,),
                )
                row = cur.fetchone()
                changed = row["modules_changed"] if row and row.get("modules_changed") else []

            if changed:
                from services.code_metrics_service import audit_single_module, log_audit, detect_audit_profile
                logger.info("Job #40: Auditing %d changed modules", len(changed))
                for key in changed:
                    mod_data = metrics.get("modules", {}).get(key, {})
                    try:
                        issues_found, notes, status, issues_list, profile = audit_single_module(
                            key, module_data=mod_data
                        )
                        log_audit(
                            module_name=key,
                            category=profile.upper(),
                            files_reviewed=mod_data.get("files", 0),
                            lines_before=mod_data.get("lines", 0),
                            lines_after=mod_data.get("lines", 0),
                            issues_found=issues_found,
                            notes=notes,
                            status=status,
                            audit_profile=profile,
                            trigger_reason="change_detected",
                            dispatched_via="F.O.R.G.E.",
                        )
                    except Exception as e:
                        logger.error("Job #40: audit failed for %s: %s", key, e)
        except Exception as e:
            logger.error("Job #40: change-detection audit failed: %s", e)
```

- [ ] **Step 2: Update Job #58 to focus on stale + never-audited modules**

Modify the module iteration in `automated_module_audit()` to prioritize stale and unaudited:

```python
    # Get audit status for all modules
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT DISTINCT ON (module_name) module_name, audited_at, stale
               FROM code_audit_log
               ORDER BY module_name, audited_at DESC"""
        )
        audit_map = {r["module_name"]: r for r in cur.fetchall()}

    # Filter to only stale (>30d) and never-audited modules
    targets = []
    for key in module_stats.keys():
        audit = audit_map.get(key)
        if not audit:
            targets.append((key, "stale_reaudit"))  # never audited
        elif audit.get("stale"):
            targets.append((key, "stale_reaudit"))  # stale
        elif audit["audited_at"] and (datetime.now() - audit["audited_at"]).days > 30:
            targets.append((key, "stale_reaudit"))  # expired

    logger.info("Job #58: %d modules need re-audit (%d total tracked)",
                len(targets), len(module_stats))
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/jobs.py
git commit -m "feat: event-driven audits — Job #40 change detection, Job #58 stale re-audit"
```

---

### Task 6: Frontend — Audit Buttons + Profile Badges

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

- [ ] **Step 1: Add audit buttons to HTML template**

After the `chStatusSummary` area in the template (around line 4220), add button container. Find the section 1 header area:

```html
<!-- Audit controls — inserted after summary bar -->
<div id="chAuditControls" style="display:flex;gap:10px;justify-content:center;margin-bottom:12px;">
    <button id="chAuditAllBtn" class="ch-audit-btn" style="background:rgba(0,229,255,0.15);color:#00e5ff;border:1px solid rgba(0,229,255,0.4);padding:6px 16px;border-radius:4px;font-size:0.75rem;cursor:pointer;text-transform:uppercase;letter-spacing:1px;">
        Audit All Modules
    </button>
    <button id="chRefreshScanBtn" class="ch-audit-btn" style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.4);padding:6px 16px;border-radius:4px;font-size:0.75rem;cursor:pointer;text-transform:uppercase;letter-spacing:1px;">
        Refresh Scan
    </button>
</div>
```

- [ ] **Step 2: Add button click handlers in JS**

Add after the `loadCodeHealth()` function in `consciousness.js`:

```javascript
// ── Audit Controls ──────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function() {
  var auditAllBtn = document.getElementById("chAuditAllBtn");
  if (auditAllBtn) {
    auditAllBtn.addEventListener("click", function() {
      auditAllBtn.disabled = true;
      auditAllBtn.textContent = "Auditing...";
      api("/api/code-health/audit", {method: "POST", body: JSON.stringify({})}).then(function(d) {
        auditAllBtn.disabled = false;
        auditAllBtn.textContent = "Audit All Modules";
        if (d.success) {
          var clean = d.results.filter(function(r) { return r.status === "completed"; }).length;
          var violations = d.results.filter(function(r) { return r.status === "violations_found"; }).length;
          alert("Audit complete: " + clean + " clean, " + violations + " with issues");
          _cache = {};
          loadCodeHealth();
        }
      }).catch(function() {
        auditAllBtn.disabled = false;
        auditAllBtn.textContent = "Audit All Modules";
      });
    });
  }

  var refreshBtn = document.getElementById("chRefreshScanBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", function() {
      refreshBtn.disabled = true;
      refreshBtn.textContent = "Scanning...";
      api("/api/code-health/scan", {method: "POST"}).then(function(d) {
        refreshBtn.disabled = false;
        refreshBtn.textContent = "Refresh Scan";
        if (d.success) {
          _cache = {};
          loadCodeHealth();
        }
      }).catch(function() {
        refreshBtn.disabled = false;
        refreshBtn.textContent = "Refresh Scan";
      });
    });
  }
});
```

- [ ] **Step 3: Add click-to-audit on module table rows**

In `_renderModuleTable()`, modify the row click handler. After building the `<tr>` HTML, add a click event via data attribute:

```javascript
// Inside _renderModuleTable, after building each row:
html += '<tr data-module="' + escHtml(name) + '" style="cursor:pointer;" title="Click to audit this module">';
```

Then after `setHtml(el, html)`, add the click handler:

```javascript
// After setHtml(el, html):
el.querySelectorAll("tr[data-module]").forEach(function(row) {
  row.addEventListener("click", function() {
    var mod = row.getAttribute("data-module");
    row.style.opacity = "0.5";
    api("/api/code-health/audit", {method: "POST", body: JSON.stringify({module: mod})}).then(function(d) {
      row.style.opacity = "1";
      if (d.success && d.results && d.results[0]) {
        var r = d.results[0];
        row.style.background = r.status === "completed" ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)";
        setTimeout(function() { row.style.background = ""; }, 3000);
        // Reload to update badges
        _cache = {};
        loadCodeHealth();
      }
    }).catch(function() { row.style.opacity = "1"; });
  });
});
```

- [ ] **Step 4: Add profile badge + trigger reason to module table columns**

In `_renderModuleTable()`, update the table header and row rendering to include profile and last-audited columns. Modify the header:

```javascript
var html = '<table class="ch-table"><thead><tr>' +
  '<th>Module</th><th class="center">Profile</th><th class="center">Status</th>' +
  '<th class="center">Files</th><th class="center">Lines</th>' +
  '<th class="center">Last Audit</th><th class="center">Trigger</th>' +
  '<th class="center">Python</th><th class="center">JS</th><th class="center">HTML</th>' +
  '<th class="center">CSS</th>' +
  '</tr></thead><tbody>';
```

For each row, add profile badge and audit info. The profile badge uses the module's `by_type` to detect:

```javascript
// Profile detection in JS (mirrors Python logic)
function _detectProfile(mod) {
  var bt = mod.by_type || {};
  var total = 0;
  Object.values(bt).forEach(function(v) { total += v.lines || 0; });
  if (total === 0) return "python";
  var web = ((bt.js||{}).lines||0) + ((bt.html||{}).lines||0) + ((bt.css||{}).lines||0) + ((bt.svg||{}).lines||0);
  var cfg = ((bt.yaml||{}).lines||0) + ((bt.config||{}).lines||0);
  if (cfg / total >= 0.6) return "config";
  if (web / total >= 0.6) return "web";
  return "python";
}
```

Profile badge HTML:
```javascript
var profileColors = {python: "#8b5cf6", web: "#f59e0b", config: "#94a3b8"};
var profile = _detectProfile(m);
var profileBadge = '<span style="font-size:0.55rem;padding:1px 5px;border-radius:3px;background:' +
  profileColors[profile] + '22;color:' + profileColors[profile] + ';border:1px solid ' +
  profileColors[profile] + '44;text-transform:uppercase;">' + profile + '</span>';
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat: audit buttons, click-to-audit rows, profile badges in Code Health"
```

---

### Task 7: Update Audit Table with Trigger + Profile Columns

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`
- Modify: `platform_v2/tools/consciousness/code_health_routes.py`

- [ ] **Step 1: Update audit-log API to return new columns**

In the `code_health_audit_log()` route, the query already selects `*` from `code_audit_log`. Verify the response includes the new columns. If the query uses explicit column names, add `audit_profile`, `trigger_reason`, `dispatched_via`.

- [ ] **Step 2: Update `_renderAuditTable()` to show profile + trigger**

Add Profile and Trigger columns to the audit history table header:

```javascript
// In _renderAuditTable, update header:
'<th>Module</th><th class="center">Profile</th><th class="center">Trigger</th>' +
'<th class="center">Files</th><th class="center">Issues</th><th class="center">Fixed</th>' +
'<th class="center">Status</th><th class="center">Date</th>'
```

Add cells for each row:
```javascript
var profileBadge = e.audit_profile ?
  '<span style="font-size:0.55rem;padding:1px 4px;border-radius:3px;background:rgba(139,92,246,0.15);color:#8b5cf6;">' + escHtml(e.audit_profile) + '</span>' : '—';
var triggerBadge = e.trigger_reason ?
  '<span style="font-size:0.55rem;padding:1px 4px;border-radius:3px;background:rgba(0,229,255,0.1);color:rgba(0,229,255,0.6);">' + escHtml(e.trigger_reason) + '</span>' : '—';
```

- [ ] **Step 3: Add "X modules changed since last audit" to attention items**

In `_renderAttentionItems()`, add a check for changed modules from the snapshot:

```javascript
// Check for recently changed modules
if (d.modules_changed && d.modules_changed.length > 0) {
  items.push({
    severity: "info",
    icon: "\u26A0",
    text: d.modules_changed.length + " modules changed since last audit",
    color: "#f59e0b"
  });
}
```

- [ ] **Step 4: Update `/api/code-health/current` to include `modules_changed`**

In the snapshot-based response in `code_health_current()`, add:

```python
# After loading per_module from snapshot
cur.execute(
    "SELECT modules_changed FROM code_metrics_snapshots WHERE id = (SELECT MAX(id) FROM code_metrics_snapshots)"
)
changed_row = cur.fetchone()
metrics["modules_changed"] = changed_row["modules_changed"] if changed_row and changed_row.get("modules_changed") else []
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/consciousness.js platform_v2/tools/consciousness/code_health_routes.py
git commit -m "feat: audit table shows profile/trigger, attention items show changed modules"
```

---

### Task 8: Integration Test + Full Verification

**Files:**
- No new files

- [ ] **Step 1: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/250_audit_pipeline_columns.sql
```

- [ ] **Step 2: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Save fresh snapshot with change detection**

```bash
docker exec archie_platform python3 -c "
from services.code_metrics_service import scan_codebase, save_snapshot
m = scan_codebase(force=True)
sid = save_snapshot(m)
print(f'Snapshot #{sid}: {m[\"total_files\"]} files, {m[\"total_lines\"]} lines')
"
```

- [ ] **Step 4: Test manual audit via browser**

Navigate to `http://192.168.1.200:3000/tools/consciousness/#codehealth`
1. Click "Audit All Modules" — should audit all ~50 modules within 30 seconds
2. After completion, verify all badges update (most should go green)
3. Click a single module row — should audit just that module within 5 seconds
4. Verify audit table shows profile badges and trigger reasons

- [ ] **Step 5: Verify profile detection**

```bash
docker exec archie_platform python3 -c "
from services.code_metrics_service import scan_codebase, detect_audit_profile
m = scan_codebase()
for key in sorted(m['modules'].keys()):
    profile = detect_audit_profile(m['modules'][key])
    print(f'{key:45s} -> {profile}')
"
```

Expected: Platform tool modules → python, websites → web, standalone apps → python or web depending on composition.

- [ ] **Step 6: Verify totals still match**

```bash
docker exec archie_platform python3 -c "
from services.code_metrics_service import scan_codebase
m = scan_codebase(force=True)
mod_sum = sum(v['lines'] for v in m['modules'].values())
print(f'Total: {m[\"total_lines\"]} | Module sum: {mod_sum} | Match: {mod_sum == m[\"total_lines\"]}')
"
```

Expected: `Match: True`

- [ ] **Step 7: Take screenshots for verification**

Use Playwright to capture:
1. Top section with stats + audit buttons
2. Module table with profile badges + status colors
3. Audit history with trigger/profile columns
4. Standalone table with status badges

- [ ] **Step 8: Commit final state**

```bash
git add -A
git commit -m "feat: code health audit pipeline — full rework complete"
```

---

## Execution Order

Tasks 1-5 are backend (can be done sequentially). Task 6-7 are frontend. Task 8 is verification.

```
Task 1 (migration) → Task 2 (profiles + checkers) → Task 3 (change detection)
  → Task 4 (API endpoint) → Task 5 (jobs update)
  → Task 6 (UI buttons + badges) → Task 7 (audit table + attention)
  → Task 8 (integration test)
```
