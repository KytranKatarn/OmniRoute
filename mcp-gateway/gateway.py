"""
Read-only MCP HTTP gateway for the Codex CLI container.

Exposes the three knowledge READ tools (search_knowledge, search_mistakes,
recall_context) plus Dev HQ TASK tools (get_projects, get_my_tasks, get_task,
create_task, set_task_status, add_task_note) over streamable HTTP.

The knowledge tools reuse the platform's existing handlers
(`mcp_server.tools.knowledge`). It connects to Postgres as the read-only `codex_ro`
role and requires a valid read-scoped bearer (validated against `mcp_api_keys`).

Trust boundary: the Codex container holds ONLY the bearer token — never DB creds.
This gateway holds the (read-only) DB creds. Defense in depth:
  container has no creds  ->  bearer is read-scoped  ->  DB role is read-only.

Run: uvicorn gateway:app --host 0.0.0.0 --port 7800   (see entrypoint.sh)
"""
import contextvars
import asyncio
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

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

# Bearer permissions for the CURRENT request. The middleware below validates the
# token once; write tools re-check here. Without this, every tool would sit behind
# the middleware's single `"read" in permissions` test and a READ-scoped bearer
# could create and close tasks.
_PERMS: contextvars.ContextVar[tuple] = contextvars.ContextVar("perms", default=())

# Dev HQ task access goes over the hub's INTERNAL HTTP API, never the DB. That
# keeps this gateway's Postgres role read-only (`codex_ro`) exactly as before, and
# puts every task mutation through the hub's own scope check, validation and audit
# trail. The key below is scoped to {tasks:read, tasks:write} and NOTHING else —
# no delegation (the lane must not be able to spend fleet compute), no approvals,
# no engine, no repair. See services/internal_auth.CALLER_SCOPES["opencode"].
_HUB_URL = os.getenv("ARCHIE_HUB_URL", "http://archie_platform:3000").rstrip("/")
_TASK_KEY = os.getenv("INTERNAL_API_KEY_OPENCODE", "")


def _hub_call(method: str, path: str, payload: dict | None = None) -> dict:
    """One blocking hub round-trip. Never raises — returns {"error": ...}."""
    if not _TASK_KEY:
        return {"error": "task access not configured (INTERNAL_API_KEY_OPENCODE unset)"}
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(_HUB_URL + path, data=body, method=method)
    req.add_header("Authorization", "Bearer " + _TASK_KEY)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        # Surface the hub's own refusal verbatim — a 403 scope_denied must read as
        # a scope problem, not as a mystery failure inside the lane.
        detail = ""
        try:
            detail = exc.read().decode()[:400]
        except Exception:
            pass
        return {"error": "hub %s" % exc.code, "detail": detail}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


async def _hub(method: str, path: str, payload: dict | None = None) -> dict:
    # urllib is blocking; keep the event loop free.
    return await asyncio.to_thread(_hub_call, method, path, payload)


def _needs_write() -> dict | None:
    """Return an error dict unless this request's bearer carries 'write'."""
    if "write" not in (_PERMS.get() or ()):
        return {"error": "forbidden: this token is read-scoped; task writes need a write-scoped key"}
    return None

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


@mcp.tool()
async def get_projects(status: str | None = None, limit: int = 25) -> dict:
    """List Dev HQ projects. Use this to find the project a task belongs to before
    creating work, so tasks do not land unparented."""
    q = "?limit=%d" % int(limit) + ("&status=%s" % status if status else "")
    return await _hub("GET", "/api/internal/projects" + q)


@mcp.tool()
async def get_my_tasks(
    project_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 25,
) -> dict:
    """List Dev HQ tasks (read-only). Check what is already open BEFORE starting work —
    duplicate tasks for one piece of work are a recurring problem on this platform."""
    parts = ["limit=%d" % int(limit)]
    if project_id:
        parts.append("project_id=%d" % int(project_id))
    if status:
        parts.append("status=%s" % status)
    if q:
        parts.append("q=%s" % urllib.parse.quote(q))
    return await _hub("GET", "/api/internal/tasks?" + "&".join(parts))


@mcp.tool()
async def get_task(task_id: int) -> dict:
    """Read one Dev HQ task in full, including its description."""
    return await _hub("GET", "/api/internal/tasks/%d" % int(task_id))


@mcp.tool()
async def create_task(
    project_id: int, title: str, description: str = "", priority: int = 5
) -> dict:
    """Create a Dev HQ task. `priority` is an INTEGER 1-10 (not a word). Search
    get_my_tasks first — do not open a second task for work already tracked."""
    err = _needs_write()
    if err:
        return err
    return await _hub(
        "POST",
        "/api/internal/tasks",
        {
            "project_id": project_id,
            "title": title,
            "description": description,
            "priority": priority,
        },
    )


@mcp.tool()
async def set_task_status(task_id: int, status: str) -> dict:
    """Update a Dev HQ task's status — this is how work gets CLOSED. Pass the
    status the platform uses (e.g. 'completed', 'in_progress', 'blocked')."""
    err = _needs_write()
    if err:
        return err
    return await _hub("POST", "/api/internal/tasks/%d/status" % int(task_id), {"status": status})


@mcp.tool()
async def add_task_note(task_id: int, note: str) -> dict:
    """Append a work note to a Dev HQ task — what you did, what you found, what is
    left. A closed task with no note is not a record anyone can use later."""
    err = _needs_write()
    if err:
        return err
    return await _hub("POST", "/api/internal/tasks/%d/note" % int(task_id), {"note": note})


class BearerAuth(BaseHTTPMiddleware):
    """Require a valid read-scoped bearer on every request except /health."""

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        info = _auth.validate_api_key(token) if token else None
        perms = tuple(info.get("permissions") or []) if info else ()
        if not info or "read" not in perms:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        # Publish for the per-tool write check. Set INSIDE dispatch so it is scoped
        # to this request's context and cannot leak across concurrent callers.
        _PERMS.set(perms)
        return await call_next(request)


# Streamable-HTTP ASGI app (MCP endpoint mounted at /mcp by FastMCP).
app = mcp.streamable_http_app()
app.add_middleware(BearerAuth)
app.router.routes.append(Route("/health", lambda r: PlainTextResponse("ok")))
