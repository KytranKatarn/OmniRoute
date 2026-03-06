---
globs: ["database/**", "platform_v2/database.py", "platform_v2/services/**"]
---

# Database Rules

## Connection
- Host: `192.168.1.200` (from outside Docker) or `archie_database` (container name)
- Docker: `docker exec -it archie_database psql -U archie -d archie`
- Python: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`

## Common Table Gotchas
- `unified_projects.name` (NOT `title`)
- `unified_tasks.priority` is INTEGER
- `unified_projects.slug` is NOT NULL
- `project_decisions.decision`/`context` (NOT `description`/`rationale`)
- `telegram_users` (NOT `telegram_linked_accounts`)
- `system_notifications` CHECK: info/warning/error/success/reminder/alert/briefing only
- JSONB fields need `psycopg2.Json()` wrapper

## Services Layer (ADR-075)
- `services/knowledge_service.py` (9 funcs) — owns knowledge_base
- `services/project_service.py` (6 funcs) — owns projects/tasks
- Data ownership: knowledge_base -> Consciousness, projects/tasks -> Dev HQ

## Migrations
- Path: `database/migrations/NNN_description.sql`
- Run: `docker exec archie_database psql -U archie -d archie -f /path/to/migration.sql`
- Always idempotent (ON CONFLICT DO UPDATE or IF NOT EXISTS)
