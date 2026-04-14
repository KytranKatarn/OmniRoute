# Code Health Audit Pipeline — Full Rework

**Date:** 2026-04-14
**Status:** Design
**Project:** Consciousness Module — Code Health Tab
**Agents:** F.O.R.G.E. (Engineering & Technology)

---

## Problem

The Code Health tab tracks file metrics accurately (629k lines, 2,069 files, 13 file types, 50 modules) but the audit workflow is broken:

- 29 of 50 modules show "unaudited" (red)
- Standalone products and websites are skipped entirely by the audit scanner
- Audits only run on Sundays at 3:30 AM — no manual trigger, no change detection
- The audit only checks Python-specific patterns — no checks for JS, HTML, CSS, config files
- No feedback loop: audit finds issues but nothing tracks whether they get fixed

## Solution

Event-driven, profile-aware audit pipeline routed through Department HQ dispatch.

---

## 1. Audit Profile System

Three profiles based on dominant file type (60% threshold, fallback to Python for mixed):

### Python Profile
**Applies to:** Platform modules, standalone Python apps
**Checks:**
- `SQL_INJECTION` — raw SQL string concatenation with user input
- `HARDCODED_SECRET` — passwords, tokens, API keys in source
- `DIRECT_OLLAMA` — direct Ollama API calls bypassing Bridge (ADR-013)
- `DIRECT_CLOUD` — direct cloud provider calls bypassing dispatch
- `BARE_EXCEPT` — bare `except:` without specific exception type
- `LARGE_FILE` — any single file >600 lines
- `MISSING_INIT` — Python package directory without `__init__.py`
- `IMPORT_VIOLATION` — importing from deprecated `ai_bridge/` shims in new code

### Web Profile
**Applies to:** Websites, JS/HTML/CSS-heavy standalone products
**Checks:**
- `HARDCODED_SECRET` — passwords, tokens, API keys in source
- `INLINE_SCRIPT` — `<script>` blocks with logic in HTML (should be external JS)
- `CONSOLE_LOG` — `console.log()` left in production JS
- `LARGE_FILE` — any single file >600 lines
- `TODO_FIXME` — count of TODO/FIXME/HACK comments (informational, not blocking)
- `MIXED_CONCERNS` — CSS in JS or JS in HTML beyond minimal bootstrap

### Config Profile
**Applies to:** Docker, YAML, TOML, nginx, systemd configs
**Checks:**
- `HARDCODED_SECRET` — passwords, tokens, API keys in config files
- `INSECURE_DEFAULT` — `privileged: true`, `read_only: false`, missing resource limits
- `LATEST_TAG` — Docker images using `:latest` instead of pinned versions
- `MISSING_RESOURCE_LIMIT` — containers without CPU/memory limits

### Profile Detection
```python
def detect_audit_profile(module_data):
    by_type = module_data.get("by_type", {})
    total = sum(v.get("lines", 0) for v in by_type.values())
    if total == 0:
        return "python"  # default
    py_pct = by_type.get("python", {}).get("lines", 0) / total
    web_pct = sum(by_type.get(t, {}).get("lines", 0) for t in ["js", "html", "css"]) / total
    config_pct = sum(by_type.get(t, {}).get("lines", 0) for t in ["yaml", "config"]) / total
    if config_pct >= 0.6:
        return "config"
    if web_pct >= 0.6:
        return "web"
    return "python"  # default for mixed or Python-dominant
```

### Severity Classification
- **Red (security):** `SQL_INJECTION`, `HARDCODED_SECRET`, `DIRECT_OLLAMA`, `DIRECT_CLOUD`, `INSECURE_DEFAULT`
- **Yellow (quality):** `BARE_EXCEPT`, `LARGE_FILE`, `MISSING_INIT`, `INLINE_SCRIPT`, `CONSOLE_LOG`, `LATEST_TAG`, `MISSING_RESOURCE_LIMIT`
- **Info:** `TODO_FIXME`, `MIXED_CONCERNS`, `IMPORT_VIOLATION`

---

## 2. Event-Driven Triggers via Department HQ

All audit requests route through Department HQ dispatch to F.O.R.G.E. agent.

### Flow
```
Trigger → POST /api/code-health/audit → dispatch(task="code_audit") → F.O.R.G.E. → run checks → write code_audit_log
```

### Three Trigger Sources

| Trigger | Source | When | Modules |
|---------|--------|------|---------|
| Change detected | Job #40 snapshot diff | Daily 3:00 AM | Only changed modules |
| Manual | Code Health tab button | On-demand | Single module or all |
| Weekly safety net | Job #58 | Sundays 3:30 AM | Stale (>30d) + never-audited |

### Change Detection (in `save_snapshot()`)
```python
# Compare new snapshot per_module against previous
prev = get_previous_snapshot()
changed = []
for key, data in new_per_module.items():
    prev_data = prev.get(key, {})
    if data.get("files") != prev_data.get("files") or data.get("lines") != prev_data.get("lines"):
        changed.append(key)
# Store in snapshot and queue audits for changed modules
```

### Dispatch Call
```python
from tools.department_hq.services.bridge_dispatcher import dispatch

result = dispatch(
    prompt=f"Audit module {module_key} using {profile} profile",
    task_type="code_audit",
    metadata={
        "module_key": module_key,
        "audit_profile": profile,
        "trigger_reason": reason,  # "change_detected" | "manual" | "scheduled" | "stale_reaudit"
    }
)
```

### Status Transitions
```
UNAUDITED (red) → audit runs → CLEAN (green) or VIOLATIONS (red)
CLEAN (green) → 30 days pass → STALE (yellow)
CLEAN (green) → files change → auto re-audit → CLEAN or VIOLATIONS
VIOLATIONS (red) → fix applied → manual re-audit → CLEAN (green)
```

---

## 3. UI Enhancements

### Top Section
- Summary bar: centered clean/stale/unaudited counts (already built)
- Last scanned timestamp in centered box (already built)
- **NEW:** "Audit All" button — cyan LCARS style, triggers full audit via dispatch
- **NEW:** "Refresh Scan" button — re-scans filesystem, saves snapshot, reloads

### Stats Cards
- All 13 file type boxes (already built)
- Sort/filter controls on chart (already built)

### Module Table — New Columns
| Column | Content |
|--------|---------|
| Module | Name + audit profile badge (Python/Web/Config) |
| Status | Green/Yellow/Red badge (CLEAN/STALE/UNAUDITED) |
| Files | File count |
| Lines | Line count |
| Last Audited | Date or "never" |
| Trigger | Why last audit ran (change/manual/scheduled) |
| Per-type columns | Python, JS, HTML, CSS, SQL, etc. |

- Click any module row to trigger single-module audit via dispatch
- Row highlights briefly when audit completes

### Standalone + Website Tables
- Same status badges — now reflect real audits with web/config profiles
- Profile badge next to product name

### Lower Sections
| Section | Enhancement |
|---------|------------|
| Attention Items | Add "X modules changed since last audit" alert |
| Audit History | Add trigger reason + profile columns |
| History Chart | Add audit event markers on timeline |
| Repair Pipeline | No change (already connected) |
| Orphan Table | No change |
| Structural Audit | No change |

---

## 4. Data Model Changes

### `code_audit_log` — Add 3 columns
```sql
ALTER TABLE code_audit_log
    ADD COLUMN IF NOT EXISTS audit_profile VARCHAR(20) DEFAULT 'python',
    ADD COLUMN IF NOT EXISTS trigger_reason VARCHAR(30) DEFAULT 'scheduled',
    ADD COLUMN IF NOT EXISTS dispatched_via VARCHAR(50);
```

### `code_metrics_snapshots` — Add 1 column
```sql
ALTER TABLE code_metrics_snapshots
    ADD COLUMN IF NOT EXISTS modules_changed JSONB DEFAULT '[]'::jsonb;
```

### No new tables required.

---

## 5. Files to Modify

| File | Changes |
|------|---------|
| `services/code_metrics_service.py` | `detect_audit_profile()`, `audit_module_web()`, `audit_module_config()`, enhance `audit_single_module()` to use profiles, change detection in `save_snapshot()` |
| `tools/consciousness/code_health_routes.py` | `POST /api/code-health/audit` endpoint (single + bulk), wire to dispatch |
| `static/js/consciousness.js` | Audit buttons, click-to-audit rows, profile badges, trigger reason column, audit markers on history chart |
| `tools/consciousness/templates/consciousness_dashboard.html` | Audit button elements in top section |
| `tools/department_hq/jobs.py` | Update Job #40 for change detection + audit queue, update Job #58 for stale re-audit |
| `database/migrations/XXX_audit_pipeline.sql` | ALTER TABLE statements for new columns |

### No changes needed to:
- Bridge dispatcher (already supports task dispatch)
- Agent service (F.O.R.G.E. already exists)
- Repair Bay (already receives proposals from audits)

---

## 6. Success Criteria

- [ ] All 50 modules have a status badge (no "unaudited" unless truly never scanned)
- [ ] Standalone products and websites get audited with appropriate profiles
- [ ] Clicking "Audit All" completes within 30 seconds and updates all badges
- [ ] Clicking a module row audits just that module within 5 seconds
- [ ] Changed modules auto-audit after next daily snapshot
- [ ] Stale modules auto-audit on weekly job
- [ ] Audit history shows trigger reason for every entry
- [ ] Zero "other" in file type breakdown (all extensions mapped)
