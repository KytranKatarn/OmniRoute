"""Faith module — spiritual care companion (F.A.I.T.H. + Emmanuel Adeyemi).

Routes registered under /tools/faith (see routes.py). Access gated by faith:access.
"""

import importlib

from flask import Blueprint

faith_bp = Blueprint("faith", __name__, url_prefix="/tools/faith")

# Import routes for their side effect of registering handlers on faith_bp.
# Done via importlib (not `from . import routes`) so raw pyflakes — which the
# Code Health scanner runs and which ignores `# noqa` — sees a used call rather
# than reporting "'.routes' imported but unused".
importlib.import_module(__name__ + ".routes")
