"""Platform access for the coder lanes: scope grants + gateway write gating (#6749 follow-on).

  archie_engine (archie-tui) — a trusted internal caller. Gains tasks:read/write so the
  TUI can SEE and CLOSE its own work. Until now it could only create task rows as a side
  effect of delegating: write-only and blind. Its 5 tui-sourced tasks sat unclosed from
  2026-08-23 because nothing on that side could reach them.

  coder_lanes (codex + opencode, via archie_mcp_gateway) — owner decision 2026-09-13:
  both lanes get platform manage/update access. They hold no internal key and still
  cannot resolve archie_platform; the gateway carries the key on their behalf, so their
  reach is exactly its tool list.

⚠️ THESE LANES ARE NO LONGER "SANDBOXED" IN THE SENSE THAT MATTERS. The container
isolation is unchanged — no platform DNS, no DB — but through the gateway they can now
create and close Dev HQ tasks, manage team members (assign, shift-state, skills) and
SPEND FLEET COMPUTE via delegation. An earlier version of this docstring said "tasks
only, no delegation, it must not be able to spend fleet compute"; that is now false and
contradicted by the exact-set test below. Anything describing these lanes as a sandbox —
UI markers, module docs, the cockpit terminal pane's `sandboxed` label — is describing
the old posture and should say "isolated container, platform WRITE access" instead.

What stays out of reach, and why it is the line: approvals:decide (an agent that can
both raise and approve is its own reviewer), plus coo, mail, sessions, engine,
repair:write, cloud:code, fleet, compliance, notify.
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


class TestCoderLaneScopes:
    def test_coder_lanes_caller_is_registered(self):
        assert ia.CALLER_ENV["coder_lanes"] == "INTERNAL_API_KEY_CODER_LANES"

    def test_coder_lanes_scope_set_is_exact(self):
        """Exact-set assertion on purpose: a future grant here must be deliberate."""
        assert ia.CALLER_SCOPES["coder_lanes"] == {
            "tasks:read",
            "tasks:write",
            "agents:read",
            "agents:manage",
            "delegation",
            "infra:read",
            "knowledge:write",
        }

    def test_coder_lanes_cannot_approve_their_own_work(self):
        """Delegation IS granted (owner decision) so the lanes can use platform skills.
        Self-approval is the line that stays: an agent that can both raise and approve
        is its own reviewer."""
        for forbidden in ("approvals:decide", "mail", "sessions", "coo", "repair:write"):
            assert forbidden not in ia.CALLER_SCOPES["coder_lanes"], forbidden

    def test_coder_lanes_never_gain_the_scopes_reserved_to_other_actors(self):
        """The lanes are NOT a subset of the engine any more — they manage agents and
        it does not — so the meaningful invariant is which scopes stay out of reach."""
        reserved = {
            "approvals:decide",
            "coo",
            "mail",
            "sessions",
            "engine",
            "repair:write",
            "cloud:code",
            "fleet",
            "compliance",
            "notify",
        }
        assert not (ia.CALLER_SCOPES["coder_lanes"] & reserved)

    def test_every_coder_lane_scope_is_real(self):
        """A typo'd scope silently grants nothing and 403s at runtime instead."""
        assert ia.CALLER_SCOPES["coder_lanes"] <= ia.SCOPES


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
        for tool in ("create_task", "set_task_status", "add_task_note", "store_memory"):
            body = re.search(r"async def %s\(.*?(?=\n@mcp\.tool|\nclass )" % tool, src, re.S)
            assert body, "tool %s not found in gateway" % tool
            assert "_needs_write()" in body.group(0), (
                "%s does not check _needs_write() — a read-scoped bearer could call it" % tool
            )

    def test_reads_are_registry_driven_not_hand_listed(self):
        """Reads come from mcp_server.tools.get_all_tools(), so a tool added to the
        platform appears here automatically WITH its real schema. The earlier design
        hand-wrote three read tools; a hand-written copy of a schema drifts, and a
        stale schema is worse than none."""
        src = self._src()
        assert "get_all_tools()" in src
        assert "_build_read_tool" in src

    def test_read_wrapper_does_not_gate_on_write(self):
        """Reads must stay reachable by a read-only bearer — the write gate belongs
        only on the hub-backed write tools."""
        src = self._src()
        body = re.search(r"def _build_read_tool\(.*?(?=\nmcp = FastMCP)", src, re.S)
        assert body, "_build_read_tool not found"
        assert "_needs_write()" not in body.group(0)

    def test_task_tools_go_over_http_not_the_database(self):
        """The gateway's Postgres role is read-only `codex_ro`; task writes MUST route
        through the hub's scoped, audited internal API instead."""
        src = self._src()
        assert "/api/internal/tasks" in src
        assert "INTERNAL_API_KEY_CODER_LANES" in src

    def test_memory_write_goes_over_the_knowledge_hub_route(self):
        """store_memory (the close-out Step 3a write) is the fourth hub-backed write:
        it must post to /api/internal/knowledge/store and gate on the write bearer,
        never touch Postgres directly from this read-only-role container."""
        src = self._src()
        assert "/api/internal/knowledge/store" in src
        body = re.search(r"async def store_memory\(.*?(?=\n@mcp\.tool|\nclass )", src, re.S)
        assert body, "store_memory not found in gateway"
        assert "_needs_write()" in body.group(0)
        assert "codex_ro" in src, "the read-only DB role note must survive"


class TestGatewayKeepsTheReadOnlyDatabaseRole:
    """Option 2's whole point: writes go through the hub's scoped API, so this
    container keeps a Postgres role that CANNOT write.

    If someone later flips the gateway to a write-capable role, the bearer check
    becomes the only control left — exactly the posture that was rejected. This test
    is the tripwire for that, and it reads compose rather than trusting a comment.
    """

    def _compose(self):
        here = os.path.abspath(os.path.dirname(__file__))
        while True:
            cand = os.path.join(here, "docker-compose.yml")
            if os.path.exists(cand):
                return open(cand).read()
            parent = os.path.dirname(here)
            if parent == here:
                break
            here = parent
        fallback = "/mnt/archie_brain/docker-compose.yml"
        if os.path.exists(fallback):
            return open(fallback).read()
        pytest.skip("docker-compose.yml not reachable (repo root not mounted)")

    def test_gateway_service_still_uses_the_read_only_role(self):
        compose = self._compose()
        block = re.search(r"\n  archie_mcp_gateway:.*?(?=\n  [a-z_]+:\n)", compose, re.S)
        assert block, "archie_mcp_gateway service not found in compose"
        body = block.group(0)
        assert "DB_USER: codex_ro" in body, (
            "the gateway's Postgres role is no longer codex_ro — writes must go through "
            "the hub's scoped API, not a write-capable DB role"
        )
