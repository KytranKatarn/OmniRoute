---
name: warden-agent
description: Use W.A.R.D.E.N. (agent #363) for admin operations tasks — user audits, backup verification, compliance checks, access reviews
---

# W.A.R.D.E.N. Agent

**Full name**: Watchful Administration, Resource Defense & Enforcement Node
**Agent ID**: 363 | **Department**: Operations & Infrastructure | **Model**: qwen2.5:7b
**Status**: Active | **Proficiency**: Lv4

---

## What W.A.R.D.E.N. Does

Autonomous guardian of admin operations. Runs scheduled and on-demand audits across the 4 admin modules:
- Account Center (users, invites, locked accounts, suspicious activity)
- Backup Manager (integrity checks, retention policy, age verification)
- Security Network (compliance scans, device audit, sinkhole health)
- System Operations (KSO compliance status, host health)

---

## Dispatch Capabilities

| Capability | Use for |
|---|---|
| `user_audit` | Audit user accounts — inactive, locked, orphaned, suspicious logins |
| `backup_verify` | Verify backup integrity — checksums, age, retention |
| `compliance_check` | Run compliance scans on any module |
| `account_management` | User role changes, invite cleanup, session review |
| `access_review` | Review HMAC access grants, API key usage, permission anomalies |
| `security` | General security checks (escalates to V.I.G.I.L. / S.H.I.E.L.D.) |

## How to Dispatch W.A.R.D.E.N.

```python
# Via MCP (Claude Code)
mcp__archie__delegate_task(
    capability='user_audit',
    reason='Weekly user account audit — check inactive and locked accounts',
    delegation_source='claude'
)

# Via dispatcher (Python)
from tools.department_hq.services.department_dispatcher import dispatch
result = dispatch(capability='backup_verify', prompt='Verify all backups from the last 7 days')
```

## Scheduled Jobs (add to department_hq/jobs.py)

```python
# Daily user audit — 03:00 EDT
@scheduler.scheduled_job('cron', hour=7, minute=0, timezone='America/Toronto', id='warden_user_audit')
def warden_user_audit():
    # Dispatch W.A.R.D.E.N. to check inactive users, locked accounts, expired invites
    dispatch(capability='user_audit', prompt='Run daily user account audit. Flag: inactive >30d, locked, expired invites.')

# Daily backup verify — 04:00 EDT
@scheduler.scheduled_job('cron', hour=8, minute=0, timezone='America/Toronto', id='warden_backup_verify')
def warden_backup_verify():
    dispatch(capability='backup_verify', prompt='Check last 24h backups: checksums, size, age. Alert if missing or failed.')

# Weekly compliance — Sunday 02:00 EDT
@scheduler.scheduled_job('cron', day_of_week='sun', hour=6, minute=0, timezone='America/Toronto', id='warden_compliance_check')
def warden_compliance_check():
    dispatch(capability='compliance_check', prompt='Run full compliance scan on account_center, security_network, backup_manager, system_operations. Report score changes.')
```

## Similar Agent: P.R.O.B.E.
P.R.O.B.E. (Platform Reliability, Observation, Browser-testing & Evaluation) runs QA test suites.
W.A.R.D.E.N. is the admin ops equivalent — it audits users, backups, and compliance.

Both follow the same pattern:
1. Agent has skills in `agent_skills` table
2. Capabilities mapped in `CAPABILITY_DEPARTMENT_MAP`
3. Scheduled jobs dispatch the agent via `dispatch(capability=..., prompt=...)`
4. Results land in `task_execution_log` + Telegram alert on failure

## Integrate with Admin Modules

W.A.R.D.E.N. can be triggered directly from the Account Center and Backup Manager UIs:
```javascript
// In account_center.js — "Run User Audit" button
async function runUserAudit() {
  const res = await api('POST', '/tools/department-hq/api/dispatch/delegate', {
    capability: 'user_audit',
    reason: 'Manual user audit triggered from Account Center',
    prompt: 'Audit all users: inactive, locked, suspicious activity in last 7 days'
  });
  showResult(res);
}
```
