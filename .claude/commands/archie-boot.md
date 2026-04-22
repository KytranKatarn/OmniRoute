# ARCHIE Session Boot Protocol

You are starting a new work session on the A.R.C.H.I.E. platform. Execute these steps IN ORDER before doing any work.

## Model Routing (check before starting)

Boot is tool-chain execution, not reasoning. **If you are on Opus, suggest `/model sonnet`** — this protocol runs 4–7 MCP calls and consumes ~20k context tokens with zero reasoning. Burning Opus on it is waste.

- `/archie-boot`, `/archie-stats`, `/archie-save`, `/archie-status` → Sonnet
- Architecture, multi-file refactor, hard debugging → Opus or `/fast`
- Visual mockups, layout exploration → https://claude.ai/design (separate weekly bucket, free with Max)

Three weekly buckets: All models, Sonnet only (safety-valve), Claude Design (separate). Reset Thursday. See CLAUDE.md "Model Routing & Weekly Buckets".

## GitHub Rate Hygiene (not a freeze — verified 2026-04-17)

Pushes, PRs, and merges are FINE as long as we respect published rate limits.

- **Quick check:** `gh api /rate_limit` — `core` remaining > 4,000 of 5,000 → push freely.
- **Batch commits** into meaningful PRs (3–5 related commits each). Don't open a PR for every micro-fix.
- **Squash-merge via `gh pr merge --squash --delete-branch`.**
- **On 403 "secondary rate limit"** → stop for 60 min; it's the abuse detector.
- **Bot/agent writes** to GitHub (Repair Bay auto-PRs, Backup Manager bundle pushes, F.O.R.G.E., agent_loop jobs) must check rate limit before each write. Shared helper is under development (see tasks in Platform Audit project).

Full policy + historical context: `~/.claude/projects/-mnt-archie-brain/memory/feedback_github-actions-minutes.md`.

## Step 0: Declare session role (multi-session coordination)

The user runs Claude Code in **two terminals at once** to conserve the
Opus weekly bucket. Every boot must explicitly declare which role this
session is taking, so sibling sessions don't collide and so the user
knows what to send where.

**Role A — Architect (Opus 4.7):**
- Planning, spec writing, architectural decisions
- Hard multi-file refactors, cross-subsystem debugging
- Writes specs to `~/.claude/plans/<slug>.md` for the Executor to pick up
- Writes durable design notes to `~/.claude/projects/-mnt-archie-brain/memory/`
- Uses Opus sparingly — most turns should hand off to Role B

**Role B — Executor (Sonnet 4.6):**
- Reads specs from `~/.claude/plans/` and executes them
- Runs all `/archie-*` skills, rsync/git/docker/psql, MCP tool-chain work
- Ships PRs, runs deploys, updates `project_session-handoff.md`
- 5× cheaper per turn — this should be the always-on terminal

**Role C — Delegate (platform agents, hub Ollama — zero Claude cost):**
- Not a Claude session at all
- Work dispatched via `mcp__archie__delegate_task(capability=..., reason=...)`
- Platform agents (F.O.R.G.E., V.I.G.I.L., C.O.D.E.X., P.R.O.C.U.R.E., etc.) pick it up
- Known-tool shortcuts (`run_qa_suite`, `check_dep_drift`, `health_check`,
  `run_misroute_audit`, `run_misroute_to_proposal_adapter`,
  `check_platform_health`) skip the LLM entirely — pure Python

**How this session decides its role:**

1. Check `$CLAUDE_MODEL` or the current model context — if you're on
   Sonnet → Role B (Executor). If you're on Opus → Role A (Architect).
2. Check `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`
   for any active sibling-session declaration (look for "Architect:
   in session" or "Executor: in session" lines set by the other terminal).
3. Read `~/.claude/plans/` for any unclaimed specs — Executor picks one
   up; Architect writes new ones.
4. Quick scan of `mcp__archie__get_my_tasks(status='in_progress')` — if
   the sibling claimed a task, don't double-claim.

**Coordination substrates (all shared between terminals):**

| Substrate | Purpose |
|---|---|
| `~/.claude/projects/-mnt-archie-brain/memory/` | Handoff + feedback + project memories, read on boot |
| `~/.claude/plans/` | Architect writes specs, Executor consumes |
| `unified_tasks` table (MCP `create_task` / `get_my_tasks`) | Queue-based work hand-off |
| `work_notes` column | Result of delegated tasks |
| Platform `delegate_task` worker | Auto-routes dispatched work to agents |

**Announce the role in the Step 7 boot summary** so the user sees which
terminal is which at a glance.

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
- **Session role**: Architect (Opus) | Executor (Sonnet) — from Step 0
- **Sibling session**: Active on <role> | None detected
- **KB Health**: [total entries] entries, [embedding %] embedded
- **Active Projects**: [list active project names]
- **Relevant Context**: [any knowledge found for the task]
- **Mistakes to Avoid**: [any mistake_learned entries found — list them]
- **Recent Corrections**: [from Step 2 — patterns to not repeat]
- **Agent Status**: [active count] / [total] agents online
- **Pending specs in ~/.claude/plans/**: [list unclaimed specs, if Executor]
- **Claimed by sibling**: [list tasks sibling is running, if any]
- **Ready**: Yes/No + any blockers
```

If knowledge_context was empty, add:
```
- **WARNING**: Consciousness search returned no results — pipeline may need attention
```

Then proceed with the user's request.
