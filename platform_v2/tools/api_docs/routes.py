"""
API Documentation Routes
Auto-generates OpenAPI 3.0 spec from Flask routes and serves Swagger UI
"""

import re
import json
from flask import jsonify, render_template_string, current_app, request
from . import api_docs_bp

# Swagger UI HTML template
SWAGGER_UI_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A.R.C.H.I.E. API Documentation</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css">
    <style>
        body {
            margin: 0;
            background: #0d1117;
        }
        .swagger-ui {
            background: #0d1117;
        }
        .swagger-ui .topbar {
            background: #161b22;
            padding: 10px 0;
        }
        .swagger-ui .topbar .download-url-wrapper .select-label {
            color: #00FF00;
        }
        .swagger-ui .info .title {
            color: #00FF00;
        }
        .swagger-ui .info .description p {
            color: #c9d1d9;
        }
        .swagger-ui .scheme-container {
            background: #161b22;
        }
        .swagger-ui section.models {
            background: #161b22;
            border-color: #30363d;
        }
        .swagger-ui .opblock-tag {
            color: #c9d1d9;
            border-color: #30363d;
        }
        .swagger-ui .opblock.opblock-get {
            background: rgba(97, 175, 254, 0.1);
            border-color: #61affe;
        }
        .swagger-ui .opblock.opblock-post {
            background: rgba(73, 204, 144, 0.1);
            border-color: #49cc90;
        }
        .swagger-ui .opblock.opblock-put {
            background: rgba(252, 161, 48, 0.1);
            border-color: #fca130;
        }
        .swagger-ui .opblock.opblock-delete {
            background: rgba(249, 62, 62, 0.1);
            border-color: #f93e3e;
        }
        .swagger-ui .opblock .opblock-summary-description {
            color: #c9d1d9;
        }
        .swagger-ui .btn {
            border-radius: 4px;
        }
        .swagger-ui .btn.execute {
            background: #00FF00;
            border-color: #00FF00;
            color: #000;
        }
        .swagger-ui .btn.execute:hover {
            background: #00cc00;
        }
        /* Custom header */
        .archie-header {
            background: linear-gradient(180deg, #0d1117 0%, #161b22 100%);
            border-bottom: 1px solid #00FF00;
            padding: 20px;
            text-align: center;
        }
        .archie-header h1 {
            color: #00FF00;
            font-family: 'Courier New', monospace;
            font-size: 2rem;
            margin: 0;
            text-shadow: 0 0 10px rgba(0, 255, 0, 0.5);
        }
        .archie-header p {
            color: #8b949e;
            margin: 10px 0 0 0;
        }
        .archie-stats {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-top: 15px;
        }
        .archie-stats .stat {
            text-align: center;
        }
        .archie-stats .stat-value {
            color: #00FF00;
            font-size: 1.5rem;
            font-weight: bold;
        }
        .archie-stats .stat-label {
            color: #8b949e;
            font-size: 0.8rem;
        }
    </style>
</head>
<body>
    <div class="archie-header">
        <h1>A.R.C.H.I.E. API</h1>
        <p>Autonomous Resource and Coordination Hub for Intelligent Execution</p>
        <div class="archie-stats">
            <div class="stat">
                <div class="stat-value">{{ endpoint_count }}</div>
                <div class="stat-label">ENDPOINTS</div>
            </div>
            <div class="stat">
                <div class="stat-value">{{ module_count }}</div>
                <div class="stat-label">MODULES</div>
            </div>
            <div class="stat">
                <div class="stat-value">{{ category_count }}</div>
                <div class="stat-label">CATEGORIES</div>
            </div>
        </div>
    </div>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
    <script>
        window.onload = function() {
            SwaggerUIBundle({
                url: "/api-docs/openapi.json",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout",
                defaultModelsExpandDepth: -1,
                docExpansion: "none",
                filter: true,
                showExtensions: true,
                showCommonExtensions: true
            });
        };
    </script>
</body>
</html>
"""


def get_method_from_rule(rule):
    """Extract HTTP methods from a rule"""
    methods = rule.methods - {"HEAD", "OPTIONS"}
    return list(methods)


def parse_docstring(func):
    """Extract description from function docstring"""
    if func.__doc__:
        lines = func.__doc__.strip().split("\n")
        return lines[0].strip()
    return None


def get_parameters_from_rule(rule):
    """Extract path parameters from URL rule"""
    params = []
    # Match <type:name> or <name> patterns
    pattern = r"<(?:(\w+):)?(\w+)>"
    for match in re.finditer(pattern, rule.rule):
        param_type = match.group(1) or "string"
        param_name = match.group(2)

        schema_type = "string"
        if param_type == "int":
            schema_type = "integer"
        elif param_type == "float":
            schema_type = "number"

        params.append(
            {
                "name": param_name,
                "in": "path",
                "required": True,
                "schema": {"type": schema_type},
            }
        )
    return params


def categorize_endpoint(rule_str):
    """Categorize endpoint based on URL pattern"""
    if "/creed/api/admin" in rule_str:
        return "C.R.E.E.D. Admin"
    elif "/tools/consciousness" in rule_str:
        return "Consciousness"
    elif "/tools/website-studio" in rule_str:
        return "Website Designer"
    elif "/tools/figma" in rule_str:
        return "Figma Integration"
    elif "/tools/project-builder" in rule_str:
        return "Project Builder"
    elif "/tools/game-studio" in rule_str:
        return "Game Studio"
    elif "/tools/media-studio" in rule_str:
        return "Media Studio"
    elif "/tools/content-studio" in rule_str:
        return "Content Studio"
    elif "/tools/repair-bay" in rule_str:
        return "Repair Bay"
    elif "/tools/backup-manager" in rule_str:
        return "Backup Manager"
    elif "/tools/sandbox" in rule_str:
        return "Sandbox Manager"
    elif "/tools/starbase" in rule_str:
        return "A.R.C.H.I.E. Starbase Command"
    elif "/tools/crm" in rule_str:
        return "CRM"
    elif "/tools/email" in rule_str:
        return "Email Manager"
    elif "/tools/invoicing" in rule_str:
        return "Invoicing"
    elif "/tools/scheduler" in rule_str:
        return "Scheduler"
    elif "/tools/store" in rule_str:
        return "Store Builder"
    elif "/tools/social-media" in rule_str:
        return "Social Media"
    elif "/tools/analytics" in rule_str:
        return "Analytics"
    elif "/tools/automations" in rule_str:
        return "Automations"
    elif "/tools/call-center" in rule_str:
        return "Call Center"
    elif "/tools/account-center" in rule_str:
        return "Account Center"
    elif "/tools/security" in rule_str:
        return "Security & Network"
    elif "/tools/code-editor" in rule_str:
        return "Code Editor"
    elif "/tools/testing" in rule_str:
        return "Testing Suite"
    elif "/tools/fine-tuning" in rule_str:
        return "AI Fine-tuning"
    elif "/tools/archie-chat" in rule_str:
        return "A.R.C.H.I.E. Chat"
    elif "/tools/doc" in rule_str:
        return "DOC App"
    elif "/tools/therapy" in rule_str:
        return "Therapy App"
    elif "/tools/fitness" in rule_str:
        return "Fitness App"
    elif "/tools/stockbot" in rule_str:
        return "StockBot"
    elif "/tools/archie-pool" in rule_str:
        return "Archie Pool"
    elif "/archie/api" in rule_str:
        return "A.R.C.H.I.E. Core"
    elif "/api/" in rule_str:
        return "Platform API"
    else:
        return "Other"


def generate_openapi_spec():
    """Generate OpenAPI 3.0 specification from Flask routes"""
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "A.R.C.H.I.E. Platform API",
            "description": """
## Autonomous Resource and Coordination Hub for Intelligent Execution

A.R.C.H.I.E. is an AI-powered platform with 35+ modules across 6 categories:

- **CREATION**: Figma, Project Builder, Game Studio, Media Studio, Content Studio
- **DEVELOPMENT**: Code Editor, A.R.C.H.I.E. Chat, Code Sentinel, Testing Suite
- **BUSINESS TOOLS**: Website Designer, CRM, Email, Invoicing, Scheduler, Store
- **STANDALONE APPS**: DOC, Therapy, Fitness, StockBot, Archie Pool
- **ADMIN**: Blueprint, Consciousness, Team Management, Improvements Lab
- **INTEGRATIONS**: Figma, Cursor IDE

### Authentication
Most endpoints require session authentication. Login at `/login` first.

### Rate Limits
API calls are logged for analytics. No strict rate limits currently enforced.
            """,
            "version": "5.13.0",
            "contact": {
                "name": "A.R.C.H.I.E. Support",
                "url": "https://github.com/KytranKatarn/archie-platform",
            },
            "license": {
                "name": "Proprietary",
                "url": "https://kytranempowerment.com/license",
            },
        },
        "servers": [{"url": request.host_url.rstrip("/"), "description": "Current Server"}],
        "tags": [],
        "paths": {},
    }

    # Collect all tags (categories)
    tags_set = set()

    # Process all routes
    for rule in current_app.url_map.iter_rules():
        # Skip static, internal, and non-API routes
        if rule.endpoint == "static":
            continue
        if rule.rule.startswith("/static"):
            continue
        if "/api" not in rule.rule and not rule.rule.endswith("/api/status"):
            continue
        if "api_docs" in rule.endpoint:
            continue

        # Get the view function
        view_func = current_app.view_functions.get(rule.endpoint)
        if not view_func:
            continue

        # Get methods
        methods = get_method_from_rule(rule)
        if not methods:
            continue

        # Get category/tag
        tag = categorize_endpoint(rule.rule)
        tags_set.add(tag)

        # Get parameters
        parameters = get_parameters_from_rule(rule)

        # Get description
        description = parse_docstring(view_func) or f"Endpoint: {rule.endpoint}"

        # Build path item
        path = rule.rule
        # Convert Flask URL params to OpenAPI format
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", path)

        if path not in spec["paths"]:
            spec["paths"][path] = {}

        for method in methods:
            method_lower = method.lower()
            operation = {
                "tags": [tag],
                "summary": description,
                "operationId": f"{rule.endpoint}_{method_lower}",
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "401": {"description": "Authentication required"},
                    "403": {"description": "Permission denied"},
                    "404": {"description": "Resource not found"},
                    "500": {"description": "Server error"},
                },
            }

            if parameters:
                operation["parameters"] = parameters

            # Add request body for POST/PUT/PATCH
            if method_lower in ["post", "put", "patch"]:
                operation["requestBody"] = {"content": {"application/json": {"schema": {"type": "object"}}}}

            spec["paths"][path][method_lower] = operation

    # Sort and add tags
    spec["tags"] = [{"name": tag, "description": f"{tag} API endpoints"} for tag in sorted(tags_set)]

    return spec


@api_docs_bp.route("/")
def swagger_ui():
    """Serve Swagger UI"""
    spec = generate_openapi_spec()
    endpoint_count = sum(len(methods) for methods in spec["paths"].values())
    module_count = len(spec["tags"])

    # Count unique categories
    categories = set()
    for tag in spec["tags"]:
        name = tag["name"]
        if name in [
            "Figma Integration",
            "Project Builder",
            "Game Studio",
            "Media Studio",
            "Content Studio",
        ]:
            categories.add("CREATION")
        elif name in [
            "Code Editor",
            "A.R.C.H.I.E. Chat",
            "Code Sentinel",
            "Testing Suite",
        ]:
            categories.add("DEVELOPMENT")
        elif name in [
            "Website Designer",
            "CRM",
            "Email Manager",
            "Invoicing",
            "Scheduler",
            "Store Builder",
            "Social Media",
            "Analytics",
            "Automations",
            "Call Center",
        ]:
            categories.add("BUSINESS_TOOLS")
        elif name in [
            "DOC App",
            "Therapy App",
            "Fitness App",
            "StockBot",
            "Archie Pool",
        ]:
            categories.add("STANDALONE_APPS")
        elif name in [
            "Blueprint",
            "Consciousness",
            "Team Management",
            "Improvements Lab",
            "Backup Manager",
            "Sandbox Manager",
            "Account Center",
            "Security & Network",
        ]:
            categories.add("ADMIN")
        else:
            categories.add("OTHER")

    return render_template_string(
        SWAGGER_UI_TEMPLATE,
        endpoint_count=endpoint_count,
        module_count=module_count,
        category_count=len(categories),
    )


@api_docs_bp.route("/openapi.json")
def openapi_spec():
    """Return OpenAPI 3.0 JSON specification"""
    spec = generate_openapi_spec()
    return jsonify(spec)


@api_docs_bp.route("/openapi.yaml")
def openapi_yaml():
    """Return OpenAPI 3.0 YAML specification"""
    import yaml

    spec = generate_openapi_spec()
    return current_app.response_class(
        yaml.dump(spec, default_flow_style=False, allow_unicode=True),
        mimetype="text/yaml",
    )


@api_docs_bp.route("/stats")
def api_stats():
    """Get API documentation statistics"""
    spec = generate_openapi_spec()

    # Count by method
    method_counts = {"get": 0, "post": 0, "put": 0, "delete": 0, "patch": 0}
    for path_item in spec["paths"].values():
        for method in path_item.keys():
            if method in method_counts:
                method_counts[method] += 1

    # Count by tag
    tag_counts = {}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            for tag in operation.get("tags", ["Other"]):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return jsonify(
        {
            "success": True,
            "stats": {
                "total_endpoints": sum(len(methods) for methods in spec["paths"].values()),
                "total_paths": len(spec["paths"]),
                "total_tags": len(spec["tags"]),
                "by_method": method_counts,
                "by_module": dict(sorted(tag_counts.items(), key=lambda x: -x[1])),
            },
        }
    )
