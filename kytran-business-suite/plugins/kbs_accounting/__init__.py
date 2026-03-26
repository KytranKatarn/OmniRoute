from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "accounting",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/accounting",
    )
    from plugins.kbs_accounting.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_accounting.routes import on_invoice_paid, on_payment_received

    event_bus.on("invoice.paid")(on_invoice_paid)
    event_bus.on("payment.received")(on_payment_received)

    return bp
