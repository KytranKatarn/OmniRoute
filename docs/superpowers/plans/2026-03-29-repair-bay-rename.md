# Dev Pipeline → Repair Bay Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the Dev Pipeline module to Repair Bay across the entire codebase (directory, blueprint, URL, template, module ID, tab labels).

**Architecture:** Git mv the directory + template, then sed/grep-replace all references across 34 files. No logic changes. Tab labels change from Scan/Proposals/Sandbox/Deploy to Diagnose/Repairs/Test Bay/Ship. F.O.R.G.E. agent branding stays.

**Tech Stack:** Python/Flask, Jinja2 templates, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-29-repair-bay-rename-design.md`

---

## File Map

### Renamed (git mv)
- `tools/dev_pipeline/` → `tools/repair_bay/`
- `templates/tools/dev_pipeline.html` → `templates/tools/repair_bay.html`
- `.claude/rules/dev-pipeline.md` → `.claude/rules/repair-bay.md`

### Modified (reference updates)
All files listed in the spec — 34 total. No new files created.

---

## Task 1: Move Directory + Template + Rules File

**Files:**
- Rename: `platform_v2/tools/dev_pipeline/` → `platform_v2/tools/repair_bay/`
- Rename: `platform_v2/templates/tools/dev_pipeline.html` → `platform_v2/templates/tools/repair_bay.html`
- Rename: `.claude/rules/dev-pipeline.md` → `.claude/rules/repair-bay.md`

- [ ] **Step 1: Git mv the directory**

```bash
cd /mnt/archie_brain
git mv platform_v2/tools/dev_pipeline platform_v2/tools/repair_bay
```

- [ ] **Step 2: Git mv the template**

```bash
git mv platform_v2/templates/tools/dev_pipeline.html platform_v2/templates/tools/repair_bay.html
```

- [ ] **Step 3: Git mv the rules file**

```bash
git mv .claude/rules/dev-pipeline.md .claude/rules/repair-bay.md
```

- [ ] **Step 4: Commit the moves**

```bash
git add -A
git commit -m "refactor: git mv dev_pipeline → repair_bay (directory, template, rules)"
```

---

## Task 2: Update Internal Module Files

**Files:**
- Modify: `platform_v2/tools/repair_bay/__init__.py`
- Modify: `platform_v2/tools/repair_bay/routes.py`
- Modify: All route files inside `platform_v2/tools/repair_bay/`
- Modify: All service files inside `platform_v2/tools/repair_bay/services/`

- [ ] **Step 1: Update __init__.py blueprint**

In `platform_v2/tools/repair_bay/__init__.py`, replace:
- `dev_pipeline_bp` → `repair_bay_bp` (all occurrences)
- `"dev_pipeline"` → `"repair_bay"` (blueprint name string)
- `url_prefix="/tools/dev-pipeline"` → `url_prefix="/tools/repair-bay"`
- Any `from . import routes` or similar should just work (relative imports)

- [ ] **Step 2: Update routes.py**

In `platform_v2/tools/repair_bay/routes.py`, replace:
- `dev_pipeline_bp` → `repair_bay_bp`
- Any `from . import dev_pipeline_bp` → `from . import repair_bay_bp`

- [ ] **Step 3: Bulk replace in all route files**

For each file in `platform_v2/tools/repair_bay/*.py`:
- Replace `dev_pipeline_bp` → `repair_bay_bp`
- Replace `dev_pipeline` → `repair_bay` (in string references like module_source)
- Replace `dev-pipeline` → `repair-bay` (in URL strings)

Run:
```bash
cd /mnt/archie_brain/platform_v2/tools/repair_bay
find . -name '*.py' -not -path './__pycache__/*' -exec sed -i 's/dev_pipeline_bp/repair_bay_bp/g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' {} +
```

- [ ] **Step 4: Bulk replace in all service files**

```bash
cd /mnt/archie_brain/platform_v2/tools/repair_bay/services
find . -name '*.py' -not -path './__pycache__/*' -exec sed -i 's/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' {} +
```

- [ ] **Step 5: Verify no dev_pipeline references remain inside the module**

```bash
grep -rn 'dev_pipeline\|dev-pipeline' /mnt/archie_brain/platform_v2/tools/repair_bay/ --include='*.py' | grep -v __pycache__ | head -20
```

Expected: 0 results.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "refactor: update all internal repair_bay references (blueprint, URLs, imports)"
```

---

## Task 3: Update External References (Python)

**Files:**
- Modify: `platform_v2/app.py`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`
- Modify: `platform_v2/services/audit_pipeline.py`
- Modify: `platform_v2/services/proposal_service.py`
- Modify: `platform_v2/services/sandbox_service.py`
- Modify: `platform_v2/services/scan_service.py`
- Modify: `platform_v2/services/browser_test_service.py`
- Modify: `platform_v2/mcp_server/tools/forge_tools.py`
- Modify: `platform_v2/tools/api_docs/routes.py`
- Modify: `platform_v2/tools/consciousness/code_health_routes.py`
- Modify: `platform_v2/tools/team_management/routes.py`

- [ ] **Step 1: Update app.py**

Replace all occurrences of:
- `from tools.dev_pipeline` → `from tools.repair_bay`
- `dev_pipeline_bp` → `repair_bay_bp`
- `dev_pipeline` → `repair_bay` (in any string references)

```bash
sed -i 's/tools\.dev_pipeline/tools.repair_bay/g; s/dev_pipeline_bp/repair_bay_bp/g; s/"dev_pipeline"/"repair_bay"/g' /mnt/archie_brain/platform_v2/app.py
```

- [ ] **Step 2: Update module_registry.py**

```bash
sed -i 's/id="dev_pipeline"/id="repair_bay"/g; s/Dev Pipeline/Repair Bay/g; s|/tools/dev-pipeline|/tools/repair-bay|g; s/tools\.dev_pipeline/tools.repair_bay/g; s/dev_pipeline_bp/repair_bay_bp/g; s/"dev_pipeline"/"repair_bay"/g' /mnt/archie_brain/platform_v2/module_registry.py
```

- [ ] **Step 3: Update rbac.py**

```bash
sed -i 's/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' /mnt/archie_brain/platform_v2/rbac.py
```

- [ ] **Step 4: Update platform services**

```bash
for f in audit_pipeline.py proposal_service.py sandbox_service.py scan_service.py browser_test_service.py; do
    sed -i 's/tools\.dev_pipeline/tools.repair_bay/g; s/"dev_pipeline"/"repair_bay"/g; s|/tools/dev-pipeline|/tools/repair-bay|g; s/dev_pipeline/repair_bay/g' /mnt/archie_brain/platform_v2/services/$f
done
```

- [ ] **Step 5: Update MCP forge tools**

```bash
sed -i 's/tools\.dev_pipeline/tools.repair_bay/g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' /mnt/archie_brain/platform_v2/mcp_server/tools/forge_tools.py
```

- [ ] **Step 6: Update other module references**

```bash
sed -i 's/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' /mnt/archie_brain/platform_v2/tools/api_docs/routes.py
sed -i 's/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' /mnt/archie_brain/platform_v2/tools/consciousness/code_health_routes.py
sed -i 's/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g' /mnt/archie_brain/platform_v2/tools/team_management/routes.py
```

- [ ] **Step 7: Verify no dev_pipeline references in Python files outside the module**

```bash
grep -rn 'dev_pipeline\|dev-pipeline' /mnt/archie_brain/platform_v2/ --include='*.py' | grep -v __pycache__ | grep -v 'tools/repair_bay' | head -20
```

Expected: 0 results.

- [ ] **Step 8: Commit**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "refactor: update all external Python references to repair_bay"
```

---

## Task 4: Update Frontend References (JS, HTML, CSS)

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`
- Modify: `platform_v2/static/js/department-ops.js`
- Modify: `platform_v2/static/js/starbase.js`
- Modify: `platform_v2/templates/includes/dev_tools_nav.html`
- Modify: `platform_v2/templates/tools/archie_chat.html`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

- [ ] **Step 1: Update JS files**

```bash
for f in consciousness.js department-ops.js starbase.js; do
    sed -i 's|/tools/dev-pipeline|/tools/repair-bay|g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g; s/Dev Pipeline/Repair Bay/g' /mnt/archie_brain/platform_v2/static/js/$f
done
```

- [ ] **Step 2: Update HTML templates**

```bash
sed -i 's|/tools/dev-pipeline|/tools/repair-bay|g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g; s/Dev Pipeline/Repair Bay/g' /mnt/archie_brain/platform_v2/templates/includes/dev_tools_nav.html
sed -i 's|/tools/dev-pipeline|/tools/repair-bay|g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g; s/Dev Pipeline/Repair Bay/g' /mnt/archie_brain/platform_v2/templates/tools/archie_chat.html
sed -i 's|/tools/dev-pipeline|/tools/repair-bay|g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g; s/Dev Pipeline/Repair Bay/g' /mnt/archie_brain/platform_v2/tools/consciousness/templates/consciousness_dashboard.html
```

- [ ] **Step 3: Verify no dev-pipeline references in frontend files**

```bash
grep -rn 'dev_pipeline\|dev-pipeline\|Dev Pipeline' /mnt/archie_brain/platform_v2/ --include='*.js' --include='*.html' --include='*.css' | grep -v __pycache__ | grep -v 'tools/repair_bay' | head -20
```

Expected: 0 results (except possibly in git-ignored files or blueprint route history comments).

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "refactor: update all frontend references to repair-bay"
```

---

## Task 5: Tab Label Rename + Rules File Update

**Files:**
- Modify: `platform_v2/templates/tools/repair_bay.html`
- Modify: `.claude/rules/repair-bay.md`

- [ ] **Step 1: Rename tab labels in template**

In `platform_v2/templates/tools/repair_bay.html`, replace tab labels:
- `Scan` → `Diagnose` (the tab label/button text)
- `Proposals` → `Repairs`
- `Sandbox` → `Test Bay`
- `Deploy` → `Ship`

Be careful to only replace the UI-visible labels, NOT the JavaScript tab IDs or API endpoint names (those can stay as scan/proposals/sandbox/deploy internally).

```bash
sed -i 's/>Scan</>Diagnose</g; s/>Proposals</>Repairs</g; s/>Sandbox</>Test Bay</g; s/>Deploy</>Ship</g' /mnt/archie_brain/platform_v2/templates/tools/repair_bay.html
```

If the tab labels use a different HTML pattern (e.g. data attributes, spans), read the file first and adjust the sed accordingly.

- [ ] **Step 2: Update rules file content**

In `.claude/rules/repair-bay.md`, replace:
- All `Dev Pipeline` → `Repair Bay`
- All `dev_pipeline` → `repair_bay`
- All `dev-pipeline` → `repair-bay`
- Tab references: `Scan, Proposals, Sandbox, Deploy` → `Diagnose, Repairs, Test Bay, Ship`
- Header: `# Dev Pipeline Rules` → `# Repair Bay Rules`

```bash
sed -i 's/Dev Pipeline/Repair Bay/g; s/dev_pipeline/repair_bay/g; s/dev-pipeline/repair-bay/g; s/Scan, Proposals, Sandbox, Deploy/Diagnose, Repairs, Test Bay, Ship/g' /mnt/archie_brain/.claude/rules/repair-bay.md
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "refactor: rename tab labels (Diagnose/Repairs/Test Bay/Ship) + update rules"
```

---

## Task 6: Deploy + Verify

- [ ] **Step 1: Final grep — zero references to old name**

```bash
grep -rn 'dev_pipeline\|dev-pipeline\|Dev Pipeline' /mnt/archie_brain/platform_v2/ --include='*.py' --include='*.html' --include='*.js' | grep -v __pycache__ | grep -v '.pyc'
```

Expected: 0 results. If any remain, fix them.

Also check rules and CLAUDE.md:
```bash
grep -rn 'dev_pipeline\|dev-pipeline\|Dev Pipeline' /mnt/archie_brain/.claude/ /mnt/archie_brain/CLAUDE.md | grep -v __pycache__
```

Expected: 0 results.

- [ ] **Step 2: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Check logs for import errors**

```bash
docker logs archie_platform --tail 20
```

Expected: Clean boot, no ImportError or ModuleNotFoundError.

- [ ] **Step 4: Browser verify**

Navigate to `http://192.168.1.200:3000/tools/repair-bay`

Verify:
1. Module loads without errors
2. 4 tabs visible: Diagnose, Repairs, Test Bay, Ship
3. Each tab loads its content
4. ENGINEERING station panel works
5. Old URL `/tools/dev-pipeline` returns 404 (not a redirect — clean break)

- [ ] **Step 5: Verify F.O.R.G.E. MCP tools still work**

Check that forge MCP tools reference the new paths:
```bash
grep -n 'repair_bay\|repair-bay' /mnt/archie_brain/platform_v2/mcp_server/tools/forge_tools.py
```

Expected: All references point to repair_bay.

- [ ] **Step 6: Commit any fixes**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "fix: final cleanup for repair-bay rename"
```

---

## Summary

| Task | What | Commit |
|------|------|--------|
| 1 | Git mv directory + template + rules | `refactor: git mv dev_pipeline → repair_bay` |
| 2 | Update internal module references | `refactor: update internal repair_bay refs` |
| 3 | Update external Python references | `refactor: update external Python refs` |
| 4 | Update frontend references (JS, HTML) | `refactor: update frontend refs` |
| 5 | Tab labels + rules file | `refactor: rename tab labels + rules` |
| 6 | Deploy + verify zero old refs | `fix: final cleanup` |
