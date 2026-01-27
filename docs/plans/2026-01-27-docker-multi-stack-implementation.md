# Docker Multi-Stack Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the Docker tab from a single-stack view into a multi-stack management interface with stack overview cards, detail drill-down, creation wizard, and per-stack actions with two-tier safety.

**Architecture:** The Docker tab gets a two-level navigation: stack overview (grid of stack cards) and stack detail (containers, compose, env, logs per stack). All stack metadata is stored in a `docker_stacks` PostgreSQL table. New per-stack endpoints use `/api/stacks/{name}` prefix. The A.R.C.H.I.E. system stack is auto-seeded with `is_system=TRUE`.

**Tech Stack:** Flask (Python), PostgreSQL (psycopg2), Jinja2 HTML template, vanilla JS, CSS variables (`var(--archie-*)`), Lucide icons, Docker CLI (`docker compose`).

**Design Reference:** `/mnt/archie_brain/docs/plans/2026-01-27-docker-multi-stack-design.md`

---

## Context for All Tasks

### File Locations
- **Routes:** `/mnt/archie_brain/platform_v2/tools/system_operations/routes.py` (1285 lines)
- **Template:** `/mnt/archie_brain/platform_v2/templates/tools/system_operations.html` (4537 lines)
- **SQL scripts:** `/mnt/archie_brain/scripts/`

### Existing Code Patterns
- All API routes use `@system_operations_bp.route(...)`, `@login_required`, `@admin_required`
- DB access: `conn = get_db()`, `cur = conn.cursor(cursor_factory=RealDictCursor)`, always close both
- Audit logging: `audit_log(action_type, target, details={}, success=True, error_message=None)`
- Re-auth: `require_reauth()` returns `None` if OK, or `(jsonify(...), 401)` if not
- Confirm modal: `showConfirmModal(title, message, callback)`
- Re-auth modal: `showReauthModal(operationName, callback)`
- Toast: `showToast('success'|'error', message)`
- Lucide icons: `<i data-lucide="icon-name">` then `lucide.createIcons()` after DOM changes
- CSS: Use `var(--archie-*)` variables from theme.css
- DOM updates: Use `.textContent` for plain text, template literals with DOM element assignment for trusted internal rendering (same pattern used throughout existing codebase)
- `BASE_DIR = /mnt/archie_brain` (A.R.C.H.I.E. stack dir)
- Docker compose: `docker compose -f <path>/docker-compose.yml --project-directory <path>`
- JSON responses: `{"success": True, "data": ...}` or `{"success": False, "error": "..."}`

### Existing Docker Endpoints (kept for backward compatibility)
- `GET /api/docker` - list containers (line 343)
- `POST /api/docker/<id>/action` - container action (line 519)
- `POST /api/docker/compose` - compose up/down/restart/pull (line 551)
- `GET /api/docker/<id>/logs` - container logs (line 597)
- `GET /api/stack/compose` - get compose file (line 625)
- `PUT /api/stack/compose` - save compose file (line 680)
- `GET /api/stack/env` - get env file (line 737)
- `PUT /api/stack/env` - save env file (line 770)

### Existing Docker HTML (lines 1711-1904)
- Overview grid: 4 stat cards (running/stopped/total/images)
- Quick actions bar: Start All, Restart All, Stop All, Refresh
- Container grid: cards with status, image, ports, actions
- Detailed table: ID, Name, Image, Status, Ports, Created, Actions
- Stack section: single "A.R.C.H.I.E. Platform" with compose view/edit/pull
- Env files: .env and platform_v2/.env viewers
- Compose modal: viewer/editor with save and apply+restart

### Existing Docker CSS (lines 899-1222)
- `.docker-overview-grid`, `.docker-stat-card`, `.docker-actions-bar`, `.docker-action-btn`
- `.docker-container-grid`, `.docker-container-card`, `.docker-card-*`
- `.stack-header`, `.stack-info`, `.stack-meta`, `.stack-actions`, `.stack-services-grid`, `.stack-service-card`
- `.env-files-list`, `.env-file-item`

### Existing Docker JS (12 functions starting around line 2739)
- `loadDocker()`: fetches `/api/docker`, calls `renderDocker()`
- `renderDocker(containers)`: renders stat cards + container cards + table
- `dockerAction(id, action)`: confirm modal then POST `/api/docker/{id}/action`
- `dockerComposeAction(action)`: confirm modal then POST `/api/docker/compose`
- `viewDockerLogs(containerId, name)`: opens logs in new tab
- `viewComposeFile()`: loads compose, opens modal
- `editComposeFile()`: opens compose in edit mode
- `toggleComposeEdit()`: switches viewer/editor
- `saveComposeFile()`: PUT to save compose
- `applyComposeChanges()`: save + restart
- `closeComposeModal()`: close with unsaved changes check
- `viewEnvFile(filename)`: loads env file in compose modal
- `renderStackServices(services)`: renders service cards

---

## Phase 1: Database & Backend Foundation

### Task 1: Create docker_stacks Database Table

**Files:**
- Create: `scripts/create_docker_stacks_table.sql`

**Step 1:** Create the SQL migration script at `scripts/create_docker_stacks_table.sql` with:
- `docker_stacks` table: id (SERIAL PK), name (VARCHAR(50) UNIQUE), display_name (VARCHAR(100)), directory (VARCHAR(500)), description (TEXT), color (VARCHAR(7) DEFAULT '#00D4AA'), is_system (BOOLEAN DEFAULT FALSE), created_at (TIMESTAMP DEFAULT NOW()), updated_at (TIMESTAMP DEFAULT NOW())
- Seed the A.R.C.H.I.E. system stack: name='archie', display_name='A.R.C.H.I.E. Platform', directory='/mnt/archie_brain', is_system=TRUE, color='#00D4AA'
- Use `ON CONFLICT (name) DO NOTHING` for idempotent seeding
- Create indexes on `name` and `is_system`

**Step 2:** Run: `docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/scripts/create_docker_stacks_table.sql`

**Step 3:** Verify: `docker exec archie_database psql -U archie -d archie -c "SELECT id, name, display_name, is_system FROM docker_stacks;"`
Expected: 1 row with archie system stack.

**Step 4:** Commit: `git commit -m "feat(docker): add docker_stacks table with A.R.C.H.I.E. seed"`

---

### Task 2: Backend - Stack CRUD API Endpoints

**Files:**
- Modify: `platform_v2/tools/system_operations/routes.py`

Add new endpoints in a new `MULTI-STACK MANAGEMENT ENDPOINTS` section after line 806. Keep all existing endpoints unchanged.

**Step 1: GET /api/stacks** - List all stacks with live container status
- Query `docker_stacks` table ordered by `is_system DESC, display_name ASC`
- For each stack, run `docker compose -f <dir>/docker-compose.yml --project-directory <dir> ps --format json` to get live container counts
- Parse JSON lines output, count running vs total containers
- Set `status` field: "running" (all running), "partial" (some running), "stopped" (none), "unknown" (error)
- Return `{"success": true, "data": [stacks...]}`

**Step 2: POST /api/stacks** - Create new stack
- Accept: name, display_name, description, color, compose_content, env_content
- Validate name: lowercase alphanumeric + hyphens only, regex `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- Stack directory: `/mnt/stacks/{name}` - check doesn't exist, then `os.makedirs()`
- If compose_content provided: validate YAML with `yaml.safe_load()`, write `docker-compose.yml`
- If env_content provided: write `.env`
- INSERT into `docker_stacks`, RETURNING the new row
- On validation failure, clean up directory with `shutil.rmtree()`
- Audit log the creation
- Return 201 with stack data

**Step 3: GET /api/stacks/{name}** - Get stack detail with containers
- Query `docker_stacks` by name, 404 if not found
- Get containers via `docker compose ps --format json -a`
- Return stack data with `containers` array, `containers_running`, `containers_total`

**Step 4: DELETE /api/stacks/{name}** - Delete stack
- Require confirmation (`data.get("confirm")`)
- Look up stack, 404 if not found, 403 if `is_system`
- Stop containers first: `docker compose -f <file> --project-directory <dir> down`
- DELETE from database
- Optionally remove directory if `remove_files=True` AND path starts with `/mnt/stacks/` (safety check)
- Audit log the deletion

**Step 5:** Commit: `git commit -m "feat(docker): add multi-stack CRUD API endpoints"`

---

### Task 3: Backend - Per-Stack Action, Compose, Env, and Logs Endpoints

**Files:**
- Modify: `platform_v2/tools/system_operations/routes.py`

Add after Task 2 endpoints.

**Step 1: POST /api/stacks/{name}/action** - Execute compose action
- Accept: `action` (up/down/restart/pull), `confirm` flag
- Look up stack from DB
- System stack + destructive action (down/restart/pull) requires `require_reauth()`
- Build command: `docker compose -f <compose_file> --project-directory <dir> <action>` (add `-d` for up)
- Run with `subprocess.run()`, timeout=120
- Audit log the result

**Step 2: GET /api/stacks/{name}/compose** - Get compose file
- Look up stack directory
- Read `docker-compose.yml`, get modification time
- Parse YAML to extract services list
- Check running containers to determine service status (check multiple naming patterns: `{name}-{svc}-1`, `{name}_{svc}_1`, `archie_brain-{svc}-1` for system stack)
- Return content, modified time, services array, is_system flag

**Step 3: PUT /api/stacks/{name}/compose** - Save compose file
- System stack requires `require_reauth()`
- Validate YAML content
- Create backup with timestamp suffix
- Write new content
- Audit log

**Step 4: GET /api/stacks/{name}/env** - Get env files
- Read `.env` from stack directory
- For system stack, also include `platform_v2/.env`
- Return array of env file objects with filename, path, content, modified time

**Step 5: PUT /api/stacks/{name}/env** - Save env file
- System stack requires `require_reauth()`
- Accept `filename` (.env or platform_v2/.env for system)
- Verify path is within stack directory (prevent traversal)
- Create backup, write content, audit log

**Step 6: GET /api/stacks/{name}/logs** - Get stack logs
- Accept query params: `tail` (default 100), `service` (optional)
- Run `docker compose -f <file> --project-directory <dir> logs --tail <n> --no-color [service]`
- Return as plain text Response

**Step 7:** Commit: `git commit -m "feat(docker): add per-stack action, compose, env, logs endpoints"`

---

## Phase 2: Frontend - Stack Overview

### Task 4: CSS - Stack Overview Cards, Detail View, and Wizard Styles

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (CSS block)

Add new CSS after the existing Stack Management Styles section (after `.env-file-item:hover` rule, approximately line 1245). Keep all existing Docker CSS intact.

**New CSS classes to add:**
- **Stack Overview:** `.stack-overview-header`, `.stack-overview-grid` (auto-fill grid, min 320px), `.stack-card` (bg-secondary, border, 12px radius, cursor pointer, hover lift, `::before` pseudo-element for color accent bar at top using `var(--stack-color)`), `.stack-card-header`, `.stack-card-name`, `.stack-card-badges`, `.badge.system`, `.stack-card-desc`, `.stack-card-stats`, `.stack-card-footer`, `.stack-card-actions`, `.stack-card-btn`
- **Detail View:** `.stack-detail-view` (hidden by default, `.active` shows), `.stack-detail-header`, `.stack-detail-title`, `.stack-color-dot`, `.stack-back-btn`, `.stack-detail-sections`
- **Sub-tabs:** `.stack-subtabs` (flex, bg-secondary, rounded), `.stack-subtab` (transparent bg, `.active` gets accent bg), `.stack-subtab-content` (hidden, `.active` shows)
- **New Stack Button:** `.new-stack-btn` (accent bg, black text, bold)
- **Wizard:** `.wizard-overlay` (fixed overlay, `.active` shows), `.wizard-dialog` (bg-primary, 700px max, 85vh max, overflow scroll), `.wizard-steps` (flex centered), `.wizard-step-indicator` (circle, `.active`=accent, `.completed`=green), `.wizard-step-line` (divider, `.completed`=green), `.wizard-content`, `.wizard-footer`, `.wizard-field`, `.wizard-field label/input/textarea/select`, `.color-picker-grid`, `.color-swatch` (32px circle, `.selected` border, hover scale)

Use existing patterns: transitions, hover effects, archie CSS variables, border-radius values from existing docker styles.

**Commit:** `git commit -m "feat(docker): add CSS for multi-stack overview, detail view, wizard"`

---

### Task 5: HTML - Stack Overview & Detail View Structure

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (HTML block)

Replace lines 1711-1870 (everything inside `<div id="tab-docker">` up to but NOT including the compose modal at line 1872). The compose modal (lines 1872-1904) stays unchanged.

**New HTML structure for `tab-docker`:**

1. **Stack Overview section** (`#docker-stack-overview`):
   - Stat cards row (same 4 cards but 4th changes from "Images" to "Stacks" with id `docker-stacks-count`)
   - Section title with "Stacks" label and "New Stack" button (onclick=`openCreateStackWizard()`)
   - Stack overview grid (`#stack-overview-grid`) with loading placeholder

2. **Stack Detail View** (`#docker-stack-detail`, class `stack-detail-view`):
   - Detail header: back button (onclick=`showStackOverview()`), color dot, stack name, system badge, action buttons
   - Sub-tabs bar: Containers, Compose, Environment, Logs
   - **Containers sub-tab** (`#subtab-containers`): actions bar (Start All / Restart All / Stop All / Pull / Refresh using `stackAction()`) + container grid (`#stack-container-grid`)
   - **Compose sub-tab** (`#subtab-compose`): panel with compose path, services count, View/Edit buttons, services grid (`#detail-services-grid`)
   - **Environment sub-tab** (`#subtab-env`): panel with env files list (`#detail-env-files`)
   - **Logs sub-tab** (`#subtab-logs`): service selector dropdown, tail selector, refresh button, pre element for log output (`#stack-log-output`)

**Commit:** `git commit -m "feat(docker): add multi-stack overview and detail view HTML"`

---

### Task 6: HTML - Stack Creation Wizard Modal

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (HTML block)

Insert wizard modal after compose modal (line ~1904), before `<!-- Tab: Network -->`.

**Wizard structure** (`#createStackWizard`, class `wizard-overlay`):
- Dialog with title "Create New Stack"
- Step indicators: 4 circles with connecting lines
- **Step 1** (Name): name input (with slug auto-update and directory preview), display name, description, color picker (8 color swatches)
- **Step 2** (Compose): textarea for docker-compose.yml content
- **Step 3** (Environment): textarea for .env content
- **Step 4** (Review): summary panel populated by JS
- Footer: Cancel button, Previous button (hidden on step 1), Next/Create button

**Commit:** `git commit -m "feat(docker): add stack creation wizard modal HTML"`

---

## Phase 3: Frontend - JavaScript

### Task 7: JavaScript - Stack Data Loading & Overview Rendering

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (JS block)

**Step 1:** Add state variables before loadDocker():
```javascript
let currentStackName = null;
let stacksData = [];
```

**Step 2:** Replace `loadDocker()` (line 2739) to fetch from `/api/stacks` instead of `/api/docker`, and call `renderStackOverview()` instead of `renderDocker()`.

**Step 3:** Replace `renderDocker()` (line 3751) with `renderStackOverview(stacks)`:
- Sum running/stopped across all stacks for global stat cards
- Set `docker-stacks-count` to number of stacks
- Render stack cards using template literals into `#stack-overview-grid`
- Each card: color accent bar (CSS `--stack-color`), display name, system badge, description, container count, directory, quick action buttons (play/restart/stop onclick=`quickStackAction()` with `event.stopPropagation()` to prevent card click)
- Call `lucide.createIcons()` after rendering

**NOTE on DOM rendering:** Follow the same trusted-source template literal pattern used throughout the existing codebase (e.g., the existing `renderDocker()` at line 3764, `renderNetwork()` at line 3896, etc.). All data comes from the authenticated API endpoint, not user input.

**Commit:** `git commit -m "feat(docker): add stack overview loading and rendering JS"`

---

### Task 8: JavaScript - Stack Detail View Navigation & Rendering

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (JS block)

Add after `renderStackOverview()`. Functions to implement:

1. `showStackOverview()` - Set currentStackName=null, show overview div, hide detail div, call loadDocker()
2. `openStackDetail(stackName)` - Set currentStackName, hide overview, show detail, activate containers sub-tab, call loadStackDetail()
3. `showStackSubtab(tabName)` - Toggle sub-tab active states, load tab data (compose/env/logs on demand)
4. `loadStackDetail(stackName)` - Fetch `/api/stacks/{name}`, update header (name, color, badges, actions), render containers
5. `renderStackContainers(containers)` - Render container cards into `#stack-container-grid` using existing card CSS. Note: `docker compose ps --format json` returns fields: `Name`, `Service`, `Image`, `State`, `Ports`, `Status`, `ID`
6. `loadStackCompose()` - Fetch `/api/stacks/{name}/compose`, update compose path, services count, render service cards
7. `renderStackServices(services)` - Replaces the existing function at line 4511. Target `#detail-services-grid`.
8. `loadStackEnv()` - Fetch `/api/stacks/{name}/env`, render env file list items with onclick=`viewStackEnvFile()`
9. `loadStackLogs()` - Fetch `/api/stacks/{name}/logs` with service filter and tail params, display in pre element
10. `viewStackCompose()` - Open compose modal for current stack (like existing viewComposeFile but using stack endpoint)
11. `editStackCompose()` - Open compose modal in edit mode for current stack
12. `viewStackEnvFile(stackName, filename)` - Open env file in compose modal (masked passwords in view mode)

**Commit:** `git commit -m "feat(docker): add stack detail view navigation and rendering JS"`

---

### Task 9: JavaScript - Stack Actions (Two-Tier Safety)

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (JS block)

Functions to implement:

1. `quickStackAction(stackName, action, isSystem)` - If system stack + destructive action (down/restart/pull), use `showReauthModal()`. Otherwise use `showConfirmModal()`. Both call `executeStackAction()`.
2. `stackAction(action)` - Wrapper that gets current stack's is_system flag from stacksData, calls quickStackAction
3. `executeStackAction(stackName, action)` - POST to `/api/stacks/{name}/action`, handle success (reload after 2s), handle requires_reauth response (show re-auth modal and retry), handle errors
4. `deleteStack(stackName)` - Confirm modal, DELETE to `/api/stacks/{name}`, on success call showStackOverview()
5. Update `saveComposeFile()` (line 4370) - If `currentStackName` is set, use PUT `/api/stacks/{name}/compose` instead of old endpoint. Handle `requires_reauth` response.

**Commit:** `git commit -m "feat(docker): add stack actions with two-tier safety"`

---

### Task 10: JavaScript - Stack Creation Wizard

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (JS block)

State variables and functions:

1. `wizardStep = 1`, `wizardColor = '#00D4AA'`
2. `openCreateStackWizard()` - Reset all wizard fields, set step 1, show overlay
3. `closeCreateStackWizard()` - Hide overlay
4. `updateWizardSlug()` - Sanitize name input (lowercase, alphanumeric + hyphens), update directory preview
5. `selectWizardColor(el)` - Toggle selected class on color swatches, update wizardColor
6. `updateWizardStepUI()` - Show/hide step content divs, update step indicators (active/completed), update prev/next buttons, on step 4 change next button to "Create Stack"
7. `wizardNext()` - Validate current step (step 1: name + display name required), on step 4 call createStack(), otherwise increment step
8. `wizardPrev()` - Decrement step
9. `updateWizardReview()` - Populate review content with summary of all fields
10. `createStack()` - POST to `/api/stacks` with all wizard data, on success toast + close wizard + reload stacks

Also add `closeCreateStackWizard()` to the existing Escape key handler (line 4175).

**Commit:** `git commit -m "feat(docker): add stack creation wizard JS"`

---

## Phase 4: Integration & Polish

### Task 11: Update Existing Docker Functions for Multi-Stack Compatibility

**Files:**
- Modify: `platform_v2/templates/tools/system_operations.html` (JS block)

**Step 1:** Update `dockerComposeAction()` (line 3833) - If `currentStackName` is set, delegate to `stackAction()` and return early. Otherwise keep existing behavior.

**Step 2:** Update `viewComposeFile()` (line 4290) - If `currentStackName` is set, call `viewStackCompose()` and return. Otherwise keep existing behavior.

**Step 3:** Update `viewEnvFile()` (line 4468) - If `currentStackName` is set, call `viewStackEnvFile()` and return. Otherwise keep existing behavior.

**Step 4:** Check auto-refresh integration - The periodic refresh calls `loadDocker()` which now loads stack data. When in detail view (`currentStackName` is set), also refresh the detail: add `if (currentStackName) loadStackDetail(currentStackName);` after the loadDocker call in the refresh interval.

**Step 5:** Remove the old detailed table section from the HTML since it's replaced by the stack detail view. (Lines 1789-1811 in old HTML, but this was already handled in Task 5.)

**Commit:** `git commit -m "feat(docker): update existing Docker functions for multi-stack"`

---

### Task 12: Directory Setup, Restart, and Final Verification

**Files:** No code changes (unless fixes needed)

**Step 1:** Create `/mnt/stacks` directory if it doesn't exist:
```bash
sudo mkdir -p /mnt/stacks
sudo chown $(whoami):$(whoami) /mnt/stacks
```

**Step 2:** Restart platform:
```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
```

**Step 3:** API verification:
```bash
curl -s -b /tmp/archie_cookies.txt http://192.168.1.200:3000/tools/system-operations/api/stacks | python3 -m json.tool
```
Expected: success=true, data contains A.R.C.H.I.E. stack with container counts.

**Step 4:** Visual verification with Playwright:
- Navigate to System Operations, click Docker tab
- Verify: stack overview grid with A.R.C.H.I.E. card, SYSTEM badge, container count, color accent
- Click card: detail view loads with containers, sub-tabs work
- "New Stack" button opens wizard, wizard steps navigate correctly
- Back button returns to overview
- Quick action buttons on overview cards trigger appropriate modals

**Step 5:** Commit any final fixes.

---

## Summary

| # | Task | Phase | Description |
|---|------|-------|-------------|
| 1 | DB Table | Phase 1 | Create `docker_stacks` table + seed A.R.C.H.I.E. |
| 2 | CRUD API | Phase 1 | GET/POST/DELETE `/api/stacks` endpoints |
| 3 | Stack APIs | Phase 1 | Action, compose, env, logs per-stack endpoints |
| 4 | CSS | Phase 2 | Stack overview cards, detail view, wizard styles |
| 5 | HTML Overview | Phase 2 | Stack overview grid + detail view structure |
| 6 | HTML Wizard | Phase 2 | Stack creation wizard modal |
| 7 | JS Overview | Phase 3 | Stack data loading + overview rendering |
| 8 | JS Detail | Phase 3 | Detail view navigation, containers, compose, env, logs |
| 9 | JS Actions | Phase 3 | Stack actions with two-tier safety |
| 10 | JS Wizard | Phase 3 | Creation wizard state management |
| 11 | JS Integration | Phase 4 | Update existing functions for multi-stack compat |
| 12 | Final Test | Phase 4 | Directory setup, restart, API + visual verification |
