"""Family Tree — AI-Powered Genealogy Module."""

from functools import wraps

from flask import Blueprint, redirect, url_for
from flask_login import current_user

family_tree_bp = Blueprint(
    "family_tree",
    __name__,
    url_prefix="/tools/family-tree",
    template_folder="templates",
    static_folder="static",
)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


from . import routes  # noqa: E402, F401
from .document_routes import register_document_routes  # noqa: E402
from .photo_routes import register_photo_routes  # noqa: E402
from .research_routes import register_research_routes  # noqa: E402
from .timeline_routes import register_timeline_routes  # noqa: E402
from .dedup_routes import register_dedup_routes  # noqa: E402
from .hints_routes import register_hints_routes  # noqa: E402
from .dna_routes import register_dna_routes  # noqa: E402

register_research_routes(family_tree_bp, admin_required)
register_document_routes(family_tree_bp, admin_required)
register_photo_routes(family_tree_bp, admin_required)
register_timeline_routes(family_tree_bp, admin_required)
register_dedup_routes(family_tree_bp, admin_required)
register_hints_routes(family_tree_bp, admin_required)
register_dna_routes(family_tree_bp, admin_required)
