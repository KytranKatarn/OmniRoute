# A.R.C.H.I.E. Blueprint Module

**Last Updated:** January 21, 2026 (v1.8 - Phase 50-55 Complete)
**Location:** `/tools/blueprint`
**Category:** Admin Operations
**Access:** Admin only

---

## Overview

The **Blueprint Module** is A.R.C.H.I.E.'s comprehensive system documentation and management dashboard. It provides a unified view of the entire platform architecture, development roadmap, module status, database schema, API endpoints, and system health.

Think of it as the "architectural control center" where administrators can understand, monitor, and manage all aspects of the A.R.C.H.I.E. platform.

---

## Features

### 13 Main Tabs

| Tab | Purpose |
|-----|---------|
| **Overview** | A.R.C.H.I.E. system overview, capabilities, and architecture |
| **Roadmap** | Development phases, tasks, and progress tracking |
| **Modules** | All platform modules organized by category with status |
| **Agents** | AI agent directory with skills and availability |
| **Database** | Live database schema viewer (tables, columns, types) |
| **API Docs** | All API endpoints with methods and descriptions |
| **System Health** | Full health check across all subsystems |
| **Dependencies** | Python package versions and status |
| **Inventory** | Platform file inventory with snapshots |
| **Cleanup** | Dead code and orphan file cleanup manager |
| **Backups** | Backup status and history |
| **Docs** | Documentation file viewer |
| **Consciousness** | Memory and knowledge base statistics |

---

## Module Structure

```
platform_v2/tools/blueprint/
├── __init__.py              # Blueprint registration
├── routes.py                # Main routes (~89KB, 45+ endpoints)
├── blueprint_intelligence.py # Cross-module data aggregation (~44KB)
├── inventory_scanner.py     # Platform file scanner (~14KB)
├── cleanup_manager.py       # Dead code cleanup (~16KB)
└── phase_manager.py         # Roadmap phase management (~14KB)
```

---

## API Endpoints

### Core Information

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/overview` | GET | A.R.C.H.I.E. system overview |
| `/api/modules` | GET | All modules with categories and status |
| `/api/status` | GET | Quick status check |
| `/api/roadmap` | GET | Development roadmap and phases |

### Documentation

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/docs` | GET | List all documentation files |
| `/api/docs/<filename>` | GET | Get specific document content |

### Phase Management (Roadmap)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/phases` | GET | Get all phases |
| `/api/phases` | POST | Create new phase |
| `/api/phases/<id>` | GET | Get specific phase |
| `/api/phases/<id>` | PUT | Update phase |
| `/api/phases/<id>` | DELETE | Delete phase |
| `/api/phases/reorder` | POST | Reorder phases |
| `/api/phases/<id>/tasks` | POST | Add task to phase |
| `/api/tasks/<id>/toggle` | PUT | Toggle task completion |
| `/api/tasks/<id>` | PUT | Update task |
| `/api/tasks/<id>` | DELETE | Delete task |

### Inventory Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/inventory` | GET | Get current inventory |
| `/api/inventory/history` | GET | Get inventory snapshots history |
| `/api/inventory/scan` | POST | Scan platform and save snapshot |
| `/api/inventory/<id>` | GET | Get specific snapshot |
| `/api/inventory/<id>` | DELETE | Delete snapshot |
| `/api/inventory/compare` | GET | Compare two snapshots |

### Cleanup Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cleanup/candidates` | GET | Get cleanup candidates |
| `/api/cleanup/scan` | POST | Scan for dead code |
| `/api/cleanup/approve/<id>` | POST | Approve cleanup candidate |
| `/api/cleanup/reject/<id>` | POST | Reject cleanup candidate |
| `/api/cleanup/approve-bulk` | POST | Bulk approve candidates |
| `/api/cleanup/execute/<id>` | POST | Execute cleanup |
| `/api/cleanup/execute-bulk` | POST | Bulk execute cleanup |
| `/api/cleanup/report` | GET | Get cleanup report |

### Intelligence & Cross-Module

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/schema` | GET | Database schema |
| `/api/endpoints` | GET | All API endpoints |
| `/api/health/full` | GET | Full system health check |
| `/api/dependencies` | GET | Python dependencies |
| `/api/backups` | GET | Backup status |
| `/api/agents` | GET | Agent directory |
| `/api/consciousness` | GET | Consciousness/memory stats |
| `/api/sync-knowledge` | POST | Sync to knowledge base |
| `/api/sync-module-code` | POST | Sync module code to knowledge |
| `/api/quick-action` | POST | Execute quick actions |
| `/api/intelligence-report` | GET | Full intelligence report |

### Git Integration

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/git-activity` | GET | Git activity and stats |
| `/api/git-tracking/initialize` | POST | Initialize git tracking |
| `/api/code-reference` | GET | Code reference stats |

---

## Key Components

### 1. Blueprint Intelligence (`blueprint_intelligence.py`)

Aggregates data from across the platform:

- **Database Schema**: Live PostgreSQL schema introspection
- **API Endpoints**: Scans all Flask blueprints for routes
- **System Health**: Checks Docker, database, services
- **Dependencies**: Parses requirements.txt
- **Backup Status**: Integrates with backup manager
- **Agent Directory**: Pulls from agents table
- **Consciousness Summary**: Knowledge base statistics

### 2. Inventory Scanner (`inventory_scanner.py`)

Scans the platform directory structure:

- **File Inventory**: Counts Python files, templates, static assets
- **Size Tracking**: Directory sizes and totals
- **Snapshot System**: Save point-in-time snapshots
- **Comparison**: Compare snapshots to track changes

### 3. Cleanup Manager (`cleanup_manager.py`)

Identifies and manages dead code:

- **Candidate Detection**: Finds unused files, orphaned templates
- **Categories**: Backup files, temp files, __pycache__, etc.
- **Approval Workflow**: Review before deletion
- **Safe Execution**: Moves to trash instead of delete
- **Reporting**: Track cleanup history

### 4. Phase Manager (`phase_manager.py`)

Manages the development roadmap:

- **Phase CRUD**: Create, read, update, delete phases
- **Task Management**: Tasks within phases
- **Progress Tracking**: Completion percentage
- **Reordering**: Drag-and-drop phase reorder
- **Sections**: Group phases by category

---

## Usage Examples

### View System Overview

```javascript
fetch('/tools/blueprint/api/overview')
  .then(r => r.json())
  .then(data => {
    console.log(data.name);  // "A.R.C.H.I.E."
    console.log(data.version);  // "5.2.2"
    console.log(data.capabilities);  // Array of capabilities
  });
```

### Get All Modules

```javascript
fetch('/tools/blueprint/api/modules')
  .then(r => r.json())
  .then(data => {
    console.log(data.categories);  // Modules by category
    console.log(data.stats.live);  // Count of live modules
  });
```

### Scan Platform Inventory

```javascript
fetch('/tools/blueprint/api/inventory/scan', { method: 'POST' })
  .then(r => r.json())
  .then(data => {
    console.log(data.snapshot_id);  // New snapshot ID
    console.log(data.summary);  // File counts
  });
```

### Sync to Knowledge Base

```javascript
fetch('/tools/blueprint/api/sync-knowledge', { method: 'POST' })
  .then(r => r.json())
  .then(data => {
    console.log(data.synced_count);  // Items synced
  });
```

---

## UI Features

### Statistics Panel

The top of the Blueprint page shows key stats:

- **Modules**: Total platform modules count
- **Docs**: Documentation file count
- **Tables**: Database table count
- **Endpoints**: API endpoint count

### Quick Actions

Available in Overview tab:

- **Run Full Inventory Scan**: Scan all platform files
- **Sync to Knowledge Base**: Push Blueprint data to knowledge
- **Generate Intelligence Report**: Full system analysis

### Search & Filter

Each tab supports searching:

- **Modules**: Filter by name, category, status
- **Docs**: Search document titles and content
- **Schema**: Search tables and columns
- **Endpoints**: Filter by path or method

---

## Database Tables

Blueprint uses these tables (created in Phase 29):

| Table | Purpose |
|-------|---------|
| `blueprint_phases` | Development roadmap phases |
| `blueprint_tasks` | Tasks within phases |
| `blueprint_inventory_snapshots` | Point-in-time file snapshots |
| `blueprint_cleanup_candidates` | Dead code candidates |

---

## Integration Points

### Module Registry

Blueprint reads from `module_registry.py` to display:
- All registered modules
- Category organization
- Status (live, beta, coming soon)
- Health check results

### Knowledge Base

Blueprint can sync data to `knowledge_base`:
- Platform documentation
- API endpoint summaries
- Module descriptions
- Architecture information

### Consciousness Module

Blueprint pulls from consciousness:
- Memory entry counts by type
- Knowledge base statistics
- Learning records

### Backup Manager

Blueprint integrates with backup system:
- Backup status and history
- Last backup timestamp
- Backup sizes

### MCP Server (Phase 50)

Blueprint integrates with the Model Context Protocol server:
- **39 MCP Tools** exposed via stdio transport
- **Tool Categories**: Knowledge (6), Creation (6), Business (7), Admin (8), Advanced (12)
- **Claude Code Integration**: Configured in `.mcp.json`
- **Rate Limiting**: Token bucket algorithm with configurable limits

MCP tools route through `archie_bridge` for:
- Local-first AI processing (internal Ollama staff)
- Contractor approval workflow for paid APIs
- Task execution logging for HR/IAAE tracking

See `/docs/MCP_SERVER_REFERENCE.md` for full tool documentation.

### Goose Orchestration (Phase 55)

Blueprint integrates with Goose autonomous workflow system:
- **Workflow Queue**: `workflow_queue` table for execution tracking
- **Workflow Templates**: Reusable blueprints stored in database
- **Scheduled Workflows**: Cron-based triggers via `workflow_schedules`
- **Step Execution**: Detailed logging in `workflow_step_executions`

Goose configuration:
```
/mnt/archie_brain/goose/
├── profiles/archie.yaml      # Goose profile with MCP connection
├── toolkits/archie_toolkit.py # Python toolkit with 39 tool wrappers
└── blueprints/*.yaml          # Workflow blueprint definitions
```

See `/tools/goose` dashboard for workflow management.

---

## Access Control

- **Minimum Role**: Admin
- **Authentication**: Required (login)
- **Category**: Admin Operations

---

## Performance Optimizations

### Lazy Loading (Phase 31.5)

To improve page load time, Blueprint uses **lazy loading** for slow endpoints:

**Fast endpoints (loaded on page startup):**
- `/api/overview` - ~5ms
- `/api/modules` - ~15ms
- `/api/docs` - ~18ms
- `/api/phases` - ~45ms
- `/api/endpoints` - ~14ms
- `/api/agents` - ~70ms

**Slow endpoints (loaded on tab click):**
- `/api/schema` - ~9s (queries every table in database)
- `/api/dependencies` - ~8s (runs `pip list --outdated`)
- `/api/health/full` - ~0.2s (CPU/memory measurements)

This reduces initial page load from **17+ seconds** to **~0.2 seconds**.

### Server-Side Caching

Blueprint Intelligence uses in-memory caching with TTL:

| Endpoint | Cache TTL | Reason |
|----------|-----------|--------|
| `schema` | 5 minutes | DB schema rarely changes |
| `dependencies` | 1 hour | Pip packages rarely change |
| `health` | 1 minute | Health can change frequently |

Cache is implemented in `blueprint_intelligence.py` with thread-safe locking.

### Performance Tips

1. **First load of slow tabs** will take time (populates cache)
2. **Subsequent loads** are instant (from cache)
3. **Refresh button** on each tab forces fresh data
4. **Cache auto-expires** based on TTL settings

---

## Related Documentation

- `MASTER_STATUS_AND_ROADMAP_2026.md` - Full development roadmap
- `MODULE_REGISTRY_STATUS.md` - Module status details
- `DATABASE_SCHEMA_DOCUMENTATION.md` - Full schema reference
- `DOCUMENTATION_INDEX.md` - All documentation files
- `UI_STYLE_GUIDE.md` - UI styling standards
- `MCP_SERVER_REFERENCE.md` - MCP tools documentation (39 tools)
- `ARCHIE_BRIDGE_MODULE_PLAN.md` - AI routing architecture

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial Blueprint module |
| 1.1 | Jan 2026 | Phase 29 - Inventory & Cleanup managers |
| 1.2 | Jan 2026 | Phase 29.5 - Full Intelligence integration |
| 1.3 | Jan 2026 | Phase 29.6 - Cross-module sync |
| 1.4 | Jan 17, 2026 | Phase 31 - UI Theme System (light/dark mode) |
| 1.5 | Jan 17, 2026 | Phase 31.5 - Performance optimization (lazy loading + caching) |
| 1.6 | Jan 19, 2026 | Platform v5.2.2 - Roadmap updates, Phase 25/25b tracking |
| 1.7 | Jan 19, 2026 | Phase 8 Figma Integration + Phase 30 Mining Pool Integration |
| 1.8 | Jan 21, 2026 | Phase 50-55: MCP Server (39 tools), Unified Routing, Goose Orchestration |

---

## Recent Platform Changes (v5.2x)

### v5.24.0 - Phase 55: Goose Orchestration (Jan 21, 2026)

- **Goose Infrastructure** - Autonomous workflow system
  - Profile configuration (`goose/profiles/archie.yaml`)
  - Python toolkit with 39 MCP tool wrappers
  - Workflow blueprints in YAML format
  - Database tables: workflow_queue, workflow_templates, workflow_schedules
  - Dashboard at `/tools/goose`

### v5.23.0 - Phase 54: MCP Documentation (Jan 21, 2026)

- **MCP Server Reference** - Complete documentation
  - All 39 tools documented with input schemas
  - Architecture diagrams and flow charts
  - Authentication and rate limiting guide
  - Troubleshooting section

### v5.22.0 - Phase 53: Unified Routing (Jan 21, 2026)

- **Module Audit & Updates**
  - content_studio: Direct archie_bridge calls
  - social_media: AI suggestions via bridge routing
  - Task execution logging for HR/IAAE tracking
  - All AI calls now route through archie_bridge

### v5.2.3 - Phase 8 & 30 Complete (Jan 19, 2026)

- **Phase 8: Figma Integration** - Design-to-code pipeline
  - OAuth 2.0 authentication with CSRF protection
  - Design file parser & component analyzer
  - AI component mapper (Navbar, Hero, Features, Footer)
  - Code generation: React/TypeScript, Vue 3, HTML/Tailwind
  - 20+ API endpoints (755 lines)
  - New module: `/tools/figma`

- **Phase 30: Mining Pool Integration** - Resource scheduler
  - AI/Mining resource balancing
  - Mining contributor tracking & rewards
  - Resource allocation API (9 endpoints)
  - Migration 027: 4 new tables

### v5.2.2 - Phase 5 Module Consolidation Complete

Blueprint's roadmap now tracks the completed CREATION category modules:

- **Project Builder** - Full Neo-Command Center UI, 12 templates, AI assistant
- **Media Studio** - Gallery, AI generator, video editor, shorts creator
- **Creation Tools Navigation** - Shared nav component with orange theme

### v5.2.1 - Phase 25/25b Complete

Blueprint's roadmap tracks these completed phases:

- **Phase 25: Website Designer Improvements**
  - Monaco Editor integration with syntax highlighting
  - Layout reorganization (2-column: Chat | Preview+Code)
  - File selection bar with language badges
  - Git tab enhancements

- **Phase 25b: Bootstrap Compatibility Restoration**
  - Bootstrap 5.3.2 CSS/JS added to base.html
  - Fixed layouts for Invoicing, Scheduler, Automations, Analytics, Store Builder

### Roadmap Tracking

The Blueprint module's `/api/roadmap` endpoint maintains comprehensive tracking of:
- **42+ development phases** across 4 sections
- **300+ individual tasks** with completion status
- Real-time progress calculation
- Section-based organization (Foundation, Workflow, Modules, Future)

---

*Blueprint is your window into A.R.C.H.I.E.'s architecture and development progress.*
