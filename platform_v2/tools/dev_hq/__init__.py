"""
A.R.C.H.I.E. Dev HQ - Unified Development Command Center
Admin-only, Hub-only development headquarters.
"""

from flask import Blueprint

dev_hq_bp = Blueprint("dev_hq", __name__, url_prefix="/dev-hq")

from . import routes  # noqa: E402, F401
