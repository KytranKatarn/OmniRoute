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

## Infrastructure & Mesh (CRITICAL)
1. **[2026-05-15] Hub Headscale mesh IP = 100.64.0.4 (NOT 100.64.0.1 — deleted)**
   Do instead: All VPS→hub calls use `http://100.64.0.4:3000`. NEVER `https://platform.kytranempowerment.com` (CDN caps at 60s). UFW allows `100.64.0.0/24 → port 3000`.

2. **[2026-05-15] tailscaled-headscale.service needs ExecStartPre for stale socket**
   Do instead: Unit must have `ExecStartPre=/bin/rm -f /tmp/tailscaled.sock` before ExecStart. Restart=always alone won't recover from stale socket.

3. **[2026-05-15] Docker read_only containers — writable dirs need tmpfs or named volumes**
   Do instead: For persistence (billing DBs, data) use named volumes. For temp-only, use `tmpfs: /tmp`. Billing SQLite must NOT be on tmpfs (lost on restart).

4. **[2026-05-15] VPS Stripe env vars must be in docker-compose environment: block**
   Do instead: Even if vars are in `.env`, they must be explicitly listed in `environment:` section of docker-compose.yml — they don't auto-inject into containers otherwise.

5. **[2026-05-15] WTF_DATABASE_URL must use container hostname, not 127.0.0.1**
   Do instead: Use `postgresql+psycopg2://user:pass@wtf_db/wtf` (container service name). `127.0.0.1` fails inside Docker.

6. **[2026-05-15] stripe must be in ROOT requirements.txt for Docker builds**
   Do instead: Dockerfile installs ROOT `requirements.txt`, not `consumer/requirements.txt`. Always add deps to root file for VPS services.

7. **[2026-05-24] Legal Watch Dockerfile: COPY . . must come BEFORE pip install**
   Do instead: If requirements.txt has `pkg @ file:///app/localdir`, Dockerfile MUST `COPY . .` BEFORE `RUN pip install`. Standard cache-friendly order (COPY requirements first) breaks local file refs. Also: `docker cp` fails on read_only rootfs — full rebuild is the only path.

8. **[2026-05-24] Legal Watch VPS live dir = /opt/archie-products/legal-watch/ (NOT kytran-legal-watch/)**
   Do instead: Two legal-watch dirs exist on VPS. `legal-watch/` has Dockerfile + docker-compose.yml and runs the live container. `kytran-legal-watch/` is a stub. Always rsync to `legal-watch/`.

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

## WTF / Parliament Scraping
1. **[2026-05-18] sencanada.ca is fully JS-rendered — requests/BS4 returns skeleton only**
   Do instead: Always use Playwright MCP for sencanada.ca. Scrape the standings/contact list views (`?v=list`, `?v=contact`) for all 96 senators in one page load — far faster than 96 individual profile pages.

2. **[2026-05-18] merge-pr skill Step 7 resets whichever branch is checked out**
   Do instead: `git checkout main` BEFORE invoking /merge-pr. Recovery: `git reflog` → `git cherry-pick <hash>` → new branch + PR.

3. **[2026-05-24] Two SEPARATE shared.entities tables — wtf db ≠ archie db**
   Do instead: `wtf` db `shared.entities` = 487 rows (persons/orgs, entity graph). `archie` db `shared.entities` = 34 rows (topics/departments, cross-watch signals). Completely separate schemas, different purposes. Never confuse them.

4. **[2026-05-24] Organization slugs use `org-` prefix in entity_graph.py**
   Do instead: All org slugs follow `org-{name}` convention (entity_graph.py line 385: `org_slug = "org-" + name_to_slug(org_norm)`). Political parties: `org-liberal-party-of-canada`, etc. Never omit the `org-` prefix.

5. **[2026-05-24] wtf-ingest has read_only rootfs — docker cp is blocked**
   Do instead: Always rsync code to VPS `/opt/archie-products/what-the-fact/` then `docker compose up -d --build --no-deps wtf-ingest`. Never `docker cp` — silently fails on read_only rootfs.

6. **[2026-05-24] rsync multiple files to different VPS subdirs — rsync each path separately**
   Do instead: `rsync file.py user@vps:/app/ingest/` and `rsync other.py user@vps:/app/ingest/shared/` as separate commands. rsync to a parent dir sends files flat — subdir structure is NOT preserved automatically.

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
