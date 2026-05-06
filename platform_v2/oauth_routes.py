"""
OAuth Routes — Kytran SSO stub
Google OAuth removed (Project Alpha, Decision #573).
All authentication is email + password against Account Center.
The oauth_bp blueprint is kept so app.py registration doesn't break.
"""

from flask import Blueprint, redirect, url_for, flash
from authlib.integrations.flask_client import OAuth

oauth_bp = Blueprint("oauth", __name__, url_prefix="/auth")
oauth = OAuth()


def init_oauth(app):
    """Initialize OAuth — Google provider removed. Kytran SSO provider lives in oauth_provider.py."""
    oauth.init_app(app)


# Catch any leftover bookmarks/links pointing at old Google routes
@oauth_bp.route("/google/login")
@oauth_bp.route("/google/callback")
@oauth_bp.route("/link/google")
@oauth_bp.route("/link/google/callback")
@oauth_bp.route("/unlink/google", methods=["GET", "POST"])
def google_removed():
    flash("Google login has been removed. Please use email and password to sign in.", "info")
    return redirect(url_for("login"))
