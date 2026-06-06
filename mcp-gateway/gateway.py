"""
Read-only MCP HTTP gateway for the Codex CLI container.

Exposes ONLY the three knowledge READ tools (search_knowledge, search_mistakes,
recall_context) over streamable HTTP, reusing the platform's existing handlers
(`mcp_server.tools.knowledge`). It connects to Postgres as the read-only `codex_ro`
role and requires a valid read-scoped bearer (validated against `mcp_api_keys`).

Trust boundary: the Codex container holds ONLY the bearer token — never DB creds.
This gateway holds the (read-only) DB creds. Defense in depth:
  container has no creds  ->  bearer is read-scoped  ->  DB role is read-only.

Run: uvicorn gateway:app --host 0.0.0.0 --port 7800   (see entrypoint.sh)
"""
import os
import sys

# platform code (handlers, auth) lives at /app in the platform image we build FROM
sys.path.insert(0, "/app")

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from mcp_server.auth import MCPAuthenticator
from mcp_server.tools.knowledge import (
    search_knowledge_handler,
    recall_context_handler,
)

_auth = MCPAuthenticator()

mcp = FastMCP("archie-kb-readonly", host="0.0.0.0", port=7800)


@mcp.tool()
async def search_knowledge(
    query: str,
    types: list | None = None,
    category: str | None = None,
    limit: int = 10,
) -> dict:
    """Search A.R.C.H.I.E.'s knowledge base (read-only). Use this to ground code
    changes in the platform's real architecture, patterns, and prior decisions.
    `types` may include: mistake_learned, vault_note, code_snippet, github_file,
    conversation_memory."""
    return await search_knowledge_handler(
        {"query": query, "types": types, "category": category, "limit": limit}
    )


@mcp.tool()
async def search_mistakes(query: str, limit: int = 10) -> dict:
    """Search learned mistakes (read-only) — check before risky or pattern-sensitive
    work to avoid repeating known errors."""
    return await search_knowledge_handler(
        {"query": query, "types": ["mistake_learned"], "limit": limit}
    )


@mcp.tool()
async def recall_context(
    topic: str, context_type: str | None = None, limit: int = 5
) -> dict:
    """Recall historical context for a topic (read-only) — memories, related
    mistakes, and procedures for the area you're working in."""
    return await recall_context_handler(
        {"topic": topic, "context_type": context_type, "limit": limit}
    )


class BearerAuth(BaseHTTPMiddleware):
    """Require a valid read-scoped bearer on every request except /health."""

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        info = _auth.validate_api_key(token) if token else None
        if not info or "read" not in (info.get("permissions") or []):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


# Streamable-HTTP ASGI app (MCP endpoint mounted at /mcp by FastMCP).
app = mcp.streamable_http_app()
app.add_middleware(BearerAuth)
app.router.routes.append(Route("/health", lambda r: PlainTextResponse("ok")))
