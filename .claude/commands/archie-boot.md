# ARCHIE Session Boot Protocol

You are starting a new work session on the A.R.C.H.I.E. platform. Execute these steps IN ORDER before doing any work.

## Step 1: Load Knowledge Context

Call `mcp__archie__session_briefing` with the topic extracted from the user's first message (or "platform status" if no specific topic).

If `session_briefing` is unavailable, call these individually:
1. `mcp__archie__recall_context` with topic from user's request
2. `mcp__archie__search_knowledge` with query from user's request, types: ["mistake_learned"], limit: 5
3. `mcp__archie__get_knowledge_stats`
4. `mcp__archie__get_projects_brief`

## Step 2: Load Agent & Dispatcher Context

Call `mcp__archie__get_quick_summary` to get platform health, agent status, and dispatcher readiness.

If working on a specific module, also call:
- `mcp__archie__list_agents` to see available agents and their stations
- `mcp__archie__get_node_status` if the task involves fleet/node operations

## Step 3: Check Active Work

Call `mcp__archie__get_my_tasks` to see any in-progress or pending tasks from previous sessions.

## Step 4: Review Feedback Memories

Read the MEMORY.md file and scan the "Behavioral Rules" section. These are hard-won lessons — violating them wastes time and money.

Key rules to internalize:
- **Search knowledge base BEFORE building** — answers are already there
- **Stop after 2 failed attempts** — ask the user, don't spiral
- **Verify before claiming done** — prove it works with evidence
- **Never commit secrets** — scan before any force-push
- **Plan mode for non-trivial tasks** — 3+ steps = plan first

## Step 5: Present Boot Summary

Print a concise summary:
```
## Session Briefing
- **KB Health**: [total entries] entries, [embedding %] embedded
- **Active Projects**: [list active project names]
- **Relevant Context**: [any knowledge found for the task]
- **Mistakes to Avoid**: [any mistake_learned entries found]
- **Agent Status**: [active count] / [total] agents online
- **Ready**: Yes/No + any blockers
```

Then proceed with the user's request.
