"""
A.R.C.H.I.E. MCP Server - Tools Package
Phase 50: AI Integration Hub - COMPLETE
Phase 64: Claude Code Integration - COMPLETE
Phase 65: Unified Project Management - COMPLETE

This package contains tool implementations for the MCP server.
Tools are organized by category:
- knowledge: Memory and knowledge base operations (9 tools)
- creation: Project and content creation (5 tools)
- business: Business operations (CRM, invoicing, etc.) (7 tools)
- admin: System administration (9 tools)
- advanced: Workflows, rate limits, audit, health (12 tools)
- claude: Claude Code integration (10 tools)
- project: Unified project management (12 tools)
- consciousness: Self-awareness & processing tools (5 tools)
- work: Work session context tracking (6 tools)
- ai_command: AI Command operations - performance, ethics, health (6 tools)
- forge: F.O.R.G.E. self-healing pipeline - health, stats, self-heal, PRs, deploy (5 tools)

Total: 85 tools
"""

from typing import Dict, List, Callable, Any, Optional

# Tool registry
_tools: Dict[str, Dict] = {}


def internal_api(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    """Call the hub's scoped `/api/internal/*` surface as the coder-lane gateway.

    The lane's own DB role (`codex_ro`) is deliberately SELECT-only on a narrow
    table set, so agent/roster tools must not read `agents` or `bridge_stations`
    directly. docker-compose.yml states the intent outright: task/agent tools
    "call the hub's INTERNAL HTTP API (never the DB), so the Postgres role above
    stays read-only." This is that call. The key is scoped by
    `services.internal_auth.CALLER_SCOPES["coder_lanes"]` to
    {tasks:read, tasks:write, agents:read, agents:manage, delegation} — a route
    outside those families answers 403, which is the point: the lane's reach is
    the scope table, not a blanket credential.

    Returns `{"ok": bool, ...}`. `ok=False` carries `error` and, for an auth
    failure, `status`, so a caller can distinguish "not configured" from
    "forbidden" from "hub unreachable" instead of surfacing a stack trace.
    """
    import os

    import requests

    base = os.getenv("ARCHIE_HUB_URL", "http://archie_platform:3000").rstrip("/")
    key = os.getenv("INTERNAL_API_KEY_CODER_LANES", "")
    if not key:
        return {
            "ok": False,
            "error": "INTERNAL_API_KEY_CODER_LANES is not set on this gateway",
        }

    url = f"{base}{path if path.startswith('/') else '/' + path}"
    try:
        response = requests.get(
            url,
            params=params or None,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        return {"ok": False, "error": f"hub unreachable at {base}: {e}"}

    if response.status_code in (301, 302, 307, 308):
        # The internal API answers 401/403 for a bad or unscoped key; a redirect
        # means the request escaped to the Flask-Login surface and got the HTML
        # login page, so there is no JSON to parse.
        return {
            "ok": False,
            "status": response.status_code,
            "error": "redirected to auth — not an /api/internal route",
        }
    if response.status_code == 403:
        return {"ok": False, "status": 403, "error": "caller lacks the scope for this route"}
    if response.status_code == 401:
        return {"ok": False, "status": 401, "error": "internal key rejected"}
    if response.status_code != 200:
        return {"ok": False, "status": response.status_code, "error": f"HTTP {response.status_code}"}

    try:
        payload = response.json()
    except ValueError as e:
        return {"ok": False, "error": f"hub returned non-JSON: {e}"}

    if isinstance(payload, dict) and payload.get("success") is False:
        return {"ok": False, "error": payload.get("error", "hub reported failure")}
    return {"ok": True, "data": payload}


def cap_limit(arguments: Dict[str, Any], default: int, cap: int) -> int:
    """Return a sane `limit` from tool arguments.

    The MCP SDK passes `None` for optional arguments the caller omitted, so the
    naive `min(arguments.get("limit", n), cap)` raises
    `TypeError: '<' not supported between instances of 'int' and 'NoneType'`
    on EVERY omission. Coerce None / garbage to the default, then cap.
    """
    raw = arguments.get("limit", default)
    try:
        if raw is None:
            return default
        return max(1, min(int(raw), cap))
    except (TypeError, ValueError):
        return default


def register_tool(
    name: str,
    category: str,
    description: str,
    input_schema: Dict,
    handler: Callable,
    requires_permission: str = "read",
):
    """
    Register a tool with the MCP server

    Args:
        name: Unique tool name
        category: Tool category
        description: Tool description for AI
        input_schema: JSON Schema for input validation
        handler: Async function to handle tool calls
        requires_permission: Required permission level
    """
    _tools[name] = {
        "name": name,
        "category": category,
        "description": description,
        "input_schema": input_schema,
        "handler": handler,
        "requires_permission": requires_permission,
    }


def get_tool(name: str) -> Dict:
    """Get a registered tool by name"""
    return _tools.get(name)


def get_all_tools() -> List[Dict]:
    """Get all registered tools"""
    return list(_tools.values())


def get_tools_by_category(category: str) -> List[Dict]:
    """Get tools filtered by category"""
    return [t for t in _tools.values() if t["category"] == category]


# Import tool modules to register them
# Phase 50.2: Knowledge tools
from . import knowledge

# Phase 50.3: Creation tools
from . import creation

# Phase 50.4: Business tools
from . import business

# Phase 50.5: Admin tools
from . import admin

# Phase 50.6: Advanced tools
from . import advanced

# Phase 64: Claude Code Integration tools
from . import claude_tools

# Phase 65: Unified Project Management tools
from . import project_tools

# P1: AI Command tools
from . import ai_command_tools

# F.O.R.G.E.: Self-healing code pipeline tools
from . import forge_tools

# P.R.O.B.E.: QA testing tools
from . import qa_tools
