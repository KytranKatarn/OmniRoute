# Collaborator Persona Curated Facts (Grounding) — Design

**Task:** #4959 · **Project:** #390 (Collaborator Persona-Assistants) · **Date:** 2026-07-17
**Status:** Design — pending owner review → writing-plans
**Depends on:** #4958 (no-fabrication guardrail, shipped PRs #2311/#2312) · Slice 1 email assistant (#4954, PR #2309)

---

## 1. Problem

The collaborator persona email assistant drafts replies "as" a human collaborator
(e.g. Jin Park) on their `human_agent` mailbox. A live test caught it **fabricating
business data** — inventing churn/retention figures and a non-existent attachment — one
tap from sending under a real person's name (KB mistake #281718). #4958 added a
fail-closed no-fabrication guard, which made drafts *safe* but not *useful*: with no real
context to draw on, the persona can only acknowledge / clarify / defer / restate the
thread. #4959 is the piece that gives the persona **real, groundable recall** so its
drafts can actually answer questions — without reopening the fabrication hole.

### Why the original framing ("read `agent_memory`") does not work

Investigation (2026-07-17) of the live platform found:

- **`agent_memory` is the wrong/empty source for collaborators.** Of the 21 `human_agent`
  collaborators, **10 have zero memories**; the 4 populated agents (9/11/43/341) hold
  almost entirely `memory_type='skill'` self-improvement logs — **not groundable business
  facts**. Wiring `agent_memory` in would inject skill-log noise, not usable context.
- **No semantic retrieval is possible.** `agent_memory` has **no `embedding` column**
  (281,186 rows), so retrieval could only be recency/importance/keyword.
- **The guard would reject recalled figures anyway.** `validate_draft_no_fabrication`
  (`draft_proposal_service.py:131`, core check L165-167) computes
  `invented = _numbers_in(body) - _numbers_in(inbound_text)` and rejects **any** number
  in the draft not present in the inbound thread. Its only allowed-facts source is the
  inbound thread. A correctly-recalled "4.1%" would be rejected because the digits live in
  the memory, not the inbound message. **Grounding and safety currently fight each other.**

**Conclusion:** the real decision is *what the grounding source should be* and *making that
source also the validator's allowed-facts source*, so recall and safety align. Owner
decision (2026-07-17): a **new curated per-collaborator facts store**, managed in the DHQ
agent profile.

## 2. Goal / Non-goals

**Goal:** Let a curated set of real, owner-controlled facts per collaborator persona be
(a) injected into the draft prompt as citable context and (b) accepted by the
no-fabrication validator as allowed facts, so a persona can cite a genuine figure without
being rejected — while pure invention still fails closed.

**Non-goals (this slice):**
- Semantic/embedding retrieval (curated sets are small; inject all active facts).
- Auto-populating facts from `agent_memory`, email history, or Chronicle (future slices).
- Applying facts to the owner/business draft path (stays unchanged this slice).
- Verifying a cited fact is applied *correctly* — the validator only checks a number is in
  the allowed set; the owner still approves every send (accepted limitation).

## 3. Design

Six small, isolated pieces.

### 3.1 Data — `collaborator_facts` (migration 460)

```sql
CREATE TABLE IF NOT EXISTS collaborator_facts (
    id          SERIAL PRIMARY KEY,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    fact_text   TEXT    NOT NULL,
    category    VARCHAR(60),           -- e.g. 'role', 'account', 'sla', 'boundary'
    importance  SMALLINT DEFAULT 5,    -- sort/priority within a persona
    is_active   BOOLEAN  DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    created_by  VARCHAR(120),
    updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_collab_facts_agent_active
    ON collaborator_facts (agent_id, is_active);
```

Keyed by `agent_id` (generic/reusable across any agent). The editor renders on every agent
profile; only the collaborator draft path *consumes* the facts, so a non-collaborator's
facts are simply unused (no per-agent gating needed in the UI). Idempotent (`IF NOT EXISTS`).

### 3.2 Retrieval — `services/collaborator_facts_service.py` (new, isolated, testable)

Pure DB, no inference. `try/finally: conn.close()`; `psycopg2.Json` for any jsonb; dict
rows via the standard cursor.

- `get_active_facts(agent_id) -> list[dict]` — active facts, ordered `importance DESC, id`.
- `list_for_agent(agent_id) -> list[dict]` — all (active + inactive) for the editor.
- `add_fact(agent_id, fact_text, category, importance, created_by) -> dict`
- `update_fact(fact_id, **fields) -> dict`
- `set_active(fact_id, is_active) -> dict`
- `delete_fact(fact_id) -> bool`
- `facts_as_prompt_block(facts) -> str` — renders the bullet block (single source of truth
  so the prompt text and the validator's allowed-facts text are built the SAME way).
- `facts_allowed_text(facts) -> str` — the concatenated `fact_text` corpus passed to the
  validator (so its numbers are recognised as allowed).

### 3.3 Draft grounding — `draft_proposal_service._create_collaborator_proposal`

After the `_NO_FABRICATION_CONTRACT`, before the inbound email, inject:

```
ALLOWED FACTS — you MAY reference these; do not invent anything beyond them or the thread:
- <fact_text>
- <fact_text>
```

When the persona has zero active facts, omit the block entirely (behaviour identical to
today → still safe). This is a DB read inside the already-fleet-dispatched
`mailhq_collaborator_drafts` job — **no new inference** (module-work-pattern preserved).

### 3.4 Safety — extend `validate_draft_no_fabrication`

Backward-compatible signature change:

```python
def validate_draft_no_fabrication(draft, inbound_text, allowed_facts_text=""):
    ...
    invented = _numbers_in(body) - _numbers_in(inbound_text) - _numbers_in(allowed_facts_text)
```

- Default `allowed_facts_text=""` → owner/business path (and any other caller) behaves
  **identically** to today.
- The attachment-claim rejection (`_ATTACHMENT_RE`) is **unchanged** — a fact never grants
  an attachment claim.
- Net rule: a cited number passes **iff** it appears in the inbound thread **or** in a
  curated fact. Pure invention still fails closed.
- Called at `_create_collaborator_proposal` L547 with `allowed_facts_text=facts_allowed_text(facts)`.

### 3.5 UI — DHQ agent profile "Curated Facts" section

- New admin-gated endpoints in `agent_detail_routes.py` (`register_agent_detail_routes`),
  mirroring the existing `/api/agent/<id>/skills` GET/POST pattern:
  - `GET  /api/agent/<int:agent_id>/facts` — list (active + inactive) for the editor.
  - `POST /api/agent/<int:agent_id>/facts` — add `{fact_text, category, importance}`.
  - `PUT  /api/agent/facts/<int:fact_id>` — edit / toggle `is_active`.
  - `DELETE /api/agent/facts/<int:fact_id>` — remove.
  - All `@admin_required`. JSON responses via `Response(json.dumps(..., default=str))`
    (psycopg2 types break `jsonify`, KB #269068).
- Frontend: a "Curated Facts" section in the agent-profile modal in `department-hq.js`,
  mirroring the existing Skills section (fetch on profile open, add/edit/toggle inline).
  Render fact text via `textContent` (XSS-safe). Rendered on every agent profile (generic
  per-agent store); only the collaborator draft path consumes it, so no per-agent gating.

### 3.6 Tests — extend `tests/test_collaborator_draft.py`

- **Validator:** number present only in a fact → **passes**; number absent from both thread
  and facts → **rejected**; attachment claim → still **rejected**; empty `allowed_facts_text`
  → identical to pre-change behaviour (owner path regression guard).
- **Facts service:** add / list_active (ordering + is_active filter) / update / set_active /
  delete; `facts_as_prompt_block` / `facts_allowed_text` formatting.
- **Draft path:** with facts → prompt contains the ALLOWED FACTS block and the validator is
  called with the facts corpus; with zero facts → block omitted, validator called with `""`.

## 4. Data flow

```
mailhq_collaborator_drafts job (scheduler, 10-min, fleet-dispatched)
  → _create_collaborator_proposal(c)
      → facts = collaborator_facts_service.get_active_facts(c.collaborator_agent_id)
      → prompt = persona + _NO_FABRICATION_CONTRACT + facts_as_prompt_block(facts) + inbound
      → draft = queued_dispatch_text(capability="support", model_override="llama3.2:3b",
                                     local_only=True, ...)                 # unchanged dispatch
      → ok, reason = validate_draft_no_fabrication(
                         draft, _inbound_text(c),
                         allowed_facts_text=facts_allowed_text(facts))     # NEW arg
      → ok  → autonomy_approval_queue row (action_type='email_reply') → owner Telegram [Send/Cancel]
        !ok → _REJECTED (no row, no ping, counted rejected)                # fail-closed unchanged
```

## 5. Module-work-pattern compliance

The grounding retrieval is a cheap DB read inside the existing **fleet-dispatched**
`mailhq_collaborator_drafts` scheduler job; draft generation already uses the cold-tolerant
`queued_dispatch_text`. No new synchronous inference, no new job, no direct Ollama. Facts
CRUD is admin UI, not agent work. Compliant.

## 6. Rollout / gate

No new gate. The whole collaborator draft path stays behind the existing
`mailhq:draft:collaborators` flag (currently OFF, needs #4957 before go-live). This slice
makes drafts *useful and still safe*; it does not flip the gate. Owner-approval Telegram
remains the only publish path.

## 7. Known limitations (accepted this slice)

- The validator checks a number is *present in the allowed set*, not that it is *applied
  correctly*; the owner approval gate covers misapplication.
- Facts are curated by hand (cold-start empty). Auto-suggestion from `agent_memory` / email
  history / Chronicle is a future slice.
- Widening the allowed-number set means a fact containing e.g. `2024` lets `2024` pass
  anywhere in that persona's drafts — acceptable, since the owner curated it as citable.

## 8. Future slices (out of scope)

- Suggest/auto-populate facts from thread history or Chronicle per-entity stories.
- Per-correspondent fact scoping.
- Owner/business path curated facts.
- Repopulate `agent_memory` with the right shape and add semantic retrieval.

## 9. Files touched

| File | Change |
|------|--------|
| `database/migrations/460_collaborator_facts.sql` | new table (idempotent) |
| `platform_v2/services/collaborator_facts_service.py` | new — CRUD + retrieval + render helpers |
| `platform_v2/tools/email_manager/draft_proposal_service.py` | inject facts block; pass `allowed_facts_text` to validator |
| `platform_v2/tools/department_hq/agent_detail_routes.py` | 4 facts endpoints (admin) |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Curated Facts section in agent profile modal |
| `platform_v2/tests/test_collaborator_draft.py` | validator + service + draft-path tests |

## 10. Verify during planning

- Exact agent-profile modal render function in `department-hq.js` to attach the Facts
  section (the profile fetches `/api/agent/<id>/profile` and renders a Skills section to
  mirror).
- Confirm `_create_collaborator_proposal` line anchors (L517-547) are current before editing.
