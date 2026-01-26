"""
Game Builder Module (Placeholder)
=================================
Build games with AI-powered tools.
Status: Coming Soon
"""

from flask import Blueprint

game_builder_bp = Blueprint('game_builder', __name__, url_prefix='/tools/game-builder')

from . import routes
