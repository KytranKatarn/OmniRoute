"""
A.R.C.H.I.E. MCP Server - Main Server Implementation
Phase 50: AI Integration Hub

Implements Model Context Protocol for AI model integration.
Supports stdio transport for Claude Code and other MCP clients.
"""

import sys

# Mirror platform_v2/app.py:284-285 — make ai_bridge modules (e.g. `db`,
# `archie_bridge`) importable so handlers that pull in
# tools.department_hq.services.department_dispatcher resolve their bare
# `from db import ...` chain. Without this, PR #499's sync dispatch path
# (trigger_code_review, generate_code) raises ModuleNotFoundError at
# dispatch-import time and silently falls through to its static-analysis
# fallback. See task #1298.
for _p in ("/mnt/archie_brain", "/mnt/archie_brain/ai_bridge"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import os
from database import _get_db_password
import json
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
import requests

from mcp_server.dispatch_context import claude_request


class MCPJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects and other non-serializable types"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "__str__"):
            return str(obj)
        return super().default(obj)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/mnt/archie_brain/logs/mcp_server.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("archie_mcp")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": _get_db_password(),
}

# A.R.C.H.I.E. Platform base URL
PLATFORM_URL = os.getenv("ARCHIE_PLATFORM_URL", "http://archie_platform:3000")


@dataclass
class MCPTool:
    """Definition of an MCP tool"""

    name: str
    description: str
    input_schema: Dict[str, Any]
    category: str = "general"
    handler: Optional[Callable] = None
    endpoint_path: Optional[str] = None
    http_method: str = "POST"
    requires_auth: bool = True
    timeout_ms: int = 30000


@dataclass
class MCPResource:
    """Definition of an MCP resource"""

    uri: str
    name: str
    description: str
    mime_type: str = "application/json"


class ArchieMCPServer:
    """
    A.R.C.H.I.E. Model Context Protocol Server

    Exposes A.R.C.H.I.E. platform capabilities as MCP tools for AI models.
    Supports authentication, rate limiting, and audit logging.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session_id = self._generate_session_id()
        self.tools: Dict[str, MCPTool] = {}
        self.resources: Dict[str, MCPResource] = {}
        self.request_count = 0
        self.start_time = datetime.now()

        # Load tools from database
        self._load_tools_from_db()

        # Register built-in tools
        self._register_builtin_tools()

        # Load tools from tools package (Phase 50.2+)
        self._load_package_tools()

        logger.info(f"MCP Server initialized with {len(self.tools)} tools")

    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        import uuid

        return f"mcp-{uuid.uuid4().hex[:12]}"

    def _get_db_connection(self):
        """Get database connection"""
        try:
            import psycopg2

            conn = psycopg2.connect(**DB_CONFIG)
            return conn
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return None

    def _load_tools_from_db(self):
        """Load tool definitions from database"""
        conn = self._get_db_connection()
        if not conn:
            logger.warning("Could not load tools from database, using defaults only")
            return

        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT name, category, display_name, description, input_schema,
                       endpoint_path, http_method, requires_auth, timeout_ms
                FROM mcp_tool_definitions
                WHERE is_enabled = TRUE
            """
            )
            rows = cur.fetchall()

            for row in rows:
                tool = MCPTool(
                    name=row[0],
                    category=row[1],
                    description=row[3] or row[2] or row[0],
                    input_schema=(row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")),
                    endpoint_path=row[5],
                    http_method=row[6] or "POST",
                    requires_auth=row[7] if row[7] is not None else True,
                    timeout_ms=row[8] or 30000,
                )
                self.tools[tool.name] = tool

            cur.close()
            conn.close()
            logger.info(f"Loaded {len(rows)} tools from database")

        except Exception as e:
            logger.error(f"Error loading tools from database: {e}")
            if conn:
                conn.close()

    def _register_builtin_tools(self):
        """Register built-in tools that don't need database definitions"""

        # System status tool
        self.tools["ping"] = MCPTool(
            name="ping",
            description="Check if the A.R.C.H.I.E. MCP server is responsive",
            input_schema={"type": "object", "properties": {}},
            category="system",
            requires_auth=False,
            handler=self._handle_ping,
        )

        # List available tools
        self.tools["list_tools"] = MCPTool(
            name="list_tools",
            description="List all available MCP tools and their descriptions",
            input_schema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category (knowledge, creation, business, admin)",
                    }
                },
            },
            category="system",
            requires_auth=False,
            handler=self._handle_list_tools,
        )

        # Get server info
        self.tools["server_info"] = MCPTool(
            name="server_info",
            description="Get information about the A.R.C.H.I.E. MCP server",
            input_schema={"type": "object", "properties": {}},
            category="system",
            requires_auth=False,
            handler=self._handle_server_info,
        )

    def _load_package_tools(self):
        """Load tools from the tools package (Phase 50.2+)

        Package tools with handlers take precedence over database tools
        with HTTP endpoints, since they're more direct and efficient.
        """
        try:
            from .tools import get_all_tools

            package_tools = get_all_tools()
            loaded_count = 0
            upgraded_count = 0

            for tool_def in package_tools:
                name = tool_def["name"]

                # Check if tool exists and whether to override
                if name in self.tools:
                    existing = self.tools[name]
                    # Override if existing has no handler (HTTP endpoint) but package has handler
                    if not existing.handler and tool_def.get("handler"):
                        logger.info(f"Upgrading tool '{name}' from HTTP endpoint to direct handler")
                        upgraded_count += 1
                    else:
                        logger.debug(f"Skipping package tool '{name}' - already has handler")
                        continue

                tool = MCPTool(
                    name=name,
                    description=tool_def["description"],
                    input_schema=tool_def["input_schema"],
                    category=tool_def["category"],
                    handler=tool_def["handler"],
                    requires_auth=tool_def.get("requires_permission", "read") != "none",
                )
                self.tools[name] = tool
                loaded_count += 1

            logger.info(f"Loaded {loaded_count} tools from package ({upgraded_count} upgraded from HTTP)")

        except ImportError as e:
            logger.warning(f"Could not load package tools: {e}")
        except Exception as e:
            logger.error(f"Error loading package tools: {e}")

    async def _handle_ping(self, params: Dict) -> Dict:
        """Handle ping tool"""
        return {
            "status": "ok",
            "message": "A.R.C.H.I.E. MCP Server is running",
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
        }

    async def _handle_list_tools(self, params: Dict) -> Dict:
        """Handle list_tools tool"""
        category_filter = params.get("category")

        tools_list = []
        for name, tool in self.tools.items():
            if category_filter and tool.category != category_filter:
                continue
            tools_list.append(
                {
                    "name": name,
                    "category": tool.category,
                    "description": tool.description,
                    "requires_auth": tool.requires_auth,
                }
            )

        # Group by category
        by_category = {}
        for t in tools_list:
            cat = t["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(t)

        return {
            "total_tools": len(tools_list),
            "by_category": by_category,
            "tools": tools_list,
        }

    async def _handle_server_info(self, params: Dict) -> Dict:
        """Handle server_info tool"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        return {
            "name": "A.R.C.H.I.E. MCP Server",
            "version": "1.0.0",
            "platform": "A.R.C.H.I.E. Platform v5.14.0",
            "session_id": self.session_id,
            "uptime_seconds": uptime,
            "total_tools": len(self.tools),
            "requests_handled": self.request_count,
            "categories": list(set(t.category for t in self.tools.values())),
        }

    async def call_tool(self, name: str, params: Dict) -> Dict:
        """
        Call an MCP tool by name with given parameters

        Args:
            name: Tool name
            params: Tool input parameters

        Returns:
            Tool execution result
        """
        self.request_count += 1
        start_time = datetime.now()

        if name not in self.tools:
            return {
                "error": True,
                "code": "TOOL_NOT_FOUND",
                "message": f"Tool '{name}' not found. Use 'list_tools' to see available tools.",
            }

        tool = self.tools[name]

        # Sanitize params: MCP transport may send integers as strings or arrays as JSON strings
        schema_props = tool.input_schema.get("properties", {}) if tool.input_schema else {}
        for key, val in params.items():
            if not isinstance(val, str):
                continue
            prop_schema = schema_props.get(key, {})
            prop_type = prop_schema.get("type")
            if prop_type == "integer" and val.isdigit():
                params[key] = int(val)
            elif prop_type == "array" and val.startswith("["):
                try:
                    params[key] = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    pass

        try:
            # Tag this call as a Claude MCP-initiated request — any
            # `department_dispatcher.dispatch()` invoked downstream will
            # write request_origin='claude' + mcp_tool=<name> to
            # task_execution_log (Tasks #1297/#1298, ADR-013).
            with claude_request(mcp_tool=name):
                # If tool has a direct handler, use it
                if tool.handler:
                    result = await tool.handler(params)
                # Otherwise, call the HTTP endpoint
                elif tool.endpoint_path:
                    result = await self._call_http_endpoint(tool, params)
                else:
                    return {
                        "error": True,
                        "code": "NO_HANDLER",
                        "message": f"Tool '{name}' has no handler configured",
                    }

            # Log successful call with output info
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            result_str = json.dumps(result, cls=MCPJSONEncoder) if result else ""
            output_size = len(result_str)
            # Build a short summary from result keys or message
            output_summary = None
            if isinstance(result, dict):
                if result.get("message"):
                    output_summary = str(result["message"])[:200]
                elif result.get("summary"):
                    output_summary = str(result["summary"])[:200]
                else:
                    output_summary = f"keys={list(result.keys())[:5]}"
            self._log_tool_usage(
                name,
                tool.category,
                params,
                True,
                execution_time,
                output_summary=output_summary,
                output_size=output_size,
            )

            return {
                "success": True,
                "tool": name,
                "result": result,
                "execution_time_ms": round(execution_time, 2),
            }

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            error_msg = str(e)

            # Log failed call
            self._log_tool_usage(
                name,
                tool.category,
                params,
                False,
                execution_time,
                error_msg=error_msg,
            )

            logger.error(f"Tool '{name}' failed: {error_msg}\n{traceback.format_exc()}")

            return {
                "error": True,
                "code": "EXECUTION_ERROR",
                "message": error_msg,
                "tool": name,
            }

    async def _call_http_endpoint(self, tool: MCPTool, params: Dict) -> Dict:
        """Call an HTTP endpoint for a tool"""
        url = f"{PLATFORM_URL}{tool.endpoint_path}"

        headers = {
            "Content-Type": "application/json",
            "X-MCP-Session": self.session_id,
            "X-MCP-Tool": tool.name,
        }

        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            timeout = tool.timeout_ms / 1000  # Convert to seconds

            if tool.http_method.upper() == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
            elif tool.http_method.upper() == "POST":
                response = requests.post(url, json=params, headers=headers, timeout=timeout)
            elif tool.http_method.upper() == "PUT":
                response = requests.put(url, json=params, headers=headers, timeout=timeout)
            elif tool.http_method.upper() == "DELETE":
                response = requests.delete(url, params=params, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {tool.http_method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            raise TimeoutError(f"Tool '{tool.name}' timed out after {tool.timeout_ms}ms")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"HTTP error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"Request failed: {str(e)}")

    def _log_tool_usage(
        self,
        tool_name: str,
        category: str,
        params: Dict,
        success: bool,
        execution_time_ms: float,
        error_msg: str = None,
        output_summary: str = None,
        output_size: int = None,
    ):
        """Log tool usage to database with full audit trail."""
        conn = self._get_db_connection()
        if not conn:
            return

        try:
            # Build client info from session context
            client_info = {
                "client": "claude-code",
                "session": self.session_id,
                "pid": os.getpid(),
            }

            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO mcp_tool_usage
                (session_id, tool_name, tool_category, input_params, success,
                 execution_time_ms, error_message, output_summary,
                 output_size_bytes, client_info, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
                (
                    self.session_id,
                    tool_name,
                    category,
                    json.dumps(params),
                    success,
                    int(execution_time_ms),
                    error_msg,
                    output_summary,
                    output_size,
                    json.dumps(client_info),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log tool usage: {e}")
            if conn:
                conn.close()

    def get_tools_list(self) -> List[Dict]:
        """Get list of tools in MCP format"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self.tools.values()
        ]

    def get_resources_list(self) -> List[Dict]:
        """Get list of resources in MCP format"""
        return [
            {
                "uri": resource.uri,
                "name": resource.name,
                "description": resource.description,
                "mimeType": resource.mime_type,
            }
            for resource in self.resources.values()
        ]


# ============================================================================
# MCP Protocol Handler (stdio transport)
# ============================================================================


class MCPProtocolHandler:
    """
    Handles MCP protocol messages over stdio

    Implements the JSON-RPC based MCP protocol for communication
    with Claude Code and other MCP clients.
    """

    def __init__(self, server: ArchieMCPServer):
        self.server = server
        self.running = False

    async def handle_message(self, message: Dict) -> Optional[Dict]:
        """Handle incoming MCP message. Returns None for notifications."""
        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")
        is_notification = "id" not in message

        logger.debug(f"Handling MCP message: {method} (notification={is_notification})")

        try:
            # Handle notifications (no id field) - must not send a response
            if is_notification:
                if method == "notifications/initialized":
                    logger.info("Client initialization confirmed")
                elif method == "notifications/cancelled":
                    logger.info(f"Client cancelled request: {params}")
                elif method.startswith("notifications/"):
                    logger.debug(f"Received notification: {method}")
                else:
                    logger.debug(f"Ignoring unknown notification: {method}")
                return None

            # Handle requests (have id field) - must send a response
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = {"tools": self.server.get_tools_list()}
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                tool_result = await self.server.call_tool(tool_name, tool_args)
                # MCP protocol requires tools/call results in content array format
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(tool_result, cls=MCPJSONEncoder, indent=2),
                        }
                    ],
                    "isError": tool_result.get("error", False),
                }
            elif method == "resources/list":
                result = {"resources": self.server.get_resources_list()}
            elif method == "resources/read":
                result = await self._handle_resource_read(params)
            elif method == "ping":
                result = {}
            else:
                return self._error_response(msg_id, -32601, f"Method not found: {method}")

            return self._success_response(msg_id, result)

        except Exception as e:
            logger.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            return self._error_response(msg_id, -32603, str(e))

    def _handle_initialize(self, params: Dict) -> Dict:
        """Handle initialize request"""
        client_info = params.get("clientInfo", {})
        logger.info(f"MCP client connected: {client_info.get('name', 'unknown')}")

        return {
            "protocolVersion": "2025-11-25",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": True},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": "archie-mcp-server", "version": "1.0.0"},
        }

    async def _handle_resource_read(self, params: Dict) -> Dict:
        """Handle resource read request"""
        uri = params.get("uri", "")
        # Resource reading will be implemented in Phase 50.6
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/plain",
                    "text": f"Resource reading not yet implemented for: {uri}",
                }
            ]
        }

    def _success_response(self, msg_id: Any, result: Any) -> Dict:
        """Create success response"""
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _error_response(self, msg_id: Any, code: int, message: str) -> Dict:
        """Create error response"""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    async def run_stdio(self):
        """Run MCP server with stdio transport (newline-delimited JSON)"""
        self.running = True
        logger.info("A.R.C.H.I.E. MCP Server starting with stdio transport...")

        loop = asyncio.get_event_loop()

        def read_line():
            """Read a line from stdin"""
            return sys.stdin.readline()

        logger.info("MCP Server ready for connections")

        while self.running:
            try:
                line = await loop.run_in_executor(None, read_line)
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                message = json.loads(line)

                # Handle message
                response = await self.handle_message(message)

                # Only send response for requests (not notifications)
                if response is not None:
                    sys.stdout.write(json.dumps(response, cls=MCPJSONEncoder) + "\n")
                    sys.stdout.flush()

            except asyncio.CancelledError:
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON on stdin: {e}")
                continue
            except Exception as e:
                logger.error(f"Error in stdio loop: {e}")
                traceback.print_exc(file=sys.stderr)
                continue

        logger.info("MCP Server shutting down")

    def stop(self):
        """Stop the server"""
        self.running = False


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Main entry point for MCP server"""
    import argparse

    parser = argparse.ArgumentParser(description="A.R.C.H.I.E. MCP Server")
    parser.add_argument("--api-key", help="API key for authentication")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create server
    server = ArchieMCPServer(api_key=args.api_key)
    handler = MCPProtocolHandler(server)

    # Run with stdio transport
    try:
        asyncio.run(handler.run_stdio())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
