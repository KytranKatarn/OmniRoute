"""
C.R.E.E.D. — Compliance, Rights & Ethical Enforcement Directive
================================================================
Public transparency page + admin governance API.

Blueprints:
- creed_public_bp (/creed) — no auth, public-facing transparency
- creed_admin_bp (/creed/api/admin) — admin governance, ethics, audit
"""

from .routes import creed_public_bp
from .admin_routes import creed_admin_bp

__all__ = ["creed_public_bp", "creed_admin_bp"]
