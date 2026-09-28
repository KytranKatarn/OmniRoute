---
description: Boot a new opencode session on the A.R.C.H.I.E. platform — KB briefing, host-direct lane framing, platform + work state, and a boot summary. Use at the start of a session or when resuming after /archie-end.
---

You are opencode starting a session on the A.R.C.H.I.E. platform. This command is a port of Claude's `/archie-boot`. Execute in order.

## Step 0: Know what lane you are (READ THIS — do not repeat the stale doc)
Per `archie-comms/services/terminal_lanes.py` (the authoritative source): since 2026-09-13 **all four lanes have `contained=False`** — this lane mounts `/var/run/docker.sock` and the **live tree `/mnt/archie_brain`**, so the container is NOT a boundary. The docstring is explicit: *"no lane is a SANDBOX, and nothing here may call one that."*

So treat this lane as **host-direct, like Claude**:
- Work in the LIVE tree at `/mnt/archie_brain` (an edit is served on the next request). `CLAUDE.md`, `.claude/rules`, and `scripts/` resolve exactly as claude saw them.
- You can run `docker` (start/restart/inspect; `docker ps` works) and verify through the running process, not just the file.
- The one line that still holds: **you cannot approve or merge your own work.** `gh pr merge`/approve is refused by the guard, and the review gate is F.O.R.G.E. + a human. Never bypass it.
- `AGENTS.md` in this repo still says opencode "holds no git credential / does not ship" — that text predates option B and is STALE. Do not let it talk you out of host-direct behavior.

## Step 1: Context from the repo
- Read `CLAUDE.md` head (repo root) — the 6 Rules. Re-state lane identity vs the old sandbox framing honestly.
- Check the live tree state: `git -C /mnt/archie_brain status --porcelain | head`, current branch, and `rev-parse --short HEAD`. The tree carries the owner's in-progress work — never blind-stage it.

## Step 2: KB briefing
- Call `session_briefing` (archie_kb MCP) with the topic from the user's first message, or "platform status" if none.
- If EMPTY: report "Warning: Knowledge search returned no context — the consciousness pipeline may need attention." Then fall back to `recall_context` + `search_knowledge` (types=["mistake_learned"]) + `get_knowledge_stats` + `get_projects_brief`.
- Internalize returned mistakes; name any that relate to today's task before working.

## Step 3: Identity & continuity — read the lane handover
**Start by reading `/opencode-home/data/archie-handover.md`** — the lane's durable handover (persistent volume; updated at the end of every session). It carries: lane identity, ship-via-F.O.R.G.E. flow, live-tree git state with this session's vs the owner's changes, blockers, and next actions. Internalize it and restate the section headings relevant to today in your reply.

- Supplement with `get_recent_activity`, `recall_context`, and `search_knowledge`, but **do not fabricate** if they are empty (the lane's MCP identity is denied on `unified_projects`/`work_sessions`, and `/archie-boot` itself cannot read them either — rely on the handover file).
- After the session, refresh the handover file (same path) — that is how the next boot resumes.
- NOTE: if this is a freshly restarted opencode, the previous session's context is gone; the handover file is the continuity bridge, not the live chat.

## Step 4: Platform & work state
- **Container/platform truth comes from `docker ps` in this lane**, NOT from the MCP status tools. Known false-negatives until the gateway image is rebuilt: `get_service_status` probes `localhost` from the gateway (everything reads "stopped"), `get_quick_summary` reads "Platform: OFFLINE" for the same reason, and `check_infra_heartbeat` sees NO containers (the gateway has no docker.sock). Cross-check any MCP down-reading against `docker ps` before treating it as an incident.
- **Gateway reachability — one line, no deps** (the gateway is the only compose host this lane can resolve; it is also where the MCP truth comes from):
  ```
  (exec 3<>/dev/tcp/archie_mcp_gateway/7800) 2>/dev/null && echo "gateway: UP" || echo "gateway: UNREACHABLE"
  ```
  If UNREACHABLE, the MCP tools error/no-op — that is a gateway problem, not a platform problem; say so. Do NOT probe `archie_platform` by name from this lane (it will not resolve — different networks); use `docker ps`.
- `get_quick_summary` — DB entry count is reliable (gateway reaches the DB); only the platform line lies.
- `get_my_tasks` is DENIED for this lane (no `unified_tasks` permission) — skip it; continuity comes from the handover file (§5).
- On demand only: `list_agents`, `get_node_status`, or a scoped `search_knowledge` mistake query.
- Host/hardware questions → KSO (`platform_v2/tools/system_operations`, `admin-system-operations` skill), not the MCP status tools.

## Step 5: Boot summary
```
## Session Briefing
- **Lane**: opencode — HOST-DIRECT (docker.sock + live tree /mnt/archie_brain mounted; contained=False)
- **Ship rule**: ship through F.O.R.G.E./Repair Bay — commit in the live tree, then Repair Bay pushes + opens the PR with the platform token; MAY NOT push with own git, approve, or merge own work
- **KB Health**: [entries], [embedding %] embedded
- **Active Projects**: [names]
- **Current Work**: [from Step 3]
- **Relevant Context**: [knowledge found]
- **Mistakes to Avoid**: [listed]
- **Agent Status**: [active]/[total] online
- **Anomalies**: [or "none"]
- **Live tree**: branch <b>, HEAD <sha>, <n> dirty (owner's in-progress work — do not blind-stage)
- **Ready**: Yes/No + blockers
```
If knowledge was empty, add the WARNING line. Then proceed with the user's request.