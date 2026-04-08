"""
A.R.C.H.I.E. FLEET COMMAND Module
===================================
Unified fleet infrastructure: node management, mesh networking, OTA updates,
cloud providers, missions, dispatch tracking, and health monitoring.

Merged from Starbase Command + Starship Command (2026-04-08).
Agent/roster/crew management lives in Department HQ.

Author: A.R.C.H.I.E. Platform
Date: 2026-04-08
"""

from flask_login import login_required
from rbac import require_permission, Permission

from .routes import fleet_bp
from .node_routes import register_node_routes
from .mesh_routes import register_mesh_routes
from .health_routes import register_health_routes
from .crew_routes import register_crew_routes
from .fleet_routes import register_fleet_routes
from .provider_routes import register_provider_routes
from .dispatch_routes import register_dispatch_routes
from .mission_routes import register_mission_routes
from .ota_routes import register_ota_routes

admin_required = require_permission(Permission.ADMIN_ACCESS)

# Node management: dual auth (read=login, write=admin)
register_node_routes(fleet_bp, login_required, admin_required)

# Mesh networking, cluster ops: admin only
register_mesh_routes(fleet_bp, admin_required)

# Health monitoring (Nagios + heartbeat): any logged-in user
register_health_routes(fleet_bp, login_required)

# Node crew management (assign/remove agents on nodes): user-facing
register_crew_routes(fleet_bp, login_required)

# Cloud providers, fleet map, budgets: admin only
register_fleet_routes(fleet_bp, admin_required)

# ComfyUI routing, provider management: admin only
register_provider_routes(fleet_bp, admin_required)

# Bridge dispatch tracking, job status: admin only
register_dispatch_routes(fleet_bp, admin_required)

# Mission profiles, SSE streaming: admin only
register_mission_routes(fleet_bp, admin_required)

# OTA push, sync, upgrades: admin only
register_ota_routes(fleet_bp, admin_required)

__all__ = ["fleet_bp"]
