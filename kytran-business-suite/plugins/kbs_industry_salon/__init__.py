from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "industry_salon",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/industry-salon",
    )
    from plugins.kbs_industry_salon.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_industry_salon.routes import on_job_created

    event_bus.on("job.created")(on_job_created)

    return bp
