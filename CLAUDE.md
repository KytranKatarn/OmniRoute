# A.R.C.H.I.E. Platform

**Version**: 5.29.0 | **Host**: 192.168.1.200 | **Status**: Operational

---

## Critical Rules

1. **Read before modify** - Check existing code patterns first
2. **Test in Docker** - `docker exec archie_platform python3 script.py`
3. **Two .env files** - Root `.env` and `platform_v2/.env` must match
4. **Module perms** - Add to BOTH `rbac.py` AND `module_registry.py`

## Quick Reference

| Resource | Location |
|----------|----------|
| Platform | http://192.168.1.200:3000 |
| Dev HQ | http://192.168.1.200:3000/dev-hq |
| Docs | `knowledge_base` table → Dev HQ Knowledge tab or MCP `search_knowledge` |
| Modules | `/mnt/archie_brain/platform_v2/tools/` (50 modules) |
| MCP Tools | 78 tools via `.mcp.json` |
| Projects | `unified_projects` table → MCP `get_projects` / `create_task` |

## Architecture (5 Systems)

1. **Knowledge Base** - `knowledge_base` table (~5,000 active entries, 100% embedded; ~1,100 archived as `archie_v1`)
2. **AI Bridge** - `/ai_bridge/archie_bridge.py` (multi-model router)
3. **Module System** - Flask Blueprints in `/platform_v2/tools/`
4. **Dev HQ** - Development command center (`/dev-hq`), projects, knowledge, schema, integrations
5. **Consciousness** - Knowledge analytics, AI processing, embedding coverage, emotional intelligence
6. **Improvement Workflow** - Scan → Proposal → Sandbox → Deploy

## Source of Truth

| Data | Location | Access |
|------|----------|--------|
| **Documentation & Knowledge** | `knowledge_base` table | Dev HQ Knowledge tab, MCP `search_knowledge`, MCP `store_memory` (use `knowledge_type='vault_note'` for docs) |
| **Projects & Tasks** | `unified_projects` + `unified_tasks` tables | MCP `get_projects`, `create_project`, `create_task`, `complete_task` |
| **Decisions** | `project_decisions` table | MCP `log_decision` |
| **Module Code** | `/platform_v2/tools/` filesystem | Direct file access |

**NO filesystem docs** — `/docs/` is archived (git history only). **NO TODO_LIST.md** — use `unified_tasks` table.

## Key Files

```
platform_v2/app.py              - Flask app
platform_v2/module_registry.py  - Module definitions
platform_v2/rbac.py             - Permissions
platform_v2/database.py         - DB connection
ai_bridge/archie_bridge.py      - AI routing
ai_bridge/knowledge_analyzer.py - Knowledge extraction (Ollama qwen2.5:7b)
ai_bridge/embedding_service.py  - Vector embeddings (nomic-embed-text)
```

## Common Errors

| Error | Fix |
|-------|-----|
| `archie_database` not found | Run inside Docker container |
| `localhost:5432 refused` | Use `192.168.1.200` for DB_HOST |
| `TemplateNotFound` | Use `tools/` prefix in path |
| Module not showing | Check both `rbac.py` + `module_registry.py` |

## Commands

```bash
docker compose up -d                          # Start
docker compose restart archie_platform        # Restart
docker logs -f archie_platform                # Logs
docker exec -it archie_database psql -U archie -d archie  # DB
```

## Skills (Use These!)

- `/archie-status` - Platform health check
- `/archie-module` - Create/modify modules
- `/archie-deploy` - Safe deployment
- `/archie-patterns` - Code patterns & conventions
- `/archie-search` - Search knowledge base
- `/archie-project` - Project & task management
- `/archie-work` - Start/track work sessions (NEW)

## Token Saving Tips

1. Use `/clear` between unrelated tasks
2. Be specific: "Fix line 45 in auth.py" not "improve auth"
3. Use subagents for file searches (Task tool)
4. Check MCP tools before reading files
5. Use skills instead of re-explaining workflows

---

*Use `/archie-patterns` for code examples, `/archie-status` for health checks*
