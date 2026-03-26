from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "appointments",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/appointments",
    )
    from plugins.kbs_appointments.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_appointments.routes import on_contact_created

    event_bus.on("contact.created")(on_contact_created)

    return bp
