"""
Team Management Module - Unified Agent Control Center

This ADMIN-ONLY module provides:
- Team roster (58 AI agents)
- Task assignment functionality
- Agent execution capabilities
- Automations/workflows
- Chat with team members
- Agent details, prompts, execution history
- Tools and performance tracking
- IAAE compliance (ethics, welfare, audit)
- Smart LLM routing

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

team_management_bp = Blueprint('team_management', __name__, url_prefix='/tools/team-management')

from . import routes
from .iaae_routes import iaae_bp
