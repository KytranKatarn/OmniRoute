"""
Figma Integration Module
Phase 8: Design-to-Code Pipeline
"""
from flask import Blueprint

figma_bp = Blueprint('figma', __name__, url_prefix='/tools/figma')

from . import routes
