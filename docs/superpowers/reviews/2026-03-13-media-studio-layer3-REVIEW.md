# Media Studio Layer 3 Plan Review

**Reviewed by**: Code Review Agent
**Date**: 2026-03-13
**Plan**: `docs/superpowers/plans/2026-03-13-media-studio-layer3.md`
**Spec**: `docs/superpowers/specs/2026-03-13-media-studio-design.md` (sections 6.1-6.6)

---

## Summary

The plan is well-structured with 7 tasks across 2 chunks, covering AnimateDiff workflow, video generation flow, external providers, API routes, UI, CSS, and integration testing. Below is a per-criterion assessment.

---

## 1. Spec Coverage — PASS (with 2 gaps)

| Spec Requirement | Plan Coverage | Status |
|---|---|---|
| 6.1 Video types (img2vid, txt2vid, img2img anim) | img2vid via `ref_image`, txt2vid via prompt-only path | PARTIAL — img2img animation mode not addressed |
| 6.2 Provider routing (4-tier escalation) | Task 3 adds `submit_external_video()` + `get_video_providers()` | PASS |
| 6.3 Generate tab updates (duration/FPS/motion/ref/provider/cost preview) | Task 5 adds all controls except cost preview | PARTIAL — no estimated cost preview before submit |
| 6.4 ComfyUI plugins (AnimateDiff Evolved + VideoHelperSuite) | Workflow uses both node types | PASS |
| 6.4 VRAM constraints table (enforced by Bridge before dispatch) | Plan relies on existing `OPERATION_REQUIREMENTS` + `can_node_handle()` | PASS |
| 6.5 External provider integration (submit/poll/capabilities) | `submit_external_video()` + `get_video_providers()` stubs | PASS |
| 6.5 Supported providers (Runway, Kling, Pika) | Referenced in docstrings, uses existing `call_external()` | PASS |
| 6.6 `build_animatediff_workflow()` location | Plan puts it in `comfyui_manager.py` (matches spec) | PASS |
| 6.6 `download_external_result()` | NOT in plan | MISSING |

**Gaps:**
- **Important**: Spec 6.6 mentions `download_external_result(provider, url)` — not implemented in any task. External video completion path needs a download step after polling.
- **Suggestion**: Spec 6.3 mentions "Estimated cost preview for paid providers before submit" — not in the plan. Could be a fast follow.
- **Suggestion**: Spec 6.1 mentions "Img2img animation" as a third mode — plan only covers txt2vid and img2vid. Acceptable if deferred.

---

## 2. File Paths — PASS (all correct)

| Plan File Path | Exists | Status |
|---|---|---|
| `platform_v2/tools/media_studio/services/comfyui_manager.py` | Yes (354 lines) | PASS |
| `platform_v2/tools/media_studio/services/generation_service.py` | Yes (398 lines) | PASS |
| `platform_v2/tools/media_studio/routes.py` | Yes (334 lines) | PASS |
| `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Yes | PASS |
| `platform_v2/tools/media_studio/static/css/media-studio.css` | Yes (ends at S16) | PASS |
| `ai_bridge/external_providers.py` | Yes (has `call_external()` at line 422) | PASS |

---

## 3. Code Snippets Consistency — FAIL (5 issues)

### Critical Issues

**C1: Wrong element IDs in `submitGeneration()` replacement (Task 5, Step 5)**

The plan references `genPrompt`, `genNegPrompt`, `generateBtn`, `genModel`, `genSeed`, etc. The actual HTML uses `msPrompt`, `msNegPrompt`, `msGenerateBtn`, `msModel`, `msSeed`, `msSteps`, `msCfg`, `msSampler`.

Every `getElementById` call in the plan's `submitGeneration()` will fail silently and produce empty/null values. This is a **breaking bug**.

Affected IDs that must be corrected:
- `genPrompt` -> `msPrompt`
- `genNegPrompt` -> `msNegPrompt`
- `generateBtn` -> `msGenerateBtn`
- `genModel` -> `msModel`
- `genSeed` -> `msSeed`
- `genWidth`, `genHeight` -> size comes from `msSizePresets` buttons (different pattern)
- `genSampler` -> `msSampler`
- `genSteps` -> `msSteps` (range slider, needs `.value`)
- `genCfg` -> `msCfg` (range slider, needs `.value`)

**C2: `submitGeneration()` is inside an IIFE — plan writes to global scope**

The existing `submitGeneration` is declared at line 691 as `window.submitGeneration = function() { ... }` inside an IIFE (`(function() { "use strict"; ...})()`). The plan's replacement code snippet is written as a bare `async function submitGeneration()` which would need to be inside the IIFE or similarly exposed as `window.submitGeneration`. The plan does not account for this scoping pattern.

**C3: Plan duplicates `DEFAULT_VIDEO_PARAMS` in two files**

Task 1 adds `DEFAULT_VIDEO_PARAMS` to `comfyui_manager.py` and Task 2 adds a similar `DEFAULT_VIDEO_PARAMS` to `generation_service.py`. These have overlapping but inconsistent values (comfyui_manager has `motion_model` but not `duration`; generation_service has `duration` but not `motion_model`). Only the `generation_service.py` version should exist — the `comfyui_manager.py` function should accept explicit parameters only.

### Important Issues

**I1: Plan says `build_ipadapter_workflow()` ends around line 354**

The file is 354 lines total and `build_ipadapter_workflow` starts at line 261. The plan's assertion is correct that it is the last function. However, the plan says "After `build_ipadapter_workflow()` (end of file)" — this is accurate. No issue here.

**I2: Plan says `merged_params` line is around line 60**

Actual line is 60: `merged_params = {**DEFAULT_IMAGE_PARAMS, **(params or {})}`. Confirmed correct.

### Suggestion

**S1: `psycopg2.extras.Json` import not verified**

Task 3's `submit_external_video()` uses `psycopg2.extras.Json()` but the plan doesn't check if this import exists in `generation_service.py`. Need to verify or add `import psycopg2.extras` to the file.

---

## 4. Missing Steps or Tasks — FAIL (2 missing)

**M1: No `poll_external_video()` function**

Spec 6.5 defines `poll_video(job_id) -> {status, url, error}` as a required adapter method. Task 3 only adds `submit_external_video()` and `get_video_providers()`. There is no polling mechanism for external video jobs (which are async by nature — submit returns a job_id, then you poll). Without this, external video generation can never complete.

**M2: No video file serving route**

Generated videos are saved to `MEDIA_ROOT` but there is no route to serve `.mp4` files. The existing gallery/media serving may handle this if it is extension-agnostic, but the plan does not verify this. If the gallery `send_file` or static serving only handles images, videos will be unplayable.

---

## 5. Task Ordering — PASS

Dependencies are respected:
1. Task 1 (AnimateDiff workflow builder) before Task 2 (generation flow that imports it)
2. Task 2 (generation flow) before Task 3 (external stubs that extend it)
3. Tasks 1-3 (backend) before Task 4 (routes that call them)
4. Task 4 (routes) before Task 5 (UI that calls routes)
5. Task 5 (UI) parallel with Task 6 (CSS) — no dependency conflict
6. Task 7 (integration test) after all others

The chunk split (backend first, then API+frontend) is clean.

---

## 6. Security — PASS (with 1 note)

| Check | Status | Details |
|---|---|---|
| innerHTML usage | PASS | Plan explicitly states "Uses DOM API exclusively (no innerHTML)". Confirmed: plan's JS uses `textContent`, `classList.toggle`, `createElement`, `appendChild` only. |
| SQL injection | PASS | All SQL uses parameterized queries (`%s` with tuple args). `psycopg2.extras.Json()` used for JSONB. |
| Input validation | PASS | Route validates JSON body present, prompt non-empty. |
| File upload (ref_image) | NOTE | The `ref_image` parameter is passed straight through to the ComfyUI workflow. If this is a user-supplied filename, it could be a path traversal vector inside ComfyUI. The plan should validate that `ref_image` is a basename only (no `/` or `..`). |

**Existing innerHTML in codebase**: Line 440 uses `div.innerHTML` inside the `escHtml()` helper function — this is safe (reads innerHTML of a textContent-set div for escaping purposes, not user-content injection).

---

## Verdict Summary

| Criterion | Result |
|---|---|
| 1. Spec coverage | PASS (2 minor gaps) |
| 2. File paths | PASS |
| 3. Code snippets | **FAIL** (3 critical, 1 important) |
| 4. Missing steps | **FAIL** (2 missing tasks) |
| 5. Task ordering | PASS |
| 6. Security | PASS (1 note) |

---

## Required Fixes Before Implementation

1. **[Critical C1]** Fix all element IDs in Task 5's `submitGeneration()` to use `ms*` prefix (`msPrompt`, `msNegPrompt`, `msGenerateBtn`, `msModel`, `msSeed`, `msSteps`, `msCfg`, `msSampler`). Size extraction needs to read from the active size preset button, not `genWidth`/`genHeight`.

2. **[Critical C2]** Ensure the rewritten `submitGeneration()` is scoped correctly — either inside the existing IIFE as `window.submitGeneration = async function() { ... }` or verify it replaces the existing function properly.

3. **[Critical C3]** Remove `DEFAULT_VIDEO_PARAMS` from Task 1 (comfyui_manager.py). Keep it only in Task 2 (generation_service.py) where it belongs.

4. **[Important M1]** Add a `poll_external_video()` function in Task 3 that checks external provider job status and calls `on_generation_complete()` when done.

5. **[Important M2]** Verify or add video file serving support in the gallery/media serving path.

6. **[Suggestion]** Add `ref_image` basename validation to prevent path traversal.

7. **[Suggestion]** Verify `psycopg2.extras` import exists in `generation_service.py`.
