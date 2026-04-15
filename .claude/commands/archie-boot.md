# ARCHIE Session Boot Protocol

You are starting a new work session on the A.R.C.H.I.E. platform. Execute these steps IN ORDER before doing any work.

## Step 1: Load Knowledge Context

Call `mcp__archie__session_briefing` with the topic extracted from the user's first message (or "platform status" if no specific topic).

**CRITICAL CHECK**: If `knowledge_context` or `mistakes_to_avoid` are EMPTY, this is a red flag. Report it to the user:
> "Warning: Knowledge search returned no context. The consciousness pipeline may need attention."

If `session_briefing` is unavailable, call these individually:
1. `mcp__archie__recall_context` with topic from user's request
2. `mcp__archie__search_knowledge` with query from user's request, types: ["mistake_learned"], limit: 5
3. `mcp__archie__get_knowledge_stats`
4. `mcp__archie__get_projects_brief`

## Step 2: Load Recent Corrections (ALWAYS — regardless of topic)

Call `mcp__archie__search_knowledge` with query: "correction mistake failure lesson learned", types: ["mistake_learned"], limit: 10

These are the patterns you MUST NOT repeat. Read each one. Internalize them.
If any relate to today's task, mention them explicitly before starting work.

## Step 3: Load Agent & Dispatcher Context

Call `mcp__archie__get_quick_summary` to get platform health, agent status, and dispatcher readiness.

If working on a specific module, also call:
- `mcp__archie__list_agents` to see available agents and their departments
- `mcp__archie__get_node_status` if the task involves fleet/node operations

## Step 4: Check Active Work

Call `mcp__archie__get_my_tasks` to see any in-progress or pending tasks from previous sessions.

## Step 5: Review Feedback Memories

Read the MEMORY.md file and scan the "Behavioral Rules" section. These are hard-won lessons — violating them wastes time and money.

Key rules to internalize:
- **Search knowledge base BEFORE building** — answers are already there
- **Stop after 2 failed attempts** — ask the user, don't spiral
- **Verify before claiming done** — prove it works with evidence
- **Never commit secrets** — scan before any force-push
- **Plan mode for non-trivial tasks** — 3+ steps = plan first
- **Use platform tools** — Hostinger API for DNS, MCP for tracking, never ad-hoc
- **All URLs use subdomains** — NEVER raw IPs in OAuth, CORS, or redirect URIs
- **Check .env has ALL required vars** — DB passwords, secrets, client IDs before deploying
- **Verify containers actually start** — check docker logs, not just docker compose up

## Step 6: Product Registry Quick Reference

These standalone products exist:

| Product | Port | Subdomain | Client ID |
|---------|------|-----------|-----------|
| ARCHIE Platform | 3000 | platform.kytranempowerment.com | — |
| A.R.C.H.I.E. Comms | 3002 | archie.kytranempowerment.com | — |
| Market Watch | 8101 | market.kytranempowerment.com | market-watch-viewer |
| Civic Watch | 8099 | civic.kytranempowerment.com | civic-watch |
| Legal Watch | 8100 | legal.kytranempowerment.com | legal-watch |
| Gov Watch | 8102 | gov.kytranempowerment.com | gov-watch |
| Business Suite | 8091 | business.kytranempowerment.com | kbs |
| System Operations | 8085 | server.kytranempowerment.com | kso |
| C.R.E.E.D. Governance | 8086 | creed.kytranempowerment.com | — |
| The News | 8103 | thenews.kytranempowerment.com | — |

Ollama runs on the HOST at 192.168.1.200:11434 — NOT in a container. KEEP_ALIVE=5m.

## Step 7: Present Boot Summary

Print a concise summary:
```
## Session Briefing
- **KB Health**: [total entries] entries, [embedding %] embedded
- **Active Projects**: [list active project names]
- **Relevant Context**: [any knowledge found for the task]
- **Mistakes to Avoid**: [any mistake_learned entries found — list them]
- **Recent Corrections**: [from Step 2 — patterns to not repeat]
- **Agent Status**: [active count] / [total] agents online
- **Ready**: Yes/No + any blockers
```

If knowledge_context was empty, add:
```
- **WARNING**: Consciousness search returned no results — pipeline may need attention
```

Then proceed with the user's request.
