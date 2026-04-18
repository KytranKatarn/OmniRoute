---
name: archie-status
description: Review current A.R.C.H.I.E. platform health — containers, database, agents, nightly jobs, GPU/CPU load, recent activity. Invoke when the user asks about "status", "health check", "is it running", or after shipping a PR to verify the hub is still healthy.
---

# A.R.C.H.I.E. Platform Status

Runs a focused health check across the hub. Output is a single concise report — no deep-dives unless the user asks.

## What to check (run in parallel where possible)

### 1. Quick summary (MCP)
- `mcp__archie__get_quick_summary` — ~50-token snapshot: platform OK? DB OK? KB entries? git branch?

### 2. Platform health (MCP)
- `mcp__archie__check_platform_health` — returns per-subsystem status (DB, Bridge, Consciousness, etc.) if available
- Otherwise fall back to `mcp__archie__get_system_status`

### 3. Agent roster + welfare (MCP)
- `mcp__archie__list_agents` with `limit: 5` — verify active agents are healthy
- Highlight any agent in `shift_state = winding_down` or `cooldown`

### 4. Budget counter drift check (post-2026-04-18 pattern — see KB vault_note #256952)
- Query `agent_budgets` for counters > 0 that don't match `bridge_jobs` in-flight count
- If drift exists, note it — the hourly `budget_reconciliation` job will fix it but flag if it's persistent

### 5. Nightly cron jobs — last run status
- Query `autonomy_loop_log` for the last 24h:
  - `translation_coverage_scan` — expect success, gaps_found > 0
  - `budget_reconciliation` — expect success, items_processed = drift count
  - `department_metrics_rollup` — once per day at 02:00
  - `backup_*` jobs

### 6. GPU + RAM
- `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader`
- `free -g | head -2`
- `curl -s http://192.168.1.200:11434/api/ps` — loaded models + VRAM/RAM split

### 7. Docker containers
- `docker ps --format 'table {{.Names}}\t{{.Status}}'` — flag anything not Up
- Key containers: `archie_platform`, `archie_database`, `archie_comms`, `archie_comfyui`, `kbs_app`, `kytran_creed`, `stalwart_mail`

### 8. Recent git activity
- `git log --oneline -5` — what shipped recently
- `git status --short` — any uncommitted drift

### 9. Known-open priority tasks (MCP)
- `mcp__archie__get_my_tasks` with `limit: 5` — P9/P10 pending items

## Output format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 A.R.C.H.I.E. PLATFORM STATUS — [time]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 HUB
 ├─ Platform:     [OK/degraded] @ 192.168.1.200:3000
 ├─ Database:     [OK] — [N] KB entries, [%] embedded
 ├─ Branch:       [branch] ([N] uncommitted)
 └─ Last commit:  [sha] [message]

 AGENTS
 ├─ Active:       [N]/[total]
 ├─ Barracked:    [N]
 ├─ Translate:    CODEX ([state], [model]) + R.O.S.E.T.T.A. ([state], [model])
 └─ Welfare:      [any stressed/cooldown agents]

 BUDGET
 ├─ Counters OK:  [N] agents at 0, [N] in normal range
 ├─ Drift:        [N] agents with counter > actual in-flight
 └─ Blocked:      [any agent currently ≥ queue_limit]

 NIGHTLY JOBS (24h)
 ├─ translation_coverage_scan:  [status] @ [time] — [gaps_found] gaps, [auto_fixed] resolved
 ├─ budget_reconciliation:      [status] @ [time] — [N] corrected
 ├─ department_metrics_rollup:  [status] @ [time]
 └─ [any failing jobs]

 RESOURCES
 ├─ GPU:   [used]/[total] MiB ([model names on VRAM])
 ├─ RAM:   [used]/[total] GB
 └─ Ollama: [N] models loaded

 CONTAINERS
 └─ [N]/[total] healthy — flag any Exited/Restarting

 RECENT WORK
 └─ [last 3-5 commits]

 OPEN P9+ TASKS
 └─ [first 3-5 priority items from get_my_tasks]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## When to flag concerns

- 🔴 Any container Exited/Restarting → surface immediately
- 🔴 Last nightly `translation_coverage_scan` failed → note
- 🟡 Budget counter drift > 3 on any active agent → mention (reconciler handles)
- 🟡 Any P10 project stale > 7 days → surface
- 🟢 All else — clean report

## Rules

- Parallel tool calls: fire #1, #2, #3, #5, #7, #8 in one batch. #4, #6, #9 can follow.
- Use `mcp__plugin_context-mode_context-mode__ctx_execute(language: "shell", code: "...")` for multi-line shell — not raw Bash — per context-mode policy.
- Keep the report under 80 lines. If user wants a deeper drill, they'll ask.
- Match the session's style (icons if user uses them, otherwise plain text).
