from flask import Blueprint

revenue_standup_bp = Blueprint(
    "revenue_standup",
    __name__,
    template_folder="../../templates",
    url_prefix="/tools/revenue-standup",
)

from . import routes  # noqa: E402, F401
