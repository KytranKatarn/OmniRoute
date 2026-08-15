# Backup Manager Rules

## Module
- Route: `/tools/backup-manager` | Blueprint: `backup_manager_bp`
- Category: `admin_operations`
- Chat overlay: **W.A.R.D.E.N.** (#363) → `backup-manager-chat.js`
- All routes: `@admin_required`
- KB Docs: #264022 · #264472 (audit 2026-05-09)

## 10 Tabs

| Tab | Purpose |
|-----|---------|
| Backups | DB dump, Brain (archie-brain git), Full (all platform files) |
| Archive | Long-term compressed snapshots |
| Cloud | Google Drive AES-256-GCM encrypted uploads |
| External | USB storage sync |
| Deployment | Docker compose state + secrets backup |
| Modules | Per-module backup (36 modules) |
| Standalones | 9 standalone products |
| Hooks | Pre/post backup automation hooks |
| Retention | GFS policy management |
| Packages | Deployment package builder |

## GFS Retention Policy
- Per-(component, tier) GFS matrix — **source of truth: `RETENTION` dict in `scripts/backup/retention_prune.py`** (NOT a single 7/4/3 triple). Each cell is `(daily, weekly, monthly)` keep counts. For `database`: primary `(30,12,6)`, usb `(14,4,0)`, gdrive **`(2,1,1)`**, vps `(7,0,0)`. Tiers: primary / usb / gdrive / vps. ⚠️ **CORRECTED 2026-08-15** — this line said gdrive `(0,4,6)` for `database`; that is the **gitbundles** row. gdrive/database has been `(2,1,1)` since #5092 (the 15 GB free tier cannot hold 10 dumps). Read the dict, not this line.
- ⚠️ **A tier can have a POLICY and no PRUNER — check both.** `vps` was declared for all 10 components and the string `vps` appeared **nowhere else in the file**: no `prune_vps()`, no caller, never applied. outpost-us grew to 63 run dirs / 49 GB and hit **100% disk** on 2026-08-02, after which the 1.8 GB DB dump could not land while 20 MB gitbundles still fit (the per-component failure signature). Fixed by `prune_vps()` in **PR #2584 / #5616** — the same bug gdrive had pre-#5092. `test_every_tier_in_retention_has_a_pruner` now fails if any tier regresses to declared-but-unapplied.
- ⚠️ **Prune the off-site tiers by ARTIFACT, not by DIRECTORY.** `prune_dir()` selects with `comp_path.exists()`, which is unsafe on an rsync-fed tier: a FAILED sync leaves the component dir present and EMPTY. Measured 2026-08-15 — the 5 newest `database/` dirs on outpost-us were 4.0K/0 files while the last real 1.7 GB dump was 6 days old. A directory-based ladder keeps 5 empty folders and **deletes the only off-site DR copies**. `prune_vps()` selects on artifact presence and refuses to empty a component that still holds artifacts (guard scoped to NON-ZERO policies — `(0,0,0)` is a real instruction, it is how `code`/`volumes` stay off the outpost).
- **Single canonical engine (#4051): `scripts/backup/retention_prune.py`, run NIGHTLY by `scripts/backup_triage.sh` (cron 02:00).** It writes `system_config.retention_last_run`. The old inline "keep-14" prune in backup_triage.sh AND the weekly `backup_retention_prune` module job (agent_jobs.py, Sun 04:00, `cleanup_old_backups` 7d/4w/6m) are RETIRED — do not re-add a competing pruner. `--dry-run` previews deletions without deleting.
- ⚠️ **CORRECTION (2026-07-23, PRs #2437/#2438):** that "RETIRED" claim was FALSE — the 7/4/6 `cleanup_old_backups` pruner was STILL LIVE via **DHQ job #60 `agent_backup_retention_cleanup`** (`dept_hq/jobs.py`, **DAILY 07:00**, `dry_run=False`; it read `result['deleted_count']` but the fn returns `deleted` a LIST → reported 0 while deleting) AND the Retention tab's **Run Cleanup** button + no-op **Save Policy** editor. `/backups` is a **symlink → /mnt/data2/backups** — the SAME dir the canonical engine prunes — so two different policies fought over one directory. #2437 neutralised job #60 → no-op, made `/cleanup` + `/retention-policy` return **410**, and made the Retention tab **read-only + honest** (no editable policy, no manual cleanup). #2438: `warden_briefing.py` stopped surfacing the fake `delete_count`. **Retention is now 100% the nightly canonical engine.**
- **Backups vs Deployment tabs (2026-07-23, #2439/#2440):** pre-deploy snapshots (`notes LIKE 'Pre-deploy snapshot%'`) are excluded from the Backups `/list` — they belong to the **Deployment tab** (`improvement_deployments`). That tab's Restore button is now gated on a `snapshot_exists` flag (retention prunes the snapshot dir but leaves the deploy row → 86% were dead 404 buttons).
- Paths: `/backups/` AND `/mnt/data2/backups/` (both must be normalized — no trailing slash)
- `backup_locks` table prevents concurrent backup runs (lock timeout: 2 hours)

## DB Tables

| Table | Key columns |
|-------|-------------|
| **`backup_log`** ⭐ | `backup_type, file_path, size_bytes, status, tier, component, notes, git_commit, git_branch, triggered_by, build_number, platform_version, created_at` — **THE source of truth for backups.** `status` ∈ success / failed / partial / skipped / prune. `tier` ∈ primary / dr / usb / gdrive / vps (NULL on standalone rows) |
| `webhook_subscriptions` | `id, event_type, target_url, secret` |
| `deployment_package_jobs` | `id, status, manifest, created_at` |

### ⚠️ Two tables in this file were WRONG and cost a real outage (corrected 2026-07-20)

- **There is NO `backups` table.** `to_regclass('public.backups')` → NULL. W.A.R.D.E.N.'s "Daily Backup Integrity Check" queried it, threw `UndefinedTable` on every run, and its `except` swallowed the error — so backups were **unmonitored while appearing monitored**, and a 12h-stale restore point went unnoticed. Use `backup_log`.
- **There is NO `backup_locks` table.** Locking is a **FILE**: `/backups/.backup_lock`, JSON `{backup_name, created_by, timestamp, pid}`, `LOCK_TIMEOUT = 7200`. See `acquire_backup_lock` / `lock_owner_is_dead` in `_shared.py`.
- **`get_backup_db_cursor()` returns TUPLES, not dicts** (unlike the main `get_db_cursor()`, which is RealDictCursor). `row['col']` raises `TypeError: tuple indices must be integers`.

### Backup health — read `status`, never just recency
`backup_service.get_health_summary()` returns per tier: `age_hours`/`status` (newest row, **any** status — for the dashboard) **and** `last_success_age_hours` (newest `status='success'` — **the real restore point**). Anything gating on freshness MUST use `last_success_age_hours` via `backup_governance_service.gate_age_hours()`; a failed run also writes a `primary` row, so measuring recency alone certifies a backup that does not exist (#5013).
Alerting: `services/backup_posture_monitor.check_backup_posture()` — deterministic, no LLM, `send_system` with cooldowns.

## Standalone Schema Map

| Standalone | DB name |
|------------|---------|
| gov_watch | `gov_watch` |
| civic_watch | `civic_transparency` |
| wtf | `wtf` |
| kbs | Own DB (code-only backup) |
| media_hub | Own DB (code-only backup) |
| creed | Own DB (code-only backup) |
| kso | Own DB (code-only backup) |
| legal_watch | Own DB (code-only backup) |
| market_watch | Own DB (code-only backup) |

## Key Gotchas

- `get_backup_db_cursor(commit=True)` with lock timeout — always use this, not plain cursor
- Lock timeout is 2 hours — if a backup hangs, check `backup_locks` and manually release
- **Path normalization**: Both `/backups/` and `/mnt/data2/backups/` are valid; normalize before comparing
- **Google Drive**: AES-256-GCM encrypted; key lives in `.env` as `GDRIVE_ENCRYPTION_KEY`
- **Scheduler volumes**: `archie_scheduler` MUST mirror `archie_platform` volumes — missing `/mnt/standalone:ro` silently dropped Code Health by 35% (KB #263303)
- **W.A.R.D.E.N.** (#363, Operations & Infrastructure, qwen2.5:7b, Lv4) — autonomous guardian. Dispatch capabilities: `user_audit`, `backup_verify`, `compliance_check`, `account_management`, `access_review`

## W.A.R.D.E.N. Dispatch Pattern

```python
# Delegate backup verification:
mcp__archie__delegate_task(
    capability='backup_verify',
    reason='Verify last 7 days of backups are intact',
    delegation_source='claude'
)

# Known-tool shortcut:
mcp__archie__run_backup()  # triggers immediate backup cycle
```
