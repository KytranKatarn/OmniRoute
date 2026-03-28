from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "knowledge_base",
        __name__,
        template_folder="templates",
    )
    from plugins.kbs_knowledge_base.routes import register_routes

    register_routes(bp)
    return bp
