"""Products showcase — public page (no login required)."""

from flask import Blueprint, render_template

products_bp = Blueprint(
    "products",
    __name__,
    url_prefix="",
    template_folder="../../templates/tools",
)


@products_bp.route("/products")
def products_page():
    """Public products showcase page."""
    return render_template("products.html")
