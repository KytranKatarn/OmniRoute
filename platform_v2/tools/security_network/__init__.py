"""
Security & Network Module
=========================
Security monitoring, network health, and system status dashboard.
"""

from flask import Blueprint

security_network_bp = Blueprint("security_network", __name__, url_prefix="/tools/security-network")

from . import routes
