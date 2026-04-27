"""
Agent Academy — Model Routes

Model configuration, A/B testing history, system prompt management.
"""

import json
import logging
import urllib.request

from flask import jsonify, request
from database import get_db_cursor

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://192.168.1.200:11434"


def register_model_routes(bp, admin_required):
    """Register model management API routes on the blueprint."""

    @bp.route("/api/models/agents")
    @admin_required
    def model_agents():
        """List agents with their model configs."""
        department = request.args.get("department")
        with get_db_cursor() as (conn, cur):
            if department:
                cur.execute(
                    """SELECT id, name, display_name, department, model,
                              temperature, max_tokens, system_prompt, shift_state
                       FROM agents
                       WHERE status = 'active' AND department = %s
                       ORDER BY display_name""",
                    (department,),
                )
            else:
                cur.execute(
                    """SELECT id, name, display_name, department, model,
                              temperature, max_tokens, system_prompt, shift_state
                       FROM agents
                       WHERE status = 'active'
                       ORDER BY department, display_name"""
                )
            agents = []
            for row in cur.fetchall():
                a = dict(row)
                a["temperature"] = float(a["temperature"]) if a["temperature"] else 0.7
                # Truncate system prompt for list view
                sp = a.get("system_prompt") or ""
                a["system_prompt_preview"] = sp[:200] + ("..." if len(sp) > 200 else "")
                a["system_prompt"] = sp
                agents.append(a)

        return jsonify({"agents": agents})

    @bp.route("/api/models/update", methods=["POST"])
    @admin_required
    def update_model_config():
        """Update agent model configuration.

        Body: {agent_id, model?, temperature?, max_tokens?, system_prompt?}
        """
        data = request.get_json(force=True)
        agent_id = data.get("agent_id")
        if not agent_id:
            return jsonify({"error": "agent_id required"}), 400

        from services.agent_service import get_agent, update_agent

        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        # Build update fields
        fields = {}
        if "model" in data and data["model"]:
            fields["model"] = data["model"]
        if "temperature" in data:
            fields["temperature"] = max(0.0, min(2.0, float(data["temperature"])))
        if "max_tokens" in data:
            fields["max_tokens"] = max(256, min(32768, int(data["max_tokens"])))
        if "system_prompt" in data:
            fields["system_prompt"] = data["system_prompt"]

        if not fields:
            return jsonify({"error": "No fields to update"}), 400

        update_agent(agent_id, **fields)

        return jsonify(
            {
                "success": True,
                "agent_id": agent_id,
                "updated_fields": list(fields.keys()),
            }
        )

    @bp.route("/api/models/available")
    @admin_required
    def available_models():
        """List available Ollama models (loaded + all tags)."""
        loaded = []
        all_models = []

        # Get currently loaded models
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/ps", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                loaded = [
                    {
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                        "size_vram": m.get("size_vram", 0),
                        "expires_at": m.get("expires_at", ""),
                    }
                    for m in data.get("models", [])
                ]
        except Exception as e:
            logger.warning("Failed to get loaded models: %s", e)

        # Get all available models
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                all_models = [
                    {
                        "name": m.get("name", ""),
                        "size": m.get("size", 0),
                        "modified_at": m.get("modified_at", ""),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "quantization": m.get("details", {}).get("quantization_level", ""),
                        "family": m.get("details", {}).get("family", ""),
                    }
                    for m in data.get("models", [])
                ]
        except Exception as e:
            logger.warning("Failed to get model tags: %s", e)

        loaded_names = {m["name"] for m in loaded}

        return jsonify(
            {
                "loaded": loaded,
                "available": all_models,
                "loaded_count": len(loaded),
                "available_count": len(all_models),
                "loaded_names": list(loaded_names),
            }
        )

    @bp.route("/api/knowledge/agents")
    @admin_required
    def knowledge_agents():
        """List agents with system prompt previews for knowledge tab."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, name, display_name, department, model, system_prompt
                   FROM agents
                   WHERE status = 'active'
                   ORDER BY department, display_name"""
            )
            agents = []
            for row in cur.fetchall():
                a = dict(row)
                sp = a.get("system_prompt") or ""
                a["system_prompt_preview"] = sp[:300] + ("..." if len(sp) > 300 else "")
                a["system_prompt_length"] = len(sp)
                a["has_system_prompt"] = bool(sp.strip())
                agents.append(a)

        return jsonify({"agents": agents})

    @bp.route("/api/knowledge/update-prompt", methods=["POST"])
    @admin_required
    def update_system_prompt():
        """Update agent system prompt.

        Body: {agent_id, system_prompt}
        """
        data = request.get_json(force=True)
        agent_id = data.get("agent_id")
        system_prompt = data.get("system_prompt", "")

        if not agent_id:
            return jsonify({"error": "agent_id required"}), 400

        # Reject obviously malformed or test-marker prompts
        _TEST_MARKERS = ("CONFIRM-TEST", "e2e-", "test-marker", "placeholder")
        if system_prompt and len(system_prompt.strip()) < 30:
            return jsonify({"error": "system_prompt too short — must be at least 30 characters"}), 400
        if any(m.lower() in system_prompt.lower() for m in _TEST_MARKERS):
            return jsonify({"error": "system_prompt contains a test marker — use a real prompt"}), 400

        from services.agent_service import get_agent, update_agent

        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        update_agent(agent_id, system_prompt=system_prompt)

        return jsonify(
            {
                "success": True,
                "agent_id": agent_id,
                "agent_name": agent.get("display_name") or agent.get("name"),
                "prompt_length": len(system_prompt),
            }
        )
