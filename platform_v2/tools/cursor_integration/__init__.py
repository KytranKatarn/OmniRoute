"""
Cursor AI + OpenCode Integration Module
IDE integration for real-time code assistance and context sharing

Features:
- MCP Protocol support for AI assistants
- REST API for IDE extensions
- Code completion, actions, and diagnostics
- Knowledge base integration

Status: Operational
Version: 2.0.0
"""

from flask import Blueprint

cursor_integration_bp = Blueprint('cursor_integration', __name__, url_prefix='/tools/cursor-integration')

from . import routes
