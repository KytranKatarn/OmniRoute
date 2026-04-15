"""
Agent Academy — Training, Benchmarking & Model Testing Center

5 tabs: Benchmarks, Training, Models, A/B Testing, Knowledge
All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

agent_academy_bp = Blueprint(
    "agent_academy",
    __name__,
    url_prefix="/tools/agent-academy",
    template_folder="templates",
    static_folder="static",
)

from . import routes  # noqa: F401, E402
from .routes import admin_required  # noqa: E402
from .benchmark_routes import register_benchmark_routes  # noqa: E402
from .training_routes import register_training_routes  # noqa: E402
from .model_routes import register_model_routes  # noqa: E402
from .competency_routes import register_competency_routes  # noqa: E402

register_benchmark_routes(agent_academy_bp, admin_required)
register_training_routes(agent_academy_bp, admin_required)
register_model_routes(agent_academy_bp, admin_required)
register_competency_routes(agent_academy_bp, admin_required)
