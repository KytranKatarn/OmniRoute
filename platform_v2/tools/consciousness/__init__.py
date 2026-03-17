"""
Consciousness Module - A.R.C.H.I.E.'s Dynamic Learning System

This ADMIN-ONLY module manages:
- Conversation memories (auto-learned from interactions)
- Team Awareness (agent directory, performance tracking)
- Analytics (knowledge growth, usage patterns)

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

consciousness_bp = Blueprint(
    "consciousness",
    __name__,
    url_prefix="/tools/consciousness",
    template_folder="templates",
)

from . import routes  # noqa: F401, E402
from .routes import admin_required  # noqa: E402
from .processing_routes import processing_bp  # noqa: E402
from .knowledge_routes import register_knowledge_routes  # noqa: E402

# team_routes removed — Team tab merged into Bridge Command Crew tab
from .insights_routes import register_insights_routes  # noqa: E402
from .github_routes import register_github_routes  # noqa: E402
from .integration_routes import register_integration_routes  # noqa: E402
from .code_health_routes import register_code_health_routes  # noqa: E402

# Register processing routes as nested blueprint
consciousness_bp.register_blueprint(processing_bp)

# Register knowledge routes (KB CRUD, search, ingestion, unified API)
register_knowledge_routes(consciousness_bp, admin_required)

# Team routes removed — merged into Bridge Command Crew tab

# Register insights routes (analytics, sessions, learning patterns, experiences)
register_insights_routes(consciousness_bp, admin_required)

# Register GitHub routes (indexing, search, dependencies)
register_github_routes(consciousness_bp, admin_required)

# Register integration routes (cross-module health)
register_integration_routes(consciousness_bp, admin_required)

# Register code health routes (metrics, audit progress)
register_code_health_routes(consciousness_bp, admin_required)

# Resume any server-side loops that were active before restart
try:
    from .processing_routes import startup_resume_loops

    startup_resume_loops()
except Exception:
    pass

# Register station actions so Bridge ACTN tab can discover them
try:
    from services.action_registry import register_station_actions

    register_station_actions(
        [
            {
                "action_key": "consciousness.analysis.start",
                "station_code": "ANALYTICS",
                "module_source": "consciousness",
                "label": "ANALYZE",
                "description": "Start batch knowledge analysis",
                "icon": "brain",
                "color_class": "cyan",
                "sort_order": 10,
                "endpoint_path": "/tools/consciousness/api/processing/start",
                "creates_job": True,
                "job_type": "knowledge_analysis",
                "test_config": {
                    "capability": "summarize",
                    "prompt": "Analyze this knowledge entry and extract key topics, entities, and a one-sentence summary:\n\nFlask is a micro web framework written in Python. It is classified as a microframework because it does not require particular tools or libraries.",
                    "system_prompt": "You are a knowledge analyst. Extract topics, entities, and summary. Be concise.",
                    "description": "Analyze short knowledge entry",
                },
            },
            {
                "action_key": "consciousness.embeddings.generate",
                "station_code": "ANALYTICS",
                "module_source": "consciousness",
                "label": "EMBED",
                "description": "Generate embeddings for unembedded entries",
                "icon": "vector",
                "color_class": "cyan",
                "sort_order": 20,
                "endpoint_path": "/tools/consciousness/api/processing/generate-embeddings",
                "creates_job": True,
                "job_type": "embedding_generation",
                "test_config": {
                    "capability": "embedding",
                    "prompt": "Generate a semantic summary suitable for vector embedding:\n\nDocker containers package applications with their dependencies, ensuring consistent deployment across environments.",
                    "system_prompt": "Summarize the text in one dense sentence capturing all key concepts.",
                    "description": "Prepare text for embedding",
                },
            },
            {
                "action_key": "consciousness.github.reindex",
                "station_code": "ANALYTICS",
                "module_source": "consciousness",
                "label": "REINDEX",
                "description": "Reindex all GitHub repositories",
                "icon": "git",
                "color_class": "cyan",
                "sort_order": 30,
                "endpoint_path": "/tools/consciousness/github/reindex-all",
                "creates_job": True,
                "job_type": "github_reindex",
                "test_config": {
                    "capability": "code_analysis",
                    "prompt": "Analyze this code file summary and categorize it:\n\nFile: app.py\nLanguage: Python\nImports: flask, os, logging\nFunctions: create_app, register_blueprints\nClasses: none",
                    "system_prompt": "You are a code indexer. Categorize the file type and purpose in one sentence.",
                    "description": "Classify code file metadata",
                },
            },
            {
                "action_key": "consciousness.translate.generate",
                "station_code": "ANALYTICS",
                "module_source": "consciousness",
                "label": "TRANSLATE",
                "description": "Generate missing translations",
                "icon": "globe",
                "color_class": "cyan",
                "sort_order": 40,
                "endpoint_path": "/tools/consciousness/api/translations/generate-async",
                "creates_job": True,
                "job_type": "translation",
                "test_config": {
                    "capability": "translate",
                    "prompt": "Translate to French: The system is operating normally. All services are online.",
                    "system_prompt": "You are a translator. Translate the given text accurately. Output only the translation.",
                    "description": "Translate short system text",
                },
            },
        ]
    )
except Exception:
    pass  # Table may not exist yet (pre-migration)
