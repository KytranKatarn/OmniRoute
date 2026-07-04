"""
Predefined schemas for common agent handoff patterns.
Validates data passed between agents during multi-step workflows.
"""

# Schema definitions as dicts (JSON Schema format)
SCHEMAS = {
    "scan_result": {
        "type": "object",
        "required": ["target", "scan_type", "findings"],
        "properties": {
            "target": {"type": "string"},
            "scan_type": {"type": "string"},
            "timestamp": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": [
                                "critical",
                                "high",
                                "medium",
                                "low",
                                "info",
                            ],
                        },
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
            "score": {"type": "number"},
        },
    },
    "code_review": {
        "type": "object",
        "required": ["file_path", "issues"],
        "properties": {
            "file_path": {"type": "string"},
            "language": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "line": {"type": "integer"},
                        "severity": {"type": "string"},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                },
            },
            "quality_score": {"type": "number"},
            "summary": {"type": "string"},
        },
    },
    "device_audit": {
        "type": "object",
        "required": ["devices", "total"],
        "properties": {
            "devices": {"type": "array"},
            "total": {"type": "integer"},
            "online": {"type": "integer"},
            "unregistered": {"type": "integer"},
            "zones": {"type": "object"},
        },
    },
    "dns_report": {
        "type": "object",
        "required": ["queries", "blocked"],
        "properties": {
            "queries": {"type": "integer"},
            "blocked": {"type": "integer"},
            "block_rate": {"type": "number"},
            "top_clients": {"type": "array"},
            "top_blocked": {"type": "array"},
            "period": {"type": "string"},
        },
    },
    "security_alert": {
        "type": "object",
        "required": ["alert_type", "title", "severity"],
        "properties": {
            "alert_type": {"type": "string"},
            "title": {"type": "string"},
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
            },
            "description": {"type": "string"},
            "source_ip": {"type": "string"},
            "target": {"type": "string"},
            "recommended_action": {"type": "string"},
        },
    },
    "proposal": {
        "type": "object",
        "required": ["title", "description", "file_path"],
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "file_path": {"type": "string"},
            "issue_type": {"type": "string"},
            "severity": {"type": "string"},
            "suggested_fix": {"type": "string"},
            "estimated_effort": {"type": "string"},
        },
    },
}


def validate_schema(data, schema_name):
    """Validate data against a named schema. Returns (is_valid, errors)."""
    schema = SCHEMAS.get(schema_name)
    if not schema:
        return True, []  # Unknown schema = no validation

    errors = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    if not isinstance(data, dict):
        return False, ["Expected object, got " + type(data).__name__]

    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    for field, value in data.items():
        if field in properties:
            expected_type = properties[field].get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"Field {field}: expected string, got {type(value).__name__}")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"Field {field}: expected integer, got {type(value).__name__}")
            elif expected_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"Field {field}: expected number, got {type(value).__name__}")
            elif expected_type == "array" and not isinstance(value, list):
                errors.append(f"Field {field}: expected array, got {type(value).__name__}")
            elif expected_type == "object" and not isinstance(value, dict):
                errors.append(f"Field {field}: expected object, got {type(value).__name__}")

    return len(errors) == 0, errors


def get_schema(name):
    """Get a schema definition by name."""
    return SCHEMAS.get(name)


def list_schemas():
    """List all available schema names."""
    return list(SCHEMAS.keys())
