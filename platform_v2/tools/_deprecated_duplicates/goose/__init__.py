"""
Goose Orchestration Module
==========================
Autonomous workflow orchestration for A.R.C.H.I.E. platform.

Phase: 55
Date: 2026-01-21
"""

from flask import Blueprint

goose_bp = Blueprint(
    "goose",
    __name__,
    url_prefix="/tools/goose",
    template_folder="../../templates/tools",
)

from . import routes
