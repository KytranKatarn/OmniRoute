"""Claude MCP request context tracking.

Marks the current asyncio context as a Claude MCP-initiated request so
any downstream `department_dispatcher.dispatch()` call writes
`request_origin='claude'` and `mcp_tool=<name>` to
`task_execution_log` — powering the DHQ Dispatch tab "Claude Requests"
feed (Task #1297) and the auto-routing through the orchestration
engine (Task #1298 / ADR-013).

ContextVar isolates each MCP call from its siblings under asyncio
concurrency. The dispatcher reads these via ``get_request_origin()`` /
``get_mcp_tool()`` lazily — if the import fails (e.g. dispatcher
imported standalone), it falls back to ``None`` and the existing
behavior is preserved.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_request_origin: ContextVar[Optional[str]] = ContextVar("claude_mcp_request_origin", default=None)
_mcp_tool: ContextVar[Optional[str]] = ContextVar("claude_mcp_tool", default=None)


def get_request_origin() -> Optional[str]:
    """Return current request origin tag, or None if outside a tracked call."""
    return _request_origin.get()


def get_mcp_tool() -> Optional[str]:
    """Return current MCP tool name, or None if outside a tracked call."""
    return _mcp_tool.get()


@contextmanager
def claude_request(mcp_tool: str, origin: str = "claude"):
    """Mark the wrapped block as a Claude MCP request.

    Any ``department_dispatcher.dispatch()`` invoked inside this block
    will tag its ``task_execution_log`` row with the given origin and
    tool name. Nested calls reset cleanly via ContextVar tokens.
    """
    o_token = _request_origin.set(origin)
    t_token = _mcp_tool.set(mcp_tool)
    try:
        yield
    finally:
        _request_origin.reset(o_token)
        _mcp_tool.reset(t_token)
