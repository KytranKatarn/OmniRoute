from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "industry",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/industry",
    )
    from plugins.kbs_industry.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_industry.routes import on_contact_created, on_contract_signed, on_invoice_paid

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("invoice.paid")(on_invoice_paid)
    event_bus.on("contract.signed")(on_contract_signed)

    return bp
