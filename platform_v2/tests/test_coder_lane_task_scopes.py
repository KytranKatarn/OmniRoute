"""Dev HQ access for the coder lanes: scope grants + gateway write gating (#6749 follow-on).

Two lanes, two very different trust levels, and the tests exist to keep them apart:

  archie_engine (archie-tui) — already a trusted internal caller. Gains tasks:read and
  tasks:write so the TUI can SEE and CLOSE its own work. Until now it could only create
  task rows as a side effect of delegating: write-only and blind. The 5 tui-sourced tasks
  it opened sat unclosed from 2026-08-23 because nothing on that side could reach them.

  opencode — a THIRD-PARTY coding agent in an isolated container that cannot resolve
  archie_platform at all. It reaches Dev HQ only through archie_mcp_gateway, which holds
  the key on its behalf. Its scope set is therefore deliberately the narrowest of any
  caller: tasks only. No delegation (it must not be able to spend fleet compute), no
  dhq:chat, no approvals, no engine, no repair, no sessions, no mail.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.internal_auth as ia  # noqa: E402


def _find_gateway():
    """Locate mcp-gateway/gateway.py, or None if the repo root is not mounted.

    The platform container mounts only platform_v2 at /app, so the repo-root
    mcp-gateway/ is simply absent there. Walk up; fall back to the known checkout.
    Returns None rather than raising so the SCOPE tests (which need no repo root)
    still run — the gateway tests then SKIP with a reason, which is visible in the
    report. A skip is not a pass; a silently-absent assertion would be.
    """
    here = os.path.abspath(os.path.dirname(__file__))
    while True:
        cand = os.path.join(here, "mcp-gateway", "gateway.py")
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    fallback = "/mnt/archie_brain/mcp-gateway/gateway.py"
    return fallback if os.path.exists(fallback) else None


_GATEWAY = _find_gateway()


class TestEngineGainedTaskAccess:
    def test_engine_can_read_and_write_tasks(self):
        scopes = ia.CALLER_SCOPES["archie_engine"]
        assert "tasks:read" in scopes
        assert "tasks:write" in scopes

    def test_engine_still_cannot_approve_or_touch_sessions_or_mail(self):
        """The grant must widen tasks ONLY — these were already forbidden and stay so."""
        scopes = ia.CALLER_SCOPES["archie_engine"]
        for forbidden in ("approvals:decide", "sessions", "mail", "coo"):
            assert forbidden not in scopes, forbidden


class TestOpencodeIsTheNarrowestCaller:
    def test_opencode_is_registered_with_its_own_key(self):
        assert ia.CALLER_ENV["opencode"] == "INTERNAL_API_KEY_OPENCODE"

    def test_opencode_has_tasks_and_nothing_else(self):
        """Exact-set assertion on purpose: a future grant here must be deliberate."""
        assert ia.CALLER_SCOPES["opencode"] == {"tasks:read", "tasks:write"}

    def test_opencode_cannot_spend_fleet_compute(self):
        """`delegation` would let a third-party agent queue work onto the GPU fleet."""
        assert "delegation" not in ia.CALLER_SCOPES["opencode"]

    def test_opencode_is_not_wider_than_the_engine(self):
        """A third-party lane must never outrank a first-party one."""
        assert ia.CALLER_SCOPES["opencode"] <= ia.CALLER_SCOPES["archie_engine"]

    def test_every_opencode_scope_is_a_real_scope(self):
        """A typo'd scope silently grants nothing and 403s at runtime instead."""
        assert ia.CALLER_SCOPES["opencode"] <= ia.SCOPES


class TestGatewayWriteGating:
    """The gateway's bearer middleware only checks `read`. Without a per-tool check a
    READ-scoped token could create and close tasks — so each write tool must gate."""

    def _src(self):
        if not _GATEWAY:
            pytest.skip("mcp-gateway/gateway.py not reachable (repo root not mounted)")
        with open(_GATEWAY) as fh:
            return fh.read()

    def test_every_mutating_tool_calls_the_write_guard(self):
        src = self._src()
        for tool in ("create_task", "set_task_status", "add_task_note"):
            body = re.search(r"async def %s\(.*?(?=\n@mcp\.tool|\nclass )" % tool, src, re.S)
            assert body, "tool %s not found in gateway" % tool
            assert "_needs_write()" in body.group(0), (
                "%s does not check _needs_write() — a read-scoped bearer could call it" % tool
            )

    def test_read_tools_do_not_require_write(self):
        """Reads must stay available to the existing read-only bearer."""
        src = self._src()
        for tool in ("get_projects", "get_my_tasks", "get_task"):
            body = re.search(r"async def %s\(.*?(?=\n@mcp\.tool|\nclass )" % tool, src, re.S)
            assert body, tool
            assert "_needs_write()" not in body.group(0), tool

    def test_task_tools_go_over_http_not_the_database(self):
        """The gateway's Postgres role is read-only `codex_ro`; task writes MUST route
        through the hub's scoped, audited internal API instead."""
        src = self._src()
        assert "/api/internal/tasks" in src
        assert "INTERNAL_API_KEY_OPENCODE" in src
        assert "codex_ro" in src, "the read-only DB role note must survive"
