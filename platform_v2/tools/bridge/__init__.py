"""
A.R.C.H.I.E. BRIDGE Module
==========================
Central command center for all AI/LLM operations.
Star Trek-inspired station-based workflow.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-16
"""

from .routes import bridge_bp
from .node_routes import register_node_routes
from .agent_routes import register_agent_routes
from .station_routes import register_station_routes
from .dispatch_routes import register_dispatch_routes
from .crew_routes import register_crew_routes
from .mission_routes import register_mission_routes
from .provider_routes import register_provider_routes
from flask_login import login_required  # noqa: F401
from rbac import require_permission, Permission

admin_required = require_permission(Permission.ADMIN_ACCESS)

register_node_routes(bridge_bp, admin_required)
register_agent_routes(bridge_bp, admin_required)
register_station_routes(bridge_bp, admin_required)
register_dispatch_routes(bridge_bp, admin_required)
register_crew_routes(bridge_bp, admin_required)
register_mission_routes(bridge_bp, admin_required)
register_provider_routes(bridge_bp, admin_required)

__all__ = ["bridge_bp"]
