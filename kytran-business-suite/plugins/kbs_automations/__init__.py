"""Automations Engine plugin — event-driven workflow automation."""

from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "automations",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/automations",
    )

    from plugins.kbs_automations.routes import register_routes

    register_routes(bp)

    # Register wildcard event consumer — catches every event on the bus
    from core.event_bus import event_bus
    from plugins.kbs_automations.engine import process_event

    def _on_any_event(data):
        tenant_id = data.get("_tenant_id")
        event_type = data.get("_event_type")
        if tenant_id and event_type:
            process_event(event_type, data, tenant_id)

    event_bus.on("*")(_on_any_event)

    return bp
