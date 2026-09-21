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

from typing import Dict, List, Callable, Any

# Tool registry
_tools: Dict[str, Dict] = {}


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
