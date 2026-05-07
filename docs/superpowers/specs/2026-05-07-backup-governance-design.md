# Backup Governance — Full System Design
**Date:** 2026-05-07
**Status:** Approved
**Owner:** W.A.R.D.E.N. (Operations & Infrastructure) + P.R.O.B.E. (Engineering)
**Tasks:** #2699 (routes split), follow-ups created below

---

## Context

The Backup Manager module (`platform_v2/tools/backup_manager/`) is a 5,029 LOC monolith with 40 endpoints in one file. Secondary backup tiers (GDrive, VPS, USB) have been stale for 20 days. The UI shows empty lists despite 174 successful runs in `backup_log`. There is no pre-deploy backup gate — the Repair Bay can deploy changes without confirming backups exist.

This design delivers three coordinated phases:
1. **Operational Fix** — stop the bleeding, fix the UI, restore secondary tiers
2. **Code Quality** — split the monolith, extract service layer, add module snapshot foundation
3. **Agent Governance** — W.A.R.D.E.N. becomes backup authority, P.R.O.B.E. requests clearance before every Repair Bay deploy

---

## Phase 1 — Operational Fix

### Goal
All backup tabs show real data. Secondary tiers (GDrive, VPS, USB) running again. 27.5% failure rate diagnosed and resolved. QA suite green.

### 1.1 UI Bug Fixes

**Backup list tab shows empty** despite 174 successful `backup_log` rows. Root cause: likely a mis-matched column name, broken query, or wrong status filter in `backup_manager_routes.py`. Fix: read the actual query, verify against `backup_log` schema, ensure list endpoint returns rows.

**Secondary tabs (Cloud, External, Deployment):** Each tab has a query that fetches tier-specific records. Audit each query against the DB schema. Fix column names, filters, and default time windows.

**Deployment/Packages tab:** Accumulating stale build packages. Add a retention policy (keep last N by date) and a "Prune old packages" button. Show only packages from the last 30 days by default.

**Hooks tab:** Audit pre/post hook wiring. Add `last_run`, `last_exit_code`, and `last_output` to the hooks tab so operators can see hook health at a glance.

### 1.2 Secondary Tier Diagnosis & Fix

GDrive, VPS, and USB last ran 2026-04-17 — 20 days stale. Investigation targets:
- GDrive: token expiry, passphrase mismatch, or gdrive_service.py path error
- VPS: SSH key or host connectivity failure
- USB: mount point missing or path changed

Fix sequence: diagnose via `backup_log.error_message` for the last failed runs → resolve root cause → trigger manual run for each tier → confirm success in `backup_log`.

### 1.3 QA Suite — `backup-health-smoke.yaml`

Suite id registered in `qa_test_suites`, type=internal. P.R.O.B.E. runs this after every Repair Bay deploy.

Tests:
- `GET /tools/backup-manager` — page loads (auth-gated)
- `GET /api/backup/health` — returns 200, `status` field present
- `GET /api/backup/list` — returns 200, array not null
- `GET /api/backup/verify` — returns 200 or 202
- `GET /api/compliance/badge/backup.svg` — returns 200 (SVG)
- `GET /api/backup/retention` — returns 200
- `GET /api/webhooks` — returns 200, array present

### 1.4 Success Criteria
- [ ] All 6 Backup Manager tabs render real data
- [ ] GDrive, VPS, USB each have a successful run after the fix
- [ ] `backup-health-smoke.yaml` green (all tests pass)
- [ ] Failure rate below 10% after tier fixes

---

## Phase 2 — Code Quality + Module Snapshot Foundation

### Goal
5,029 LOC monolith split into 5 focused route files. `backup_service.py` extracted for direct Python calls. Manual module snapshots working end-to-end.

### 2.1 Routes Split

`backup_manager_routes.py` (5,029 LOC) → 5 files, registered via `register_*_routes(bp, admin_required)` pattern:

| File | Responsibility | Key Endpoints |
|------|---------------|---------------|
| `routes_operations.py` | Create, list, status, health | `/api/backup/create`, `/api/backup/list`, `/api/backup/health` |
| `routes_restore.py` | Restore, preview, component restore | `/api/backup/restore`, `/api/backup/preview` |
| `routes_webhooks.py` | Webhook CRUD, trigger, history | `/api/webhooks`, `/api/webhooks/trigger` |
| `routes_storage.py` | GDrive, external USB, encryption, packages | `/api/gdrive/*`, `/api/external/*`, `/api/packages/*` |
| `routes_admin.py` | Hooks, retention, audit log, config | `/api/hooks/*`, `/api/retention`, `/api/audit-log` |

`__init__.py` calls all 5 `register_*_routes()` functions. The old `backup_manager_routes.py` is deleted after all routes are migrated and verified.

### 2.2 Service Extraction — `backup_service.py`

Business logic extracted from routes into a service callable without Flask context. Used by W.A.R.D.E.N., the scheduler, and Phase 3 governance:

```python
create_backup(tier, components, triggered_by) -> BackupResult
verify_integrity(backup_id) -> VerifyResult
get_health_summary() -> HealthSummary
run_retention(policy) -> RetentionResult
snapshot_module(module_name, trigger_source, backup_id) -> SnapshotResult
```

No route handler contains more than 50 lines of business logic after extraction.

### 2.3 Module Snapshot Foundation

New DB table `module_snapshots`:

```sql
CREATE TABLE module_snapshots (
    id              SERIAL PRIMARY KEY,
    module_name     TEXT NOT NULL,
    snapshot_type   TEXT NOT NULL CHECK (snapshot_type IN ('auto', 'manual', 'pre_deploy')),
    trigger_source  TEXT NOT NULL,  -- 'repair_bay' | 'manual' | 'schedule'
    file_paths      JSONB DEFAULT '[]',
    db_tables       JSONB DEFAULT '[]',
    backup_id       INTEGER REFERENCES backup_log(id),
    clearance_task_id INTEGER,       -- unified_tasks.id for the governance task (Phase 3)
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Two snapshot types wired:
- **Manual**: "Checkpoint module" button in Backup Manager UI → `backup_service.snapshot_module(type='manual')`
- **Pre-deploy stub**: `backup_service.snapshot_module(type='pre_deploy', trigger_source='repair_bay')` — callable from Phase 3, returns snapshot_id

### 2.4 Success Criteria
- [ ] All 5 route files register cleanly, no endpoint regressions
- [ ] `backup_service.py` callable from a Python script without Flask context
- [ ] Manual module snapshot creates a row in `module_snapshots`
- [ ] `backup-health-smoke.yaml` still green after split

---

## Phase 3 — W.A.R.D.E.N. ↔ P.R.O.B.E. Governance

### Goal
W.A.R.D.E.N. is the backup authority. P.R.O.B.E. cannot run a Repair Bay deploy without W.A.R.D.E.N.'s clearance. Module snapshots are automatic before every deploy. Severity gates are configurable.

### 3.1 Backup Governance Service

New `platform_v2/services/backup_governance_service.py` owned by W.A.R.D.E.N.:

```python
def request_deploy_clearance(
    module: str,
    severity: str,          # 'critical' | 'high' | 'medium' | 'low'
    triggered_by: str = 'probe',
) -> ClearanceResult:
    """
    1. Load severity gate config from system_config
    2. Check backup recency (latest backup_log success within window)
    3. Auto-snapshot the module via backup_service.snapshot_module()
    4. Verify snapshot checksum
    5. Return approved=True + snapshot_id, or approved=False + reason
    """
```

`ClearanceResult` fields: `approved`, `snapshot_id`, `gate_level`, `reason`, `backup_age_hours`, `expires_at`

### 3.2 Severity Gate Configuration

Stored in `system_config` table, editable via Backup Manager → Admin tab:

| Severity | Backup Age Limit | Gate Type | Override Path |
|----------|-----------------|-----------|---------------|
| critical | 48h | soft — warn + proceed | none needed |
| high | 12h | soft — warn + Telegram | A.R.C.H.I.E. Telegram approval |
| medium | 6h | hard — block | Kytran approves via Telegram |
| low | 24h | hard — block | Kytran approves via Telegram |

Gate config key: `backup_governance_gates` (JSONB in system_config).

### 3.3 Coordination Protocol

Uses the existing `delegate_task` infrastructure (Project #276):

```
Repair Bay (P.R.O.B.E.) about to deploy:
  1. proposal_service.py calls backup_governance_service.request_deploy_clearance()
  2. OR: delegate_task(capability='backup_verify',
                       args={module, severity, proposal_id},
                       reason='Pre-deploy clearance request')
  3. W.A.R.D.E.N. claims task via delegate_task_worker
  4. W.A.R.D.E.N. runs governance check + auto-snapshot
  5. W.A.R.D.E.N. writes {approved, snapshot_id, reason} to unified_tasks.metadata
  6. Repair Bay reads clearance from task metadata before sandbox_manager executes
  7. On denial: Telegram alert → A.R.C.H.I.E. → escalates to Kytran
```

For synchronous deploys (non-async path), `request_deploy_clearance()` is called directly — no delegation needed. For async scheduled deploys, delegation is used.

### 3.4 Repair Bay Integration

**`proposal_service.py`** — add before `_deploy_to_sandbox()`:
```python
clearance = backup_governance_service.request_deploy_clearance(
    module=proposal.module_name,
    severity=proposal.severity,
)
if not clearance.approved:
    _handle_denied_clearance(proposal, clearance)
    return  # blocked
```

**`sandbox_manager.py`** — check `clearance_id` present in proposal metadata before executing.

**Repair Bay proposals table** — add `backup_clearance_id` column, `backup_snapshot_id` column. Both shown in Repair Bay UI as "Pre-deploy backup: ✅ snapshot_id" or "⚠️ waived (critical severity)".

### 3.5 W.A.R.D.E.N. Skill Upgrade

Add `backup_governance` skill to W.A.R.D.E.N. at Lv5:
```sql
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES (363, 'backup_governance', 5, NULL);
```

Add `backup_governance` to `CAPABILITY_DEPARTMENT_MAP` → Operations & Infrastructure.

### 3.6 QA Suite — `backup-governance-e2e.yaml`

Tests:
- Clearance request returns approved for healthy backup + correct severity
- Clearance request denied when backup exceeds age limit (medium severity, 6h+ old)
- Module snapshot created and has valid checksum
- Soft gate (critical severity) proceeds despite stale backup
- Hard gate (low severity) blocks when backup stale
- Repair Bay proposal blocked when clearance denied

### 3.7 Follow-Up Tasks (Dev HQ)

The following tasks are created at spec time to ensure nothing is forgotten:

1. **Audit Repair Bay full workflow** — review all steps in `proposal_service.py` and `sandbox_manager.py` for any other pre-deploy gates needed
2. **P.R.O.B.E. job audit** — verify P.R.O.B.E.'s scheduled jobs acknowledge backup systems
3. **`CAPABILITY_DEPARTMENT_MAP` update** — add `backup_governance` → Operations & Infrastructure
4. **W.A.R.D.E.N. skill upgrade** — add `backup_governance` Lv5
5. **Repair Bay UI update** — show backup clearance status on each proposal card
6. **Severity config UI** — editable gate config in Backup Manager Admin tab
7. **Telegram escalation template** — W.A.R.D.E.N. denial message format for A.R.C.H.I.E.

### 3.8 Success Criteria
- [ ] P.R.O.B.E. cannot deploy without W.A.R.D.E.N. clearance (medium/low severity)
- [ ] Module snapshot created automatically before every deploy
- [ ] Severity gate config editable without code change
- [ ] Telegram alert fires on every denial
- [ ] `backup-governance-e2e.yaml` green

---

## Agent Assignments

| Agent | Role | Phase |
|-------|------|-------|
| W.A.R.D.E.N. (id=363) | Backup authority, governance service, snapshot owner | 1, 2, 3 |
| P.R.O.B.E. | Repair Bay integration, QA suite execution | 1, 3 |
| F.O.R.G.E. | Routes split, service extraction, code quality | 2 |
| A.R.C.H.I.E. | Telegram escalation relay, Kytran approval gating | 3 |

---

## Phased Delivery Order

```
Phase 1 (Operational — 2-3 days)
  ├── Fix backup list UI query
  ├── Diagnose + fix secondary tier failures
  ├── Deployment/packages cleanup
  ├── Hooks tab audit
  └── backup-health-smoke.yaml QA suite

Phase 2 (Code Quality — 3-4 days)
  ├── Split backup_manager_routes.py → 5 files
  ├── Extract backup_service.py
  ├── module_snapshots table + migration
  ├── Manual snapshot UI button
  └── Verify no regressions

Phase 3 (Governance — 3-4 days)
  ├── backup_governance_service.py
  ├── Severity gate config in system_config
  ├── delegate_task coordination protocol
  ├── Repair Bay proposal_service integration
  ├── sandbox_manager clearance check
  ├── W.A.R.D.E.N. skill upgrade
  ├── Repair Bay UI clearance column
  ├── backup-governance-e2e.yaml QA suite
  └── Create 7 follow-up Dev HQ tasks
```

**Total estimated effort:** 8-11 days
