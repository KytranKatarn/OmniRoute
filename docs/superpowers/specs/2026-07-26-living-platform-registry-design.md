# Living Platform Registry — generated, not hand-typed

**Status:** design · **Owner ask:** 2026-07-26 · **Project:** #343 (Master Vision)
**Related:** ADR-012 (#958) · KB #258559 (database-centric docs) · KB #277474 (capability-index debt)
· KB #258466 (index must be updated on surface change) · KB #284817 (measurement lesson)

## The problem, stated precisely

Kytran: *"I wanted an indexed module document ... that keeps track of the features, updates, skills,
services that we keep updated that will help us for the future. Consciousness [is] supposed to have
some sort of documentation."*

Consciousness **does** own documentation, and most of it is already automated:

| Surface | Maintained how | Drifts? |
|---|---|---|
| `knowledge_base` (38.8k entries, 98.9% embedded) | live, agent-written | no |
| `learned-skills.md` | **generated** by a Consciousness job (6h) | no |
| project docs | `auto_doc_service.generate_project_docs` (cooldown-gated) | no |
| event docs | `codex_event_docs_service` (30 min) | no |
| ADRs | `project_decisions` via `log_decision` | no |
| **`module-capability-index.md`** | **hand-typed, 314 lines, NO generator** | **yes** |
| **`CLAUDE.md`** | hand-typed; untouched since 2026-06-01 | **yes** |
| **`operational-state.md`** | hand-typed | **yes** |

So the failure is not "we have no documentation system." It is that the three files a new session
reads FIRST are the only ones nobody generates. Every drift incident this month traces to that:
capability-index drift (last session's first action item), `auth_events` documented as existing when
it does not (#5174), `backups`/`backup_locks` phantom tables that left backups unmonitored while
appearing monitored, `media_studio`/`game_studio`/`media_hub` listed as Codex-writable when they never
were (a real safety widening).

**A hand-maintained index does not merely go stale — it asserts things that are false, and agents act
on those assertions.** That is the same failure family as KB #284817: a check that passes against
something adjacent to the truth.

## Principle

> Anything an agent reads to make a decision must be **derived from a live source**, or must **declare
> its own staleness**. Prose that cannot be verified against the system it describes is a liability,
> not documentation.

## Design

### 1. Registry tables (source of truth, DB — per KB #258559)

Migration adds `platform_registry_*`:

- `platform_registry_module` — one row per module. Derived from `module_registry.py` +
  `rbac.py`: `module_key, route, blueprint, category, status, maturity, owner_department,
  chat_agent_id, template_path, static_prefix, last_seen_at, source_sha`.
- `platform_registry_service` — deployed services: `name, host, port, container, subdomain,
  front_door, compose_path, version_endpoint, baked_sha, expected_sha, drift_status`.
  Reuses `scripts/deploy_drift_check.py:check_products()` — already the SSOT for provenance.
- `platform_registry_job` — scheduled work: `job_id, schedule, timezone, module, capability,
  enabled, last_run_at, last_status`. Derived from the APScheduler registry + `work_control_service`.
- `platform_registry_skill` — `name, kind (claude_skill|mcp_tool|agent_capability|shell_script),
  path, invocable_as, tested_at, test_status`. Derived from `.claude/skills/**/SKILL.md`,
  `.claude/commands/*.md`, the MCP tool registry, and `CAPABILITY_DEPARTMENT_MAP`.
- `platform_registry_change` — append-only feed: `(kind, key, field, old, new, source, changed_at,
  pr_number)`. **This is the "updates" half of the ask** — the thing that answers "what changed
  since I last looked."

### 2. Collectors (read live state, never prose)

`services/platform_registry_service.py` — one `collect_*()` per table, each returning rows from a
*live* source (import `module_registry`, query the scheduler, walk the skills dirs, call
`check_products()`). `reconcile()` diffs collected vs stored, writes `platform_registry_change` rows,
and **never deletes** — a vanished row gets `last_seen_at` frozen + `status='absent'`, because a
disappearance is the most interesting event and must not be silently dropped.

### 3. Generated views (what agents actually read)

`scripts/generate_registry_docs.py` renders from the DB:
- `.claude/rules/module-capability-index.md` — **generated**, with a
  `<!-- GENERATED … do not hand-edit -->` header and a `generated_at` stamp.
- A "What changed" digest (last 7/30 days) from `platform_registry_change`.
- Hand-written *rationale* stays, but moves into per-module `notes` columns so it survives
  regeneration. Prose and derived facts must not live in the same unmanaged blob.

### 4. Drift gate (the part that makes it stick)

- Pre-commit / CI check: if a PR touches `module_registry.py`, `rbac.py`, a `tools/<m>/` blueprint,
  a compose file, or a skills dir, and the registry was not regenerated → **fail with the diff**.
  This is the mechanism `learned-skills.md` already effectively has and the capability index lacks.
- Nightly `platform_registry_reconcile` job: alerts on any row whose `last_seen_at` is older than
  its collector's run (i.e. documented-but-absent) — the phantom-table class of bug (`auth_events`,
  `backups`, `backup_locks`) becomes a **red alert instead of a silent lie**.
- Every generated file carries `generated_at`; a reader older than N days is reported, so a stale
  index announces itself rather than being trusted.

### 5. Mistake loop (the "learn from mistakes" half)

`platform_registry_change` rows link to `project_decisions` and to `knowledge_base`
`mistake_learned` entries by `pr_number`. A mistake filed against a module surfaces **on that
module's registry entry**, so the next agent reading the index sees "this module has 3 recorded
mistakes" before touching it — instead of relying on remembering to search.

## Phasing

1. **Migration + `platform_registry_module` + collector + generated index.** Highest value: it kills
   the file that drifts most, and proves the loop end-to-end.
2. `platform_registry_service` (reuse `check_products()`) + `platform_registry_job`.
3. `platform_registry_skill` + the drift gate in pre-commit.
4. `platform_registry_change` digest + mistake linkage + the reconcile alert job.

Ship 1 alone and the recurring "the index says X but the code says Y" class is already closed.

## Explicit non-goals

- Not a new UI. It surfaces in Consciousness (which owns KB/docs) and as generated markdown.
- Not a replacement for the KB, ADRs, or Dev HQ tasks — it **indexes** them.
- Not another hand-written summary. If a field cannot be derived or explicitly curated in a `notes`
  column, it does not belong here.
