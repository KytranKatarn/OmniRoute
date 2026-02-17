"""
System Operations Module
========================
Host machine administration interface for CPU, RAM, disk,
process, service, Docker, and network management.

Provides real-time monitoring and control of the A.R.C.H.I.E. host server.
"""

from flask import Blueprint

system_operations_bp = Blueprint("system_operations", __name__, url_prefix="/tools/system-operations")

from . import routes
