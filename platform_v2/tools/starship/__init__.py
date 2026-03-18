"""
A.R.C.H.I.E. STARSHIP Module
==============================
Fleet node management — Starbase hub + remote starship nodes.
"""

from flask_login import login_required

from .routes import starship_bp
from .node_routes import register_node_routes
from .crew_routes import register_crew_routes
from .ota_routes import register_ota_routes

register_node_routes(starship_bp, login_required)
register_crew_routes(starship_bp, login_required)
register_ota_routes(starship_bp, login_required)

__all__ = ["starship_bp"]
