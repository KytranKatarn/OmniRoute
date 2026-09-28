---
description: Platform health overview — load the archie-status skill and run its checks, then summarize. Use when the user says "status", "is the platform up", "health", "is it running".
---

Load the `archie-status` skill from `.claude/skills/archie-status/` and follow it. This lane is **host-direct**: the Docker socket IS mounted and the live tree is served here, so run the skill's container checks directly.

**Truth order — read state in this order, newest knowledge first:**
1. **`docker ps` (authoritative).** `docker ps --format 'table {{.Names}}\t{{.Status}}'` shows the real container state — this lane's socket is the one true view alongside the platform container itself.
2. **Gateway probe (only compose host this lane can reach by name; also the MCP blind spot).** One line, no deps:
   ```
   (exec 3<>/dev/tcp/archie_mcp_gateway/7800) 2>/dev/null && echo "gateway: UP" || echo "gateway: UNREACHABLE"
   ```
   The lane container cannot resolve `archie_platform`/`archie_database` (different compose networks) — do not read a DOWN from name-based probes of them; use `docker ps`. If the gateway itself is DOWN, MCP tools error/no-op — say that's why, don't report the platform as down.
3. **KSO** (Kytran System Operations) for host hardware / docker stack monitoring (module `platform_v2/tools/system_operations`, wizard route `system-operations`; KSO also surfaces host facts per `admin-system-operations` skill).
4. **arbitrary_kb MCP *only* as a pointer**, and with the caveat below.

**KNOWN FALSE-NEGATIVES in the MCP checks (gateway-based; do not trust, do not alarm, until the gateway image is rebuilt):**
- `get_service_status` / `get_quick_summary` probe `localhost` from inside `archie_mcp_gateway` → everything reads "stopped"/"OFFLINE" even when healthy. Fix (docker-DNS hostnames) is committed/PR'd; effective after `archie_mcp_gateway` rebuild.
- `check_infra_heartbeat` can't see any container from the gateway (no docker.sock there) → reports "all absent". The real V.I.G.I.L. signal is the `vigil_infra_heartbeat` agent-loop job in `archie_platform` (has the socket). Cross-check with `docker ps` before trusting a DOWN alert from the MCP tool.

Always report the `docker ps` ground truth explicitly; say which checks are MCP-only guesses. Do not run time-consuming probes.