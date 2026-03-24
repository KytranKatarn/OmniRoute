# ARCHIE Code CLI — Design Specification

**Date**: 2026-03-23
**Status**: Approved
**Replaces**: Project #175 (Claude Code Decommission), Project #183 (Dispatch Tracking)
**New Project**: ARCHIE Code CLI — Unified Development Tool

---

## 1. Vision

Build **ARCHIE Code CLI** — a branded terminal-based development tool that mirrors Claude Code's architecture but runs on ARCHIE's own agent fleet, orchestration engine, and module system. Three distribution tiers: Community (public, free), Node (hub-connected), and Hub (full orchestration).

### Goals

- Replace the failed node deployment approach (10 cancelled projects, Decision #258) with a lightweight CLI that connects to hub
- Give node operators development power via a single binary install
- Create a public open-source tool that showcases ARCHIE's capabilities
- Enable bidirectional collaboration with Claude CLI via MCP
- Reuse 91KB of proven code from archie_core module

### Non-Goals

- Replacing Claude Code entirely (augment, not replace)
- Building a full IDE (terminal TUI only, web Chat module as secondary)
- Supporting non-Ollama inference backends in v1

---

## 2. System Architecture

Four layers: Interfaces, Engine, Platform Hub, Inference.

```
┌──────────────────────────────────────────────────────────┐
│                    INTERFACES                             │
│   Go TUI (.exe)  │  Web Chat (/archie-chat)  │  Claude CLI│
└────────┬─────────┴──────────┬─────────────────┴─────┬────┘
         │ gRPC/WebSocket     │ WebSocket              │ MCP
┌────────▼────────────────────▼───────────────────────▼────┐
│                  ARCHIE ENGINE (Python)                    │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────┐  │
│  │ Session Mgr  │ │ Tool Runtime │ │ Skill Loader      │  │
│  │ - context    │ │ - file ops   │ │ - GitHub skills   │  │
│  │ - history    │ │ - git/branch │ │ - slash commands  │  │
│  │ - approval   │ │ - shell exec │ │ - custom actions  │  │
│  └─────────────┘ └──────────────┘ └───────────────────┘  │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────┐  │
│  │ Sandbox Mgr  │ │ Hub Connector│ │ Claude Connector  │  │
│  │ - branch     │ │ - API/MCP    │ │ - escalation      │  │
│  │ - deploy     │ │ - heartbeat  │ │ - peer collab     │  │
│  │ - test       │ │ - sync       │ │ - context share   │  │
│  └─────────────┘ └──────────────┘ └───────────────────┘  │
└──────────────────────────┬───────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────┐
│                 ARCHIE PLATFORM (Hub)                      │
│  Bridge Dispatcher │ Orchestration Engine │ Smart Router   │
│  Agent Roster      │ Knowledge Base (18K) │ Starbase CMD   │
│  Model Management  │ VRAM Warm-boot       │ Skill Registry │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────┐
│                    INFERENCE                               │
│  Local Ollama (GPU/CPU) │ Fleet Nodes │ Cloud (escalation) │
└──────────────────────────────────────────────────────────┘
```

### Key Principle

The Engine is the product. TUI and Web Chat are interfaces to it. The engine runs on every machine (hub, node, or standalone). It talks UP to hub for orchestration/knowledge, DOWN to Ollama for inference, and SIDEWAYS to Claude for collaboration.

---

## 3. archie_core Migration

### Moves to ARCHIE Engine

| Source File | Size | Destination | Notes |
|-------------|------|-------------|-------|
| intent_parser.py | 30KB | `archie_engine/intent_parser.py` | 18 intent types, modernize to use Bridge dispatch |
| command_router.py | 46KB | `archie_engine/command_router.py` | Route intents to handlers via Bridge (not direct Ollama) |
| command_interface.py | 15KB | `archie_engine/session.py` | Session pipeline: parse -> route -> execute -> log |

### Moves to Platform Modules

| Source File | Size | Destination | Notes |
|-------------|------|-------------|-------|
| ai_chat.py | 12KB | `tools/archie_chat/ai_chat.py` | Merge ArchieAI class into existing chat module |
| archie_core.py | 18KB | `ai_bridge/personality.py` | Personality + relationship system benefits all agents |
| ha_bridge.py | 14KB | `tools/archie_chat/ha_bridge.py` | HA integration is a chat interface variant |
| api.py | 18KB | Split: API routes stay in app.py, chat logic merges into archie_chat | Remove duplicate chat logic |

### Deleted After Migration

| Item | Reason |
|------|--------|
| routes.py | Already a placeholder stub |
| archie_core/ directory | Empty after all code migrated |
| All direct Ollama calls | Rewritten to use `get_dispatcher()` (ADR-013) |

---

## 4. Engine Components

```
archie_engine/
├── __init__.py              # Package init, version
├── engine.py                # Main daemon — starts server, manages lifecycle
├── session.py               # Session orchestration (from command_interface.py)
├── intent_parser.py         # Intent classification (from intent_parser.py)
├── command_router.py        # Intent -> handler routing (from command_router.py)
├── tools/                   # Tool runtime
│   ├── file_ops.py          # Read, write, edit, glob, grep
│   ├── git_ops.py           # Branch, commit, diff, merge
│   ├── shell_ops.py         # Command execution with sandboxing
│   └── sandbox.py           # Branch deploy to sandbox subdomain
├── hub/                     # Hub connectivity
│   ├── connector.py         # API/MCP connection to ARCHIE platform
│   ├── heartbeat.py         # Node registration, GPU/RAM reporting
│   ├── sync.py              # Skill sync, model state, agent assignments
│   └── auth.py              # API key auth, node identity
├── inference/               # Model management
│   ├── ollama_client.py     # Local Ollama interface (Bridge-compliant)
│   ├── model_manager.py     # VRAM warm-boot, tier management
│   └── escalation.py        # When to escalate to hub/cloud/Claude
├── skills/                  # Skill system
│   ├── loader.py            # Load skills from hub + local
│   ├── registry.py          # Slash command registration
│   └── executor.py          # Skill execution runtime
├── claude/                  # Claude CLI collaboration
│   ├── mcp_server.py        # Expose engine as MCP server (Claude connects)
│   ├── mcp_client.py        # Connect to Claude CLI as MCP client (escalation)
│   └── context_bridge.py    # Share context/history between engines
└── server.py                # gRPC/WebSocket server for TUI + Web Chat
```

### Request Flow

```
User: "Fix the login timeout bug"
  -> Go TUI -> gRPC -> engine.server
  -> session.py: create/resume session, load context
  -> intent_parser.py: classify -> code_task (complexity: medium)
  -> command_router.py: code_task -> needs ENGINEERING agent
  -> hub/connector.py: ask hub for agent assignment
     Hub responds: Nova (ENGINEERING), model: qwen3-coder on node GPU
  -> inference/ollama_client.py: warm model if needed
  -> inference/model_manager.py: check VRAM, swap if necessary
  -> Agent executes: reads files, generates diff
  -> tools/git_ops.py: create branch fix/login-timeout
  -> tools/file_ops.py: apply diff (pending approval)
  -> Go TUI: shows diff with [Accept] [Reject] [Edit] [Sandbox Test]
  -> tools/sandbox.py: push branch, deploy to sandbox.kytranempowerment.com
  -> Go TUI: "Sandbox live — verify and accept"
```

### Offline Mode (no hub)

- Intent parsing: local Ollama model
- Agent routing: default local agent profile
- Skills: cached from last hub sync
- Inference: local Ollama only, no escalation
- Git/file ops: work normally
- Starbase tracking: queues events, syncs when hub reconnects

---

## 5. Go TUI Design

Built with **Bubble Tea** (Go TUI framework, 30K+ stars).

### Layout

```
┌─ Status Bar ────────────────────────────────────────────┐
│ A.R.C.H.I.E. Code v1.0  │ Hub: * Online │ GPU: 6.2/8GB │
├─────────────────────────────────────────────────────────┤
│  ┌─ Agent Panel (collapsible) ────────────────────────┐ │
│  │ * Nova (ENGINEERING) — qwen3-coder:30b [GPU]       │ │
│  │ o Cipher (SECURITY) — standby                      │ │
│  │ Branch: fix/auth-timeout │ Files: 3 modified       │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  You: Fix the login timeout bug                         │
│                                                         │
│  Nova (ENGINEERING):                                    │
│  ┌─ Flight Deck (thinking) ───────────────────────────┐ │
│  │ > Intent: code_task (confidence: 0.94)             │ │
│  │ > Router: ENGINEERING station, Nova assigned        │ │
│  │ > Model: qwen3-coder:30b-a3b on local GPU          │ │
│  │ > KB context: 3 entries injected                    │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─ Diff: auth_service.py ────────────────────────────┐ │
│  │  142 │-    timeout = 300                           │ │
│  │  142 │+    timeout = int(os.getenv(                │ │
│  │  143 │+        "SESSION_TIMEOUT", 300))            │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  [a]ccept  [r]eject  [e]dit  [s]andbox  [d]iff full    │
├─ Input ─────────────────────────────────────────────────┤
│ > _                                                     │
└─────────────────────────────────────────────────────────┘
```

### Key Bindings

| Key | Action |
|-----|--------|
| Enter | Send message |
| a | Accept pending diff |
| r | Reject pending diff |
| e | Edit diff before accepting |
| s | Deploy to sandbox for testing |
| d | Show full diff (scrollable) |
| Tab | Toggle flight deck |
| Ctrl+P | Toggle agent panel |
| / | Slash command (skills) |
| Ctrl+C | Cancel current operation |
| Ctrl+D | Exit |

### TUI Modes

| Mode | Purpose |
|------|---------|
| Chat | Default — conversational coding with agents |
| Diff Review | Reviewing pending changes — accept/reject/edit per file |
| Sandbox | Watching sandbox deployment + test results |
| Browse | File browser — navigate, read, search codebase |
| Skills | Slash command picker |

### Community vs Hub TUI

| Element | Community | Hub Connected |
|---------|-----------|---------------|
| Status bar | `Local` | `Hub: * Online + GPU stats` |
| Agent panel | Hidden | Active agents + stations |
| Flight deck | Model name only | Full routing trace |
| Sandbox button | Disabled | Active |
| Slash commands | Community skills | Full hub library |

### Branding

- Colors: LCARS palette — #00e5ff cyan, #f5a623 amber, #8b5cf6 purple
- ASCII art ARCHIE banner on startup
- LCARS-style boot animation (0.5s)

---

## 6. Claude CLI Collaboration

### Bidirectional MCP Bridge

ARCHIE Engine is both MCP server (Claude connects to it) and MCP client (it escalates to Claude).

### ARCHIE as MCP Server

Claude adds to `.mcp.json`:
```json
{
  "archie-engine": {
    "command": "archie-code",
    "args": ["mcp-serve"],
    "type": "stdio"
  }
}
```

Tools exposed:

| Tool | Description |
|------|-------------|
| archie_dispatch | Route task to agent/station |
| archie_search_kb | Search 18K knowledge base |
| archie_agent_status | Agent roster and availability |
| archie_sandbox_deploy | Deploy branch to sandbox |
| archie_sandbox_test | Run tests against sandbox |
| archie_skill_execute | Run an ARCHIE skill |
| archie_model_status | Check GPU/model availability |
| archie_git_branch | Create/manage feature branches |

### ARCHIE as MCP Client (Escalation)

When engine decides a task needs cloud intelligence:

| Condition | Action |
|-----------|--------|
| Complexity > local model capability | Escalate to Claude |
| Local model fails twice on same task | Escalate to Claude |
| User types `/claude` or `@claude` | Force escalate |
| Task involves 10+ files | Suggest escalation |
| Code review of ARCHIE output | Always escalate (second opinion) |
| Claude unavailable | Fall back to best local, warn user |

### Context Sharing

Structured handoff — neither engine sees the other's full conversation:

```json
{
  "session_id": "abc-123",
  "task": "Refactor auth middleware",
  "files_involved": ["auth.py", "rbac.py"],
  "kb_context": ["3 relevant entries"],
  "intent": { "type": "code_task", "complexity": "high" },
  "history": ["what has been tried so far"],
  "branch": "refactor/auth-middleware",
  "constraints": ["ADR-013", "no direct Ollama"]
}
```

### Starbase Visibility

All CLI dispatches and Claude collaborations appear in Starbase Command activity feed with full audit trail.

---

## 7. Skill System

### Skill Format

Markdown files with YAML frontmatter:

```markdown
---
name: code-review
description: Review code for bugs, security, and style
trigger: /review, "review this", "check this code"
tier: community
agents: [SECURITY, ENGINEERING]
---

## Steps
1. Read files (or current git diff)
2. Search knowledge base for patterns and past mistakes
3. Analyze for bugs, security, style, performance
4. Present findings by severity
5. Offer auto-fix
```

### Three Sources

| Source | Available To | How Loaded |
|--------|-------------|------------|
| Community | Everyone | Ships with binary |
| Hub | Connected nodes | Synced via Job #54 |
| Custom | Creator only | Local file |

### Skill Tiers

| Tier | Requires |
|------|----------|
| Community | Nothing — ships with binary |
| Hub | Hub connection + auth |
| Station | Agent assignment to specific station |
| Admin | Admin role on hub |
| Custom | Local file (user created) |

### GitHub Ingestion Pipeline

```
GitHub repos -> Job #54 (every 6h) -> knowledge_base -> Hub syncs to nodes -> skills/loader.py
```

### In-CLI Skill Authoring

Users create skills via `/skill create` without leaving the TUI.

---

## 8. Distribution Tiers

| Tier | Name | For | Hub Required | Repo |
|------|------|-----|--------------|------|
| Community | `archie-code` | Anyone (public, free) | No | KytranKatarn/archie-code (public) |
| Node | `archie-code --connect` | Node operators | Yes | Same repo, hub features unlock |
| Hub | Full orchestration | Hub operator | Yes (is the hub) | Private platform repo |

### Node Problems Solved

Previous approach: push full platform clone to nodes via Docker + OTA. Failed 10 times.

New approach: nodes run lightweight engine daemon, connects to hub for orchestration.

| Before (failed) | After (ARCHIE Code CLI) |
|-----------------|------------------------|
| Full platform clone on each node | Lightweight engine daemon |
| Docker required | pip install + Ollama |
| OTA sync breaking things | pip upgrade |
| compose files to manage | No compose needed |
| Days of debugging | Minutes to set up |
| Linux only | Windows, macOS, Linux |

### Subdomain Routing

| Subdomain | Purpose |
|-----------|---------|
| code.kytranempowerment.com | Engine API — TUI + Web Chat connect |
| sandbox.kytranempowerment.com | Branch deployments for testing |
| archie.kytranempowerment.com | Platform UI |

AdGuard split DNS: LAN -> 192.168.1.200, external -> public IP / Cloudflare.

### Install Methods

| Method | Command |
|--------|---------|
| pip (all platforms) | `pip install archie-code` |
| Windows installer | `ARCHIE-Code-Setup.exe` (bundled Python + Go TUI) |
| Homebrew (macOS) | `brew install kytrankatarn/tap/archie-code` |
| One-liner (Linux/macOS) | `curl -fsSL https://code.kytranempowerment.com/install \| bash` |

### Public Repo Structure

```
KytranKatarn/archie-code (public)
├── cmd/                     # Go TUI source
│   └── archie-code/
├── engine/                  # Python engine (community subset)
│   ├── intent_parser.py
│   ├── command_router.py
│   ├── tools/
│   └── skills/
├── skills/                  # Default community skills
│   └── community/
├── installer/               # Platform-specific installers
├── docs/                    # Setup guide, skill authoring
├── README.md
└── LICENSE                  # MIT or Apache 2.0
```

### CI/CD

GitHub Actions builds on tag push:
- Go TUI: cross-compile for linux/mac/windows x amd64/arm64
- Python engine: build + publish to PyPI
- Windows installer: PyInstaller .exe
- GitHub Release: all binaries + installer

### Update Mechanism

| Component | Update Method |
|-----------|--------------|
| Python engine | `pip install --upgrade archie-code` |
| Go TUI | Auto-check GitHub releases on startup |
| Community skills | Ship with engine updates |
| Hub skills | Auto-sync from hub (Job #54) |
| Custom skills | User manages locally |
| Windows installer | Download new .exe |

---

## 9. Hub Features (Node-Connected Only)

When a node connects to hub, these features unlock:

| Feature | How |
|---------|-----|
| Agent orchestration | Hub's 8-step pipeline picks agents for tasks |
| VRAM warm-boot | model_load_state tracks loaded models per host |
| Agent tracking | All dispatches logged to bridge_jobs, visible in Starbase |
| Knowledge base | 18K entries available for RAG context injection |
| Smart Router | GPU-aware task classification and model recommendation |
| Claude escalation | Automatic escalation when local models can't handle task |
| Sandbox deployment | Deploy branches to sandbox.kytranempowerment.com |
| Full skill library | All hub + station-gated skills unlock |
| Starbase visibility | Node activity appears in Starbase Command feed |

---

## 10. Security Model

### Node Authentication (C1)

Node registration is a two-step process:

1. **Registration**: Hub operator generates a node API key via Starbase Command (`/nodes/register`). Key is a 256-bit token stored hashed in `remote_nodes` table.
2. **Connection**: Node connects with `archie-code connect code.kytranempowerment.com --key <token>`. Engine sends key in `Authorization: Bearer <token>` header on every request.
3. **TLS**: All hub connections over HTTPS (Cloudflare tunnel for external, Nginx for LAN). No plaintext.
4. **Revocation**: Hub operator revokes key via Starbase. Node gets 401 on next heartbeat, falls back to offline mode.
5. **Rate limiting**: Hub API rate-limited per node key — 100 requests/min for dispatch, 1000/min for KB search.

Per-node permission scopes:

| Scope | What it allows |
|-------|---------------|
| `read` | KB search, agent status, model status |
| `dispatch` | Route tasks to agents, execute skills |
| `deploy` | Sandbox deployment, branch management |
| `admin` | Full hub access (hub operator only) |

Default node key gets `read` + `dispatch`. `deploy` requires explicit grant.

### MCP Permission Scoping (C2)

MCP server (`archie-code mcp-serve`) runs in **stdio mode only** — binds to the local process, not a network port. Only the local Claude CLI process can connect (same as how Claude Code's MCP servers work).

High-risk tools require user approval in the TUI:

| Tool | Approval Required |
|------|-------------------|
| `archie_dispatch` | No (normal operation) |
| `archie_search_kb` | No (read-only) |
| `archie_sandbox_deploy` | **Yes** — shows branch + target in TUI, user confirms |
| `archie_skill_execute` | **Yes** for hub/admin tier skills, No for community |
| `archie_git_branch` | No (non-destructive) |

### Shell Execution Sandboxing (C3)

`tools/shell_ops.py` implements a permission system modeled on Claude Code's:

1. **Denylist**: Commands that are NEVER executed without explicit override:
   - `rm -rf /`, `mkfs`, `dd`, `chmod 777`, `curl | bash`, `eval`
   - Any command containing `sudo` without prior user approval
2. **Allowlist (auto-approve)**: Safe commands run without prompting:
   - `git status`, `git diff`, `git log`, `git branch`
   - `ls`, `cat`, `head`, `tail`, `grep`, `find`
   - `python -m pytest`, `npm test`, `make test`
3. **Everything else**: Shown to user in TUI with the full command, requires `[a]pprove` or `[r]eject`
4. **Working directory confinement**: Shell ops run in the project root. `cd /` or absolute paths outside project require approval.
5. **Skills cannot bypass**: Skill-triggered shell commands go through the same approval flow.

### Error Handling & Resilience (H4)

| Failure | Engine Behavior |
|---------|----------------|
| Hub connection drops mid-task | Completes current operation locally, queues remaining events for sync. TUI shows "Hub: disconnected — working offline" |
| Ollama crashes | Catches connection error, retries once after 3s, then shows "Model unavailable" with option to switch model |
| gRPC disconnect (TUI ↔ engine) | TUI auto-reconnects with exponential backoff (1s, 2s, 4s, max 30s). Engine preserves session state |
| Multi-file operation partial failure | Atomic per-file: each file edit is a separate git add. If file 4/5 fails, first 3 are staged, user sees which failed and why |
| Model loading failure (VRAM) | Falls back to CPU tier, warns user of slower inference |

---

## 11. Install & Process Model (H1)

### How the Two Processes Work

`pip install archie-code` installs the Python engine AND a CLI entry point `archie-code`. On first run:

```
$ archie-code
  Engine starting on port 7700...
  TUI binary not found. Downloading for your platform...
  Downloaded archie-code-tui-linux-amd64 (12MB) ✓
  Launching TUI...
```

The pip package includes a bootstrap script that:
1. Starts the Python engine as a background daemon
2. Downloads the Go TUI binary from GitHub releases (cached locally)
3. Launches the TUI, which connects to the local engine

For offline installs or Windows installer: both binaries are bundled.

For users who don't want the TUI: `archie-code --headless` runs the engine only (Web Chat or Claude CLI connect to it).

### Minimum Model Requirements (H2)

| Tier | Minimum Model | Intent Parsing | Code Tasks |
|------|--------------|----------------|------------|
| Community (no hub) | qwen2.5-coder:7b (4.5GB) | Rule-based fallback + LLM assist | Basic single-file edits |
| Node (hub-connected) | Any — hub routes to best available | Hub's Smart Router classifies | Full multi-file via hub orchestration |
| Hub | qwen3-coder:30b-a3b (20GB) | Full LLM classification | Complex agentic tasks |

**Rule-based fallback**: When no model is loaded or model quality is insufficient, the intent parser falls back to regex/keyword matching for slash commands (`/review`, `/commit`, `/explain`) and simple patterns ("fix", "add", "delete", "search"). This ensures the CLI always works, even without Ollama.

### Migration Detail: api.py Overlap (H3)

Specific function mapping for api.py (18KB):

| Function in api.py | Destination | Action |
|-------------------|-------------|--------|
| `/api/archie/health` | Stays in app.py | Platform health endpoint (not chat) |
| `/api/archie/search` | Stays in app.py | KB search API (used by multiple modules) |
| `/api/archie/chat` | Merge into archie_chat/api_routes.py | Deduplicate with existing chat service |
| `/api/archie/learn` | Stays in app.py | KB ingestion API (used by MCP) |
| `/api/archie/learn/batch` | Stays in app.py | Batch ingestion |
| `@require_api_key` decorator | Stays in app.py | Shared auth decorator |
| ArchieAI import | Removed — archie_chat uses its own chat_service | Eliminates duplicate |

### Testing Strategy (H5)

| Component | Test Type | Framework |
|-----------|-----------|-----------|
| Intent parser (18 types) | Unit tests with fixture inputs per type | pytest |
| Command router | Unit tests mocking Bridge dispatcher | pytest |
| Tool runtime (file_ops, git_ops) | Integration tests in temp git repos | pytest + tmp_path |
| Shell sandboxing | Unit tests for denylist/allowlist/approval | pytest |
| Hub connector | Integration tests with mock hub server | pytest + httpx |
| Go TUI | Bubble Tea snapshot tests (golden files) | Go testing + teatest |
| Cross-platform builds | CI matrix: ubuntu/macos/windows x amd64/arm64 | GitHub Actions |
| End-to-end | Playwright tests against sandbox deployment | Playwright |

---

## 12. Additional Design Notes

### Protocol Simplification (M1)

v1 uses **WebSocket only** for both TUI and Web Chat connections to the engine. gRPC is a v2 optimization if performance demands it. This halves the serialization work and keeps one connection model.

### Community Access Model (M2)

- Community users: engine binds to `localhost:7700`. TUI connects locally. No DNS needed.
- Hub operator (LAN): `code.kytranempowerment.com` via AdGuard split DNS → 192.168.1.200:7700
- Hub operator (external): Cloudflare tunnel to 192.168.1.200:7700, TLS terminated at Cloudflare

### Skill Execution Model (M3)

Skills are **prompt templates** sent to the LLM as system instructions. The LLM then calls the engine's tools (file_ops, git_ops, shell_ops) through the normal tool-calling flow. Skills cannot execute code directly — they guide the LLM's behavior, and all tool calls go through the same approval pipeline.

### Version Negotiation (M4)

Engine reports its version to hub on connect. Hub checks against minimum compatible version. Incompatible → hub returns `{"error": "upgrade_required", "min_version": "1.2.0", "current": "1.0.0"}` and the TUI shows a clear upgrade message.

### Offline Sync (M5)

Offline queue uses idempotent event IDs. On reconnect, engine replays queued events. Hub deduplicates by event ID. Git branch conflicts detected by hub and surfaced to user as "Branch X has diverged — resolve before sync."

### License (L3)

Apache 2.0 — includes patent grant, preferred for tools that may integrate with commercial systems.

### Logging (L4)

Engine logs to `~/.archie-code/logs/engine.log` with rotation (10MB x 5 files). Log levels: DEBUG, INFO, WARN, ERROR. `--verbose` flag enables DEBUG in TUI. Hub-connected mode also sends ERROR-level events to Starbase.

### Boot Animation (L2)

Shown on first run only. Subsequent launches skip straight to prompt. `--no-banner` flag for scripts/CI.

---

## 13. Technology Stack

| Component | Technology | Reason |
|-----------|-----------|--------|
| TUI client | Go + Bubble Tea | Fast, single binary, cross-platform, proven by OpenCode |
| Engine | Python 3.11+ | Reuses entire ARCHIE codebase, existing Bridge/orchestration |
| Engine server | gRPC + WebSocket | gRPC for TUI (fast, typed), WebSocket for Web Chat |
| Inference | Ollama | Already deployed, GPU/CPU tier management exists |
| Hub communication | REST API + MCP (stdio) | Existing MCP server (79 tools), REST for heartbeat |
| Claude collaboration | MCP (bidirectional) | Standard protocol, Claude Code native support |
| Database | SQLite (engine-local) | Session history, cached skills, offline queue |
| Hub database | PostgreSQL | Existing archie DB (agents, knowledge, jobs) |
| Installer (Windows) | PyInstaller + NSIS | Existing pattern from ARCHIE-Node-Setup.exe |
| CI/CD | GitHub Actions | Existing workflow pattern, cross-platform builds |

---

## 14. Success Criteria

### Product Milestones
1. `pip install archie-code` works on Windows, macOS, Linux
2. Community edition runs standalone with local Ollama (no hub needed)
3. `archie-code connect code.kytranempowerment.com` unlocks full hub features
4. Go TUI renders LCARS-branded interface with diff review and approval
5. Intent parser classifies 18+ task types correctly (with rule-based fallback)
6. Hub-connected nodes appear in Starbase Command with agent tracking
7. Claude CLI can connect as MCP peer and collaborate bidirectionally
8. Sandbox deployment works via sandbox.kytranempowerment.com
9. Skill system loads community + hub + custom skills
10. Shell execution sandboxing passes security review

### Migration Milestones (prerequisite)
11. archie_core code migrated to engine + platform modules
12. archie_core directory deleted
13. api.py functions mapped and deduplicated
14. All direct Ollama calls converted to Bridge dispatch
