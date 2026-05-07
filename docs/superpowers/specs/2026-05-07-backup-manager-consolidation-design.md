# Backup Manager Consolidation Design

## Overview

Four improvements to the Backup Manager: wiring the ghost Deployment Backups tab, making Retention policy editable with W.A.R.D.E.N. visibility, making Deployment Package creation async, and adding a new Standalone Systems tab for backing up all 9 standalone products.

---

## Context

### Current tab inventory

| Tab | Status | Gap |
|-----|--------|-----|
| Backups | Complete | — |
| Module Backups | Functional | No auto-trigger |
| Hooks | Complete | — |
| Deployment Backups | Ghost | Repair Bay never calls the trigger |
| Retention | Minimal | GFS hardcoded, no W.A.R.D.E.N. panel |
| Deployment Packages | Underused | Synchronous create, no W.A.R.D.E.N. automation |
| External Storage | Functional | — |

### What's not changing
- Hooks tab — complete, leave alone
- Module Backups tab — functional, leave alone
- Backups tab — complete, leave alone
- External Storage tab — functional, leave alone

---

## Work Item 1 — Wire Deployment Backups

### Goal
The Deployment Backups tab exists and has a working route (`/api/deployment-backups`) but is always empty because Repair Bay never creates a pre-deploy snapshot.

### Design

**Trigger point**: `platform_v2/services/proposal_service.py` — the function that deploys a proposal. Before executing the deploy:

1. Call `create_backup_programmatic()` from `tools.backup_manager._shared` to create the snapshot. Capture the returned `backup_name`.
2. Insert a row into `improvement_deployments` with `backup_name`, `proposal_id`, `deployment_type`, `status='deploying'`. This is exactly what `get_deployment_backups()` queries — it selects `WHERE backup_name IS NOT NULL`.

```python
from tools.backup_manager._shared import create_backup_programmatic
backup_name = create_backup_programmatic(
    backup_type="pre_deploy",
    description=f"Pre-deploy snapshot for proposal #{proposal.id}"
)
# Insert into improvement_deployments so Deployment Backups tab shows it
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute(
        """INSERT INTO improvement_deployments
           (proposal_id, backup_name, deployment_type, status)
           VALUES (%s, %s, 'manual', 'deploying')""",
        (proposal.id, backup_name)
    )
```

**No migration needed** — `improvement_deployments` already has all required columns (`proposal_id`, `backup_name`, `deployment_type`, `status`, `health_check_passed`, etc.) and `backup_log.proposal_id` already exists from migration 375.

**W.A.R.D.E.N. role**: After the pre-deploy backup completes, W.A.R.D.E.N. verifies the checksum before allowing the deploy to proceed. If verification fails, the deploy is blocked and a Telegram alert fires.

**UI**: No changes needed — the tab already renders `improvement_deployments` rows correctly once data exists.

### Files to touch
- `platform_v2/services/proposal_service.py` — add pre-deploy backup + `improvement_deployments` insert
- `platform_v2/services/agent_jobs.py` — add W.A.R.D.E.N. verify step after pre-deploy backup

---

## Work Item 2 — Retention: Editable Policy + W.A.R.D.E.N. Panel

### Goal
GFS values (7 daily / 4 weekly / 6 monthly) are hardcoded in the Python backend. Make them editable via the UI and show W.A.R.D.E.N. agent activity in the tab.

### Design

**Config storage**: Add three keys to `system_config` table:
- `retention_daily` = 7
- `retention_weekly` = 4
- `retention_monthly` = 6

Seed via idempotent migration using `ON CONFLICT DO NOTHING`.

**Backend**: `routes_operations.py` `retention_status()` reads from `system_config` instead of constants. Add `PUT /retention-policy` endpoint that updates the three keys (admin only).

**W.A.R.D.E.N. job**: The existing `_run_warden_retention_prune()` job (Sundays 04:00) reads `retention_daily/weekly/monthly` from `system_config`. After each run, write a result record to `system_config`:
- `retention_last_run` = ISO timestamp
- `retention_last_deleted_count` = integer
- `retention_last_run_summary` = short text

**UI changes** in `backup_manager.html` Retention tab:
1. Replace static GFS number cards with editable `<input type="number">` fields + Save button
2. Add W.A.R.D.E.N. status panel below the GFS section:
   - Agent chip (name, status indicator)
   - Last prune: timestamp + "deleted N backups"
   - Next run: "Sunday 04:00 EDT"
   - Manual trigger button: "Run Now" → calls `POST /cleanup`

### Files to touch
- `database/migrations/NNN_retention_policy_config.sql` — seed 3 system_config keys
- `platform_v2/tools/backup_manager/routes_operations.py` — read from DB, add PUT endpoint
- `platform_v2/services/agent_jobs.py` — W.A.R.D.E.N. prune reads config, writes result
- `platform_v2/templates/tools/backup_manager.html` — Retention tab UI

---

## Work Item 3 — Deployment Packages: Async + W.A.R.D.E.N.

### Goal
`create_deployment_package()` runs synchronously. Large archives (800MB+) cause browser timeouts. Make it async using the existing `backup_download_jobs` pattern, and add W.A.R.D.E.N. auto-creation on version bump.

### Design

**Async create**: `POST /api/create-deployment-package` returns `{job_id, status: "queued"}` immediately. A background thread runs the actual tar.gz + DB dump. The client polls `GET /api/deployment-package-status/<job_id>` every 3 seconds.

Job state machine: `queued → building → ready → expired`

Store jobs in a new `deployment_package_jobs` table (id, package_name, status, progress_pct, error, created_at, completed_at).

**Progress reporting**: Background thread writes progress_pct at key steps:
- 10% — DB dump started
- 40% — DB dump complete
- 60% — code archive started
- 90% — code archive complete, packaging
- 100% — ready

**UI**: Replace synchronous "Create Package" button with async flow:
- Click → spinner + "Building package… 45%"
- On ready → "Download" button appears
- On error → red error message

**W.A.R.D.E.N. auto-create**: New agent job `_run_warden_package_on_version_bump()` runs nightly (03:30 EDT — offset from standalone backup job at 02:00 EDT). Checks if `system_config.platform_version` changed since the last deployment package `created_at`. If yes, triggers package creation via `create_backup_programmatic()`.

**W.A.R.D.E.N. status strip** at top of tab: last auto-package version + date, agent chip.

### Files to touch
- `database/migrations/NNN_deployment_package_jobs.sql` — new table
- `platform_v2/tools/backup_manager/routes_storage.py` — make create async, add status endpoint
- `platform_v2/services/agent_jobs.py` — add W.A.R.D.E.N. version-bump job
- `platform_v2/templates/tools/backup_manager.html` — async UI for Deployment Packages tab

---

## Work Item 4 — New: Standalone Systems Tab

### Goal
Add a new tab to backup all 9 standalone products (code + data), similar to Module Backups but for standalone products. Media Hub is config-only (no media library files).

### Standalone registry

| Product | Code path (hub) | DB schema | Backup type |
|---------|----------------|-----------|-------------|
| KBS | `/mnt/archie_brain/kytran-business-suite/` | `kbs` | code + schema |
| Media Hub | `/mnt/archie_brain/standalone/media_hub/` | `media_hub` | configs + schema only (no media files) |
| CREED | `/mnt/archie_brain/kytran-creed/` | `creed` | code + schema |
| KSO | `/mnt/archie_brain/kytran-server-manager/` | `kso` | code + schema |
| Gov Watch | `/mnt/standalone/kytran-gov-watch/` | `gov_watch` | code + schema |
| Civic Watch | `/mnt/standalone/kytran-civic-watch/` | `civic_watch` | code + schema |
| Legal Watch | `/mnt/standalone/kytran-legal-watch/` | `legal_watch` | code + schema |
| Market Watch | `/mnt/standalone/kytran-market-watch/` | `market_watch` | code + schema |
| WTF | `/mnt/archie_brain/what-the-fact/` | `wtf` | code + schema |

### Media Hub exception
Media Hub has `/mnt/Plex/` and `/mnt/data2/` mounts with terabytes of media files. The backup excludes all media library data entirely. What IS backed up:
- Source code: `/mnt/archie_brain/standalone/media_hub/` (Python files, templates, static)
- Config files: `docker-compose.yml`, `.env` at the standalone root
- `media_hub` Postgres schema — this contains service configuration (API keys, URLs), user watchlists, user preferences, and `media_hub_services` rows. It does NOT contain actual media files (those live in Plex/Jellyfin, not Postgres).

The tar.gz for Media Hub explicitly excludes: `media/`, `data/`, any path under `/mnt/Plex/`, `/mnt/data2/`, and any `*.mkv`, `*.mp4`, `*.avi` files.

### Design

**Standalone registry**: Hardcode the 9-product registry in `platform_v2/tools/backup_manager/_shared.py` as `STANDALONE_PRODUCTS` dict. Each entry has: `name`, `code_path`, `db_schema`, `backup_type` (`full` | `config_only`), `display_name`.

**Backup operation** per standalone:
1. `pg_dump -n <schema>` → `standalone_<name>_<timestamp>.sql`
2. `tar.gz` of code_path (Media Hub: exclude `media/`, `data/`, mounted volumes)
3. Store both in `/backups/standalones/<name>/`
4. Write metadata to `backup_log` with `backup_type='standalone'`, `standalone_name=<name>`

**New routes** in `routes_storage.py` (or new `routes_standalones.py`):
- `GET /api/standalones/list` — list all standalones with last backup info
- `POST /api/standalones/backup` — `{standalone_names: [...]}` — async, returns job_id
- `GET /api/standalones/backup-status/<job_id>` — poll progress
- `GET /api/standalones/history/<name>` — backup history for one standalone

**UI**: New tab "Standalone Systems" in the tab nav (after Module Backups).
- Same grid pattern as Module Backups: checkbox per standalone, name, backup type badge, last backup date (green/yellow/red age indicator), size
- "All" / "None" select buttons
- "Backup Selected" button → async job with progress
- Per-standalone "History" link → modal with last 10 backups
- Restore: modal with confirmation ("This will overwrite current code and database schema")

**W.A.R.D.E.N. automation**: New weekly job `_run_warden_standalone_backup()` (Wednesdays 02:00 EDT — offset from nightly version-bump job at 03:30 EDT) backs up all 9 standalones. Writes summary to `system_config` and sends Telegram report.

W.A.R.D.E.N. status panel at top of tab: last auto-backup date, count of standalones covered, agent chip.

### Files to touch
- `platform_v2/tools/backup_manager/_shared.py` — add `STANDALONE_PRODUCTS` registry
- `platform_v2/tools/backup_manager/routes_standalones.py` — new route file (4 endpoints)
- `platform_v2/tools/backup_manager/__init__.py` — register new route file
- `platform_v2/services/agent_jobs.py` — add W.A.R.D.E.N. standalone backup job
- `platform_v2/templates/tools/backup_manager.html` — new Standalone Systems tab
- `database/migrations/NNN_standalone_backup_log.sql` — ensure `backup_log` has `standalone_name` column

---

## W.A.R.D.E.N. Summary

W.A.R.D.E.N. (agent #363, Operations & Infrastructure, `qwen2.5:7b`) gains 3 new scheduled jobs:

| Job | Schedule | Action |
|-----|----------|--------|
| Pre-deploy verify | On every proposal deploy | Verify checksum of pre-deploy backup |
| Version-bump packager | Nightly 03:00 EDT | Auto-create deployment package if version changed |
| Standalone backup | Wednesdays 03:00 EDT | Full backup of all 9 standalones |

Existing jobs unchanged:
- Retention prune: Sundays 04:00 EDT (now reads editable GFS from `system_config`)
- Download cleanup: Daily 04:00 EDT

---

## Migration Plan

All DB changes are additive and idempotent. Execution order:

1. `NNN_add_proposal_id_to_backup_log.sql` — nullable column, no breakage
2. `NNN_retention_policy_config.sql` — `INSERT ... ON CONFLICT DO NOTHING`
3. `NNN_deployment_package_jobs.sql` — new table
4. `NNN_standalone_backup_log.sql` — nullable column on `backup_log`

---

## Known Issues to Address

### Issue A — DB/Filesystem drift (264 DB rows vs 31 disk dirs)

`backup_log` has 264 entries but only 31 backup directories exist on disk. The DB accumulated records for backups whose files were deleted (manually or by earlier cleanup runs) without the DB rows being removed.

**Impact**: The Backups tab stat card shows 264 total backups which is misleading — most of those files don't exist. The retention scanner correctly ignores DB-only entries (it reads the filesystem), but the UI presents a false picture.

**Fix**: When `cleanup_old_backups()` deletes a backup directory, it should also delete the corresponding `backup_log` row. Add a `DELETE FROM backup_log WHERE backup_name = %s` call in the cleanup path. For the existing orphan rows (264 - 31 = ~233), add a one-time cleanup route `POST /api/cleanup-orphan-log-entries` that removes `backup_log` rows where the backup directory no longer exists on disk.

**Files**: `platform_v2/tools/backup_manager/_shared.py` `cleanup_old_backups()` + `routes_admin.py` new orphan-cleanup endpoint.

---

### Issue B — Duplicate daily backups (daily + Daily_Triage both running every day)

Every day produces two backup directories:
```
20260506_060001_Daily_Triage
20260506_060001_daily
```

Two separate scheduled jobs are both creating full backups at 06:00 UTC daily. GFS counts these as two distinct backups, doubling daily storage consumption and consuming the "keep 7 daily" slots twice as fast.

**Fix**: Audit `agent_jobs.py` to identify both jobs. If they produce identical content, remove one. If `Daily_Triage` is a subset backup (e.g. DB only) and `daily` is a full backup, keep both but add a `backup_subtype` tag so GFS can treat them separately — or intentionally exclude `Daily_Triage` from retention counting since it's meant to be short-lived.

**Files**: `platform_v2/services/agent_jobs.py` — identify and reconcile the two daily backup jobs.

---

## What's NOT in scope

- Changing the existing Hooks, Module Backups, External Storage, or main Backups tabs
- Modifying the restore flow for regular backups
- Changing the 3-button quick-backup section (Brain Backup / Full Restore / Complete Archive)
- GDrive integration (existing gap, separate work item)
- VPS SSH-based backup (not needed — VPS standalones use hub Postgres)
