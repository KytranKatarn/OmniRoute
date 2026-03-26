from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "content_studio",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/content_studio",
    )
    from plugins.kbs_content_studio.routes import register_routes

    register_routes(bp)

    return bp
