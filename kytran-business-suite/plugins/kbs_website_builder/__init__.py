from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "website_builder",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/website-builder",
    )
    from plugins.kbs_website_builder.routes import register_routes

    register_routes(bp)
    return bp
