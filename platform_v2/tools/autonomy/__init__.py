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

# Loop startup (migrated from Consciousness 2026-03-23)
try:
    from services.loop_service import startup_resume_loops

    startup_resume_loops()
except Exception as e:
    print(f"[AUTONOMY] Loop startup failed: {e}")

# Register station actions for OPERATIONS panel
try:
    from services.action_registry import register_station_actions

    register_station_actions(
        [
            {
                "action_key": "autonomy.loop.toggle",
                "station_code": "OPERATIONS",
                "module_source": "autonomy",
                "label": "LOOP TOGGLE",
                "description": "Toggle server processing loops",
                "icon": "refresh",
                "color_class": "cyan",
                "sort_order": 10,
                "endpoint_path": "/tools/autonomy/api/ops-server-loop/toggle",
                "creates_job": False,
            },
            {
                "action_key": "autonomy.embeddings.generate",
                "station_code": "OPERATIONS",
                "module_source": "autonomy",
                "label": "EMBED",
                "description": "Generate embeddings for unembedded entries",
                "icon": "vector",
                "color_class": "cyan",
                "sort_order": 20,
                "endpoint_path": "/tools/consciousness/api/processing/generate-embeddings",
                "creates_job": True,
                "job_type": "embedding_generation",
            },
            {
                "action_key": "autonomy.translate.generate",
                "station_code": "OPERATIONS",
                "module_source": "autonomy",
                "label": "TRANSLATE",
                "description": "Generate missing translations",
                "icon": "globe",
                "color_class": "cyan",
                "sort_order": 30,
                "endpoint_path": "/tools/consciousness/api/translations/generate-async",
                "creates_job": True,
                "job_type": "translation",
            },
        ]
    )
except Exception:
    pass
