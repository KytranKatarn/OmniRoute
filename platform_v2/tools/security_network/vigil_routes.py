"""
vigil_routes.py -- V.I.G.I.L. AI-powered threat analysis API endpoints.

Follows ADR-045 register_*_routes pattern.
"""

from flask import jsonify
from flask_login import login_required


def register_vigil_routes(bp, admin_required_decorator):
    """Register V.I.G.I.L. analysis endpoints on the security_network blueprint."""

    @bp.route("/api/vigil/analyze-device/<device_ip>", methods=["POST"])
    @login_required
    @admin_required_decorator
    def vigil_analyze_device(device_ip):
        """Use V.I.G.I.L. to analyze a device's network behavior and assess risk."""
        from .vigil_analysis import analyze_device_behavior

        result = analyze_device_behavior(device_ip)
        has_error = "error" in result
        return jsonify({"success": not has_error, "analysis": result}), (500 if has_error else 200)

    @bp.route("/api/vigil/threat-report", methods=["POST"])
    @login_required
    @admin_required_decorator
    def vigil_threat_report():
        """Generate a V.I.G.I.L. network threat assessment report."""
        from .vigil_analysis import generate_threat_report

        result = generate_threat_report()
        has_error = "error" in result
        return jsonify({"success": not has_error, "report": result}), (500 if has_error else 200)

    @bp.route("/api/vigil/classify-device/<device_ip>", methods=["POST"])
    @login_required
    @admin_required_decorator
    def vigil_classify_device(device_ip):
        """Use V.I.G.I.L. to classify an unknown device by its traffic patterns."""
        from .vigil_analysis import classify_unknown_device

        result = classify_unknown_device(device_ip)
        has_error = "error" in result
        return jsonify({"success": not has_error, "classification": result}), (500 if has_error else 200)
