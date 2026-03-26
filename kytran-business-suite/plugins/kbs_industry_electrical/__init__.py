from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "industry-electrical",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/industry-electrical",
    )
    from plugins.kbs_industry_electrical.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_industry_electrical.routes import on_job_completed, on_job_created

    event_bus.on("job.created")(on_job_created)
    event_bus.on("job.completed")(on_job_completed)

    return bp
