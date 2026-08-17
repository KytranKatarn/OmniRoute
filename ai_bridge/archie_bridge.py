"""
A.R.C.H.I.E. Bridge - Smart AI Model Router
Intelligently routes requests to the best available AI model
WITH MEMORY INTEGRATION - She remembers everything!
"""

import logging
import os
import sys
import requests
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Add platform directory to path for imports
sys.path.insert(0, "/app")
from consciousness.memory_manager import get_memory_context, learn_from_conversation
from consciousness.archie_tools import read_file, edit_file, write_file
from db import get_db, _get_db_password

# Import new learning loop modules
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

try:
    from conversation_ingest import (
        ingest_conversation,
        retrieve_similar_conversations,
        get_archie_personality,
    )
except ImportError:

    def ingest_conversation(*args, **kwargs):
        return {"success": True, "memory_id": 0}

    def retrieve_similar_conversations(*args, **kwargs):
        return []

    def get_archie_personality():
        return {
            "confidence_level": 0.7,
            "cautiousness": 0.5,
            "enthusiasm": 0.8,
            "empathy": 0.7,
            "curiosity": 0.9,
        }


# Import LOCAL-FIRST knowledge retrieval (Phase 3)
try:
    from knowledge_retrieval import get_relevant_knowledge, check_for_known_mistakes

    LOCAL_KNOWLEDGE_AVAILABLE = True
except ImportError as e:
    print(f"[AI Bridge] WARNING: Local knowledge retrieval not available: {e}")
    LOCAL_KNOWLEDGE_AVAILABLE = False

    def get_relevant_knowledge(*args, **kwargs):
        return ""

    def check_for_known_mistakes(*args, **kwargs):
        return None


try:
    from emotional_intelligence import (
        analyze_sentiment,
        analyze_trust_impact,
        generate_learning_response_prefix,
    )
except ImportError:

    def analyze_sentiment(text):
        return {"sentiment": "neutral", "confidence": 0.5, "emotions": []}

    def analyze_trust_impact(conversation):
        return 0.0

    def generate_learning_response_prefix(personality, sentiment):
        return ""


# Smart LLM Router (Phase 32-37)
SMART_ROUTING_AVAILABLE = False
try:
    from tools.department_hq.services.smart_router import get_router, classify_task

    SMART_ROUTING_AVAILABLE = True
except ImportError:
    print("[AI Bridge] Smart routing not available")

    def get_router():
        return None

    def classify_task(prompt, context=None):
        return "code_simple"


# Node Router for dynamic Ollama routing (Phase 71) and Image Services (Phase 72)
NODE_ROUTING_AVAILABLE = False
IMAGE_ROUTING_AVAILABLE = False
try:
    from node_router import (
        get_ollama_url,
        log_model_request,
        get_fallback_host,
        # Image generation services (Phase 72)
        get_foocus_url,
        get_comfyui_url,
        get_auto1111_url,
    )

    NODE_ROUTING_AVAILABLE = True
    IMAGE_ROUTING_AVAILABLE = True
    print("[AI Bridge] Node routing enabled - dynamic model and image routing active")
except ImportError as e:
    print(f"[AI Bridge] Node routing not available: {e}")

    def get_ollama_url(model_name, prefer_gpu=True):
        return os.getenv("OLLAMA_HOST", "http://localhost:11434"), None

    def log_model_request(*args, **kwargs):
        pass

    def get_fallback_host():
        return os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def get_foocus_url():
        return os.getenv("FOOOCUS_URL", "http://localhost:7865"), None

    def get_comfyui_url():
        return os.getenv("COMFYUI_URL", "http://localhost:8188"), None

    def get_auto1111_url():
        return os.getenv("AUTO1111_URL", "http://localhost:7860"), None


def call_ollama_json(
    prompt,
    model="dolphin3-8k:latest",
    system_prompt=None,
    max_retries=2,
    timeout=120,
    options=None,
):
    """
    Call Ollama with structured JSON output enforcement.

    Uses Ollama's format=json parameter and validates the response.
    Retries with correction prompt on malformed JSON.

    Args:
        prompt: The prompt (should ask for JSON output)
        model: Ollama model to use
        system_prompt: Optional system prompt
        max_retries: Retries on malformed JSON (default 2)
        timeout: Request timeout in seconds

    Returns:
        {'success': bool, 'data': dict|None, 'raw': str, 'error': str|None}
    """
    ollama_host, node_id = get_ollama_url(model, prefer_gpu=True)

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "model": model,
                "prompt": (
                    prompt
                    if attempt == 0
                    else (
                        f"Your previous response was not valid JSON. "
                        f"Please respond with ONLY valid JSON.\n\n{prompt}"
                    )
                ),
                "stream": False,
                "format": "json",
            }
            if system_prompt:
                payload["system"] = system_prompt
            if options:
                payload["options"] = options

            resp = requests.post(
                f"{ollama_host}/api/generate",
                json=payload,
                timeout=timeout,
            )

            if resp.status_code != 200:
                continue

            ollama_response = resp.json()
            raw = ollama_response.get("response", "")
            # Extract token counts so DispatchResult / agent_budgets get real
            # usage data. Without these, every JSON-mode dispatch logged 0
            # tokens and welfare digest false-flagged working agents as
            # "starving" (Bug B, 2026-05-03).
            _jpt = ollama_response.get("prompt_eval_count", 0)
            _jct = ollama_response.get("eval_count", 0)
            _jest = False
            # Estimate each side independently (#4230) — see call_ollama for rationale.
            if not _jpt and (prompt or system_prompt):
                _jpt = _estimate_tokens((system_prompt or "") + (prompt or ""))
                _jest = True
            if not _jct and raw:
                _jct = _estimate_tokens(raw)
                _jest = True
            tokens_meta = {
                "prompt_tokens": _jpt,
                "completion_tokens": _jct,
                "tokens_estimated": _jest,
                "model": model,
                "provider": "ollama",
            }
            data = json.loads(raw)
            return {"success": True, "data": data, "raw": raw, "error": None, **tokens_meta}

        except json.JSONDecodeError:
            # Try to extract JSON from markdown fences or mixed text
            import re as _re

            match = _re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    data = json.loads(match.group())
                    return {"success": True, "data": data, "raw": raw, "error": None, **tokens_meta}
                except json.JSONDecodeError:
                    pass
            continue
        except Exception as e:
            return {"success": False, "data": None, "raw": "", "error": str(e)}

    return {
        "success": False,
        "data": None,
        "raw": raw if "raw" in dir() else "",
        "error": f"Failed to get valid JSON after {max_retries + 1} attempts",
    }


def detect_current_environment():
    """
    Detect the current execution environment (Phase 23)

    Returns:
        str: 'production', 'sandbox_full', or 'sandbox_<module>'

    Detection order:
    1. Check ARCHIE_ENVIRONMENT env var (explicit setting)
    2. Check if running in a sandbox Docker container
    3. Check if database schema suggests sandbox
    4. Default to 'production'
    """
    # 1. Check explicit environment variable
    env_var = os.getenv("ARCHIE_ENVIRONMENT")
    if env_var:
        return env_var

    # 2. Check if running in sandbox container (has _sandbox in hostname)
    import socket

    hostname = socket.gethostname()
    if "_sandbox" in hostname or "sandbox" in hostname.lower():
        # Try to extract module name from container name
        parts = hostname.split("_")
        for i, part in enumerate(parts):
            if part == "sandbox" and i > 0:
                return f"sandbox_{parts[i-1]}"
        return "sandbox_full"

    # 3. Check database schema search_path for sandbox indicator
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SHOW search_path")
            search_path = cur.fetchone()[0]

            if "sandbox" in search_path.lower():
                # Extract module name from schema like 'sandbox_coderabbit'
                for schema in search_path.split(","):
                    schema = schema.strip()
                    if schema.startswith("sandbox_"):
                        module = schema.replace("sandbox_", "")
                        return f"sandbox_{module}"
                return "sandbox_full"
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.debug("Environment detection failed, defaulting to production: %s", e)

    # 4. Default to production
    return "production"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for when Ollama omits eval counts.

    Ollama drops prompt_eval_count on a prompt-cache hit (e.g. a classify model
    called repeatedly with a stable system prompt → qwen25-classify logged 0 tokens
    for 93% of calls, task #4230). This keeps token tracking non-zero for real
    generation; callers tag the result `tokens_estimated=True` so it's distinguishable
    from exact counts.
    """
    return max(1, len(text or "") // 4) if text else 0


def call_ollama(
    prompt,
    model="dolphin3-8k:latest",
    system_prompt=None,
    context=None,
    prefer_gpu=True,
    timeout=300,
    options=None,
):
    """
    Call Ollama API with dynamic node routing (Phase 71)

    Routes requests to the best available bridge-enabled node that has the model.
    Falls back to OLLAMA_HOST environment variable if no nodes available.

    Args:
        prompt: The user's prompt
        model: Preferred model (default: deepseek-coder-v2:16b)
        system_prompt: Optional system prompt for behavior guidance
        context: Optional context from previous conversation
        prefer_gpu: Whether to prefer GPU-enabled nodes (default: True)

    Returns:
        {
            'success': bool,
            'response': str,
            'model': str,  # Actual model used
            'provider': 'ollama',
            'node_id': str or None,  # Node that handled request
            'node_url': str  # URL used
        }
    """
    import time

    # Route cloud models to ollama.com API
    if ":cloud" in model or model in ("minimax-m2.5", "qwen3-coder-next"):
        return call_ollama_cloud(prompt, model=model, system_prompt=system_prompt)

    start_time = time.time()

    # Get the best node for this model (Phase 71: Dynamic Node Routing)
    ollama_host, node_id = get_ollama_url(model, prefer_gpu)

    payload = {"model": model, "prompt": prompt, "stream": False}

    if system_prompt:
        payload["system"] = system_prompt

    if context:
        payload["context"] = context
    if options:
        payload["options"] = options

    try:
        response = requests.post(
            f"{ollama_host}/api/generate",
            json=payload,
            timeout=timeout,
        )

        response_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            result = response.json()

            # Log successful request (Phase 71)
            if NODE_ROUTING_AVAILABLE and node_id:
                log_model_request(
                    node_id=node_id,
                    model_name=model,
                    request_type="generate",
                    tokens_in=result.get("prompt_eval_count"),
                    tokens_out=result.get("eval_count"),
                    response_ms=response_ms,
                    success=True,
                )

            _resp_text = result.get("response", "")
            _pt = result.get("prompt_eval_count", 0)
            _ct = result.get("eval_count", 0)
            _estimated = False
            # Estimate each side INDEPENDENTLY (#4230): Ollama omits prompt_eval_count on a
            # prompt-cache hit (warm classify model), and eval_count on a tiny/empty completion.
            # A real classify call still processed its input prompt, so count it even when the
            # response is empty — don't gate the prompt estimate on having a response.
            if not _pt and (prompt or system_prompt):
                _pt = _estimate_tokens((system_prompt or "") + (prompt or ""))
                _estimated = True
            if not _ct and _resp_text:
                _ct = _estimate_tokens(_resp_text)
                _estimated = True
            return {
                "success": True,
                "response": _resp_text,
                "model": model,
                "provider": "ollama",
                "context": result.get("context"),
                "node_id": node_id,
                "node_url": ollama_host,
                "response_ms": response_ms,
                # Surface token counts so DispatchResult / task_execution_log /
                # agent_budgets track real usage; estimate when Ollama omits them (#4230).
                "prompt_tokens": _pt,
                "completion_tokens": _ct,
                "tokens_estimated": _estimated,
            }
        else:
            # Log failed request
            if NODE_ROUTING_AVAILABLE and node_id:
                log_model_request(
                    node_id=node_id,
                    model_name=model,
                    response_ms=response_ms,
                    success=False,
                    error_message=f"HTTP {response.status_code}",
                )

            return {
                "success": False,
                "error": f"Ollama API error: {response.status_code}",
                "model": model,
                "provider": "ollama",
                "node_id": node_id,
                "node_url": ollama_host,
            }

    except Exception as e:
        response_ms = int((time.time() - start_time) * 1000)

        # Log failed request
        if NODE_ROUTING_AVAILABLE and node_id:
            log_model_request(
                node_id=node_id,
                model_name=model,
                response_ms=response_ms,
                success=False,
                error_message=str(e),
            )

        return {
            "success": False,
            "error": str(e),
            "model": model,
            "provider": "ollama",
            "node_id": node_id,
            "node_url": ollama_host,
        }


def _log_cloud_usage(
    model,
    provider,
    prompt_tokens,
    completion_tokens,
    response_ms,
    success=True,
    error_message=None,
    session_id=None,
    agent_id=None,
    task_type=None,
):
    """Log cloud model usage to cloud_model_usage table."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cloud_model_usage
                (model_name, provider, prompt_tokens, completion_tokens, total_tokens,
                 response_ms, success, error_message, session_id, agent_id, task_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                model,
                provider,
                prompt_tokens,
                completion_tokens,
                prompt_tokens + completion_tokens,
                response_ms,
                success,
                error_message,
                session_id,
                agent_id,
                task_type,
            ),
        )
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to log cloud usage: {e}")
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def call_ollama_cloud(
    prompt,
    model="qwen3-coder-next",  # was minimax-m2.5 — retired 2026-08-17 (#5706), 410s on every dispatch
    system_prompt=None,
    session_id=None,
    agent_id=None,
    task_type=None,
):
    """
    Call Ollama Cloud API (ollama.com) for cloud-hosted models.

    Uses OLLAMA_API_KEY for authentication. Cloud models run on Ollama's
    infrastructure — no local GPU needed. All calls are logged to
    cloud_model_usage for weekly/session tracking.

    Supported models: qwen3-coder-next (minimax-m2.5 retired 2026-08-17, #5706)
    """
    import time

    start_time = time.time()
    api_key = os.getenv("OLLAMA_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "OLLAMA_API_KEY not configured",
            "model": model,
            "provider": "ollama_cloud",
        }

    # Strip :cloud suffix if present (ollama.com uses base model names)
    cloud_model = model.replace(":cloud", "")

    payload = {"model": cloud_model, "prompt": prompt, "stream": False}
    if system_prompt:
        payload["system"] = system_prompt

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.post(
            "https://ollama.com/api/generate",
            json=payload,
            headers=headers,
            timeout=300,
        )

        response_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            result = response.json()
            prompt_tokens = result.get("prompt_eval_count", 0)
            completion_tokens = result.get("eval_count", 0)

            # Log usage
            _log_cloud_usage(
                model=cloud_model,
                provider="ollama_cloud",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                response_ms=response_ms,
                success=True,
                session_id=session_id,
                agent_id=agent_id,
                task_type=task_type,
            )

            return {
                "success": True,
                "response": result.get("response", ""),
                "thinking": result.get("thinking", ""),
                "model": model,
                "provider": "ollama_cloud",
                "node_id": None,
                "node_url": "https://ollama.com",
                "response_ms": response_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        else:
            _log_cloud_usage(
                model=cloud_model,
                provider="ollama_cloud",
                prompt_tokens=0,
                completion_tokens=0,
                response_ms=response_ms,
                success=False,
                error_message=f"HTTP {response.status_code}",
                session_id=session_id,
                agent_id=agent_id,
                task_type=task_type,
            )
            return {
                "success": False,
                "error": f"Ollama Cloud API error: {response.status_code} - {response.text[:200]}",
                "model": model,
                "provider": "ollama_cloud",
            }

    except Exception as e:
        _log_cloud_usage(
            model=cloud_model,
            provider="ollama_cloud",
            prompt_tokens=0,
            completion_tokens=0,
            response_ms=int((time.time() - start_time) * 1000),
            success=False,
            error_message=str(e)[:500],
            session_id=session_id,
            agent_id=agent_id,
            task_type=task_type,
        )
        return {
            "success": False,
            "error": str(e),
            "model": model,
            "provider": "ollama_cloud",
        }


def call_claude_api(prompt, model="claude-sonnet-4-20250514", system_prompt=None):
    """
    Call Claude API (Anthropic)

    Requires CLAUDE_API_KEY environment variable
    """
    api_key = os.getenv("CLAUDE_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "Claude API key not configured",
            "model": model,
            "provider": "claude",
        }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }

    if system_prompt:
        payload["system"] = system_prompt

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            usage = result.get("usage", {})
            return {
                "success": True,
                "response": result["content"][0]["text"],
                "model": model,
                "provider": "claude",
                "tokens_used": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
            }
        else:
            return {
                "success": False,
                "error": f"Claude API error: {response.status_code}",
                "model": model,
                "provider": "claude",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": "claude"}


def call_openai_api(prompt, model="gpt-4-turbo", system_prompt=None):
    """
    Call OpenAI API

    Requires OPENAI_API_KEY environment variable
    """
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "OpenAI API key not configured",
            "model": model,
            "provider": "openai",
        }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages, "max_tokens": 4096}

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            usage = result.get("usage", {})
            return {
                "success": True,
                "response": result["choices"][0]["message"]["content"],
                "model": model,
                "provider": "openai",
                "tokens_used": usage.get("total_tokens", 0),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        else:
            return {
                "success": False,
                "error": f"OpenAI API error: {response.status_code}",
                "model": model,
                "provider": "openai",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": "openai"}


def generate_image(
    prompt,
    model="dall-e-3",
    size="1024x1024",
    quality="standard",
    style="vivid",
    requesting_agent=None,
    task_type="avatar_generation",
):
    """
    Generate image using OpenAI DALL-E API with full tracking and learning.

    Args:
        prompt: Text description of the image to generate
        model: Image model ('dall-e-3' or 'dall-e-2')
        size: Image dimensions ('1024x1024', '1024x1792', '1792x1024' for DALL-E 3)
        quality: 'standard' or 'hd' (DALL-E 3 only)
        style: 'vivid' or 'natural' (DALL-E 3 only)
        requesting_agent: Agent ID requesting the generation (for tracking)
        task_type: Type of generation task for learning categorization

    Returns:
        dict with success, image_url, revised_prompt, and metadata
    """
    import requests
    from datetime import datetime

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "success": False,
            "error": "OpenAI API key not configured. Set OPENAI_API_KEY environment variable.",
            "model": model,
            "provider": "openai_image",
        }

    # Pricing for DALL-E (per image)
    dalle_pricing = {
        "dall-e-3": {
            "1024x1024": {"standard": 0.04, "hd": 0.08},
            "1024x1792": {"standard": 0.08, "hd": 0.12},
            "1792x1024": {"standard": 0.08, "hd": 0.12},
        },
        "dall-e-2": {
            "1024x1024": {"standard": 0.02},
            "512x512": {"standard": 0.018},
            "256x256": {"standard": 0.016},
        },
    }

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {"model": model, "prompt": prompt, "n": 1, "size": size}

        # DALL-E 3 specific options
        if model == "dall-e-3":
            payload["quality"] = quality
            payload["style"] = style

        start_time = datetime.now()

        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers=headers,
            json=payload,
            timeout=120,
        )

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if response.status_code == 200:
            data = response.json()
            image_data = data["data"][0]
            image_url = image_data.get("url")
            revised_prompt = image_data.get("revised_prompt", prompt)

            # Calculate cost
            cost = dalle_pricing.get(model, {}).get(size, {}).get(quality, 0.04)

            # Log usage to database
            try:
                conn = get_db()
                try:
                    cur = conn.cursor()

                    cur.execute(
                        """
                        INSERT INTO token_usage_log
                        (agent_id, provider, model, prompt_tokens, completion_tokens, tokens_used, cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            requesting_agent,
                            "openai_dalle",
                            model,
                            len(prompt.split()),  # Approximate prompt "tokens"
                            0,
                            len(prompt.split()),
                            cost,
                        ),
                    )

                    conn.commit()

                    print(
                        f"[archie_bridge] Logged image generation: model={model}, cost=${cost:.4f}, agent={requesting_agent}"
                    )
                finally:
                    try:
                        cur.close()
                        conn.close()
                    except Exception:
                        pass

            except Exception as log_error:
                print(f"Warning: Failed to log image generation: {log_error}")

            return {
                "success": True,
                "image_url": image_url,
                "revised_prompt": revised_prompt,
                "model": model,
                "provider": "openai_image",
                "cost": cost,
                "duration_ms": duration_ms,
                "metadata": {"size": size, "quality": quality, "style": style},
            }
        else:
            error_msg = response.json().get("error", {}).get("message", f"HTTP {response.status_code}")

            # Log failed attempt (cost=0)
            try:
                conn = get_db()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO token_usage_log
                        (agent_id, provider, model, prompt_tokens, completion_tokens, tokens_used, cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            requesting_agent,
                            "openai_dalle",
                            model,
                            len(prompt.split()),
                            0,
                            0,
                            0,
                        ),
                    )
                    conn.commit()
                    print(f"[archie_bridge] Logged failed image generation: {error_msg[:100]}")
                finally:
                    try:
                        cur.close()
                        conn.close()
                    except Exception:
                        pass
            except Exception:
                pass

            return {
                "success": False,
                "error": error_msg,
                "model": model,
                "provider": "openai_image",
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Image generation timed out (120s limit)",
            "model": model,
            "provider": "openai_image",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "model": model,
            "provider": "openai_image",
        }


# ============================================================================
# LOCAL IMAGE GENERATION (Fooocus) - Phase 51 + Dynamic Routing (Phase 72)
# Generate images using local Stable Diffusion XL via Fooocus API
# Routes to best available node with Fooocus when multiple nodes available
# ============================================================================


def check_fooocus_health():
    """
    Quick health check for Fooocus server.

    Uses dynamic node routing to check the best available Foocus node.

    Returns:
        bool: True if Fooocus is available and responding
    """
    try:
        # Use dynamic routing (Phase 72)
        fooocus_url, node_id = get_foocus_url()
        response = requests.get(f"{fooocus_url}/docs", timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.debug("Fooocus health check failed: %s", e)
        return False


def generate_image_local(
    prompt,
    style="default",
    size="1024x1024",
    performance="Speed",
    negative_prompt="",
    requesting_agent=None,
    task_type="image_generation",
):
    """
    Generate image using local Fooocus API (Stable Diffusion XL).

    Uses dynamic node routing (Phase 72) to select the best available
    node with Foocus. Prefers GPU-enabled nodes for faster generation.

    Args:
        prompt: Text description of image to generate
        style: Fooocus style preset ('default', 'realistic', 'anime',
               'artistic', 'cinematic', 'digital-art')
        size: Image dimensions ('1024x1024', '1792x1024', '1024x1792')
        performance: 'Speed', 'Quality', or 'Extreme Speed'
        negative_prompt: Things to avoid in the image
        requesting_agent: Agent ID for tracking
        task_type: Categorization for learning

    Returns:
        {
            success: bool,
            image_url: str (base64 data URL or file path),
            model: 'fooocus-sdxl',
            provider: 'fooocus_local',
            cost: 0.0,  # Always free for local
            duration_ms: int,
            metadata: {style, size, performance},
            node_id: str or None,  # Node that processed request
            node_url: str  # URL used
        }
    """
    # Dynamic node routing for Foocus (Phase 72)
    fooocus_url, node_id = get_foocus_url()
    timeout = int(os.getenv("IMAGE_LOCAL_TIMEOUT", "180"))

    # Map styles to Fooocus presets
    style_mapping = {
        "default": ["Fooocus V2", "Fooocus Enhance", "Fooocus Sharp"],
        "realistic": ["Fooocus Photograph", "Fooocus Enhance", "Fooocus Sharp"],
        "anime": ["SAI Anime", "SAI Digital Art"],
        "artistic": ["MRE Spontaneous Picture", "SAI Enhance"],
        "cinematic": ["SAI Cinematic", "Fooocus Sharp", "Fooocus Enhance"],
        "digital-art": ["SAI Digital Art", "Fooocus Sharp", "Fooocus Enhance"],
    }

    # Map sizes to aspect ratios
    aspect_mapping = {
        "1024x1024": "1024×1024",
        "1792x1024": "1792×1024",
        "1024x1792": "1024×1792",
        "1280x720": "1280×720",
        "720x1280": "720×1280",
        "512x512": "512×512",
    }

    # Build payload for Fooocus API
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "low quality, blurry, distorted",
        "style_selections": style_mapping.get(style, style_mapping["default"]),
        "performance_selection": performance,
        "aspect_ratios_selection": aspect_mapping.get(size, "1024×1024"),
        "image_number": 1,
        "image_seed": -1,
        "sharpness": 2.0,
        "guidance_scale": 7.0,
        "async_process": False,
        "require_base64": True,
    }

    try:
        start_time = datetime.now()

        response = requests.post(f"{fooocus_url}/v1/generation/text-to-image", json=payload, timeout=timeout)

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if response.status_code == 200:
            data = response.json()

            # Handle response format (can be list or dict)
            if isinstance(data, list) and len(data) > 0:
                image_data = data[0]
            else:
                image_data = data

            # Get image URL (base64 or file path)
            image_url = image_data.get("base64")
            if image_url and not image_url.startswith("data:"):
                image_url = f"data:image/png;base64,{image_url}"

            if not image_url:
                image_url = image_data.get("url", "")

            # Log to database (cost=0 for local)
            try:
                conn = get_db()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO token_usage_log
                        (agent_id, provider, model, prompt_tokens, completion_tokens, tokens_used, cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            requesting_agent,
                            "fooocus_local",
                            "fooocus-sdxl",
                            len(prompt.split()),
                            0,
                            len(prompt.split()),
                            0.0,
                        ),
                    )
                    conn.commit()
                    print(f"[archie_bridge] Logged local image generation: style={style}, duration={duration_ms}ms")
                finally:
                    try:
                        cur.close()
                        conn.close()
                    except Exception:
                        pass
            except Exception as log_error:
                print(f"Warning: Failed to log local image generation: {log_error}")

            return {
                "success": True,
                "image_url": image_url,
                "model": "fooocus-sdxl",
                "provider": "fooocus_local",
                "cost": 0.0,
                "duration_ms": duration_ms,
                "metadata": {"style": style, "size": size, "performance": performance},
                "node_id": node_id,
                "node_url": fooocus_url,
            }
        else:
            error_msg = f"Fooocus API error: {response.status_code}"
            try:
                error_data = response.json()
                if "detail" in error_data:
                    error_msg = error_data["detail"]
            except Exception:
                pass

            return {
                "success": False,
                "error": error_msg,
                "model": "fooocus-sdxl",
                "provider": "fooocus_local",
                "node_id": node_id,
                "node_url": fooocus_url,
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": f"Local image generation timed out ({timeout}s limit)",
            "model": "fooocus-sdxl",
            "provider": "fooocus_local",
            "node_id": node_id,
            "node_url": fooocus_url,
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"Cannot connect to Fooocus server at {fooocus_url}. Is it running?",
            "model": "fooocus-sdxl",
            "provider": "fooocus_local",
            "node_id": node_id,
            "node_url": fooocus_url,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "model": "fooocus-sdxl",
            "provider": "fooocus_local",
            "node_id": node_id,
            "node_url": fooocus_url,
        }


def generate_image_smart(
    prompt,
    style="default",
    size="1024x1024",
    quality="standard",
    prefer_local=None,
    requesting_agent=None,
    task_type="image_generation",
):
    """
    Smart image generation router - local first, paid fallback.

    Routing Logic:
    1. Try Fooocus (local, free) if prefer_local=True
    2. Fallback to DALL-E 3 (paid) if local fails
    3. Track all attempts for learning

    Args:
        prompt: Text description of image
        style: Style preset for generation
        size: Image dimensions
        quality: 'standard' or 'hd' (for DALL-E fallback)
        prefer_local: Override local preference (uses IMAGE_PREFER_LOCAL env if None)
        requesting_agent: Agent ID for tracking
        task_type: Task categorization

    Returns:
        Standard response format with 'provider' indicating source
    """
    # Determine local preference
    if prefer_local is None:
        prefer_local = os.getenv("IMAGE_PREFER_LOCAL", "true").lower() == "true"

    routing_info = {
        "local_attempted": False,
        "local_available": False,
        "fallback_used": False,
    }

    if prefer_local:
        # Check if Fooocus is available
        routing_info["local_available"] = check_fooocus_health()

        if routing_info["local_available"]:
            routing_info["local_attempted"] = True

            # Try local Fooocus first
            result = generate_image_local(
                prompt=prompt,
                style=style,
                size=size,
                requesting_agent=requesting_agent,
                task_type=task_type,
            )

            if result.get("success"):
                print(f"[archie_bridge] Image generated locally (FREE): style={style}")
                result["routing"] = routing_info
                return result
            else:
                print(f"[archie_bridge] Local generation failed: {result.get('error')}")
                routing_info["fallback_used"] = True
        else:
            print("[archie_bridge] Fooocus not available, using DALL-E fallback")
            routing_info["fallback_used"] = True

    # Fallback to DALL-E (or if prefer_local=False)
    # Map styles for DALL-E
    dalle_style = "vivid" if style in ["anime", "artistic", "digital-art"] else "natural"

    result = generate_image(
        prompt=prompt,
        model="dall-e-3",
        size=size,
        quality=quality,
        style=dalle_style,
        requesting_agent=requesting_agent,
        task_type=task_type,
    )

    result["routing"] = routing_info
    return result


# ============================================================================
# VISION/IMAGE ANALYSIS (Ollama) - Phase 51
# Analyze images using local vision models (minicpm-v, llava)
# ============================================================================


def analyze_image(
    image_path=None,
    image_url=None,
    image_base64=None,
    prompt="Describe this image in detail",
    model=None,
    timeout=120,
):
    """
    Analyze image using Ollama vision model.

    Args:
        image_path: Local file path to image
        image_url: URL to fetch image from
        image_base64: Base64 encoded image data
        prompt: Question or instruction about the image
        model: Vision model to use (defaults to VISION_MODEL_PRIMARY env)

    Returns:
        {
            success: bool,
            response: str (analysis result),
            model: str,
            provider: 'ollama_vision',
            cost: 0.0
        }
    """
    import base64

    if model is None:
        model = os.getenv("VISION_MODEL_PRIMARY", "minicpm-v:8b")

    # Use node routing for vision models too (Phase 71)
    ollama_host, node_id = get_ollama_url(model, prefer_gpu=True)

    # Get image as base64
    img_data = None

    if image_base64:
        # Already have base64
        img_data = image_base64
        # Strip data URL prefix if present
        if img_data.startswith("data:"):
            img_data = img_data.split(",")[1]
    elif image_path:
        # Read from file
        try:
            with open(image_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read image file: {e}",
                "model": model,
                "provider": "ollama_vision",
            }
    elif image_url:
        # Fetch from URL
        try:
            response = requests.get(image_url, timeout=30)
            if response.status_code == 200:
                img_data = base64.b64encode(response.content).decode("utf-8")
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch image: HTTP {response.status_code}",
                    "model": model,
                    "provider": "ollama_vision",
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to fetch image: {e}",
                "model": model,
                "provider": "ollama_vision",
            }
    else:
        return {
            "success": False,
            "error": "No image provided. Supply image_path, image_url, or image_base64",
            "model": model,
            "provider": "ollama_vision",
        }

    # Build Ollama vision request
    payload = {"model": model, "prompt": prompt, "images": [img_data], "stream": False}

    try:
        start_time = datetime.now()

        response = requests.post(f"{ollama_host}/api/generate", json=payload, timeout=timeout)

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if response.status_code == 200:
            result = response.json()

            # Log usage (cost=0 for local)
            try:
                conn = get_db()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO token_usage_log
                        (agent_id, provider, model, prompt_tokens, completion_tokens, tokens_used, cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            None,  # No specific agent
                            "ollama_vision",
                            model,
                            len(prompt.split()),
                            len(result.get("response", "").split()),
                            len(prompt.split()) + len(result.get("response", "").split()),
                            0.0,
                        ),
                    )
                    conn.commit()
                    print(f"[archie_bridge] Vision analysis complete: model={model}, duration={duration_ms}ms")
                finally:
                    try:
                        cur.close()
                        conn.close()
                    except Exception:
                        pass
            except Exception as log_error:
                print(f"Warning: Failed to log vision analysis: {log_error}")

            # Log model request (Phase 71)
            if NODE_ROUTING_AVAILABLE and node_id:
                log_model_request(
                    node_id=node_id,
                    model_name=model,
                    request_type="generate",
                    response_ms=duration_ms,
                    success=True,
                )

            return {
                "success": True,
                "response": result.get("response", ""),
                "model": model,
                "provider": "ollama_vision",
                "cost": 0.0,
                "duration_ms": duration_ms,
                "node_id": node_id,
                "node_url": ollama_host,
            }
        else:
            if NODE_ROUTING_AVAILABLE and node_id:
                log_model_request(
                    node_id=node_id,
                    model_name=model,
                    success=False,
                    error_message=f"HTTP {response.status_code}",
                )
            return {
                "success": False,
                "error": f"Ollama vision error: {response.status_code}",
                "model": model,
                "provider": "ollama_vision",
                "node_id": node_id,
            }

    except requests.exceptions.Timeout:
        if NODE_ROUTING_AVAILABLE and node_id:
            log_model_request(
                node_id=node_id,
                model_name=model,
                success=False,
                error_message="Timeout",
            )
        return {
            "success": False,
            "error": f"Vision analysis timed out ({timeout}s limit)",
            "model": model,
            "provider": "ollama_vision",
            "node_id": node_id,
        }
    except Exception as e:
        if NODE_ROUTING_AVAILABLE and node_id:
            log_model_request(node_id=node_id, model_name=model, success=False, error_message=str(e))
        return {
            "success": False,
            "error": str(e),
            "model": model,
            "provider": "ollama_vision",
            "node_id": node_id,
        }


def enhance_image_prompt(basic_prompt, style="realistic"):
    """
    Enhance a basic prompt for better image generation results.
    Uses local Ollama model for free enhancement.

    Args:
        basic_prompt: Simple description
        style: Target style ('realistic', 'anime', 'artistic', 'cinematic', 'digital-art')

    Returns:
        str: Enhanced prompt
    """
    style_hints = {
        "realistic": "photorealistic, detailed, 8k resolution, professional photography, natural lighting",
        "anime": "anime style, vibrant colors, detailed linework, studio quality, dynamic pose",
        "artistic": "artistic, painterly, masterpiece quality, fine art, museum worthy",
        "cinematic": "cinematic lighting, dramatic, movie still, professional cinematography, anamorphic",
        "digital-art": "digital art, sharp details, trending on artstation, highly detailed, concept art",
    }

    system_prompt = f"""You are an expert at writing prompts for AI image generation (Stable Diffusion).
Enhance the following prompt to create a better image. Add specific details about:
- Subject details and positioning
- Lighting and atmosphere
- Composition and framing
- Technical quality keywords
- Style-specific elements

The target style is: {style}
Style keywords to incorporate: {style_hints.get(style, style_hints['realistic'])}

Keep it concise (under 150 words). Output ONLY the enhanced prompt, nothing else.
Do not include any explanations or preamble."""

    user_prompt = f"Original prompt: {basic_prompt}"

    # Use local Ollama model for enhancement (free)
    result = call_ollama(prompt=user_prompt, model="dolphin3:latest", system_prompt=system_prompt)

    if result.get("success"):
        enhanced = result.get("response", basic_prompt).strip()
        # Clean up any markdown or quotes
        enhanced = enhanced.strip("`\"'")
        if len(enhanced) > 20:  # Sanity check
            return enhanced

    # Fallback: just add style hints
    return f"{basic_prompt}, {style_hints.get(style, style_hints['realistic'])}"


def get_default_provider():
    """
    Get default AI provider from database settings
    Returns: (provider_name, model_name) tuple
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT provider, model_name
                FROM archie_api_settings
                WHERE enabled = TRUE AND is_default = TRUE
                LIMIT 1
            """
            )

            result = cur.fetchone()

            if result:
                return (result["provider"], result["model_name"])
            else:
                # Fallback to Ollama
                return ("ollama", "dolphin3-8k:latest")
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    except Exception as e:
        print(f"Error getting default provider: {e}")
        return ("ollama", "dolphin3-8k:latest")


def calculate_cost(provider, model, tokens_used, prompt_tokens=0, completion_tokens=0):
    """
    Calculate cost for API usage

    Returns: float (cost in USD)
    """
    # Pricing per 1M tokens (as of Dec 2024)
    pricing = {
        "claude": {
            "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
            "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
        },
        "openai": {
            "gpt-4-turbo": {"input": 10.0, "output": 30.0},
            "gpt-4": {"input": 30.0, "output": 60.0},
            "gpt-4o": {"input": 2.5, "output": 10.0},
            "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
            "o1-preview": {"input": 15.0, "output": 60.0},
        },
        "grok": {
            "grok-beta": {"input": 5.0, "output": 15.0},
            "grok-vision-beta": {"input": 5.0, "output": 15.0},
        },
        "gemini": {
            "gemini-2.0-flash-exp": {
                "input": 0.0,
                "output": 0.0,
            },  # Free during preview
            "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
            "gemini-1.5-flash": {"input": 0.075, "output": 0.3},
        },
        "cohere": {
            "command-r-plus": {"input": 3.0, "output": 15.0},
            "command-r": {"input": 0.5, "output": 1.5},
            "command": {"input": 1.0, "output": 2.0},
        },
        "mistral": {
            "mistral-large-latest": {"input": 4.0, "output": 12.0},
            "mistral-medium-latest": {"input": 2.7, "output": 8.1},
            "mistral-small-latest": {"input": 1.0, "output": 3.0},
            "codestral-latest": {"input": 1.0, "output": 3.0},
        },
        "ollama": {
            # Local models have no API cost
            "*": {"input": 0.0, "output": 0.0}
        },
    }

    if provider == "ollama":
        return 0.0

    if provider not in pricing or model not in pricing[provider]:
        # Unknown model, estimate conservatively
        return (tokens_used / 1_000_000) * 10.0

    model_pricing = pricing[provider][model]

    if prompt_tokens > 0 and completion_tokens > 0:
        # We have detailed token counts
        input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * model_pricing["output"]
        return input_cost + output_cost
    else:
        # Estimate: assume 30% input, 70% output
        input_cost = (tokens_used * 0.3 / 1_000_000) * model_pricing["input"]
        output_cost = (tokens_used * 0.7 / 1_000_000) * model_pricing["output"]
        return input_cost + output_cost


def track_token_usage(agent_id, provider, model, tokens_used, cost, user_id=None):
    """
    Track token usage and costs in database

    Returns: dict with budget warning if applicable
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Record usage
            cur.execute(
                """
                INSERT INTO token_usage_log
                (agent_id, user_id, provider, model, tokens_used, cost, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
                (agent_id, user_id, provider, model, tokens_used, cost),
            )

            # Update agent metrics
            cur.execute(
                """
                UPDATE agents
                SET total_tokens_used = COALESCE(total_tokens_used, 0) + %s,
                    total_cost = COALESCE(total_cost, 0) + %s,
                    last_used = NOW()
                WHERE id = %s
            """,
                (tokens_used, cost, agent_id),
            )

            # Check budget limits
            cur.execute(
                """
                SELECT
                    a.name,
                    a.monthly_budget,
                    a.total_cost,
                    a.budget_alert_threshold,
                    COALESCE(
                        (SELECT SUM(cost)
                         FROM token_usage_log
                         WHERE agent_id = a.id
                         AND created_at >= DATE_TRUNC('month', NOW())
                        ), 0
                    ) as monthly_cost
                FROM agents a
                WHERE a.id = %s
            """,
                (agent_id,),
            )

            agent_data = cur.fetchone()
            conn.commit()
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

        warning = None
        if agent_data and agent_data["monthly_budget"]:
            monthly_budget = float(agent_data["monthly_budget"])
            monthly_cost = float(agent_data["monthly_cost"])
            threshold = float(agent_data.get("budget_alert_threshold") or 0.8)

            usage_percent = (monthly_cost / monthly_budget) * 100 if monthly_budget > 0 else 0

            if monthly_cost >= monthly_budget:
                warning = {
                    "level": "critical",
                    "message": f"🚨 BUDGET EXCEEDED: {agent_data['name']} has used ${monthly_cost:.2f} of ${monthly_budget:.2f} monthly budget!",
                    "usage_percent": usage_percent,
                    "monthly_cost": monthly_cost,
                    "monthly_budget": monthly_budget,
                }
            elif monthly_cost >= (monthly_budget * threshold):
                warning = {
                    "level": "warning",
                    "message": f"⚠️ BUDGET WARNING: {agent_data['name']} has used ${monthly_cost:.2f} of ${monthly_budget:.2f} monthly budget ({usage_percent:.1f}%)",
                    "usage_percent": usage_percent,
                    "monthly_cost": monthly_cost,
                    "monthly_budget": monthly_budget,
                }

            # Insert budget alert for HR/C.R.E.E.D. tracking (if warning triggered)
            if warning:
                try:
                    conn2 = get_db()
                    try:
                        cur2 = conn2.cursor()
                        # Check if similar alert exists in last hour to avoid spam
                        cur2.execute(
                            """
                            SELECT id FROM budget_alerts
                            WHERE agent_id = %s
                              AND alert_level = %s
                              AND created_at > NOW() - INTERVAL '1 hour'
                              AND acknowledged = false
                            LIMIT 1
                        """,
                            (agent_id, warning["level"]),
                        )
                        existing = cur2.fetchone()

                        if not existing:
                            cur2.execute(
                                """
                                INSERT INTO budget_alerts
                                (agent_id, alert_level, message, usage_percent, monthly_cost, monthly_budget)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                                (
                                    agent_id,
                                    warning["level"],
                                    warning["message"],
                                    usage_percent,
                                    monthly_cost,
                                    monthly_budget,
                                ),
                            )
                            conn2.commit()
                            print(f"[AI Bridge] Budget alert recorded for agent {agent_id}: {warning['level']}")
                    finally:
                        try:
                            cur2.close()
                            conn2.close()
                        except Exception:
                            pass
                except Exception as alert_err:
                    print(f"[AI Bridge] Error recording budget alert: {alert_err}")

        return {"success": True, "warning": warning}

    except Exception as e:
        print(f"Error tracking token usage: {e}")
        return {"success": False, "error": str(e)}


def _parse_bridge_intent(prompt, original_prompt, user_id, enable_memory, try_local_first):
    """
    Extract intent, retrieve knowledge, and check for local answers.

    Returns:
        dict with keys:
            prompt (str): possibly enriched prompt
            memory_used (bool)
            local_knowledge_used (bool)
            similar_conversations (list)
            local_answer (dict or None): if answerable locally, the full return dict
    """
    memory_used = False
    similar_conversations = []
    local_knowledge_used = False

    if not (enable_memory and user_id):
        return {
            "prompt": prompt,
            "memory_used": memory_used,
            "local_knowledge_used": local_knowledge_used,
            "similar_conversations": similar_conversations,
            "local_answer": None,
        }

    # STEP 1: Check for known mistakes FIRST (highest priority!)
    if LOCAL_KNOWLEDGE_AVAILABLE:
        try:
            mistake_warning = check_for_known_mistakes(original_prompt)
            if mistake_warning:
                memory_used = True
                local_knowledge_used = True
                prompt = mistake_warning + "\n\n" + prompt
                print(f"[AI Bridge] Known mistake detected - prepended warning to prompt")
        except Exception as e:
            print(f"[AI Bridge] Error checking for known mistakes: {e}")

    # STEP 2: Get relevant knowledge from unified knowledge base
    if LOCAL_KNOWLEDGE_AVAILABLE:
        try:
            local_knowledge = get_relevant_knowledge(original_prompt, max_results=5)
            if local_knowledge:
                memory_used = True
                local_knowledge_used = True
                prompt = local_knowledge + "\n\n" + prompt
                print(f"[AI Bridge] Local knowledge retrieved and prepended to prompt")
        except Exception as e:
            print(f"[AI Bridge] Error retrieving local knowledge: {e}")

    # STEP 2.5: Try local answer generation (Phase 3)
    # Check user preference from database (Week 2: per-user control)
    user_wants_local_answers = try_local_first  # Default to parameter
    if user_id and not try_local_first:
        try:
            # Query user preference from database
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "archie_database"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )
            cur = conn.cursor()
            cur.execute("SELECT enable_local_answers FROM users WHERE id = %s", (user_id,))
            result = cur.fetchone()
            if result:
                user_wants_local_answers = result[0]
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[AI Bridge] Error checking user local answer preference: {e}")

    if user_wants_local_answers and LOCAL_KNOWLEDGE_AVAILABLE and enable_memory:
        try:
            from local_answer_generator import (
                can_answer_locally,
                generate_local_response,
                estimate_cost_savings,
                track_local_answer_usage,
            )
            from knowledge_retrieval import get_relevant_knowledge_enhanced

            # Get enhanced knowledge results (structured data)
            knowledge_results = get_relevant_knowledge_enhanced(
                original_prompt,
                max_results=10,
                use_semantic=False,  # Start with keyword-only, add semantic later
            )

            if knowledge_results:
                # Evaluate if we can answer locally
                decision = can_answer_locally(original_prompt, knowledge_results)

                if decision["can_answer"]:
                    print(
                        f"[AI Bridge] LOCAL ANSWER: confidence={decision['confidence']:.2f}, strategy={decision['strategy']}"
                    )

                    # Generate local response
                    local_response = generate_local_response(
                        original_prompt,
                        knowledge_results,
                        strategy=decision["strategy"],
                    )

                    # Determine what model would have been used
                    provider, model = get_default_provider()

                    # Track cost savings
                    track_local_answer_usage(
                        query=original_prompt,
                        knowledge_ids=[r["id"] for r in knowledge_results[:5]],
                        confidence=decision["confidence"],
                        strategy=decision["strategy"],
                        user_id=user_id,
                        default_model=model,
                        default_provider=provider,
                    )

                    # Estimate savings
                    savings = estimate_cost_savings(original_prompt, model, provider)

                    print(f"[AI Bridge] Cost saved: ${savings['cost_saved']:.4f}, tokens: {savings['tokens_saved']}")

                    # Return early with local answer
                    local_answer = {
                        "success": True,
                        "response": local_response,
                        "model": "local-knowledge",
                        "provider": "archie-brain",
                        "local_answer": True,
                        "confidence": decision["confidence"],
                        "strategy": decision["strategy"],
                        "knowledge_entries_used": len(knowledge_results),
                        "tokens_used": 0,
                        "cost": 0.0,
                        "cost_saved": savings["cost_saved"],
                        "tokens_saved": savings["tokens_saved"],
                        "memory_used": True,
                        "memories_learned": 0,  # Don't re-learn from local answers
                        "local_knowledge_used": True,
                    }
                    return {
                        "prompt": prompt,
                        "memory_used": memory_used,
                        "local_knowledge_used": local_knowledge_used,
                        "similar_conversations": similar_conversations,
                        "local_answer": local_answer,
                    }
                else:
                    print(f"[AI Bridge] Local answer not confident enough: {decision['reason']}")

        except Exception as e:
            print(f"[AI Bridge] Error in local answer generation: {e}")
            import traceback

            traceback.print_exc()
            # Fall through to LLM

    # STEP 3: Fallback to conversation memory (old system)
    try:
        # NEW: Use tag-based RAG retrieval
        similar_conversations = retrieve_similar_conversations(
            query=original_prompt,
            user_id=user_id,
            max_results=3,
            min_importance=0.4,
        )

        if similar_conversations:
            memory_used = True
            # Build context from similar conversations
            memory_context = "## Relevant Knowledge from A.R.C.H.I.E.'s Memory:\n\n"
            for i, conv in enumerate(similar_conversations, 1):
                memory_context += f"{i}. {conv.get('summary', conv.get('user_message', '')[:100])}\n"
                if conv.get("ai_response"):
                    memory_context += f"   Response: {conv['ai_response'][:200]}...\n"
                memory_context += f"   Tags: {', '.join(conv.get('tags', []))}\n\n"

            # Prepend memory context to prompt
            prompt = f"{memory_context}\n---\n\nCurrent Question: {prompt}"
    except Exception as e:
        print(f"Error retrieving similar conversations: {e}")
        # Fallback to old memory system
        memory_context = get_memory_context(original_prompt, user_id=user_id, max_context=3)
        if memory_context:
            memory_used = True
            prompt = f"{memory_context}\n\n{prompt}"

    return {
        "prompt": prompt,
        "memory_used": memory_used,
        "local_knowledge_used": local_knowledge_used,
        "similar_conversations": similar_conversations,
        "local_answer": None,
    }


def _select_bridge_model(
    original_prompt,
    prompt,
    context,
    force_model,
    use_smart_routing,
    task_type,
    complexity,
    agent_id,
):
    """
    Determine which model/provider to use via smart routing or force_model.

    Returns:
        tuple: (provider_or_none, model_or_none, routing_info_or_none)
            provider is None when force_model is used (embedded in the call).
    """
    routing_info = None
    smart_routed_model = None
    smart_routed_provider = None

    if use_smart_routing and SMART_ROUTING_AVAILABLE and not force_model:
        try:
            router = get_router()
            if router:
                # Classify task if not provided
                detected_task_type = task_type or classify_task(original_prompt, context)

                # Get routing recommendation
                recommendation = router.suggest_model(
                    task_type=detected_task_type,
                    complexity=complexity,
                    context_tokens=len(prompt) // 4,  # Rough token estimate
                    agent_id=agent_id,
                    failure_count=0,  # Could be enhanced to track failures
                )

                smart_routed_model = recommendation.model_name
                smart_routed_provider = recommendation.provider

                routing_info = {
                    "tier": recommendation.tier,
                    "task_type": detected_task_type,
                    "reason": recommendation.reason,
                    "escalated": recommendation.should_escalate,
                    "claude_as_judge": recommendation.use_claude_as_judge,
                    "estimated_cost": recommendation.estimated_cost,
                }

                print(f"[AI Bridge] Smart routing: {detected_task_type} → {recommendation.tier} ({smart_routed_model})")

        except Exception as e:
            print(f"[AI Bridge] Smart routing error: {e}, falling back to default")

    if force_model:
        return None, force_model, routing_info
    elif smart_routed_model and smart_routed_provider:
        return smart_routed_provider, smart_routed_model, routing_info
    else:
        provider, model = get_default_provider()
        return provider, model, routing_info


def _execute_bridge_call(prompt, context, system_prompt, provider, model, force_model):
    """
    Execute the actual LLM call based on provider/model selection.

    Args:
        prompt: The (possibly enriched) prompt
        context: Conversation context
        system_prompt: System prompt override
        provider: Provider name (None if force_model is used)
        model: Model name
        force_model: Original force_model param (if set, provider is None)

    Returns:
        dict: Raw result from the LLM call
    """
    if force_model:
        # Parse force_model to determine provider
        # Check for Ollama format first (contains colon like "mistral:latest", "llama3.1:8b")
        # These should route to Ollama, not cloud APIs
        is_ollama_format = ":" in force_model and not force_model.startswith("http")

        if is_ollama_format:
            # Ollama model format - route to local Ollama
            return call_ollama(prompt, model=force_model, system_prompt=system_prompt, context=context)
        elif "grok" in force_model.lower():
            return call_grok_api(prompt, model=force_model, system_prompt=system_prompt)
        elif "gemini" in force_model.lower():
            return call_gemini_api(prompt, model=force_model, system_prompt=system_prompt)
        elif "command" in force_model.lower() or "cohere" in force_model.lower():
            return call_cohere_api(prompt, model=force_model, system_prompt=system_prompt)
        elif "mistral" in force_model.lower() or "codestral" in force_model.lower():
            return call_mistral_api(prompt, model=force_model, system_prompt=system_prompt)
        elif "gpt" in force_model.lower() or "o1" in force_model.lower():
            return call_openai_api(prompt, model=force_model, system_prompt=system_prompt)
        elif "claude" in force_model.lower():
            return call_claude_api(prompt, model=force_model, system_prompt=system_prompt)
        else:
            # Assume Ollama
            return call_ollama(prompt, model=force_model, system_prompt=system_prompt, context=context)
    else:
        if provider == "ollama":
            return call_ollama(prompt, model=model, system_prompt=system_prompt, context=context)
        elif provider == "claude":
            return call_claude_api(prompt, model=model, system_prompt=system_prompt)
        elif provider == "openai":
            return call_openai_api(prompt, model=model, system_prompt=system_prompt)
        elif provider == "grok":
            return call_grok_api(prompt, model=model, system_prompt=system_prompt)
        elif provider == "gemini":
            return call_gemini_api(prompt, model=model, system_prompt=system_prompt)
        elif provider == "cohere":
            return call_cohere_api(prompt, model=model, system_prompt=system_prompt)
        elif provider == "mistral":
            return call_mistral_api(prompt, model=model, system_prompt=system_prompt)
        else:
            # Fallback
            return call_ollama(prompt, system_prompt=system_prompt, context=context)


def _log_bridge_result(
    result,
    original_prompt,
    user_id,
    agent_id,
    enable_memory,
    memory_used,
    local_knowledge_used,
    similar_conversations,
    environment,
    routing_info,
    task_type,
):
    """
    Handle cost calculation, token tracking, conversation learning, and bridge logging.

    Mutates `result` dict in place (adds cost, memory stats, routing info, etc.).

    Returns:
        int: memories_learned count
    """
    memories_learned = 0

    # Calculate cost
    tokens_used = result.get("tokens_used", 0)
    prompt_tokens = result.get("prompt_tokens", 0)
    completion_tokens = result.get("completion_tokens", 0)

    cost = calculate_cost(
        result.get("provider", "ollama"),
        result.get("model", ""),
        tokens_used,
        prompt_tokens,
        completion_tokens,
    )

    result["cost"] = cost

    # Track token usage if agent_id provided
    budget_warning = None
    if agent_id and tokens_used > 0:
        tracking_result = track_token_usage(
            agent_id,
            result.get("provider"),
            result.get("model"),
            tokens_used,
            cost,
            user_id,
        )
        budget_warning = tracking_result.get("warning")
        result["budget_warning"] = budget_warning

    # Learn from this conversation with emotional intelligence
    if enable_memory and user_id and result.get("success"):
        try:
            # Use new ingest_conversation with auto-tagging and emotional learning
            learning_result = ingest_conversation(
                user_message=original_prompt,  # Use original, not memory-enhanced
                ai_response=result.get("response", ""),
                user_id=user_id,
                source="archie_bridge",
                model=result.get("model"),
                provider=result.get("provider"),
                environment=environment,  # Phase 23: Track sandbox vs production
                metadata={
                    "agent_id": agent_id,
                    "memory_retrieval_used": memory_used,
                    "similar_conversations_count": len(similar_conversations),
                    "tokens_used": tokens_used,
                    "cost": cost,
                },
            )

            if learning_result.get("success"):
                memories_learned = 1  # Successfully stored
                result["sentiment"] = learning_result.get("sentiment")
                result["trust_impact"] = learning_result.get("trust_impact")
                result["tags_applied"] = learning_result.get("tags_applied", [])
                result["importance_score"] = learning_result.get("importance_score", 0)

                # Add emotional response prefix if applicable
                emotional_context = {
                    "sentiment": learning_result.get("sentiment", {}).get("sentiment"),
                    "user_emotion": learning_result.get("sentiment", {}).get("user_emotion"),
                    "should_double_check": learning_result.get("trust_impact", {}).get("should_double_check"),
                    "trust_delta": learning_result.get("trust_impact", {}).get("trust_delta", 0),
                }

                # Generate personality-aware response prefix
                response_prefix = generate_learning_response_prefix(emotional_context)
                if response_prefix and result.get("response"):
                    result["response"] = response_prefix + result["response"]
                    result["personality_aware"] = True

        except Exception as e:
            print(f"Error with new learning system: {e}")
            import traceback

            traceback.print_exc()
            # Fallback to old system
            try:
                memories_learned = learn_from_conversation(
                    user_id=user_id,
                    user_message=original_prompt,
                    ai_response=result.get("response", ""),
                    conversation_metadata={
                        "model": result.get("model"),
                        "provider": result.get("provider"),
                        "timestamp": datetime.now().isoformat(),
                    },
                )
            except Exception as e2:
                print(f"Error with fallback learning: {e2}")
                memories_learned = 0

    # Add memory stats to result
    result["memory_used"] = memory_used
    result["memories_learned"] = memories_learned
    result["local_knowledge_used"] = local_knowledge_used  # Phase 3: Track local-first retrieval
    result["environment"] = environment  # Phase 23: Track environment context

    # Add smart routing info if used (Phase 32-37)
    if routing_info:
        result["routing_info"] = routing_info
        # Track execution in smart router if available
        if SMART_ROUTING_AVAILABLE and agent_id:
            try:
                router = get_router()
                if router:
                    router.track_execution(
                        agent_id=agent_id,
                        task_type=routing_info.get("task_type", "code_simple"),
                        tier=routing_info.get("tier", "sonnet"),
                        model=result.get("model", ""),
                        provider=result.get("provider", "ollama"),
                        outcome="success" if result.get("success") else "failed",
                        tokens=result.get("tokens_used", 0),
                        cost=result.get("cost", 0.0),
                        escalated=routing_info.get("escalated", False),
                        claude_as_judge=routing_info.get("claude_as_judge", False),
                    )
            except Exception as e:
                print(f"[AI Bridge] Error tracking smart routing execution: {e}")

    # ========================================================================
    # PHASE 61: LOG BRIDGE INTERACTION
    # Every call to archie_bridge is logged for analytics and learning
    # ========================================================================
    try:
        # Determine if this was escalated to Claude
        escalated = "claude" in (result.get("provider", "") or "").lower()

        # Extract tags from learning result if available
        tags = result.get("tags_applied", [])

        # Log the interaction
        log_bridge_interaction(
            user_id=user_id,
            module_name="archie_bridge",  # Can be overridden by caller
            agent_id=agent_id,
            intent_type=(task_type or routing_info.get("task_type") if routing_info else None),
            prompt_summary=original_prompt[:500] if original_prompt else None,
            response_summary=(result.get("response", "") or "")[:500],
            model_used=result.get("model"),
            tokens_used=result.get("tokens_used", 0),
            cost_estimate=result.get("cost", 0.0),
            execution_time_ms=None,  # Could add timing
            success=result.get("success", False),
            error_message=result.get("error"),
            escalated_to_claude=escalated,
            tags=tags,
            metadata={
                "memory_used": memory_used,
                "local_knowledge_used": local_knowledge_used,
                "environment": environment,
                "routing_info": routing_info,
            },
        )
    except Exception as e:
        print(f"[AI Bridge] Error in Phase 61 bridge logging: {e}")

    return memories_learned


def archie_bridge(
    prompt,
    context=None,
    user_id=None,
    force_model=None,
    enable_memory=True,
    agent_id=None,
    system_prompt=None,
    try_local_first=False,
    environment="production",
    task_type=None,
    use_smart_routing=False,
    complexity=5,
):
    """
    Main A.R.C.H.I.E. Bridge function - routes to best available AI
    NOW WITH MEMORY INTEGRATION, TOKEN TRACKING & LOCAL ANSWER GENERATION (Phase 3)!
    ENVIRONMENT AWARENESS (Phase 23) - Tracks sandbox vs production context!
    SMART LLM ROUTING (Phase 32-37) - Intelligent model selection for cost optimization!

    Args:
        prompt: The user's question/request
        context: Optional conversation context
        user_id: User ID for memory tracking
        force_model: Force a specific model (e.g., 'deepseek-coder-v2:16b', 'qwen-coder')
        enable_memory: Enable long-term memory system (default: True)
        agent_id: Agent ID for token tracking
        system_prompt: System prompt override
        try_local_first: Try answering from knowledge base before LLM (default: False, Phase 3)
        environment: Environment context - 'production', 'sandbox_full', 'sandbox_<module>' (Phase 23)
        task_type: Task type for smart routing (e.g., 'code_simple', 'architecture')
        use_smart_routing: Enable smart routing for model selection (default: False)
        complexity: Task complexity score 1-10 for routing (default: 5)

    Returns:
        {
            'success': bool,
            'response': str,
            'model': str,
            'provider': str,
            'memory_used': bool,
            'memories_learned': int,
            'tokens_used': int,
            'cost': float,
            'budget_warning': dict (if applicable),
            'local_answer': bool (if answered locally),
            'confidence': float (if local answer),
            'cost_saved': float (if local answer),
            'environment': str (Phase 23: sandbox/production context),
            'routing_info': dict (if smart routing used)
        }
    """
    original_prompt = prompt  # Keep original for learning

    # STEP 1: Parse intent, retrieve knowledge, check local answers
    intent = _parse_bridge_intent(prompt, original_prompt, user_id, enable_memory, try_local_first)

    # If answerable locally, return immediately
    if intent["local_answer"]:
        return intent["local_answer"]

    prompt = intent["prompt"]
    memory_used = intent["memory_used"]
    local_knowledge_used = intent["local_knowledge_used"]
    similar_conversations = intent["similar_conversations"]

    # STEP 2: Select model/provider via smart routing or force_model
    provider, model, routing_info = _select_bridge_model(
        original_prompt,
        prompt,
        context,
        force_model,
        use_smart_routing,
        task_type,
        complexity,
        agent_id,
    )

    # STEP 3: Execute the LLM call
    result = _execute_bridge_call(prompt, context, system_prompt, provider, model, force_model)

    # STEP 4: Log result, track costs, learn from conversation
    _log_bridge_result(
        result,
        original_prompt,
        user_id,
        agent_id,
        enable_memory,
        memory_used,
        local_knowledge_used,
        similar_conversations,
        environment,
        routing_info,
        task_type,
    )

    return result


def test_model(provider="ollama", model=None):
    """Test if a specific AI provider/model is available"""
    test_prompt = "Respond with 'OK' if you can read this."

    try:
        if provider == "ollama":
            if not model:
                model = "dolphin3-8k:latest"
            result = call_ollama(test_prompt, model=model)
        elif provider == "claude":
            if not model:
                model = "claude-sonnet-4-20250514"
            result = call_claude_api(test_prompt, model=model)
        elif provider == "openai":
            if not model:
                model = "gpt-4-turbo"
            result = call_openai_api(test_prompt, model=model)
        else:
            return {"success": False, "error": "Unknown provider"}

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


def call_grok_api(prompt, model="grok-beta", system_prompt=None):
    """
    Call Grok AI API (X.AI)

    Requires GROK_API_KEY environment variable
    Great for: medical, therapy, creative writing, general knowledge
    """
    api_key = os.getenv("GROK_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "Grok API key not configured",
            "model": model,
            "provider": "grok",
        }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.7,
    }

    try:
        response = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            return {
                "success": True,
                "response": result["choices"][0]["message"]["content"],
                "model": model,
                "provider": "grok",
                "tokens_used": result.get("usage", {}).get("total_tokens", 0),
                "prompt_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": result.get("usage", {}).get("completion_tokens", 0),
            }
        else:
            return {
                "success": False,
                "error": f"Grok API error: {response.status_code}",
                "model": model,
                "provider": "grok",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": "grok"}


def call_gemini_api(prompt, model="gemini-2.0-flash-exp", system_prompt=None):
    """
    Call Google Gemini API

    Requires GEMINI_API_KEY environment variable
    Great for: general tasks, multimodal, fast responses
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "Gemini API key not configured",
            "model": model,
            "provider": "gemini",
        }

    # Build request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    # Combine system prompt and user prompt
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\n{prompt}"

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }

    try:
        response = requests.post(url, json=payload, timeout=60)

        if response.status_code == 200:
            result = response.json()

            # Extract response text
            text = result["candidates"][0]["content"]["parts"][0]["text"]

            # Extract token usage
            usage = result.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount", 0)
            completion_tokens = usage.get("candidatesTokenCount", 0)

            return {
                "success": True,
                "response": text,
                "model": model,
                "provider": "gemini",
                "tokens_used": prompt_tokens + completion_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        else:
            return {
                "success": False,
                "error": f"Gemini API error: {response.status_code}",
                "model": model,
                "provider": "gemini",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": "gemini"}


def call_cohere_api(prompt, model="command-r-plus", system_prompt=None):
    """
    Call Cohere API

    Requires COHERE_API_KEY environment variable
    Great for: RAG, search, classification
    """
    api_key = os.getenv("COHERE_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "Cohere API key not configured",
            "model": model,
            "provider": "cohere",
        }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload = {"model": model, "message": prompt, "temperature": 0.7}

    if system_prompt:
        payload["preamble"] = system_prompt

    try:
        response = requests.post("https://api.cohere.ai/v1/chat", headers=headers, json=payload, timeout=60)

        if response.status_code == 200:
            result = response.json()

            # Extract token usage
            usage = result.get("meta", {}).get("billed_units", {})
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

            return {
                "success": True,
                "response": result["text"],
                "model": model,
                "provider": "cohere",
                "tokens_used": prompt_tokens + completion_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        else:
            return {
                "success": False,
                "error": f"Cohere API error: {response.status_code}",
                "model": model,
                "provider": "cohere",
            }

    except Exception as e:
        return {"success": False, "error": str(e), "model": model, "provider": "cohere"}


def call_mistral_api(prompt, model="mistral-large-latest", system_prompt=None):
    """
    Call Mistral AI API

    Requires MISTRAL_API_KEY environment variable
    Great for: European compliance, multilingual, code
    """
    api_key = os.getenv("MISTRAL_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": "Mistral API key not configured",
            "model": model,
            "provider": "mistral",
        }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    try:
        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            usage = result.get("usage", {})

            return {
                "success": True,
                "response": result["choices"][0]["message"]["content"],
                "model": model,
                "provider": "mistral",
                "tokens_used": usage.get("total_tokens", 0),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        else:
            return {
                "success": False,
                "error": f"Mistral API error: {response.status_code}",
                "model": model,
                "provider": "mistral",
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "model": model,
            "provider": "mistral",
        }


# ============================================================================
# CONTRACTOR ROUTING SYSTEM
# Routes requests to external AI contractors based on their API provider
# ============================================================================


def call_contractor(contractor_agent, prompt, system_prompt=None):
    """
    Route a request to a contractor's API based on their provider.

    Args:
        contractor_agent: Dict with contractor info (id, name, api_provider, model, personality_prompt)
        prompt: The prompt to send
        system_prompt: Optional override for system prompt (uses personality_prompt if not provided)

    Returns:
        {
            'success': bool,
            'response': str,
            'provider': str,
            'model': str,
            'tokens_used': int,
            'cost': float
        }
    """
    provider = contractor_agent.get("api_provider", "").lower()
    model = contractor_agent.get("model")

    # Use personality prompt as system prompt if not overridden
    if not system_prompt:
        system_prompt = contractor_agent.get("personality_prompt")

    # Route to appropriate API
    if provider == "anthropic" or provider == "claude":
        result = call_claude_api(
            prompt,
            model=model or "claude-sonnet-4-20250514",
            system_prompt=system_prompt,
        )
    elif provider == "openai":
        result = call_openai_api(prompt, model=model or "gpt-4-turbo", system_prompt=system_prompt)
    elif provider == "google" or provider == "gemini":
        result = call_gemini_api(prompt, model=model or "gemini-2.0-flash-exp", system_prompt=system_prompt)
    elif provider == "x-ai" or provider == "grok":
        result = call_grok_api(prompt, model=model or "grok-beta", system_prompt=system_prompt)
    elif provider == "cohere":
        result = call_cohere_api(prompt, model=model or "command-r-plus", system_prompt=system_prompt)
    elif provider == "mistral":
        result = call_mistral_api(prompt, model=model or "mistral-large-latest", system_prompt=system_prompt)
    else:
        # Fallback to Ollama for unknown providers
        result = call_ollama(prompt, model=model or "dolphin3-8k:latest", system_prompt=system_prompt)

    # Track usage if successful
    if result.get("success"):
        try:
            track_token_usage(
                agent_id=contractor_agent.get("id"),
                provider=result.get("provider", provider),
                model=result.get("model", model),
                tokens_used=result.get("tokens_used", 0),
                cost=result.get("cost", 0.0),
            )
        except Exception as e:
            print(f"Warning: Could not track contractor usage: {e}")

    return result


def get_contractor_proposal(contractor_agent, prompt, proposal_context=None):
    """
    Get a fix proposal from a contractor for an escalated improvement.

    Args:
        contractor_agent: Dict with contractor info
        prompt: The contractor prompt (from test_retry_handler)
        proposal_context: Optional additional context

    Returns:
        {
            'success': bool,
            'proposal': str,
            'code_suggestion': str (extracted if present),
            'explanation': str,
            'confidence': float,
            'tokens_used': int,
            'cost': float
        }
    """
    result = call_contractor(contractor_agent, prompt)

    if not result.get("success"):
        return result

    response = result.get("response", "")

    # Parse response to extract code and explanation
    code_suggestion = ""
    explanation = response

    # Try to extract code blocks
    import re

    code_blocks = re.findall(r"```(?:python|javascript|sql|bash)?\n(.*?)```", response, re.DOTALL)
    if code_blocks:
        code_suggestion = "\n\n".join(code_blocks)
        # Remove code blocks from explanation
        explanation = re.sub(
            r"```(?:python|javascript|sql|bash)?\n.*?```",
            "[CODE BLOCK]",
            response,
            flags=re.DOTALL,
        )

    return {
        "success": True,
        "proposal": response,
        "code_suggestion": code_suggestion,
        "explanation": explanation.strip(),
        "confidence": 0.7,  # Default confidence
        "tokens_used": result.get("tokens_used", 0),
        "cost": result.get("cost", 0.0),
        "provider": result.get("provider"),
        "model": result.get("model"),
    }


def get_contractor_by_id(contractor_id):
    """
    Get contractor agent details by ID.

    Args:
        contractor_id: Agent ID

    Returns:
        Dict with contractor info or None
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT id, name, api_provider, model, personality_prompt,
                       communication_style, worker_type, status
                FROM agents
                WHERE id = %s AND worker_type = 'contract'
            """,
                (contractor_id,),
            )

            contractor = cur.fetchone()
            return dict(contractor) if contractor else None
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    except Exception as e:
        print(f"Error getting contractor: {e}")
        return None


def list_available_contractors():
    """
    Get list of available contractor agents.

    Returns:
        List of contractor dicts
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT id, name, api_provider, model, personality_prompt,
                       communication_style, status, api_enabled
                FROM agents
                WHERE worker_type = 'contract'
                AND status = 'active'
                AND api_enabled = TRUE
                ORDER BY api_provider, name
            """
            )

            contractors = cur.fetchall()
            return [dict(c) for c in contractors]
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    except Exception as e:
        print(f"Error listing contractors: {e}")
        return []


def get_available_models():
    """Get list of available AI models/providers"""
    return {
        "ollama": [
            "dolphin3-8k:latest",
            "qwen3-coder-cpu:latest",
            "qwen25-classify",
            "arctic-embed-cpu",
            "minicpm-v-cpu",
        ],
        "claude": ["claude-sonnet-4-20250514", "claude-opus-4-20250514"],
        "openai": ["gpt-4-turbo", "gpt-4", "gpt-3.5-turbo", "gpt-4o", "o1-preview"],
        "grok": ["grok-beta", "grok-vision-beta"],
        "gemini": ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"],
        "cohere": ["command-r-plus", "command-r", "command"],
        "mistral": [
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "codestral-latest",
        ],
    }


# ============================================================================
# CONTRACTOR APPROVAL SYSTEM (Phase 52)
# Requires admin approval before using paid API contractors
# ============================================================================


def estimate_contractor_cost(prompt, model=None, provider=None):
    """
    Estimate cost of a contractor API call before making it.

    Args:
        prompt: The prompt text
        model: Model name
        provider: API provider

    Returns:
        float: Estimated cost in USD
    """
    # Rough token estimation (4 chars per token average)
    estimated_tokens = len(prompt) / 4

    # Add estimated output tokens (assume 2x input for code tasks)
    estimated_total = estimated_tokens * 3

    # Use existing cost calculation
    return calculate_cost(provider or "openai", model or "gpt-4-turbo", int(estimated_total))


def check_contractor_approval(agent_id, task_type, estimated_cost, user_id=None):
    """
    Check if contractor usage is approved for this task.

    Checks:
    1. Auto-approval threshold (small tasks)
    2. Existing approved request
    3. Budget remaining

    Args:
        agent_id: Contractor agent ID
        task_type: Type of task
        estimated_cost: Estimated API cost
        user_id: Requesting user ID

    Returns:
        {
            'approved': bool,
            'auto_approved': bool,
            'approval_id': int or None,
            'message': str,
            'budget_remaining': float or None
        }
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get agent's approval settings
        cur.execute(
            """
            SELECT
                id, name, worker_type,
                auto_approve_threshold,
                contractor_budget_monthly,
                contractor_usage_this_month,
                requires_api_approval
            FROM agents
            WHERE id = %s
        """,
            (agent_id,),
        )

        agent = cur.fetchone()
        if not agent:
            cur.close()
            conn.close()
            return {
                "approved": False,
                "auto_approved": False,
                "message": f"Agent {agent_id} not found",
            }

        # Internal agents don't need approval
        if agent["worker_type"] != "contract":
            cur.close()
            conn.close()
            return {
                "approved": True,
                "auto_approved": True,
                "message": "Internal agent - no approval needed",
            }

        # Check budget remaining
        budget = float(agent["contractor_budget_monthly"] or 50.0)
        used = float(agent["contractor_usage_this_month"] or 0)
        remaining = budget - used

        if remaining < estimated_cost:
            cur.close()
            conn.close()
            return {
                "approved": False,
                "auto_approved": False,
                "message": f"Budget exceeded. Remaining: ${remaining:.4f}, Estimated: ${estimated_cost:.4f}",
                "budget_remaining": remaining,
            }

        # Check auto-approval threshold
        threshold = float(agent["auto_approve_threshold"] or 0)
        if threshold > 0 and estimated_cost <= threshold:
            cur.close()
            conn.close()
            return {
                "approved": True,
                "auto_approved": True,
                "message": f"Auto-approved: cost ${estimated_cost:.4f} under threshold ${threshold:.4f}",
                "budget_remaining": remaining,
            }

        # Check if approval not required for this agent
        if not agent.get("requires_api_approval", True):
            cur.close()
            conn.close()
            return {
                "approved": True,
                "auto_approved": True,
                "message": "Agent does not require approval",
                "budget_remaining": remaining,
            }

        # Check for existing approved request
        cur.execute(
            """
            SELECT id, status, expires_at
            FROM contractor_approval_requests
            WHERE agent_id = %s
                AND task_type = %s
                AND status = 'approved'
                AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY approved_at DESC
            LIMIT 1
        """,
            (agent_id, task_type),
        )

        existing = cur.fetchone()
        cur.close()
        conn.close()

        if existing:
            return {
                "approved": True,
                "auto_approved": False,
                "approval_id": existing["id"],
                "message": "Pre-approved for this task type",
                "budget_remaining": remaining,
            }

        # Requires manual approval
        return {
            "approved": False,
            "auto_approved": False,
            "needs_approval": True,
            "message": "Contractor usage requires admin approval",
            "budget_remaining": remaining,
            "estimated_cost": estimated_cost,
        }

    except Exception as e:
        print(f"[AI Bridge] Error checking contractor approval: {e}")
        return {
            "approved": False,
            "auto_approved": False,
            "message": f"Error checking approval: {str(e)}",
        }


def request_contractor_approval(
    agent_id,
    user_id,
    task_type,
    task_description,
    module_source=None,
    estimated_cost=0.0,
    contractor_model=None,
    contractor_provider=None,
    priority="normal",
):
    """
    Create a contractor approval request for admin review.

    Args:
        agent_id: Contractor agent ID
        user_id: Requesting user ID
        task_type: Type of task
        task_description: Description of the task
        module_source: Source module requesting
        estimated_cost: Estimated API cost
        contractor_model: Model to use
        contractor_provider: API provider
        priority: 'low', 'normal', 'high', 'urgent'

    Returns:
        {
            'success': bool,
            'approval_id': int,
            'status': str,
            'auto_approved': bool,
            'message': str
        }
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        cur.execute(
            """
            SELECT * FROM request_contractor_approval(
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """,
            (
                agent_id,
                user_id,
                task_type,
                task_description,
                module_source,
                estimated_cost,
                contractor_model,
                contractor_provider,
                priority,
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": True,
            "approval_id": result["approval_id"],
            "status": result["status"],
            "auto_approved": result["auto_approved"],
            "message": result["message"],
        }

    except Exception as e:
        print(f"[AI Bridge] Error requesting contractor approval: {e}")
        return {"success": False, "message": f"Error requesting approval: {str(e)}"}


def log_task_execution(
    agent_id,
    task_type,
    module_source,
    model_used,
    provider,
    tokens_used,
    cost,
    duration_ms,
    success,
    user_id=None,
    error_message=None,
    station_code=None,
    mcp_tool=None,
    request_origin="platform",
):
    """
    Log task execution for HR monitoring and C.R.E.E.D. compliance.

    All tasks (internal and contractor) are logged for:
    - HR productivity tracking
    - C.R.E.E.D. compliance auditing
    - Cost analysis
    - Performance monitoring

    Args:
        agent_id: Agent who performed the task
        task_type: Classification of task
        module_source: Source module (e.g., 'media_studio')
        model_used: LLM model used
        provider: Provider (ollama, anthropic, openai, etc.)
        tokens_used: Total tokens consumed
        cost: Cost in USD (0 for internal)
        duration_ms: Execution time in milliseconds
        success: Whether task succeeded
        user_id: User who requested task
        error_message: Error message if failed
        station_code: Bridge station code
        mcp_tool: MCP tool name if from MCP
        request_origin: 'platform', 'mcp', 'goose', 'api'

    Returns:
        UUID: Execution ID for tracking
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        cur.execute(
            """
            SELECT log_task_execution(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) as execution_id
        """,
            (
                agent_id,
                task_type,
                module_source,
                model_used,
                provider,
                tokens_used,
                cost,
                duration_ms,
                success,
                user_id,
                error_message,
                station_code,
                mcp_tool,
                request_origin,
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return result["execution_id"] if result else None

    except Exception as e:
        print(f"[AI Bridge] Error logging task execution: {e}")
        return None


# ============================================================================
# PHASE 61: BRIDGE LEARNING INTEGRATION
# Log all bridge interactions and enable agent skill acquisition
# ============================================================================


def log_bridge_interaction(
    user_id=None,
    module_name=None,
    agent_id=None,
    intent_type=None,
    prompt_summary=None,
    response_summary=None,
    model_used=None,
    tokens_used=0,
    cost_estimate=0.0,
    execution_time_ms=None,
    success=True,
    error_message=None,
    escalated_to_claude=False,
    tags=None,
    metadata=None,
):
    """
    Log a bridge interaction for analytics and learning.

    This enables:
    - Complete visibility into all AI interactions
    - Tracking which modules use which models
    - Identifying patterns for optimization
    - Agent learning from successful interactions

    Args:
        user_id: User who initiated the interaction
        module_name: Source module (e.g., 'archie_chat', 'media_studio')
        agent_id: Agent involved in the interaction
        intent_type: Type of intent (code_task, business_task, etc.)
        prompt_summary: Summary of the prompt (first 500 chars)
        response_summary: Summary of the response (first 500 chars)
        model_used: LLM model used
        tokens_used: Total tokens consumed
        cost_estimate: Estimated cost in USD
        execution_time_ms: Execution time in milliseconds
        success: Whether the interaction succeeded
        error_message: Error message if failed
        escalated_to_claude: Whether this was escalated to Claude contractor
        tags: List of relevant tags
        metadata: Additional metadata dict

    Returns:
        int: Log entry ID or None on error
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Truncate summaries
        prompt_summary = (prompt_summary or "")[:500]
        response_summary = (response_summary or "")[:500]

        # Use the database function from migration 060
        cur.execute(
            """
            SELECT log_bridge_interaction(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) as log_id
        """,
            (
                user_id,
                module_name,
                agent_id,
                intent_type,
                prompt_summary,
                response_summary,
                model_used,
                tokens_used,
                cost_estimate,
                execution_time_ms,
                success,
                error_message,
                escalated_to_claude,
                tags or [],
                json.dumps(metadata or {}),
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        log_id = result["log_id"] if result else None
        if log_id:
            print(f"[AI Bridge] Bridge interaction logged (ID: {log_id})")
        return log_id

    except Exception as e:
        print(f"[AI Bridge] Error logging bridge interaction: {e}")
        return None


def log_agent_learning_from_claude(
    agent_id,
    skill_name,
    skill_category=None,
    knowledge_id=None,
    context_summary=None,
    initial_confidence=0.5,
    metadata=None,
):
    """
    Log when an agent learns a skill from Claude's work.

    When Claude (contractor) does work, the relevant internal agent
    should learn the skill so next time we can use local LLMs.

    Args:
        agent_id: Agent who should learn this skill
        skill_name: Name of the skill learned
        skill_category: Category (code, business, creative, etc.)
        knowledge_id: Reference to knowledge_base entry if stored
        context_summary: Brief description of what was learned
        initial_confidence: Starting confidence (0.0-1.0)
        metadata: Additional metadata

    Returns:
        int: Learning log ID or None on error
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function from migration 060
        cur.execute(
            """
            SELECT log_agent_learning(
                %s, %s, %s, %s, %s, 'claude', %s, %s
            ) as log_id
        """,
            (
                agent_id,
                skill_name,
                skill_category,
                knowledge_id,
                context_summary,
                initial_confidence,
                json.dumps(metadata or {}),
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        log_id = result["log_id"] if result else None
        if log_id:
            print(f"[AI Bridge] Agent {agent_id} learned skill '{skill_name}' from Claude (ID: {log_id})")
        return log_id

    except Exception as e:
        print(f"[AI Bridge] Error logging agent learning: {e}")
        return None


def get_best_agent_for_task(skill_name, min_confidence=0.6):
    """
    Find the best internal agent for a task based on learned skills.

    Before escalating to Claude, check if any internal agent has
    learned this skill with sufficient confidence.

    Args:
        skill_name: The skill/task type to look for
        min_confidence: Minimum confidence threshold (default 0.6)

    Returns:
        dict: Best agent info or None if no qualified agent found
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM get_best_agent_for_skill(%s, %s)
        """,
            (skill_name, min_confidence),
        )

        result = cur.fetchone()
        cur.close()
        conn.close()

        return dict(result) if result else None

    except Exception as e:
        print(f"[AI Bridge] Error finding best agent: {e}")
        return None


def extract_skill_from_task(prompt, response, task_type=None):
    """
    Extract a skill name from a task for learning purposes.

    Args:
        prompt: The original prompt
        response: The AI response
        task_type: Optional task type classification

    Returns:
        tuple: (skill_name, skill_category)
    """
    # Simple extraction based on task_type
    skill_categories = {
        "code_task": "code",
        "code_simple": "code",
        "code_complex": "code",
        "architecture": "code",
        "business_task": "business",
        "creative_task": "creative",
        "knowledge_query": "knowledge",
        "workflow": "automation",
        "file_operation": "code",
    }

    category = skill_categories.get(task_type, "general")

    # Extract key words from prompt for skill name
    prompt_lower = prompt.lower()[:200]

    # Common skill patterns
    if "refactor" in prompt_lower:
        return ("code_refactoring", "code")
    elif "debug" in prompt_lower or "fix" in prompt_lower:
        return ("debugging", "code")
    elif "test" in prompt_lower:
        return ("testing", "code")
    elif "api" in prompt_lower:
        return ("api_development", "code")
    elif "database" in prompt_lower or "sql" in prompt_lower:
        return ("database_operations", "code")
    elif "design" in prompt_lower or "ui" in prompt_lower:
        return ("ui_design", "creative")
    elif "email" in prompt_lower:
        return ("email_composition", "business")
    elif "report" in prompt_lower or "analysis" in prompt_lower:
        return ("data_analysis", "business")

    # Default to task_type as skill name
    skill_name = task_type or "general_task"
    return (skill_name, category)


def call_contractor_with_approval(
    contractor_agent,
    prompt,
    system_prompt=None,
    task_type=None,
    module_source=None,
    user_id=None,
    skip_approval_check=False,
):
    """
    Call contractor with approval check and execution logging.

    This is the recommended way to call contractors - it:
    1. Checks approval before calling
    2. Estimates cost
    3. Makes the API call
    4. Logs the execution for HR/C.R.E.E.D.

    Args:
        contractor_agent: Dict with contractor info
        prompt: The prompt to send
        system_prompt: Optional system prompt override
        task_type: Task classification
        module_source: Source module
        user_id: Requesting user ID
        skip_approval_check: Set True to bypass approval (use carefully)

    Returns:
        {
            'success': bool,
            'response': str,
            'provider': str,
            'model': str,
            'tokens_used': int,
            'cost': float,
            'execution_id': UUID,
            'needs_approval': bool (if not approved)
        }
    """
    import time

    start_time = time.time()

    agent_id = contractor_agent.get("id")
    model = contractor_agent.get("model")
    provider = contractor_agent.get("api_provider", "")

    # Estimate cost
    estimated_cost = estimate_contractor_cost(prompt, model, provider)

    # Check approval unless skipped
    if not skip_approval_check:
        approval = check_contractor_approval(agent_id, task_type or "general", estimated_cost, user_id)

        if not approval.get("approved"):
            return {
                "success": False,
                "needs_approval": True,
                "error": approval.get("message", "Contractor usage requires admin approval"),
                "estimated_cost": estimated_cost,
                "budget_remaining": approval.get("budget_remaining"),
                "model": model,
                "provider": provider,
            }

    # Make the actual call
    result = call_contractor(contractor_agent, prompt, system_prompt)

    # Calculate duration
    duration_ms = int((time.time() - start_time) * 1000)

    # Log execution
    execution_id = log_task_execution(
        agent_id=agent_id,
        task_type=task_type or "contractor_call",
        module_source=module_source,
        model_used=result.get("model", model),
        provider=result.get("provider", provider),
        tokens_used=result.get("tokens_used", 0),
        cost=result.get("cost", 0.0),
        duration_ms=duration_ms,
        success=result.get("success", False),
        user_id=user_id,
        error_message=result.get("error") if not result.get("success") else None,
        request_origin="platform",
    )

    result["execution_id"] = execution_id
    result["duration_ms"] = duration_ms

    # ========================================================================
    # PHASE 61: AGENT SKILL ACQUISITION FROM CLAUDE
    # When Claude does work, internal agents learn the skill
    # ========================================================================
    if result.get("success") and "claude" in (provider or "").lower():
        try:
            # Extract skill from the task
            skill_name, skill_category = extract_skill_from_task(prompt, result.get("response", ""), task_type)

            # Find the best internal agent to learn this skill
            # Use the module_source to determine department
            department_mapping = {
                "media_studio": "CREATION",
                "content_studio": "CREATION",
                "game_studio": "CREATION",
                "archie_chat": "DEVELOPMENT",
                "code_editor": "DEVELOPMENT",
                "improvements_lab": "DEVELOPMENT",
                "website_studio": "BUSINESS_TOOLS",
                "store_builder": "BUSINESS_TOOLS",
                "email_manager": "BUSINESS_TOOLS",
                "crm": "BUSINESS_TOOLS",
            }
            department = department_mapping.get(module_source, "DEVELOPMENT")

            # Get an internal agent from this department to learn the skill
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, name FROM agents
                WHERE department = %s
                  AND worker_type = 'internal'
                  AND status = 'active'
                ORDER BY RANDOM()
                LIMIT 1
            """,
                (department,),
            )
            learner = cur.fetchone()
            cur.close()
            conn.close()

            if learner:
                learning_id = log_agent_learning_from_claude(
                    agent_id=learner["id"],
                    skill_name=skill_name,
                    skill_category=skill_category,
                    context_summary=f"Learned from Claude contractor task: {prompt[:200]}",
                    initial_confidence=0.5,
                    metadata={
                        "contractor_agent_id": agent_id,
                        "module_source": module_source,
                        "task_type": task_type,
                        "execution_id": str(execution_id) if execution_id else None,
                    },
                )
                result["agent_learning"] = {
                    "learner_id": learner["id"],
                    "learner_name": learner["name"],
                    "skill_name": skill_name,
                    "skill_category": skill_category,
                    "learning_id": learning_id,
                }
        except Exception as e:
            print(f"[AI Bridge] Error in agent skill acquisition: {e}")

    return result


# ============================================================================
# TOOL CALLING SYSTEM
# ============================================================================


def list_available_tools():
    """
    List all available tools A.R.C.H.I.E. can use
    Returns: dict of {tool_name: description}
    """
    from consciousness.archie_tools import AVAILABLE_TOOLS

    tool_descriptions = {}
    for tool_name, tool_func in AVAILABLE_TOOLS.items():
        # Get docstring as description
        doc = tool_func.__doc__ or "No description available"
        # Clean up docstring
        description = " ".join(doc.split()[:20]) + "..."
        tool_descriptions[tool_name] = description

    return tool_descriptions


def format_tools_for_prompt():
    """
    Format available tools in a way A.R.C.H.I.E. can understand
    Returns a string describing all available tools
    """
    tools = list_available_tools()

    tool_desc = """
# AVAILABLE TOOLS

You have access to the following tools to interact with your codebase:

"""
    for tool_name, description in tools.items():
        tool_desc += f"**{tool_name}**: {description}\n\n"

    tool_desc += """
# HOW TO USE TOOLS

**CRITICAL**: You MUST use tools to answer questions, not just describe what you could do!

When the user asks a question, identify which tool to use and USE IT IMMEDIATELY:
- "What do you know about X?" → USE query_knowledge(search_term="X")
- "Read file X" → USE read_file(path="X")
- "Search for X" → USE search_code(pattern="X")
- "Analyze file X" → USE analyze_file(path="X")
- "Learn about file X" → USE learn_from_file(path="X")

To use a tool, format your response like this:

```tool
{
  "tool": "tool_name",
  "args": {
    "arg1": "value1",
    "arg2": "value2"
  }
}
```

You can use multiple tools in sequence. After each tool execution, you'll receive the results and can decide what to do next.

# EXAMPLES

To read a file:
```tool
{
  "tool": "read_file",
  "args": {
    "path": "consciousness/memory_manager.py"
  }
}
```

To search for code:
```tool
{
  "tool": "search_code",
  "args": {
    "pattern": "def extract_memories",
    "file_pattern": "*.py"
  }
}
```

To write a file (requires approval):
```tool
{
  "tool": "write_file",
  "args": {
    "path": "consciousness/improved_file.py",
    "content": "# New optimized code..."
  }
}
```

To query your knowledge base:
```tool
{
  "tool": "query_knowledge",
  "args": {
    "search_term": "edit_file"
  }
}
```

To learn from a file:
```tool
{
  "tool": "learn_from_file",
  "args": {
    "file_path": "consciousness/memory_manager.py"
  }
}
```

IMPORTANT:
- ALWAYS USE TOOLS when asked questions - don't just talk about what you could do!
- Explain WHY you're using a tool and what you're trying to accomplish.
- Use your knowledge base (query_knowledge) to remember what you've learned about your codebase.
"""
    return tool_desc


def parse_tool_calls(response_text):
    """
    Parse tool calls from A.R.C.H.I.E.'s response

    Returns: list of {
        'tool': str,
        'args': dict,
        'raw': str
    }
    """
    import re

    tool_calls = []

    # Find all ```tool ... ``` blocks
    pattern = r"```tool\s*\n(.*?)\n```"
    matches = re.findall(pattern, response_text, re.DOTALL)

    for match in matches:
        try:
            tool_data = json.loads(match)
            tool_calls.append(
                {
                    "tool": tool_data.get("tool"),
                    "args": tool_data.get("args", {}),
                    "raw": match,
                }
            )
        except json.JSONDecodeError:
            # Invalid JSON, skip
            continue

    return tool_calls


def execute_tool_calls(tool_calls):
    """
    Execute a list of tool calls

    Returns: list of {
        'tool': str,
        'args': dict,
        'result': dict  # from tool execution
    }
    """
    from consciousness.archie_tools import AVAILABLE_TOOLS

    results = []

    for call in tool_calls:
        tool_name = call["tool"]
        args = call["args"]

        if tool_name not in AVAILABLE_TOOLS:
            results.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "result": {"success": False, "error": f"Unknown tool: {tool_name}"},
                }
            )
            continue

        try:
            tool_func = AVAILABLE_TOOLS[tool_name]
            result = tool_func(**args)

            results.append({"tool": tool_name, "args": args, "result": result})
        except Exception as e:
            results.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "result": {"success": False, "error": str(e)},
                }
            )

    return results


def format_tool_results(tool_results):
    """Format tool execution results for feeding back to A.R.C.H.I.E."""
    formatted = "\n# TOOL EXECUTION RESULTS\n\n"

    for i, result in enumerate(tool_results, 1):
        formatted += f"## Result {i}: {result['tool']}\n"
        formatted += f"**Args**: {json.dumps(result['args'], indent=2)}\n\n"

        # Get result data
        res = result["result"]

        if res.get("success"):
            formatted += "**Status**: ✓ Success\n\n"
            formatted += "**Output**:\n"

            # Format output based on result type

            if "content" in res:
                # File content
                formatted += f"```\n{res['content'][:2000]}...\n```\n"
                if len(res["content"]) > 2000:
                    formatted += f"*(Showing first 2000 characters of {res.get('lines', 'many')} lines)*\n"

            elif "files" in res:
                # File list
                formatted += f"Found {res['count']} files:\n"
                for f in res["files"][:20]:
                    formatted += f"- {f['name']} ({f['size']} bytes)\n"
                if res["count"] > 20:
                    formatted += f"*(and {res['count'] - 20} more)*\n"

            elif "matches" in res:
                # Search results
                formatted += f"Found {res['count']} matches:\n"
                for m in res["matches"][:10]:
                    formatted += f"- {m['file']}:{m['line_number']} - {m['line_content'][:80]}\n"
                if res["count"] > 10:
                    formatted += f"*(and {res['count'] - 10} more)*\n"

            elif "diff" in res:
                # Git diff or file edit diff
                if res.get("has_changes") or res.get("lines_changed"):
                    formatted += f"```diff\n{res['diff'][:1000]}...\n```\n"
                    if res.get("lines_changed"):
                        formatted += f"*Lines changed: {res['lines_changed']}*\n"
                    if res.get("backup_path"):
                        formatted += f"*Backup created: {res['backup_path']}*\n"
                else:
                    formatted += "No changes detected.\n"

            elif "analysis" in res:
                # File analysis
                analysis = res["analysis"]
                formatted += f"**Lines**: {analysis['lines']}\n"
                formatted += f"**Functions**: {len(analysis['functions'])}\n"
                formatted += f"**Classes**: {len(analysis['classes'])}\n"
                formatted += f"**Imports**: {len(analysis['imports'])}\n"

            elif "results" in res and "search_term" in res:
                # Knowledge query results
                formatted += f"Found {res['count']} knowledge entries for '{res['search_term']}':\n\n"
                for knowledge in res["results"][:10]:
                    formatted += f"**{knowledge['entity_name']}** ({knowledge['knowledge_type']})\n"
                    formatted += f"- {knowledge['description']}\n"
                    if knowledge.get("file_path"):
                        formatted += f"- File: {knowledge['file_path']}\n"
                    if knowledge.get("purpose"):
                        formatted += f"- Purpose: {knowledge['purpose']}\n"
                    formatted += "\n"
                if res["count"] > 10:
                    formatted += f"*(and {res['count'] - 10} more)*\n"

            elif "learned" in res:
                # Learn from file results
                formatted += f"Learned {res['count']} items:\n"
                for item in res["learned"]:
                    formatted += f"- {item}\n"

            else:
                # Generic result
                formatted += f"```json\n{json.dumps(res, indent=2)}\n```\n"

        else:
            formatted += f"**Status**: ✗ Error\n"
            formatted += f"**Error**: {res.get('error', 'Unknown error')}\n"

        formatted += "\n---\n\n"

    return formatted


def archie_bridge_with_tools(
    prompt,
    context=None,
    user_id=None,
    force_model=None,
    enable_memory=True,
    max_iterations=5,
):
    """
    Enhanced A.R.C.H.I.E. Bridge with tool calling support

    This allows A.R.C.H.I.E. to use tools to read files, search code, make changes, etc.

    Args:
        prompt: User's request
        context: Optional context
        user_id: User ID for memory and tracking
        force_model: Force specific model
        enable_memory: Enable memory system
        max_iterations: Maximum tool-use iterations (prevents infinite loops)

    Returns:
        {
            'success': bool,
            'response': str,  # Final response
            'conversation': list,  # Full conversation history
            'tools_used': list,  # Tools that were executed
            'model': str,
            'provider': str,
            'iterations': int
        }
    """
    conversation_history = []
    tools_used = []

    # Add tool descriptions to the initial prompt
    tool_info = format_tools_for_prompt()
    enhanced_prompt = f"""You are A.R.C.H.I.E., an AI that can improve her own codebase.

{tool_info}

# USER REQUEST

{prompt}

You can use the tools above to read your code, analyze it, and suggest or make improvements.

**CRITICAL INSTRUCTIONS**:
- When you use tools and get results, SHARE THE SPECIFIC DETAILS with the user
- Don't be vague - list actual function names, file paths, line numbers, etc.
- If you query your knowledge base, tell the user exactly what you found
- Always explain your reasoning before using tools."""

    # First call to A.R.C.H.I.E.
    result = archie_bridge(
        enhanced_prompt,
        context=context,
        user_id=user_id,
        force_model=force_model,
        enable_memory=enable_memory,
    )

    if not result["success"]:
        return result

    conversation_history.append({"role": "user", "content": prompt})

    conversation_history.append({"role": "assistant", "content": result["response"]})

    current_response = result["response"]
    iterations = 0

    # Tool execution loop
    while iterations < max_iterations:
        iterations += 1

        # Check if A.R.C.H.I.E. wants to use tools
        tool_calls = parse_tool_calls(current_response)

        if not tool_calls:
            # No more tools to execute, we're done
            break

        # Execute tools
        tool_results = execute_tool_calls(tool_calls)
        tools_used.extend(tool_results)

        # Format results for A.R.C.H.I.E.
        results_text = format_tool_results(tool_results)

        # Feed results back to A.R.C.H.I.E.
        followup_prompt = f"""{results_text}

**IMPORTANT**: Share the SPECIFIC DETAILS from the tool results above with the user!
Don't just say "I found some functions" - list them by name with their details.

Based on these tool results, what would you like to do next?

You can:
1. Use more tools to gather more information
2. Share your analysis and specific recommendations based on the results
3. Propose specific code changes with exact file paths and line numbers

Remember:
- ALWAYS share specific details (function names, file paths, line numbers, etc.)
- If you want to write files, clearly show the changes you're proposing."""

        conversation_history.append({"role": "user", "content": results_text})

        # Get A.R.C.H.I.E.'s next response
        followup_result = archie_bridge(
            followup_prompt,
            user_id=user_id,
            force_model=force_model,
            enable_memory=False,  # Don't duplicate memory on followups
        )

        if not followup_result["success"]:
            break

        current_response = followup_result["response"]

        conversation_history.append({"role": "assistant", "content": current_response})

    # Build final result
    return {
        "success": True,
        "response": current_response,
        "conversation": conversation_history,
        "tools_used": tools_used,
        "model": result.get("model", ""),
        "provider": result.get("provider", ""),
        "iterations": iterations,
        "memory_used": result.get("memory_used", False),
        "memories_learned": result.get("memories_learned", 0),
    }


# ============================================================================
# PLAN-AND-EXECUTE WORKFLOW
# ============================================================================


def archie_bridge_with_planning(prompt, user_id, force_model=None):
    """
    Plan-and-Execute workflow for code improvements

    A.R.C.H.I.E. creates a detailed plan with approval steps before making changes.

    Args:
        prompt: User's improvement request
        user_id: User ID for tracking
        force_model: Force specific model

    Returns:
        {
            'success': bool,
            'proposal_id': int,  # ID in improvement_proposals table
            'plan': {
                'title': str,
                'description': str,
                'steps': [
                    {
                        'step': int,
                        'description': str,
                        'action': str,  # read_file, edit_file, etc.
                        'target': str,  # file path or search term
                        'details': str  # what will be changed
                    }
                ]
            },
            'message': str
        }
    """

    # Create planning prompt
    planning_prompt = f"""You are A.R.C.H.I.E., an AI that can improve her own codebase.

The user has requested a code improvement:
"{prompt}"

**YOUR CODEBASE STRUCTURE**:
- Platform code: /mnt/archie_brain/platform_v2/
  - Main app: /mnt/archie_brain/platform_v2/app.py
  - Consciousness: /mnt/archie_brain/platform_v2/consciousness/
    - memory_manager.py
    - archie_tools.py
  - Tools: /mnt/archie_brain/platform_v2/tools/admin/routes.py
  - Templates: /mnt/archie_brain/platform_v2/templates/
- AI Bridge: /mnt/archie_brain/ai_bridge/
  - archie_bridge.py

Your task is to CREATE A DETAILED PLAN for implementing this improvement.

**IMPORTANT**: Format your plan as JSON in a ```plan block like this:

```plan
{{
  "title": "Brief title for this improvement",
  "description": "Detailed description of what will be improved and why",
  "category": "performance | security | features | refactoring | documentation",
  "priority": "low | medium | high | critical",
  "steps": [
    {{
      "step": 1,
      "description": "What this step accomplishes",
      "action": "read_file | analyze_file | search_code | edit_file | write_file",
      "target": "file path or search term",
      "details": "Specific changes or analysis to perform"
    }},
    {{
      "step": 2,
      "description": "...",
      "action": "...",
      "target": "...",
      "details": "..."
    }}
  ],
  "estimated_impact": "Brief description of expected benefits",
  "risks": "Potential risks or concerns"
}}
```

**CRITICAL GUIDELINES**:
1. **File Paths**: Use complete paths matching the structure above
   - Example: "/mnt/archie_brain/platform_v2/consciousness/memory_manager.py"
   - Example: "/mnt/archie_brain/ai_bridge/archie_bridge.py"
   - DO NOT use wildcards like "*memory_manager.py"
   - DO NOT use /app/ paths (use /mnt/archie_brain/ instead)

2. **Search Patterns**: Use simple text search, not regex
   - Good: "memory_manager.py"
   - Bad: "*memory_manager.py" or ".*memory.*"

3. **Available Actions**:
   - read_file: Read a specific file (requires exact path)
   - analyze_file: Analyze a file (requires exact path)
   - search_code: Search for text in codebase (use simple keywords)
   - edit_file: Modify existing file (I'll generate the actual code during execution)
   - write_file: Create new file (I'll generate the content during execution)

4. **Step Order**:
   - Start with search_code to find relevant files
   - Then read_file to understand current implementation
   - Then edit_file with clear description of what needs to change
   - Keep steps focused and specific

5. **Edit Details**: For edit_file steps, describe WHAT needs to change, not HOW
   - Good: "Add try-except blocks around database calls to handle connection errors"
   - Bad: "Add error handling" (too vague)

Create a clear, executable plan. During execution, I'll generate the actual code for edit/write steps."""

    # Get A.R.C.H.I.E.'s plan
    result = archie_bridge(
        planning_prompt,
        user_id=user_id,
        force_model=force_model or "dolphin3-8k:latest",
        enable_memory=True,
    )

    if not result["success"]:
        return {
            "success": False,
            "error": "Failed to generate plan",
            "details": result.get("error"),
        }

    # Parse the plan from response
    response_text = result["response"]

    import re

    plan_pattern = r"```plan\s*\n(.*?)\n```"
    plan_matches = re.findall(plan_pattern, response_text, re.DOTALL)

    if not plan_matches:
        return {
            "success": False,
            "error": "A.R.C.H.I.E. did not generate a valid plan",
            "response": response_text,
        }

    try:
        plan = json.loads(plan_matches[0])
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": "Failed to parse plan JSON",
            "details": str(e),
            "raw_plan": plan_matches[0],
        }

    # Validate plan structure
    required_fields = ["title", "description", "steps"]
    for field in required_fields:
        if field not in plan:
            return {
                "success": False,
                "error": f"Plan missing required field: {field}",
                "plan": plan,
            }

    # Store plan in database
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO improvement_proposals
            (title, description, category, priority, status, proposed_by,
             plan_steps, code_changes, metadata)
            VALUES (%s, %s, %s, %s, 'pending_approval', %s, %s, %s, %s)
            RETURNING id
        """,
            (
                plan.get("title"),
                plan.get("description"),
                plan.get("category", "refactoring"),
                plan.get("priority", "medium"),
                user_id,
                json.dumps(plan.get("steps", [])),
                response_text,  # Store full response as code_changes for now
                json.dumps(
                    {
                        "estimated_impact": plan.get("estimated_impact"),
                        "risks": plan.get("risks"),
                        "model": result.get("model"),
                        "provider": result.get("provider"),
                        "created_at": datetime.now().isoformat(),
                    }
                ),
            ),
        )

        proposal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": True,
            "proposal_id": proposal_id,
            "plan": plan,
            "message": f"Plan created successfully! Proposal ID: {proposal_id}",
        }

    except Exception as e:
        return {
            "success": False,
            "error": "Failed to store plan in database",
            "details": str(e),
        }


def execute_proposal(proposal_id, user_id, approved_steps=None):
    """
    Execute an approved improvement proposal step-by-step with automatic backups

    Args:
        proposal_id: ID of the proposal to execute
        user_id: User ID for approval verification
        approved_steps: Optional list of step numbers to execute (None = all)

    Returns:
        {
            'success': bool,
            'results': [...]  # Results from each step
            'errors': [...]  # Any errors encountered
            'backups': [...]  # List of backup file paths created
        }
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal
        cur.execute(
            """
            SELECT * FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()

        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        if proposal["status"] != "approved":
            return {
                "success": False,
                "error": f'Proposal status is {proposal["status"]}, must be approved',
            }

        # Get plan steps
        plan_steps = proposal["plan_steps"]

        if not plan_steps or len(plan_steps) == 0:
            # Legacy proposal without plan steps - need to regenerate
            return {
                "success": False,
                "error": "Legacy proposal without implementation plan. Please create a new proposal or regenerate the plan for this improvement.",
                "legacy": True,
                "suggestion": "Archive this proposal and create a new one with detailed steps.",
            }

        # Track execution state
        results = []
        errors = []
        backups_created = []
        execution_failed = False

        # Helper function to normalize file paths for container environment
        def normalize_path(path):
            """Convert host paths to container paths"""
            if not path:
                return path
            # Remove platform_v2/ prefix if present (host path -> container path)
            if path.startswith("platform_v2/"):
                path = path.replace("platform_v2/", "", 1)
            # Ensure absolute path if needed
            if not path.startswith("/"):
                path = f"/app/{path}"
            return path

        # Execute each step
        for step in plan_steps:
            step_num = step.get("step")

            # Skip if not in approved_steps list
            if approved_steps and step_num not in approved_steps:
                continue

            action = step.get("action")
            target = step.get("target")
            details = step.get("details")

            # Normalize the target path
            target = normalize_path(target)

            # Build tool call
            tool_call = {"tool": action, "args": {}}

            # Map step data to tool args
            if action == "read_file":
                tool_call["args"]["path"] = target
            elif action == "analyze_file":
                tool_call["args"]["path"] = target
            elif action == "search_code":
                tool_call["args"]["pattern"] = target
            elif action == "edit_file":
                # For edit_file, call A.R.C.H.I.E. to generate the actual code changes
                try:
                    # First read the file
                    file_content = read_file(target)
                    if not file_content or "error" in file_content:
                        errors.append(f"Step {step_num}: Could not read file {target}")
                        execution_failed = True
                        continue

                    # Ask A.R.C.H.I.E. to generate the specific code changes
                    code_gen_prompt = f"""You need to edit the file: {target}

Step description: {step.get('description')}
Details: {details}

Current file content:
```
{file_content.get('content', '')}
```

Generate the EXACT code changes needed. Respond with a ```edit block containing:
- old_content: The exact text to replace (must match exactly)
- new_content: The replacement text

```edit
{{
  "old_content": "exact text to find and replace",
  "new_content": "replacement text"
}}
```
"""

                    edit_result = archie_bridge(
                        code_gen_prompt,
                        user_id=user_id,
                        enable_memory=False,
                        force_model="dolphin3-8k:latest",
                    )

                    if not edit_result.get("success"):
                        errors.append(f"Step {step_num}: Failed to generate code changes")
                        execution_failed = True
                        continue

                    # Parse the edit block
                    import re

                    edit_pattern = r"```edit\s*\n(.*?)\n```"
                    edit_matches = re.findall(edit_pattern, edit_result["response"], re.DOTALL)

                    if not edit_matches:
                        errors.append(f"Step {step_num}: A.R.C.H.I.E. did not generate valid edit block")
                        execution_failed = True
                        continue

                    edit_data = json.loads(edit_matches[0])

                    # Now execute the edit
                    tool_call["tool"] = "edit_file"
                    tool_call["args"] = {
                        "path": target,
                        "old_content": edit_data["old_content"],
                        "new_content": edit_data["new_content"],
                        "proposal_id": proposal_id,
                    }

                except Exception as e:
                    errors.append(f"Step {step_num}: Error generating edit: {str(e)}")
                    execution_failed = True
                    continue

            elif action == "write_file":
                # For write_file, call A.R.C.H.I.E. to generate the file content
                try:
                    content_gen_prompt = f"""You need to create/write a file: {target}

Step description: {step.get('description')}
Details: {details}

Generate the complete file content. Respond with a ```content block:

```content
[complete file content here]
```
"""

                    content_result = archie_bridge(
                        content_gen_prompt,
                        user_id=user_id,
                        enable_memory=False,
                        force_model="dolphin3-8k:latest",
                    )

                    if not content_result.get("success"):
                        errors.append(f"Step {step_num}: Failed to generate file content")
                        execution_failed = True
                        continue

                    # Parse the content block
                    import re

                    content_pattern = r"```content\s*\n(.*?)\n```"
                    content_matches = re.findall(content_pattern, content_result["response"], re.DOTALL)

                    if not content_matches:
                        errors.append(f"Step {step_num}: A.R.C.H.I.E. did not generate valid content block")
                        execution_failed = True
                        continue

                    # Now execute the write
                    tool_call["tool"] = "write_file"
                    tool_call["args"] = {
                        "path": target,
                        "content": content_matches[0],
                        "proposal_id": proposal_id,
                        "create_backup": True,
                    }

                except Exception as e:
                    errors.append(f"Step {step_num}: Error generating content: {str(e)}")
                    execution_failed = True
                    continue

            # Execute tool
            try:
                tool_results = execute_tool_calls([tool_call])
                step_result = tool_results[0] if tool_results else None

                results.append(
                    {
                        "step": step_num,
                        "description": step.get("description"),
                        "result": step_result,
                    }
                )

                # Track any backups created
                if step_result and "result" in step_result:
                    result_data = step_result["result"]
                    if isinstance(result_data, dict) and "backup_path" in result_data:
                        backups_created.append(
                            {
                                "step": step_num,
                                "file": target,
                                "backup_path": result_data["backup_path"],
                            }
                        )

            except Exception as e:
                error_msg = f"Step {step_num}: {str(e)}"
                errors.append(error_msg)
                execution_failed = True

                # Stop execution on critical errors
                if action in ["edit_file", "write_file"]:
                    break

        # Determine final status
        if execution_failed or errors:
            final_status = "failed"
            # Auto-restore from backups if any file modifications failed
            if backups_created and execution_failed:
                restore_result = restore_from_backups(proposal_id, backups_created)
                if restore_result["success"]:
                    errors.append(f"Auto-restored {restore_result['restored_count']} files from backup")
        else:
            final_status = "completed"

        # Update proposal with execution results
        metadata = proposal.get("metadata", {}) or {}
        metadata["backups"] = backups_created
        metadata["execution_timestamp"] = datetime.now().isoformat()

        cur.execute(
            """
            UPDATE improvement_proposals
            SET execution_results = %s,
                status = %s,
                metadata = %s,
                implemented_at = NOW()
            WHERE id = %s
        """,
            (
                json.dumps({"results": results, "errors": errors, "backups": backups_created}),
                final_status,
                json.dumps(metadata),
                proposal_id,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": not execution_failed,
            "results": results,
            "errors": errors,
            "backups": backups_created,
            "status": final_status,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def restore_from_backups(proposal_id, backups):
    """
    Restore files from proposal backups

    Args:
        proposal_id: Proposal ID
        backups: List of backup info dicts with 'file' and 'backup_path'

    Returns:
        {'success': bool, 'restored_count': int, 'errors': [...]}
    """
    import shutil

    restored_count = 0
    errors = []

    for backup_info in backups:
        try:
            original_file = backup_info["file"]
            backup_path = backup_info["backup_path"]

            # Restore from backup
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, original_file)
                restored_count += 1
            else:
                errors.append(f"Backup not found: {backup_path}")

        except Exception as e:
            errors.append(f"Failed to restore {backup_info['file']}: {str(e)}")

    return {
        "success": len(errors) == 0,
        "restored_count": restored_count,
        "errors": errors,
    }


def get_proposal_backups(proposal_id):
    """
    Get all backups associated with a proposal

    Args:
        proposal_id: Proposal ID

    Returns:
        {'success': bool, 'backups': [...]}
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT metadata FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )

        result = cur.fetchone()
        cur.close()
        conn.close()

        if not result:
            return {"success": False, "error": "Proposal not found"}

        metadata = result.get("metadata", {}) or {}
        backups = metadata.get("backups", [])

        return {"success": True, "backups": backups, "count": len(backups)}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# AGENT EXECUTION ENGINE
# ============================================================================


def execute_agent_task(agent_id, task, user_id, stream=False):
    """
    Execute a task using a specific agent

    Args:
        agent_id: ID of the agent to use
        task: Task description
        user_id: User ID for tracking
        stream: Whether to stream the response

    Returns:
        {
            'success': bool,
            'response': str,
            'execution_id': int,
            'tokens_used': int,
            'duration_seconds': float,
            'cost': float
        }
    """
    import time

    start_time = time.time()

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get agent configuration
        cur.execute(
            """
            SELECT
                a.*,
                at.name as type_name,
                at.category as type_category
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.id = %s
        """,
            (agent_id,),
        )

        agent = cur.fetchone()

        if not agent:
            return {"success": False, "error": "Agent not found"}

        if agent["status"] != "active":
            return {
                "success": False,
                "error": f'Agent is {agent["status"]}, must be active',
            }

        # Create execution record
        cur.execute(
            """
            INSERT INTO agent_executions (agent_id, user_id, task_description, status, input_data)
            VALUES (%s, %s, %s, 'running', %s)
            RETURNING id
        """,
            (agent_id, user_id, task, json.dumps({"task": task})),
        )

        execution_id = cur.fetchone()["id"]
        conn.commit()

        # Build system prompt
        system_prompt = agent["system_prompt"] or f"You are {agent['name']}, a {agent['type_name']}."

        # Call the AI model based on agent configuration
        result = archie_bridge(
            task,
            user_id=user_id,
            system_prompt=system_prompt,
            force_model=agent["model"],
            enable_memory=False,  # Agents use their own context
            agent_id=agent_id,  # Track which agent is executing
        )

        duration = time.time() - start_time

        # Update execution record
        if result.get("success"):
            cur.execute(
                """
                UPDATE agent_executions
                SET status = 'completed',
                    completed_at = NOW(),
                    duration_seconds = %s,
                    tokens_used = %s,
                    cost = %s,
                    result = %s
                WHERE id = %s
            """,
                (
                    int(duration),
                    result.get("tokens_used", 0),
                    result.get("cost", 0.0),
                    json.dumps(result),
                    execution_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE agent_executions
                SET status = 'failed',
                    completed_at = NOW(),
                    duration_seconds = %s,
                    error = %s
                WHERE id = %s
            """,
                (int(duration), result.get("error", "Unknown error"), execution_id),
            )

        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": result.get("success", False),
            "response": result.get("response", ""),
            "execution_id": execution_id,
            "tokens_used": result.get("tokens_used", 0),
            "duration_seconds": round(duration, 2),
            "cost": result.get("cost", 0.0),
            "agent_name": agent["name"],
            "agent_tier": agent["tier"],
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# ============================================================================
# SHIFT-AWARE ROUTING (Phase 28)
# ============================================================================


def get_agents_on_duty(station_name: str = None):
    """
    Get agents currently on duty based on shift schedule.

    Args:
        station_name: Optional - filter by station name

    Returns:
        List of agent dicts with shift info
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current time and day
        from datetime import datetime

        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_day = now.isoweekday() % 7  # 0=Sun, 1=Mon, ..., 6=Sat

        query = """
            SELECT DISTINCT
                a.id, a.name, a.department, a.floor, a.worker_type,
                sd.shift_name, sd.start_time, sd.end_time
            FROM agents a
            LEFT JOIN agent_shifts ash ON a.id = ash.agent_id
                AND ash.effective_from <= CURRENT_DATE
                AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
                AND (ash.day_of_week IS NULL OR ash.day_of_week = %s)
            LEFT JOIN shift_definitions sd ON ash.shift_id = sd.id AND sd.is_active = true
            WHERE a.status = 'active'
              AND a.department IS NOT NULL
        """
        params = [current_day]

        if station_name:
            query += " AND LOWER(a.department) = LOWER(%s)"
            params.append(station_name)

        # Check if current time is within shift hours (handle overnight shifts)
        query += """
            AND (
                sd.id IS NULL  -- No shift assigned = always available
                OR (sd.start_time <= sd.end_time AND %s::time BETWEEN sd.start_time AND sd.end_time)
                OR (sd.start_time > sd.end_time AND (%s::time >= sd.start_time OR %s::time <= sd.end_time))
            )
            ORDER BY a.department, a.name
        """
        params.extend([current_time, current_time, current_time])

        cur.execute(query, params)
        agents = cur.fetchall()

        cur.close()
        conn.close()

        return [dict(a) for a in agents]

    except Exception as e:
        print(f"[AI Bridge] Error getting on-duty agents: {e}")
        return []


def get_available_agent_for_station(station_name: str, prefer_primary: bool = True):
    """
    Get the best available agent for a station, considering shifts and priority.
    Falls back to contractors if no station agents available.

    Args:
        station_name: Name of the bridge station
        prefer_primary: If True, prioritize primary agents over backups

    Returns:
        Agent dict or None
    """
    # First, try to get on-duty agents for this station
    on_duty = get_agents_on_duty(station_name)

    if on_duty:
        # Sort by assignment type (primary first) if preferred
        if prefer_primary:
            primaries = [a for a in on_duty if a.get("assignment_type") == "primary"]
            backups = [a for a in on_duty if a.get("assignment_type") == "backup"]
            sorted_agents = primaries + backups
        else:
            sorted_agents = on_duty

        if sorted_agents:
            return sorted_agents[0]

    # Fallback: get any assigned agent for this station (regardless of shift)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT a.id, a.name, a.department, a.floor, a.worker_type
            FROM agents a
            WHERE a.status = 'active'
              AND LOWER(a.department) = LOWER(%s)
            ORDER BY a.name
            LIMIT 1
        """,
            (station_name,),
        )

        agent = cur.fetchone()
        cur.close()
        conn.close()

        if agent:
            return dict(agent)

    except Exception as e:
        print(f"[AI Bridge] Error getting agent for department: {e}")

    # Final fallback: return a contractor
    contractors = list_available_contractors()
    if contractors:
        print(f"[AI Bridge] No department agents available, using contractor fallback")
        return contractors[0]

    return None


def route_task_to_station(task_type: str, task_description: str = None):
    """
    Route a task to the appropriate station and get an available agent.

    Args:
        task_type: Type of task (e.g., 'code_review', 'content', 'support')
        task_description: Optional description for smart routing

    Returns:
        Dict with station and agent info
    """
    # Task type to station mapping
    TASK_STATION_MAP = {
        # Engineering/Development tasks
        "code": "Engineering",
        "code_review": "R&D - Core",  # Code Reviewer and Solutions Architect
        "testing": "R&D - Core",
        "bug_fix": "Engineering",
        "development": "Engineering",
        "devops": "Engineering",
        # Creative tasks
        "content": "Creative",
        "writing": "Creative",
        "marketing": "Creative",
        "documentation": "Creative",
        # Operations tasks
        "finance": "Operations",
        "billing": "Operations",
        "scheduling": "Operations",
        "crm": "Operations",
        # Support tasks
        "support": "Operations",
        "customer": "Operations",
        # HR tasks
        "hr": "HR",
        "training": "HR",
        "compliance": "HR",
        # Security tasks
        "security": "Security",
        "backup": "Security",
        "infrastructure": "Security",
        # Medical/Wellness tasks
        "wellness": "Medical",
        "health": "Medical",
        "therapy": "Medical",
        # Research tasks
        "research": "Away Team",
        "web_search": "Away Team",
        # Knowledge/Memory tasks
        "memory": "Consciousness",
        "knowledge": "Consciousness",
        "learning": "Consciousness",
        # Default/General
        "general": "Command",
        "chat": "Command",
    }

    # Determine station
    station = TASK_STATION_MAP.get(task_type.lower(), "Command")

    # Get available agent for station
    agent = get_available_agent_for_station(station)

    return {
        "station": station,
        "agent": agent,
        "task_type": task_type,
        "routed_at": datetime.now().isoformat(),
    }
