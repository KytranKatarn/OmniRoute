"""
A.R.C.H.I.E. STARBASE COMMAND Module
=====================================
Fleet infrastructure dashboard: node management, model control, OTA/sync,
fleet health, and cluster operations.

Agent/roster/department management has moved to Department HQ.
Station and agent route files contain redirect stubs only.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-16
"""

from .routes import starbase_bp
from .node_routes import register_node_routes
from .agent_routes import register_agent_routes
from .station_routes import register_station_routes
from .dispatch_routes import register_dispatch_routes
from .crew_routes import register_crew_routes
from .mission_routes import register_mission_routes
from .provider_routes import register_provider_routes
from .mesh_routes import register_mesh_routes
from .fleet_routes import register_fleet_routes
from flask_login import login_required  # noqa: F401
from rbac import require_permission, Permission

admin_required = require_permission(Permission.ADMIN_ACCESS)

register_node_routes(starbase_bp, admin_required)
register_agent_routes(starbase_bp, admin_required)
register_station_routes(starbase_bp, admin_required)
register_dispatch_routes(starbase_bp, admin_required)
register_crew_routes(starbase_bp, admin_required)
register_mission_routes(starbase_bp, admin_required)
register_provider_routes(starbase_bp, admin_required)
register_mesh_routes(starbase_bp, admin_required)
register_fleet_routes(starbase_bp, admin_required)

__all__ = ["starbase_bp"]
