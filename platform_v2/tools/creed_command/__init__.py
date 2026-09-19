"""C.R.E.E.D. Command — E.T.H.O.S. governance command center (AI Command module).

E.T.H.O.S.'s (agent #336) work dashboard for running C.R.E.E.D. as a nonprofit:
mail (the creed-ai.org mailboxes), grants pipeline, marketing/promotion, files, and
a governance overview of the C.R.E.E.D. public surfaces E.T.H.O.S. owns. Admin-only.

Scaffold (P0, project #367) — tab backends land in later phases. Mail reads the
Hostinger creed-ai.org boxes directly over IMAP (mail_routes.py) — kept separate
from the Stalwart-only Email Manager; governance tab links the live C.R.E.E.D.
surfaces.
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
from .mail_routes import register_mail_routes  # noqa: E402
from .marketing_routes import register_marketing_routes  # noqa: E402
from .files_routes import register_files_routes  # noqa: E402
from .tenants_routes import register_tenants_routes  # noqa: E402
from .redress_routes import register_redress_routes  # noqa: E402

register_grants_routes(creed_command_bp, routes.admin_required)
register_mail_routes(creed_command_bp, routes.admin_required)
register_marketing_routes(creed_command_bp, routes.admin_required)
register_files_routes(creed_command_bp, routes.admin_required)
register_tenants_routes(creed_command_bp, routes.admin_required)
register_redress_routes(creed_command_bp, routes.admin_required)
