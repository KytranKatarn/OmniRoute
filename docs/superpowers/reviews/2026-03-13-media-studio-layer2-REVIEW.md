# Review: Media Studio Layer 2 Implementation Plan

**Reviewed**: 2026-03-13
**Plan**: `docs/superpowers/plans/2026-03-13-media-studio-layer2.md`
**Spec**: `docs/superpowers/specs/2026-03-13-media-studio-design.md` (Section 5)

---

## Verdict: Approved with Minor Issues

The plan is well-structured across 3 chunks / 6 tasks and covers all spec requirements. No critical issues found.

---

## Completeness (Spec Section 5 Coverage)

- **Portrait workflow** (5.1): Covered — canonical gen, review, approve, IP-Adapter variant gen, diversity map fallback.
- **Environment art** (5.2): Covered — hub + node background generation, prompt templates, media_assignments integration.
- **Portraits tab UI** (5.3): Covered — agent grid, management panel, canonical/variant gen, approval toggle, variant gallery, "Generate All Missing" bulk action.
- **Portrait service** (5.4): Covered — all 6 functions from spec mapped to implementation.
- **ComfyUI plugins** (5.5): Covered — IP-Adapter Plus, Impact Pack referenced. InstantID mentioned in spec but not in plan workflow builder (acceptable — spec lists it as "backup").
- **API endpoints** (5.6): All 8 spec endpoints present. Plan adds 2 bonus endpoints (`PUT identity-prompt`, `GET environments/prompts`) which are sensible additions.
- **Assignments endpoints**: Already implemented in Layer 1 `routes.py` — plan correctly does NOT re-add them.

## Correctness

- **`agent_portraits` schema**: Plan matches migration 149 exactly — `agent_id`, `canonical_image_path`, `identity_prompt`, `face_seed`, `ip_adapter_ref_path`, `style_tags`, `approved`, timestamps. No column name mismatches.
- **`submit_generation` signature**: Current signature is `(user_id, media_type, prompt, negative_prompt, params)`. Plan correctly identifies the hardcoded `owner_type='user'` issue and adds `owner_type`/`owner_id` params with backward-compatible defaults.
- **`AGENT_DIVERSITY` structure**: Plan correctly references it as `Dict[str, Tuple[str, str]]` keyed by agent name with `(description, age_range)` tuples. Usage in `_build_identity_prompt()` matches.
- **Route patterns**: Plan follows existing `routes.py` patterns — `@media_studio_bp.route`, `@login_required`, lazy imports, `current_user.id`, JSON error responses.
- **File paths**: All paths match codebase conventions (`platform_v2/tools/media_studio/services/`, `ai_bridge/`).

## Platform Conventions

- **`get_db_cursor`**: Plan uses correct `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):` pattern throughout.
- **template_folder**: Not modified (already set in Layer 1 `__init__.py`).
- **RBAC**: No new permissions needed — portrait management is admin-only via existing `@login_required` (single-user SaaS). This is acceptable per spec scope but worth noting.

## Security

- **No innerHTML**: All JS DOM manipulation uses `document.createElement()` + `textContent` for user-provided strings (agent names, prompts, status text). Clean.
- **Identity prompt**: Rendered via `textarea.value` assignment (L893), not innerHTML. Safe.
- **Image sources**: `img.src` set from API JSON paths — no user-controlled HTML injection vector.

## Issues Found

### Important

- **(I1) RBAC gap for environment art**: The `POST /api/environments/generate` endpoint uses only `@login_required`. Since environment art affects the global hub/node UI, consider adding an admin check. Currently acceptable for single-user but fragile if multi-user is added later.

### Minor

- **(M1) InstantID omitted**: Spec section 5.5 lists InstantID as a backup face-matching plugin. Plan's `build_ipadapter_workflow()` only implements IP-Adapter Plus. Acceptable since spec says "backup", but the plan should note this is deferred.
- **(M2) No error handling for missing Pillow in portrait crops**: The existing `portrait_generator.py` has `HAS_PILLOW` guard. The new `portrait_service.py` should similarly handle missing Pillow gracefully for IP-Adapter ref extraction.
- **(M3) Two bonus endpoints undocumented in spec**: `PUT /api/portraits/{agent_id}/identity-prompt` and `GET /api/environments/prompts` are plan additions not in spec. They're useful — just note they're plan-originated extensions.

---

**Summary**: Plan is comprehensive, matches codebase conventions, and covers all spec requirements. The 1 important and 3 minor issues are non-blocking. Ready to implement.
