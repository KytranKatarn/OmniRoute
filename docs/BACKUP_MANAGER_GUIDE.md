# A.R.C.H.I.E. Backup Manager Guide

## Overview

The Backup Manager provides comprehensive backup and restore functionality for the A.R.C.H.I.E. platform. It supports full platform backups, selective backups (critical/database-only), custom component selection, and module-level backups for isolated sandbox testing.

**Last Updated**: 2026-01-15
**Module Location**: `/mnt/archie_brain/platform_v2/tools/backup_manager/`
**Components Backed Up**: 11 (database, platform, documentation, ai_bridge, migrations, n8n_workflows, n8n_persistence, scripts, nginx, environment, conversation_logs)

---

## Quick Start

### Programmatic Usage

```python
from tools.backup_manager import create_backup_programmatic, backup_module

# Full platform backup (all 11 components)
result = create_backup_programmatic(
    description='pre_improvement_45',
    created_by_username='admin',
    proposal_id=45
)
# Returns: {'success': True, 'backup_name': '...', 'build_number': 23, ...}

# Module-only backup (for sandbox testing)
result = backup_module('improvements', proposal_id=45)

# Get module dependencies
from tools.backup_manager import get_module_dependencies
deps = get_module_dependencies('improvements')
```

### API Endpoints

All endpoints require admin authentication.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/backup-manager/` | GET | Main UI page |
| `/tools/backup-manager/list` | GET | List all backups (includes current_build) |
| `/tools/backup-manager/create` | POST | Create backup (supports backup_type) |
| `/tools/backup-manager/restore/<name>` | POST | Restore full backup |
| `/tools/backup-manager/download/<name>` | GET | Download as tar.gz |
| `/tools/backup-manager/delete/<name>` | DELETE | Delete backup |
| `/tools/backup-manager/current-build` | GET | Get current build number |
| `/tools/backup-manager/set-current/<num>` | POST | Set current build number |
| `/tools/backup-manager/deploy-to-sandbox` | POST | Deploy backup to sandbox |
| `/tools/backup-manager/backup-module` | POST | Backup single module |
| `/tools/backup-manager/restore-module/<name>` | POST | Restore module backup |
| `/tools/backup-manager/modules/list` | GET | List module backups |
| `/tools/backup-manager/modules/available` | GET | List all available modules |
| `/tools/backup-manager/module-dependencies/<name>` | GET | Get module files |
| `/tools/backup-manager/retention-status` | GET | Show retention policy status |
| `/tools/backup-manager/cleanup` | POST | Delete old backups (dry_run default) |
| `/tools/backup-manager/storage-stats` | GET | Get storage statistics |
| `/tools/backup-manager/verify-modules` | GET | Verify all modules are backed up |

---

## Backup Types

### 1. Full Platform Backup (Default)

Creates a complete backup of all 11 components with auto-assigned build number.

**Components:**
- `database` - PostgreSQL dump (all tables)
- `platform` - Platform code (`/mnt/archie_brain/platform_v2/`)
- `documentation` - Docs (`/mnt/archie_brain/docs/`)
- `ai_bridge` - AI integration code
- `migrations` - Database migrations (`/mnt/archie_brain/database/migrations/`)
- `n8n_workflows` - n8n workflow definitions
- `n8n_persistence` - n8n runtime data
- `scripts` - Deployment scripts
- `nginx` - Nginx configuration
- `environment` - Root docker-compose.yml
- `conversation_logs` - Claude Code hook transcripts

**Usage:**
```bash
curl -X POST http://localhost:3000/tools/backup-manager/create \
  -H "Content-Type: application/json" \
  -d '{"backup_type": "full", "description": "Full platform backup"}'
```

### 2. Critical-Only Backup

Backs up only essential components for quick recovery.

**Components:** database, platform, documentation, environment

```bash
curl -X POST http://localhost:3000/tools/backup-manager/create \
  -H "Content-Type: application/json" \
  -d '{"backup_type": "critical", "description": "Critical components only"}'
```

### 3. Database-Only Backup

Backs up only the PostgreSQL database.

```bash
curl -X POST http://localhost:3000/tools/backup-manager/create \
  -H "Content-Type: application/json" \
  -d '{"backup_type": "database", "description": "Database snapshot"}'
```

### 4. Custom Backup

Select specific components to backup.

```bash
curl -X POST http://localhost:3000/tools/backup-manager/create \
  -H "Content-Type: application/json" \
  -d '{
    "backup_type": "custom",
    "components": ["database", "platform", "ai_bridge"],
    "description": "Custom selection"
  }'
```

### 5. Module-Level Backup

Creates a targeted backup of individual modules for sandbox testing.

```bash
curl -X POST http://localhost:3000/tools/backup-manager/backup-module \
  -H "Content-Type: application/json" \
  -d '{"module_name": "improvements", "proposal_id": 45}'
```

---

## Build Numbers

Each backup is automatically assigned a sequential build number. The current build number tracks which backup represents the "deployed" state.

### Get Current Build
```bash
curl http://localhost:3000/tools/backup-manager/current-build
# Returns: {"success": true, "current_build": 23}
```

### Set Current Build
```bash
curl -X POST http://localhost:3000/tools/backup-manager/set-current/23
```

### Build Number in UI
- Displayed in backup list as "Build #23"
- Current build highlighted with green badge
- "SET CURRENT" button to mark a backup as deployed

---

## Directory Structure

### Full Backups
```
/mnt/archie_brain/backups/
├── 20260115_171131_Full_backup_all_11_components/
│   ├── database.sql                    # Full PostgreSQL dump (~46MB)
│   ├── platform_v2/                    # Platform code
│   │   ├── tools/                      # All 48+ modules
│   │   ├── templates/
│   │   ├── static/
│   │   ├── consciousness/
│   │   ├── migrations/
│   │   ├── app.py
│   │   ├── config.py
│   │   ├── module_registry.py
│   │   ├── rbac.py
│   │   ├── requirements.txt
│   │   └── .env
│   ├── ai_bridge/                      # AI integration (44 files)
│   ├── docs/                           # Documentation (56+ files)
│   ├── database/migrations/            # SQL migrations (10 files)
│   ├── n8n_workflows/                  # n8n automation (4 files)
│   ├── persistence/n8n/                # n8n runtime data
│   ├── scripts/                        # Deployment scripts
│   ├── nginx/                          # Nginx config
│   ├── docker-compose.yml              # Root docker config
│   ├── conversation_logs/              # Claude Code transcripts
│   ├── metadata.json                   # Backup metadata
│   └── rollback.sh                     # Auto-generated rollback script
```

### Module Backups
```
/mnt/archie_brain/backups/modules/
├── 20260115_module_improvements/
│   ├── tools/improvements/             # Module routes
│   ├── templates/tools/                # Related templates
│   │   └── improvements_lab.html
│   ├── static/js/improvements_lab/     # Module JS files
│   └── metadata.json                   # Module backup metadata
```

---

## Metadata Format

### Full Backup Metadata
```json
{
  "name": "20260115_171131_Full_backup_all_11_components",
  "timestamp": "20260115_171131",
  "description": "Full_backup_all_11_components",
  "created_by": "admin",
  "created_at": "2026-01-15T17:11:34.156123",
  "platform_version": "3.1.1",
  "build_number": 23,
  "backup_type": "full",
  "proposal_id": null,
  "components": {
    "database": true,
    "platform_v2": true,
    "documentation": true,
    "ai_bridge": true,
    "database_migrations": true,
    "n8n_workflows": true,
    "n8n_persistence": true,
    "scripts": true,
    "nginx": true,
    "environment": true,
    "conversation_logs": true
  }
}
```

### Module Backup Metadata
```json
{
  "name": "20260115_150302_module_improvements",
  "type": "module",
  "module_name": "improvements",
  "timestamp": "20260115_150302",
  "created_by": "admin",
  "proposal_id": 45,
  "files_backed_up": [
    "tools/improvements/",
    "templates/tools/improvements_lab.html",
    "static/js/improvements_lab/"
  ]
}
```

---

## UI Features

### Quick Backup Buttons
- **FULL BACKUP** (Purple) - All 11 components
- **CRITICAL ONLY** (Green) - Essential components only
- **DATABASE ONLY** (Orange) - PostgreSQL dump only

### Custom Backup Section
- Component checkboxes grouped by importance (Critical, Important, Optional)
- Real-time size/time estimation
- Custom description field

### Module Backups Section (Purple)
- Lists all 48+ available modules with file counts and sizes
- Select All / Clear All buttons
- Module backup history with restore buttons
- Useful for Improvements Lab sandbox testing

### Backup List
- Shows all backups with type badges (FULL, CRITICAL, DATABASE, CUSTOM, LEGACY)
- Build number display
- Current build indicator
- Actions: Deploy to Sandbox, Set Current, Restore, Download, Delete

---

## Sandbox Integration

### Deploy Backup to Sandbox
```bash
curl -X POST http://localhost:3000/tools/backup-manager/deploy-to-sandbox \
  -H "Content-Type: application/json" \
  -d '{"backup_name": "20260115_171131_...", "sandbox_id": 1}'
```

Supports both sandbox types:
- `schema_separation` - Database schema isolation
- `docker_container` - Full container isolation

---

## Retention Policy

### Grandfather-Father-Son (GFS) Strategy

The backup manager implements industry-standard retention:
- **Daily**: Keep last 7 daily backups
- **Weekly**: Keep last 4 weekly backups (one per week)
- **Monthly**: Keep last 6 monthly backups (one per month)

This typically keeps ~17 backups max while ensuring recovery points across different time ranges.

### Check Retention Status
```bash
curl http://localhost:3000/tools/backup-manager/retention-status
```

### Cleanup Old Backups
```bash
# Dry run (default)
curl -X POST http://localhost:3000/tools/backup-manager/cleanup \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# Actually delete
curl -X POST http://localhost:3000/tools/backup-manager/cleanup \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

---

## Rollback Procedure

Each backup includes an auto-generated `rollback.sh` script:

```bash
cd /mnt/archie_brain/backups/20260115_171131_Full_backup_all_11_components
./rollback.sh
```

The script:
1. Stops the platform
2. Restores the database
3. Restores platform files
4. Restarts the platform

---

## Future Features (Roadmap)

### Google Drive Remote Backup (Planned)
- Compress backups to password-protected `.tar.gz`
- Upload to Google Drive for Business via API
- Off-site redundancy for disaster recovery
- Track in: `/docs/MASTER_STATUS_AND_ROADMAP_2026.md`

### Scheduled Backups (Planned)
- Daily full backup at 2:00 AM
- Database-only backup every 6 hours
- Requires APScheduler or external cron

### Encryption (Planned)
- Encrypt `.env` files using Fernet symmetric encryption
- Secure storage of backup encryption keys

---

## Best Practices

1. **Create backups before major changes** - Always backup before deployments
2. **Use appropriate backup type** - Critical for quick saves, Full for complete snapshots
3. **Use module backups for testing** - Faster and more targeted than full backups
4. **Track build numbers** - Know which backup is currently deployed
5. **Keep at least one backup** - System prevents deleting the last backup
6. **Review metadata before restore** - Check what components are included
7. **Test rollback scripts** - Verify they work in sandbox first

---

## Troubleshooting

### Common Issues

**Error: "No module named 'backup_manager'"**
- Use: `from tools.backup_manager.backup_manager_routes import create_backup_programmatic`

**Error: "Database backup failed"**
- Check DB_HOST environment variable
- Default: `archie_database`

**Error: "Permission denied"**
- Ensure backup directory is writable
- Check: `ls -la /mnt/archie_brain/backups/`

**Missing components in backup**
- Verify docker-compose.yml has all volume mounts
- Required mounts: docs, ai_bridge, database/migrations, n8n_workflows, persistence/n8n, scripts, nginx, docker-compose.yml, conversation_logs

---

## Related Documentation

- `/docs/IMPROVEMENT_WORKFLOW_RETRY_ESCALATION.md` - Proposal workflow
- `/docs/MASTER_STATUS_AND_ROADMAP_2026.md` - Platform roadmap
- Blueprint Module - Track module status and dependencies
