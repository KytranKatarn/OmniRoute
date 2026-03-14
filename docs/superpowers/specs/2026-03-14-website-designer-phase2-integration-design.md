# Website Designer Phase 2: Integration & Deployment — Design Spec

## Overview

Complete the Website Designer's backend integration layer and enhance the frontend with deployment capabilities, Hostinger domain management, and an upgraded AI chat system. Also folds in Phase 3 cleanup (double decorators, silent exceptions, missing DB columns).

**Goal:** Create the missing `hostinger_integration.py` and `github_deployment.py` files that routes.py already imports, upgrade AI chat to project-aware role-based dispatch with persistent conversation history in a resizable drawer, add deployment UI, and fix backend bugs.

## Scope

Five capabilities:
1. **Hostinger integration** — HostingerAPI class with mock mode, domain/DNS management
2. **GitHub deployment** — GitHub Pages deploy, commit+push, deployment history
3. **Enhanced AI chat** — whole-project context, role-based agent dispatch, resizable drawer, conversation history persistence
4. **Deployment UI** — deploy button, status indicators, Hostinger domain panel
5. **Backend cleanup** — fix double decorators, silent exceptions, missing columns

## Database Migration

### Add missing columns

```sql
ALTER TABLE website_deployments
ADD COLUMN IF NOT EXISTS deployment_url VARCHAR(500);

ALTER TABLE website_builder_projects
ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
```

`chat_history` stores array of `{role, message, timestamp}` objects, last 50 messages per project.

## Hostinger Integration

**New file:** `platform_v2/tools/website_studio/hostinger_integration.py` (~120 lines)

### `HostingerAPI` class

```python
class HostingerAPI:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.base_url = "https://api.hostinger.com/v2"
        self.mock_mode = not bool(api_key)
```

Methods (matching existing route calls):
- `is_configured()` — returns True if api_key set
- `list_domains()` — GET /domains or mock response with sample domains
- `get_dns_records(domain)` — GET /domains/{domain}/dns or mock
- `add_dns_record(domain, record_type, name, content, ttl)` — POST or mock
- `update_dns_record(domain, record_id, data)` — PUT or mock
- `delete_dns_record(domain, record_id)` — DELETE or mock
- `apply_preset(domain, preset_type)` — add common DNS records for "github_pages" or "custom" presets

Mock mode returns realistic sample data with `[MOCK]` flag. All HTTP calls use `requests` with `Authorization: Bearer {api_key}` header.

### `get_hostinger_api(user_id)` factory

Loads API key from `user_integrations` table (`service='hostinger'`, `credentials->>'api_key'`). Returns `HostingerAPI(api_key)` or `HostingerAPI()` for mock mode.

## GitHub Deployment

**New file:** `platform_v2/tools/website_studio/github_deployment.py` (~80 lines)

### Functions (matching existing route imports)

**`deploy_website(user_id, project_id=None)`**
1. Load GitHub token from `user_integrations` WHERE `service='github'`
2. Call `ensure_repo_cloned()` from chat_handler
3. Call `auto_commit_changes("Deploy from Website Designer")` from chat_handler
4. `git push origin main` via subprocess
5. Enable GitHub Pages via GitHub API: `PUT /repos/{owner}/{repo}/pages` with `source: {branch: "main"}`
6. Insert/update `website_deployments` row with status, `deployment_url`
7. Return `{success, url, commit_hash}`

**`auto_commit_and_push(message="Auto-deploy", repo_path=None)`**
Wrapper around chat_handler's `auto_commit_changes()` + git push.

**`get_deployment_history(project_id)`**
Query `website_deployments` for project, ordered by `created_at DESC`.

All git operations reuse chat_handler.py functions — no duplicate logic.

## Enhanced AI Chat

**Modified file:** `platform_v2/tools/website_studio/chat_handler.py` (add ~60 lines)

### Role detection

**`detect_task_role(message)`** — keyword-based classification:
- Design keywords (color, font, css, layout, responsive, etc.) → `'design'` → prefer Pixel agent
- Deploy keywords (deploy, publish, github pages, domain, etc.) → `'deploy'` → handled by deploy routes
- Default → `'engineering'` → prefer Nexus agent

### Modified dispatch

Update `chat_with_archie()` to pass `prefer_agent` based on detected role. Bridge dispatch selects appropriate agent.

### Chat history persistence

**`save_chat_history(project_id, history)`** — UPDATE projects SET chat_history, keep last 50 messages.

**`load_chat_history(project_id)`** — SELECT chat_history from projects, return list.

## Frontend

### Chat drawer

Upgrade inline chat bar to expandable resizable drawer:
- Default: just input bar (Phase 1 behavior)
- Toggle button expands upward showing conversation history
- Draggable top edge (100px–400px height)
- Messages with role labels and timestamps
- Clear button to reset
- Project-scoped: switch project = switch history

### Deployment UI

Deploy button in toolbar opens dropdown:
- GitHub Pages: one-click deploy button
- Status indicator: last deploy status + URL link
- Deploy history list
- Hostinger section (if configured or mock)

### Hostinger domain panel

Shown in deploy dropdown when Hostinger available:
- Domain list from API
- Per-domain DNS records table
- Add/edit/delete DNS record forms
- Preset buttons (GitHub Pages DNS setup)
- Mock mode banner: "Demo mode — connect API key in Settings"

### JS additions (~150 lines)

- `toggleChatDrawer()` — expand/collapse
- `loadChatHistory(projectId)` — fetch + render
- `saveChatMessage(role, text)` — append + persist
- Upgrade `sendAiChat()` — send project_id, handle role-based responses
- `openDeployPanel()` — show deploy options
- `deployToGitHub()` — POST deploy, show result
- `loadHostingerDomains()` — GET domains, render
- `loadDnsRecords(domain)` — GET records, render table
- `addDnsRecord(domain)` — POST record
- Chat drawer drag resize

### CSS additions (~40 lines)

- `.ws-ai-drawer` — resizable, max-height 400px
- `.ws-ai-drawer-handle` — drag handle
- `.ws-deploy-panel` — dropdown
- `.ws-deploy-btn` — toolbar button
- `.ws-domain-list`, `.ws-dns-table` — Hostinger UI
- `.ws-mock-banner` — orange warning

## Backend Cleanup

### Double decorators

Remove duplicate `@admin_required` stacking on deploy routes in routes.py. Keep single `@login_required` + `@admin_required` where admin is required.

### Silent exceptions

Replace bare `except Exception: pass` in DB cleanup blocks (~20 locations) with `except Exception: logger.debug("cleanup error", exc_info=True)`. At minimum, log something so failures aren't invisible.

### NOT in scope

- DB connection pattern change (`get_db_connection` → `get_db_cursor`) — too many locations, separate effort
- Full route refactoring

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/158_website_designer_phase2.sql` | deployment_url + chat_history columns |
| **Create** | `platform_v2/tools/website_studio/hostinger_integration.py` | HostingerAPI class + mock mode (~120 lines) |
| **Create** | `platform_v2/tools/website_studio/github_deployment.py` | GitHub Pages deploy + history (~80 lines) |
| **Modify** | `platform_v2/tools/website_studio/chat_handler.py` | Role detection + chat persistence (~60 lines) |
| **Modify** | `platform_v2/tools/website_studio/routes.py` | Fix double decorators + silent exceptions (~20 lines) |
| **Modify** | `platform_v2/templates/tools/website_studio.html` | Deploy button + Hostinger panel + chat drawer HTML |
| **Modify** | `platform_v2/static/js/website-studio.js` | Chat drawer + deploy + Hostinger JS (~150 lines) |
| **Modify** | `platform_v2/static/css/website-studio.css` | Chat drawer + deploy + domain CSS (~40 lines) |

**Total:** ~470 lines new code, ~80 lines modifications

## Dependencies

- `requests` library (already available)
- Hostinger API v2 (when API key configured)
- GitHub API (when token configured)

## Scope constraints

- Hostinger in mock mode until API key configured
- No Vercel/Netlify/Cloudflare deployment
- No real-time collaborative editing
- No Git branch management (push to main only)
- No custom SSL provisioning
