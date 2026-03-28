"""DEPRECATED: Agent management moved to Department HQ (/tools/department-hq).
Agent CRUD, skills, assignments, and roster operations are now handled by
the Department HQ module.

Legacy station constants are re-exported from helpers.py so that other
Starbase route files (dispatch_routes, provider_routes, crew_routes) that
import them continue to work without changes.
"""

import logging
from flask import jsonify

# Re-export constants so existing `from .agent_routes import ...` statements
# in other route files keep working.
from .helpers import (  # noqa: F401
    LEGACY_STATION_DEPARTMENT,
    LEGACY_STATION_COLORS,
    DEPARTMENT_TO_STATION,
)

logger = logging.getLogger(__name__)

_MOVED_MSG = "Agent management moved to Department HQ."
_REDIRECT = "/tools/department-hq"


def register_agent_routes(bp, admin_required):
    """Register deprecated agent redirect stubs."""

    @bp.route("/api/agents", methods=["GET"])
    @admin_required
    def get_bridge_agents():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents", methods=["POST"])
    @admin_required
    def create_agent():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>", methods=["PUT", "PATCH"])
    @admin_required
    def update_agent(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
    @admin_required
    def delete_agent(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>/toggle", methods=["POST"])
    @admin_required
    def toggle_agent(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>/skills", methods=["GET", "POST"])
    @admin_required
    def agent_skills(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>/assign-station", methods=["POST"])
    @admin_required
    def assign_agent_to_station(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/<int:agent_id>/unassign-station", methods=["POST"])
    @admin_required
    def unassign_agent_from_station(agent_id):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/stations/assignments", methods=["GET"])
    @admin_required
    def get_all_station_assignments():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/stations/unassigned-agents", methods=["GET"])
    @admin_required
    def get_unassigned_agents():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/dispatch/agent-gaps", methods=["GET"])
    @admin_required
    def get_agent_gaps():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/agents/create-from-gap", methods=["POST"])
    @admin_required
    def create_agent_from_gap():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301
