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

_raw_host = os.getenv('OLLAMA_HOST', 'http://host.docker.internal:11434')
OLLAMA_HOST = _raw_host if _raw_host.startswith('http') else f'http://{_raw_host}'
EXTRACTION_MODEL = os.getenv('ARCHIE_CHAT_MODEL', 'dolphin3:latest')

AVAILABLE_DEPARTMENTS = [
    'Engineering', 'Operations', 'Customer Support', 'Marketing',
    'Finance', 'Legal', 'HR', 'Security', 'Documentation',
    'AI Operations', 'Creative', 'Research', 'Compliance', 'Administration'
]

AVAILABLE_STATIONS = [
    'COMMAND', 'CONSCIOUSNESS', 'HR', 'RND', 'OPERATIONS',
    'ENGINEERING', 'CREATIVE', 'SECURITY', 'MEDICAL', 'AWAY_TEAM'
]

AVAILABLE_MODELS = [
    'dolphin3:latest', 'qwen2.5:7b', 'tinyllama', 'nomic-embed-text'
]

# Template prompts for different action types
TEMPLATES = {
    'create_agent': """Extract agent creation parameters from this request.
Return ONLY valid JSON, no explanation.

Available Ollama models (local, free): {models}
Available departments: {departments}

Request: "{message}"

JSON format:
{{"model": "string (pick best model for the role)", "first_name": "string", "last_name": "string", "department": "string", "title": "string", "system_prompt": "string (brief role description)", "capabilities": ["string"]}}

JSON:""",

    'assign_station': """Extract station assignment parameters from this request.
Return ONLY valid JSON, no explanation.

Available stations: {stations}

Request: "{message}"

JSON format:
{{"agent_name": "string", "station_code": "string (UPPERCASE)", "assignment_type": "primary"}}

JSON:""",

    'agent_action': """Extract agent action parameters from this request.
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
    if '```' in text:
        blocks = text.split('```')
        for block in blocks[1::2]:  # odd-indexed blocks are inside backticks
            block = block.strip()
            if block.startswith('json'):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    # Try to find JSON object in text
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
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
        models=', '.join(AVAILABLE_MODELS),
        departments=', '.join(AVAILABLE_DEPARTMENTS),
        stations=', '.join(AVAILABLE_STATIONS),
    )

    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": EXTRACTION_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 4096}
            },
            timeout=120  # M4000 cold starts can be slow
        )
        resp.raise_for_status()

        text = resp.json().get("response", "").strip()
        logger.info("Param extraction response: %s", text[:300])

        result = _parse_json_from_response(text)

        # Normalize station codes to uppercase
        if 'station_code' in result:
            result['station_code'] = result['station_code'].upper()

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
    cur.execute("""
        SELECT id, name, first_name, last_name, department, model, status
        FROM agents
        WHERE LOWER(name) LIKE %s
           OR LOWER(first_name) LIKE %s
           OR LOWER(last_name) LIKE %s
        ORDER BY status = 'active' DESC, id
        LIMIT 1
    """, (f"%{name.lower()}%", f"%{name.lower()}%", f"%{name.lower()}%"))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def resolve_station_by_name(name: str, conn) -> dict | None:
    """Find station by code or name match."""
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, station_code, station_name, full_name
        FROM bridge_stations
        WHERE UPPER(station_code) = %s
           OR LOWER(station_name) LIKE %s
           OR LOWER(full_name) LIKE %s
        ORDER BY id
        LIMIT 1
    """, (name.upper(), f"%{name.lower()}%", f"%{name.lower()}%"))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None
