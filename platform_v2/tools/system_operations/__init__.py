"""
System Operations Module
========================
Host machine administration interface for CPU, RAM, disk,
process, service, Docker, and network management.

Provides real-time monitoring and control of the A.R.C.H.I.E. host server.
"""

from flask import Blueprint

system_operations_bp = Blueprint("system_operations", __name__, url_prefix="/tools/system-operations")

from . import routes  # noqa: F401, E402
from flask_login import login_required  # noqa: F401, E402
from rbac import require_permission, Permission  # noqa: E402

admin_required = require_permission(Permission.ADMIN_ACCESS)

from .process_routes import register_process_routes  # noqa: E402
from .docker_routes import register_docker_routes  # noqa: E402
from .stack_routes import register_stack_routes  # noqa: E402
from .storage_routes import register_storage_routes  # noqa: E402
from .network_routes import register_network_routes  # noqa: E402
from .firewall_routes import register_firewall_routes  # noqa: E402
from .health_routes import register_health_routes  # noqa: E402

register_process_routes(system_operations_bp, admin_required)
register_docker_routes(system_operations_bp, admin_required)
register_stack_routes(system_operations_bp, admin_required)
register_storage_routes(system_operations_bp, admin_required)
register_network_routes(system_operations_bp, admin_required)
register_firewall_routes(system_operations_bp, admin_required)
register_health_routes(system_operations_bp, admin_required)

__all__ = ["system_operations_bp"]
