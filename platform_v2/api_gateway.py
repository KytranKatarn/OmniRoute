"""
API Gateway — REST endpoints for ARCHIE Code CLI and external tools.

Exposes MCP tool handlers via HTTP REST API with API key authentication.
Single endpoint pattern: POST /api/v1/tools/<tool_name> with JSON body.

This is the bridge between the CLI hub connector and the MCP tool handlers.
"""

import os
import json
import logging
import asyncio
from functools import wraps
from datetime import datetime
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

api_gateway_bp = Blueprint("api_gateway", __name__)

# API key auth
API_KEYS = set()


def _load_api_keys():
    """Load valid API keys from environment or database."""
    # Default dev key for local testing
    dev_key = os.environ.get("ARCHIE_API_GATEWAY_KEY", "local-dev")
    if dev_key:
        API_KEYS.add(dev_key)
    # TODO: Load from database for production multi-key support


_load_api_keys()


def require_api_key(f):
    """Require valid API key in Authorization header."""

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if token in API_KEYS:
                return f(*args, **kwargs)
        return jsonify({"error": "unauthorized", "status": 401}), 401

    return decorated


# MCP server singleton (lazy loaded)
_mcp_server = None


def _get_mcp_tools():
    """Get MCP tool handlers from the tools package."""
    global _mcp_server
    if _mcp_server is not None:
        return _mcp_server

    try:
        from mcp_server.tools import get_all_tools

        tools = get_all_tools()
        _mcp_server = {t["name"]: t for t in tools}
        logger.info("API Gateway loaded %d MCP tools", len(_mcp_server))
    except Exception as e:
        logger.error("Failed to load MCP tools: %s", e)
        _mcp_server = {}

    return _mcp_server


def _run_async(coro):
    """Run async handler in sync Flask context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=60)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ─────────────────────────────────────────────
# Generic tool endpoint
# ─────────────────────────────────────────────


@api_gateway_bp.route("/api/v1/tools/<tool_name>", methods=["POST"])
@require_api_key
def execute_tool(tool_name):
    """Execute any MCP tool by name. Body is the tool's input params."""
    tools = _get_mcp_tools()
    tool = tools.get(tool_name)

    if not tool:
        return (
            jsonify(
                {
                    "error": f"Tool not found: {tool_name}",
                    "available": sorted(tools.keys()),
                }
            ),
            404,
        )

    params = request.get_json(silent=True) or {}
    handler = tool.get("handler")

    if not handler:
        return jsonify({"error": f"Tool '{tool_name}' has no handler"}), 501

    try:
        result = _run_async(handler(params))
        return jsonify({"success": True, "tool": tool_name, "result": result})
    except Exception as e:
        logger.error("Tool %s failed: %s", tool_name, e)
        return jsonify({"error": str(e), "tool": tool_name}), 500


# ─────────────────────────────────────────────
# Discovery endpoints (no auth required)
# ─────────────────────────────────────────────


@api_gateway_bp.route("/api/v1/tools", methods=["GET"])
def list_tools():
    """List all available tools with metadata."""
    tools = _get_mcp_tools()
    category_filter = request.args.get("category")

    tool_list = []
    for name, t in sorted(tools.items()):
        cat = t.get("category", "unknown")
        if category_filter and cat != category_filter:
            continue
        tool_list.append(
            {
                "name": name,
                "description": t.get("description", ""),
                "category": cat,
            }
        )

    return jsonify(
        {
            "total": len(tool_list),
            "tools": tool_list,
        }
    )


@api_gateway_bp.route("/api/v1/health", methods=["GET"])
def gateway_health():
    """API gateway health check."""
    tools = _get_mcp_tools()
    return jsonify(
        {
            "status": "ok",
            "tools_loaded": len(tools),
            "timestamp": datetime.now().isoformat(),
        }
    )


# ─────────────────────────────────────────────
# Node registration + heartbeat
# ─────────────────────────────────────────────


@api_gateway_bp.route("/api/v1/nodes/register", methods=["POST"])
@require_api_key
def register_node():
    """Register a CLI node with the hub."""
    data = request.get_json(silent=True) or {}
    import uuid

    node_id = str(uuid.uuid4())[:12]

    logger.info("Node registered: %s (hostname=%s)", node_id, data.get("hostname"))

    return jsonify(
        {
            "node_id": node_id,
            "status": "registered",
            "tools_available": len(_get_mcp_tools()),
        }
    )


@api_gateway_bp.route("/api/v1/nodes/<node_id>/heartbeat", methods=["POST"])
@require_api_key
def node_heartbeat(node_id):
    """Receive heartbeat from a CLI node."""
    return jsonify({"status": "ok", "node_id": node_id})
