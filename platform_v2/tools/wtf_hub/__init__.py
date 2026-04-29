"""WTF Hub — internal Bridge dispatch surface for What The Fact ingest pipeline."""

from flask import Blueprint

wtf_hub_bp = Blueprint("wtf_hub", __name__, url_prefix="/tools/wtf-hub")

from . import routes  # noqa: E402, F401
