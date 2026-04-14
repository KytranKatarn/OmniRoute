---
globs: ["platform_v2/tools/consciousness/devhq_routes.py", "platform_v2/services/knowledge_service.py", "platform_v2/services/project_service.py"]
---

# Project & Knowledge Rules

## Modules
- **Dev HQ** — Consciousness module → Dev HQ tab (`/tools/consciousness/#devhq`)
  - 5 subtabs: Overview (with intelligence analytics), Projects, Ideas, Decisions, System
  - Routes at `tools/consciousness/devhq_routes.py` (Decision #433)

## Key DB Tables
- `unified_projects` — uses `name` NOT `title`, `slug` is NOT NULL
- `unified_tasks` — `priority` is INTEGER (1-10)
- `project_decisions` — uses `decision`/`context` NOT `description`/`rationale`
- `knowledge_base` — 18,000+ entries, `importance_score` (NOT `importance`)

## Data Ownership
- `knowledge_base` → owned by Consciousness module
- `unified_projects` + `unified_tasks` → owned by Dev HQ
- `project_decisions` → owned by Dev HQ

## MCP Integration
- `create_project`, `create_task`, `complete_task` — project/task management
- `log_decision` — architectural decision records
- `search_knowledge`, `search_knowledge_brief` — knowledge search
- `store_memory` (vault_note) — docs/roadmap updates
- `update_project_understanding` — project familiarity tracking

## Dev HQ Workflow (MANDATORY)
After every commit+push:
1. `create_task` for new work
2. `complete_task` with verification notes when done
3. `log_decision` for architectural choices
4. `update_project_understanding` after working on a project

## Gotchas
- Knowledge types: mistake_learned, vault_note, code_snippet, github_file, conversation_memory
- JSONB fields need `psycopg2.Json()` wrapper
- Knowledge `importance_score` is DECIMAL(3,2), default 0.85
