"""
Site Manager Routes
Create, manage, and host multiple websites (e.g., whatthefact.ca)
"""

from flask import Blueprint, render_template, jsonify
from flask_login import login_required

site_manager_bp = Blueprint("site_manager", __name__, url_prefix="/tools/site-manager", template_folder="templates")


@site_manager_bp.route("/")
@login_required
def index():
    """Site Manager main page (Coming Soon)"""
    return render_template(
        "coming_soon.html",
        module_name="Site Manager",
        module_icon="🌍",
        module_description=(
            "Create, manage, and host multiple websites. "
            "Build sites like whatthefact.ca (fact news site) and manage all your web properties in one place."
        ),
    )


@site_manager_bp.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {"status": "healthy", "module": "site_manager", "version": "0.1.0", "ready": False, "message": "Coming Soon"}
    )
