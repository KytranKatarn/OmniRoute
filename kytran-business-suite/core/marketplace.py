from flask import Blueprint, render_template
from flask_login import login_required

marketplace_bp = Blueprint(
    "marketplace", __name__, template_folder="../shared/templates"
)


@marketplace_bp.route("/")
@login_required
def index():
    return render_template("marketplace.html")
