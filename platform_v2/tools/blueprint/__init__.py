"""
A.R.C.H.I.E. Blueprint Module
Admin-only overview of the entire A.R.C.H.I.E. platform

Features:
- System overview and architecture
- Module status tracker (live/in-progress/planned)
- Documentation browser
- Roadmap and progress tracking
- Code reference (for A.R.C.H.I.E.'s self-reference)
"""

from flask import Blueprint

blueprint_bp = Blueprint("blueprint", __name__, url_prefix="/tools/blueprint")

from . import routes
