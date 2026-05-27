"""
Brainstorm Module (T2069) — durable, DB-backed ideation workspace.
Option 3: per-user sessions, clustered ideas, KB export, AI assist.
"""

from flask import Blueprint

brainstorm_bp = Blueprint("brainstorm", __name__, url_prefix="/tools/brainstorm")

from . import routes  # noqa: E402, F401
