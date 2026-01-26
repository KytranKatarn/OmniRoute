# A.R.C.H.I.E. System Documentation Index

**Last Updated:** 2026-01-21
**Platform Version:** 5.24.0
**Access:** `/tools/consciousness`

---

## Overview

This document serves as a master index for all A.R.C.H.I.E. system documentation.
All documentation is stored in the unified `knowledge_base` table and managed through
the Consciousness interface.

### Quick Links
- **Dashboard:** `/dashboard`
- **Consciousness:** `/tools/consciousness`
- **Module Registry:** See `MODULE_REGISTRY_STATUS.md`

---

## Platform Architecture (v5.0.0)

### Module Categories

| Category | Description | Modules |
|----------|-------------|---------|
| **CREATION** | Build apps, websites, games, media | Website Builder, App Builder, +4 coming soon |
| **DEVELOPMENT** | Code, edit, collaborate | Code Editor, Business Directory, A.R.C.H.I.E. Chat, +2 coming soon |
| **BUSINESS_TOOLS** | Business infrastructure | Website Studio, Store Builder, Call Center |
| **ADMIN** | System management | Improvements Lab, Consciousness, Team Management, Backup Manager, Security & Network, Account Center, +2 coming soon |
| **INTEGRATIONS** | External services | +3 coming soon |

---

## System Documentation

### Core System
| Document | Location | Description |
|----------|----------|-------------|
| Master Status & Roadmap | `MASTER_STATUS_AND_ROADMAP_2026.md` | Project status, roadmap |
| Changelog | `CHANGELOG.md` | Version history (v5.0.0 current) |
| Module Registry Status | `MODULE_REGISTRY_STATUS.md` | **NEW** - All modules, health status |
| Database Schema | `DATABASE_SCHEMA_DOCUMENTATION.md` | Complete schema reference |
| File Structure | `FILE_STRUCTURE_MASTER.md` | Directory layout |

### Architecture
| Document | Location | Description |
|----------|----------|-------------|
| Dashboard Architecture | `DASHBOARD_ARCHITECTURE.md` | Dashboard design |
| Directory & SaaS | `DIRECTORY_AND_SAAS_ARCHITECTURE.md` | Multi-tenant architecture |
| Consciousness System | `ARCHIE_CONSCIOUSNESS.md` | Knowledge & memory system |

### AI Infrastructure (Phase 50-60)
| Document | Location | Description |
|----------|----------|-------------|
| MCP Server Reference | `MCP_SERVER_REFERENCE.md` | 39 MCP tools documentation |
| AI Bridge Module | `ARCHIE_BRIDGE_MODULE_PLAN.md` | Unified AI routing architecture |
| Blueprint Module | `ARCHIE_BLUEPRINT_MODULE.md` | Blueprint system documentation |
| Command Interface Plan | `ARCHIE_COMMAND_INTERFACE_PLAN.md` | **NEW** - Phase 56-60 unified chat interface |
| LLM Reference Guide | `LLM_REFERENCE_GUIDE.md` | Ollama model assignments & staff roster |

---

## Module Documentation

### CREATION Tools
| Module | Status | Documentation |
|--------|--------|---------------|
| Website Builder | Live | `AI_POWERED_APPS.md` |
| App Builder | Live | `APP_BUILDER_DEPLOYMENT_FRAMEWORK.md`, `APP_BUILDER_TESTING_FRAMEWORK.md` |
| Game Builder | Coming Soon | - |
| Picture Generation | Coming Soon | - |
| Video Generation | Coming Soon | - |
| Story Generation | Coming Soon | - |

### DEVELOPMENT Tools
| Module | Status | Documentation |
|--------|--------|---------------|
| Code Sentinel | Live | `CODE_SENTINEL_MODULE.md` |
| Code Editor | Live | `AI_POWERED_CODE_EDITOR.md` |
| Sandbox Manager | Live | `SANDBOX_MANAGER.md` |
| Business Directory | Live | `BUSINESS_AGENTS_GUIDE.md` |
| A.R.C.H.I.E. Chat | Live | `ARCHIE_PERSONALITY_SYSTEM.md` |
| Cursor Integration | Coming Soon | `CURSOR_OPTIONAL_ENHANCEMENTS_PLAN.md` |

### BUSINESS Tools
| Module | Status | Documentation |
|--------|--------|---------------|
| Website Studio | Live | See Website Builder docs |
| Store Builder | Live | - |
| Call Center | Live | - |

### ADMIN Tools
| Module | Status | Documentation |
|--------|--------|---------------|
| Improvements Lab | Live | `IMPROVEMENT_WORKFLOW_COMPLETE_GUIDE.md`, `SELF_IMPROVEMENT_SYSTEM.md` |
| Consciousness | Live | `ARCHIE_CONSCIOUSNESS.md` |
| Team Management | Live | `AGENT_DIRECTORY.md`, `AGENT_SYSTEM_IMPROVEMENTS.md` |
| Backup Manager | Live | `BACKUP_RECOVERY_GUIDE.md`, `BACKUP_SYSTEM_REDESIGN.md` |
| Security & Network | Live | - |
| Account Center | Live | `USER_MANAGEMENT_AND_SUBSCRIPTION_SYSTEM_2026.md` |
| Goose Orchestration | Live | `MCP_SERVER_REFERENCE.md` (Phase 55) |
| Blueprint | Live | `ARCHIE_BLUEPRINT_MODULE.md` |
| Sandbox Manager | Coming Soon | - |
| Analytics Dashboard | Coming Soon | - |

### INTEGRATIONS
| Module | Status | Documentation |
|--------|--------|---------------|
| Social Media | Coming Soon | - |
| Archie Pool | Coming Soon | - |
| Automations | Coming Soon | `AUTOMATIONS_SECTION_REDESIGN.md` |

---

## API Documentation

### Core APIs
| Endpoint Group | Base Path | Description |
|----------------|-----------|-------------|
| Module Health | `/api/modules/health` | Health monitoring |
| Notifications | `/api/notifications/` | User notifications |
| Knowledge | `/api/knowledge/` | Knowledge base CRUD |
| MCP Server | stdio transport | 39 AI tools (Phase 50) |

### Module APIs
| Module | Base Path | Routes |
|--------|-----------|--------|
| Code Sentinel | `/tools/code_sentinel/` | 56+ routes |
| Improvements Lab | `/tools/improvements-lab/` | 50+ routes |
| Consciousness | `/tools/consciousness/` | 20+ routes |
| Team Management | `/tools/team-management/` | 15+ routes |
| Backup Manager | `/tools/backup-manager/` | 10+ routes |
| Account Center | `/tools/account-center/` | 15+ routes |
| Website Studio | `/tools/website-studio/` | 10+ routes |
| Store Builder | `/tools/store-builder/` | 10+ routes |
| Call Center | `/tools/call-center/` | 10+ routes |
| Goose Orchestration | `/tools/goose/` | 10+ routes |
| Blueprint | `/tools/blueprint/` | 45+ routes |

---

## Archived Documentation

The following docs have been moved to `/docs/archive/`:

| Document | Status | Reason |
|----------|--------|--------|
| `ADMIN_REFERENCE.md` | **ARCHIVED** | Admin panel removed in v5.0.0 |
| `ADMIN_INTERFACE_REORGANIZATION.md` | **ARCHIVED** | Completed in v5.0.0 |
| `ADMIN_SECTIONS_GUIDE.md` | **ARCHIVED** | Routes migrated to standalone modules |
| `ADMIN_VS_PUBLIC_DIRECTORY.md` | **ARCHIVED** | Admin structure obsolete |
| `AGENTS_SECTION_FIXES.md` | **ARCHIVED** | Bug fixes superseded |
| `FILE_STRUCTURE_MASTER.md` | **ARCHIVED** | Directory structure changed |
| `SESSION_HANDOFF.md` | **ARCHIVED** | Historical session state |
| `TODO_LIST.md` | **ARCHIVED** | Replaced by Blueprint roadmap |
| `DOCUMENTATION_STRATEGY.md` | **ARCHIVED** | Consolidated |
| `DOCUMENTATION_CONSOLIDATION.md` | **ARCHIVED** | Historical |
| `IMPLEMENTATION_STATUS.md` | **ARCHIVED** | See MASTER_STATUS_AND_ROADMAP_2026.md |
| `PHASE_2_WEEK_1-2_SUMMARY.md` | **ARCHIVED** | See PHASE_2_COMPLETE_SUMMARY.md |
| `CODERABBIT_MODULE.md` | **DEPRECATED** | Replaced by `CODE_SENTINEL_MODULE.md` |

---

## Key Files in /docs/

### Active Documentation
```
CHANGELOG.md                              - Version history
MODULE_REGISTRY_STATUS.md                 - Current module status
MASTER_STATUS_AND_ROADMAP_2026.md        - Project roadmap
DATABASE_SCHEMA_DOCUMENTATION.md          - Schema reference
IMPROVEMENT_WORKFLOW_COMPLETE_GUIDE.md    - Improvement system
USER_MANAGEMENT_AND_SUBSCRIPTION_SYSTEM_2026.md - Account system
ARCHIE_CONSCIOUSNESS.md                   - Consciousness system
TROUBLESHOOTING.md                        - Known issues & fixes
MCP_SERVER_REFERENCE.md                   - MCP tools documentation (39 tools)
ARCHIE_BLUEPRINT_MODULE.md                - Blueprint system docs
ARCHIE_BRIDGE_MODULE_PLAN.md              - AI routing architecture
ARCHIE_COMMAND_INTERFACE_PLAN.md          - Unified chat interface (Phase 56-60)
LLM_REFERENCE_GUIDE.md                    - Ollama model assignments
CODE_SENTINEL_MODULE.md                   - Code review & security scanning
```

### Reference Documentation
```
AGENT_DIRECTORY.md                        - Agent catalog
BACKUP_RECOVERY_GUIDE.md                  - Backup procedures
DEPLOYMENT_INSTRUCTIONS.md                - Deployment guide
DASHBOARD_ARCHITECTURE.md                 - Module architecture
QUICK_REFERENCE.md                        - Quick commands
```

---

## Maintenance

### Adding Documentation
1. Create `.md` file in `/mnt/archie_brain/docs/`
2. Navigate to `/tools/consciousness`
3. Use "Ingest All" to sync to knowledge_base

### Updating This Index
Update this file when:
- New modules are added
- Modules are renamed/removed
- New documentation files are created
- API routes change significantly

---

*Last updated: 2026-01-24 (Phase 50-55.5 complete, Phase 56-60 planned - Command Interface)*
