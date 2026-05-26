"""
Game Studio Module
"""

import os
import sys

from flask import Blueprint

# Add module directory to sys.path so bare-name lazy imports in routes.py
# (e.g. `from game_builder_service import ...`) resolve correctly.
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

game_studio_bp = Blueprint("game_studio", __name__, url_prefix="/tools/game-studio")

from . import routes
