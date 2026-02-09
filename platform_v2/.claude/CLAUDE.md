# A.R.C.H.I.E. Platform

**Version**: 5.25.0 | **Host**: 192.168.1.200 | **Status**: Operational

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
| MCP Tools | 69 tools via `.mcp.json` |
| Projects | `unified_projects` table (84 projects) |

## Architecture (5 Systems)

1. **Knowledge Base** - `knowledge_base` table (3,390 entries)
2. **AI Bridge** - `/ai_bridge/archie_bridge.py` (multi-model router)
3. **Module System** - Flask Blueprints in `/platform_v2/tools/`
4. **Dev HQ** - Development command center (`/dev-hq`), projects, knowledge, schema, integrations
5. **Improvement Workflow** - Scan → Proposal → Sandbox → Deploy

## Key Files

```
platform_v2/app.py              - Flask app
platform_v2/module_registry.py  - Module definitions
platform_v2/rbac.py             - Permissions
platform_v2/database.py         - DB connection
ai_bridge/archie_bridge.py      - AI routing
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
