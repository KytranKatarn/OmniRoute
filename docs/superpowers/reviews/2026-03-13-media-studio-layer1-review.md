# Media Studio Layer 1 Plan Review

**Reviewer**: Senior Code Reviewer (Claude Opus 4.6)
**Date**: 2026-03-13
**Verdict**: **ISSUES** (5 fixes required before execution)

---

## What Was Done Well

- All 10 tasks have clear step-by-step instructions with exact bash commands
- Dependency order is correct: DB -> services -> routes -> directories -> UI -> CSS -> wire -> test
- Follows platform conventions: `get_db_cursor`, `login_required`, `template_folder="templates"`, services layer
- All spec Layer 1 API endpoints are covered in the plan routes
- Migration SQL is idempotent (`IF NOT EXISTS`) per CLAUDE.md rules
- Existing `bridge_dispatcher.py` already has `image_generation` in CAPABILITY_STATION_MAP, so no dispatcher changes needed (plan correctly omits this as a task)
- Correctly wraps existing `ai_bridge/comfyui_service.py` rather than reimplementing

---

## Critical Issues (Must Fix)

### C1: Health check path is wrong after template move

The existing `module_registry.py` health check (line ~187) looks for:
```
/app/templates/tools/media_studio.html
/mnt/archie_brain/platform_v2/templates/tools/media_studio.html
```

But the plan moves the template to:
```
platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
```

**Fix**: Add a task (between Task 5 and Task 7) to update `media_studio_health_check()` in `module_registry.py` to check the new path:
```
/app/tools/media_studio/templates/tools/media_studio/media_studio.html
```
Or simply make the health check verify the blueprint is importable rather than checking a filesystem path.

### C2: Existing `routes.py` uses `get_db()` — old pattern leaks connections

The existing `routes.py` defines `get_db()` using `from database import get_db as _get_db` (raw connection, caller must close). The plan rewrites routes to use services with `get_db_cursor`, which is correct, but does not mention removing old route functions that may still reference `get_db()`. If any old route code remains after the "full rewrite", leaked connections will occur.

**Fix**: Task 5 Step 2 should explicitly state: "Delete ALL existing route functions. This is a full replacement, not a merge."

---

## Important Issues (Should Fix)

### I1: No RBAC permissions added

The spec (Section 11.2) says to add `MEDIA_STUDIO_GENERATE` and `MEDIA_STUDIO_MANAGE` to `rbac.py`. The existing `module_registry.py` entry has `required_permissions=[]`, and there are no `MEDIA_STUDIO_*` entries in `rbac.py` today. CLAUDE.md rule #4 states: "Module perms - Add to BOTH `rbac.py` AND `module_registry.py`".

The plan has no task for RBAC updates. Since `minimum_role="USER"` provides base access and the existing entry has `required_permissions=[]`, this works for Layer 1 but violates the spec and CLAUDE.md convention.

**Fix**: Add a task (or step in Task 5) to add `MEDIA_STUDIO_GENERATE` and `MEDIA_STUDIO_MANAGE` permissions to `rbac.py` Permission enum and role mappings. Update `module_registry.py` `required_permissions` accordingly.

### I2: `media_generation_queue.owner_id` spec says `NOT NULL` but plan says nullable

Spec Section 3.2: `owner_id INTEGER NOT NULL`
Plan migration: `owner_id INTEGER,` (nullable, with `DEFAULT 'user'` on owner_type)

For a queue table, every job should have an owner. System-owned jobs (environment art) are Layer 2, and even those could use a system user ID.

**Fix**: Make `owner_id INTEGER NOT NULL` in the migration to match the spec. The `media_library` table correctly allows NULL for system-owned items, but queue entries should always have an owner.

### I3: Docker volume mount path mismatch

Docker compose line 246 shows: `./platform_v2/static/media:/media`

But the services use `MEDIA_ROOT` pointing to `platform_v2/static/media/` (relative to module). Inside Docker, the app runs from `/app/`, so the actual path would be `/app/static/media/`. The Docker mount maps host `./platform_v2/static/media` to container `/media`, NOT to `/app/static/media/`.

**Fix**: Either update `MEDIA_ROOT` in the services to use `/media` (matching Docker mount), or update the Docker compose volume to mount at `/app/static/media`. The latter is more consistent with how static files are served. Task 6 should verify or fix this mount.

---

## Suggestions (Nice to Have)

### S1: Missing `services/__init__.py` content

Task 2 Step 1 creates an `__init__.py` with just a docstring. Consider adding `__all__` exports for the three services to make imports cleaner.

### S2: No mention of removing old template

The old template at `platform_v2/templates/tools/media_studio.html` should be deleted (or confirmed already absent) to avoid confusion with the new blueprint-local template.

### S3: Task 7 commit message is truncated

The commit message in Task 7 Step 3 is cut off mid-sentence: `"feat(media-studio): LCARS UI — dashboard,`. Provide the full message.

### S4: `assign_media` endpoint in routes but function lives in gallery_service

The plan correctly puts `assign_media()` in `gallery_service.py` (matching spec Section 11.6), but routes.py imports it from gallery_service. This is fine, but the route for `POST /api/assignments` should be explicitly documented as a Layer 1 endpoint (it appears in routes.py code but not in the spec's Layer 1 endpoint list -- it is listed under Layer 2 Section 5.6).

---

## Spec Coverage Checklist

| Spec Layer 1 Item | Plan Coverage | Status |
|---|---|---|
| `media_library` table | Task 1 | OK |
| `media_generation_queue` table | Task 1 | OK (owner_id nullability issue noted) |
| `agent_portraits` table | Task 1 | OK (Layer 2 ready) |
| `media_assignments` table | Task 1 | OK |
| `agent_voices` table | Task 1 | OK (Layer 4 ready) |
| `generation_service.py` | Task 4 + Task 9 | OK |
| `gallery_service.py` | Task 3 | OK |
| `comfyui_manager.py` | Task 2 | OK |
| Blueprint + routes rebuild | Task 5 | OK |
| Dashboard tab | Task 7 | OK |
| Generate tab (wizard) | Task 7 | OK |
| Gallery tab (masonry) | Task 7 | OK |
| Queue tab (live polling) | Task 7 | OK |
| Portraits tab (greyed out) | Task 7 | OK |
| All 10 API endpoints | Task 5 | OK |
| LCARS CSS | Task 8 | OK |
| ComfyUI E2E wire | Task 9 | OK |
| Media directories + .gitignore | Task 6 | OK |
| Module registry update | Not needed (exists) | OK |
| RBAC update | **Missing** | ISSUE I1 |
| Health check path update | **Missing** | ISSUE C1 |
| Bridge dispatcher changes | Not needed (already has capabilities) | OK |
