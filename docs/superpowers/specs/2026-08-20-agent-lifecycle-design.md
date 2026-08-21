# Agent Lifecycle — Create, Profile, Decommission

**Date**: 2026-08-20
**Module**: Department HQ → Roster + shared agent profile modal
**Status**: design approved, implementation plan pending
**Sub-project**: C of 4 (A Roster table ✅ merged · B hire visibility ✅ merged · **C this** · ~~D portraits — CANCELLED, folded into C~~ · E identity & access)

---

## 1. Problem

There is no way to create an agent from the UI, no way to retire one, and no way to edit the
fields that make an agent work (system prompt, skills, model). The roster is read-plus-shift
only. Every agent that exists was created by a script, a migration, or the K.I.N. hire path.

## 2. Two kinds of agent — a presentation branch, not two systems

Measured live 2026-08-20 across 140 non-decommissioned agents:

| `worker_type` | n | has `acronym` | dotted name | has `gender` | has `system_prompt` | has `model` |
|---|---|---|---|---|---|---|
| `ai` | 116 | 108 | **116/116** | **0** | 116 | 116 |
| `internal` (human-like) | 23 | **0** | **0** | **22** | 23 | 23 |
| `contractor` | 1 | 0 | 0 | 0 | 1 | 1 |

**Both kinds are AI.** Every `internal` agent has a `system_prompt` and a `model`, exactly
like the `ai` ones. The difference is entirely how they present:

| | AI agent | Human-like agent |
|---|---|---|
| name | dotted acronym — `F.O.R.G.E.` | real first + last name |
| identity fields | `acronym`, `acronym_expansion` | `first_name`, `last_name`, `gender`, `ethnicity`, `age_range` |
| portrait style | sci-fi | corporate, with named ethnicity |
| purpose | platform/department work | assisting human-facing tasks (persona email drafting, LinkedIn personas) |

Human-like agents are the ones behind the 21 `COLLABORATOR` mailboxes and the persona email
assistant. This is why the create form branches on presentation **first** — it changes the
name fields, the portrait prompt style, and nothing else.

⚠️ Agent names are **dotted**. `ILIKE '%HAVEN%'` does not match `H.A.V.E.N.`; use
`replace(name,'.','')`. This has already caused a duplicate-name bug (#5272).

## 3. What already exists — do not rebuild

Verified by reading the code on 2026-08-20:

| exists | detail |
|---|---|
| `agent_service.create_agent(name, display_name, department, model, **kwargs)` | line 315 (was 244 before the A+B filter helpers were inserted above it). kwargs: `system_prompt, temperature, max_tokens, capabilities, is_department_ai, shift_state, tier, worker_type, allow_duplicate_name`. Carries the **#5272 name-collision guard at the single-writer choke point** — `allow_duplicate_name` defaults `False`. |
| `agent_service.update_agent(agent_id, **fields)` | line 362. Auto-derives `floor` from `department`. |
| `agent_service.propose_hire(...)` | line 763. K.I.N.'s gap-driven path. |
| async name generation | `POST /api/approvals/hire/<id>/generate-name` + `GET .../generate-name/<job_id>`, backed by `hire_name_jobs` + `services/hire_name_job_service.py` + `agent_identity_builder.build_identity`. |
| shared profile modal | `static/js/agent_profile_modal.js` (`apm-*`), already hosts the Curated Facts card. |

### 3.1 Two documentation corrections found while verifying

- **`agent_service.deactivate_agent()` DOES NOT EXIST.** `CLAUDE.md` lists it as part of the
  agent lifecycle. There is no `deactivate`/`decommission`/`retire` function anywhere in
  `agent_service.py` or `tools/department_hq/*.py`. **Decommission in this spec is new
  code, not reuse.** CLAUDE.md needs correcting.
- **#4969 part 2 is already done.** The capability index says the frontend "STILL USES" the
  legacy synchronous `suggest-name`; it does not — `department_hq.html:1933` calls the async
  `generate-name`. The sync endpoint still exists at `approvals_routes.py:747` but is not the
  live path. The index is stale.

## 4. Create — one surface, two entry points

1. `[+ New Agent]` in the Roster.
2. Approving a pending `hiring_candidates` row (sub-project B surfaces these) opens the
   **same** modal, pre-filled from its `capability`, `narrative` and `shortlist`.

Both converge on one create surface so there is one validation path and one set of side
effects, not two that drift.

### 4.1 Fields

**Step 1 — presents as**: `AI` or `Human-like`. Drives the name fields, the portrait style,
and `worker_type` (`ai` / `internal`).

**Step 2 — identity**
- AI: `name` (dotted), `acronym`, `acronym_expansion`, `display_name`
- Human-like: `first_name`, `last_name`, `gender`, `ethnicity`, `age_range`, `display_name`
- Name assist: reuse the existing **async** `generate-name` job pattern (§3). Never call a
  synchronous identity builder from a request handler — it spins 6–23s and up to ~60s
  (`MAX_ATTEMPTS=3` × a 20s per-attempt bound), holding a gunicorn worker.

**Step 3 — placement & behaviour**: `department` (derives `floor`), `title`, `model`,
`system_prompt`, `bio`, `is_department_ai`.

**Step 4 — skills** (see §4.2).

**Step 5 — side effects** (see §4.3).

### 4.2 At least one skill is REQUIRED

Dispatch selects agents by matching `agent_skills.skill_name` against the dispatched
capability. An agent with zero skills is **structurally undispatchable** — it appears in the
roster looking healthy, is counted in headcount, and never receives work. Worse, the
scoring path applies a hard penalty when a capability is present and not in the agent's
skills, so it loses even inside its own department.

The form therefore requires ≥1 skill with a proficiency level, offering capabilities from
`CAPABILITY_DEPARTMENT_MAP` and warning when a chosen skill's home department differs from
the agent's department (legal, but it means cross-department routing).

### 4.3 Side effects — defaulted ON, individually visible

Owner decision 2026-08-20: all four are automatic. Budget, mailbox and portrait render as
checkboxes, pre-ticked — a create is one click, but each consequence stays an observable
decision rather than a silent cascade. **Skills are not a checkbox**: they are a required
input (§4.2) and cannot be unticked.

| side effect | what it writes | notes |
|---|---|---|
| `agent_skills` rows | required, ≥1 | not optional — §4.2 |
| `agent_budgets` row | default `token_limit_per_day` | without it, welfare gating and K.I.N. over-budget checks have nothing to read |
| Stalwart mailbox | real external state | ~79 mailboxes exist across ~140 agents, so this is **not** universal today; removal is manual |
| portrait | queued job | §4.4 |

Each side effect reports its own outcome. A create where the agent row succeeded and the
mailbox failed must say exactly that — never a bare "Agent created".

### 4.4 Portrait generation

Queued through `media_generation_queue`, never dispatched synchronously (ADR-005: all image
generation goes through the worker queue; a sync call blocks the web thread for minutes).

⚠️ **ComfyUI parks itself.** `comfyui_service.stop_if_idle()` stops the hub container to free
VRAM for Ollama; `state=exited` with `exit 137` is its **correct resting state**, not a
crash. The create path must call `wake_if_stopped()` and tolerate a cold start. Portrait
failure must never fail the agent creation — the agent exists, the portrait is retryable.

Style follows §2: sci-fi for AI, corporate with named ethnicity for human-like.

## 5. Profile editing

Extends the **shared** `static/js/agent_profile_modal.js`.

⚠️ **Not `department-hq.js`'s `openAgentDetail`** — that function is dead code, shadowed at
load by `agent_profile_modal.js`'s `window.openAgentDetail =`. UI added there renders
nowhere. This exact trap cost a live-drive bug in #4959 (KB mistake #281727).

Editable: `title`, `bio`, `system_prompt`, `model`, `department`, skills (add/remove/level),
and the identity fields for the agent's kind. All writes go through
`agent_service.update_agent()` — no direct SQL on agent tables.

**AMENDED 2026-08-21 — this is WIRING, not new endpoints.** The backend already exists
(§7.2): `PATCH /api/agent/<id>` for fields and `POST /api/agent/<id>/skills` for skills.
This section's work is the modal UI calling them. Do NOT add parallel endpoints.

**Portrait regeneration lands here too** (formerly sub-project D, now folded in — §8).
`POST /api/agents/<id>/generate-portrait` already exists and already queues via
`portrait_service.generate_canonical`, returning a `queue_id`. The work is a
"Regenerate portrait" button on the profile that calls it and surfaces the queued state.
Style follows §2: sci-fi for AI agents, corporate for human-like.

⚠️ Queue depth is not completion. The button must show "queued", not "done" — a portrait
job can sit behind a ComfyUI cold start, and ComfyUI parks itself (`exited`) to free VRAM,
which is its correct resting state (§4.4).

## 6. Decommission — never DELETE

**New code** (§3.1 — no existing function).

- Sets `shift_state='decommissioned'`; the agent leaves the roster listing (which already
  filters that state) and is retained for history.
- **Never `DELETE`.** Agents are referenced by `node_agents`, `email_mailboxes`,
  `task_execution_log`, `work_notes`, `agent_skills`, `agent_budgets`. A hard delete either
  fails on FK constraints or shreds history. 84 agents are already decommissioned this way.
- Releases `node_agents` assignments.

### 6.1 Refuse or warn — dispatch safety

Before decommissioning, check and surface:

- **Sole holder of a skill** — if no other active agent has that `skill_name`, decommissioning
  creates a capability dead-end: dispatches for it will find no candidate. **Warn loudly and
  name the skills.**
- **Department director** (`is_department_ai=true`) — warn; the department loses its default
  routing target.

These mirror the gap logic K.I.N. already uses to *propose* hires; here they prevent silently
manufacturing the gap.

## 7. API surface

> **AMENDED 2026-08-21, before implementation.** The original table proposed five
> endpoints. A pre-planning audit of `tools/department_hq/agent_detail_routes.py` found
> that **three of them already exist**, and the existing implementations are better than
> what this spec described. Building the original table would have stood up a SECOND
> parallel agent-CRUD surface — the same duplication class as the Roster's hand-built
> COUNT and the per-caller merge gate. Only the genuinely-missing endpoints are new.

### 7.1 NEW — these do not exist

| endpoint | purpose |
|---|---|
| `POST /api/roster/agent` | create; returns agent id + per-side-effect results |
| `GET /api/agent/<id>/decommission-precheck` | the §6.1 warnings, without acting |
| `POST /api/agent/<id>/decommission` | decommission; refuses/warns per §6.1 |

All `@admin_required`. All mutations through `agent_service`.

### 7.2 ALREADY EXISTS — CALL IT, DO NOT REBUILD IT

| existing endpoint | what it already does |
|---|---|
| `PATCH /api/agent/<id>` | field update via `agent_service.update_agent`, validates unknown fields, captures a before-state, **and writes `governance_audit_log`** |
| `GET`/`POST /api/agent/<id>/skills` | list / add-or-update a skill, with 1–5 level validation |
| `POST /api/agents/<id>/generate-portrait` | calls `portrait_service.generate_canonical`, returns a `queue_id` — already QUEUED, not sync |
| `GET /api/agent/<id>/profile` · `/welfare` · `/facts` · `POST /shift` · `/department` | profile read, welfare, curated facts, shift + department changes |

⚠️ The audit-logging in `PATCH /api/agent/<id>` is a REASON to reuse it, not an
incidental. A second update path would silently skip the governance trail.

### 7.3 How create composes them — SERVER-SIDE

`POST /api/roster/agent` performs its side effects by calling the SAME service functions
those existing routes call, **in the request handler** — not by having the browser fire a
sequence of follow-up requests after the agent row exists.

Rationale: a browser-driven sequence fails partially and invisibly (three of five calls
land, the user sees one toast), and there is no single place to report the outcome. A
server-side composition has one place to catch each failure and one response carrying
per-side-effect results (§4.3). This mirrors the decision already made for
`POST /api/roster/bulk-shift`, which loops server-side for exactly this reason.

Import the service functions; do not issue internal HTTP calls to our own routes.

## 8. Out of scope

- **Platform login / RBAC for agents** — sub-project E. Note `users.agent_department` exists
  and 21 users are already `role=COLLABORATOR`, but there is **no `users.agent_id`**, so the
  agent↔user link is loose today. E decides whether agents log in at all.
- **KBS / CRM access** — KBS is a separate repo, separate Postgres (`kbs_postgres`, user
  `kbs`), separate auth, multi-tenant by schema. There is **no CRM module in
  `module_registry.py`**. Cross-product access is E, and is materially harder than platform
  RBAC.
- ~~Portrait *iteration* UI — sub-project D. C only queues the first one.~~
  **AMENDED 2026-08-21: sub-project D is CANCELLED and folded into C (§5).** D was scoped
  on the assumption that portrait generation needed building. It does not:
  `POST /api/agents/<id>/generate-portrait` exists and already queues through
  `portrait_service.generate_canonical`. What remained of D was a button, so it belongs in
  C's profile surface rather than in a sub-project of its own.
- Bulk create. One agent at a time, deliberately.
- **Bulk portrait generation** — `generateAllMissingPortraits()` already exists and was
  re-wired to a Roster control-bar button during the A+B work. C does not touch it.

## 9. Testing

**Unit**
- Create rejects a duplicate name including the dotted/undotted equivalence (#5272).
- Create with zero skills is rejected (§4.2).
- Each side-effect failure is reported individually and does not roll back the agent row.
- Decommission precheck detects a sole-skill-holder and a department director.
- Decommission never issues a `DELETE`.
- Human-like create writes `worker_type='internal'`, no acronym; AI create writes a dotted
  name + acronym. Pin the §2 convention so it cannot silently invert.

Per `repair-bay.md`: prove each new test fails against the unfixed code first, using a
**copy** of the module (`importlib`), never by mutating the live file.

**Live browser drive — required.** Create one AI agent and one human-like agent end to end,
confirm each appears in the roster with the right identity fields, confirm the portrait job
is queued (not run inline), then decommission both and confirm they leave the listing and the
warnings fired. Per KB #292215 a green suite has proved nothing for DHQ UI three times.

## 10. Risks

| risk | mitigation |
|---|---|
| Agent created with no skills → invisible dead weight | ≥1 skill required (§4.2) |
| Sole-skill decommission → silent capability dead-end | precheck warns and names the skills (§6.1) |
| Partial create reads as full success | per-side-effect results (§4.3) |
| Sync identity generation holds a worker up to 60s | reuse the async job pattern (§4.1) |
| Portrait failure blocks agent creation | portrait is queued and non-fatal (§4.4) |
| ComfyUI `exited` misread as a crash | it is the correct resting state; `wake_if_stopped` (§4.4) |
| Profile UI added to the dead `openAgentDetail` | shared modal only (§5) |
| Hard delete shreds history / FK-fails | decommission only (§6) |

## 11. Open questions

None for C. E's opening question — whether agents authenticate at all, or hold scoped access
a human exercises on their behalf — is deliberately deferred, not assumed.
