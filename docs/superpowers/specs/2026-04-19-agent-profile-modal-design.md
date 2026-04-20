# Agent Profile Detail Modal — Design Spec

**Task**: #1916 (Project #262 — Agent Profile Manager)
**Date**: 2026-04-19
**Status**: Approved, awaiting implementation plan

## Goal

Build the authoritative editor for agent profiles inside Department HQ → Roster tab. Click any agent card → LCARS `bm-` modal opens with the full profile in read-only view; admin can toggle Edit and save 23 fields. Every successful save writes to `agents` via `agent_service.update_agent()` and emits one `governance_audit_log` row with before/after diff.

This modal is the **single-source anchor**. All downstream consumers (AI Directors public page, website `/directory`, Org Chart tab when built, `/api/identity/directors`, `/api/public/directory`) read from the same `agents` table this modal writes to. Consolidation of duplicate directory/employee modules is tracked separately under follow-up tasks.

## Scope

### In scope (this PR)
- New LCARS `bm-` modal in `department_hq.html`, opened from Roster tab card clicks.
- View mode (read-only render of all profile data).
- Edit mode (23 editable fields, Save/Cancel, confirm-on-dirty for sensitive fields).
- Extend existing `GET /api/agent/<id>/profile` to return the full editable set.
- New `PATCH /api/agent/<int:agent_id>` endpoint with field allowlist + validation + audit log.
- Shift-state one-click pill (reuses existing `POST /api/agent/<id>/shift`).
- Read-only portrait, skills, welfare, performance sections with deep-links to their edit locations.
- Pytest unit tests + Playwright e2e test.

### Out of scope (separate tasks)
- Portrait upload (#1917) / generate via Media Studio (#1918 + #1923) / gallery (#1919).
- Skills editor inside this modal (skills tab handles that).
- Welfare editor inside this modal (Performance tab handles that).
- Decommission of `platform_v2/tools/directory/` and `platform_v2/business/routes.py` directory endpoints (new tasks under #1921).
- Wiring `website/kytranempowerment.com/directory.html` to platform public API (new task under #1921).
- Org Chart tab (new task under Project #262).

## Architecture

### Frontend

One modal in `platform_v2/tools/department_hq/templates/department_hq.html`:

```html
<div id="agentProfileModal" class="bm-overlay" data-mode="view" data-agent-id="">
  <div class="bm-shell">
    <div class="bm-frame">
      <div class="bm-content">
        <div class="bm-header">…portrait, name band, Edit pill…</div>
        <div class="bm-body">…sections…</div>
        <div class="bm-footer">…Close | Cancel/Save…</div>
      </div>
    </div>
  </div>
</div>
```

Logic lives in `platform_v2/static/js/agent_profile_modal.js` (follows the `lcars-header.js` pattern — keeps the 20k-line template lean).

Module API exposed on `window`:
```javascript
window.agentProfileModal = {
  open(agentId),
  close(),
  _refresh(),          // internal
};
```

Roster tab card click handler binds to `window.agentProfileModal.open(card.dataset.agentId)`.

**Naming note for implementation plan**: an existing function `openAgentProfileFromBridge(hubAgentId)` is referenced in CLAUDE.md for profile UI elsewhere. The plan should decide whether to (a) replace/redirect that helper to call `agentProfileModal.open()`, or (b) leave it as a distinct legacy path until its callers migrate. Either choice is fine; the spec does not prescribe.

### Backend

Two changes in `platform_v2/tools/department_hq/agent_detail_routes.py`:

1. **Extend `GET /api/agent/<id>/profile`** — return all 23 editable fields alongside the existing read-only blocks (portrait, skills, welfare, performance, shift). Purely additive, no breaking change.

2. **Add `PATCH /api/agent/<int:agent_id>`** (admin-gated) — accepts partial JSON body of dirty fields, validates against allowlist + per-field rules, calls `agent_service.update_agent(agent_id, **fields)`, writes governance audit row.

No new tables. No migrations. No changes to `agent_service.py` public surface (new validation lives inside the PATCH handler so `update_agent` stays generic).

## Modal structure

```
┌─ bm-header ─────────────────────────────────────┐
│  Portrait (200x200)   Display Name      [Edit]  │
│                       Code Name · ACR           │
│                       ⟨dept⟩ · ⟨floor⟩ · ⟨pill⟩ │
└─────────────────────────────────────────────────┘
┌─ bm-body (scrolls) ─────────────────────────────┐
│  ▸ Identity       (7 fields)                     │
│  ▸ Classification (5 fields)                     │
│  ▸ Dispatch       (4 fields, ⚠️ sensitive)       │
│  ▸ Appearance     (5 fields)                     │
│  ▸ Voice & Social (2 fields)                     │
│  ─────────────────────────────                   │
│  Skills           (chips, read-only) → Academy   │
│  Welfare          (meters, read-only) → Perf tab │
│  Performance      (stat tiles) → Perf tab        │
│  Shift State      (one-click pill)               │
└─────────────────────────────────────────────────┘
┌─ bm-footer ─────────────────────────────────────┐
│  view-mode: [Close]                              │
│  edit-mode: [Cancel]              [Save Changes] │
└─────────────────────────────────────────────────┘
```

### Sections

| Section | Fields |
|---|---|
| Identity | display_name, title, bio, acronym, acronym_expansion, pronouns, current_grade |
| Classification | department, floor, writing_tone, is_department_ai, reports_to_agent_id |
| Dispatch ⚠️ | model, temperature, max_tokens, system_prompt |
| Appearance | communication_style, appearance_notes, age_range, gender, ethnicity |
| Voice & Social | social_topics (JSON list), auto_approve_threshold |

Sensitive fields (trigger confirm-on-dirty):
```
model, temperature, max_tokens, system_prompt,
is_department_ai, reports_to_agent_id
```

## State machine

```
closed --open(id)--> loading --(fetch ok)--> view
                            --(fetch err)--> closed (toast)
view --edit--> edit
edit --cancel--> view (discard)
edit --save--> [sensitive dirty?] --yes--> confirm-overlay --accept--> saving
                                  --no---> saving
saving --ok--> view (refreshed)
saving --err-> edit (toast, field highlighted)
any --close--> closed (unbinds listeners, clears snapshot)
```

## Data flow

**Open**:
```
click .roster-agent-card[data-agent-id=N]
  → window.agentProfileModal.open(N)
  → GET /api/agent/N/profile (admin-gated)
  → populate view DOM, cache snapshot
  → bm-overlay.classList.add('active')
```

**Edit**:
```
click [data-action=edit]
  → overlay.dataset.mode = 'edit'
  → view divs hidden, inputs shown (prefilled from snapshot)
```

**Save**:
```
click [data-action=save]
  → diff(snapshot, form) → dirty_fields
  → if any ∈ SENSITIVE_FIELDS → show confirm overlay
  → PATCH /api/agent/N with dirty_fields body
  → 200: toast 'Saved', _refresh(), mode='view'
  → 4xx: toast error, stay in edit mode, highlight failing field
```

## API contracts

### `GET /tools/department-hq/api/agent/<int:agent_id>/profile`

Response body extended to include all editable fields:

```json
{
  "agent": {
    "id": 145, "name": "kin", "display_name": "K.I.N.",
    "title": "Human Resources Director", "bio": "…", "acronym": "KIN",
    "acronym_expansion": "Kinship, Integrity, Nurture",
    "pronouns": "she/her", "current_grade": "A",
    "department": "Human Resources & Culture", "floor": "SERVICES",
    "writing_tone": "warm", "is_department_ai": true,
    "reports_to_agent_id": null,
    "model": "mistral:7b", "temperature": 0.7, "max_tokens": 2048,
    "system_prompt": "…",
    "communication_style": "supportive", "appearance_notes": "…",
    "age_range": "30s", "gender": "female", "ethnicity": "…",
    "social_topics": ["hr", "culture"], "auto_approve_threshold": 50.0,
    "shift_state": "active", "status": "active", "avatar_url": "…"
  },
  "skills":     [...],
  "welfare":    {...},
  "performance":{...}
}
```

### `PATCH /tools/department-hq/api/agent/<int:agent_id>`

Admin-gated. Body is a partial dict of dirty fields.

Success (200):
```json
{ "ok": true, "updated_fields": ["display_name", "bio"] }
```

Errors:
| Status | `error` code | Meaning |
|---|---|---|
| 400 | `unknown_field` | Field not in allowlist |
| 400 | `invalid_value` | Failed per-field rule |
| 400 | `model_not_available` | Model not present on any Ollama host |
| 400 | `reports_to_self` | `reports_to_agent_id == agent_id` |
| 400 | `reports_to_missing` | Target agent not found |
| 403 | `not_admin` | Auth fail |
| 404 | `not_found` | agent_id missing |
| 500 | `update_failed` | DB error |

### Field allowlist

```python
EDITABLE_FIELDS = {
  "display_name", "title", "bio", "acronym", "acronym_expansion",
  "pronouns", "current_grade",
  "department", "floor", "writing_tone", "is_department_ai",
  "reports_to_agent_id",
  "model", "temperature", "max_tokens", "system_prompt",
  "communication_style", "appearance_notes",
  "age_range", "gender", "ethnicity",
  "social_topics", "auto_approve_threshold",
}

SENSITIVE_FIELDS = {
  "model", "temperature", "max_tokens", "system_prompt",
  "is_department_ai", "reports_to_agent_id",
}
```

### Validation rules

| Field | Rule |
|---|---|
| `model` | Probe `/api/tags` on hub (5s timeout). The same check already exists inside `hiring_service` as a private helper; the implementation plan should either promote it to a public helper (e.g. `services/ollama_availability.py::is_model_available`) or duplicate the minimal logic locally. Do not import underscore-private symbols across services. |
| `temperature` | `0.0 <= x <= 2.0` |
| `max_tokens` | `1 <= x <= 8192` |
| `reports_to_agent_id` | Must exist in agents; must ≠ agent_id; may be `null` |
| `department` | Must be key in `agent_service.DEPARTMENT_FLOOR_MAP` |
| `floor` | Must be valid LCARS floor string |
| `social_topics` | Must be list[str] |
| `auto_approve_threshold` | `0.0 <= x <= 1000.0` |
| `is_department_ai` | bool |
| All others | Pass through (trim strings, preserve nulls) |

### Audit trail

Every successful PATCH writes one row:
```
event_type     = 'agent_profile_update'
event_category = 'agent_management'
agent_id       = <subject agent id>
user_id        = <acting admin user id>
action         = 'profile_update'
details        = {
  "before": { <old values of changed fields only> },
  "after":  { <new values of changed fields only> }
}
timestamp      = now()
```

Serialize `details` with `json.dumps(..., default=str)` to handle any datetime leaks.

## Cache invalidation

`agent_service.update_agent()` already invalidates `_agent_cache`. The dispatcher picks up changes on next `get_agent_cache()` refresh (30s TTL). No additional cache work.

## Files changed

| File | Change |
|---|---|
| `platform_v2/tools/department_hq/agent_detail_routes.py` | Extend `api_agent_profile` return; add `api_agent_patch` handler |
| `platform_v2/tools/department_hq/templates/department_hq.html` | Add `#agentProfileModal` markup + include `agent_profile_modal.js` |
| `platform_v2/static/js/agent_profile_modal.js` | **New** — modal open/edit/save state machine |
| `platform_v2/static/css/agent_profile_modal.css` | **New** — section dividers, field grid, sensitive marker, confirm-on-dirty styling |
| `platform_v2/static/css/department_hq.css` | Add `.roster-agent-card { cursor:pointer }` + hover state |
| `platform_v2/tests/test_agent_profile_patch.py` | **New** — 11 unit tests (see below) |
| `platform_v2/tests/e2e/test_agent_profile_modal.py` | **New** — 6 Playwright scenarios |

## Testing

### Pytest (`platform_v2/tests/test_agent_profile_patch.py`)

1. `test_patch_unknown_field_rejected` — `{"tier": 99}` → 400 `unknown_field`
2. `test_patch_non_admin_forbidden` — non-admin → 403
3. `test_patch_missing_agent` — `/api/agent/99999` → 404
4. `test_patch_valid_identity_fields` — display_name/bio/title → 200, row updated
5. `test_patch_sensitive_model_invalid` — model not in Ollama → 400 `model_not_available`
6. `test_patch_sensitive_model_valid` — model exists → 200
7. `test_patch_temperature_bounds` — -1, 3 → 400; 0.5 → 200
8. `test_patch_reports_to_self_rejected` — reports_to_agent_id == agent_id → 400
9. `test_patch_writes_audit_row` — after 200, governance_audit_log has new row with before/after diff
10. `test_patch_partial_body` — only dirty fields update; untouched columns preserved
11. `test_patch_invalidates_cache` — `_agent_cache` stale after successful update

### Playwright (`platform_v2/tests/e2e/test_agent_profile_modal.py`)

1. Navigate to `/tools/department-hq#roster`, click any agent card → modal opens, portrait visible, name matches card.
2. Click Edit → inputs appear, Save/Cancel swap in footer.
3. Change bio → Save → toast "Saved", modal reverts to view mode, bio reflects new value.
4. Click Edit → change `system_prompt` → Save → confirm-on-dirty overlay appears → accept → saves.
5. Click Edit → change `model` to known-missing name → Save → error toast, field highlighted, modal stays open.
6. Close modal → reopen same agent → edits persisted.

## Rollout

1. Merge PR behind default-on (admin-only auth is the gate).
2. Post-deploy smoke: edit K.I.N.'s bio to known value, confirm `governance_audit_log` row, revert.
3. Dev HQ close-out:
   - `mcp__archie__complete_task(task_id=1916, notes=...)`
   - `mcp__archie__log_decision(title="Agent Profile Modal as Single-Source Editor", ...)`
   - `mcp__archie__update_project_understanding(project_id=262, understanding_level=35, ...)` (Project #262 has 8 tasks; this lands #1 of 8)
   - `mcp__archie__store_memory(memory_type='vault_note', ...)` — API reference for #1917/#1918/#1923 consumers

## Follow-up tasks (to log after spec approval)

All under Project #262:

- **Expand #1921** — "Auto-distribute" becomes three concrete decommissions:
  - Kill `platform_v2/tools/directory/` — redirect `/directory` + `/tools/directory` → `/tools/department-hq#roster`
  - Kill `/directory` + `/api/directory*` inside `platform_v2/business/routes.py`
  - Wire `website/kytranempowerment.com/directory.html` to consume `/api/public/directory`
- **New task** — Build Org Chart tab in Dept HQ. Reads from agents table, node click opens this same modal.

These do NOT block #1916. They are scheduled after the modal lands so the editor is live before any consumer flips over to it.

## Non-goals

- No per-field inline autosave (ruled out — see design session Q2).
- No propose-and-approve workflow for profile edits (Q3 ruled this out; audit + confirm-on-dirty is sufficient).
- No public API surface change (readers like `/api/public/directory` already pull from `agents` unchanged).
- No feature flag — the modal is admin-gated and strictly additive; no legacy edit path to keep alive.
