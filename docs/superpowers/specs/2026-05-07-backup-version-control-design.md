# Backup System v2 — Version Control, Safe Restore & Deployment Triad
**Date:** 2026-05-07
**Status:** Approved
**Owner:** W.A.R.D.E.N. (restore + backup) · F.O.R.G.E. (code gate) · C.O.D.E.X. (docs gate) · P.R.O.B.E. (QA)
**Coordination:** A.R.C.H.I.E. (COO) via Department HQ orchestration

---

## Context

The Backup Manager has three broken buttons (500 error on creation), no git version tracking on backups, no visible restore UI, and `backup_log` is never updated when backups are created. This spec delivers a complete redesign: fix the bugs, add version tracking, build a two-stage safe restore, and establish the **Deployment Triad** as the governance layer for all platform changes.

---

## The Deployment Triad

Every change to the platform — by Repair Bay, Claude CLI, ARCHIE agents, or Kytran — passes through three existing agents:

| Agent | Department | Gate |
|-------|-----------|------|
| **F.O.R.G.E.** | Engineering & Technology | PR exists on GitHub? Code reviewed? No secrets? |
| **W.A.R.D.E.N.** | Operations & Infrastructure | Valid backup exists? Module snapshot taken? |
| **C.O.D.E.X.** | Documentation & Knowledge | Changes documented? KB entry created? PR notes complete? |

### Communication hierarchy

```
Repair Bay / Claude CLI / ARCHIE agents
          ↓
    [TRIAD GATE]
    F.O.R.G.E. · W.A.R.D.E.N. · C.O.D.E.X.
          ↓ report up ↓
     A.R.C.H.I.E. — COO co-owner
   (autonomous on routine; judgment on critical)
          ↓ advises ↓
     Kytran — Owner
   (approves major structural changes)
```

**A.R.C.H.I.E. authority tiers:**
- **Always autonomous:** routine deploys, minor updates, scheduled jobs
- **Advisory (informs only):** service restarts, new agent deployed, PR batch merged
- **COO judgment (sleep window):** if Kytran unavailable, A.R.C.H.I.E. acts on critical issues, documents everything, full report on wake

---

## Part 1 — Bug Fixes (immediate)

### 1.1 Fix the 3 backup creation buttons

**Root cause:** `backup_database_python()` crashes with "year 58317 is out of range" — a datetime overflow in the SQL dump generation when iterating over DB rows. The code calls `.isoformat()` or `.strftime()` on a value that produces an out-of-range year.

**Fix:** Wrap all datetime serialization in `backup_database_python()` in a `try/except`, skipping or casting invalid datetimes. Also fix all `.isoformat()` and `.strftime()` calls in backup creation to use `try/except ValueError`.

**Each button's scope:**
- **Full Backup:** 11 components (DB + platform + docs + ai_bridge + migrations + n8n + scripts + nginx + env + logs + conversation_logs). ~100-200 MB.
- **Critical Backup:** 4 components (DB + platform + docs + env). ~30-50 MB.
- **Database Backup:** 1 component (SQL dump). ~5-20 MB.

### 1.2 Fix backup_log INSERT on creation

**Root cause:** `api_create_backup()` writes `metadata.json` to filesystem but never INSERTs into `backup_log`. The list endpoint now reads from `backup_log` (fixed in Phase 1 earlier), so new backups are invisible.

**Fix:** After successful backup creation, INSERT a row into `backup_log` with: `backup_type`, `file_path`, `size_bytes`, `status='success'`, `tier='primary'`, `component`, `notes` (includes description, build_number, git_commit, triggered_by).

---

## Part 2 — Version Tracking

### 2.1 New columns on backup_log

Migration 373:

```sql
ALTER TABLE backup_log
  ADD COLUMN IF NOT EXISTS git_commit TEXT,
  ADD COLUMN IF NOT EXISTS git_branch TEXT,
  ADD COLUMN IF NOT EXISTS platform_version TEXT,
  ADD COLUMN IF NOT EXISTS triggered_by TEXT,       -- 'repair_bay' | 'manual' | 'schedule' | 'warden'
  ADD COLUMN IF NOT EXISTS proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS pr_number INTEGER;
```

### 2.2 Capture git context at backup time

In `api_create_backup()`, before the backup runs:
```python
import subprocess
git_commit = subprocess.run(['git', '-C', '/app', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
git_branch = subprocess.run(['git', '-C', '/app', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
platform_version = get_platform_version()  # reads from version file or DB
```

Store these in `backup_log` row and in `metadata.json`.

### 2.3 Backup row UI — three visible fields

Every backup row in the Backups tab shows:
```
Build #54  ·  commit abc123f  ·  PR #557  ·  Repair Bay auto-deploy  ·  May 6, 11:02 PM
[🧪 Test Restore]  [⬇ Restore Live — locked until QA passes]
```

"Restore Live" button is **disabled/hidden** until P.R.O.B.E. QA passes on the sandbox restore.

---

## Part 3 — Two-Stage Safe Restore

### 3.1 Flow (via Department HQ dispatch queue)

```
User or A.R.C.H.I.E. clicks "Test Restore" on a backup row
  → delegate_task(capability='restore_sandbox', args={backup_id})
  → W.A.R.D.E.N. claims task:
      1. Verify checksum
      2. Provision sandbox via SandboxManager (platform_v2/sandbox_manager.py — same class Repair Bay uses, schema-separation mode)
      3. Restore DB tables to sandbox schema + copy files to sandbox directory
      4. Report sandbox URL
  → delegate_task(capability='qa_sandbox_restore', args={sandbox_url, backup_id})
  → P.R.O.B.E. claims task:
      1. Run backup-health-smoke suite against sandbox
      2. Run targeted module QA (Repair Bay spec)
      3. Check page loads, auth, API responses
      4. Report: pass/fail + details
  → If PASS:
      "Restore Live" button unlocks in Backup Manager UI
      A.R.C.H.I.E. advisory: "Sandbox verified. Restore Live is available."
  → If FAIL:
      Issues listed. Sandbox discarded. Try earlier backup.

User clicks "Restore Live":
  → delegate_task(capability='restore_production', args={backup_id, sandbox_verified=True})
  → W.A.R.D.E.N. claims task:
      1. Pre-restore backup of current production state (safety net)
      2. Apply restore to production
      3. Tag version: "Restored to Build #54"
  → C.O.D.E.X. auto-logs: who triggered, which backup, QA results, timestamp
  → A.R.C.H.I.E. Telegram: "✅ Restore complete. Platform is now Build #54."
```

### 3.2 New W.A.R.D.E.N. skills

Add to `agent_skills` for agent id=363:
- `restore_sandbox` — Lv4
- `restore_production` — Lv5 (high authority)
- `restore_verify` — Lv4

Add to `CAPABILITY_DEPARTMENT_MAP`:
- `restore_sandbox` → Operations & Infrastructure
- `restore_production` → Operations & Infrastructure
- `restore_verify` → Operations & Infrastructure

### 3.3 New P.R.O.B.E. skill

Add to `agent_skills` for P.R.O.B.E.:
- `qa_sandbox_restore` — Lv5

Add to `CAPABILITY_DEPARTMENT_MAP`:
- `qa_sandbox_restore` → Engineering & Technology

---

## Part 4 — F.O.R.G.E. Code Gate

F.O.R.G.E. (Engineering) gains a `pr_gate` skill. Before any Repair Bay deploy:

```python
delegate_task(capability='pr_gate', args={
    'proposal_id': proposal_id,
    'git_commit': current_commit,
})
```

F.O.R.G.E. checks:
1. Does a merged PR exist for this commit on GitHub?
2. Is the branch protection satisfied?
3. No secrets in the diff (V.I.G.I.L. can assist)?

Returns `{approved: bool, pr_number: int|None, reason: str}`.

**Gate config:** Same severity model as W.A.R.D.E.N. governance — critical=soft, medium=hard.

---

## Part 5 — C.O.D.E.X. Documentation Gate

C.O.D.E.X. (Documentation & Knowledge) gains a `doc_gate` skill. After every successful deploy:

```python
delegate_task(capability='doc_gate', args={
    'module': module_name,
    'pr_number': pr_number,
    'changes_summary': changes_summary,
})
```

C.O.D.E.X. auto-creates:
1. KB vault_note for the change (module + what changed + PR link)
2. Updates module capability index if relevant
3. Flags if PR description is empty/inadequate

This is non-blocking (soft gate) — C.O.D.E.X. documents and advises, does not block deploys.

---

## Part 6 — A.R.C.H.I.E. Briefing Layer

A.R.C.H.I.E. sends three tiers of Telegram messages:

**Morning briefing (daily, automated):**
```
🤖 A.R.C.H.I.E. — Morning Briefing
Platform v5.34.0 · Build #55 · Backup ✅ 6h ago
3 PRs merged. W.A.R.D.E.N.: all tiers healthy. C.O.D.E.X.: 4 KB entries. No incidents.
```

**Advisory (immediate, no approval needed):**
```
⚠️ A.R.C.H.I.E. — Advisory
Repair Bay deploying fix for account_center in 5 min.
W.A.R.D.E.N. pre-snapshot ✅ · F.O.R.G.E. PR #559 approved ✅
No action needed.
```

**Approval required:**
```
🚨 A.R.C.H.I.E. — Approval Required
DB migration requires platform restart. ~90s downtime.
[✅ Approve] [❌ Deny] [⏰ Schedule 2 AM]
```

**Sleep window (Kytran unavailable):** A.R.C.H.I.E. uses COO judgment, acts, full report on wake.

---

## Implementation Order

```
Phase A — Bug Fixes (1-2 days, highest priority)
  ├── Fix datetime overflow in backup_database_python()
  ├── Fix backup_log INSERT on creation
  └── Migration 373 (git_commit, triggered_by, pr_number columns)

Phase B — Version Tracking UI (1-2 days)
  ├── Capture git context at backup time
  └── Update backup row UI (commit · actor · restore buttons)

Phase C — Two-Stage Restore (3-4 days)
  ├── W.A.R.D.E.N. restore_sandbox + restore_production skills
  ├── P.R.O.B.E. qa_sandbox_restore skill
  ├── Sandbox restore flow wired through Department HQ
  └── "Restore Live" conditional unlock after QA pass

Phase D — Deployment Triad (2-3 days)
  ├── F.O.R.G.E. pr_gate skill + check in proposal_service
  ├── C.O.D.E.X. doc_gate skill (soft gate, auto-documents)
  └── A.R.C.H.I.E. briefing Telegram templates (3 tiers)
```

**Total: 7-11 days**

---

## Future Sessions (saved for later)

- **archie.kytranempowerment.com redesign** — make it an interactive live command center reflecting A.R.C.H.I.E.'s COO role (KB #264018)
- **Consciousness module evolution** — how A.R.C.H.I.E. develops judgment over time, feedback loop from decision history
- **V.I.G.I.L. integration** in F.O.R.G.E. code gate — secret scanning, security review of diffs
