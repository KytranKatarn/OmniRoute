# Code Health Tab — Move from Consciousness to Repair Bay

**Date:** 2026-05-13
**Scope:** Relocate the Code Health tab from the Consciousness module to Repair Bay as a new top-level tab.

---

## Context

Code Health lives in `tools/consciousness/code_health_routes.py` (952 lines) and is registered under the consciousness blueprint at `/tools/consciousness/api/code-health/*`. It shows codebase metrics, file quality scores, module audit progress, and severity summaries — all of which feed directly into Repair Bay's proposal system. Architecturally it belongs in Repair Bay.

The Repair Bay "Diagnose" tab is different — it runs targeted scans on specific files. Code Health is the overall codebase health dashboard. No conflict.

---

## Changes

### 1. New route file in Repair Bay

**Create:** `platform_v2/tools/repair_bay/code_health_routes.py`

Copy `platform_v2/tools/consciousness/code_health_routes.py` to the new location. The `register_code_health_routes(bp, admin_required)` function signature and all route logic stays identical. No functional changes.

### 2. Register in Repair Bay __init__.py

**Modify:** `platform_v2/tools/repair_bay/__init__.py`

Add after the last `register_*_routes` call:
```python
from .code_health_routes import register_code_health_routes
register_code_health_routes(repair_bay_bp, admin_required)
```

All routes now live under `/tools/repair-bay/api/code-health/*`.

### 3. Add Code Health tab to Repair Bay template

**Modify:** `platform_v2/tools/repair_bay/templates/repair_bay.html`

Add "Code Health" as a new top-level tab. The tab panel content is the same HTML currently in the Consciousness template — metrics cards, module table, severity summary, audit log.

Update all JavaScript calls from `/tools/consciousness/api/code-health/` to `/tools/repair-bay/api/code-health/`.

### 4. Remove from Consciousness

**Modify:** `platform_v2/tools/consciousness/__init__.py`
- Remove: `from .code_health_routes import register_code_health_routes`
- Remove: `register_code_health_routes(consciousness_bp, admin_required)`

**Modify:** `platform_v2/tools/consciousness/templates/consciousness.html`
- Remove the Code Health tab entry from the tab nav
- Remove the Code Health tab panel HTML

**Delete:** `platform_v2/tools/consciousness/code_health_routes.py` (after new file is verified working)

---

## URL changes

| Old | New |
|-----|-----|
| `/tools/consciousness/api/code-health/scan` | `/tools/repair-bay/api/code-health/scan` |
| `/tools/consciousness/api/code-health/current` | `/tools/repair-bay/api/code-health/current` |
| `/tools/consciousness/api/code-health/snapshots` | `/tools/repair-bay/api/code-health/snapshots` |
| `/tools/consciousness/api/code-health/audit-log` | `/tools/repair-bay/api/code-health/audit-log` |
| `/tools/consciousness/api/code-health/module-status` | `/tools/repair-bay/api/code-health/module-status` |
| `/tools/consciousness/api/code-health/severity-summary` | `/tools/repair-bay/api/code-health/severity-summary` |
| `/tools/consciousness/api/code-health/backfill-git` | `/tools/repair-bay/api/code-health/backfill-git` |
| `/tools/consciousness/api/code-health/governance-log` | `/tools/repair-bay/api/code-health/governance-log` |

`code_metrics_service.py` stays in `platform_v2/services/` — it is a shared service with no move needed.

---

## Out of Scope

- Changes to code_metrics_service.py functionality
- Changes to the Diagnose tab
- Adding new Code Health features
- Any Consciousness routes other than code-health

---

## Testing

1. Open Repair Bay — "Code Health" tab appears in nav
2. Tab loads: module table shows file counts + quality scores
3. "Scan" button triggers `/tools/repair-bay/api/code-health/scan` — verify 200 response
4. Consciousness module — Code Health tab is gone from nav
5. No 404s in browser console for old `/tools/consciousness/api/code-health/*` paths
