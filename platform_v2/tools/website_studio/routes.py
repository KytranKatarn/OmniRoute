"""
Website Studio — RETIRED. Redirects to Kytran Business Suite.

All website builder features have been consolidated into the KBS kbs_website_builder plugin:
- Project/page CRUD
- AI assistant (suggest-design, generate-content, improve-seo, generate-styles)
- Chat-based editing with role detection
- Multi-provider deployment (Hostinger, GitHub, Vercel, Netlify)
- 14 templates (6 industry + 8 application)
- Onboarding wizard + live preview

See: kytran-business-suite/plugins/kbs_website_builder/
Decision: #335
"""

import os

from flask import Blueprint, redirect
from flask_login import login_required

website_studio_bp = Blueprint(
    "website_studio",
    __name__,
    url_prefix="/tools/website-studio",
)


@website_studio_bp.route("/")
@login_required
def index():
    """Redirect to KBS Website Builder plugin."""
    KBS_URL = os.getenv("KBS_BASE_URL", "http://192.168.1.200:8091")
    return redirect(f"{KBS_URL}/plugins/website-builder/")


@website_studio_bp.route("/health")
def health_check():
    return {"status": "retired", "redirect": "kbs_website_builder"}, 200
