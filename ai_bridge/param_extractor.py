"""
Parameter extraction from natural language for team management actions.
Uses Ollama dolphin3 to parse chat messages into structured API parameters.

Part of Phase 2: ARCHIE manages agents via Chat.
"""

import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)


def _get_extraction_model():
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        model = get_dispatcher().get_model_for_capability("conversation")
        return model or "dolphin3-8k:latest"
    except Exception:
        return os.getenv("ARCHIE_CHAT_MODEL", "dolphin3-8k:latest")


EXTRACTION_MODEL = _get_extraction_model()

AVAILABLE_DEPARTMENTS = [
    "Engineering",
    "Operations",
    "Customer Support",
    "Marketing",
    "Finance",
    "Legal",
    "HR",
    "Security",
    "Documentation",
    "AI Operations",
    "Creative",
    "Research",
    "Compliance",
    "Administration",
]


def _get_available_models():
    """Get available model names from smart router tiers."""
    try:
        from tools.department_hq.services.smart_router import SmartRouter

        router = SmartRouter()
        configs = router._get_model_configs()
        return [c.model_name for c in configs.values() if c.provider == "ollama"]
    except Exception:
        return ["dolphin3-8k:latest", "qwen3-coder-cpu:latest", "arctic-embed-cpu", "qwen25-classify", "minicpm-v-cpu"]


AVAILABLE_MODELS = _get_available_models()

# Template prompts for different action types
TEMPLATES = {
    "create_agent": """Extract agent creation parameters from this request.
Return ONLY valid JSON, no explanation.

Available Ollama models (local, free): {models}
Available departments: {departments}

Request: "{message}"

JSON format:
{{"model": "string (pick best model for the role)", "first_name": "string", "last_name": "string", "department": "string", "title": "string", "system_prompt": "string (brief role description)", "capabilities": ["string"]}}

JSON:""",
    "assign_department": """Extract department assignment parameters from this request.
Return ONLY valid JSON, no explanation.

Available departments: {departments}

Request: "{message}"

JSON format:
{{"agent_name": "string", "department": "string", "assignment_type": "primary"}}

JSON:""",
    "agent_action": """Extract agent action parameters from this request.
Return ONLY valid JSON, no explanation.

Actions: deactivate, activate, update

Request: "{message}"

JSON format:
{{"agent_name": "string", "action": "deactivate|activate|update", "reason": "string"}}

JSON:""",
}


def _parse_json_from_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Handle markdown code blocks
    if "```" in text:
        blocks = text.split("```")
        for block in blocks[1::2]:  # odd-indexed blocks are inside backticks
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    # Try to find JSON object in text
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {"error": f"Could not parse JSON from response: {text[:200]}"}


def extract_params(message: str, action_type: str) -> dict:
    """Extract structured parameters from natural language using Ollama."""
    template = TEMPLATES.get(action_type)
    if not template:
        return {"error": f"Unknown action type: {action_type}"}

    prompt = template.format(
        message=message,
        models=", ".join(AVAILABLE_MODELS),
        departments=", ".join(AVAILABLE_DEPARTMENTS),
    )

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        dispatch_result = dispatcher.request_work(
            "conversation", prompt, "param_extractor", json_mode=True, timeout=120
        )

        if not dispatch_result.success:
            return {"error": f"Extraction failed: {dispatch_result.error}"}

        text = dispatch_result.response.strip()
        logger.info("Param extraction response: %s", text[:300])

        result = _parse_json_from_response(text)

        # Normalize department names
        if "department" in result:
            result["department"] = result["department"].strip()

        return result

    except requests.exceptions.Timeout:
        logger.error("Param extraction timed out (120s)")
        return {"error": "LLM timeout — model may be loading"}
    except requests.RequestException as e:
        logger.error("Param extraction request failed: %s", e)
        return {"error": str(e)}


def resolve_agent_by_name(name: str, conn) -> dict | None:
    """Find agent by fuzzy name match. Returns dict with id, name, etc."""
    from psycopg2.extras import RealDictCursor

    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT id, name, first_name, last_name, department, model, status
        FROM agents
        WHERE LOWER(name) LIKE %s
           OR LOWER(first_name) LIKE %s
           OR LOWER(last_name) LIKE %s
        ORDER BY status = 'active' DESC, id
        LIMIT 1
    """,
        (f"%{name.lower()}%", f"%{name.lower()}%", f"%{name.lower()}%"),
    )
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def resolve_department_by_name(name: str, conn) -> dict | None:
    """Find a department by fuzzy name match against the agents table."""
    from psycopg2.extras import RealDictCursor

    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT DISTINCT department, floor
        FROM agents
        WHERE LOWER(department) LIKE %s
          AND status = 'active'
        ORDER BY department
        LIMIT 1
    """,
        (f"%{name.lower()}%",),
    )
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None
