# DHQ Hiring Queue — Design

**Project**: #261 LLM Resource Management
**Task**: #2102 Department HQ UI — Hire candidate review + approval workflow (no auto-hire)
**Date**: 2026-04-19
**Status**: draft — awaiting user review
**Branch**: `feat/dhq-hiring-queue-spec`

## Background

`check_understaffed_capabilities()` (in `platform_v2/services/agent_jobs.py`, job id `agent_understaffed_digest`) runs daily at 09:00 UTC and emits capability gaps to `autonomy_loop_log` with `details={"understaffed_capabilities": gaps, ...}`. Today the output just sits there — no automated response, no proposal surfaced to Kytran.

Task #2102 requires that K.I.N. (Human Resources & Culture director) **propose** candidates to fill these gaps rather than auto-hire. Candidates come from two sources: reactivation of decommissioned agents with matching skills, or new acronym-agent creation. Kytran is the only approver. The queue lives in Department HQ, not Telegram, because the shortlist UI needs a proper card layout.

## Scope

This spec covers the **first two phases** of the full #2102 vision:

| Phase | In this spec? | Scope |
|---|---|---|
| **A — Schema + UI shell** | ✅ | New `hiring_candidates` table, new `hire:` source in the unified approvals UI, Approve/Reject endpoints wired to `agent_service.transition_shift_state` with a model-availability pre-check |
| **B — K.I.N. reactivation proposals** | ✅ | New `kin_generate_hire_proposals` job that runs after `agent_understaffed_digest`, deterministic SQL shortlist of 3 decommissioned candidates per gap, short LLM-generated narrative per proposal |
| C — New-acronym-agent proposals | ❌ deferred | LLM-generated name/department/skill/budget spec for genuinely missing capability. Bigger surface. |
| D — Ask-for-alternative button | ❌ deferred | On-demand regeneration when all 3 shortlisted candidates are unsuitable |

Test the shape of the flow by reactivating a real decommissioned translate-capable agent (Oracle, Wordsmith, Scout, or Spark-Jr are candidates in the current DB) before investing in C/D.

## Non-goals

- Automatic hiring (explicit rule: Kytran-only approval).
- Generation of new acronym agents from scratch (Phase C).
- Multi-candidate comparison UI beyond a simple radio-buttoned shortlist.
- Hiring proposals for contractors (separate pipeline in `contractor_approval_requests`).
- Capability→department mapping changes (use what the SQL already infers).
- Reactivating an agent whose primary model is unavailable AND auto-pulling the model (Phase 1 surfaces the error; pulling is a manual follow-up).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Daily 09:00 UTC — agent_understaffed_digest                 │
│  (existing; writes gaps to autonomy_loop_log.details)       │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ NEW: kin_generate_hire_proposals (~09:05 UTC)               │
│  For each gap in the most recent understaffed_digest row:   │
│   1. SQL shortlist — top 3 decommissioned agents with the   │
│      skill, proficiency ≥ 3, sorted by proficiency DESC,    │
│      then decommissioned_at DESC.                           │
│   2. Bridge dispatch (K.I.N., capability="workforce_        │
│      planning") → short "why this gap + why these 3"        │
│      narrative. Failure → narrative=NULL; proposal still    │
│      ships.                                                 │
│   3. INSERT into hiring_candidates (status='pending').      │
│   4. Dedup: skip if pending row already exists for the      │
│      same capability.                                       │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Unified GET /api/approvals/pending (extended)               │
│  Adds "hire:N" rows to the existing UNION across            │
│  autonomy_approval_queue / contractor_approval_requests /   │
│  bridge_jobs.pending_approval.                              │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ DHQ Approvals tab — new source pill "hire:"                 │
│  Card renders gap description, LLM narrative, and an        │
│  expandable radio-buttoned shortlist of the 3 candidates.   │
│  Buttons: [Approve with selected] / [Reject]                │
└──────────────┬──────────────────────────────────────────────┘
               │ Approve
               ▼
┌─────────────────────────────────────────────────────────────┐
│ POST /api/approvals/hire/<id>/approve                       │
│   {"chosen_agent_id": N, "notes": "..."}                    │
│                                                              │
│  1. Pre-check: GET /api/tags on hub → verify agent's        │
│     primary model is present. If missing: 409, row stays    │
│     pending, precheck_status + precheck_message persisted.  │
│  2. agent_service.transition_shift_state(chosen_agent_id,   │
│     'active', 'hired_via_queue').                           │
│  3. hiring_candidates: status='approved', chosen_agent_id,  │
│     decided_by_user_id, decided_at.                         │
│  4. governance_audit_log row (event_category=               │
│     'agent_lifecycle', action='hire_reactivation_           │
│     approved').                                             │
│  5. Return 200 with the new agent shift_state.              │
└─────────────────────────────────────────────────────────────┘
```

### Module layout

Three logical units, each testable independently:

1. **`platform_v2/services/hiring_service.py`** (new) — pure business logic. `get_shortlist(capability, limit=3)`, `propose_for_gap(gap_alert_id, capability, gap_reason)`, `approve_candidate(hire_id, chosen_agent_id, decided_by_user_id, notes)`, `reject_candidate(hire_id, decided_by_user_id, notes)`, `expire_stale_proposals(max_age_days=14)`.
2. **`platform_v2/tools/department_hq/approvals_routes.py`** (modify) — extend the existing unified endpoint with a `hire:` source + add `/api/approvals/hire/<id>/approve|reject` handlers.
3. **`platform_v2/services/agent_jobs.py`** (modify) — register the `kin_generate_hire_proposals` and `expire_stale_hire_proposals` jobs in the scheduler.

The K.I.N. narrative step calls the dispatcher through `build_options()` → `select_node()` (shipped in PR #195), so it inherits GPU-placement awareness automatically.

## Data model

### New table: `hiring_candidates`

```sql
CREATE TABLE hiring_candidates (
    id                   SERIAL PRIMARY KEY,

    -- Gap context
    capability           VARCHAR(100) NOT NULL,
    gap_reason           TEXT NOT NULL,
    gap_alert_id         INTEGER,                    -- optional FK-ish to autonomy_loop_log.id
    narrative            TEXT,                       -- K.I.N. LLM text; may be NULL on failure

    -- Shortlist — JSONB array of 3 candidate objects
    shortlist            JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Proposer
    proposed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    proposed_by_agent_id INTEGER,                    -- K.I.N.'s agents.id

    -- Decision
    status               VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','approved','rejected','expired')),
    chosen_agent_id      INTEGER,                    -- set on approve
    decided_by_user_id   INTEGER,
    decided_at           TIMESTAMPTZ,
    decision_notes       TEXT,

    -- Approve-time pre-check outcome
    precheck_status      VARCHAR(20),                -- 'ok'|'model_missing'|'ollama_unreachable'
    precheck_message     TEXT
);

CREATE INDEX idx_hiring_candidates_status ON hiring_candidates(status);
CREATE INDEX idx_hiring_candidates_cap_pending
    ON hiring_candidates(capability) WHERE status = 'pending';
CREATE INDEX idx_hiring_candidates_proposed_at ON hiring_candidates(proposed_at DESC);
```

Migration: `database/migrations/NNN_hiring_candidates.sql` (sequential number at implementation time).

### `shortlist` JSONB shape

Each entry:
```json
{
  "agent_id": 42,
  "display_name": "Olivia Oduya (Oracle)",
  "proficiency_level": 4,
  "department": "Medical & Wellness",
  "decommissioned_at": "2026-01-15T12:00:00Z",
  "primary_model": "mistral:7b"
}
```

`primary_model` is hydrated from wherever the agent row actually stores model assignment (the DB exploration found the column name is NOT `primary_model`; implementation confirms the correct column during schema read).

### Dedup rule

Before INSERT in `kin_generate_hire_proposals`:
```sql
SELECT 1 FROM hiring_candidates
 WHERE capability = %s AND status = 'pending'
 LIMIT 1
```
If a pending row exists, skip. Rejected/approved/expired rows never block re-proposal.

### Expiry

New sibling job `expire_stale_hire_proposals` runs daily 04:30 UTC. Sets `status='expired'` on any `pending` row with `proposed_at < now() - interval '14 days'`. Expired rows stay for history; they're filtered out of the unified endpoint.

## Unified endpoint extension

Existing endpoint (per PR #182): `GET /api/approvals/pending` UNIONs rows from `autonomy_approval_queue`, `contractor_approval_requests`, and `bridge_jobs.status='pending_approval'`. Source-prefixed IDs: `autonomy:N`, `contractor:N`, `bridge:N`.

Add a fourth source:

```python
# Pseudo — implementation will match the existing UNION's shape
SELECT
    id                          AS id,
    'hire'                      AS source,
    'hiring'                    AS category,
    capability                  AS display_name,
    COALESCE(narrative, gap_reason) AS reason,
    (SELECT display_name FROM agents WHERE id = proposed_by_agent_id) AS agent_name,
    proposed_at                 AS created_at,
    jsonb_build_object(
        'shortlist',    shortlist,
        'gap_reason',   gap_reason,
        'narrative',    narrative
    )                           AS payload
FROM hiring_candidates
WHERE status = 'pending'
```

Payload carries the shortlist JSONB so the frontend renders the radio picker without a second round-trip.

Response row for a hire proposal:
```json
{
  "id": "hire:17",
  "source": "hire",
  "category": "hiring",
  "display_name": "translate",
  "reason": "Translate capability concentrated on 2 agents (C.O.D.E.X., R.O.S.E.T.T.A.) — single-department failure risk.",
  "agent_name": "K.I.N.",
  "created_at": "2026-04-19T09:05:12Z",
  "payload": {
    "shortlist": [ ... ],
    "gap_reason": "only 2 active agents with translate@5",
    "narrative": "Two of three active translate holders are in Documentation & Knowledge..."
  }
}
```

## Approve / reject endpoints

Both `@admin_required` (Kytran-only per task requirement).

```
POST /api/approvals/hire/<int:hire_id>/approve
  body: {"chosen_agent_id": <int>, "notes": "<optional str>"}

POST /api/approvals/hire/<int:hire_id>/reject
  body: {"notes": "<optional str>"}
```

### Approve flow

1. Load `hiring_candidates` row. 404 if not found. 409 if `status != 'pending'`.
2. Validate `chosen_agent_id` appears in the row's `shortlist` JSONB. 400 if not.
3. Look up the chosen agent's primary_model. If agent row is missing or shift_state isn't `decommissioned`, 409.
4. Pre-check: `GET /api/tags` on hub; extract model stems. If chosen agent's model stem isn't present, persist `precheck_status='model_missing'`, `precheck_message='Model <name> not on hub'`, return 409 WITHOUT transitioning. Row stays `pending` so Kytran can fix and retry.
5. `agent_service.transition_shift_state(chosen_agent_id, 'active', 'hired_via_queue')`.
6. UPDATE hiring_candidates SET status='approved', chosen_agent_id, decided_by_user_id, decided_at=now(), decision_notes, precheck_status='ok' WHERE id=%s AND status='pending'. If affected rows = 0 (someone else beat us), 409.
7. INSERT governance_audit_log row with `event_category='agent_lifecycle'`, `action='hire_reactivation_approved'`, actor user id, subject agent id.
8. Return 200 with `{"status":"approved", "agent": {...}}`.

### Reject flow

1. 404 / 409 checks as above.
2. UPDATE hiring_candidates SET status='rejected', decided_by_user_id, decided_at=now(), decision_notes WHERE id=%s AND status='pending'.
3. Governance log `action='hire_reactivation_rejected'`.
4. 200.

## K.I.N. proposal generation (`kin_generate_hire_proposals`)

Scheduler registration mirrors `agent_understaffed_digest` but runs slightly after:

```python
scheduler.add_job(
    with_ctx(kin_generate_hire_proposals),
    trigger=CronTrigger(hour=9, minute=5, timezone="UTC"),
    id="kin_generate_hire_proposals",
    replace_existing=True,
    max_instances=1,
)
```

Flow:

```python
def kin_generate_hire_proposals():
    gaps = _load_latest_understaffed_digest()  # reads most recent autonomy_loop_log row
    inserted = 0
    for gap in gaps:
        if _pending_proposal_exists(gap["capability"]):
            continue
        shortlist = hiring_service.get_shortlist(gap["capability"], limit=3)
        if not shortlist:
            continue
        narrative = _generate_narrative(gap, shortlist)  # bridge dispatch, best-effort
        hiring_service.propose_for_gap(
            capability=gap["capability"],
            gap_reason=gap["reason"],
            gap_alert_id=gap.get("alert_id"),
            shortlist=shortlist,
            narrative=narrative,
            proposed_by_agent_id=_get_kin_agent_id(),
        )
        inserted += 1
    _log_cycle("kin_generate_hire_proposals", inserted, 0, ...)
```

`_generate_narrative` uses `dispatch(capability="workforce_planning", agent="K.I.N.", ...)` with a prompt that includes the gap reason, department distribution of active holders, and the shortlist. Falls back to `None` on any exception — proposal still ships.

### Shortlist SQL

```sql
SELECT
    a.id                          AS agent_id,
    a.display_name                AS display_name,
    s.proficiency_level           AS proficiency_level,
    a.department                  AS department,
    a.decommissioned_at           AS decommissioned_at,
    a.<model_col>                 AS primary_model
FROM agents a
JOIN agent_skills s ON s.agent_id = a.id AND s.skill_name = %s
WHERE a.shift_state = 'decommissioned'
  AND s.proficiency_level >= 3
ORDER BY s.proficiency_level DESC, a.decommissioned_at DESC NULLS LAST
LIMIT 3;
```

The `<model_col>` identifier is resolved at implementation time — the exploration hit an error assuming `primary_model`, which isn't the actual column. Implementation starts with `\d agents` to confirm.

## Error handling

| Failure | Behavior | User impact |
|---|---|---|
| No matches for a gap's capability | Insert nothing for that gap, log INFO | Nothing appears in queue — correct |
| Bridge/K.I.N. dispatch for narrative fails | `narrative=NULL`; proposal ships | Card shows gap_reason only, no loss of function |
| Dedup hit (pending proposal already exists) | Skip silently, log INFO | No duplicate proposals in queue |
| K.I.N.'s `agents` row absent | `proposed_by_agent_id=NULL` | `agent_name` comes back as NULL in the unified endpoint — harmless |
| Pre-check: `/api/tags` unreachable | Persist `precheck_status='ollama_unreachable'`, 409, row stays pending | Toast: "Ollama unreachable, try again" |
| Pre-check: model not present | Persist `precheck_status='model_missing'`, 409, row stays pending | Toast: "Model X not on hub. Pull it first then retry." |
| `transition_shift_state` raises | 500, status stays pending | Kytran retries |
| Approve on non-pending row | 409 "already decided" | Frontend refresh |
| `chosen_agent_id` not in shortlist JSONB | 400 "invalid candidate" | Frontend refresh |
| Race — two admins approve simultaneously | UPDATE WHERE status='pending' affects 0 rows → second caller gets 409 | Last-writer-wins prevented |
| Expiry job crashes | Next daily run picks up the backlog | Queue gets a few extra stale rows |

### Observability

- `_log_cycle("kin_generate_hire_proposals", inserted, errors, duration_ms, details={"gaps_seen": N, "shortlists_empty": N})` — writes to `autonomy_loop_log`
- `governance_audit_log` row per approve / reject — permanent audit trail
- No new observer/metrics in Phase 1; if proposals start auto-expiring frequently that's itself a signal (Kytran isn't reviewing), which can be surfaced in a later phase

## Testing

### Unit — `platform_v2/tests/test_hiring_service.py`

- `test_shortlist_returns_top_3_decommissioned_by_proficiency`
- `test_shortlist_excludes_active_agents`
- `test_shortlist_excludes_proficiency_below_3`
- `test_shortlist_tiebreaks_on_decommissioned_at_desc`
- `test_shortlist_returns_fewer_than_3_when_pool_is_small`
- `test_propose_for_gap_dedups_on_pending_capability`
- `test_propose_for_gap_empty_shortlist_inserts_nothing`
- `test_propose_for_gap_narrative_null_on_bridge_failure`
- `test_approve_candidate_happy_path_transitions_shift_state`
- `test_approve_candidate_blocks_on_missing_model_precheck`
- `test_approve_candidate_blocks_on_ollama_unreachable_precheck`
- `test_approve_candidate_rejects_chosen_agent_not_in_shortlist`
- `test_approve_candidate_rejects_already_decided_row`
- `test_approve_candidate_rejects_when_target_agent_not_decommissioned`
- `test_reject_candidate_writes_notes_and_decided_by`
- `test_expire_stale_flips_rows_older_than_14d`

### Route — `platform_v2/tests/test_approvals_hire_routes.py`

- `test_pending_endpoint_unions_hire_rows_with_payload_shortlist`
- `test_post_approve_hire_calls_service_and_returns_200`
- `test_post_approve_hire_returns_409_on_precheck_failure`
- `test_post_approve_hire_requires_admin`
- `test_post_reject_hire_requires_admin`
- `test_post_reject_hire_writes_governance_audit_log_row`

### Migration

- `tests/test_hiring_candidates_migration.py` — apply the SQL to a scratch DB, verify the CHECK constraint rejects bad status values, verify the partial index exists.

### Integration / manual smoke (per PR)

- Seed a gap row (SQL) + verify the job generates a proposal (via direct call or a dev-only `/api/hiring/run` endpoint).
- Approve through the UI and watch `agents.shift_state` flip + dispatcher immediately considers the reactivated agent (verified via `get_agent_cache`).
- Reactivate a real decommissioned agent (Oracle, Wordsmith, Scout, or Spark-Jr) against a live hub.

### Out of scope

No load tests (≤20 gaps/day is trivial), no frontend unit tests beyond Jest smoke on the shortlist picker card, no chaos tests.

## Delivery plan

Two PRs on this branch family:

### PR 1 — Schema + service + job + endpoints
- Migration `NNN_hiring_candidates.sql`
- `services/hiring_service.py` with shortlist / propose / approve / reject / expire functions
- `services/agent_jobs.py`: register `kin_generate_hire_proposals` + `expire_stale_hire_proposals`
- `approvals_routes.py`: extend unified endpoint + approve/reject handlers
- Unit + route tests (no UI yet)

### PR 2 — DHQ Approvals tab UI for the `hire:` source
- New source pill rendering in the existing Approvals tab template
- Expandable card with shortlist radio picker + Approve/Reject buttons
- Minimal client JS for the radio + POST flow
- Jest smoke test on the card component

## Open questions (resolved during implementation)

1. **Exact `primary_model` column name** in `agents` table — resolve via `\d agents` during PR 1 (the DB exploration hit an error on this name).
2. **Capability → skill_name mapping** — is it 1:1 or does the `check_understaffed_capabilities` output use different vocabulary than `agent_skills.skill_name`? If different, add a mapping table or alignment step in PR 1.
3. **`decommissioned_at` column** — does it exist on `agents`, or must be inferred from audit log? If missing, use `updated_at` as a fallback tiebreak and file a follow-up to add the column.
4. **K.I.N. agent row** — confirmed exists in DB (HR director); verify `proposed_by_agent_id` is the correct foreign key during PR 1.

None are scope-changing; all resolvable by reading existing code/schema during implementation.

## Decisions logged (via `mcp log_decision` after approval)

- Scope: Phase A + B ship in this spec. Phases C (new-acronym generation) and D (ask-for-alternative) deferred.
- Data model: new `hiring_candidates` table + UNION into the unified approvals endpoint.
- Shortlist: one proposal per gap with embedded 3-candidate shortlist (not N proposals).
- Approve pre-check: model availability via `/api/tags`, fail-fast with persisted `precheck_status`.
- UI: new `hire:` source in the existing DHQ Approvals tab (PR #182 pattern) — no new tab.
- Proposal generation: SQL-deterministic shortlist + best-effort K.I.N. narrative (hybrid).

## References

- Task #2102 — original specification
- `check_understaffed_capabilities` — `platform_v2/services/agent_jobs.py:1558`
- `agent_understaffed_digest` job — `platform_v2/tools/department_hq/services/job_registry.py:873`
- `agent_service.transition_shift_state` — `platform_v2/services/agent_service.py:988`
- `agent_service.create_agent` / `update_agent` — `platform_v2/services/agent_service.py:158,210`
- Unified approvals endpoint (PR #182) — `platform_v2/tools/department_hq/approvals_routes.py`
- `feedback_ghost-models.md` memory — rationale for the model-availability pre-check
