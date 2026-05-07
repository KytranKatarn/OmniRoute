"""
Backup Manager Module
=====================
Provides backup creation, restoration, and management functionality.

The original 5,251-LOC monolith (backup_manager_routes.py) was split into 5
focused route files (Task #2699). All shared helpers, constants, and
programmatic functions live in _shared.py.

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

from flask import Blueprint

# Re-export shared programmatic API used by proposal_service, agent_loop, etc.
from ._shared import (
    create_backup,
    create_backup_programmatic,
    backup_module,
    get_module_dependencies,
    admin_required,
)

# Create the blueprint that module_registry imports
backup_manager_bp = Blueprint("backup_manager", __name__, url_prefix="/tools/backup-manager")

# Register routes from each split file
from .routes_operations import register_operations_routes  # noqa: E402
from .routes_restore import register_restore_routes  # noqa: E402
from .routes_webhooks import register_webhooks_routes  # noqa: E402
from .routes_storage import register_storage_routes  # noqa: E402
from .routes_admin import register_admin_routes  # noqa: E402
from .routes_download import register_download_routes  # noqa: E402
from .routes_standalones import register_standalone_routes  # noqa: E402

register_operations_routes(backup_manager_bp, admin_required)
register_restore_routes(backup_manager_bp, admin_required)
register_webhooks_routes(backup_manager_bp, admin_required)
register_storage_routes(backup_manager_bp, admin_required)
register_admin_routes(backup_manager_bp, admin_required)
register_download_routes(backup_manager_bp, admin_required)
register_standalone_routes(backup_manager_bp, admin_required)
