"""
Department HQ Module — THE Command Center
==========================================
12 tabs: Overview, Org Chart, Roster, Work Tracking, Performance,
C.R.E.E.D., Social, Devices, Dispatch, Fleet, Contractors, COMs

Manages 16 departments across 5 floors with AI Directors and staff agents.
Fleet/node/mesh/OTA management migrated from A.R.M.A.D.A. (2026-04-08).

Routes split per ADR-045:
- routes.py — Overview + Org Chart (dashboard, floor summary, org tree)
- roster_routes.py — Agent CRUD, assignments, shift management
- work_routes.py — Work sessions, job tracking, performance, C.R.E.E.D.
- crew_routes.py — Hub crew manifest + agent personality
- contractor_routes.py — External AI provider management
- fleet_*_routes.py — Fleet/node/mesh/OTA/provider/mission (from A.R.M.A.D.A.)
"""

import os as _os

from flask import Blueprint
from flask_login import login_required

department_hq_bp = Blueprint(
    "department_hq",
    __name__,
    template_folder="templates",
    static_folder="static",
    url_prefix="/tools/department-hq",
)


# Cache-busting for this blueprint's static assets. The <script>/<link> tags were
# unversioned, so a browser kept serving the OLD department-hq.js after a deploy:
# measured 2026-09-20, a fresh renderer was on the server while the page still ran
# the previous one, and only a fresh browser context picked it up. Keyed on mtime,
# so it changes exactly when the file does and needs no build step.
_STATIC_ROOT = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "static")


@department_hq_bp.context_processor
def _inject_asset_version():
    def asset_v(rel_path: str) -> int:
        try:
            return int(_os.path.getmtime(_os.path.join(_STATIC_ROOT, rel_path)))
        except OSError:
            # A missing file must not break page render -- the tag simply goes
            # unversioned, which is the pre-existing behaviour.
            return 0

    return {"asset_v": asset_v}


from .routes import register_routes, admin_required  # noqa: F401, E402
from .roster_routes import register_roster_routes  # noqa: E402
from .work_routes import register_work_routes  # noqa: E402
from .kin_calendar_routes import register_kin_calendar_routes  # noqa: E402
from .agent_detail_routes import register_agent_detail_routes  # noqa: E402
from .identity_routes import register_identity_routes  # noqa: E402
from .social_routes import register_social_routes  # noqa: E402
from .scout_routes import register_scout_routes  # noqa: E402
from .theme_routes import register_theme_routes  # noqa: E402
from .skill_routes import register_skill_routes  # noqa: E402
from .auth_routes import register_auth_routes  # noqa: E402
from .knowledge_routes import register_knowledge_routes  # noqa: E402
from .model_routes import register_model_routes  # noqa: E402
from .dispatch_routes import register_dispatch_routes  # noqa: E402
from .crew_routes import register_crew_routes  # noqa: E402
from .contractor_routes import register_contractor_routes  # noqa: E402
from .approvals_routes import register_approvals_routes  # noqa: E402
from .chat_routes import register_chat_routes as register_agent_chat  # noqa: E402
from .creed_routes import register_creed_routes  # noqa: E402
from .coms_routes import register_coms_routes  # noqa: E402
from .browser_routes import register_browser_routes  # noqa: E402
from .session_routes import register_session_routes  # noqa: E402
from .hiring_routes import register_hiring_routes  # noqa: E402

# Fleet routes (migrated from A.R.M.A.D.A.)
from .fleet_dashboard_routes import register_dashboard_routes as register_fleet_dashboard  # noqa: E402
from .fleet_node_routes import register_node_routes as register_fleet_nodes  # noqa: E402
from .fleet_mesh_routes import register_mesh_routes as register_fleet_mesh  # noqa: E402
from .fleet_crew_routes import register_crew_routes as register_fleet_crew  # noqa: E402
from .fleet_provider_routes import register_fleet_routes as register_fleet_providers  # noqa: E402
from .fleet_dispatch_routes import register_dispatch_routes as register_fleet_dispatch  # noqa: E402
from .fleet_mission_routes import register_mission_routes as register_fleet_missions  # noqa: E402
from .fleet_ota_routes import register_ota_routes as register_fleet_ota  # noqa: E402
from .fleet_orchestration_routes import register_orchestration_routes as register_fleet_orchestration  # noqa: E402
from .fleet_ssh_routes import register_ssh_routes as register_fleet_ssh  # noqa: E402

# Register all route groups on the blueprint
register_routes(department_hq_bp)
register_roster_routes(department_hq_bp, admin_required)
register_work_routes(department_hq_bp, admin_required)
register_kin_calendar_routes(department_hq_bp, admin_required)
register_agent_detail_routes(department_hq_bp, admin_required)
register_identity_routes(department_hq_bp, admin_required)
register_social_routes(department_hq_bp, admin_required)
register_scout_routes(department_hq_bp, admin_required)
register_theme_routes(department_hq_bp, admin_required)
register_skill_routes(department_hq_bp, admin_required)
register_auth_routes(department_hq_bp, admin_required)
register_knowledge_routes(department_hq_bp, admin_required)
register_model_routes(department_hq_bp, admin_required)
register_dispatch_routes(department_hq_bp, admin_required)
register_crew_routes(department_hq_bp, admin_required)
register_contractor_routes(department_hq_bp, admin_required)
register_approvals_routes(department_hq_bp, admin_required)
register_agent_chat(department_hq_bp, admin_required)
register_creed_routes(department_hq_bp, admin_required)
register_coms_routes(department_hq_bp, admin_required)
register_browser_routes(department_hq_bp, admin_required)
register_session_routes(department_hq_bp, login_required, admin_required)
register_hiring_routes(department_hq_bp, admin_required)

# Fleet routes — all under /tools/department-hq/api/fleet/*
register_fleet_dashboard(department_hq_bp, login_required)
register_fleet_nodes(department_hq_bp, login_required, admin_required)
register_fleet_mesh(department_hq_bp, login_required)
register_fleet_crew(department_hq_bp, login_required)
register_fleet_providers(department_hq_bp, login_required)
register_fleet_dispatch(department_hq_bp, login_required)
register_fleet_missions(department_hq_bp, login_required)
register_fleet_ota(department_hq_bp, admin_required)
register_fleet_orchestration(department_hq_bp, admin_required)
register_fleet_ssh(department_hq_bp, admin_required)
