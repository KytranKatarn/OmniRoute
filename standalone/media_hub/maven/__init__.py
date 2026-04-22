"""
M.A.V.E.N. — Media Archive & Viewing Experience Navigator

Skill routes for the standalone Media Hub. Each submodule ships one capability
as a Flask Blueprint; they're all mounted under /maven/* via maven_bp.

Tracked in project #279 tasks #2237 (agent promotion) + #2239 (troubleshoot) +
#2240 (upgrade scanner) + #2241 (recommendations) + #2242 (duplicate triage).
"""

from flask import Blueprint

maven_bp = Blueprint("maven", __name__, url_prefix="/maven")

# Register submodule routes on the blueprint. Importing triggers decorator
# registration — order doesn't matter.
from . import troubleshoot    # noqa: E402, F401
from . import upgrades        # noqa: E402, F401
from . import recommendations # noqa: E402, F401
from . import chat            # noqa: E402, F401
from . import duplicates      # noqa: E402, F401
