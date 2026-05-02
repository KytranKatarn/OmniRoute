# K.I.N. × C.R.E.E.D. Welfare Intelligence Pipeline

**Date**: 2026-05-01
**Status**: Approved — ready for implementation
**Project**: Agent Welfare / C.R.E.E.D. Governance

---

## Problem

The `kin_welfare_digest` job runs daily and produces accurate welfare data, but K.I.N. the agent is never actually involved — all logic is rule-based Python. K.I.N. never appears in `task_execution_log`, shows as idle, and the welfare system produces numbers without judgment. C.R.E.E.D. has a `governance_audit_log` table and a public dashboard but no agent is actively filing ethics concerns to it.

---

## Solution

Transform `kin_welfare_digest` into a 4-phase intelligence pipeline where K.I.N. (gemma3:12b) is the reasoning layer, can act autonomously, and files formal concerns to C.R.E.E.D. Results are reported to A.R.C.H.I.E. — not directly to Telegram — so A.R.C.H.I.E. controls escalation based on severity.

---

## Architecture

```
Phase 1: Data collection (Python)
    get_kin_welfare_digest() → per-agent welfare snapshot dict

Phase 2: K.I.N. LLM assessment (dispatch)
    dispatch(capability='welfare', agent='K.I.N.', prompt=snapshot)
    → structured JSON assessment

Phase 3: Autonomous actions (Python executes K.I.N.'s decisions)
    welfare_recovery | cooldown | barracks | workload_cap
    → all logged to governance_audit_log as C.R.E.E.D. paper trail

Phase 4: C.R.E.E.D. + A.R.C.H.I.E. report
    K.I.N.'s creed_flags → governance_audit_log (event_category='welfare_ethics')
    K.I.N.'s archie_report → telegram_service(source_agent='K.I.N.')
    A.R.C.H.I.E. routes: critical/alert → Telegram now, warning → digest, info → internal
```

---

## Phase 2 — K.I.N. Dispatch Contract

**Capability**: `welfare`
**Model**: `gemma3:12b` (K.I.N.'s assigned model)
**prefer_agent**: `K.I.N.`

**Prompt structure**:
```
You are K.I.N. (Kinship & Internal Nurturing), Director of Human Resources & Culture.
Today's welfare snapshot: <formatted JSON of per-agent flags>

Assess the platform's welfare state. Return ONLY valid JSON matching this schema:
{
  "summary": "<2-3 sentence plain-language overview>",
  "at_risk_agents": [{"agent_id": int, "name": str, "reason": str, "severity": "low|medium|high|critical"}],
  "idle_neglected": [{"agent_id": int, "name": str, "days_idle": int, "department": str}],
  "actions": [
    {"type": "welfare_recovery|cooldown|barracks|workload_cap", "agent_id": int, "reason": str, "value": <int for workload_cap, else null>}
  ],
  "creed_flags": [
    {"event_type": str, "agent_id": int, "reason": str, "severity": "low|medium|high|critical"}
  ],
  "archie_report": {"message": str, "severity": "info|warning|alert|critical"}
}
```

**Fallback**: if dispatch returns queued/empty, skip Phase 3+4 and log warning. Do not fail the job.

---

## Phase 3 — Autonomous Actions

K.I.N. makes the call. No Telegram approval required. All actions executed in order:

| `type` | Implementation | Notes |
|--------|---------------|-------|
| `welfare_recovery` | `agent_service.recover_idle(agent_id)` | Boosts energy +0.2, reduces stress -0.15 |
| `cooldown` | `agent_service.transition_shift_state(id, 'cooldown', 'kin_welfare_action')` | Temporary rest cycle |
| `barracks` | `agent_service.transition_shift_state(id, 'barracked', 'kin_welfare_action')` | Full stand-down |
| `workload_cap` | `UPDATE agent_budgets SET task_queue_limit = value WHERE agent_id = id` | Caps daily task load |

Each executed action is immediately logged to `governance_audit_log`:
- `event_type`: `kin_welfare_action`
- `event_category`: `welfare_ethics`
- `agent_id`: target agent
- `action`: the action type
- `reason`: K.I.N.'s stated reason
- `outcome`: `applied`

---

## Phase 4a — C.R.E.E.D. Ethics Filing

For each item in `creed_flags` K.I.N. raises:

```sql
INSERT INTO governance_audit_log (
  event_type, event_category, agent_id, action, reason, outcome, details
) VALUES (
  <creed_flag.event_type>, 'welfare_ethics', <agent_id>,
  'ethics_concern', <reason>, 'flagged',
  '{"severity": "<severity>", "filed_by": "K.I.N.", "digest_date": "<date>"}'
)
```

K.I.N. decides what warrants filing — exploitation, neglect, forced-barracks confirmation, mood collapse. No threshold rule in Python.

---

## Phase 4b — A.R.C.H.I.E. Report

K.I.N. sends its `archie_report` via `telegram_service` with `source_agent='K.I.N.'`, not directly to Telegram. A.R.C.H.I.E. applies severity routing:

| K.I.N. severity | A.R.C.H.I.E. action |
|-----------------|---------------------|
| `critical` | `telegram_service.send_alert()` → immediate Telegram push |
| `alert` | `telegram_service.send_alert()` → immediate Telegram push |
| `warning` | `telegram_service.send_info()` → included in next digest |
| `info` | Internal log only — no Telegram |

Message format: K.I.N.'s `archie_report.message` + count of actions taken + count of C.R.E.E.D. flags filed.

---

## Files to Modify

| File | Change |
|------|--------|
| Job file containing `kin_welfare_digest` — search `autonomy_loop_log` job_name or grep for `_log_cycle.*kin_welfare` to locate it | Replace single `_log_cycle` call with 4-phase pipeline |
| Same file — add `_kin_assess_welfare(data)` | Dispatch to K.I.N., parse JSON response, return assessment dict |
| Same file — add `_kin_execute_actions(actions)` | Iterate K.I.N.'s action list, apply each, log to governance_audit_log |
| Same file — add `_kin_file_creed(creed_flags)` | Insert each flag into governance_audit_log |
| Same file — add `_kin_report_to_archie(archie_report, actions_taken, flags_filed)` | Format + route via telegram_service(source_agent='K.I.N.', source_department='Human Resources & Culture') |

**Note on C.R.E.E.D. dashboard**: `creed_routes.py` `creed_public_stats()` already queries `governance_audit_log` with `event_category` filtering. K.I.N.'s `welfare_ethics` entries will appear automatically on `creed.kytranempowerment.com` and `creed-ai.org` with no route changes needed.

No schema changes required. All target tables already exist.

---

## Error Handling

- **K.I.N. dispatch fails / queued**: log warning, skip Phases 3+4, job still succeeds. Do not create false failures.
- **K.I.N. returns invalid JSON**: catch parse error, log warning, skip action execution.
- **Individual action fails**: log the error to governance_audit_log with `outcome='failed'`, continue to next action. Do not abort the whole pipeline.
- **C.R.E.E.D. insert fails**: log warning, continue. Non-fatal.
- **A.R.C.H.I.E. message fails**: log warning. Non-fatal.

---

## Success Criteria

- K.I.N. appears in `task_execution_log` daily (no longer idle)
- `kin_welfare_digest` anomaly: warnings become meaningful (K.I.N.-authored) not Python-threshold noise
- `governance_audit_log` receives welfare_ethics entries from K.I.N. when warranted
- C.R.E.E.D. public dashboard (`creed.kytranempowerment.com`) reflects K.I.N.'s filings
- A.R.C.H.I.E. routes severity correctly — low-severity days stay quiet, critical issues reach Telegram
- `kin_welfare_digest` job stays under 120s total (K.I.N. dispatch is the bottleneck — gemma3:12b cold ~30s)

---

## Out of Scope

- K.I.N. UI tab in DHQ (separate project)
- K.I.N. responding to Telegram messages directly (A.R.C.H.I.E. is sole Telegram voice)
- Automated re-activation after barracks (human decision or separate scheduled review)
