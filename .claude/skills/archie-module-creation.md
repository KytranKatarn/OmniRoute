---
name: archie-module-creation
description: Step-by-step guide for creating a new A.R.C.H.I.E. platform module
---

# Creating a New A.R.C.H.I.E. Module

## Steps
1. Create module directory: `platform_v2/tools/{module_name}/`
2. Create `__init__.py` with Blueprint definition
3. Create `routes.py` with endpoints
4. Create `services/` subdirectory for business logic
5. Create HTML template (extends base.html with extra_css, content, extra_js blocks)
6. Add to `module_registry.py` (ModuleCategory.SAAS_SERVICES)
7. Add permissions to `rbac.py` if needed
8. Create database migration in `database/migrations/`
9. Run migration in Docker
10. Restart platform

## Patterns
- Blueprint: `{name}_bp = Blueprint("{name}", __name__, url_prefix="/tools/{route}")`
- Routes: `@bp.route(...)` + `@login_required`, local imports, `jsonify()`
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- AI: `import sys; sys.path.insert(0, "/mnt/archie_brain/ai_bridge"); from archie_bridge import archie_bridge as ai_bridge`
- CSS: unique prefix per module, LCARS theme with module-specific accent color
- JS: IIFE, `window.funcName`, `api(method, path, body)`, createElement/textContent (no innerHTML)
