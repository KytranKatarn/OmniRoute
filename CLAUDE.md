# A.R.C.H.I.E. Platform

**Version**: 5.33.0 | **Host**: 192.168.1.200 | **Status**: Operational

---

## ⛔ MANDATORY PRE-FLIGHT CHECKLIST

**Run this BEFORE writing any code. No exceptions.**

```
□ 1. SEARCH  — mcp search_knowledge for the topic. Search mistake_learned too.
□ 2. READ    — Read the existing code you're about to modify. Read the reference implementation.
□ 3. VERIFY  — Check CSS classes exist (grep). Check DB columns (schema). Check function signatures.
□ 4. PLAN    — If 3+ steps, enter plan mode. Get user approval before coding.
□ 5. TEST    — Can you test this? If NO, tell user upfront. Don't write untestable code.
```

**After EVERY code change:**
```
□ 1. BRANCH  — NEVER commit directly to main. Create a feature branch first.
□ 2. COMMIT  — Stage and commit the change to the feature branch
□ 3. DEPLOY  — docker compose restart archie_platform
□ 4. TEST    — Browser test (Playwright or manual). Show output.
□ 5. PR      — Push branch, create PR via `gh pr create`. Let user merge.
□ 6. CLAIM   — Only NOW say "done" — with proof
```

**Branch naming:**
```
feat/short-description    — new features
fix/short-description     — bug fixes
chore/short-description   — maintenance, docs, deps
auto/short-description    — AI/automation-initiated changes
```

**Direct push to main is ONLY allowed for:**
- Emergency hotfixes with explicit user approval
- Trivial one-line fixes (typos, version bumps) with user approval

### ⚠️ Never commit a partially-staged file

A file that is staged and then modified again (`git status` shows `AM` or `MM`)
**deadlocks the fixer hooks.** Reproduced deterministically:

```
$ git status --short script.sh
AM script.sh                        # staged, then edited again
$ git commit -m "..."
[WARNING] Unstaged files detected.
fix end of files................Failed
- files were modified by this hook
[WARNING] Stashed changes conflicted with hook auto-fixes... Rolling back fixes...
```

What happens: pre-commit stashes the unstaged delta, runs the fixer over the
staged content, then the stash pop collides with the fix it just made and rolls
everything back. The commit aborts with a message that does not name the real
cause.

Fix — stage the file *again* so index and worktree agree, then retry:

```bash
git add <file> && git commit -m "..."
```

Never reach for `--no-verify` here. Every hook still passes; it is the stash
ordering that fails, not the checks. If a hook legitimately rewrites your file,
re-stage it and commit again.

**On failure:**
```
□ Attempt 1 fails → Understand WHY (read code, check logs, verify state)
□ Attempt 2 fails → STOP. Tell user what you tried and why it failed. Ask how to proceed.
□ NEVER spiral through 20 attempts. NEVER corrupt working code trying workarounds.
```

---

## Model Routing & Weekly Buckets (Max 20x)

Three independent weekly buckets reset Thursday. Route work deliberately.

| Bucket | Use for | How to invoke |
|---|---|---|
| **All models** (Opus + Sonnet + Haiku) | Hard reasoning, architecture, multi-file refactor, complex debugging | `/model opus` or `/fast` (Opus 4.6, faster output) |
| **Sonnet only** (safety-valve) | Routine work — reads, edits, commits, boot/stats/status skills, tool-chain execution | `/model sonnet` |
| **Claude Design** (separate quota, free with Max) | Visual mockups, prototypes, slides, LCARS layout exploration — Project #223 lives here | https://claude.ai/design |

**Default rule**: Sonnet for routine work. Opus only when reasoning is actually required. Claude Design for anything visual — it does not touch the Claude Code budget.

`/archie-boot`, `/archie-stats`, `/archie-save`, `/archie-status`, `/archie-search`, `/archie-project` are tool-chain execution — **run them on Sonnet**.

---

## 6 Rules (Memorize These)

| # | Rule | One-liner |
|---|------|-----------|
| 1 | **Verify Everything** | Never claim done without live browser proof |
| 2 | **Read Before Building** | Search KB + read existing code before writing anything |
| 3 | **Never Guess** | If you haven't read it, you don't know it. 2 strikes → ask user |
| 4 | **No Wasted Effort** | Can't test it? Say so. Beyond capability? Say so immediately |
| 5 | **Follow Patterns** | Departments→AgentService, modals→LCARS, LLM→Bridge, SaaS→per-user |
| 6 | **Platform Rules** | User is REMOTE (192.168.1.200). Never commit secrets. Bridge first |

Full details in memory files: `feedback_01` through `feedback_06`

---

## Session Start Protocol (MANDATORY)

Every new session MUST begin with one of:
- Run `/archie-boot` (preferred — guided session boot)
- Call `mcp__archie__session_briefing` with the task topic (one-call alternative)

**The knowledge base has 25,700+ entries with embeddings (99% coverage). Search before building. Search before asking.**
- `search_knowledge` — semantic + text search across all knowledge types
- `recall_context` — recall past context for a topic
- `search_knowledge` with types: ["mistake_learned"] — prevent repeating costly errors

**The user is REMOTE** — always use 192.168.1.200, never localhost.

---

## Quick Reference

| Resource | Location |
|----------|----------|
| Platform | http://192.168.1.200:3000 |
| Dev HQ | http://192.168.1.200:3000/tools/consciousness/#devhq (tab inside Consciousness) |
| Docs | `knowledge_base` table → Consciousness Knowledge tab or MCP `search_knowledge` |
| Modules | `/mnt/archie_brain/platform_v2/tools/` (36 modules) |
| MCP Tools | 87 tools via `.mcp.json` (incl. `session_briefing`, `propose_hire` #2124, `delegate_task` #2207) |
| Projects | `unified_projects` table → MCP `get_projects` / `create_task` |

## Architecture (3 Core Systems + 6 Subsystems)

### 3 Core Systems
1. **Autonomy Module** - Scheduled jobs, background processing (`ai_bridge/agent_loop.py`)
2. **Department HQ** - Agents, departments, dispatch, fleet, jobs — 14 tabs (`tools/department_hq/`)
3. **AI Bridge** - Model routing, embeddings, knowledge analysis (`ai_bridge/`)

### 6 Subsystems
4. **Knowledge Base** - `knowledge_base` table (~25,700 entries, 99% embedded, quality-scored)
5. **Module System** - Flask Blueprints in `/platform_v2/tools/` (36 modules)
6. **Consciousness** - Knowledge analytics, AI processing, embedding coverage
7. **Self-Healing Pipeline** - Audit → Propose → Fix → Verify (`services/audit_pipeline.py`)
8. **C.R.E.E.D.** - Ethics & compliance, standalone at :8086 + DHQ tab (Decision #438)
9. **Agent Service** - Centralized agent CRUD, lifecycle (`services/agent_service.py`)

*Starbase Command merged into Department HQ Fleet tab (2026-04-08). Dispatcher moved to DHQ services (Decision #440).*

## Source of Truth

| Data | Location | Access |
|------|----------|--------|
| Documentation & Knowledge | `knowledge_base` table | MCP `search_knowledge`, `store_memory` |
| Projects & Tasks | `unified_projects` + `unified_tasks` | MCP `get_projects`, `create_task`, `complete_task` |
| Decisions | `project_decisions` table | MCP `log_decision` |
| Module Code | `/platform_v2/tools/` | Direct file access |
| Roadmaps | `knowledge_base` vault_notes with "roadmap" tag | MCP `search_knowledge` |

**NO filesystem docs** — `/docs/` is archived. **NO TODO_LIST.md** — use `unified_tasks`. **NO ad-hoc memory** — use Dev HQ.

## Key Files

```
platform_v2/app.py                          - Flask app + |localtime filter
platform_v2/module_registry.py              - Module definitions
platform_v2/rbac.py                         - Permissions
platform_v2/database.py                     - DB connection
platform_v2/services/agent_service.py       - Centralized agent CRUD, lifecycle, skills, welfare (+propose_hire #2124)
platform_v2/services/agent_models.py        - Model load/unload/warmboot
platform_v2/services/agent_dispatch.py      - Candidate selection, scoring
platform_v2/services/audit_pipeline.py      - Self-healing repair pipeline
platform_v2/services/agent_social_service.py - Social presence
platform_v2/services/work_tracking_service.py - Work sessions, metrics
platform_v2/services/department_coordinator.py - Skill-first routing w/ cross-dept fallback (ADR-002, #2217)
platform_v2/services/delegation_service.py  - Claude → A.R.C.H.I.E. delegation surface (#276)
platform_v2/services/misroute_to_proposal_adapter.py - S.P.E.C.T.R.A. observer→proposal adapter (#2186)
platform_v2/tools/department_hq/            - Department management (6 tabs)
platform_v2/tools/agent_academy/            - Training & benchmarks (5 tabs)
platform_v2/static/js/archie-time.js        - Timezone formatter
ai_bridge/archie_bridge.py                  - AI routing (intent parse + cost calc)
ai_bridge/knowledge_analyzer.py             - Knowledge extraction
ai_bridge/embedding_service.py              - Vector embeddings
platform_v2/tools/department_hq/services/department_dispatcher.py - Dispatch entry point (renamed from bridge_dispatcher, Decision #441)
platform_v2/tools/department_hq/services/orchestration_engine.py - 8-step orchestration pipeline
platform_v2/tools/department_hq/services/smart_router.py         - GPU-aware 11-tier routing + CAPABILITY_TAXONOMY
platform_v2/tools/department_hq/coms_routes.py                   - COMs tab: Telegram message feed, config, migration status
platform_v2/tools/agent_academy/competency_routes.py             - Competency testing + department readiness
platform_v2/services/telegram_service.py                         - Unified Telegram: A.R.C.H.I.E. voice, source_agent, message logging
# NOTE: ai_bridge/{bridge_dispatcher,orchestration_engine,smart_router}.py are back-compat shims only.
# New code must import from tools.department_hq.services.* — enforced by scripts/check_agent_single_writer.py
```

## Pattern Reference

### Department HQ → Agent Service Pattern
- All agent mutations go through `agent_service.py` — no direct SQL on agent tables
- 17 departments across 5 floors: BRIDGE, OPERATIONS, ENGINEERING, CREATIVE, SERVICES
- Department HQ module: 14 tabs (Overview, Org Chart, Roster, K.I.N., C.R.E.E.D., S.I.G.N.A.L., S.C.O.U.T., Autonomy, A.R.M.A.D.A., Contractors, COMs, Online Presence, V.I.G.I.L., Approvals) — Devices tab removed 2026-08-17 (device management lives in Security & Network)
- Agent Academy module: 5 tabs (Benchmarks, Training, A/B Testing, Skills, Reports)
- Agent lifecycle: `agent_service.create_agent()`, `.update_agent()` — there is NO `deactivate_agent()`/decommission function today; retire an agent via `update_agent()` setting `shift_state='decommissioned'`

### Bridge Dispatch → ALL LLM Calls (ADR-013)
- `get_dispatcher()` singleton — never instantiate directly
- `dispatch()` or `dispatch_json()` for all inference
- `get_crew_manifest()` for roster data
- Escalation: home → capability → cross-department → fleet → cloud

### LCARS Modals → bm- Classes
- `bm-overlay > bm-shell > bm-frame + bm-content > bm-header + bm-body + bm-footer`
- Set `--bm-accent` for theming
- Reference: `bridge.html` lines 9209-9249

### Agent Roster
- `agents` table = single source of truth (**140 non-decommissioned re-measured 2026-08-20: 116 ai + 23 internal + 1 contractor** by worker_type; the 2026-08-17 line said 24 internal, which summed to 141 — the arithmetic did not close)
- worker_type='ai' spans 17 departments (incl. persona/collaborator identities — the ~34 "roster AI agents" figure was a stale, narrower classification)
- 17 departments (News & Media added 2026-04-14 with 6 AI agents)
- 1 agent = 1 department (managed via `agent_service.py`)
- Shift states: active, deployed, barracked, off_duty, winding_down, cooldown
- A.R.C.H.I.E. = Executive Office (COO), P.R.O.B.E. = Engineering director, V.I.G.I.L. = Security & Compliance director
- Column is `worker_type` (ai/internal/contractor) — NOT `agent_type`
- All agent mutations go through `agent_service.py` — no direct SQL on agent tables

### UI
- 🔴 **`sc-live` / `sc-static` DO NOT EXIST** (corrected 2026-09-01) — defined in no
  stylesheet; `department-hq-orchestration.js:31` still sets them and wipes the badge's
  other classes doing it. Details + replacement guidance in `.claude/rules/frontend.md`.
- Single status badge per agent
- `_renderUnifiedAgentCard()` for all agent cards
- `openAgentProfileFromBridge(hubAgentId)` for profiles
- Responsive: 480px / 768px / 1024px breakpoints

### Model Management
- 3 tiers: GPU (VRAM) > CPU (RAM) > Cold (disk)
- `model-control` endpoint for load/unload (accepts `node_id`)
- ComfyUI VRAM swap before SDXL generation

## Critical Technical Rules

1. **Read before modify** — Check existing code patterns first
2. **Two `.env` sources, both LIVE — a variable can have TWO different values at once.**
   Root `.env` is injected as **process env** by compose (`env_file: - .env`, read at *container
   create*). `platform_v2/.env` is visible inside the same container at **`/app/.env`**, and code
   loads it with dotenv. So `os.getenv("X")` and `load_dotenv("/app/.env")["X"]` can disagree.

   As of 2026-10-06 they **do** disagree for 7 shared vars — `ARCHIE_CLAUDE_PASSWORD`,
   `CANLII_API_KEY` (absent from the mirror), `GDRIVE_ENCRYPTION_PASSPHRASE_HASH` (absent from
   root), `GITHUB_REPOS`, `GITHUB_TOKEN`, `INTERNAL_API_KEY`, `NTOPNG_ADMIN_PASSWORD` — and the
   files are not even the same shape (49 vars only in root, 17 only in the mirror). **Do not
   "fix" this by copying one over the other**; each side may be correct for its own consumer.
   Resolve a given variable's source deliberately before trusting it.

   **Precedence, settled three independent ways — root `.env` wins:**
   1. compose injects root `.env` as process env (`env_file: - .env`)
   2. `platform_v2/config.py` calls bare `load_dotenv()` — **no `override=True`** — and
      python-dotenv defaults to `override=False`, so an existing process env is never replaced
   3. `ai_bridge/external_providers._get_api_key()` checks `auth_env_var` against `os.getenv`
      *before* the encrypted DB column
   4. `platform_v2/services/agent_credential_service.py` and
      `platform_v2/tools/backup_manager/_shared.py` both document it in comments

   So `/app/.env` only fills variables root does not define at all (it has 17 such), and all 7
   divergent shared vars resolve to the ROOT value at runtime.

   **The mirror is NOT dead config — do not delete it.** It has four real readers (verified
   2026-10-06 by sweeping cron, systemd, compose, Dockerfiles, CI and every running container):

   | reader | what it does |
   |---|---|
   | `platform_v2/services/qa_spec_runner.py` | `load_dotenv("/app/.env")`, falls back to the mirror for `${...}` refs in QA specs |
   | `platform_v2/tools/system_operations/stack_routes.py` | reads the file's **full contents** and returns them in the System Operations stack API |
   | `platform_v2/tools/system_operations/stack_routes.py` | whitelists `platform_v2/.env` as a servable env file beside `.env` |
   | `website/.../_export_agents.py` | `DB_PASSWORD` fallback |

   Of its 17 mirror-only vars, none is read by any consumer that loads dotenv — but that is a
   statement about those variables, NOT about the file. Confusing the two leads to deleting a file
   that four things depend on.

   `platform_v2/tools/backup_manager/_shared.py`, `.../routes_storage.py` and
   `platform_v2/services/agent_credential_service.py` also mention the path, but only in COMMENTS —
   and those comments say the container does NOT load it. Don't read a comment as a reader.

   This has caused real incidents, not just confusion: **#5124** (Cloud tab hid itself, and 37
   good off-site backups appeared lost, because a recovery check keyed off a var
   `archie_platform` does not load) and **#5311** (a rotation reported success against
   `/app/.env` while the root `.env` needed a hand-sync).

   Verify with fingerprints, never by printing a value:
   `sed -n 's/^VAR=//p' .env | tr -d '"\''\r' | sha256sum | cut -c1-12`
3. **Module perms** — Add to BOTH `rbac.py` AND `module_registry.py`
4. **Keep indexes in sync** — Memory files → MEMORY.md. Architecture changes → rules files + CLAUDE.md
5. **Dev HQ after every commit+push**:
   - `mcp create_task` for new work
   - `mcp complete_task` with notes when done
   - `mcp log_decision` for architectural choices
   - `mcp update_project_understanding` after working on a project

## Common Errors

| Error | Fix |
|-------|-----|
| `archie_database` not found | Run inside Docker container |
| `localhost:5432 refused` | Use `192.168.1.200` for DB_HOST |
| `TemplateNotFound` | Use `tools/` prefix in path |
| Module not showing | Check both `rbac.py` + `module_registry.py` |
| Ollama resource contention | Unload non-essential models before inference |
| Changed a var in `.env` but the container ignores it | `docker restart` does **NOT** re-read `env_file`. It is applied at container **create**. Use `docker compose up -d --force-recreate <svc>` |
| A rotated secret looks half-applied | Same cause. Confirm with `docker exec <svc> sh -lc 'printf "%s" "$VAR" \| sha256sum \| cut -c1-12'` — the **process env** hash, not the file's |
| Agent column errors | `current_mood` (not mood), `skill_category` (not category), `proficiency_level` (not level) |

## Commands

```bash
docker compose up -d                          # Start
docker compose restart archie_platform        # Restart
docker logs -f archie_platform                # Logs
docker exec -it archie_database psql -U archie -d archie  # DB
```

## Skills

- `/archie-boot` - Session start protocol (MANDATORY)
- `/archie-status` - Platform health check
- `/archie-module` - Create/modify modules
- `/archie-deploy` - Safe deployment
- `/archie-patterns` - Code patterns & conventions
- `/archie-search` - Search knowledge base
- `/archie-project` - Project & task management
- `/archie-work` - Start/track work sessions

# context-mode — MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional — they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session.

## BLOCKED commands — do NOT attempt these

### curl / wget — BLOCKED
Any Bash command containing `curl` or `wget` is intercepted and replaced with an error message. Do NOT retry.
Instead use:
- `ctx_fetch_and_index(url, source)` to fetch and index web pages
- `ctx_execute(language: "javascript", code: "const r = await fetch(...)")` to run HTTP calls in sandbox

### Inline HTTP — BLOCKED
Any Bash command containing `fetch('http`, `requests.get(`, `requests.post(`, `http.get(`, or `http.request(` is intercepted and replaced with an error message. Do NOT retry with Bash.
Instead use:
- `ctx_execute(language, code)` to run HTTP calls in sandbox — only stdout enters context

### WebFetch — BLOCKED
WebFetch calls are denied entirely. The URL is extracted and you are told to use `ctx_fetch_and_index` instead.
Instead use:
- `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` to query the indexed content

## REDIRECTED tools — use sandbox equivalents

### Bash (>20 lines output)
Bash is ONLY for: `git`, `mkdir`, `rm`, `mv`, `cd`, `ls`, `npm install`, `pip install`, and other short-output commands.
For everything else, use:
- `ctx_batch_execute(commands, queries)` — run multiple commands + search in ONE call
- `ctx_execute(language: "shell", code: "...")` — run in sandbox, only stdout enters context

### Read (for analysis)
If you are reading a file to **Edit** it → Read is correct (Edit needs content in context).
If you are reading to **analyze, explore, or summarize** → use `ctx_execute_file(path, language, code)` instead. Only your printed summary enters context. The raw file content stays in the sandbox.

### Grep (large results)
Grep results can flood context. Use `ctx_execute(language: "shell", code: "grep ...")` to run searches in sandbox. Only your printed summary enters context.

## Tool selection hierarchy

1. **GATHER**: `ctx_batch_execute(commands, queries)` — Primary tool. Runs all commands, auto-indexes output, returns search results. ONE call replaces 30+ individual calls.
2. **FOLLOW-UP**: `ctx_search(queries: ["q1", "q2", ...])` — Query indexed content. Pass ALL questions as array in ONE call.
3. **PROCESSING**: `ctx_execute(language, code)` | `ctx_execute_file(path, language, code)` — Sandbox execution. Only stdout enters context.
4. **WEB**: `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` — Fetch, chunk, index, query. Raw HTML never enters context.
5. **INDEX**: `ctx_index(content, source)` — Store content in FTS5 knowledge base for later search.

## Subagent routing

When spawning subagents (Agent/Task tool), the routing block is automatically injected into their prompt. Bash-type subagents are upgraded to general-purpose so they have access to MCP tools. You do NOT need to manually instruct subagents about context-mode.

## Output constraints

- Keep responses under 500 words.
- Write artifacts (code, configs, PRDs) to FILES — never return them as inline text. Return only: file path + 1-line description.
- When indexing content, use descriptive source labels so others can `ctx_search(source: "label")` later.

## ctx commands

| Command | Action |
|---------|--------|
| `ctx stats` | Call the `ctx_stats` MCP tool and display the full output verbatim |
| `ctx doctor` | Call the `ctx_doctor` MCP tool, run the returned shell command, display as checklist |
| `ctx upgrade` | Call the `ctx_upgrade` MCP tool, run the returned shell command, display as checklist |
