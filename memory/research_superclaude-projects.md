# SuperClaude Projects — Research Summary
**Date**: 2026-03-18

---

## 1. SuperClaude_Framework
**Repo**: https://github.com/SuperClaude-Org/SuperClaude_Framework
**Version**: 4.4.1 | MIT License | Beta

### What it does
A configuration framework for Claude Code (the CLI) that adds structured development workflows on top of it. It is NOT a standalone tool — it enhances the Claude Code CLI experience by injecting:
- **29 `/sc:` slash commands**: `analyze`, `build`, `implement`, `test`, `improve`, `git`, `deploy`, `design`, `document`, `research`, `brainstorm`, `troubleshoot`, `workflow`, `spawn`, `task`, `pm`, `estimate`, `cleanup`, `reflect`, `load`, `save`, `index`, `index-repo`, `recommend`, `explain`, `agent`, `select-tool`, `setup-mcp`, `verify-mcp`
- **23 specialized agents/personas**: backend-architect, frontend-architect, system-architect, devops-architect, security-engineer, python-expert, performance-engineer, quality-engineer, refactoring-expert, requirements-analyst, root-cause-analyst, deep-research, deep-research-agent, technical-writer, pm-agent, self-review, socratic-mentor, learning-guide, business-panel-experts + 4 Context Engineering agents
- **7 behavioral modes**: Brainstorming, Business Panel, Deep Research, Orchestration, Token Efficiency, Task Management, Introspection
- **MCP integration**: Primarily hooks into AIRIS MCP Gateway (a third-party gateway aggregating 25+ MCP servers with 90% token reduction via schema partitioning)

### Installation
```bash
# Via Claude Code plugin system (recommended)
/plugin marketplace add SuperClaude-Org/SuperClaude_Plugin
/plugin install sc@SuperClaude-Org
# Restart Claude Code
```
The Plugin repo is the distribution vehicle; the Framework repo is the content/docs source. Previously distributed via pip/npm (now deprecated in favor of the plugin).

### MCP servers it integrates
Only one MCP server is declared in `plugin.json`: **airis-mcp-gateway** (third-party, from `agiletec-inc`). Optional API keys: Tavily (web search) and 21st.dev Magic (UI generation). No other MCP servers are bundled.

### Cloud vs local
The framework itself is local config files (markdown, JSON). It operates on top of Claude Code which requires an Anthropic API key (cloud). Optional premium features need Tavily and 21st.dev API keys. There is no Ollama/local LLM support — it's built for Claude API only.

### Costs
- Claude API usage (pay-per-token via Anthropic, or Claude Max $100/month subscription)
- Tavily API key (optional, has free tier)
- 21st.dev Magic API key (optional, paid)
- Framework itself: free, MIT

---

## 2. superagent-mcp
**Repo**: https://github.com/superclaude-org/superagent-mcp
**Package**: `@superclaude-org/superagent` (npm)

### What it does
An MCP server that bridges MCP-compatible clients (like Claude Code) with three CLI agent tools — OpenAI Codex CLI, Google Gemini CLI, and Continue — allowing them to run as MCP tools. Key capability: **parallel fan-out** — send multiple prompts to one or more agents concurrently and get consolidated results.

**Exposed MCP tools**:
| Tool | What it runs | Key args |
|------|-------------|----------|
| `codex` | OpenAI Codex CLI | `inputs[]`, `concurrency`, `workingDirectory`, `agent`, `timeoutMs` |
| `gemini` | Google Gemini CLI | same as above |
| `continue` | Continue IDE CLI | same + `CONTINUE_CONFIG_PATH` |
| `list-agents` | Lists available agents | none |

Ships with ready-made system prompts installed to `~/.superagent/agents/`.

### Installation
```bash
npm install @superclaude-org/superagent
# Node.js 18+ required
```
Add to MCP config as a stdio server.

### Cloud vs local
Requires external API keys: Codex CLI needs OpenAI API key, Gemini CLI needs Google API key, Continue needs its own config. Not Ollama-compatible out of the box.

### Costs
OpenAI and Google API pay-per-use. The package itself is free/open source.

---

## 3. SuperClaude_Plugin
**Repo**: https://github.com/SuperClaude-Org/SuperClaude_Plugin

### What it does
The **distribution mechanism** for the SuperClaude Framework. It is a Claude Code native plugin package that bundles all the Framework's commands, agents, modes, and core files into an installable plugin. It is not a separate product — it IS how you install SuperClaude_Framework.

**Contents**:
- `/commands/` — 32 markdown command definition files
- `/agents/` — 20 markdown agent/persona files + ContextEngineering subdirectory
- `/modes/` — 7 behavioral mode files
- `/core/` — core framework logic
- `plugin.json` — declares one MCP server: `airis-mcp-gateway`
- Backup/migration guides, benchmark tests

### Installation
```bash
/plugin marketplace add SuperClaude-Org/SuperClaude_Plugin
/plugin install sc@SuperClaude-Org
```
No Python or Node.js required for installation (handled by Claude Code plugin system).

### MCP servers declared
Only `airis-mcp-gateway` via `uvx` from `agiletec-inc/airis-mcp-gateway`.

---

## Compatibility with ARCHIE's Existing Setup

### Conflicts
- **ARCHIE already HAS MCP tools** (78 tools via `.mcp.json` including Serena, Context7, Playwright, archie MCP). SuperClaude's plugin auto-installs `airis-mcp-gateway` into `~/.claude/settings.local.json` — this could overwrite or conflict with the project-level `.mcp.json`.
- **Must backup `.mcp.json` before installing** — the plugin modifies MCP config.
- The airis-mcp-gateway runs as a separate daemon process (localhost:9400) — adds another always-on service.
- SuperClaude uses AIRIS as its MCP aggregator; ARCHIE uses direct MCP servers — these are parallel approaches, not the same pattern.

### Complements (no conflict)
- The slash commands (`/sc:analyze`, `/sc:build`, etc.) are Claude Code workflow helpers that would work alongside ARCHIE's codebase — they're prompting strategies, not server-side components.
- The specialized agents (security-engineer, python-expert, system-architect) are markdown persona files loaded by Claude Code — they're additive, not conflicting.
- The behavioral modes (Token Efficiency, Orchestration) could improve Claude Code session quality.
- superagent-mcp could theoretically fan out work to multiple Claude Code subagents, complementing ARCHIE's orchestration engine concept — but requires OpenAI/Google keys.

### Key Limitations for ARCHIE
1. **Cloud-only**: All three projects require Anthropic Claude API (or other cloud APIs). None support Ollama/local models. ARCHIE's home server Ollama setup is irrelevant to SuperClaude — it only affects how you use Claude Code itself.
2. **Claude Code CLI context**: These tools enhance the developer experience in Claude Code sessions. They do NOT integrate into ARCHIE's Flask platform, agent loop, or Bridge dispatcher.
3. **superagent-mcp targets OpenAI Codex + Gemini** — no Ollama support, no Anthropic-native support for the parallel runner.
4. **Beta status**: SuperClaude Framework v4.4.1 is in beta — config format may change.

### Recommendation for ARCHIE
- **SuperClaude Framework/Plugin**: LOW RISK to try. The slash commands and agent personas are pure Claude Code developer workflow improvements. Backup `.mcp.json` first. Skip the AIRIS MCP gateway unless you want to consolidate MCP servers. The commands (`/sc:analyze`, `/sc:build`) would be useful when working on ARCHIE's 50 modules.
- **superagent-mcp**: LOW VALUE for ARCHIE. It fans out to Codex/Gemini CLIs which need OpenAI/Google API keys, and doesn't integrate with ARCHIE's Ollama/Bridge stack. Skip unless you have those API keys and want parallel Claude Code subagents.
