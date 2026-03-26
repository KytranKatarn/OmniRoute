from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "marketing",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/marketing",
    )
    from plugins.kbs_marketing.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_marketing.routes import (
        on_contact_created,
        on_document_published,
        on_post_published,
    )

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("post.published")(on_post_published)
    event_bus.on("document.published")(on_document_published)

    return bp
