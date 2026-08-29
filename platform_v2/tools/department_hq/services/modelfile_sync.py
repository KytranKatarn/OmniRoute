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

    # Build Modelfile content (the on-disk AUDIT copy only — see below)
    # Escape triple quotes in system prompt
    escaped_prompt = system_prompt.replace('"""', '\\"\\"\\"')
    content = f'FROM {model_base}\n\nSYSTEM """\n{escaped_prompt}\n"""\n'

    # 1. REGISTER WITH OLLAMA FIRST — the functional step, and it needs NO file on
    #    disk (the payload is self-contained). The old order wrote the file first
    #    and returned on failure, so from archie_platform — where /mnt/llm_drive is
    #    mounted read-only (models subdir only) — registration was NEVER attempted
    #    (#6115, hit live on the V.I.V.I.D./W.E.A.V.E. hires 2026-08-28).
    #
    #    Modern structured create: Ollama removed the legacy {"name","modelfile"}
    #    fields from /api/create (the hub host service runs 0.16.2), so the old
    #    payload would have failed even WITH the file written — two defects, one
    #    function. {"model","from","system"} is the current schema.
    registered = False
    reg_err = ""
    try:
        payload = json.dumps(
            {
                "model": safe_name,
                "from": model_base,
                "system": system_prompt,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/create",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=120)
        # Ollama streams JSON status lines; an error can arrive IN the stream with
        # an HTTP 200, so read to completion and scan rather than trusting the code.
        body = resp.read()
        if b'"error"' in body:
            reg_err = body[-300:].decode("utf-8", errors="replace")
        else:
            registered = True
            logger.info("Ollama registered model %s from base %s", safe_name, model_base)
    except Exception as e:
        reg_err = str(e)

    # 2. Best-effort audit copy. Writable only where /mnt/llm_drive is rw (host,
    #    scheduler-adjacent tooling); from archie_platform this fails and MUST NOT
    #    block or fail the sync — the registration above is what agents run on.
    disk_note = ""
    try:
        os.makedirs(MODELFILE_DIR, exist_ok=True)
        with open(modelfile_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Exported Modelfile audit copy for %s to %s", agent_name, modelfile_path)
    except Exception as e:
        logger.warning("Modelfile audit copy not written for %s (read-only mount is normal here): %s", agent_name, e)
        disk_note = " (audit copy not written: read-only mount)"
        modelfile_path = None

    if registered:
        return {
            "success": True,
            "message": f"Model {safe_name} created from {model_base}{disk_note}",
            "modelfile_path": modelfile_path,
        }
    logger.warning("Ollama create failed for %s: %s", safe_name, reg_err)
    return {
        "success": False,
        "message": f"Ollama registration failed: {reg_err}{disk_note}",
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
