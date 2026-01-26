"""
Business Module - Public-facing company website components

Provides:
- Business Directory (human + AI employees)
- Company information pages
- Public API for employee lookup
"""

from flask import Blueprint

business_bp = Blueprint('business', __name__, url_prefix='/business')

from . import routes
