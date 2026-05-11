# Napkin Runbook

## Curation Rules
- Re-prioritize on every read.
- Keep recurring, high-value notes only.
- Max 10 items per category.
- Each item includes date + "Do instead".

## Execution & Validation (Highest Priority)
1. **[2026-04-15] Never claim done without browser proof**
   Do instead: Screenshot or Playwright verify every UI change before reporting complete.

2. **[2026-04-15] 2 failures = STOP**
   Do instead: After 2 failed attempts, stop and ask user. Never spiral through retries.

3. **[2026-04-15] Search KB before building anything**
   Do instead: `mcp search_knowledge` + `search_mistakes` for the topic before writing code.

4. **[2026-04-15] Plan mode for 3+ step tasks**
   Do instead: Enter plan mode, get user approval, then execute.

5. **[2026-04-15] Verify containers actually start after deploy**
   Do instead: Check `docker logs` output, not just `docker compose up` exit code.

## Shell & Command Reliability
1. **[2026-04-15] Black pre-commit reformats Python**
   Do instead: After first commit fails, re-stage files and commit again.

2. **[2026-04-15] User is REMOTE — never use localhost**
   Do instead: Always use 192.168.1.200 for all URLs and connections.

3. **[2026-04-15] Feature branches mandatory**
   Do instead: Never push to main. Create feat/fix/chore branch + PR via `gh pr create`.

## Domain Behavior Guardrails
1. **[2026-04-15] All LLM inference through Bridge dispatcher**
   Do instead: `from tools.department_hq.services.bridge_dispatcher import dispatch` — never direct Ollama.

2. **[2026-04-15] Agent mutations through agent_service.py only**
   Do instead: Use `agent_service.create_agent()`, `.update_agent()` — no direct SQL on agents table.

3. **[2026-04-15] Docker compose changes are dangerous**
   Do instead: ALWAYS warn user before touching docker-compose.yml — triggers rebuild + DNS downtime.

4. **[2026-04-15] Check .env has all required vars before deploy**
   Do instead: Verify DB_PASSWORD, secrets, client IDs exist in both root `.env` and `platform_v2/.env`.

5. **[2026-04-15] Module perms need BOTH files**
   Do instead: Add to `rbac.py` AND `module_registry.py` when creating/modifying modules.

## Module-Agent Chat Pattern
1. **[2026-05-08] _step_execute ignores selected agent without prefer_agent**
   Do instead: Pass `prefer_agent=agent.get("name")` to `dispatcher.request_work()` — otherwise capability routing overrides agent_target.

2. **[2026-05-08] Service account language preference poisons LLM responses**
   Do instead: After creating probe/claude/archie accounts, set `language='en', auto_detect=false` in `user_language_preferences` immediately.

3. **[2026-05-08] [Action confirmed:] messages re-trigger action injection loop**
   Do instead: In `_inject_warden_action`, skip when `user_msg.startswith("[Action confirmed:")`.

4. **[2026-05-08] Per-module chat = dedicated JS file, not inline configure()**
   Do instead: Create `static/js/{module}-chat.js` with config baked in. No inline configure() in template.

## User Directives
1. **[2026-05-11] PR review → Repair Bay F.O.R.G.E., not Claude tokens**
   Do instead: After `gh pr create`, trigger Repair Bay review (Decision #587). Read summary before merging. Claude does NOT do inline code review — F.O.R.G.E. does it for free on Ollama.

2. **[2026-05-11] /archie-save and /archie-end: vault_notes are MANDATORY, not optional**
   Do instead: For every substantive PR, write 2 vault_notes (user-doc + coder-doc) before marking session done. If skipped, /archie-end is incomplete. No exceptions at any context level.

3. **[2026-04-15] Dev HQ workflow after every commit+push**
   Do instead: `create_task` / `complete_task` / `log_decision` / `update_project_understanding`.

4. **[2026-04-15] Update session-handoff.md at session end**
   Do instead: Write what was done, what to do next, critical context for next session.

5. **[2026-04-15] Use MCP tools, not raw DB queries**
   Do instead: Use platform MCP tools for tracking, knowledge, projects — not ad-hoc SQL.
