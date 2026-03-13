# Media Studio Design Spec — Review

**Reviewer**: Claude Opus 4.6 (Code Review)
**Date**: 2026-03-13
**Spec**: `docs/superpowers/specs/2026-03-13-media-studio-design.md`
**Verdict**: APPROVED with ISSUES (5 must-fix, 8 suggestions)

---

## What Was Done Well

- Layered delivery approach is pragmatic — Layer 1 has zero plugin dependencies
- Bridge dispatcher already has `image_generation`, `video_generation`, `audio_generation` capabilities mapped (confirmed in `bridge_dispatcher.py` lines 76-81)
- Good reuse plan for existing `comfyui_service.py` and `portrait_generator.py`
- Filesystem layout is clean with date-partitioned directories
- Escalation chain matches existing ARCHIE patterns (local -> node -> free cloud -> paid cloud)

---

## ISSUES (Must Fix)

### 1. Blueprint Missing `template_folder` Parameter
**Severity**: Critical

The existing `__init__.py` registers:
```python
media_studio_bp = Blueprint("media_studio", __name__, url_prefix="/tools/media-studio")
```

The spec places templates at `templates/tools/media_studio/media_studio.html`, but the Blueprint has no `template_folder="templates"`. Per ADR-021 and `.claude/rules/frontend.md`, if the module has a `templates/` subdir, MUST set `template_folder="templates"`.

Additionally, the existing health check in `module_registry.py` looks for `/app/templates/tools/media_studio.html` (top-level templates dir), not within the Blueprint's template dir. The spec must clarify which template location pattern is being used and update the health check accordingly.

**Fix**: Add `template_folder="templates"` to Blueprint constructor in spec, or clarify templates live in top-level `platform_v2/templates/tools/`.

### 2. `bridge_job_id` FK Type Mismatch
**Severity**: Critical

`media_generation_queue.bridge_job_id` is declared as `INTEGER` but has no FK constraint to `bridge_jobs(id)`. This should either:
- Add `REFERENCES bridge_jobs(id)` explicitly, or
- Document why it's intentionally unconstrained (e.g., Bridge jobs may be deleted independently)

Also missing: an index on `bridge_job_id` for join performance.

**Fix**: Add `REFERENCES bridge_jobs(id) ON DELETE SET NULL` and `CREATE INDEX idx_media_queue_bridge_job ON media_generation_queue(bridge_job_id)`.

### 3. `owner_id` Polymorphic FK Without Validation
**Severity**: Important

Both `media_library` and `media_generation_queue` use `owner_type` + `owner_id` pattern where `owner_id` references either `users(id)` or `agents(id)`. The spec also mentions `owner_type='system'` for environment art (Section 5.4) but `owner_id` is `INTEGER NOT NULL` — what integer represents "system"?

**Fix**: Either allow `owner_id` to be NULL when `owner_type='system'`, or define a convention (e.g., owner_id=0 for system). Add a CHECK constraint: `CHECK (owner_type IN ('user', 'agent', 'system'))`.

### 4. Database Access Pattern Violation
**Severity**: Important

The existing `routes.py` uses `from database import get_db as _get_db` (raw connection pattern). The spec's service layer should use the standard pattern per `.claude/rules/database.md`:
```python
from database import get_db_cursor
with get_db_cursor(commit=True) as (conn, cur):
```

The spec's pseudocode doesn't specify which pattern to use. Since this is a rebuild, it must mandate `get_db_cursor`.

**Fix**: Add explicit note in spec that all services use `get_db_cursor` context manager, not raw `get_db()`.

### 5. VRAM Budget for AnimateDiff (Layer 3) Not Addressed
**Severity**: Important

AnimateDiff on SDXL requires ~10-12GB VRAM (motion model + base model). The Quadro M4000 has only 8GB. AnimateDiff on SD1.5 needs ~6-8GB — borderline. The spec says "Local ComfyUI AnimateDiff" as Tier 1 but doesn't acknowledge this constraint.

**Fix**: Add a note that AnimateDiff is SD1.5-only on Starbase (M4000), and SDXL AnimateDiff requires fleet nodes with larger GPUs. Update Tier 1 description to reflect this limitation.

---

## SUGGESTIONS (Nice to Have)

### S1. Missing `updated_at` on `media_library`
The table has `created_at` but no `updated_at`. Toggling favorite, soft-deleting, or reassigning media won't have a timestamp trail.

### S2. No Unique Constraint on `media_assignments`
Nothing prevents duplicate active assignments for the same target+type. Consider: `CREATE UNIQUE INDEX idx_media_assignments_unique ON media_assignments(assignment_type, target_type, target_id) WHERE is_active = true`.

### S3. `media_generation_queue` Lacks Cleanup Strategy
No mention of TTL, archival, or purging old completed/failed entries. This table will grow unbounded.

### S4. Category Mismatch
The spec says `category: MEDIA_HOME` but the existing module registry shows `MEDIA_HOME = "media_home"` which maps to `media_hub`. Confirm this is the intended category and that only one module occupies it.

### S5. API Endpoints Missing Auth Annotation
The spec lists endpoints but doesn't specify which require admin vs user role. Portrait management (approve canonical, bulk generate) should likely be admin-only.

### S6. Thumbnail Generation Detail
`on_generation_complete` mentions "Generate thumbnail (256px wide)" but doesn't specify the library (Pillow? ImageMagick?) or whether this happens synchronously in the callback or as a background task.

### S7. `assign_media` Duplicated Between Services
`gallery_service.assign_media()` (Section 4.2) and `portrait_service.assign_media()` (Section 5.4) appear to do the same thing. Consolidate into one location.

### S8. No Mention of `|localtime` or `archie-time.js`
Per frontend rules, all timestamps in templates must use the `|localtime` Jinja2 filter and JS timestamps must use `archie-time.js`. The spec should note this requirement for the UI layer.

---

## Schema Summary

| Table | Status | Notes |
|-------|--------|-------|
| `media_library` | OK with fixes | Add `updated_at`, CHECK on `owner_type` |
| `media_generation_queue` | OK with fixes | Add FK + index on `bridge_job_id`, handle system owner |
| `agent_portraits` | OK | Clean schema, UNIQUE on agent_id is correct |
| `media_assignments` | OK with suggestion | Add partial unique index for active assignments |
| `agent_voices` | OK | Clean schema |

---

## Existing Code Compatibility

| Component | Compatible | Notes |
|-----------|-----------|-------|
| `bridge_dispatcher.py` | YES | Already has image/video/audio capabilities mapped to CREATIVE |
| `comfyui_service.py` | YES | Wrap-and-extend pattern is sound |
| `portrait_generator.py` | YES | Diversity map reuse is correct approach |
| `external_providers.py` | PARTIAL | Has `get_providers_with_capability()` but no video adapter pattern yet — spec correctly notes this needs extension |
| `module_registry.py` | NEEDS UPDATE | Health check path must be updated for new template location |
| `rbac.py` | NEEDS UPDATE | Spec doesn't mention rbac.py entry — must add |
