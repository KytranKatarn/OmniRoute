"""
A.R.C.H.I.E. Project Manager Module
Phase 65: Unified Project & Documentation System

Features:
- Unified project and task tracking
- Team collaboration (users + AI agents)
- Documentation management with versioning
- Decision logging (ADR support)
- ARCHIE self-awareness integration
- Activity feed and audit trail
"""

from flask import Blueprint

project_manager_bp = Blueprint("project_manager", __name__, url_prefix="/tools/project-manager")

from . import routes
