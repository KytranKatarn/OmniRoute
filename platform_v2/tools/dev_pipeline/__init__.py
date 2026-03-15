"""
Dev Pipeline Module — Unified Development Tools

Consolidates Code Sentinel + Improvements Lab + Sandbox Manager into
a single module with 4 tabs: Scan, Proposals, Sandbox, Deploy.

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

dev_pipeline_bp = Blueprint(
    "dev_pipeline",
    __name__,
    url_prefix="/tools/dev-pipeline",
    template_folder="templates",
)

from . import routes  # noqa: F401, E402
from .routes import admin_required  # noqa: E402
from .scan_routes import register_scan_routes  # noqa: E402
from .proposal_routes import register_proposal_routes  # noqa: E402
from .sandbox_routes import register_sandbox_routes  # noqa: E402
from .deploy_routes import register_deploy_routes  # noqa: E402
from .station_routes import register_station_routes  # noqa: E402

# Register all route groups (service layer — no more proxy imports)
register_scan_routes(dev_pipeline_bp, admin_required)
register_proposal_routes(dev_pipeline_bp, admin_required)
register_sandbox_routes(dev_pipeline_bp, admin_required)
register_deploy_routes(dev_pipeline_bp, admin_required)
register_station_routes(dev_pipeline_bp, admin_required)

# Register station actions so Bridge ACTN tab can discover them
try:
    from services.action_registry import register_station_actions

    register_station_actions(
        [
            {
                "action_key": "dev_pipeline.scan.batch",
                "station_code": "ENGINEERING",
                "module_source": "dev_pipeline",
                "label": "BATCH SCAN",
                "description": "Run code scan across all tracked files",
                "icon": "search",
                "color_class": "green",
                "sort_order": 10,
                "endpoint_path": "/tools/dev-pipeline/api/scan/batch",
                "creates_job": True,
                "job_type": "code_scan",
                "test_config": {
                    "capability": "code_analysis",
                    "prompt": "Analyze this Python function for bugs, style issues, and improvements:\n\ndef add(a, b):\n    return a + b",
                    "system_prompt": "You are a code reviewer. List issues briefly. Be concise.",
                    "description": "Scan trivial function for issues",
                },
            },
            {
                "action_key": "dev_pipeline.scan.run",
                "station_code": "ENGINEERING",
                "module_source": "dev_pipeline",
                "label": "SCAN FILE",
                "description": "Scan a specific file for issues",
                "icon": "file",
                "color_class": "green",
                "sort_order": 20,
                "endpoint_path": "/tools/dev-pipeline/api/scan/run",
                "params_schema": [
                    {
                        "key": "file_path",
                        "label": "File Path",
                        "type": "text",
                        "required": True,
                    }
                ],
                "creates_job": True,
                "job_type": "code_scan",
                "test_config": {
                    "capability": "code_analysis",
                    "prompt": "Review this Python function for correctness and suggest improvements:\n\ndef factorial(n):\n    if n == 0: return 1\n    return n * factorial(n-1)",
                    "system_prompt": "You are a code reviewer. List issues briefly. Be concise.",
                    "description": "Scan single file function",
                },
            },
            {
                "action_key": "dev_pipeline.sandbox.run",
                "station_code": "ENGINEERING",
                "module_source": "dev_pipeline",
                "label": "RUN TESTS",
                "description": "Execute sandbox test suite",
                "icon": "terminal",
                "color_class": "green",
                "sort_order": 30,
                "endpoint_path": "/tools/dev-pipeline/api/sandbox/run",
                "creates_job": True,
                "job_type": "sandbox_test",
                "test_config": {
                    "capability": "code_analysis",
                    "prompt": 'Write a simple pytest test for this function:\n\ndef greet(name):\n    return f"Hello, {name}!"',
                    "system_prompt": "You are a test engineer. Write one pytest function. Be concise.",
                    "description": "Generate simple test case",
                },
            },
        ]
    )
except Exception as e:
    import logging

    logging.getLogger(__name__).warning(f"Station action registration failed: {e}")
