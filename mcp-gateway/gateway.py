"""MCP HTTP gateway for the containerised coder lanes (codex, opencode).

Gives both lanes the platform's READ tools in-process, and WRITE capability through
the hub's scoped internal HTTP API — never by writing to Postgres directly.

    lane --bearer--> gateway --+--> read handlers, in-process, role `codex_ro`
                               +--> GET /api/internal/*, scoped internal key, for reads
                               |   that observe host state this container cannot see
                               +--> POST /api/internal/*, scoped internal key, for writes

WHY THE SPLIT (owner decision 2026-09-13). The obvious implementation is to serve all
~105 registry tools in-process and give this container a write-capable Postgres role.
That was rejected: it removes BOTH of this gateway's defences at once — the read-only
tool set AND the read-only database role — leaving the bearer's permission list as the
only thing between a third-party coding agent and the whole schema.

Keeping `codex_ro` means a bug anywhere in this file, or a stolen bearer, still cannot
write a row. Writes instead go where they are individually scoped, validated and
audited by the platform itself (`services/internal_auth.require_internal_scope`).

The cost is honest and worth stating: this is NOT every tool Claude has. Writes cover
what the internal API exposes — tasks, agent/team management, delegation, and memory
(store_memory) — and nothing more. Adding a write capability means adding a scoped route
on the hub, deliberately, rather than it appearing here for free.

⚠️ Read tools run as `codex_ro`. A read tool that needs a table `codex_ro` cannot see
will fail at the DB, not here; that is the role doing its job, not a gateway bug.

The other failure mode is the opposite: a read tool that observes something this
container structurally CANNOT see, which returns a confident wrong answer rather than
an error. `_HUB_PROXIED_READS` names those. The first entry is V.I.G.I.L.'s infra
heartbeat — no docker socket here means every container reads as removed. Serving a
false "9 of 10 critical containers DOWN" to a coding agent is worse than withholding
the tool, so it is proxied to the hub instead.

Run: uvicorn gateway:app --host 0.0.0.0 --port 7800   (see entrypoint.sh)
"""

import contextvars
import inspect
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# platform code (handlers, auth, registry) lives at /app in the image we build FROM
sys.path.insert(0, "/app")

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from mcp_server.auth import MCPAuthenticator
from mcp_server.tools import get_all_tools

logger = logging.getLogger("archie_mcp.gateway")

_auth = MCPAuthenticator()

# Permissions of the CURRENT request's bearer. A ContextVar, not a global, so
# concurrent callers holding different bearers cannot observe each other's grants.
_PERMS: contextvars.ContextVar[tuple] = contextvars.ContextVar("perms", default=())

_HUB_URL = os.getenv("ARCHIE_HUB_URL", "http://archie_platform:3000").rstrip("/")
_HUB_KEY = os.getenv("INTERNAL_API_KEY_CODER_LANES", "")


def _needs_write():
    """Error dict unless this request's bearer carries 'write'; None if it does.

    The middleware below only proves the bearer is valid and has 'read'. Without this
    second check a READ-scoped bearer could call every write tool.
    """
    if "write" not in (_PERMS.get() or ()):
        return {"success": False, "error": "forbidden: this token is read-scoped"}
    return None


def _needs_read():
    """Error dict unless this request's bearer carries 'read'; None if it does."""
    if "read" not in (_PERMS.get() or ()):
        return {"success": False, "error": "forbidden: this token has no read grant"}
    return None


def _hub_call(method: str, path: str, payload=None) -> dict:
    """One blocking round-trip to the hub's internal API. Never raises."""
    if not _HUB_KEY:
        return {"success": False, "error": "write access not configured (INTERNAL_API_KEY_CODER_LANES unset)"}
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(_HUB_URL + path, data=body, method=method)
    req.add_header("Authorization", "Bearer " + _HUB_KEY)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:400]
        except Exception:
            pass
        # Surface the hub's own refusal verbatim. A 403 scope_denied must read as a
        # scope problem, not as a mystery failure inside the lane.
        return {"success": False, "error": "hub %s" % exc.code, "detail": detail}
    except Exception as exc:
        return {"success": False, "error": "%s: %s" % (type(exc).__name__, exc)}


async def _hub(method: str, path: str, payload=None) -> dict:
    import asyncio

    return await asyncio.to_thread(_hub_call, method, path, payload)


# ---------------------------------------------------------------------------
# READ tools — the platform registry, in-process, on the read-only role
# ---------------------------------------------------------------------------


def _build_read_tool(spec: dict) -> Tool:
    """Wrap one read-permission registry entry, preserving its real JSON schema.

    FastMCP infers a schema from the function signature, which would discard the
    platform's hand-written schemas (field descriptions, enums, required lists) — the
    things that make a tool usable by a model. So the Tool is built directly with
    `parameters=` set to the registry's schema.

    The synthesised signature exists only to satisfy FastMCP's argument validation.
    Measured: a bare `async def _run(**kwargs)` makes pydantic demand a literal
    `kwargs` field and EVERY call fails "Field required [type=missing]".
    """
    name = spec["name"]
    handler = spec["handler"]
    schema = spec.get("input_schema") or {}

    async def _run(**kwargs):
        return await handler(kwargs)

    props = schema.get("properties") or {}
    req_names = set(schema.get("required") or [])
    params = [
        inspect.Parameter(
            p,
            inspect.Parameter.KEYWORD_ONLY,
            default=(inspect.Parameter.empty if p in req_names else None),
        )
        for p in props
        if p.isidentifier()
    ]
    _run.__name__ = name
    _run.__signature__ = inspect.Signature(params)

    return Tool(
        fn=_run,
        name=name,
        title=None,
        description=spec.get("description") or "",
        parameters=schema,
        fn_metadata=func_metadata(_run),
        is_async=True,
        context_kwarg=None,
        annotations=None,
    )


mcp = FastMCP("archie-platform", host="0.0.0.0", port=7800)

# READ tools that MUST be answered by the hub, not run here.
#
# Most read tools are pure DB queries and belong in-process on the read-only role.
# A few observe something this container structurally cannot see — and for those,
# "answer from here" is not degraded, it is FALSE. archie_mcp_gateway has no
# docker socket by design (see the module docstring), so any tool that inspects
# container state run here reports every subject as absent.
#
# That is not hypothetical: check_infra_heartbeat did exactly that, reporting 9 of
# 10 critical containers DOWN at severity=error on a hub where all 42 containers
# were running. Worse than useless — most of those carry auto_restart_safe, so an
# operator reading the output could approve restarting healthy services.
#
# infra_heartbeat_service.py now raises DockerObserverUnavailable instead of
# conflating "cannot see" with "not there", which stops the lie. This table stops
# the blindness by giving the answer to a process that can actually see.
_HUB_PROXIED_READS = {"check_infra_heartbeat"}

_read, _skipped, _withheld, _proxied = 0, [], 0, 0
for _spec in get_all_tools():
    if _spec.get("name") in _HUB_PROXIED_READS:
        # Served below via the hub's scoped API, not in-process.
        _proxied += 1
        continue
    if _spec.get("requires_permission", "read") != "read":
        # Deliberately NOT served in-process: its handler writes to Postgres, and this
        # container's role cannot. Serving it would list a tool that always fails.
        # Write capability is offered below, through the hub's scoped API instead.
        _withheld += 1
        continue
    try:
        mcp._tool_manager._tools[_spec["name"]] = _build_read_tool(_spec)
        _read += 1
    except Exception as exc:  # one malformed schema must not cost every other tool
        _skipped.append((_spec.get("name"), str(exc)[:120]))

logger.info(
    "gateway: %d read tools in-process, %d write tools withheld (served via hub API), "
    "%d read tools proxied to hub, %d skipped",
    _read, _withheld, _proxied, len(_skipped),
)
for _n, _e in _skipped:
    logger.warning("gateway: tool %s NOT served: %s", _n, _e)

# A gateway serving nothing looks identical to a healthy one until a lane tries to use
# it. Refuse to start instead — same reasoning as the absent-profile trap in
# residency_activation (KB #300145).
if _read == 0:
    raise RuntimeError("gateway: no read tools registered — refusing to serve an empty gateway")


# ---------------------------------------------------------------------------
# PROXIED READ tools — hub-side, because this container cannot observe the subject
# ---------------------------------------------------------------------------


@mcp.tool()
async def check_infra_heartbeat() -> dict:
    """Run V.I.G.I.L. infrastructure heartbeat audit on demand.

    Checks every critical container in the registry (network_adguard,
    archie_comms, archie_comfyui, kbs_app, kytran-system-operations,
    kytran_creed, media_plex, media_jellyfin, media_samba, archie_tailscale)
    for presence, running state, healthcheck status, and TCP/HTTP reachability.

    Returns severity ('info' | 'warning' | 'error'), per-container detail with
    reasons, and summary_metrics (down, warnings, healthy counts). Read-only; it
    never restarts anything.

    IMPORTANT — read `observer_blind` before reading anything else. When it is
    true this process could not reach the docker daemon and inspected NOTHING:
    `down_names` is empty because nothing was checked, NOT because the fleet is
    healthy. Treat a blind result as "the monitor is broken", never as an
    all-clear and never as missing containers.

    The check runs on the hub, which holds the docker socket; this gateway has
    none, so it is proxied rather than answered locally.
    """
    err = _needs_read()
    if err:
        return err
    return await _hub("GET", "/api/internal/infra/heartbeat")


# ---------------------------------------------------------------------------
# WRITE tools — through the hub's scoped internal API
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_task(project_id: int, title: str, description: str = "", priority: int = 5) -> dict:
    """Create a Dev HQ task. `priority` is an INTEGER 1-10, not a word. Search the
    existing tasks first — duplicate tasks for one piece of work are a recurring
    problem on this platform."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/tasks", {
        "project_id": project_id, "title": title,
        "description": description, "priority": priority,
    })


@mcp.tool()
async def set_task_status(task_id: int, status: str) -> dict:
    """Update a Dev HQ task's status — this is how work gets CLOSED."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/tasks/%d/status" % int(task_id), {"status": status})


@mcp.tool()
async def set_task_priority(task_id: int, priority: int) -> dict:
    """Set a Dev HQ task's priority (INTEGER 1-10)."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/tasks/%d/priority" % int(task_id), {"priority": priority})


@mcp.tool()
async def add_task_note(task_id: int, note: str) -> dict:
    """Append a work note to a task — what you did, what you found, what is left.
    A closed task with no note is not a record anyone can use later."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/tasks/%d/note" % int(task_id), {"text": note})


@mcp.tool()
async def delegate_task_to_fleet(capability: str, reason: str, priority: int = 5) -> dict:
    """Delegate work to the A.R.C.H.I.E. agent fleet (DHQ dispatch). `reason` IS the
    agent's prompt — write it as the instruction you want carried out, not as a title."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/delegation/submit", {
        "capability": capability, "reason": reason,
        "priority": priority, "delegation_source": "coder_lane",
    })


@mcp.tool()
async def store_memory(
    content: str,
    title: str = "",
    knowledge_type: str = "conversation_memory",
    category: str = "general",
    tags: list[str] | None = None,
    importance: float = 0.6,
) -> dict:
    """Store information in A.R.C.H.I.E.'s long-term memory (knowledge base). Use for
    facts, learnings, procedures or preferences that should persist across sessions.

    `knowledge_type`: conversation_memory | vault_note | mistake_learned | code_snippet |
    improvement. vault_note = 1.2x and mistake_learned = 1.3x search weight, so a note
    worth finding later should say so. This is the write the close-out procedure's Step 3a
    requires; it needs a write-scoped bearer."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/knowledge/store", {
        "content": content, "title": title, "knowledge_type": knowledge_type,
        "category": category, "tags": tags or [], "importance": importance,
    })


@mcp.tool()
async def assign_agent_to_department(agent_id: int, department: str) -> dict:
    """Assign a team member (agent) to a department."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/agents/%d/assign" % int(agent_id), {"department": department})


@mcp.tool()
async def set_agent_shift_state(agent_id: int, shift_state: str) -> dict:
    """Set a team member's shift state (active, barracked, off_duty, ...)."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/agents/%d/shift-state" % int(agent_id),
                             {"shift_state": shift_state})


@mcp.tool()
async def add_agent_skill(agent_id: int, skill_name: str, proficiency_level: int = 3) -> dict:
    """Grant a team member a skill. `skill_name` must match the capability string used
    at dispatch, or the agent will never be selected for that work."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/agents/%d/skills/add" % int(agent_id),
                             {"skill_name": skill_name, "proficiency_level": proficiency_level})


@mcp.tool()
async def remove_agent_skill(agent_id: int, skill_name: str) -> dict:
    """Remove a skill from a team member."""
    err = _needs_write()
    return err or await _hub("POST", "/api/internal/agents/%d/skills/remove" % int(agent_id),
                             {"skill_name": skill_name})


class BearerAuth(BaseHTTPMiddleware):
    """Require a valid bearer on every request except /health, and publish its
    permissions for the per-tool write checks above."""

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        info = _auth.validate_api_key(token) if token else None
        perms = tuple(info.get("permissions") or []) if info else ()
        if not info or "read" not in perms:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        # Set INSIDE dispatch so it is scoped to this request's context.
        _PERMS.set(perms)
        return await call_next(request)


def _health(_request):
    return PlainTextResponse("ok")


# Streamable-HTTP ASGI app (MCP endpoint mounted at /mcp by FastMCP).
app = mcp.streamable_http_app()
app.add_middleware(BearerAuth)
app.router.routes.append(Route("/health", _health))
