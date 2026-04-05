# Auto-Tag Bridge Dispatches with Project ID — Design Spec

**Date:** 2026-04-05
**Project:** #221 — Agent-Driven Knowledge Intelligence Phase 2
**Task:** #1634 — Auto-tag bridge dispatches with project_id
**Status:** Approved design, pending implementation

---

## Problem

Bridge dispatches (`request_work()`, `dispatch()`, `dispatch_json()`) create `bridge_jobs` rows without `project_id`. The Agent Contributions panel on the Consciousness Dashboard stays empty because there's no way to know which project a dispatch served. The `project_id` column and dispatcher plumbing exist (shipped in Phase 1, Decision #394), but no caller passes it and there's no auto-detection.

## Goals

1. **Auto-detect project** from prompt/capability text at dispatch time using cached keyword matching.
2. **Explicit passthrough** for call sites that already know the project context.
3. **Zero performance impact** — pure string matching with 5-min cached keywords, no embeddings.

## Approach

Dispatcher-level auto-detect + explicit passthrough (Approach A). A cached `_detect_project_id(text)` function inside `bridge_dispatcher.py`. In `request_work()`, if `project_id` is None, run the detector. Update call sites that have project context to pass it explicitly.

---

## Auto-Detect Function

### Location

`ai_bridge/bridge_dispatcher.py` — module-level function and cache, called from `request_work()`.

### Cache Design

```python
_project_keyword_cache = {}   # {keyword_str: project_id_int}
_project_cache_time = 0
_PROJECT_CACHE_TTL = 300      # 5 minutes
```

- Refreshed when `time.time() - _project_cache_time > 300`
- Typical size: ~50 keywords for 5-10 active projects
- Keywords: project slug split on hyphens (4+ chars) + project tags (4+ chars)

### `_load_project_keywords()`

Queries `unified_projects` where `status IN ('active', 'planning')`. For each project, splits slug on hyphens and adds tags. Filters words shorter than 4 chars. Returns `{keyword: project_id}` dict.

Uses `ai_bridge/db.py` `get_db()` for DB access (ai_bridge's own connection pattern, not platform_v2's `get_db_cursor`).

### `_detect_project_id(text)`

1. Check cache freshness, refresh if stale (>5 min).
2. Lowercase first 500 chars of text.
3. Count keyword matches per project: `{project_id: match_count}`.
4. Return project_id with highest match count if count >= 2. Return None otherwise.

### Injection Point

Inside `request_work()`, right before the bridge_jobs INSERT:

```python
if project_id is None:
    project_id = _detect_project_id(f"{capability} {prompt}")
```

Explicit `project_id` always takes priority — auto-detect only runs when None.

---

## Explicit Call Site Updates

### Update (caller has project context)

| Call Site | File | Source of project_id |
|-----------|------|---------------------|
| API Gateway | `platform_v2/api_gateway.py:210` | Optional `project_id` in request JSON body |
| Orchestration Engine | `ai_bridge/orchestration_engine.py:1381` | Pass through from api_gateway caller |
| Archie Chat | `platform_v2/tools/archie_chat/ha_bridge.py:204` | Check `user_context` dict for `project_id` key |
| API Standalone | `platform_v2/api_standalone.py:139` | Optional `project_id` in request JSON |
| Directory Chat | `platform_v2/tools/directory/chat_routes.py:197` | Optional `project_id` in request JSON |

### No Change (auto-detect covers these)

| Call Site | Reason |
|-----------|--------|
| `knowledge_analyzer.py` | KB analysis, not project-scoped |
| `translation_service.py` | i18n work, not project-scoped |
| `emotional_intelligence.py` | Agent wellness, not project-scoped |
| `agent_loop.py` (2 calls) | Autonomous jobs |
| `code_generation_engine.py` (4 calls) | Generic code gen |
| `proactive_intelligence.py` (2 calls) | System probing |
| `param_extractor.py` | Parameter extraction |
| `browser_automation.py` | Browser tasks |
| `auto_tagger.py` | KB tagging |
| `bridge_learning.py` | Learning extraction |
| `chat_handler.py` | Generic chat |
| `improvement_chat.py` (3 calls) | Improvement proposals |
| `forge_triage.py` | FORGE triage |

---

## Performance

| Metric | Value |
|--------|-------|
| Cache hit latency | ~0.1ms (dict lookup, 50 keys, 500 chars) |
| Cache miss (refresh) | 1 DB query every 5 min |
| Memory | ~2KB for keyword dict |
| Embedding generation | None — pure string matching |

## Edge Cases

- **Ambiguous keywords** (keyword in 2+ projects): highest match count wins. Ties go to lowest project_id (deterministic via `min()` on tied scores).
- **Short prompts** ("test", "hello"): won't hit 2-keyword threshold, returns None. Job stays untagged.
- **No active projects**: cache is empty, function returns None immediately.
- **New project created**: picked up within 5 min on next cache refresh.
- **Project deleted/completed**: removed from cache on next refresh. Existing bridge_jobs keep their project_id (historical data).

## What Stays Unchanged

- `bridge_jobs` table schema — `project_id` column already exists (Phase 1)
- `dispatch()` and `dispatch_json()` kwargs extraction — already works (Phase 1)
- `request_work()` signature — `project_id` param already exists (Phase 1)
- Bridge job INSERT — already includes `project_id` (Phase 1)
- Auto-linker backfill — still runs for historical jobs without project_id

---

## File Summary

| Action | File |
|--------|------|
| Modify | `ai_bridge/bridge_dispatcher.py` — add `_detect_project_id()`, `_load_project_keywords()`, cache vars, inject in `request_work()` |
| Modify | `platform_v2/api_gateway.py` — extract optional `project_id` from request, pass to orchestration |
| Modify | `ai_bridge/orchestration_engine.py` — accept and pass `project_id` to `request_work()` |
| Modify | `platform_v2/tools/archie_chat/ha_bridge.py` — extract `project_id` from `user_context` |
| Modify | `platform_v2/api_standalone.py` — extract optional `project_id` from request |
| Modify | `platform_v2/tools/directory/chat_routes.py` — extract optional `project_id` from request |
