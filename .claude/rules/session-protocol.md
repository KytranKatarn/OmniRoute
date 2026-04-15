# Session Protocol (MANDATORY)

## Before Any Work
1. Run `/archie-boot` OR call `mcp__archie__session_briefing` with the task topic
2. The knowledge base has 25,700+ entries with embeddings (99% coverage) — **search before building, search before asking**
3. Check `mistake_learned` entries for the task area — these prevent repeating costly errors
4. The user is REMOTE (not on the server) — never give localhost URLs, always use 192.168.1.200

## During Work
- Use `mcp__archie__search_knowledge` when unsure about patterns, conventions, or past decisions
- Use `mcp__archie__recall_context` when picking up work from a previous session
- All LLM inference goes through Bridge dispatcher — never call Ollama directly from modules (ADR-013)
- Plan mode for ANY task with 3+ steps or architectural decisions
- Stop after 2 failed attempts and ask the user

## After Work
- `mcp__archie__complete_task` with verification notes
- `mcp__archie__log_decision` for any architectural choices made
- `mcp__archie__update_project_understanding` after working on a project
- `mcp__archie__store_memory` for important learnings (use knowledge_type='mistake_learned' for errors)
- **UPDATE `project_session-handoff.md`** — write what was done, what to do next, and any critical context the next session needs. This is the #1 way to prevent forgetting work across sessions.

## Keeping Memory & Index in Sync (MANDATORY)

### Claude Memory Files (`~/.claude/projects/-mnt-archie-brain/memory/`)
When you **create** a new memory file:
- Add it to MEMORY.md in the correct section with a one-line description
- Follow the naming convention: `{type}_{topic}.md` (e.g., `feedback_no-mocking-db.md`)

When you **update** an existing memory file:
- If the description changed, update the corresponding line in MEMORY.md
- If the memory is now stale/irrelevant, add `archived: true` to frontmatter and move to Archived section

When you **delete** a memory file:
- Remove its line from MEMORY.md

### Knowledge Base (DB)
When you learn something important during a session:
- Store it via `mcp__archie__store_memory` (persists across sessions for ALL tools, not just Claude)
- Use `mistake_learned` for errors (1.3x search weight), `vault_note` for docs (1.2x weight)

### Platform State Changes
When modules, agents, stations, or architecture changes:
- Update the relevant `.claude/rules/` file if patterns changed
- Update CLAUDE.md if key files, module counts, or architecture sections are affected
- Run `mcp__archie__update_project_understanding` for the affected project

### MEMORY.md Staleness Check
At session start, if MEMORY.md references counts or statuses (agent count, KB size, node status):
- Verify against current DB state before trusting the numbers
- Update MEMORY.md if numbers are stale (>1 week old or visibly wrong)

## Agent Coordination
- `mcp__archie__get_quick_summary` for platform health and agent status
- `mcp__archie__list_agents` to see who's available and their capabilities
- Bridge dispatcher handles agent routing — use `get_dispatcher()` singleton, never instantiate directly
- 76 active roster agents across 17 departments, ~66 active at any time
