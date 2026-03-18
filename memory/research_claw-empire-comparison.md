# Claw-Empire vs ARCHIE Bridge: Research Comparison

**Date**: 2026-03-16
**Repo**: https://github.com/GreenSheep01201/claw-empire (v2.0.4, 751 stars, TypeScript)
**Category**: Multi-agent AI orchestration simulator

---

## What is Claw-Empire?

A local-first AI agent "office simulator" where you play CEO. It orchestrates **external CLI/OAuth/API agents** (Claude Code, Codex CLI, Gemini CLI, OpenCode, Kimi Code, Antigravity, GitHub Copilot) as employees in a virtual company. Pixel-art office UI with agents walking between departments. SQLite-backed, Node.js/TypeScript.

**Key difference from ARCHIE**: Claw-Empire orchestrates *external* coding agents (CLI tools). ARCHIE orchestrates *local* LLM models (Ollama) as specialized AI crew members.

---

## Feature Comparison Table

| Dimension | ARCHIE Bridge | Claw-Empire | Winner |
|-----------|--------------|-------------|--------|
| **Architecture** | Flask/Python, PostgreSQL, Docker | Node.js/TypeScript, SQLite, Docker-optional | Tie (different stacks) |
| **Agent Types** | Local Ollama models (23 agents) | External CLI/API providers (Claude, Codex, Gemini, etc.) | Different scope |
| **Departments/Stations** | 10 stations (COMMAND, ANALYTICS, CREATIVE, etc.) | 6 departments per workflow pack (varies by pack type) | ARCHIE (more granular) |
| **Staffing Model** | 2 primary + 1 auxiliary per station, fixed roster | Dynamic per-pack department topology, flexible agent count | Claw-Empire (more flexible) |
| **Task Dispatch** | capability -> station -> agent mapping, Bridge dispatcher | `$` CEO directives -> Planning dept -> delegation | ARCHIE (more systematic) |
| **Escalation** | 5-step: normal -> same-station -> cross-station -> free cloud -> paid cloud | Meeting-based delegation, team-leader routing | ARCHIE (more sophisticated) |
| **Welfare/Wellness** | Full IAAE: stress, mood, energy, rest cycles, cooldown thresholds | None mentioned | ARCHIE (unique) |
| **Task Board** | unified_tasks table, Dev HQ UI | Full Kanban: Inbox -> Planned -> Collaborating -> In Progress -> Review -> Done | Claw-Empire (richer lifecycle) |
| **Workflow Packs** | Single workflow (improvement pipeline) | 6 packs: development, report, web_research, novel, video_preprod, roleplay | Claw-Empire (more versatile) |
| **Git Integration** | Standard git, single worktree | Isolated git worktrees for parallel agent development | Claw-Empire (safer parallel work) |
| **Multi-Provider** | Ollama local + cloud escalation (OpenAI-compatible) | 7+ CLI providers + API providers (OpenAI, Anthropic, Google, Ollama, etc.) | Claw-Empire (broader) |
| **Messaging** | Telegram bot (approval workflow) | OpenClaw: Telegram, WhatsApp, Discord, Google Chat, Slack, Signal, iMessage | Claw-Empire (more channels) |
| **Auto-Update** | Manual deploy pipeline | Safe-mode auto-update with channel tracking, dry-run, force guards | Claw-Empire |
| **Stuck Task Recovery** | Manual intervention | Active agent monitor with kill action for stuck tasks | Claw-Empire |
| **Office Visualization** | LCARS sci-fi aesthetic, station panels | Pixel-art office with animated agents walking between departments | Tie (different aesthetics) |
| **Self-Healing** | Improvement pipeline (scan -> proposal -> sandbox -> deploy) | Auto-update recovery with git divergence detection | Different approaches |
| **Security** | RBAC, admin auth, Docker isolation | AES-256-GCM encrypted tokens, preflight secret scanning, localhost-only | Both strong |
| **Ethics/Governance** | IAAE transparency page, governance audit log | None mentioned | ARCHIE (unique) |
| **Real-time Updates** | HTTP polling / page refresh | WebSocket live sync | Claw-Empire |
| **Report Generation** | N/A | Report-to-PPT pipeline with templates | Claw-Empire |

---

## Features ARCHIE Could Adopt

### 1. Workflow Pack Profiles (HIGH VALUE, HIGH EFFORT)
Claw-Empire's 6 workflow packs dynamically reconfigure department topology, routing rules, QA criteria, and output templates per project type. ARCHIE could benefit from "mission profiles" that reconfigure station routing based on project type (e.g., a "content creation" profile that emphasizes CREATIVE + COMMUNICATIONS vs an "infrastructure" profile that emphasizes ENGINEERING + SECURITY).

**Effort**: 3-4 weeks. Requires new `workflow_profiles` table, station routing overrides, UI for profile selection.

### 2. Kanban Task Lifecycle (MEDIUM VALUE, MEDIUM EFFORT)
Claw-Empire has a full drag-and-drop Kanban with 6 stages (Inbox -> Planned -> Collaborating -> In Progress -> Review -> Done). ARCHIE's unified_tasks has basic status tracking but lacks visual Kanban and the "Collaborating" stage (multi-agent coordination visibility).

**Effort**: 1-2 weeks. Add Kanban view to Dev HQ, expand task status enum, add drag-drop JS.

### 3. Stuck Task Auto-Kill (HIGH VALUE, LOW EFFORT)
Active agent monitor with process metadata and direct kill action. ARCHIE currently lacks automated detection and termination of hung agent tasks.

**Effort**: 2-3 days. Add timeout watchdog to dispatcher, auto-cancel jobs exceeding expected duration, expose kill button in Bridge UI.

### 4. Git Worktree Isolation (MEDIUM VALUE, MEDIUM EFFORT)
Claw-Empire uses isolated git worktrees so multiple agents can work on different branches simultaneously without conflicts. ARCHIE's agents share a single working tree.

**Effort**: 1-2 weeks. Integrate `git worktree` into sandbox_manager, assign per-agent worktrees for code tasks.

### 5. WebSocket Real-Time Updates (MEDIUM VALUE, MEDIUM EFFORT)
Claw-Empire uses WebSocket for live state sync. ARCHIE currently relies on polling/page refresh for Bridge updates.

**Effort**: 1-2 weeks. Add Flask-SocketIO, emit events from dispatcher on job state changes, update Bridge JS to listen.

### 6. Multi-Messenger Gateway (LOW VALUE, HIGH EFFORT)
Claw-Empire supports 7 messaging platforms via OpenClaw. ARCHIE only has Telegram.

**Effort**: 3-4 weeks. Low priority — Telegram covers the primary use case well.

### 7. Safe Auto-Update Pipeline (LOW VALUE, MEDIUM EFFORT)
Channel-based auto-update with dry-run, force guards, and git divergence detection.

**Effort**: 1 week. Low priority — ARCHIE's improvement pipeline already handles this differently.

---

## Overall Assessment

| Aspect | Verdict |
|--------|---------|
| **Orchestration depth** | ARCHIE is superior — 5-step escalation, welfare tracking, IAAE governance, capability-based routing |
| **Flexibility** | Claw-Empire is superior — workflow packs, dynamic department topology, multi-provider support |
| **Agent welfare** | ARCHIE is unique — no equivalent in Claw-Empire |
| **Task management** | Claw-Empire is superior — full Kanban lifecycle vs basic status tracking |
| **Visualization** | Tie — different aesthetics (LCARS vs pixel-art), both effective |
| **Production readiness** | ARCHIE is superior — PostgreSQL, Docker-native, RBAC, audit logging |
| **Scope** | Different — ARCHIE runs local LLMs; Claw-Empire orchestrates external CLI tools |

### Summary

Claw-Empire and ARCHIE solve **different problems**. Claw-Empire is a coordinator for external AI coding agents (Claude Code, Codex, etc.) — it doesn't run inference itself. ARCHIE runs its own LLM fleet locally and has deeper orchestration (welfare, escalation, governance).

**Claw-Empire is NOT better than ARCHIE's Bridge system** for ARCHIE's use case. However, it has three ideas worth stealing:
1. **Workflow pack profiles** — reconfigurable station routing per project type
2. **Stuck task auto-kill** — watchdog + kill button for hung agents
3. **Kanban task board** — richer task lifecycle visualization

These three would be the highest-ROI additions. The stuck task auto-kill is the quickest win (2-3 days).

---

## Concrete Recommendations (Priority Order)

1. **Stuck Task Watchdog** — 2-3 days, high value. Add timeout detection to BridgeDispatcher, auto-cancel hung jobs, expose kill action in Bridge UI.
2. **Kanban View for Dev HQ** — 1-2 weeks, medium value. Visual drag-drop board for unified_tasks with expanded lifecycle stages.
3. **Mission Profiles** — 3-4 weeks, high value but high effort. Configurable station routing weights per project type. Do this when ARCHIE needs to handle diverse project types simultaneously.
4. **WebSocket for Bridge** — 1-2 weeks, medium value. Replace polling with live updates. Nice quality-of-life improvement.
5. **Git Worktree Isolation** — 1-2 weeks, medium value. Only relevant if agents start doing code generation tasks in parallel.
