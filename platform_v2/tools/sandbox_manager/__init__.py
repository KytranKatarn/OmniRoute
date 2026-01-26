"""
Sandbox Manager Module
Per-module sandbox testing environments for safe code deployment

Features:
- Dashboard showing all module sandboxes with status
- Create/destroy module sandboxes
- Run tests in sandboxes
- Visual access to sandbox environments
- Configuration management
- Integration with Code Sentinel and Improvements Lab
"""

from flask import Blueprint

sandbox_manager_bp = Blueprint('sandbox_manager', __name__, url_prefix='/tools/sandbox-manager')

from . import routes
