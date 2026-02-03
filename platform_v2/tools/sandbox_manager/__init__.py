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
- Test discovery across codebase (Python, JavaScript, Shell)
- Automated regression testing with live progress
- Test history and trends visualization
- Performance benchmarking (API, database, module)

Note: Testing Suite features were merged into this module on 2026-02-03
"""

from flask import Blueprint

sandbox_manager_bp = Blueprint("sandbox_manager", __name__, url_prefix="/tools/sandbox-manager")

from . import routes  # noqa: F401, E402
