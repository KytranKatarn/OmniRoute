"""
Backup Manager — backwards-compatibility shim
=============================================

The original 5,251-LOC monolith was split into 5 focused route files (Task #2699):
- routes_operations.py
- routes_restore.py
- routes_webhooks.py
- routes_storage.py
- routes_admin.py

Shared helpers + constants + programmatic API live in _shared.py.

This shim re-exports everything from the package so legacy imports of the form
``from tools.backup_manager.backup_manager_routes import X`` continue to work.
New code should import from ``tools.backup_manager`` (package) or
``tools.backup_manager._shared`` directly.
"""

# Re-export blueprint and programmatic API from the package's __init__
from tools.backup_manager import (  # noqa: F401
    backup_manager_bp,
    create_backup,
    create_backup_programmatic,
    backup_module,
    get_module_dependencies,
    admin_required,
)

# Re-export every helper, constant, and lower-level function from _shared
from tools.backup_manager._shared import *  # noqa: F401, F403
