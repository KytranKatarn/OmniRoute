# Agent Directory Backfill (Phase 2) — Design

**Date:** 2026-07-16
**Owner:** Kytran
**Project:** #388 Agent Directory Integrity — Phase 2 (task #4946)
**Status:** Approved (design decisions); spec pending owner review
**Scope:** AI acronym agents (`worker_type='ai'`) only. Builds on the shipped `agent_identity_builder` (Phase 1).

---

## Problem

Of 55 non-decommissioned AI agents, ~12 are **incomplete but actively used** — several are the platform's busiest (A.X.I.O.M. 9,396 / V.E.T. 8,924 / E.T.H.O.S. 10,174 dispatches in 90d) yet run with a **0-char or thin system prompt**. The Phase-1 builder only fixes *new* hires; the existing directory needs a one-time enrichment pass. (Only V.I.S.A.G.E. #334 is idle — the lone dismiss candidate; that goes to the K.I.N. lifecycle lane #4950, not here.)

## Goal

Bring every incomplete-but-used AI agent to a **complete, directory-aligned identity** — **preserving each agent's established identity** (name + any existing good expansion/title/bio/personality) and only **filling gaps + deepening the thin/empty system prompt**. Owner reviews a single before→after doc before anything is written. Sovereign-local, single-writer, human-reviewed.

## Key decisions (owner-approved)

- **Enrich, don't regenerate.** Keep existing non-empty fields; fill only what's missing; always rebuild the (thin/empty) system prompt from the *merged* fields. Protects live personas (a 9k-dispatch agent's meaning/voice must not change out from under it).
- **Review via a generated before→after doc** (an Artifact). Owner skims once → approve-all or flag individuals → apply the approved set. No new UI.
- **Scope = the ~12 incomplete-but-used agents.** Skip idle V.I.S.A.G.E. #334 (dismiss lane). C.H.A.I.N. #365 (2) / R.E.S.T.O.R.E. #335 (4) are borderline-low-use → include in the doc, owner decides keep-or-dismiss per-agent.
- **Priority order:** the heavily-used BROKEN first (A.X.I.O.M., V.E.T., S.T.R.I.N.G.E.R., T.R.I.A.G.E.).
- **Generation delegated to the fleet** (M.U.S.E., `build_identity` → `local_only`), per the module-work-pattern.

---

## Design

### Component 1: `agent_identity_builder.enrich_identity(current, capability, department)` (pure)

```
enrich_identity(current: dict, capability: str, department: str) -> dict
```

- `current` = the agent's existing fields: `{name, acronym_expansion, title, bio, personality_prompt, portrait_prompt, system_prompt}`.
- Generate a candidate: `build_identity(capability, department=department, existing_name=current["name"])`.
- **Merge (preserve non-empty, fill empty):** for `expansion, title, bio, personality, portrait_prompt` → keep `current` if non-empty, else take the candidate's.
- **Always rebuild `system_prompt`** from the *merged* fields via `_assemble_system_prompt(...)` (guaranteed ≥400 chars; reflects the preserved expansion/title/personality — this "deepens" a thin prompt without changing identity).
- Return `{name, after: {expansion,title,bio,personality,system_prompt,portrait_prompt,source}, changed: [fields that differ from current], portrait_needed: bool}`.
- Pure/mockable: `build_identity` is the only external call (mock it in tests). No DB.

### Component 2: `services/agent_backfill.py` (DB glue + orchestration)

- `_primary_capability(agent_id) -> str` — the agent's main `agent_skills.skill_name` (highest `proficiency_level`, else its department's default capability).
- `plan_backfill(agent_ids) -> list[dict]` — for each agent: load current fields, resolve capability + department, call `enrich_identity`, return `{agent_id, name, before, after, changed, portrait_needed}`. This is the review payload. (Runs the M.U.S.E. dispatches — slow ~20-25s each cold; run as a fleet-delegated batch / job, not on the web thread.)
- `apply_backfill(agent_id, after, portrait_needed) -> None` — **single-writer**: `agent_service.update_agent(agent_id, system_prompt=…, acronym_expansion=…, title=…, bio=…, personality_prompt=…, portrait_prompt=…)` (only the fields in `after`), then `agent_service.add_portrait(agent_id, after["portrait_prompt"], style="sci-fi")` **iff** `portrait_needed` (fail-open). Never raw SQL.

### Component 3: review doc + apply run (operational, controller-driven)

1. Run `plan_backfill([the ~12 ids])` (fleet-delegated) → collect the before→after set.
2. Generate a **before→after Artifact** (per agent: kept fields, newly-filled fields, prompt length before→after) for the owner.
3. Owner approves-all or flags → controller calls `apply_backfill(...)` for the approved set.
4. Redeploy not needed (data-only change; agents pick up the new prompt on next dispatch — verify via a re-audit query).

### Error handling
- `build_identity` cold-fleet → complete fallback (already guaranteed). A single agent's enrich failure is logged and skipped (doesn't abort the batch).
- Portrait enqueue is fail-open (never blocks an apply).
- All inference `local_only` (ADR-013); all agent writes via `agent_service` (single-writer).

### Testing (TDD)
- `enrich_identity`: preserves a non-empty existing field (expansion/bio kept); fills an empty field from the candidate; **always** returns a `system_prompt` ≥400 that contains the (preserved) name+expansion; `changed`/`portrait_needed` computed correctly; a broken agent (all-empty) gets a fully-filled identity.
- `apply_backfill`: calls `update_agent` with exactly the `after` fields; calls `add_portrait` only when `portrait_needed`; a portrait failure doesn't raise.
- `_primary_capability`: picks the highest-proficiency skill; falls back to the department default.

### Out of scope
- Dismiss decisions (V.I.S.A.G.E. + the 5 idle agents) → K.I.N. lifecycle #4950.
- The 42 existing-portrait "does it match?" review → #4949 (owner-gated).
- New-hire `worker_type` alignment → #4951.

---

## Non-goals
- No cloud inference, no direct Ollama, no raw SQL on `agents`.
- No auto-apply — every write is owner-reviewed via the before→after doc.
- Do not change an agent's name or an already-rich (≥400) system prompt.
