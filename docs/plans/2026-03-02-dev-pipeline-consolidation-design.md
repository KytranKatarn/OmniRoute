# Dev Pipeline Consolidation — Design

**Project**: #102 Dev Pipeline Consolidation
**Date**: 2026-03-02
**Status**: Approved

---

## Problem

Code Sentinel, Improvements Lab, and Sandbox Manager are three separate modules handling one pipeline: scan → propose → test → deploy. Users jump between 3 UIs to follow a single workflow. The shared `dev_tools_nav.html` had 7 links, 4 to non-existent blueprints, causing crashes.

## Solution

Single unified module at `/tools/dev-pipeline` with 4 LCARS tabs: **Scan**, **Proposals**, **Sandbox**, **Deploy**. LCARS gold-standard design, Fold5 responsive. Bridge Command agents for all AI operations.

## Tabs

### Tab 1: Scan (from Code Sentinel)
- File browser + scan controls (single + batch)
- Scan history with quality scores
- Issue list by severity (critical/high/medium/low) with fix suggestions
- Multi-agent code review via Bridge agents
- Issues auto-feed Proposals tab via Phase 4 scan_pipeline hooks

### Tab 2: Proposals (from Improvements Lab)
- Proposal list with status filter: Pending → Approved → Testing → Tested → Deployed
- Approve/reject (Tier 2 human gate)
- Team assignments + agent discussions
- Code generation results + diffs
- Proposal chat with ARCHIE

### Tab 3: Sandbox (from Sandbox Manager)
- Active sandbox environments (Docker + schema types)
- Test suite runner with pass/fail results
- Configure test suites and sandbox settings
- Apply proposal code into sandbox

### Tab 4: Deploy (from Improvements + Sandbox)
- Deployment history with status badges
- Active deployment monitoring (24h health checks)
- One-click rollback with backup restoration
- Risk scores + pre/post health comparison

## Architecture

### New Module Structure
```
platform_v2/tools/dev_pipeline/
├── __init__.py           # Blueprint, register_*_routes pattern
├── scan_routes.py        # From code_sentinel/routes.py (16 endpoints)
├── proposal_routes.py    # From improvements/routes.py (core endpoints)
├── sandbox_routes.py     # From sandbox_manager/routes.py (29 endpoints)
├── deploy_routes.py      # From improvements + sandbox deploy endpoints
```

### Template
Single LCARS template: `templates/tools/dev_pipeline.html`
- LCARS frame wrapper (matching Chat, Bridge, Consciousness pattern)
- Glass-nav tab switcher (4 tabs)
- Hash navigation: #scan, #proposals, #sandbox, #deploy
- Responsive: 768px tablet, 500px mobile (Fold5 standard)

### Route Pattern
Same as Consciousness: `register_*_routes(bp, admin_required)` in `__init__.py`

### Backend Services Unchanged
- `services/scan_pipeline.py` — stays as-is
- `ai_bridge/code_generation_engine.py` — stays as-is
- `platform_v2/sandbox_manager.py` — stays as-is
- `ai_bridge/bridge_dispatcher.py` — stays as-is
All backend logic untouched. Only route layer + template change.

### DB Tables (all retained, no schema changes)
- `code_scans`, `code_issues`, `code_fixes` — Scan tab
- `improvement_proposals`, `improvement_team_assignments`, `improvement_workflow_states`, `improvement_conversations`, `improvement_deployments` — Proposals tab
- `module_sandboxes`, `sandbox_config`, `sandbox_test_suites`, `sandbox_test_results`, `test_runs` — Sandbox tab

## Migration

1. Build new module, register in module_registry.py + rbac.py
2. Old modules redirect: `/tools/code_sentinel` → `/tools/dev-pipeline#scan`, `/tools/improvements-lab` → `/tools/dev-pipeline#proposals`, `/tools/sandbox-manager` → `/tools/dev-pipeline#sandbox`
3. Update dashboard category: DEV_TOOLS shows single "Dev Pipeline" entry
4. 30-day deprecation period (old modules serve redirects)
5. Remove old modules + dev_tools_nav.html after deprecation

## What Gets Dropped
- CodeRabbit, IDE Integration, Testing Suite, Fine-tuning (already dead)
- `dev_tools_nav.html` — replaced by module's own tab nav
- Duplicate dispatch activity history endpoints (consolidate to one)
- Separate module registrations (3 → 1)
