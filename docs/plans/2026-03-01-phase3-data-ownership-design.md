# Phase 3: Data Ownership & Shared Service Layer — Design

**Project**: #101 ARCHIE Self-Evolution Pipeline
**Tasks**: #707 (Define data ownership), #708 (Implement shared service layer)
**Date**: 2026-03-01
**Status**: Approved

---

## Problem

Dev HQ and Consciousness both query the same database tables with duplicate SQL scattered across route files. This creates maintenance burden, inconsistent query patterns, and makes it unclear which module "owns" which data.

## Data Ownership Map

| Table | Owner | Consumers | Access Pattern |
|-------|-------|-----------|----------------|
| `knowledge_base` | Consciousness (38 endpoints) | Dev HQ (6 endpoints) | Dev HQ: browse, module docs CRUD |
| `unified_projects` | Dev HQ (10+ CRUD endpoints) | Consciousness (3 read-only) | Consciousness: dashboard summary |
| `unified_tasks` | Dev HQ (8+ CRUD endpoints) | Consciousness (3 read-only) | Consciousness: dashboard stats |
| `project_decisions` | Dev HQ (3 CRUD endpoints) | Consciousness (1 read-only) | Consciousness: integration summary |
| `agents` / `agent_emotional_state` | Consciousness (exclusive) | None | No overlap |
| `docker_stacks` / `system_metrics_history` | System Ops (exclusive) | None | No overlap |

## Approach: Thin Service Modules

Create standalone Python service files under `platform_v2/services/` that encapsulate shared DB queries. Both modules import from these instead of writing duplicate SQL.

### Why This Over Alternatives

- **vs Internal REST APIs**: HTTP overhead for in-process calls is unnecessary in a monolith
- **vs Database Views**: Can't encapsulate business logic, doesn't reduce Python duplication

## Architecture

```
platform_v2/services/
├── __init__.py
├── knowledge_service.py    # Extracted from Consciousness knowledge_routes.py
└── project_service.py      # Extracted from Dev HQ routes
```

### knowledge_service.py

Functions extracted from Consciousness's knowledge_routes.py:

- `search_knowledge(query, filters=None, limit=50)` — full-text + optional embedding search
- `browse_knowledge(category=None, knowledge_type=None, page=1, per_page=20)` — paginated browse with filters
- `get_knowledge_stats()` — counts by category, type, embedding coverage
- `get_entry(entry_id)` — single entry lookup
- `create_entry(title, content, category, knowledge_type, **kwargs)` — insert with defaults
- `update_entry(entry_id, **fields)` — partial update
- `delete_entry(entry_id)` — soft or hard delete (match existing behavior)

### project_service.py

Functions extracted from Dev HQ's routes:

- `get_projects(status=None, limit=50)` — project listing with optional status filter
- `get_project_with_stats(project_id)` — single project + task counts + recent activity
- `get_tasks(project_id=None, status=None, limit=50)` — task listing
- `get_project_stats()` — aggregate counts (active, completed, total tasks)
- `get_recent_decisions(project_id=None, limit=10)` — decision log entries
- `get_recent_activity(limit=20)` — combined project + task activity feed

### Migration Strategy

1. Create `platform_v2/services/` with service files
2. Extract common SQL patterns from owner modules into services
3. Update Dev HQ knowledge endpoints → call `knowledge_service`
4. Update Consciousness project/dashboard endpoints → call `project_service`
5. Owner modules adopt their own service internally for consistency

### What Doesn't Change

- All existing API endpoints remain identical (same URLs, same response shapes)
- Consciousness keeps all 38 knowledge endpoints
- Dev HQ keeps all project/task CRUD endpoints
- System Ops: completely untouched
- No database schema changes
