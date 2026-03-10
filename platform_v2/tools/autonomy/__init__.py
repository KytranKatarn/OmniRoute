"""
Autonomy Module — Proactive Agent Loop Management

Dashboard for managing ARCHIE's autonomous operations:
- Agent loop status and control
- Approval queue management
- Execution history and analytics
- Feature configuration

All routes require admin authentication.
"""

from flask import Blueprint

autonomy_bp = Blueprint("autonomy", __name__, url_prefix="/tools/autonomy")

from . import routes  # noqa: F401, E402
from . import telegram_routes  # noqa: F401, E402
from . import browser_routes  # noqa: F401, E402
from . import intelligence_routes  # noqa: F401, E402

from .routes import admin_required  # noqa: E402
from .ops_routes import register_ops_routes  # noqa: E402

register_ops_routes(autonomy_bp, admin_required)
