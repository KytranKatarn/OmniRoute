# Compliance Pipeline — Design Spec
**Date:** 2026-05-12 | **Status:** Approved | **Author:** Claude + Kytran

---

## Problem

KSO, Security Network, and Consciousness Code Health all run compliance scans, but findings never reach Repair Bay or Consciousness. Each module is a silo — results stay in their own DB tables, no proposals are created, no fixes are tracked, no knowledge is recorded.

---

## Solution: Unified Compliance Coordinator (Option A)

New `platform_v2/services/compliance_coordinator.py` — single entry point for all compliance findings. Each module submits findings; the coordinator groups, deduplicates, dispatches to the module's designated agent, creates Repair Bay proposals, and writes Consciousness vault_notes.

---

## Architecture

```
KSO scan completes           ──┐   POST /api/compliance/submit-findings
Security Network scan        ─┼──►  { source, scan_id, findings[] }
Consciousness Code Health    ──┘            │
                                            ▼
                              ComplianceCoordinator.process()
                                1. Group findings by rule_id across sources
                                2. Deduplicate: skip if open proposal exists
                                3. Dispatch to module agent (B.A.S.E./V.I.G.I.L./F.O.R.G.E.)
                                4. Agent writes proposal title + description + fix
                                            │
                               ┌────────────┴────────────────┐
                               ▼                             ▼
                       Repair Bay proposal          Consciousness vault_note
                       (improvement_proposals)      (category: compliance_finding)

                       [Later: fix deployed]
                               ▼
                       Consciousness vault_note #2 (category: compliance_resolved)
```

---

## Components

### 1. `ComplianceCoordinator` (`services/compliance_coordinator.py`)

**`process(source, scan_id, findings, triggered_by)`**
- `source`: `'kso'` | `'security_network'` | `'consciousness_code_health'`
- `findings`: list of `{rule_id, severity, title, detail, remediation}`
- Groups findings by `rule_id` across concurrent submissions
- Deduplicates: calls `_has_open_proposal(rule_id)` before creating
- Dispatches to agent: `dispatch(capability='compliance', prompt=..., context={...})`
- Returns `{proposals_created, skipped_duplicates, vault_notes_written}`

**Agent routing (module-based):**
| Source | Agent | ID | Capability |
|--------|-------|----|------------|
| kso | B.A.S.E. | #139 | compliance |
| security_network | V.I.G.I.L. | #3 | compliance |
| consciousness_code_health | F.O.R.G.E. | #136 | code_review |

### 2. API endpoint (`tools/repair_bay/routes.py` or new `compliance_routes.py`)

**`POST /api/compliance/submit-findings`**
```json
{
  "source": "kso",
  "scan_id": "uuid",
  "triggered_by": "scheduled",
  "findings": [
    {
      "rule_id": "docker-stig:VULN-001",
      "severity": "high",
      "title": "Docker container running as root",
      "detail": "Container archie_platform running with --user=root",
      "remediation": "Add USER directive to Dockerfile"
    }
  ]
}
```
Response: `{proposals_created, skipped_duplicates, vault_notes_written}`

### 3. DB table: `compliance_pipeline_submissions`

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| source | varchar | kso / security_network / consciousness_code_health |
| scan_id | uuid | links back to source scan |
| rule_id | varchar | for grouping cross-source |
| severity | varchar | high / medium / low |
| proposal_id | int FK | null if skipped/deduped |
| vault_note_id | int | KB entry id |
| triggered_by | varchar | scheduled / manual |
| created_at | timestamptz | |

### 4. Trigger wiring (per module)

**KSO** (scheduled): add hook in `kytran_system_operations/routes/compliance_routes.py` after `run_scan()` completes on scheduled jobs — POST to `http://192.168.1.200:3000/api/compliance/submit-findings` using `KSO_ARCHIE_HUB_URL` + `KSO_CHAT_API_KEY`.

**KSO** (manual): add "Send to Repair Bay" button in compliance tab — shown only when `chat_enabled=True` (business+ tier). Confirmation dialog before submitting.

**Security Network**: hook into `_run_proactive_scan()` in `agent_loop.py` for scheduled. Manual button in Security Network compliance tab.

**Consciousness Code Health**: hook into `_run_proactive_scan()` or code audit job in `agent_loop.py`.

---

## Tier Gate

Business+ tier required to submit findings to the coordinator. Matches the B.A.S.E. chat paywall. Free/pro users run scans locally — findings stay in their module's DB.

---

## Consciousness Loop

**On proposal creation:**
```python
store_memory(
    title=f"Compliance Finding — {rule_id} [{source}]",
    memory_type='vault_note',
    category='compliance_finding',
    content=f"B.A.S.E./V.I.G.I.L./F.O.R.G.E. identified: {agent_analysis}",
    tags=[source, rule_id, 'compliance', 'auto-generated'],
    importance=0.8
)
```

**On fix deployed (Repair Bay post-deploy hook):**
```python
store_memory(
    title=f"Compliance Resolved — {rule_id}",
    memory_type='vault_note',
    category='compliance_resolved',
    tags=[source, rule_id, 'compliance', 'resolved']
)
```

---

## Deduplication

`_has_open_proposal(rule_id)`: query `improvement_proposals` for any row with matching `rule_id` in metadata AND status not in `('rejected', 'deployed')`. If found, skip creation. If found and status is `deployed`, allow re-creation (regression).

---

## Error Handling

- Agent dispatch fails → log to `compliance_pipeline_submissions` with `proposal_id=NULL`, no retry. Next scheduled scan will re-submit.
- Hub unreachable from KSO → KSO stores finding locally in `compliance_pending_queue` table, retries on next heartbeat.
- Severity filter: `high` → immediate, `medium` → batched (weekly Sunday 02:00), `low` → skip.

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `platform_v2/services/compliance_coordinator.py` | CREATE — main coordinator service |
| `platform_v2/tools/repair_bay/compliance_routes.py` | CREATE — POST endpoint |
| `platform_v2/tools/repair_bay/__init__.py` | MODIFY — register new routes |
| `database/migrations/NNN_compliance_pipeline.sql` | CREATE — new table |
| `kso/routes/compliance_routes.py` | MODIFY — add submit hook + UI button |
| `platform_v2/tools/security_network/` (compliance routes) | MODIFY — add submit hook + UI button |
| `platform_v2/ai_bridge/agent_loop.py` | MODIFY — hook Code Health to submit |

---

## Out of Scope (follow-up)

- Real-time scan streaming to coordinator
- Cross-module rule deduplication beyond rule_id matching
- Tier 2: auto-remediation without human approval
