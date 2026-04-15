"""Modelfile Sync — exports agent system_prompt from DB to Ollama Modelfile.

Called automatically when system_prompt is updated via Roster UI.
The Modelfile creates a named model in Ollama that wraps a base model
with the agent's personality/instructions as the SYSTEM prompt.
"""

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

MODELFILE_DIR = "/mnt/llm_drive/ollama"
OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://host.docker.internal:11434")


def export_modelfile(agent_name, model_base, system_prompt):
    """Write a Modelfile and register it with Ollama.

    Args:
        agent_name: Agent code name (used as model name in Ollama)
        model_base: Base model (e.g., 'mistral:7b')
        system_prompt: The agent's system prompt text

    Returns:
        dict with success, message, and modelfile_path
    """
    if not system_prompt or not system_prompt.strip():
        return {"success": False, "message": "No system prompt provided"}
    if not model_base or not model_base.strip():
        return {"success": False, "message": "No base model specified"}

    # Sanitize agent name for filename (lowercase, no spaces)
    safe_name = agent_name.lower().replace(" ", "-").replace(".", "")
    modelfile_path = os.path.join(MODELFILE_DIR, f"Modelfile.{safe_name}")

    # Build Modelfile content
    # Escape triple quotes in system prompt
    escaped_prompt = system_prompt.replace('"""', '\\"\\"\\"')
    content = f'FROM {model_base}\n\nSYSTEM """\n{escaped_prompt}\n"""\n'

    try:
        # Write Modelfile to disk
        os.makedirs(MODELFILE_DIR, exist_ok=True)
        with open(modelfile_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Exported Modelfile for %s to %s", agent_name, modelfile_path)
    except Exception as e:
        logger.error("Failed to write Modelfile for %s: %s", agent_name, e)
        return {"success": False, "message": f"File write failed: {e}"}

    # Register with Ollama via API (create endpoint)
    try:
        payload = json.dumps(
            {
                "name": safe_name,
                "modelfile": content,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/create",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=120)
        # Ollama streams response — read to completion
        resp.read()
        logger.info("Ollama registered model %s from base %s", safe_name, model_base)
        return {
            "success": True,
            "message": f"Model {safe_name} created from {model_base}",
            "modelfile_path": modelfile_path,
        }
    except Exception as e:
        logger.warning(
            "Ollama create failed for %s (Modelfile saved to disk): %s",
            safe_name,
            e,
        )
        return {
            "success": True,  # File was written even if Ollama registration failed
            "message": f"Modelfile saved but Ollama registration failed: {e}",
            "modelfile_path": modelfile_path,
        }


def delete_modelfile(agent_name):
    """Remove a Modelfile from disk (does not remove from Ollama)."""
    safe_name = agent_name.lower().replace(" ", "-").replace(".", "")
    modelfile_path = os.path.join(MODELFILE_DIR, f"Modelfile.{safe_name}")
    try:
        if os.path.exists(modelfile_path):
            os.remove(modelfile_path)
            logger.info("Deleted Modelfile for %s", agent_name)
            return True
    except Exception as e:
        logger.error("Failed to delete Modelfile for %s: %s", agent_name, e)
    return False
