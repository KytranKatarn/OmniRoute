from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "store",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/store",
    )
    from plugins.kbs_store.routes import register_routes

    register_routes(bp)

    # Public storefront routes (no login)
    from plugins.kbs_store.public_routes import register_public_routes

    public_bp = Blueprint(
        "store_public",
        __name__,
        url_prefix="/public",
    )
    register_public_routes(public_bp)
    bp.register_blueprint(public_bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_store.routes import on_contact_created, on_invoice_paid, on_order_paid

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("invoice.paid")(on_invoice_paid)
    event_bus.on("order.paid")(on_order_paid)

    return bp
