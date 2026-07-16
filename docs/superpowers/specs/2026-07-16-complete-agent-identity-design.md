# Complete Agent Identity — Design

**Date:** 2026-07-16
**Owner:** Kytran
**Status:** Approved (structure + Phase 1 build decision); spec pending owner review
**Scope:** AI acronym agents only (`agents.worker_type='ai'`). Internal / contractor / local rows are out of scope.

---

## Problem

Two linked defects in the agent directory:

1. **New hires are thin stubs.** Approving a net-new hire (`hiring_service._create_new_hire`) sets a generic 90-char system prompt (`"You are X, a specialist in Y in the Z department."`), one skill, and a budget — nothing else. No rich persona, bio, personality, or portrait. It does store `acronym_expansion`/`title` if the name generator returned them, but the expansion is never woven into the prompt.

2. **The existing directory is uneven.** Of 55 non-decommissioned AI agents:
   - **4 critical** — empty/stub system prompt: S.T.R.I.N.G.E.R. #379 (active, 0 chars), V.E.T. #380, A.X.I.O.M. #381, T.R.I.A.G.E. #416.
   - **~9 thin** (150–400 chars) — incl. P.R.O.B.E. #340 (232) and E.T.H.O.S. #336 (305).
   - **Field gaps across the whole set:** 6 missing `acronym_expansion`, 5 missing `bio`, 11 missing `personality_prompt`, 4 missing portrait.
   - **42 are rich** (400+ char prompt) — the reference bar (e.g. F.O.R.G.E. #136, 1344 chars, expansion woven in).

The `agents` table already has every needed column (`system_prompt`, `title`, `bio`, `personality_prompt`, `acronym_expansion`, `portrait_prompt`, `avatar_url`, `avatar_generation_prompt`, `voice_sample`). The pipeline just doesn't fill them.

## Goal

Every AI agent — newly hired and existing — carries a **complete, directory-aligned identity**: meaningful acronym + expansion, human title, bio, personality, a rich (400+ char) system prompt with the expansion woven in, and a portrait that represents the agent. All generation is **sovereign-local** (DHQ dispatch, ADR-013 — no cloud, no direct Ollama).

---

## Program structure (3 phases, one shared engine)

**Shared core — the Agent Identity Builder** (`services/agent_identity_builder.py`, extends today's `agent_name_generator.py`). One sovereign-local M.U.S.E. creative dispatch returns the *creative* JSON parts; a **deterministic template** assembles the rich system prompt from those parts + role/department/floor/platform conventions. This is the approved build model — it guarantees length/consistency and is robust to a weak/cold local model, while keeping the *meaning* LLM-authored.

- **Phase 1 — Complete-hire (this spec, build now).** Generate → full identity shown for review → Approve persists all fields + skill + budget + queues a sci-fi portrait. New hires are born complete.
- **Phase 2 — Full-directory backfill.** Run the same builder (keeping each agent's existing name) over every agent with any gap, owner-reviewed before apply; generate the 4 missing portraits; regenerate existing portraits only where they don't represent the agent (owner-gated, never blanket).
- **Phase 3 — Usage-based lifecycle.** K.I.N. analyzes dispatch activity → recommends **barrack** (occasionally useful) or **dismiss** (unused + redundant) → routed through the existing approval queue (human-approved, never auto). Feeds Phase 2's repair-or-dismiss decision.

Build order: 1 → 2 → 3. Each phase independently shippable and owner-reviewed.

---

## Phase 1 — Detailed design

### Component 1: `services/agent_identity_builder.py`

Public function:

```
build_identity(capability, department=None, *, existing_name=None,
               avoid_names=None, max_attempts=3) -> dict
```

Returns:

```
{
  "name": "V.E.R.I.F.Y.",          # dotted acronym; deduped, OR existing_name (backfill)
  "expansion": "Validation Engine Reviewing Information For Yield",
  "title": "Fact Checker",
  "bio": "<2-3 sentence backstory>",
  "personality": "<traits + voice, 1-2 sentences>",
  "system_prompt": "<assembled, >=400 chars, expansion woven in>",
  "portrait_prompt": "<sci-fi portrait description derived from role + meaning>",
  "source": "llm" | "fallback"
}
```

Internals:
- One creative dispatch (reuse `_dispatch_name` — timeout-bounded, `local_only`, `capability="creative"` → M.U.S.E.) with a prompt asking for STRICT JSON: `{name, expansion, title, bio, personality_traits, voice, portrait_hint}`.
- `_assemble_system_prompt(parts, name, role, department, floor)` — **deterministic template**. Shape (mirrors the rich reference agents):
  > "You are `NAME` (`EXPANSION`), the `TITLE` in the `DEPARTMENT` department on Floor `FLOOR` of the A.R.C.H.I.E. platform. Role: `<role sentence from parts/capability>`. Personality: `<personality>`. Voice: `<voice>`. You operate sovereign-local under DHQ dispatch and C.R.E.E.D. governance. `<capability-specific responsibilities>`."
  Guarantees ≥400 chars regardless of model verbosity.
- `_build_portrait_prompt(parts, name, department)` — sci-fi portrait description (per `feedback_portrait-style-rule`: AI acronym agents = sci-fi), seeded from role + acronym meaning.
- Quality gate: valid 4–7 letter acronym, non-trivial expansion (≥ N words, each mapping to a letter), assembled prompt ≥400 chars, name deduped vs all agents. Retry on collision (existing loop).
- **Fallback** preserved: if the dispatch times out/fails, deterministic parts (capability-derived expansion/title/bio) still flow through the template → a complete (if plainer) identity. `source="fallback"`.
- `existing_name` path (for Phase 2): skip name generation/dedupe, keep the name, regenerate expansion+title+bio+personality+system_prompt+portrait_prompt from the role.
- Reuse from `agent_name_generator.py`: `_normalize`, `_dotify`, `_valid_letters`, `_parse_json`, `_department_for_capability`, `_existing_names`, `_dispatch_name`. Keep `suggest_name` as a thin wrapper over `build_identity` (back-compat) OR leave it; `build_identity` is the new entry point.

### Component 2: suggest-identity route

`tools/department_hq/approvals_routes.py` — extend the existing
`POST /api/approvals/hire/<hire_id>/suggest-name` (or add `/suggest-identity`) to call
`build_identity(capability)` and return the full package. Keep the response shape a superset of
today's `{ok, name, expansion, title, source}` so nothing breaks.

### Component 3: frontend (net-new hire card)

`tools/department_hq/templates/department_hq.html` — the Generate handler already lands
`name`/`expansion`/`title` into `hireState.newAgent` + the hint. Extend it to also stash
`bio`, `personality`, `system_prompt`, `portrait_prompt` and show a short **identity preview**
(expansion · title · bio) under the input so the owner reviews *meaning* before approving.
The 15s auto-refresh guard (PR #2305, shipped) already protects this in-progress state.

### Component 4: complete creation on approve

`hiring_service._create_new_hire` — persist the full identity. All agent writes go through
`agent_service` (single-writer rule):
- `agent_service.create_agent(..., system_prompt=<assembled>)` as today, PLUS
- set `title`, `bio`, `personality_prompt`, `acronym`, `acronym_expansion`, `portrait_prompt`
  via `agent_service.update_agent(agent_id, **identity_fields)` (extend `create_agent` kwargs
  and/or `update_agent` to cover these columns — no direct SQL on `agents`).
- Then `add_skill` (dispatchable), `init_budget`, `log_creation_event` (unchanged), PLUS
- **queue a portrait**: enqueue a Media Studio generation job (media_generation_queue →
  media_generation_worker → ComfyUI) with the `portrait_prompt`, sci-fi style, writing back to
  `agent_portraits`/`avatar_url` on completion. Async — never blocks approve.

### Component 5: portrait enqueue helper

A thin helper (in `hiring_service` or a small `services/agent_portrait_enqueue.py`) that submits an
agent-portrait job to the existing Media Studio queue (`agent_portraits.agent_id` UNIQUE,
migration 331). Fail-open: a portrait failure must not fail the hire — the agent still exists,
the portrait retries.

### Error handling
- Builder dispatch failure/timeout → deterministic fallback identity (still complete). Never blocks the button (existing 20s wall-clock bound).
- Approve persistence: create_agent + update_agent in one flow; if the portrait enqueue fails, log + continue (agent is still complete textually).
- No cloud path anywhere (ADR-013, `local_only=True`).

### Testing (TDD)
- `build_identity`: valid acronym format; expansion non-trivial; **assembled system_prompt ≥400 chars even on the fallback path**; dedupe vs existing names; `existing_name` keeps the name; template weaves expansion+title+department.
- suggest-identity route returns the full superset package.
- `_create_new_hire` persists system_prompt + title + bio + personality_prompt + acronym_expansion + portrait_prompt (assert on the row) and enqueues exactly one portrait job.
- Portrait-enqueue failure does not fail the hire.

### Out of scope for Phase 1
- Backfilling existing agents (Phase 2 — reuses `build_identity(existing_name=...)`).
- The barrack/dismiss lifecycle advisor (Phase 3).
- Regenerating the 42 existing portraits (Phase 2, owner-gated).

---

## Phases 2 & 3 (outline — separate specs/plans)

**Phase 2 — full-directory backfill.** A one-time, owner-reviewed pass: for each AI agent with a
gap (empty/thin prompt, or missing expansion/bio/personality/portrait), run
`build_identity(existing_name=..)`, present a review batch, apply on approval, and generate the 4
missing portraits. Regenerate an existing portrait only when the owner flags it as not matching.
Delegated to the fleet (M.U.S.E.) per the module-work pattern — not ground out by hand.

**Phase 3 — usage-based lifecycle.** K.I.N. computes per-agent dispatch activity (from
`task_execution_log`) over a window; agents with no activity + a redundant skill peer →
recommend **dismiss**, occasionally-used → **barrack**. Surface as `hiring_candidates`-style rows
in the existing approval queue (inverse of a hire). Human-approved; never auto-decommission.
Reuses the `welfare_governance_service.recommend_*` + approval-queue patterns.

---

## Non-goals
- No cloud inference. No direct Ollama. No changes to internal/contractor/local roster rows.
- No auto-dismiss / auto-hire — every lifecycle action is human-approved.
