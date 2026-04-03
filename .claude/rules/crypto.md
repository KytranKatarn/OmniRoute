---
globs: ["platform_v2/tools/archie_pool/**", "platform_v2/tools/pool_management/**"]
---

# Crypto Rules

## Modules
- **Archie Pool** — `/tools/archie-pool`, `archie_pool_bp`
- **Pool Management** — `/tools/pool-management`, `pool_management_bp` (5+ routes)

## Status
- Phase 7 Standalone Apps — admin dashboard for mining pool
- Minimal/early-stage implementation

## Structure
- Each: `routes.py` + `__init__.py` in `tools/{module_name}/`
- Templates: `templates/tools/{module_name}.html`
- No Bridge dispatch — external pool API calls via requests

## Gotchas
- Pool API external endpoint configuration required
- Development mode uses random data generation for testing
- No per-user data isolation needed (admin-only module)
