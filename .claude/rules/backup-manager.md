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
- 7 daily / 4 weekly / 3 monthly
- Job #60: auto-cleanup at 07:00 AM
- Paths: `/backups/` AND `/mnt/data2/backups/` (both must be normalized — no trailing slash)
- `backup_locks` table prevents concurrent backup runs (lock timeout: 2 hours)

## DB Tables

| Table | Key columns |
|-------|-------------|
| `backups` | `id, backup_type, status, file_path, size_bytes, created_at` |
| `backup_locks` | `id, lock_type, locked_at, expires_at` |
| `webhook_subscriptions` | `id, event_type, target_url, secret` |
| `backup_log` | `id, backup_id, message, level, created_at` |
| `deployment_package_jobs` | `id, status, manifest, created_at` |

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
