"""
Code Sentinel Module - AI-Powered Code Health & Quality Analysis
Local-first code scanning with AI/Ollama and Bridge routing

DEPRECATED: UI consolidated into Dev Pipeline module (/tools/dev-pipeline#scan).
API routes remain active for proxy layer compatibility.
"""

from flask import Blueprint

code_sentinel_bp = Blueprint("code_sentinel", __name__, url_prefix="/tools/code_sentinel")

from . import routes  # noqa: F401, E402

# Redirect index to Dev Pipeline Scan tab
from flask import redirect  # noqa: E402


@code_sentinel_bp.route("/redirect-to-pipeline")
def redirect_to_pipeline():
    return redirect("/tools/dev-pipeline#scan", code=302)
