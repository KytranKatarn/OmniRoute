from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "industry_photography",
        __name__,
        template_folder="templates",
        static_url_path="/static/industry-photography",
    )
    from plugins.kbs_industry_photography.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_industry_photography.routes import on_job_created

    event_bus.on("job.created")(on_job_created)

    return bp
