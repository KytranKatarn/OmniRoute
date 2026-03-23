# Session Protocol (MANDATORY)

## Before Any Work
1. Run `/archie-boot` OR call `mcp__archie__session_briefing` with the task topic
2. The knowledge base has 18,000+ entries with embeddings — **search before building, search before asking**
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

## Agent Coordination
- `mcp__archie__get_quick_summary` for platform health and agent status
- `mcp__archie__list_agents` to see who's available and their capabilities
- Bridge dispatcher handles agent routing — use `get_dispatcher()` singleton, never instantiate directly
- 107 agents across 10 stations, ~25 active at any time
