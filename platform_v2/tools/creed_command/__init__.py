"""C.R.E.E.D. Command — E.T.H.O.S. governance command center (AI Command module).

E.T.H.O.S.'s (agent #336) work dashboard for running C.R.E.E.D. as a nonprofit:
mail (the creed-ai.org mailboxes), grants pipeline, marketing/promotion, files, and
a governance overview of the C.R.E.E.D. public surfaces E.T.H.O.S. owns. Admin-only.

Scaffold (P0, project #367) — tab backends land in later phases. Mail reuses the
platform Email Manager (IMAP); governance tab links the live C.R.E.E.D. surfaces.
"""

from flask import Blueprint

creed_command_bp = Blueprint(
    "creed_command",
    __name__,
    url_prefix="/tools/creed-command",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/creed_command",
)

from . import routes  # noqa: F401, E402
from .grants_routes import register_grants_routes  # noqa: E402

register_grants_routes(creed_command_bp, routes.admin_required)
