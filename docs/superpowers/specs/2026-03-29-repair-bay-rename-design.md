# Dev Pipeline → Repair Bay Rename

**Date**: 2026-03-29
**Project**: New (Repair Bay Rename)
**Status**: Approved

---

## Summary

Rename the Dev Pipeline module to Repair Bay. The AI agent running it remains F.O.R.G.E. All internal logic, DB tables, and service functionality stay the same. This is a pure naming refactor.

## Naming

| Aspect | Old | New |
|--------|-----|-----|
| Directory | `tools/dev_pipeline/` | `tools/repair_bay/` |
| Blueprint | `dev_pipeline_bp` | `repair_bay_bp` |
| URL | `/tools/dev-pipeline` | `/tools/repair-bay` |
| Template | `templates/tools/dev_pipeline.html` | `templates/tools/repair_bay.html` |
| Module ID | `dev_pipeline` | `repair_bay` |
| Rules file | `.claude/rules/dev-pipeline.md` | `.claude/rules/repair-bay.md` |

## Tab Rename

| Old | New |
|-----|-----|
| Scan | Diagnose |
| Proposals | Repairs |
| Sandbox | Test Bay |
| Deploy | Ship |

## What Stays The Same

- All route file names (scan_routes.py, proposal_routes.py, sandbox_routes.py, deploy_routes.py, github_routes.py, repair_routes.py, station_routes.py)
- All 33 service files (directory path changes but filenames stay)
- F.O.R.G.E. branding on GitHub/webhook routes
- All logic, DB tables, functionality
- Station panel (ENGINEERING)

## Files to Update

### Rename/Move (3)

1. `tools/dev_pipeline/` → `tools/repair_bay/`
2. `templates/tools/dev_pipeline.html` → `templates/tools/repair_bay.html`
3. `.claude/rules/dev-pipeline.md` → `.claude/rules/repair-bay.md`

### Internal Module Files (update blueprint name, url_prefix, imports)

4. `tools/repair_bay/__init__.py` — blueprint name `repair_bay_bp`, url_prefix `/tools/repair-bay`
5. `tools/repair_bay/routes.py` — blueprint import ref
6. `tools/repair_bay/scan_routes.py` — any self-references
7. `tools/repair_bay/proposal_routes.py` — any self-references
8. `tools/repair_bay/sandbox_routes.py` — any self-references
9. `tools/repair_bay/deploy_routes.py` — any self-references
10. `tools/repair_bay/github_routes.py` — any self-references
11. `tools/repair_bay/repair_routes.py` — any self-references
12. `tools/repair_bay/station_routes.py` — any self-references
13. `tools/repair_bay/services/*.py` — update any `from tools.dev_pipeline` imports (33 files, grep for refs)

### External Files (update imports, URLs, string refs)

14. `app.py` — import path for blueprint
15. `module_registry.py` — id, name, route, blueprint_import, health_check
16. `rbac.py` — permission key
17. `services/audit_pipeline.py` — module_id string
18. `services/proposal_service.py` — import from tools.dev_pipeline
19. `services/sandbox_service.py` — import from tools.dev_pipeline
20. `services/scan_service.py` — module_id and module_source strings
21. `services/browser_test_service.py` — URL string
22. `mcp_server/tools/forge_tools.py` — import paths
23. `static/js/consciousness.js` — URL references
24. `static/js/department-ops.js` — URL references
25. `static/js/starbase.js` — URL references
26. `templates/includes/dev_tools_nav.html` — URL references
27. `templates/tools/archie_chat.html` — URL references
28. `tools/consciousness/code_health_routes.py` — references
29. `tools/consciousness/templates/consciousness_dashboard.html` — references
30. `tools/api_docs/routes.py` — references
31. `tools/team_management/routes.py` — references

### Tab Rename

32. `templates/tools/repair_bay.html` — change tab labels: Scan→Diagnose, Proposals→Repairs, Sandbox→Test Bay, Deploy→Ship

### Documentation

33. `.claude/rules/repair-bay.md` — update all content to use new names
34. `CLAUDE.md` — update any Dev Pipeline references (if present)

## Verification

After rename:
1. `grep -rn 'dev_pipeline\|dev-pipeline' platform_v2/` should return 0 results (excluding git history)
2. `docker compose restart archie_platform` — app boots without import errors
3. Navigate to `http://192.168.1.200:3000/tools/repair-bay` — module loads with 4 tabs (Diagnose, Repairs, Test Bay, Ship)
4. F.O.R.G.E. GitHub webhook still works at `/tools/repair-bay/api/forge/webhook`
