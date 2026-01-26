# A.R.C.H.I.E. Platform - Module Registry Status

**Last Updated:** 2026-01-21 (Phase 55 - Goose Orchestration Complete)
**Source:** `/mnt/archie_brain/platform_v2/module_registry.py`

---

## Overview

The A.R.C.H.I.E. platform uses a centralized module registry system for:
- Dashboard module rendering
- Role-based access control
- Health monitoring
- Dynamic blueprint loading
- MCP Server integration (39 tools)
- Goose workflow orchestration

**Total Modules:** 37
- **Live/Enabled:** 33
- **Coming Soon:** 4

---

## Module Categories

| Category | Description | Module Count |
|----------|-------------|--------------|
| `CREATION` | Build apps, websites, games, media | 6 (6 live) |
| `DEVELOPMENT` | Code, edit, test, collaborate | 8 (7 live, 1 coming soon) |
| `BUSINESS_TOOLS` | Full business suite | 11 (10 live, 1 disabled) |
| `STANDALONE_APPS` | Health, wellness, finance apps | 6 (6 live) |
| `ADMIN` | System management (admin only) | 12 (12 live) |
| `INTEGRATIONS` | External services | 2 (0 live, 2 coming soon) |

---

## Live Modules (24)

### CREATION TOOLS (Phase 43 Complete - 2026-01-19)

| Module | Route | Blueprint | Description | Role |
|--------|-------|-----------|-------------|------|
| **Project Builder** | `/tools/project-builder` | `project_builder_bp` | Build web applications from natural language. Full stack, AI-assisted | USER |
| **Game Studio** | `/tools/game-studio` | `game_studio_bp` | Build games with AI tools. 2D/3D, scene editor, assets, AI assistant | USER |
| **Media Studio** | `/tools/media-studio` | `media_studio_bp` | Create images, videos & shorts with AI. Multiple styles, export ready | USER |
| **Content Studio** | `/tools/content-studio` | `content_studio_bp` | AI writing for books, articles & copy. Templates, export, version history | USER |
| **Figma Integration** | `/tools/figma` | `figma_bp` | Import designs from Figma. AI conversion to code, component mapping | USER |

### DEVELOPMENT TOOLS

| Module | Route | Blueprint | Description | Role |
|--------|-------|-----------|-------------|------|
| **Code Editor** | `/tools/code-editor` | `code_editor_bp` | Edit code directly in browser. VS Code integration, syntax highlighting, NL code generation | USER |
| **Business Directory** | `/business/directory` | `business_bp` | Public team directory. AI & Human employees, company directory | PUBLIC |
| **A.R.C.H.I.E. Chat** | `/tools/archie-chat` | `archie_chat_bp` | Chat with A.R.C.H.I.E. AI assistant. Emotional awareness, memory system | USER |
| **IDE Integration** | `/tools/cursor-integration` | `cursor_integration_bp` | External IDE integration. Cursor AI, OpenCode, VS Code, MCP Protocol | ADMIN |
| **Testing Suite** | `/tools/testing-suite` | `testing_suite_bp` | Automated testing. Regression tests, benchmarks, test discovery | ADMIN |
| **AI Fine-tuning** | `/tools/fine-tuning` | `fine_tuning_bp` | Custom model training. Datasets, LoRA/QLoRA, training jobs, deploy to Ollama | ADMIN |

### BUSINESS TOOLS (Phase 6 Complete - 2026-01-16)

| Module | Route | Blueprint | Description | Role | Status |
|--------|-------|-----------|-------------|------|--------|
| **Website Designer** | `/tools/website-studio` | `website_studio_bp` | Build & deploy websites with AI. E-commerce templates, GitHub, custom domains | USER | Live |
| **Store Builder** | `/tools/store-builder` | `store_builder_bp` | Create e-commerce stores. Products, payments, Printful, website integration | USER | Live |
| **Call Center** | `/tools/call-center` | `call_center_bp` | Phone system & call handling. TELUS 1-800, AI agents, CRM lookup | USER | Live |
| **Email Manager** | `/tools/email-manager` | `email_manager_bp` | Email campaigns & newsletters. Templates, SMTP, automation | USER | Live |
| **CRM** | `/tools/crm` | `crm_bp` | Customer relationship management. Contacts, segments, interactions | USER | Live |
| **Invoicing** | `/tools/invoicing` | `invoicing_bp` | Quotes, invoices & payments. Subscription billing, PDF export, Stripe | USER | Live |
| **Scheduler** | `/tools/scheduler` | `scheduler_bp` | AI calendar & task planner. Events, subscription renewals, reminders | USER | Live |
| **Social Media** | `/tools/social-media` | `social_media_bp` | Multi-platform content manager. 7 platforms, scheduling, AI suggestions | USER | Live |
| **Automations** | `/tools/automations` | `automations_bp` | Business workflow automation. N8N integration, visual builder | USER | Live |
| **Analytics** | `/tools/analytics-dashboard` | `analytics_bp` | Business metrics & insights. Unified dashboard, all modules | USER | Live |
| **GitHub Manager** | `/tools/github-manager` | `github_manager_bp` | Repository management (moved to CodeRabbit) | USER | Disabled |

### ADMIN TOOLS

| Module | Route | Blueprint | Description | Role |
|--------|-------|-----------|-------------|------|
| **Improvements Lab** | `/tools/improvements-lab` | `improvements_lab_bp` | AI-powered self-improvement. Chat, proposals, workflow, team | ADMIN |
| **Consciousness** | `/tools/consciousness` | `consciousness_bp` | Knowledge analytics, long-term memory system. Claude Code hooks, user preferences, memory maintenance | ADMIN |
| **Team Management** | `/tools/team-management` | `team_management_bp` | Unified agent control center. Roster, tasks, execution, performance, IAAE compliance, LLM routing | ADMIN |
| **Backup Manager** | `/tools/backup-manager` | `backup_manager_bp` | System backups and restore. Automated, version control, safety | ADMIN |
| **Security & Network** | `/tools/security-network` | `security_network_bp` | Security monitoring & network health. Threats, system health, audit logs | ADMIN |
| **Account Center** | `/tools/account-center` | `account_center_bp` | Manage accounts, permissions, subscriptions. Activity tracking, role management | ADMIN |
| **Sandbox Manager** | `/tools/sandbox-manager` | `sandbox_manager_bp` | Per-module sandbox testing. Safe deployments, test results, visual access | ADMIN |
| **CodeRabbit** | `/tools/coderabbit` | `coderabbit_bp` | AI code health scanner. Security scans, issue detection, Git Manager | ADMIN |
| **A.R.C.H.I.E. Blueprint** | `/tools/blueprint` | `blueprint_bp` | Platform overview & documentation. Modules, roadmap, code reference | ADMIN |
| **Goose Orchestration** | `/tools/goose` | `goose_bp` | Autonomous workflow orchestration. MCP tools, blueprints, scheduling | ADMIN |
| **HR Management** | `/tools/hr-management` | `hr_bp` | Staff performance, skills, scheduling, IAAE compliance, wellness. Extracted from Team Management | ADMIN |

---

## Coming Soon Modules (4)

### DEVELOPMENT TOOLS

| Module | Route | Description | Min Role |
|--------|-------|-------------|----------|
| **AI Model Fine-tuning** | `/tools/fine-tuning` | Custom AI model training. Dataset management, training workflows | ADMIN |

### INTEGRATIONS

| Module | Route | Description | Min Role |
|--------|-------|-------------|----------|
| **Archie Pool** | `/tools/archie-pool` | Crypto mining with AI integration. Mining, control panel, stats | PREMIUM |

---

## Phase 6 Completion Summary (2026-01-16)

### New Modules Implemented

| Module | Lines | Key Features |
|--------|-------|--------------|
| CRM | ~820 | Customer database, segments, interactions, subscription tracking |
| Email Manager | ~620 | Templates, SMTP config, logs, auto-send |
| Invoicing | ~750 | Subscription billing, recurring charges, PDF export, Stripe |
| Scheduler | ~680 | Calendar events, subscription renewals, scheduled tasks |
| Analytics | ~780 | Unified metrics, custom dashboards, all module data |
| Automations | ~520 | N8N integration, workflow stats, pre-built templates |
| Social Media | ~1,420 | 7 platforms, scheduling, AI suggestions, content calendar |

### Integrations Added

- **Store + Website**: E-commerce templates, embed widgets, store linking
- **Call Center + CRM**: Customer lookup on incoming calls
- **TELUS 1-800**: Business phone number configured with AI agent

### STORE.KytranEmpowerment.com

- Website project created with 7 e-commerce pages
- Store linked with 10 products across 4 categories
- Subscription tiers configured (Free, Pro, Business, Enterprise)
- TELUS 1-800 number enabled

---

## Health Monitoring

Each module has a health check function that reports:
- `healthy` (boolean) - Is the module operational?
- `status` - `healthy`, `degraded`, `unhealthy`, `disabled`
- `message` - Human-readable status message

### Health Check API

```
GET /api/modules/health          # All modules (admin only)
GET /api/modules/<id>/health     # Single module
```

### Dashboard Integration

The dashboard shows real-time health status:
- **Green pulse** - Module online
- **Red pulse** - Module offline
- **Orange pulse** - Module degraded
- **Blue pulse** - Checking status

Stats bar shows: `ONLINE: X | OFFLINE: X | DEGRADED: X`

---

## Role Hierarchy

```
PUBLIC (0)      - No login required
USER (10)       - Basic authenticated user
PREMIUM (20)    - Paid subscription
ADMIN (90)      - Platform administrator
SUPER_ADMIN (100) - Full system access
```

---

## Recent Changes

### v5.24.0 - 2026-01-21 (Phase 55 - Goose Orchestration)

1. **Goose Orchestration Module** - Autonomous workflow system
   - Profile configuration (`goose/profiles/archie.yaml`)
   - Python toolkit with 39 MCP tool wrappers
   - Workflow blueprints in YAML format
   - Dashboard at `/tools/goose`

2. **Database Migration 054** - Workflow queue tables
   - `workflow_queue` - Execution tracking
   - `workflow_templates` - Reusable blueprints
   - `workflow_schedules` - Cron-based triggers
   - `workflow_step_executions` - Detailed step logging

### v5.23.0 - 2026-01-21 (Phase 54 - MCP Documentation)

1. **MCP Server Reference** - Complete documentation for 39 tools
2. **Tool Categories** - Knowledge (6), Creation (6), Business (7), Admin (8), Advanced (12)
3. **Claude Code Integration** - MCP server configured in `.mcp.json`

### v5.22.0 - 2026-01-21 (Phase 53 - Unified Routing)

1. **Module Audit** - content_studio, social_media updated for archie_bridge
2. **Task Execution Logging** - HR/IAAE tracking for all AI calls
3. **Contractor Approval Flow** - All contractor calls require permission

### v5.21.0 - 2026-01-20 (Phase 50 - MCP Server)

1. **39 MCP Tools** - Full AI integration hub via stdio transport
2. **Rate Limiting** - Token bucket algorithm
3. **Audit Logging** - Complete operation tracking

### v5.11.0 - 2026-01-20 (Phase 39 UI - Station Assignment Drag-Drop)

1. **Station Assignment Tab in Team Management** - Full drag-and-drop UI restored
2. **Command Center Layout** - ARCHIE (Commander) + Kytran (Co-Commander) fixed, Assistant/Backup flexible
3. **9-Station Grid** - Consciousness, HR, R&D, Operations, Engineering, Creative, Security, Medical, Away Team
4. **Training Room Integration** - Skill picker modal with 201 skills, proficiency tracking
5. **Lounge Area** - IAAE rest cycles, forced-rest locked, voluntary rest droppable
6. **Unassigned Pool** - Searchable table with stress/energy indicators
7. **IAAE Compliance** - Pre-move checks, warnings for high stress/low energy, blocked forced-rest
8. **5 New API Endpoints** - full-layout, drag-drop, iaae-check-move, lounge

### v5.9.0 - 2026-01-19 (Phase 44 - Figma Integration Enhancement)

1. **Full Figma API Integration** - Real OAuth 2.0 with persistent tokens in database
2. **AI Bridge Analysis** - Smart component mapping and design interpretation
3. **Code Generators** - React, Vue, HTML output with multiple styling options
4. **Database Schema** - 6 new tables for complete Figma workflow persistence
5. **Project Builder Export** - Direct export generated code to App Builder projects
6. **18 API Endpoints** - OAuth, files, parsing, generation, export, history

### v5.7.1 - 2026-01-19 (Phase 39.1 - Bridge Consolidation)

1. **Training/Lounge Moved to Bridge** - Centralized station control in Bridge module
2. **Bridge Station Assignments** - 5 tabs: Assignments, Unassigned, Training, Lounge, Configure
3. **Team Management Cleanup** - Removed Stations tab (~1,100 lines)
4. **Bridge API Endpoints** - 8 new endpoints for training/lounge/IAAE

### v5.7.0 - 2026-01-19 (Phase 39 Complete)

1. **Station Assignment Drag-and-Drop UI** - Visual interface in Bridge module
2. **Command Station Special Layout** - ARCHIE + Kytran fixed, with Assistant/Backup slots
3. **Training Room with Skill Picker** - Assign agents to skill training (201 skills)
4. **Lounge Area Integration** - IAAE rest cycles, forced-rest agents locked
5. **Unassigned Pool Table** - Large searchable table at bottom
6. **9 New API Endpoints** - Drag-drop moves, training assignment, lounge management
7. **Database Migration** - `training_assignments` table, new views for layout

### v5.6.0 - 2026-01-19 (Phase 38 Complete)

1. **ATHENA Ethics Watchdog Deployed** - Chief Ethics Officer agent for IAAE compliance
2. **Ethics Monitor Module** - `/ai_bridge/ethics_monitor.py` (~450 lines)
3. **15 New API Endpoints** - Ethics monitoring, alerts, compliance reports
4. **Ethics Monitor UI** - New sub-tab in Team Management IAAE tab
5. **Database Migration** - `ethics_monitoring_runs`, `ethics_alerts`, `compliance_reports` tables

### v5.1.0 - 2026-01-16 (Phase 6 Complete)

1. **7 New Business Tools** - CRM, Email, Invoicing, Scheduler, Analytics, Automations, Social Media
2. **STORE.KytranEmpowerment.com** - Full e-commerce deployment
3. **TELUS 1-800 Integration** - AI-powered call handling with CRM lookup
4. **Store + Website Integration** - E-commerce templates and widgets
5. **Obsidian Vault Watcher Deprecated** - Using unified PostgreSQL knowledge_base

### v5.0.0 - 2026-01-13

1. **Admin Module Removed** - Routes distributed to standalone modules
2. **BUSINESS_TOOLS Category Added** - Website Studio, Store Builder, Call Center
3. **User Management Renamed** - Now "Account Center"
4. **Security & Network Added** - New admin module
5. **Health Monitoring Added** - Real-time status on dashboard

---

## File Location

```
/mnt/archie_brain/platform_v2/module_registry.py
```

---

*This document is auto-maintained. For changes, update module_registry.py.*
