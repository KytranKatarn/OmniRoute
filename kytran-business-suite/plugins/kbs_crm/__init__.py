from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "crm",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/crm",
    )
    from plugins.kbs_crm.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_crm.routes import on_invoice_paid, on_order_created

    event_bus.on("order.created")(on_order_created)
    event_bus.on("invoice.paid")(on_invoice_paid)

    return bp
