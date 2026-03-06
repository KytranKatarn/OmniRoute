---
globs: ["platform_v2/tools/consciousness/**"]
---

# Consciousness Module Rules

## Structure
- 5 tabs (ADR-058): Dashboard, Knowledge, Team, GitHub, Languages
- Route split (ADR-045): `routes.py` + `knowledge_routes.py` + `team_routes.py` + `insights_routes.py` + `github_routes.py` + `integration_routes.py`
- Pattern: `register_*_routes(bp, admin_required)` in `__init__.py`
- External JS: `static/js/consciousness.js` — `api()` helper, `switchConsciousnessTab()`, `escHtml()`/`setHtml()`

## CSS
- Prefix: `cs-` (vs `devhq-` for Dev HQ) | Accent: purple #8b5cf6
- HoloSphere: `static/css/holo-sphere.css` + `static/js/holo-sphere.js`
- GlassNav: `static/css/glass-nav.css` + `static/js/glass-nav.js`

## Async Batch Jobs (ADR-048/049/050)
- Background threads, return job_id immediately
- Duplicate prevention: `create_job()` checks running job with same type+module
- `_log_governance()` writes direct to DB (not iaae_routes — avoids Flask context in threads)

## DB Gotchas
- `agent_emotional_state` (SINGULAR) — no `relationship_strength`, use `stress_level`/`mood_intensity`
- `agent_identity` (not `agent_personalities`)
- `agent_activity_events` (not `agent_activity_log`)
- `has_embedding` — use `embedding IS NOT NULL`
- Agent names: DB=code names (Nexus), UI=human names (Jin Park) via `display_name`

## Blueprint Gotcha (ADR-021)
If module has `templates/` subdir, MUST set `template_folder="templates"` in Blueprint.
