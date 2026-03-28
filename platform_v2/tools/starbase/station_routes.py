"""DEPRECATED: Station management moved to Department HQ (/tools/department-hq).
Station panels replaced by department-based organization.

This file retains minimal redirect stubs so existing URL references return
a helpful 301 instead of a 404.
"""

import logging
from flask import jsonify

logger = logging.getLogger(__name__)

_MOVED_MSG = "Stations replaced by departments. Use Department HQ."
_REDIRECT = "/tools/department-hq"


def register_station_routes(bp, admin_required):
    """Register deprecated station redirect stubs."""

    @bp.route("/api/stations", methods=["GET"])
    @admin_required
    def get_stations():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/stations/<code>", methods=["GET"])
    @admin_required
    def get_station_detail(code):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/stations/<code>/dispatch", methods=["GET"])
    @admin_required
    def get_station_dispatch(code):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/stations/<code>/metrics", methods=["GET"])
    @admin_required
    def get_station_metrics(code):
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/station-actions", methods=["GET"])
    @admin_required
    def get_station_actions():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/benchmarks/start", methods=["POST"])
    @admin_required
    def start_benchmark():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/benchmarks/active", methods=["GET"])
    @admin_required
    def get_active_benchmark():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/bridge/resources", methods=["GET"])
    @admin_required
    def get_bridge_resources():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301

    @bp.route("/api/modules/metadata", methods=["POST"])
    @admin_required
    def get_modules_metadata():
        return jsonify({"message": _MOVED_MSG, "redirect": _REDIRECT}), 301
