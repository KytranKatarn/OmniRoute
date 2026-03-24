# ARCHIE Code CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ARCHIE Code CLI — a branded terminal development tool with Go TUI + Python engine, three distribution tiers (Community/Node/Hub), Claude CLI collaboration, and skill system.

**Architecture:** Python engine daemon handles orchestration, tools, and inference. Go TUI (Bubble Tea) provides LCARS-branded terminal interface. Engine exposes WebSocket server for both TUI and Web Chat. Hub connectivity via REST API + MCP. Reuses 91KB of proven code from archie_core migration.

**Tech Stack:** Python 3.11+, Go 1.22+, Bubble Tea, WebSocket, Ollama, MCP (stdio), SQLite (local), PostgreSQL (hub), GitHub Actions CI/CD.

**Spec:** `docs/superpowers/specs/2026-03-23-archie-code-cli-design.md`

**Rollback:** All commits before Task 1.7 are additive (create/copy). Only the final deletion (Task 1.7) is destructive. Rollback: `git revert` the deletion commit to restore archie_core.

---

## Plan Overview (8 Sub-Plans)

| # | Plan | Scope | Dependency | Est. Tasks |
|---|------|-------|------------|------------|
| 1 | archie_core Migration | Migrate code, delete old module | None | 12 |
| 2 | Engine Core | Intent parser, router, session, tools | Plan 1 | 15 |
| 3 | Hub Connectivity | Connector, heartbeat, sync, auth | Plan 2 | 10 |
| 4 | Skill System | Loader, registry, executor, community skills | Plan 2 | 8 |
| 5 | Claude Collaboration | MCP server/client, context bridge, escalation | Plan 2+3 | 8 |
| 6 | Go TUI | Bubble Tea interface, LCARS branding, all modes | Plan 2 | 12 |
| 7 | Distribution | pip package, Windows installer, CI/CD, auto-update | Plan 2+6 | 10 |
| 8 | Website + Public Repo | GitHub public repo, website hero, subdomain setup | Plan 7 | 6 |

**Execution order:** Plan 1 first (unblocks everything). Plans 2-5 can partially parallelize. Plan 6 after Plan 2 core is stable. Plans 7-8 last.

---

## Plan 1: archie_core Migration

**Goal:** Migrate all useful code from `tools/archie_core/` to proper homes (engine package + existing modules), fix ADR-013 violations, delete the old directory.

**Files to create:**
- `ai_bridge/personality.py` — personality traits + relationship system (from archie_core.py)
- `tools/archie_chat/ha_bridge.py` — Home Assistant integration (from ha_bridge.py)

**Files to modify:**
- `tools/archie_chat/chat_service.py` — merge ArchieAI class
- `app.py:1383-1400` — remove archie_core imports
- `module_registry.py` — remove archie_core registration

**Files to delete:**
- `tools/archie_core/` — entire directory after migration

**Files preserved for engine (Plan 2):**
- `intent_parser.py` → copied to engine package, modernized there
- `command_router.py` → copied to engine package, modernized there
- `command_interface.py` → copied to engine package, modernized there

---

### Task 1.1: Create personality.py from archie_core.py

**Files:**
- Create: `ai_bridge/personality.py`
- Read: `tools/archie_core/archie_core.py` (348 LOC)
- Test: `tests/test_personality.py`

- [ ] **Step 1: Read archie_core.py and identify functions to migrate**

Read `tools/archie_core/archie_core.py`. Extract: `get_personality_trait()`, `get_relationship()`, `update_relationship()`, `check_predefined_script()`. Note DB tables: `archie_personality`, `archie_relationships`.

- [ ] **Step 2: Write failing test for personality module**

```python
# tests/test_personality.py
from ai_bridge.personality import get_personality_trait, get_relationship

def test_get_personality_trait_returns_dict():
    """Personality trait should return a dict with trait data or None."""
    result = get_personality_trait("curiosity")
    assert result is None or isinstance(result, dict)

def test_get_relationship_creates_if_missing():
    """Should create a new relationship record if none exists."""
    result = get_relationship(user_id=99999)
    assert result is not None
    assert "familiarity" in result
```

Run: `pytest tests/test_personality.py -v`
Expected: FAIL — module doesn't exist yet

- [ ] **Step 3: Create ai_bridge/personality.py**

Copy functions from archie_core.py. Fix:
- Import `from db import get_db` (not local get_db)
- Use `try/finally: conn.close()` pattern
- Remove any direct Ollama calls
- Add module docstring noting this was extracted from archie_core

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_personality.py -v`
Expected: PASS (may need DB connection — skip if no test DB)

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/personality.py tests/test_personality.py
git commit -m "refactor: extract personality system from archie_core to ai_bridge"
```

---

### Task 1.2: Move ha_bridge.py to archie_chat

**Files:**
- Create: `tools/archie_chat/ha_bridge.py`
- Read: `tools/archie_core/ha_bridge.py` (296 LOC)
- Modify: `tools/archie_chat/__init__.py` — register HA routes

- [ ] **Step 1: Read ha_bridge.py and identify dependencies**

Read `tools/archie_core/ha_bridge.py`. Note: `register_ha_routes(bp)` function, ArchieAI import, emotional_intelligence import, voice_synthesis import.

- [ ] **Step 2: Copy ha_bridge.py to archie_chat**

```bash
cp platform_v2/tools/archie_core/ha_bridge.py platform_v2/tools/archie_chat/ha_bridge.py
```

- [ ] **Step 3: Update imports in ha_bridge.py**

Fix import paths:
- `from tools.archie_core.ai_chat import ArchieAI` → use archie_chat's chat_service instead
- Ensure Bridge dispatcher used for inference (not direct Ollama)

- [ ] **Step 4: Register HA routes in archie_chat __init__.py**

Add `register_ha_routes(bp)` call in `tools/archie_chat/__init__.py` alongside existing route registrations.

- [ ] **Step 5: Test HA endpoint responds**

```bash
curl -s http://192.168.1.200:3000/api/archie/ha/health | python -m json.tool
```

Expected: JSON response (may be error if HA not configured — that's OK, route must exist)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/archie_chat/ha_bridge.py platform_v2/tools/archie_chat/__init__.py
git commit -m "refactor: move ha_bridge from archie_core to archie_chat"
```

---

### Task 1.3: Merge ArchieAI chat logic into archie_chat

**Files:**
- Read: `tools/archie_core/ai_chat.py` (ArchieAI class)
- Read: `tools/archie_chat/chat_service.py` (existing chat service)
- Modify: `tools/archie_chat/chat_service.py` — merge useful patterns

- [ ] **Step 1: Read both files, identify overlap**

Compare `ArchieAI.chat()` with `chat_service.py`'s chat handling. Identify:
- What ArchieAI does that chat_service doesn't (personality-aware prompting, model selection)
- What's duplicated (both call Ollama/Bridge for inference)
- What should be kept from ArchieAI

- [ ] **Step 2: Merge personality-aware prompting into chat_service**

Add ArchieAI's `_build_system_prompt(user_context)` pattern to chat_service if not already present. This enriches the existing chat with personality traits.

- [ ] **Step 3: Ensure chat_service uses Bridge dispatcher (not direct Ollama)**

Verify all inference calls go through `get_dispatcher().dispatch()`. Fix any direct `requests.post()` to Ollama.

- [ ] **Step 4: Test chat endpoint still works**

```bash
curl -X POST http://192.168.1.200:3000/tools/archie-chat/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "conversation_id": "test"}'
```

Expected: JSON response with agent reply

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/archie_chat/chat_service.py
git commit -m "refactor: merge ArchieAI personality prompting into archie_chat"
```

---

### Task 1.4: Migrate api.py endpoints

**Files:**
- Read: `tools/archie_core/api.py` (581 LOC, 6 endpoints)
- Modify: `app.py:1383-1400` — remove archie_api_bp import/registration
- Verify: existing archie_chat API routes cover the same functionality

- [ ] **Step 1: Map api.py endpoints to existing equivalents**

| archie_core endpoint | Action | Reason |
|---------------------|--------|--------|
| `GET /api/archie/health` | **Keep in app.py** | Platform health — used by monitoring |
| `POST /api/archie/search` | **Keep in app.py** | KB search API — used by MCP tools and external systems |
| `POST /api/archie/chat` | **Drop** | Covered by archie_chat `POST /chat/message` |
| `POST /api/archie/learn` | **Keep in app.py** | KB ingestion — used by MCP `store_memory` |
| `POST /api/archie/learn/batch` | **Keep in app.py** | Batch ingestion — used by GitHub indexing |
| `GET /api/archie/learn/status` | **Keep in app.py** | Job status tracking for batch ingestion |
| `@require_api_key` decorator | **Keep in app.py** | Shared auth decorator for above endpoints |

- [ ] **Step 2: Check if any external system calls the old endpoints**

```bash
grep -r "/api/archie/" platform_v2/ ai_bridge/ --include="*.py" --include="*.js" --include="*.html" | grep -v archie_core
```

If HA Bridge calls `/api/archie/chat` → update to use new endpoint.

- [ ] **Step 3: Move health endpoint to app.py if needed**

If `/api/archie/health` is used by external systems (HA, monitoring), add a lightweight health route to app.py directly.

- [ ] **Step 4: Migrate kept endpoints to app.py, remove archie_api_bp**

Copy the 5 kept endpoint functions (health, search, learn, learn/batch, learn/status) and the `@require_api_key` decorator from `archie_core/api.py` into `app.py` as standalone routes. Then:
- Remove line ~1383: `from tools.archie_core.api import archie_api_bp`
- Remove line ~1400: `app.register_blueprint(archie_api_bp)`
- Fix imports in the copied functions to use `from db import get_db` pattern

- [ ] **Step 5: Test platform still starts**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | tail -10
```

Expected: No import errors, platform starts cleanly

- [ ] **Step 6: Commit**

```bash
git add platform_v2/app.py
git commit -m "refactor: remove archie_core api.py blueprint, endpoints covered by archie_chat"
```

---

### Task 1.4b: Update orchestration_engine.py imports

**Files:**
- Modify: `ai_bridge/orchestration_engine.py` — 3 import blocks reference archie_core

- [ ] **Step 1: Find all archie_core imports in orchestration_engine.py**

```bash
grep -n "archie_core" ai_bridge/orchestration_engine.py
```

Expected: ~3 import sites:
- `get_intent_parser()` from `tools.archie_core.intent_parser` (~line 169-193)
- `ArchieAI` from `tools.archie_core.ai_chat` (~line 798-801)
- Another `ArchieAI` import (~line 2386-2396)

- [ ] **Step 2: Update intent_parser import to use staging path**

Change lazy import from `tools.archie_core.intent_parser` to `archie_engine_staging.intent_parser`. Add graceful fallback:

```python
try:
    from archie_engine_staging.intent_parser import IntentParser
except ImportError:
    IntentParser = None  # Engine not installed — skip intent parsing
```

- [ ] **Step 3: Update ArchieAI imports to use archie_chat**

Replace both `ArchieAI` import blocks to use archie_chat's chat_service:

```python
try:
    from tools.archie_chat.chat_service import ChatService
except ImportError:
    ChatService = None
```

- [ ] **Step 4: Test orchestration still works**

```bash
docker compose restart archie_platform
# Test a Bridge dispatch
curl -X POST http://192.168.1.200:3000/api/archie-chat/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "conversation_id": "test"}'
```

Expected: Response from agent (orchestration pipeline intact)

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "refactor: update orchestration_engine imports from archie_core to new locations"
```

---

### Task 1.5: Copy engine-bound files to staging area

**Files:**
- Create: `archie_engine_staging/intent_parser.py`
- Create: `archie_engine_staging/command_router.py`
- Create: `archie_engine_staging/session.py`

- [ ] **Step 1: Create staging directory**

```bash
mkdir -p archie_engine_staging
```

- [ ] **Step 2: Copy the three engine-bound files**

```bash
cp platform_v2/tools/archie_core/intent_parser.py archie_engine_staging/intent_parser.py
cp platform_v2/tools/archie_core/command_router.py archie_engine_staging/command_router.py
cp platform_v2/tools/archie_core/command_interface.py archie_engine_staging/session.py
```

- [ ] **Step 3: Add header comments noting origin and needed changes**

Add to top of each file:
```python
# ARCHIE Engine — migrated from platform_v2/tools/archie_core/
# TODO (Plan 2): Modernize imports, replace direct Ollama with Bridge dispatch,
# add WebSocket server integration, add tool runtime integration
```

- [ ] **Step 4: Commit staging area**

```bash
git add archie_engine_staging/
git commit -m "refactor: stage engine-bound code from archie_core for Plan 2 modernization"
```

---

### Task 1.6: Remove archie_core from module_registry

**Files:**
- Modify: `module_registry.py` — remove archie_core entry
- Read: `module_registry.py` — find exact line

- [ ] **Step 1: Find archie_core registration**

```bash
grep -n "archie_core" platform_v2/module_registry.py
```

- [ ] **Step 2: Remove archie_core from module_registry.py**

Remove the archie_core entry from the module definitions dict. Keep archie_chat registration intact.

- [ ] **Step 2b: Remove archie_core from rbac.py**

```bash
grep -n "archie_core" platform_v2/rbac.py
```

Remove any permission entries for archie_core. Per CLAUDE.md: "Module perms: add to BOTH rbac.py AND module_registry.py" — the inverse applies on removal.

- [ ] **Step 2c: Fix coderabbit.html archie_core reference**

```bash
grep -n "archie_core" platform_v2/templates/tools/coderabbit.html
```

Update or remove the hardcoded reference to archie_core in the module listing (line ~1564).

- [ ] **Step 3: Test platform starts without archie_core module**

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/api/archie/health
```

Expected: Platform starts, archie_core no longer in module list, no 500 errors

- [ ] **Step 4: Commit**

```bash
git add platform_v2/module_registry.py
git commit -m "refactor: remove archie_core from module registry"
```

---

### Task 1.7: Delete archie_core directory

**Files:**
- Delete: `tools/archie_core/` — entire directory

- [ ] **Step 1: Final verification — nothing imports from archie_core**

```bash
grep -r "from tools.archie_core" platform_v2/ ai_bridge/ --include="*.py"
grep -r "import archie_core" platform_v2/ ai_bridge/ --include="*.py"
```

Expected: Zero results (all imports removed in prior tasks)

- [ ] **Step 2: Delete the directory**

```bash
rm -rf platform_v2/tools/archie_core/
```

- [ ] **Step 3: Verify platform still works**

```bash
docker compose restart archie_platform
docker logs archie_platform 2>&1 | tail -10
curl -s http://192.168.1.200:3000/ | head -5
```

Expected: Clean startup, dashboard loads

- [ ] **Step 4: Commit**

```bash
git add -A platform_v2/tools/archie_core/
git commit -m "refactor: delete archie_core module — all code migrated

Personality system → ai_bridge/personality.py
HA Bridge → tools/archie_chat/ha_bridge.py
ArchieAI → merged into archie_chat/chat_service.py
API endpoints → covered by archie_chat + app.py
Engine code → staged in archie_engine_staging/ for Plan 2

Completes Migration Milestone 11-14 from ARCHIE Code CLI spec."
```

---

### Task 1.8: Push and deploy

- [ ] **Step 1: Push all migration commits**

```bash
git push
```

- [ ] **Step 2: Deploy and verify**

```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Browser test — verify archie_chat still works**

Navigate to `http://192.168.1.200:3000/tools/archie-chat` and send a test message.

- [ ] **Step 4: Log decision and complete tasks in Dev HQ**

```
mcp log_decision: "archie_core module fully migrated and deleted"
mcp complete_task: migration tasks
mcp update_project_understanding: project awareness to 100%
```

---

## Plans 2-8: Outline (detailed plans written after Plan 1 execution)

### Plan 2: Engine Core
- Create `archie_engine/` Python package
- Modernize intent_parser.py (18 intent types, Bridge dispatch, rule-based fallback)
- Modernize command_router.py (intent → handler routing via Bridge)
- Modernize session.py (session lifecycle, context management)
- Build tool runtime: file_ops.py, git_ops.py, shell_ops.py (with sandboxing), sandbox.py
- WebSocket server (engine.py + server.py)
- SQLite local database for sessions
- Unit tests for all components

### Plan 3: Hub Connectivity
- hub/connector.py — REST API client for ARCHIE platform
- hub/heartbeat.py — node registration, GPU/RAM reporting
- hub/sync.py — skill sync, model state, agent assignments
- hub/auth.py — API key management, TLS, permission scopes
- Integration tests with mock hub server

### Plan 4: Skill System
- skills/loader.py — load from community + hub + custom directories
- skills/registry.py — slash command registration, trigger matching
- skills/executor.py — prompt template execution through tool pipeline
- Default community skills (code-review, commit, explain, debug, refactor, test)
- Skill authoring via `/skill create`
- GitHub ingestion pipeline integration (Job #54)

### Plan 5: Claude Collaboration
- claude/mcp_server.py — expose engine tools as MCP server (stdio)
- claude/mcp_client.py — connect to Claude CLI for escalation
- claude/context_bridge.py — structured context sharing protocol
- Escalation rules (complexity threshold, failure count, user override)
- Starbase activity feed integration for Claude-assisted dispatches

### Plan 6: Go TUI
- Bubble Tea application scaffold
- LCARS color theme + ASCII branding
- Chat mode (default conversational coding)
- Diff review mode (accept/reject/edit/sandbox)
- Agent panel (collapsible, shows active agents)
- Flight deck (thinking/routing trace)
- Skill picker (slash commands)
- Status bar (hub connection, GPU, branch)
- WebSocket client connecting to engine
- Community vs Hub mode differences
- Snapshot tests (golden files)

### Plan 7: Distribution
- PyPI package (`archie-code`) with setup.py/pyproject.toml
- Go cross-compilation (linux/mac/windows x amd64/arm64)
- Bootstrap script (pip installs engine, auto-downloads TUI binary)
- Windows installer (PyInstaller + NSIS)
- GitHub Actions CI/CD (build on tag push)
- Auto-update mechanism (check GitHub releases)
- Homebrew tap formula
- Install script for curl one-liner

### Plan 8: Website + Public Repo
- Public GitHub repo structure (KytranKatarn/archie-code)
- README with screenshots, comparison table, install instructions
- Default community skills shipped in repo
- CONTRIBUTING.md for skill authors
- Website hero section with animated terminal
- code.kytranempowerment.com subdomain setup (AdGuard + Nginx)
- sandbox.kytranempowerment.com subdomain setup
- Apache 2.0 LICENSE file
