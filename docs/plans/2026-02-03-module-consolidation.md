# Module Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate 51 platform modules into a cleaner architecture by merging duplicates, removing unused modules, and reorganizing into clear categories.

**Architecture:** Move modules to `_deprecated_duplicates/` after extracting useful code, update `module_registry.py` and `rbac.py` to reflect new structure, and ensure all routes/functionality are preserved in the target modules.

**Tech Stack:** Python/Flask, PostgreSQL, Docker (archie_platform container)

---

## Summary of Changes

### Modules to Merge (8 merges)
| Target Module | Absorbing From |
|---------------|----------------|
| `media_hub` | `plex_stack` |
| `website_studio` | `site_manager` |
| `project_manager` | `project_builder` |
| `automations` | `goose` + `automation_services` |
| `sandbox_manager` | `testing_suite` |
| `bridge` | `cursor_integration` + `fine_tuning` |
| `team_management` | `hr_management` |
| `crm` | `analytics` |

### Modules to Remove (2 removals)
| Module | Reason |
|--------|--------|
| `coderabbit` | Using code_sentinel + Claude instead |
| `figma` | Not needed |

### Final Category Structure
1. **Admin Operations** (4): backup_manager, security_network, account_center, system_operations
2. **AI Command** (5): blueprint, consciousness, team_management, bridge, archie_core
3. **Development Tools** (2): code_sentinel, sandbox_manager, improvements
4. **SaaS Services** (9): crm, website_studio, store_builder, call_center, email_manager, automations, invoicing, scheduler, social_media
5. **Project & Knowledge** (3): project_manager, obsidian_vault, api_docs
6. **Media & Home** (1): media_hub
7. **Placeholders** (12): fitness, therapy, doc, stockbot, game_studio, archie_pool, pool_management, task_planner, google_workspace, content_studio, media_studio, app_builder

---

## Pre-Implementation Checklist

- [ ] Create backup of current state
- [ ] Document current module registry state
- [ ] Verify Docker container is running

---

## Phase 1: Preparation & Backup

### Task 1.1: Create Full Platform Backup

**Files:**
- None modified

**Step 1: Create timestamped backup**

```bash
docker exec archie_platform python3 -c "
from tools.backup_manager import create_backup
result = create_backup('pre-consolidation-backup')
print(result)
"
```

Expected: Backup created successfully with timestamp

**Step 2: Verify backup exists**

```bash
ls -la /mnt/archie_brain/backups/ | head -5
```

Expected: New backup file with today's date

**Step 3: Commit preparation**

```bash
git add -A && git commit -m "chore: pre-consolidation backup checkpoint"
```

---

### Task 1.2: Document Current Module Registry State

**Files:**
- Read: `platform_v2/module_registry.py`
- Read: `platform_v2/rbac.py`

**Step 1: Export current module list**

```bash
grep -E "^['\"].*['\"]:\s*\{" /mnt/archie_brain/platform_v2/module_registry.py | head -60
```

**Step 2: Save snapshot for reference**

```bash
cp /mnt/archie_brain/platform_v2/module_registry.py /mnt/archie_brain/backups/module_registry_pre_consolidation.py
cp /mnt/archie_brain/platform_v2/rbac.py /mnt/archie_brain/backups/rbac_pre_consolidation.py
```

---

## Phase 2: Simple Removals (No Merge Required)

### Task 2.1: Remove coderabbit Module

**Files:**
- Move: `platform_v2/tools/coderabbit/` → `platform_v2/tools/_deprecated_duplicates/coderabbit/`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

**Step 1: Move module to deprecated folder**

```bash
mv /mnt/archie_brain/platform_v2/tools/coderabbit /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 2: Comment out in module_registry.py**

Find and comment out the coderabbit entry in module_registry.py

**Step 3: Comment out in rbac.py**

Find and comment out any coderabbit permissions in rbac.py

**Step 4: Verify platform still loads**

```bash
docker exec archie_platform python3 -c "from app import app; print('App loads OK')"
```

**Step 5: Commit**

```bash
git add -A && git commit -m "chore: deprecate coderabbit module (using code_sentinel + Claude)"
```

---

### Task 2.2: Remove figma Module

**Files:**
- Move: `platform_v2/tools/figma/` → `platform_v2/tools/_deprecated_duplicates/figma/`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

**Step 1: Move module to deprecated folder**

```bash
mv /mnt/archie_brain/platform_v2/tools/figma /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 2: Comment out in module_registry.py**

Find and comment out the figma entry in module_registry.py

**Step 3: Comment out in rbac.py**

Find and comment out any figma permissions in rbac.py

**Step 4: Verify platform still loads**

```bash
docker exec archie_platform python3 -c "from app import app; print('App loads OK')"
```

**Step 5: Commit**

```bash
git add -A && git commit -m "chore: deprecate figma module (not needed)"
```

---

## Phase 3: Merges - Media & Content

### Task 3.1: Merge plex_stack into media_hub

**Files:**
- Read: `platform_v2/tools/plex_stack/__init__.py`
- Read: `platform_v2/tools/media_hub/__init__.py`
- Modify: `platform_v2/tools/media_hub/__init__.py` (if plex_stack has unique features)
- Move: `platform_v2/tools/plex_stack/` → `platform_v2/tools/_deprecated_duplicates/plex_stack/`

**Step 1: Compare modules for unique functionality**

Review plex_stack to identify any routes/features NOT in media_hub.

```bash
# List plex_stack routes
grep -E "@.*\.route\(" /mnt/archie_brain/platform_v2/tools/plex_stack/__init__.py 2>/dev/null || echo "Check routes file"
```

**Step 2: Extract unique features (if any)**

If plex_stack has unique features, add them to media_hub before deprecating.

**Step 3: Move plex_stack to deprecated**

```bash
mv /mnt/archie_brain/platform_v2/tools/plex_stack /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 4: Update module_registry.py**

Comment out plex_stack entry.

**Step 5: Update rbac.py**

Comment out plex_stack permissions.

**Step 6: Verify platform loads**

```bash
docker exec archie_platform python3 -c "from app import app; print('App loads OK')"
```

**Step 7: Commit**

```bash
git add -A && git commit -m "chore: merge plex_stack into media_hub"
```

---

## Phase 4: Merges - Website & Projects

### Task 4.1: Merge site_manager into website_studio

**Files:**
- Read: `platform_v2/tools/site_manager/__init__.py`
- Read: `platform_v2/tools/website_studio/__init__.py`
- Modify: `platform_v2/tools/website_studio/__init__.py` (if site_manager has unique features)
- Move: `platform_v2/tools/site_manager/` → `platform_v2/tools/_deprecated_duplicates/site_manager/`

**Step 1: Compare modules for unique functionality**

Review site_manager for features not in website_studio (especially multi-site hosting for whatthefact.ca etc.)

**Step 2: Add site hosting features to website_studio if missing**

If site_manager has unique hosting/management features, integrate into website_studio.

**Step 3: Move site_manager to deprecated**

```bash
mv /mnt/archie_brain/platform_v2/tools/site_manager /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 4: Update module_registry.py and rbac.py**

**Step 5: Verify and commit**

```bash
git add -A && git commit -m "chore: merge site_manager into website_studio"
```

---

### Task 4.2: Merge project_builder into project_manager

**Files:**
- Read: `platform_v2/tools/project_builder/__init__.py`
- Move: `platform_v2/tools/project_builder/` → `platform_v2/tools/_deprecated_duplicates/project_builder/`

**Step 1: Compare modules**

project_builder is placeholder (872 lines marked "Coming Soon"), project_manager is operational (1,071 lines, Phase 65).

**Step 2: Move project_builder to deprecated**

```bash
mv /mnt/archie_brain/platform_v2/tools/project_builder /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 3: Update registry and permissions**

**Step 4: Verify and commit**

```bash
git add -A && git commit -m "chore: deprecate project_builder (using project_manager)"
```

---

## Phase 5: Merges - Automation

### Task 5.1: Merge goose + automation_services into automations

**Files:**
- Read: `platform_v2/tools/goose/__init__.py`
- Read: `platform_v2/tools/automation_services/__init__.py`
- Read: `platform_v2/tools/automations/__init__.py`
- Modify: `platform_v2/tools/automations/__init__.py`
- Move: `platform_v2/tools/goose/` → `platform_v2/tools/_deprecated_duplicates/goose/`
- Move: `platform_v2/tools/automation_services/` → `platform_v2/tools/_deprecated_duplicates/automation_services/`

**Step 1: Review goose for workflow orchestration features**

Extract any useful workflow/orchestration code.

**Step 2: Review automation_services for n8n integration**

Extract n8n integration code.

**Step 3: Integrate useful features into automations module**

Add workflow + n8n capabilities to automations.

**Step 4: Move deprecated modules**

```bash
mv /mnt/archie_brain/platform_v2/tools/goose /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
mv /mnt/archie_brain/platform_v2/tools/automation_services /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 5: Update registry and permissions**

**Step 6: Verify and commit**

```bash
git add -A && git commit -m "chore: consolidate automation modules (goose + automation_services → automations)"
```

---

## Phase 6: Merges - Development Tools

### Task 6.1: Merge testing_suite into sandbox_manager

**Files:**
- Read: `platform_v2/tools/testing_suite/__init__.py`
- Read: `platform_v2/tools/sandbox_manager/__init__.py`
- Modify: `platform_v2/tools/sandbox_manager/__init__.py`
- Move: `platform_v2/tools/testing_suite/` → `platform_v2/tools/_deprecated_duplicates/testing_suite/`

**Step 1: Extract test discovery and regression testing features from testing_suite**

**Step 2: Add testing capabilities to sandbox_manager**

**Step 3: Move and update**

```bash
mv /mnt/archie_brain/platform_v2/tools/testing_suite /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 4: Verify and commit**

```bash
git add -A && git commit -m "chore: merge testing_suite into sandbox_manager"
```

---

## Phase 7: Merges - AI Command

### Task 7.1: Merge cursor_integration + fine_tuning into bridge

**Files:**
- Read: `platform_v2/tools/cursor_integration/__init__.py`
- Read: `platform_v2/tools/fine_tuning/__init__.py`
- Read: `platform_v2/tools/bridge/__init__.py`
- Modify: `platform_v2/tools/bridge/__init__.py`
- Move: `platform_v2/tools/cursor_integration/` → `platform_v2/tools/_deprecated_duplicates/cursor_integration/`
- Move: `platform_v2/tools/fine_tuning/` → `platform_v2/tools/_deprecated_duplicates/fine_tuning/`

**Step 1: Extract MCP Protocol and IDE integration from cursor_integration**

**Step 2: Extract model fine-tuning/training features from fine_tuning**

**Step 3: Add IDE integration section to bridge**

Bridge should have a new section for external tool connections.

**Step 4: Add agent training section to bridge**

Bridge should handle LLM fine-tuning for agents.

**Step 5: Move deprecated modules**

```bash
mv /mnt/archie_brain/platform_v2/tools/cursor_integration /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
mv /mnt/archie_brain/platform_v2/tools/fine_tuning /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 6: Verify and commit**

```bash
git add -A && git commit -m "chore: consolidate AI tools (cursor_integration + fine_tuning → bridge)"
```

---

## Phase 8: Merges - Team & Business

### Task 8.1: Merge hr_management into team_management

**Files:**
- Read: `platform_v2/tools/hr_management/__init__.py`
- Read: `platform_v2/tools/team_management/__init__.py`
- Modify: `platform_v2/tools/team_management/__init__.py`
- Move: `platform_v2/tools/hr_management/` → `platform_v2/tools/_deprecated_duplicates/hr_management/`

**Step 1: Extract HR features (performance, skills, training, scheduling, wellness)**

**Step 2: Integrate into team_management's IAAE section**

team_management already has IAAE compliance - HR features fit naturally.

**Step 3: Move and update**

```bash
mv /mnt/archie_brain/platform_v2/tools/hr_management /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 4: Verify and commit**

```bash
git add -A && git commit -m "chore: merge hr_management into team_management"
```

---

### Task 8.2: Merge analytics into crm

**Files:**
- Read: `platform_v2/tools/analytics/__init__.py`
- Read: `platform_v2/tools/crm/__init__.py`
- Modify: `platform_v2/tools/crm/__init__.py`
- Move: `platform_v2/tools/analytics/` → `platform_v2/tools/_deprecated_duplicates/analytics/`

**Step 1: Extract business analytics dashboards**

**Step 2: Add analytics section to CRM**

CRM should include:
- Customer analytics
- Sales analytics (from store_builder)
- Subscription tracking
- Business intelligence

**Step 3: Move and update**

```bash
mv /mnt/archie_brain/platform_v2/tools/analytics /mnt/archie_brain/platform_v2/tools/_deprecated_duplicates/
```

**Step 4: Verify and commit**

```bash
git add -A && git commit -m "chore: merge analytics into crm"
```

---

## Phase 9: Update Module Registry & Categories

### Task 9.1: Update module_registry.py with New Categories

**Files:**
- Modify: `platform_v2/module_registry.py`

**Step 1: Reorganize module definitions by category**

Add category comments and update any module metadata to reflect new organization:

```python
# ============================================
# ADMIN OPERATIONS (4 modules)
# ============================================
# backup_manager, security_network, account_center, system_operations

# ============================================
# AI COMMAND (5 modules)
# ============================================
# blueprint, consciousness, team_management, bridge, archie_core

# ============================================
# DEVELOPMENT TOOLS (3 modules)
# ============================================
# code_sentinel, sandbox_manager, improvements

# ============================================
# SAAS SERVICES (9 modules)
# ============================================
# crm, website_studio, store_builder, call_center, email_manager,
# automations, invoicing, scheduler, social_media

# ============================================
# PROJECT & KNOWLEDGE (3 modules)
# ============================================
# project_manager, obsidian_vault, api_docs

# ============================================
# MEDIA & HOME (1 module)
# ============================================
# media_hub

# ============================================
# PLACEHOLDERS - FUTURE (12 modules)
# ============================================
# fitness, therapy, doc, stockbot, game_studio, archie_pool,
# pool_management, task_planner, google_workspace, content_studio,
# media_studio, app_builder
```

**Step 2: Update category metadata in module definitions**

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: reorganize module_registry.py with new category structure"
```

---

### Task 9.2: Update rbac.py Permissions

**Files:**
- Modify: `platform_v2/rbac.py`

**Step 1: Remove deprecated module permissions**

**Step 2: Ensure merged module permissions are correct**

**Step 3: Verify permission structure matches new categories**

**Step 4: Commit**

```bash
git add -A && git commit -m "chore: update rbac.py for consolidated modules"
```

---

## Phase 10: Final Verification

### Task 10.1: Full Platform Verification

**Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

**Step 2: Check for startup errors**

```bash
docker logs archie_platform --tail 50
```

**Step 3: Verify all active modules load**

```bash
docker exec archie_platform python3 -c "
from app import app
print('Routes registered:', len(list(app.url_map.iter_rules())))
print('App loads successfully')
"
```

**Step 4: Test key module endpoints**

```bash
# Test a few critical endpoints
curl -s http://192.168.1.200:3000/tools/blueprint/ | head -1
curl -s http://192.168.1.200:3000/tools/media_hub/ | head -1
curl -s http://192.168.1.200:3000/tools/website_studio/ | head -1
```

**Step 5: Final commit**

```bash
git add -A && git commit -m "feat: complete module consolidation - 51 → 37 active modules"
```

---

## Post-Implementation Summary

### Before Consolidation
- **Total Modules:** 51
- **Duplicates:** Multiple
- **Categories:** Unclear

### After Consolidation
- **Active Modules:** 37
- **Deprecated:** 14 (moved to _deprecated_duplicates)
- **Categories:** 7 clear categories

### Modules Deprecated
1. coderabbit
2. figma
3. plex_stack
4. site_manager
5. project_builder
6. goose
7. automation_services
8. testing_suite
9. cursor_integration
10. fine_tuning
11. hr_management
12. analytics

### Category Distribution
| Category | Count | Modules |
|----------|-------|---------|
| Admin Operations | 4 | backup_manager, security_network, account_center, system_operations |
| AI Command | 5 | blueprint, consciousness, team_management, bridge, archie_core |
| Development Tools | 3 | code_sentinel, sandbox_manager, improvements |
| SaaS Services | 9 | crm, website_studio, store_builder, call_center, email_manager, automations, invoicing, scheduler, social_media |
| Project & Knowledge | 3 | project_manager, obsidian_vault, api_docs |
| Media & Home | 1 | media_hub |
| Placeholders | 12 | fitness, therapy, doc, stockbot, game_studio, archie_pool, pool_management, task_planner, google_workspace, content_studio, media_studio, app_builder |

---

## Rollback Plan

If issues occur, restore from pre-consolidation backup:

```bash
# Restore module_registry.py
cp /mnt/archie_brain/backups/module_registry_pre_consolidation.py /mnt/archie_brain/platform_v2/module_registry.py

# Restore rbac.py
cp /mnt/archie_brain/backups/rbac_pre_consolidation.py /mnt/archie_brain/platform_v2/rbac.py

# Move deprecated modules back
# (Use backup_manager restore if full rollback needed)
```
