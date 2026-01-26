"""
A.R.C.H.I.E. MCP Server - Tools Package
Phase 50: AI Integration Hub - COMPLETE
Phase 64: Claude Code Integration - COMPLETE
Phase 65: Unified Project Management - COMPLETE

This package contains tool implementations for the MCP server.
Tools are organized by category:
- knowledge: Memory and knowledge base operations (6 tools)
- creation: Project and content creation (6 tools)
- business: Business operations (CRM, invoicing, etc.) (7 tools)
- admin: System administration (8 tools)
- advanced: Workflows, rate limits, audit, health (12 tools)
- claude: Claude Code integration (6 tools)
- project: Unified project management (15 tools)
- consciousness: Self-awareness tools (3 tools)
- work: Work session context tracking (6 tools)

Total: 69 tools
"""

from typing import Dict, List, Callable, Any

# Tool registry
_tools: Dict[str, Dict] = {}


def register_tool(name: str, category: str, description: str,
                  input_schema: Dict, handler: Callable,
                  requires_permission: str = 'read'):
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
        'name': name,
        'category': category,
        'description': description,
        'input_schema': input_schema,
        'handler': handler,
        'requires_permission': requires_permission
    }


def get_tool(name: str) -> Dict:
    """Get a registered tool by name"""
    return _tools.get(name)


def get_all_tools() -> List[Dict]:
    """Get all registered tools"""
    return list(_tools.values())


def get_tools_by_category(category: str) -> List[Dict]:
    """Get tools filtered by category"""
    return [t for t in _tools.values() if t['category'] == category]


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
