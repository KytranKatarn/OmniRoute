from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "communications",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/communications",
    )
    from plugins.kbs_communications.routes import register_routes
    from plugins.kbs_communications.sms_routes import register_sms_routes
    from plugins.kbs_communications.chat_routes import register_chat_routes
    from plugins.kbs_communications.campaign_routes import register_campaign_routes
    from plugins.kbs_communications.webhook_routes import register_webhook_routes

    register_routes(bp)
    register_sms_routes(bp)
    register_chat_routes(bp)
    register_campaign_routes(bp)
    register_webhook_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_communications.routes import on_appointment_booked
    from plugins.kbs_communications.routes import on_appointment_cancelled

    event_bus.on("appointment.booked")(on_appointment_booked)
    event_bus.on("appointment.cancelled")(on_appointment_cancelled)

    return bp
