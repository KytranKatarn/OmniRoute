# A.R.C.H.I.E. Platform - Dashboard Architecture

**Last Updated:** 2026-01-12
**Status:** Active Development
**Version:** 2.0.0

---

## Overview

The A.R.C.H.I.E. platform has a **modular architecture** with a central Dashboard serving as the main tool selection interface. Tools are organized into four categories and dynamically loaded from the Module Registry.

---

## Dashboard Architecture

### Main Dashboard
- **URL:** `http://localhost:3000/dashboard`
- **Route:** `/dashboard`
- **Access:** All authenticated users (`@login_required`)
- **Purpose:** Main tool selection interface with Matrix-style UI
- **Template:** `templates/dashboard.html`

### Module Categories (4 sections)

#### 1. CREATION TOOLS
Tools for building apps, websites, games, and media content.

| Module | Route | Status | Description |
|--------|-------|--------|-------------|
| Website Builder | `/tools/website-builder` | BETA | Build and deploy websites with AI assistance |
| App Builder | `/tools/app-builder` | BETA | Build web applications from natural language |
| Game Builder | `/tools/game-builder` | Coming Soon | Build games with AI-powered tools |
| Picture Generation | `/tools/picture-generation` | Coming Soon | AI image generation |
| Video Generation | `/tools/video-generation` | Coming Soon | Promotional videos and audio |
| Story Generation | `/tools/story-generation` | Coming Soon | Create books and collections |

#### 2. DEVELOPMENT TOOLS
Tools for coding, editing, and collaboration.

| Module | Route | Status | Description |
|--------|-------|--------|-------------|
| Code Editor | `/tools/code-editor` | ACTIVE | VS Code integration, syntax highlighting |
| Team Directory | `/directory` | ACTIVE | 58 AI specialists directory |
| A.R.C.H.I.E. Chat | `/tools/archie-chat` | ACTIVE | Chat with A.R.C.H.I.E. assistant |
| Cursor Integration | `/tools/cursor-integration` | Coming Soon | IDE integration API |
| GitHub Manager | `/tools/github-manager` | Coming Soon | Repository management UI |

#### 3. ADMIN TOOLS (Admin Only)
System management, analytics, and consciousness tools.

| Module | Route | Status | Description |
|--------|-------|--------|-------------|
| A.R.C.H.I.E. Blueprint | `/tools/blueprint` | ACTIVE | Platform architecture & roadmap |
| Consciousness | `/tools/consciousness` | ACTIVE | Knowledge analytics, memory insights |
| Improvements Lab | `/tools/improvements-lab` | ACTIVE | AI-powered self-improvement workflow |
| Backup Manager | `/tools/backup-manager` | ACTIVE | System backups and restore |
| Sandbox Manager | `/tools/sandbox-manager` | Coming Soon | Testing environment control |
| Analytics Dashboard | `/tools/analytics-dashboard` | Coming Soon | Platform metrics and insights |

#### 4. INTEGRATIONS
External services and automation tools.

| Module | Route | Status | Description |
|--------|-------|--------|-------------|
| Social Media | `/tools/social-media` | Coming Soon | Auto posting, multi-platform |
| Archie Pool | `/tools/archie-pool` | Coming Soon | Crypto mining integration |
| Automations | `/tools/automations` | Coming Soon | n8n workflow automation |

---

## Module Registry System

All modules are defined in `/mnt/archie_brain/platform_v2/module_registry.py`

### Module Definition Structure
```python
ModuleDefinition(
    id="module_id",
    name="Display Name",
    description="Short description",
    icon="emoji",
    category=ModuleCategory.ADMIN,
    route="/tools/module-route",
    blueprint_import="tools.module.routes:module_bp",
    required_permissions=["permission:name"],
    minimum_role="ADMIN",
    enabled=True,
    beta=False,
    coming_soon=False,
    health_check=lambda: health_check_function(),
    priority=1,
    tags=["tag1", "tag2"]
)
```

### Role Hierarchy
```
PUBLIC (0) < USER (10) < PREMIUM (20) < ADMIN (90) < SUPER_ADMIN (100)
```

---

## Standalone Modules (Recent Migration)

The following modules were migrated from embedded Admin sections to standalone modules:

### Consciousness Module
- **Old Location:** Previously embedded in admin (now standalone)
- **New Location:** `/tools/consciousness`
- **Features:**
  - Knowledge analytics dashboard
  - Memory insights and tracking
  - Claude Code session tracking
  - Conversation memory sources breakdown
  - Learning resources management

### Improvements Lab Module
- **Old Location:** Previously embedded in admin (now standalone) (`section-improvements`)
- **New Location:** `/tools/improvements-lab`
- **Features:**
  - Chat with A.R.C.H.I.E. about improvements
  - Workflow automation
  - Proposal management (filter, approve, reject)
  - Team assignments
  - Sandbox testing
  - Deployment tracking

### Backup Manager Module
- **Old Location:** Previously embedded in admin (now standalone)
- **New Location:** `/tools/backup-manager`
- **Features:**
  - Quick backup buttons (Full, Critical, Database)
  - Custom backup with 10 component selection
  - Build number tracking
  - Estimated size/time calculation
  - Backup history and restore

---

## Admin Modules (Modular Architecture)

After migration, the standalone admin modules now focuses on:

1. **User Management** - Approve signups, reset passwords
2. **Agents Management** - View/edit/execute AI agents
3. **Directory Management** - Agent directory configuration
4. **System Configuration** - API settings, provider configuration
5. **GitHub Integration** - Repository management
6. **Analytics** - Basic platform metrics
7. **Billing** - Subscription management (placeholder)
8. **Store** - Printful integration (placeholder)
9. **Security** - Network health, audit logging

**Removed from Admin (now standalone):**
- ~~Consciousness section~~
- ~~Improvements section~~
- ~~Backup Manager section~~

---

## Route Structure

### Public Routes
```
/                        → Login page (or redirect to dashboard)
/login                   → Login form
/signup                  → User registration (requires admin approval)
/logout                  → Logout
/health                  → Health check endpoint
```

### Dashboard Routes
```
/dashboard               → Main tool grid interface
/directory               → Team Directory (Agent listing)
```

### Standalone Module Routes
```
/tools/consciousness/         → Consciousness dashboard
/tools/improvements-lab/      → Improvements Lab
/tools/backup-manager/        → Backup Manager
/tools/code-editor/           → Code Editor
/tools/archie-chat/           → A.R.C.H.I.E. Chat
/tools/website-builder/       → Website Builder (BETA)
/tools/app-builder/           → App Builder (BETA)
```

### Admin Routes
```
/tools/blueprint/             → A.R.C.H.I.E. Blueprint (architecture)
/tools/consciousness/         → Consciousness (knowledge management)
/tools/team-management/       → Team Management (agents)
/tools/improvements-lab/      → Improvements Lab (AI workflow)
/tools/backup-manager/        → Backup Manager
```

---

## Knowledge Base Integration

The Consciousness module tracks all knowledge sources:

| Source Type | Description | Count (approx) |
|-------------|-------------|----------------|
| n8n | Workflow templates | 2,074 |
| general | General documentation | 341 |
| conversation_memory | Chat histories | 291 |
| vault_note | Obsidian documentation | 125+ |
| claude_code_hook | Claude Code session checkpoints | 3+ |
| archie-development | Development docs | 7 |
| archie-agents | Agent documentation | 6 |
| archie-core | Core system docs | 5 |
| archie-workflows | Workflow documentation | 3 |

---

## File Locations

### Core Application
- Main App: `/mnt/archie_brain/platform_v2/app.py`
- Module Registry: `/mnt/archie_brain/platform_v2/module_registry.py`
- Dashboard Template: `/mnt/archie_brain/platform_v2/templates/dashboard.html`

### Standalone Modules
- Consciousness: `/mnt/archie_brain/platform_v2/tools/consciousness/`
- Improvements Lab: `/mnt/archie_brain/platform_v2/tools/improvements/`
- Backup Manager: `/mnt/archie_brain/platform_v2/tools/backup_manager/`
- Code Editor: `/mnt/archie_brain/platform_v2/tools/code_editor/`

### Templates
- Dashboard: `templates/dashboard.html`
- Admin: `templates/ (now modular templates)`
- Consciousness: `templates/tools/consciousness_dashboard.html`
- Improvements Lab: `templates/tools/improvements_lab.html`
- Backup Manager: `templates/admin/backup_manager.html`

---

## Claude Code Integration

### Pre-Compact Hook
Automatically saves conversation checkpoints to the knowledge base when context reaches ~80%.

- **Hook Location:** `/mnt/archie_brain/platform_v2/scripts/hooks/pre_compact_hook.sh`
- **Saves To:** `knowledge_base` table with `source_type = 'claude_code_hook'`
- **Viewable In:** Consciousness module → Analytics → Claude Code Sessions

### Session End Hook
Saves session summary when conversation ends.

- **Hook Location:** `/mnt/archie_brain/platform_v2/scripts/hooks/session_end_hook.sh`

---

## Access URLs Summary

| Interface | URL | Access Level |
|-----------|-----|--------------|
| Login | http://localhost:3000/login | Public |
| Dashboard | http://localhost:3000/dashboard | Authenticated Users |
| Admin Panel | http://localhost:3000/dashboard | Admins Only |
| Consciousness | http://localhost:3000/tools/consciousness | Admins Only |
| Improvements Lab | http://localhost:3000/tools/improvements-lab | Admins Only |
| Backup Manager | http://localhost:3000/tools/backup-manager | Admins Only |
| Team Directory | http://localhost:3000/directory | Authenticated Users |
| Code Editor | http://localhost:3000/tools/code-editor | Authenticated Users |
| A.R.C.H.I.E. Chat | http://localhost:3000/tools/archie-chat | Authenticated Users |

---

**Documentation maintained by:** A.R.C.H.I.E. with Claude Code
**Last Updated:** 2026-01-12
