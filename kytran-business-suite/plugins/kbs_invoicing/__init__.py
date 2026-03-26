from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "invoicing",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/invoicing",
    )
    from plugins.kbs_invoicing.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_invoicing.routes import on_contact_created, on_order_created

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("order.created")(on_order_created)

    return bp
