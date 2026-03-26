from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "call_center",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/call-center",
    )
    from plugins.kbs_call_center.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_call_center.routes import on_contact_created

    event_bus.on("contact.created")(on_contact_created)

    return bp
