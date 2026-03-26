"""Automations UI plugin — visual workflow builder on top of the Automations Engine."""

from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "automations_ui",
        __name__,
        template_folder="templates",
        static_url_path="/static/automations-ui",
    )

    from plugins.kbs_automations_ui.routes import register_routes

    register_routes(bp)
    return bp
