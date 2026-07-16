# DHQ Hiring Queue — "Generate" button for net-new agent names

**Date:** 2026-07-15
**Status:** Approved design (brainstorming complete)
**Branch:** `feat/hire-name-generator`
**Owner ask:** On the pending-hire approvals, add a way to generate an acronym-style agent
name recommended for the job — matching the existing A.R.C.H.I.E. naming convention
(F.O.R.G.E., V.I.G.I.L., M.A.V.E.N.) — without overlapping/duplicating existing names.

---

## 1. Problem

When a K.I.N. pool-saturation gap produces a **net-new** hire candidate (no existing agent to
reactivate), the DHQ Approvals form (PR #2288) makes the human **type the new agent's name by
hand**. There's no help producing a name that (a) follows the dotted-acronym convention, (b) fits
the job/capability, and (c) doesn't collide with any of the ~163 existing agent names (active or
decommissioned). This feature adds an on-demand **Generate** button that proposes a unique,
job-fit acronym name — plus what its letters stand for and a human role title.

## 2. Current state (verified against code, worktree `feat+maven-armada-visibility`)

- **Candidate row** — `hiring_candidates` (`platform_v2/services/hiring_service.py`): top-level
  cols include `capability`, `gap_reason`, `narrative`, `shortlist` (JSONB), `precheck_status`,
  `status`. **No per-candidate `model`/`department`/`title` column** — those live inside each
  `shortlist` JSONB entry (`agent_id`, `display_name`, `department`, `primary_model`,
  `proficiency_level`; net-new entries also carry `type:"new_hire"`, `agent_id:null`, `capability`,
  `note`). The capability to generate a name *for* is the row's `capability`.
- **Approve service** — `hiring_service.approve_candidate(*, hire_id, chosen_agent_id=None,
  decided_by_user_id, notes="", new_agent=None)` (L302-412). Net-new branch → `_create_new_hire()`
  (L188-299): reads `new_agent["name"]`, `["model"]`, optional `["display_name"]`; `display_name`
  default = `f"{capability.replace('_',' ').title()} Specialist"` (L209-211); department via
  `_department_for_capability(capability)`; **name-collision guard** already exists —
  `SELECT id, shift_state FROM agents WHERE name = %s` across **all** shift states (L229-238);
  creates via `agent_service.create_agent(name=, display_name=, department=, model=,
  shift_state="active", worker_type="internal", tier=3, system_prompt=…)` (L243-252) then
  `add_skill(id, capability, level=3, category=capability)` + `init_budget(id)` +
  `log_creation_event(...)`.
- **Route** — `platform_v2/tools/department_hq/approvals_routes.py`, blueprint prefix
  `/tools/department-hq`. Hire endpoints: `POST /api/approvals/hire/<int:hire_id>/approve`
  (L572-574 → reads `body["new_agent"]` / `body["chosen_agent_id"]`), `.../reject` (L618-620),
  `GET /api/approvals/pending` (L546-548, hiring block L482-510 returns the `shortlist`).
- **Frontend** — inline `<script>` in
  `platform_v2/tools/department_hq/templates/department_hq.html` (NOT department-hq.js). Net-new
  form built with `document.createElement` at **~L1397-1429**: closure vars `nameInput`
  (placeholder `New agent name (e.g. V.E.R.I.F.Y.)`, writes `hireState.newAgent.name`) and
  `modelSel` (`['qwen2.5:1.5b','llama3.2:3b','qwen2.5:7b','mistral:7b']`). **No element IDs** — all
  closure-scoped. Net-new detected via `shortlist.some(c => c.type==='new_hire' || c.agent_id==null)`
  (~L1390). Submit: `_dhqApproveHire(approvalId, hireState, btn)` (~L1707) builds
  `body = { new_agent: { name, model }, notes:'' }` → POST `.../hire/<id>/approve`.
- **Naming convention** — real agents are dotted uppercase acronyms with three linked fields
  (migration 158, e.g. F.A.I.T.H.): `name` == `display_name` == `acronym` = `F.A.I.T.H.`;
  `acronym_expansion` = "Faithful AI for Inspired Theological Heritage"; `title` = human role.
  Columns `acronym`, `acronym_expansion`, `title` exist on `agents`.
- **No DB UNIQUE constraint** on `agents.name` — uniqueness is app-level only. Decommissioned
  agents remain in the table, so a uniqueness check MUST include all shift states.
- **Sovereign dispatch** — canonical entry `from tools.department_hq.services.department_dispatcher
  import dispatch, dispatch_json`. `dispatch_json(capability, prompt, module_id="unknown",
  system_prompt=None, user_id=None, **kwargs) -> Optional[Dict]`; `**kwargs` forwards `local_only`,
  `prefer_agent`, etc. `local_only=True` sovereign precedent: `mail_hq_service.py:77`,
  `chronicle_story_service.py:120`, `benchmark_service.py:97`. `CAPABILITY_DEPARTMENT_MAP`:
  **`'creative'` → Creative & Design (M.U.S.E.)** — the natural fit for naming.

## 3. Approach

**Chosen: LLM generation + server-side validator + dedupe/retry + safe fallback (option B).**
- (A) One LLM call + dedupe/retry — simplest, but trusts model formatting blindly. Rejected.
- **(B) ✅** sovereign-local `creative` dispatch, then a lightweight server validator (format +
  strict uniqueness), bounded retry feeding collisions back into the avoid-list, deterministic
  fallback on exhaustion. Keeps creativity, guarantees well-formed + unique output.
- (C) Curated word-bank hybrid — guarantees real words but rigid, maintenance burden, over-built.
  Rejected (YAGNI).

**Owner decisions (brainstorming):**
1. **Trigger = Generate button** (on-demand, re-click to regenerate). Not auto-on-render (would
   fire an LLM dispatch per pending candidate every time Approvals opens).
2. **Output = name + expansion + title** (populate `display_name`/`acronym`/`acronym_expansion`/
   `title`, not just the bare name). Roster stays coherent; no bland "X Specialist".

## 4. Components

### 4.1 `platform_v2/services/agent_name_generator.py` (NEW)
Pure-ish service, no Flask context required (callable from a route).

```
suggest_name(capability: str, department: str, avoid_names: set[str] | None = None,
             *, max_attempts: int = 3) -> dict
    # returns {"name","expansion","title","source"}  source in {"llm","fallback"}
```
- Loads the avoid-set if not passed: `SELECT name FROM agents` (all shift states), normalized
  (uppercase, dot-stripped for comparison) — plus the caller-supplied `avoid_names`.
- Builds a `creative` prompt (see §5), dispatches `dispatch_json(capability="creative", prompt=…,
  system_prompt=…, module_id="hire_name_generator", local_only=True)`.
- Validates + dedupes the result (§6). On collision/malformed → retry (≤ `max_attempts`), each retry
  appends the rejected name to the avoid-list passed into the prompt.
- On exhaustion → `_fallback_name(capability, avoid_names)` deterministic generator (§6.3),
  `source="fallback"`.
- Helper `_normalize(name) -> str` (uppercase, strip dots/spaces) is the single comparison key used
  everywhere (generation dedupe AND — see §7 — reused by the approve guard).

### 4.2 Route — `approvals_routes.py`
`POST /tools/department-hq/api/approvals/hire/<int:hire_id>/suggest-name` (admin-gated, same
decorator as the other hire routes).
- Reads `capability` from the `hiring_candidates` row for `hire_id` (404 if missing). Client sends
  **no** capability (server-derived → nothing to trust/spoof).
- `department = _department_for_capability(capability)` (reuse hiring_service helper).
- Calls `agent_name_generator.suggest_name(capability, department)`.
- Returns `{"ok": true, "name","expansion","title","source"}`.
- **Fail-soft:** any dispatch/exception → HTTP 200 `{"ok": false, "error": "<short>"}` so the UI can
  say "couldn't generate — type one or retry". Never 500s the panel; manual approval unaffected.

### 4.3 Frontend — `department_hq.html` net-new form (~L1397-1429)
- Add a **Generate** button (LCARS styling, matches sibling buttons) appended to `form` next to
  `nameInput` (~L1425). Give `nameInput` a stable ref (already a closure var) + add a small
  `hintEl` line under it for the expansion/title.
- `onclick`: disable button + show "Generating…" → `fetch` POST `.../hire/<hireId>/suggest-name`
  → on `{ok:true}` set `nameInput.value = name`, `hireState.newAgent.name = name`,
  `.display_name = name`, `.expansion = expansion`, `.title = title`; render `hintEl` =
  `expansion — title` (via `textContent`, XSS-safe). On `{ok:false}` show the retry note. Always
  re-enable the button.
- Re-click = regenerate (server dedupes fresh each call).
- `_dhqApproveHire` (~L1707): extend the payload to
  `{ new_agent: { name, model, display_name, expansion, title }, notes:'' }`. Name-required check
  stays. Manual typing still supported (fields just stay unset → server defaults apply).

### 4.4 Approve path — `hiring_service._create_new_hire()`
- Accept optional `new_agent["expansion"]` and `["title"]`.
- When `display_name` is provided (generated flow), use it verbatim; when a generated **name** is
  present but no display_name, default `display_name = name` (dotted acronym) instead of
  "X Specialist".
- Persist `acronym = name`, `acronym_expansion = expansion` (if given), `title = title` (if given)
  onto the created agent row. Extend the `create_agent(...)` call / a follow-up UPDATE to write
  these columns. If the columns aren't already writable via `create_agent`, do a targeted
  `UPDATE agents SET acronym=%s, acronym_expansion=%s, title=%s WHERE id=%s` right after creation
  (same txn/cursor). No behavior change when expansion/title are absent (manual path).
- The existing all-states name-collision guard (L229-238) is unchanged and remains the final
  authority (belt-and-braces vs the generate-time check).

## 5. Prompt design (creative dispatch)

System prompt (sovereign, terse): *"You name AI agents for the A.R.C.H.I.E. platform. Every agent
name is a short real/pronounceable English word, 4–7 letters, written UPPERCASE and dot-separated
(e.g. F.O.R.G.E., V.I.G.I.L., M.A.V.E.N., C.O.D.E.X.). Each letter begins a word describing the
agent's role. Return STRICT JSON only."*

User prompt (filled): capability (human-readable), department, and the avoid-list; ask for
`{"name": "X.X.X.X.", "expansion": "Word Word …", "title": "<short human role>"}` where the
expansion has one word per letter and the acronym reads as a real word tied to the job. Include the
avoid-list explicitly: *"Do NOT use any of these existing names: …"*.

Keep the avoid-list bounded (e.g. current + decommissioned names is ~163 short strings — acceptable;
if it ever grows large, cap to a sample + rely on the server-side dedupe which is authoritative).

## 6. Validation, dedupe, fallback

### 6.1 Format validator (strict, hard requirement)
- Regex on the dotted form: `^[A-Z](\.[A-Z]){3,6}\.?$` (4–7 letters). Normalize first
  (strip stray spaces, ensure trailing dot canonical to match convention).
- Reject if letters < 4 or > 7, or non-alpha.

### 6.2 Uniqueness (strict, hard requirement)
- `_normalize(name)` (uppercase, remove dots) must not be in the normalized avoid-set. This catches
  `VERIFY` vs `V.E.R.I.F.Y.` equivalence.

### 6.3 Expansion/title (best-effort, NOT a rejection reason)
- Trust the creative model. Light sanity only: expansion is a non-empty string; title non-empty and
  short. Do **not** reject a well-formed unique name because the expansion's first letters don't
  perfectly line up (owner-approved leniency). If expansion missing → leave it null (approve path
  tolerates).

### 6.4 Retry + fallback
- On format-fail or duplicate → retry (≤ `max_attempts=3`), adding the rejected name to the avoid
  list sent to the model.
- Exhausted → `_fallback_name`: deterministic, guaranteed-unique. E.g. derive letters from the
  capability (first letters of its words, padded to ≥4 from a fixed themed suffix), dot-format,
  and if still colliding append a rotating vowel/consonant until unique. `source="fallback"`,
  expansion = capability words, title = `"<Capability> Specialist"`. The field is never left broken.

## 7. Data flow

```
[Generate click]
  → POST /tools/department-hq/api/approvals/hire/<id>/suggest-name
      → route reads hiring_candidates.capability, derives department
      → agent_name_generator.suggest_name(capability, department)
          → avoid = SELECT name FROM agents (all states) ∪ caller
          → dispatch_json(capability='creative', local_only=True)  [M.U.S.E., sovereign]
          → validate format + uniqueness → retry≤3 → fallback
      → {ok, name, expansion, title, source}
  → UI fills nameInput + hint, stashes into hireState.newAgent
  → [user optionally regenerates]
  → [Approve] POST .../hire/<id>/approve  { new_agent:{name,model,display_name,expansion,title} }
      → _create_new_hire: existing name guard → create_agent → persist acronym/expansion/title
        → add_skill(capability) → init_budget → log_creation_event → mark approved
```

## 8. Error handling

- Dispatch failure / queued / timeout → route returns `{ok:false}` (HTTP 200); button re-enables,
  small note; **manual approval unaffected**.
- All retries collide/malformed → deterministic fallback name (field never broken).
- Uniqueness enforced at BOTH generate-time (`agent_name_generator`) and approve-time (existing
  `_create_new_hire` guard). If a name is somehow taken between generate and approve, the approve
  guard rejects with the existing error and the UI surfaces it → user regenerates.
- All API-rendered text via `textContent` (XSS-safe).

## 9. Testing

- **Unit** (`platform_v2/tests/`): `agent_name_generator` with a **mocked dispatch** —
  - accepts `V.E.R.I.F.Y.`; rejects lowercase, 3-letter, 9-letter, non-alpha;
  - `_normalize` treats `V.E.R.I.F.Y.` == `VERIFY` for dedupe;
  - collision → retry consumes another dispatch result;
  - all-collide → `_fallback_name` returns unique, `source="fallback"`;
  - fallback uniqueness against a seeded avoid-set.
- **Live in-container tick** (the "status ≠ artifact" rule — KB #270002/#277249): after deploy,
  `POST suggest-name` for a **real** pending candidate in the running `archie_platform` container,
  confirm a unique well-formed `{name,expansion,title}`; then a **throwaway** end-to-end approve
  (create → verify dispatchable skill + budget + acronym columns persisted → clean up), exactly as
  PR #2289 validated the precheck. **The 6 real pending candidates stay untouched.**
- Browser check: open Approvals → net-new candidate → Generate fills field + hint; regenerate gives
  a different name; approve with a throwaway succeeds; 0 console errors.

## 10. Compliance / non-goals

- **Sovereign, DHQ-routed:** generation is `local_only=True` via `department_dispatcher` (ADR-013).
  No direct Ollama, no cloud.
- **Out of scope (YAGNI):** no model recommendation change (existing dropdown stays); no
  auto-generate-on-render; no DB UNIQUE constraint migration (app-level guard is the established
  pattern); no name generation for the *reactivation* path (names already exist there); no bulk
  regenerate. Curated word banks are explicitly not built.

## 11. Files touched

| File | Change |
|------|--------|
| `platform_v2/services/agent_name_generator.py` | **NEW** — generator service |
| `platform_v2/tools/department_hq/approvals_routes.py` | **NEW route** `suggest-name` |
| `platform_v2/services/hiring_service.py` | `_create_new_hire` persists expansion/title/acronym + display_name default |
| `platform_v2/tools/department_hq/templates/department_hq.html` | Generate button + hint + payload |
| `platform_v2/tests/test_agent_name_generator.py` | **NEW** — unit tests |

## 12. Deploy

Platform-core (volume-mounted): after merge to main, `docker restart archie_platform` picks up the
Python; the template is volume-mounted too. Verify with the live tick in §9. Per compliance rules,
ship on the feature branch → PR → F.O.R.G.E. review → merge (Tier-gated approvals require Kytran's
explicit OK before merge).
