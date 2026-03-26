from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "social_media",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/social-media",
    )
    from plugins.kbs_social_media.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_social_media.routes import on_contact_created, on_document_published

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("document.published")(on_document_published)

    return bp
