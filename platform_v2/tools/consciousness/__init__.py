"""
Consciousness Module - A.R.C.H.I.E.'s Dynamic Learning System

This ADMIN-ONLY module manages:
- Conversation memories (auto-learned from interactions)
- Team Awareness (agent directory, performance tracking)
- Analytics (knowledge growth, usage patterns)

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

consciousness_bp = Blueprint('consciousness', __name__, url_prefix='/tools/consciousness')

from . import routes
