"""
Department HQ Module - Organizational Management & Performance Tracking

6 tabs: Overview, Org Chart, Roster, Work Tracking, Performance, C.R.E.E.D.
Manages 16 departments across 5 floors with AI Directors and staff agents.

Routes split per ADR-045:
- routes.py — Overview + Org Chart (dashboard, floor summary, org tree)
- roster_routes.py — Agent CRUD, assignments, shift management
- work_routes.py — Work sessions, job tracking, performance, C.R.E.E.D.
"""

from flask import Blueprint

department_hq_bp = Blueprint(
    "department_hq",
    __name__,
    template_folder="templates",
    static_folder="static",
    url_prefix="/tools/department-hq",
)

from .routes import register_routes, admin_required  # noqa: F401, E402
from .roster_routes import register_roster_routes  # noqa: E402
from .work_routes import register_work_routes  # noqa: E402
from .agent_detail_routes import register_agent_detail_routes  # noqa: E402
from .identity_routes import register_identity_routes  # noqa: E402

# Register all route groups on the blueprint
register_routes(department_hq_bp)
register_roster_routes(department_hq_bp, admin_required)
register_work_routes(department_hq_bp, admin_required)
register_agent_detail_routes(department_hq_bp, admin_required)
register_identity_routes(department_hq_bp, admin_required)
