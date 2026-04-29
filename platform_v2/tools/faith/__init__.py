"""Faith module — spiritual care companion (F.A.I.T.H. + Emmanuel Adeyemi)."""

from flask import Blueprint

faith_bp = Blueprint("faith", __name__, url_prefix="/tools/faith")

from . import routes  # noqa: E402, F401
