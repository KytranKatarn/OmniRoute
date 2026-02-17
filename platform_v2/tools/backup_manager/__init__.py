"""
Backup Manager Module
=====================
Provides backup creation, restoration, and management functionality.

Usage (programmatic):
    from tools.backup_manager import create_backup, backup_module

    # Full platform backup
    result = create_backup(
        description='pre_improvement_45',
        created_by_username='admin',
        proposal_id=45
    )

    # Module-only backup (for sandbox testing)
    result = backup_module('improvements', proposal_id=45)

API Routes (at /tools/backup-manager/...):
- /list GET - List all backups
- /create POST - Create new backup
- /download/<name> GET - Download backup
- /delete/<name> DELETE - Delete backup
- /restore/<name> POST - Restore backup
- /deploy-to-sandbox POST - Deploy backup to sandbox
- /backup-module POST - Backup single module
- /module-dependencies/<name> GET - Get module file list
"""

from .backup_manager_routes import (
    backup_manager_bp,
    create_backup,
    create_backup_programmatic,
    backup_module,
    get_module_dependencies,
)
