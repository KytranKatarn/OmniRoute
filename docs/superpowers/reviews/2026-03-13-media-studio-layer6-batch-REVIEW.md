# Layer 6 Batch Generation & Queue Management -- Spec Review

**Reviewer:** Senior Code Reviewer (Claude Opus 4.6)
**Spec:** `/mnt/archie_brain/docs/superpowers/specs/2026-03-13-media-studio-layer6-batch-design.md`
**Date:** 2026-03-13

---

## Overall Assessment

This is a well-structured spec that follows the established Layer 5 conventions closely. The database schema, service functions, API routes, and UI sections are all present and clearly specified. The scope is focused and achievable. Below are the specific findings.

---

## Issues (Must Fix)

### Issue 1: `submit_generation()` signature mismatch -- batch_id cannot be set after the fact

The spec says `expand_batch` "calls `submit_generation()` from generation_service.py with the merged params and gets `batch_id` set on the resulting queue entry." However, the existing `submit_generation()` signature is:

```python
def submit_generation(user_id, media_type, prompt, negative_prompt="", params=None, owner_type="user", owner_id=None) -> Dict
```

It returns `{"queue_id": N, "status": "dispatched", ...}` but has **no `batch_id` parameter**. The queue INSERT in `submit_generation()` does not include a `batch_id` column.

**The spec must specify one of:**
- (A) Add an optional `batch_id` parameter to `submit_generation()` so it can be set at INSERT time (cleanest), or
- (B) Have `expand_batch` do a separate `UPDATE media_generation_queue SET batch_id = %s WHERE id = %s` after each `submit_generation()` call (works but is two transactions per item).

**Recommendation:** Option A. Add `batch_id: Optional[int] = None` to the signature and include it in the INSERT. The spec should document this modification to `generation_service.py` explicitly.

### Issue 2: `expand_batch` args include `owner_type`/`owner_id` but `submit_generation` uses `user_id`

The spec defines `expand_batch` with `owner_type, owner_id` args, but `submit_generation()` takes `user_id` as its first positional arg (not `owner_id`). For agent-owned batches (`owner_type="agent"`), the spec does not clarify how the dispatch call maps `owner_type + owner_id` to `submit_generation(user_id=...)`.

**Fix:** The spec should note that for `owner_type="user"`, `user_id = owner_id`. For `owner_type="agent"`, the spec needs to define what `user_id` value is passed (likely the system user or the agent's assigned user). This is an edge case that will cause bugs if not specified.

### Issue 3: `prompt` sweep type listed in text but not in sweep logic

Line 23 lists `sweep_param` values as `seed`, `model`, `prompt`, **or NULL**. But the expansion logic section (lines 61-63) only defines behavior for NULL, `seed`, and `model`. There is no expansion rule for `sweep_param = 'prompt'`, which does not make sense anyway since prompts are already the multi-prompt axis. The `prompt` value should be removed from the `sweep_param` allowed values, or the spec should explain what "prompt sweep" means distinctly from the multi-prompt input.

**Fix:** Remove `prompt` from the allowed `sweep_param` values in the table definition notes. The column comment should say: `seed`, `model`, or NULL.

### Issue 4: `on_generation_failed` hook not shown in Generation Service Hook section

The spec (line 154) says "Same pattern needed for failure handling" but only shows the code snippet for the success path (`on_generation_complete`). The failure path in `on_generation_failed()` needs an identical hook. Since this is a code modification to an existing file, the spec should show both snippets explicitly to avoid ambiguity during implementation.

**Fix:** Add the concrete code snippet for the failure hook inside `on_generation_failed()`.

---

## Suggestions (Nice to Have)

### Suggestion 1: Specify the `prompt` column on `media_generation_queue`

The existing `media_generation_queue` table (migration 149) stores prompt inside `params JSONB`, not as a separate column. The spec's `get_batch_items` function says "LEFT JOIN media_library for thumbnails" but does not clarify how prompt text is extracted for display in queue cards. The implementer will need to know it comes from `params->>'prompt'`. A brief note would help.

### Suggestion 2: Concurrency guard for `update_batch_counters`

If multiple queue items from the same batch complete near-simultaneously, `update_batch_counters` could race. Since it does a COUNT + UPDATE pattern, consider noting that this should use `SELECT ... FOR UPDATE` on the batch row, or accept eventual consistency (the next completion will correct it). The current spec is silent on this.

### Suggestion 3: Add `prompt` sweep clarification or `cfg_scale`/`steps` as future sweep params

The sweep feature currently supports only `seed` and `model`. A note about extensibility (e.g., adding `cfg_scale` or `steps` as sweep params later) would future-proof the design. The JSONB `sweep_values` column already supports this, so just a sentence acknowledging it would suffice.

### Suggestion 4: Queue panel element ID prefixes

The UI section describes JS function names (`toggleQueuePanel`, `loadQueueStats`, etc.) but does not specify element IDs for the queue panel, batch modal, or interactive elements. The existing convention uses `ms-` prefixes (e.g., `ms-gallery-grid`). The spec should list key element IDs like `ms-queue-panel`, `ms-queue-badge`, `ms-batch-modal`, `ms-batch-prompts`, `ms-batch-preview` for implementation consistency.

### Suggestion 5: Batch modal -- how are "shared params" populated?

The spec says the batch modal has "same controls as single generation (model selector, size, negative prompt, etc.)" but does not specify whether these are cloned DOM elements or a shared form. Since the batch modal is triggered from each media type tab, the implementer needs to know if the modal reads current tab state or maintains its own state. A brief note would help.

### Suggestion 6: Files summary missing `generation_service.py` hook detail

The files summary correctly lists "Modify `services/generation_service.py`" but could note the specific function names modified (`on_generation_complete`, `on_generation_failed`) and the new parameter addition (`batch_id` on `submit_generation`).

---

## Consistency Checks

| Check | Result |
|-------|--------|
| All service functions have args + returns + notes | PASS |
| All API routes have method, path, body, returns | PASS |
| Service functions match API routes (no orphans) | PASS |
| Files summary matches spec body | PASS (minor: see Suggestion 6) |
| Migration number sequential (151 -> 152) | PASS |
| DB constraints and indexes fully specified | PASS |
| Status transitions documented | PASS |
| Edge case: >50 cap | PASS (specified in expansion logic + UI preview) |
| Edge case: 0 prompts | PASS (submit button disabled) |
| Edge case: cancelled mid-batch | PASS (cancel_batch sets pending/dispatched to cancelled) |
| Edge case: empty prompts in textarea | Not specified -- should blank lines be stripped? |
| APScheduler job registration location | PASS (__init__.py) |
| Polling behavior specified | PASS (5s stats, 10s items, stops when collapsed) |
| Layer 5 pattern consistency | PASS (same table structure, service pattern, route pattern) |

---

## Verdict: NEEDS_FIXES

Four issues must be addressed before implementation:
1. Specify how `batch_id` gets into `submit_generation()` / queue INSERT
2. Clarify `user_id` vs `owner_id` mapping for agent-owned batches
3. Remove `prompt` from allowed `sweep_param` values (or define its behavior)
4. Show the explicit `on_generation_failed` hook code

All four are straightforward to resolve with a few sentences each. The spec is otherwise solid and ready for implementation after these fixes.
