---
name: admin-backup-manager
description: Work on Backup Manager — DB dumps, file snapshots, config exports, scheduled retention, restore, external USB sync
---

# Backup Manager Module

**Path**: `platform_v2/tools/backup_manager/` | **URL**: `/tools/backup-manager`
**KB Docs**: #263993 (full user + developer guide)

## Tabs
Overview → Backups → Schedule → Restore → Storage → Settings

## Key File
`backup_manager_routes.py` — ALL logic in one file (5030 lines — known large file, split is a pending task)

## Key Tables
```sql
backups              — type, status, file_path, checksum (SHA256), size_bytes, created_at
backup_locks         — advisory lock (2h timeout, prevents concurrent runs)
webhook_subscriptions — completion webhook endpoints
```

## Backup Process Pattern
```python
# Lock → dump → checksum → record → webhook → (optional) USB sync
with get_backup_db_cursor(commit=True) as (conn, cur):
    # 1. Acquire advisory lock (fails if another backup running)
    # 2. pg_dump with compression
    # 3. SHA256 checksum
    # 4. INSERT into backups table
    # 5. Fire webhooks if configured
    # 6. rsync to /mnt/usb_backup if mounted
```

## Backup Types
- `database` — pg_dump gzip compressed
- `files` — platform code + static assets
- `config` — .env, docker-compose.yml, nginx configs
- `full` — all three combined

## Restore API
```
POST /api/backup/restore/<id>
Body: {components: ["database", "files", "config"]}  # subset restore supported
```

## Pre/Post Hooks
```python
# Stored in system_config as JSON
# Pre: run before backup (e.g. enable maintenance mode)
# Post: run after completion (e.g. sync to S3, send alert)
```

## Auth Pattern
All routes: `@admin_required` (no `@login_required` needed — admin implies logged in)

## Known Gaps (Do Not Duplicate)
- GDrive upload: `gdrive_crypto.py` exists but UI not wired — Task #pending
- Incremental backups: not implemented — full dumps only
- 2h lock is hardcoded in `backup_manager_routes.py`

## QA
Suite #19 — **23/23 passed** (2026-05-06)
Code health: ✅ completed, 0 red issues

## Common Tasks
- **Check last backup status**: query `backups` table, `status` column
- **Force unlock**: DELETE from `backup_locks` (use only if backup is truly stuck)
- **Add a webhook**: POST `/api/backup/webhooks` with `{url, events: ["complete", "fail"]}`
- **Debug restore failure**: check `backups.file_path` exists + checksum matches
