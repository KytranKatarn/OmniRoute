"""
archie_pool Module (Placeholder)
Status: Coming Soon
"""

from flask import Blueprint

archie_pool_bp = Blueprint('archie_pool', __name__, url_prefix='/tools/archie-pool')

from . import routes
