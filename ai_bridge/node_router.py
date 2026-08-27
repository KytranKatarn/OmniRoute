"""
A.R.C.H.I.E. Node Router - Dynamic Model Routing (Phase 71)

Routes Ollama requests to the best available node based on:
- Model availability
- Node load
- GPU preference
- Bridge priority

Falls back to OLLAMA_HOST environment variable when no nodes available.
"""

import os
import random
import logging
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Optional, Dict, Any, List
from ai_bridge.db import get_db

logger = logging.getLogger("archie.node_router")

# Cache for node selections (avoid DB hits on every request)
_node_cache = {}
_cache_ttl = 30  # seconds


def get_fallback_host() -> str:
    """Get fallback Ollama host from environment"""
    host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    return host


def get_nodes_with_model(model_name: str) -> List[Dict[str, Any]]:
    """
    Find all bridge-enabled nodes that have a specific model available.

    Args:
        model_name: The Ollama model name (e.g., 'deepseek-coder-v2:16b')

    Returns:
        List of node dicts with connection info and load metrics
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                n.node_id,
                n.node_name,
                n.vpn_ip,
                n.port,
                n.current_load,
                n.bridge_priority,
                n.gpu_available,
                n.gpu_model,
                n.status,
                n.deployment_mode,
                m.avg_response_ms,
                n.hostname,
                n.mesh_ip
            FROM remote_nodes n
            JOIN node_ollama_models m ON n.node_id = m.node_id
            WHERE n.bridge_enabled = true
              AND n.status = 'online'
              AND n.approval_status = 'approved'
              AND n.ollama_available = true
              AND m.model_name = %s
              AND m.is_available = true
              AND n.deployment_mode IN ('starship', 'starbase')
              AND n.node_id != 'archie-starbase'
              AND n.last_heartbeat > NOW() - INTERVAL '90 seconds'
            ORDER BY n.current_load ASC, n.bridge_priority DESC
        """,
            (model_name,),
        )

        nodes = cur.fetchall()
        cur.close()
        conn.close()

        return nodes

    except Exception as e:
        logger.error(f"Error getting nodes with model {model_name}: {e}")
        return []


def select_best_node(model_name: str, prefer_gpu: bool = True) -> Optional[Dict[str, Any]]:
    """
    Select the best available node for a model request.

    Uses weighted random selection based on:
    - Inverse load (lower load = higher weight)
    - Bridge priority
    - GPU availability bonus

    Args:
        model_name: The model to route to
        prefer_gpu: Whether to prefer GPU-enabled nodes

    Returns:
        Node dict with connection info, or None if no nodes available
    """
    # Check cache first
    cache_key = f"{model_name}:{prefer_gpu}"
    cached = _node_cache.get(cache_key)
    if cached and (datetime.now() - cached["time"]).total_seconds() < _cache_ttl:
        # Return cached node if still valid
        return cached["node"]

    nodes = get_nodes_with_model(model_name)

    if not nodes:
        logger.debug(f"No bridge-enabled nodes have model {model_name}")
        return None

    # If only one node, return it
    if len(nodes) == 1:
        node = dict(nodes[0])
        _node_cache[cache_key] = {"node": node, "time": datetime.now()}
        return node

    # Calculate weights for each node
    weights = []
    for node in nodes:
        # Base weight from load (0-100 load -> 100-0 weight)
        load_factor = max(0.1, 1 - (node.get("current_load", 0) / 100))

        # Priority factor (0-100 priority -> 0-1 factor)
        priority_factor = node.get("bridge_priority", 50) / 100

        # GPU bonus
        gpu_bonus = 1.3 if (prefer_gpu and node.get("gpu_available")) else 1.0

        # Combined weight
        weight = load_factor * priority_factor * gpu_bonus * 100
        weights.append(max(weight, 1))  # Minimum weight of 1

    # Weighted random selection
    selected = random.choices(nodes, weights=weights, k=1)[0]
    node = dict(selected)

    # Cache the selection
    _node_cache[cache_key] = {"node": node, "time": datetime.now()}

    logger.debug(
        f"Selected node {node['node_name']} for model {model_name} "
        f"(load: {node.get('current_load', 0)}, priority: {node.get('bridge_priority', 50)})"
    )

    return node


def _resolve_best_host(node: Dict[str, Any]) -> str:
    """Resolve the best reachable host for a node.

    Priority: mesh_ip (encrypted, works LAN+WAN) → vpn_ip → hostname → fallback.
    """
    return node.get("mesh_ip") or node.get("vpn_ip") or node.get("hostname") or "unknown"


def get_ollama_url(model_name: str, prefer_gpu: bool = True) -> tuple:
    """
    Get the Ollama URL for a model request.

    Returns:
        Tuple of (url, node_id) where node_id is None if using fallback
    """
    node = select_best_node(model_name, prefer_gpu)

    if node:
        host = _resolve_best_host(node)
        url = f"http://{host}:{node.get('port', 11434)}"
        return url, node["node_id"]
    else:
        # Fallback to environment variable
        logger.info(f"Using fallback OLLAMA_HOST for model {model_name}")
        return get_fallback_host(), None


def log_model_request(
    node_id: Optional[str],
    model_name: str,
    request_type: str = "generate",
    tokens_in: int = None,
    tokens_out: int = None,
    response_ms: int = None,
    success: bool = True,
    error_message: str = None,
):
    """
    Log a model request for analytics and load tracking.

    Args:
        node_id: The node that handled the request (None if fallback)
        model_name: The model used
        request_type: 'generate', 'chat', or 'embed'
        tokens_in: Input token count
        tokens_out: Output token count
        response_ms: Response time in milliseconds
        success: Whether the request succeeded
        error_message: Error message if failed
    """
    if not node_id:
        return  # Don't log fallback requests

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO node_model_requests (
                node_id, model_name, request_type, tokens_in, tokens_out,
                response_ms, success, error_message
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                node_id,
                model_name,
                request_type,
                tokens_in,
                tokens_out,
                response_ms,
                success,
                error_message,
            ),
        )

        # Update model stats
        if success and response_ms:
            cur.execute(
                """
                UPDATE node_ollama_models
                SET total_requests = total_requests + 1,
                    avg_response_ms = COALESCE(
                        (avg_response_ms * total_requests + %s) / (total_requests + 1),
                        %s
                    ),
                    last_used = NOW(),
                    updated_at = NOW()
                WHERE node_id = %s AND model_name = %s
            """,
                (response_ms, response_ms, node_id, model_name),
            )

        # Node request stats. current_load is now HUB-DERIVED in the heartbeat
        # (V6) — no manual increment here (the old +5/cap-100 leaked/inflated).
        cur.execute(
            """
            UPDATE remote_nodes
            SET total_requests = total_requests + 1,
                successful_requests = successful_requests + %s,
                failed_requests = failed_requests + %s,
                updated_at = NOW()
            WHERE node_id = %s
        """,
            (1 if success else 0, 0 if success else 1, node_id),
        )

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"Error logging model request: {e}")


def clear_cache():
    """Clear the node selection cache"""
    global _node_cache
    _node_cache = {}


def get_model_availability() -> Dict[str, List[str]]:
    """
    Get a map of models to available nodes.

    Returns:
        Dict mapping model names to list of node names
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT m.model_name, ARRAY_AGG(n.node_name) as nodes
            FROM node_ollama_models m
            JOIN remote_nodes n ON m.node_id = n.node_id
            WHERE n.bridge_enabled = true
              AND n.status = 'online'
              AND m.is_available = true
            GROUP BY m.model_name
            ORDER BY m.model_name
        """
        )

        result = {row["model_name"]: row["nodes"] for row in cur.fetchall()}
        cur.close()
        conn.close()

        return result

    except Exception as e:
        logger.error(f"Error getting model availability: {e}")
        return {}


# ============================================
# Image Generation Service Routing (Phase 72)
# ============================================


def get_nodes_with_service(service_name: str) -> List[Dict[str, Any]]:
    """
    Find all bridge-enabled nodes that have a specific AI service available.

    Args:
        service_name: 'foocus', 'comfyui', or 'auto1111'

    Returns:
        List of node dicts with connection info
    """
    service_column = f"{service_name}_available"
    port_column = f"{service_name}_port"

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            f"""
            SELECT
                id,
                node_id,
                node_name,
                hostname,
                vpn_ip,
                mesh_ip,
                {port_column} as port,
                current_load,
                bridge_priority,
                gpu_available,
                gpu_model,
                gpu_vram_gb,
                status,
                deployment_mode
            FROM remote_nodes
            WHERE bridge_enabled = true
              AND status = 'online'
              AND approval_status = 'approved'
              AND {service_column} = true
              AND deployment_mode = 'starship'
            ORDER BY current_load ASC, bridge_priority DESC
        """
        )

        nodes = cur.fetchall()
        cur.close()
        conn.close()

        return nodes

    except Exception as e:
        logger.error(f"Error getting nodes with service {service_name}: {e}")
        return []


def select_best_image_node(service_name: str) -> Optional[Dict[str, Any]]:
    """
    Select the best available node for an image generation request.

    Prioritizes GPU-enabled nodes for image generation.

    Args:
        service_name: 'foocus', 'comfyui', or 'auto1111'

    Returns:
        Node dict with connection info, or None if no nodes available
    """
    # Check cache
    cache_key = f"image:{service_name}"
    cached = _node_cache.get(cache_key)
    if cached and (datetime.now() - cached["time"]).total_seconds() < _cache_ttl:
        return cached["node"]

    nodes = get_nodes_with_service(service_name)

    if not nodes:
        logger.debug(f"No bridge-enabled nodes have {service_name}")
        return None

    # Single node - return it
    if len(nodes) == 1:
        node = dict(nodes[0])
        _node_cache[cache_key] = {"node": node, "time": datetime.now()}
        return node

    # Calculate weights - heavily prefer GPU nodes for image generation
    weights = []
    for node in nodes:
        load_factor = max(0.1, 1 - (node.get("current_load", 0) / 100))
        priority_factor = node.get("bridge_priority", 50) / 100

        # Strong GPU preference for image generation
        gpu_bonus = 2.0 if node.get("gpu_available") else 0.5
        vram = node.get("gpu_vram_gb", 0) or 0
        vram_bonus = 1.0 + (vram / 24)  # Up to ~1.67x bonus for 16GB VRAM

        weight = load_factor * priority_factor * gpu_bonus * vram_bonus * 100
        weights.append(max(weight, 1))

    selected = random.choices(nodes, weights=weights, k=1)[0]
    node = dict(selected)

    _node_cache[cache_key] = {"node": node, "time": datetime.now()}

    logger.debug(
        f"Selected node {node['node_name']} for {service_name} "
        f"(GPU: {node.get('gpu_model', 'None')}, VRAM: {node.get('gpu_vram_gb', 0)}GB)"
    )

    return node


def get_foocus_url() -> tuple:
    """
    Get the Foocus URL for image generation.

    Returns:
        Tuple of (url, node_id) where node_id is None if using fallback
    """
    node = select_best_image_node("foocus")

    if node:
        host = _resolve_best_host(node)
        url = f"http://{host}:{node.get('port', 7865)}"
        return url, node["node_id"]
    else:
        logger.info("Using fallback FOOOCUS_URL")
        fallback = os.getenv("FOOOCUS_URL", "http://localhost:7865")
        return fallback, None


def get_comfyui_url() -> tuple:
    """
    Get the ComfyUI URL for node-based image generation.

    Returns:
        Tuple of (url, node_id) where node_id is None if using fallback
    """
    node = select_best_image_node("comfyui")

    if node:
        host = _resolve_best_host(node)
        url = f"http://{host}:{node.get('port', 8188)}"
        return url, node["node_id"]
    else:
        logger.info("Using fallback COMFYUI_URL")
        fallback = os.getenv("COMFYUI_URL", "http://localhost:8188")
        return fallback, None


def get_auto1111_url() -> tuple:
    """
    Get the Automatic1111 URL for Stable Diffusion WebUI.

    Returns:
        Tuple of (url, node_id) where node_id is None if using fallback
    """
    node = select_best_image_node("auto1111")

    if node:
        host = _resolve_best_host(node)
        url = f"http://{host}:{node.get('port', 7860)}"
        return url, node["node_id"]
    else:
        logger.info("Using fallback AUTO1111_URL")
        fallback = os.getenv("AUTO1111_URL", "http://localhost:7860")
        return fallback, None


def get_image_service_availability() -> Dict[str, List[str]]:
    """
    Get a map of image services to available nodes.

    Returns:
        Dict mapping service names to list of node names
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                node_name,
                foocus_available,
                comfyui_available,
                auto1111_available
            FROM remote_nodes
            WHERE bridge_enabled = true
              AND status = 'online'
              AND approval_status = 'approved'
        """
        )

        nodes = cur.fetchall()
        cur.close()
        conn.close()

        result = {"foocus": [], "comfyui": [], "auto1111": []}

        for node in nodes:
            if node.get("foocus_available"):
                result["foocus"].append(node["node_name"])
            if node.get("comfyui_available"):
                result["comfyui"].append(node["node_name"])
            if node.get("auto1111_available"):
                result["auto1111"].append(node["node_name"])

        return result

    except Exception as e:
        logger.error(f"Error getting image service availability: {e}")
        return {"foocus": [], "comfyui": [], "auto1111": []}


# Export main functions
__all__ = [
    "get_ollama_url",
    "select_best_node",
    "get_nodes_with_model",
    "log_model_request",
    "get_fallback_host",
    "clear_cache",
    "get_model_availability",
    # Image generation services (Phase 72)
    "get_foocus_url",
    "get_comfyui_url",
    "get_auto1111_url",
    "get_nodes_with_service",
    "select_best_image_node",
    "get_image_service_availability",
]
