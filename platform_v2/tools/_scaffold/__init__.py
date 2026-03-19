"""
[MODULE_NAME] Module - A.R.C.H.I.E. Platform
=============================================
[Brief description of what this module does.]

All routes require admin authentication via @admin_required decorator.

Author: A.R.C.H.I.E. Platform
Date: [DATE]
"""

from .routes import scaffold_bp  # noqa: F401, E402
from flask_login import login_required  # noqa: F401, E402
from rbac import require_permission, Permission  # noqa: E402

admin_required = require_permission(Permission.ADMIN_ACCESS)

# --- Register sub-route files (ADR-045 pattern) ---
# Uncomment and add as your module grows:
# from .data_routes import register_data_routes  # noqa: E402
# register_data_routes(scaffold_bp, admin_required)

__all__ = ["scaffold_bp"]
