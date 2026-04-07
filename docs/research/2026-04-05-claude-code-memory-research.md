# Claude Code Memory & Session Persistence Research

**Date**: 2026-04-05
**Depth**: Exhaustive
**Researcher**: Claude Opus 4.6 (Deep Research Agent)

---

## 1. Official Claude Code Memory System

Claude Code has **three complementary memory layers** (as of early 2026):

### Layer 1: CLAUDE.md Files (User-Written Instructions)

Markdown files that give Claude persistent instructions. Claude reads them at the **start of every session**.

| Location | Scope | Loaded When |
|----------|-------|-------------|
| `~/.claude/CLAUDE.md` | Global (all projects) | Always at launch |
| `~/project/CLAUDE.md` | Project root | Always at launch |
| `~/project/CLAUDE.local.md` | Project (gitignored) | Always at launch |
| Parent directories above CWD | Inherited | Always at launch |
| Subdirectory `CLAUDE.md` | Directory-specific | On-demand when Claude reads files in that directory |

**Precedence**: More specific locations override broader ones.

**Key limitation**: CLAUDE.md is **advisory** -- Claude reads it but LLM judgment decides how closely to follow it. Without hooks, rules are suggestions, not enforced gates.

### Layer 2: Auto Memory (MEMORY.md -- Claude-Written Notes)

Shipped in **v2.1.59 on 26 February 2026**. Claude writes notes for itself automatically.

- **Location**: `~/.claude/projects/{project-hash}/MEMORY.md`
- **Scope**: Per-project (one memory directory per git repo, or per working directory outside git)
- **Loading**: First **200 lines or 25KB** (whichever is smaller) loaded at session start
- **Content**: Build commands, code style, architecture decisions, debugging insights, workflow habits
- **Toggle**: `/memory` command in session, or via project settings, or `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- **Zero maintenance**: Users don't need to manually record project details
- **Per-project isolation**: Different projects don't pollute each other

### Layer 3: Session Memory (Conversation History)

- **`claude --continue`**: Picks up the most recent session
- **`claude --resume`**: Choose from recent sessions by name
- **`/rename`**: Give sessions descriptive names (e.g., "oauth-migration")
- **Session summaries**: Include title, status, completed items, open questions, key results, work log

### Context Compaction

- Triggers at ~64-75% context usage (improved from 90%+ historically)
- For 200K context window, compaction happens around 167K tokens
- 33K buffer reserved for the summarization process itself
- **v2.0.64 (Feb 2026)**: Made compaction instant
- Preserves requests and key code snippets; detailed early instructions may be lost
- **Best practice**: Put persistent rules in CLAUDE.md, not conversation history
- **PreCompact hook**: Fire custom scripts before compaction to save state

---

## 2. Claude Code Hooks for Session Persistence

Hooks are scripts that fire at specific lifecycle points. **12 hook event types** as of 2026.

### Key Hook Types for Memory/Persistence

| Hook | When It Fires | Memory Use Case |
|------|--------------|-----------------|
| `SessionStart` | New session begins | Load previous session summary, inject context |
| `SessionEnd` | Session ends | Save session summary, extract patterns |
| `PreCompact` | Before context compaction | Save work state before summarization |
| `PostToolUse` | After any tool runs | Capture observations, log actions |
| `UserPromptSubmit` | User sends a message | Inject relevant memories into context |
| `Stop` | Claude stops responding | Parse transcript, generate summaries |

### Configuration

Hooks are configured in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "bash /path/to/session-start.sh",
        "timeout": 5000
      }
    ]
  }
}
```

### Hooks vs MEMORY.md

| Aspect | MEMORY.md / Auto Memory | Hooks |
|--------|------------------------|-------|
| **Purpose** | Knowledge persistence | Rule enforcement + state preservation |
| **Reliability** | Advisory (LLM judgment) | Mechanical execution (guaranteed) |
| **Maintenance** | Zero (auto) or manual | Requires scripting |
| **Best for** | Learning, preferences, patterns | Enforcing standards, saving state |

**Modern best practice**: Use BOTH together. Auto Memory for learning; hooks for enforcement.

---

## 3. claude-mem by thedotmack -- Deep Dive

### Overview

| Attribute | Value |
|-----------|-------|
| **GitHub** | https://github.com/thedotmack/claude-mem |
| **Stars** | **45,602** |
| **Forks** | Not retrieved (API limited) |
| **Latest Version** | v11.0.0 (released 2026-04-05) |
| **Previous** | v10.7.2, v10.7.1 (same day) |
| **Language** | TypeScript/JavaScript |
| **License** | Listed in repo |
| **Author** | Alex Newman (@thedotmack) |
| **Website** | https://claude-mem.ai |
| **Docs** | https://docs.claude-mem.ai |
| **Discord** | Active community |
| **X/Twitter** | @Claude_Memory |

### How It Works

**6 Core Components:**

1. **5 Lifecycle Hooks** -- SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd
2. **Smart Install** -- Cached dependency checker (pre-hook script)
3. **Worker Service** -- Express HTTP API on port 37777 with web viewer UI and 10 search endpoints (managed by Bun)
4. **SQLite Database** -- Stores sessions, observations, summaries at `~/.claude-mem/claude-mem.db`
5. **mem-search Skill** -- Natural language queries with progressive disclosure
6. **Chroma Vector Database** -- Hybrid semantic + keyword search for intelligent context retrieval

### Installation

**Via Plugin Marketplace:**
```bash
/plugin marketplace add thedotmack/claude-mem
/plugin install claude-mem
```

**Via OpenClaw Gateway:**
```bash
curl -fsSL https://install.cmem.ai/openclaw.sh | bash
```

### Key Features

- **Persistent Memory**: Context survives across sessions automatically
- **Progressive Disclosure**: Layered memory retrieval with token cost visibility
- **Skill-Based Search**: Query project history with `mem-search` skill
- **Web Viewer UI**: Real-time memory stream at http://localhost:37777
- **Claude Desktop Skill**: Search memory from Claude Desktop conversations
- **Privacy Control**: `<private>` tags to exclude sensitive content
- **Context Configuration**: Fine-grained control over what gets injected
- **Citations**: Reference past observations with IDs
- **Beta Channel**: Experimental features like "Endless Mode" (biomimetic memory for extended sessions)

### Open Issues (as of 2026-04-05)

Multiple open issues exist on the repo. The tool is very actively developed (3 releases on April 5 alone), which suggests both rapid iteration and potential instability.

### Production Readiness Assessment

**Strengths:**
- 45K+ stars -- massive community validation
- Very active development (v11.0.0 just released)
- Comprehensive architecture (hooks + vector DB + web UI)
- Official documentation site, Discord, dedicated X account
- OpenClaw integration

**Concerns:**
- Extremely rapid versioning (v4 -> v11 in weeks) suggests breaking changes
- Runs a background worker service (port 37777) -- resource overhead
- Requires Bun runtime
- Chroma vector DB adds complexity
- Multiple open issues

---

## 4. Alternative Memory Tools (Ranked by Stars)

### Tier 1: Major Tools (1000+ stars)

| Tool | Stars | Description | Approach |
|------|-------|-------------|----------|
| **memsearch** (zilliztech) | 1,124 | Markdown-first memory system | 4 shell hooks + Milvus shadow index. No Node.js, no MCP, no Web UI. Semantic search injects top-3 memories at prompt time. Cross-platform (Claude Code, OpenClaw, OpenCode, Codex CLI). |
| **claude-reflect** (BayramAnnakov) | 879 | Self-learning correction system | Captures corrections, positive feedback, preferences. Syncs to CLAUDE.md and AGENTS.md. |
| **pro-workflow** (rohitg00) | 1,551 | Self-correcting memory | Learns from corrections over 50+ sessions. Context engineering, parallel worktrees, agent teams, 17 skills. |

### Tier 2: Solid Tools (300-1000 stars)

| Tool | Stars | Description | Approach |
|------|-------|-------------|----------|
| **claude-code-workflow** (runesleo) | 536 | Battle-tested workflow template | Memory management, context engineering, task routing from 3 months of daily usage. |
| **napkin** (blader) | 470 | Mistake memory | Per-repo markdown scratchpad for persistent memory of mistakes. Simple, focused. |
| **vestige** (samvallad33) | 468 | Cognitive memory with spaced repetition | FSRS-6 algorithm, 29 brain modules, 3D dashboard, 22MB Rust binary. MCP server for Claude, Cursor, VS Code, Xcode, JetBrains. |
| **claude-cognitive** (GMaN1911) | 447 | Working memory | Persistent context and multi-instance coordination. |
| **claude-diary** (rlancemartin) | 353 | Simple diary system | Shell-based. Creates diary entries from conversation history. Reflect command analyzes patterns across entries and auto-updates CLAUDE.md. |

### Tier 3: Specialized (100-300 stars)

| Tool | Stars | Description |
|------|-------|-------------|
| **my-claude-code-setup** (centminmod) | 2,160 | Shared starter template + CLAUDE.md memory bank system |
| **ai-maestro** (23blocks-OS) | 590 | Agent orchestrator with memory search, code graph queries |
| **rulebook-ai** (botingw) | 588 | Universal managed template with memory bank |

---

## 5. Session Continuity Best Practices (Community Consensus)

### The Golden Rules

1. **Start fresh sessions per task** -- Don't let one session accumulate unrelated context
2. **Use `/clear` between unrelated tasks** within a session
3. **Compact proactively at 70% context** -- Don't wait for auto-compact
4. **Delegate research to subagents** -- Keep main session context clean
5. **Scope each task narrowly** -- The tighter the scope, the better the memory
6. **Never let a long session be your only record** -- Commit frequently, dump progress to files
7. **Treat every session as disposable** -- Anything important should be in CLAUDE.md or committed

### The Memory Injection Principle

**Key insight from the community**: Memory must be **injected at session start** rather than left as an on-demand tool. Every reliable solution pushes context into the session startup, not waiting for Claude to decide to search.

### What Actually Works (from user testing)

From "I tested 5 fixes" and "I tried 3 ways" articles:

1. **CLAUDE.md + Auto Memory** -- Built-in, zero maintenance, good baseline
2. **claude-mem** -- Best for comprehensive session capture and replay
3. **memsearch** -- Lightest weight, Markdown-first, no background services
4. **PreCompact hooks** -- Critical for saving state before compaction destroys context
5. **Session summaries to files** -- Manual but reliable; write a summary file at session end

### Context Engineering Structure

The difference between high-output engineers and everyone else is not prompt quality but the **structure built around Claude before execution begins**:

- CLAUDE.md with project rules
- Auto Memory accumulating preferences
- Hooks enforcing standards
- Session naming for easy resume
- Subagent delegation for research

---

## 6. Common Complaints and Solutions

### Top Complaints

1. **"Claude forgets everything between sessions"** -- The #1 complaint. Auto Memory helps but has a 200-line/25KB cap.
2. **"Context compaction loses important details"** -- PreCompact hooks are the solution.
3. **"CLAUDE.md rules are ignored"** -- They're advisory. Use hooks for enforcement.
4. **"Memory files are just grep"** -- True. Claude Code's built-in memory search is basic text matching, not semantic. This is why tools like claude-mem and memsearch add vector search.
5. **"200-line cap is too small"** -- For complex projects, 200 lines of MEMORY.md is insufficient. Plugins solve this by injecting relevant context dynamically.

### The 4-Layer Problem

As noted in "Claude Code's Memory: 4 Layers of Complexity, Still Just Grep and a 200-Line Cap":
- Layer 1: CLAUDE.md (static, user-maintained)
- Layer 2: MEMORY.md (auto, 200-line cap)
- Layer 3: Session history (lost on session end unless --continue/--resume)
- Layer 4: Context window (destroyed on compaction)

All 4 layers have limits. The community response has been to add a 5th layer: external persistent memory via plugins.

---

## 7. Recommendations for A.R.C.H.I.E.

### Current State Assessment

A.R.C.H.I.E. already has a sophisticated memory system:
- CLAUDE.md with comprehensive rules
- `.claude/rules/` directory with domain-specific rule files
- MEMORY.md index with 30+ memory files
- MCP tools for knowledge base search (22,000+ entries)
- Session handoff protocol

### What's Missing

1. **Automatic session capture** -- No hooks capturing what was done each session
2. **Semantic memory search at session start** -- MCP search is available but not auto-injected
3. **PreCompact preservation** -- No hook saving state before compaction
4. **Cross-session pattern learning** -- No automated extraction of recurring patterns

### Recommended Approach

**Option A: Lightweight (memsearch-style)**
- Add SessionStart hook to inject recent session summary
- Add PreCompact hook to save current work state
- Add SessionEnd hook to write session diary
- Keep using existing MCP knowledge base as the backend
- Estimated effort: 1-2 days

**Option B: Full Plugin (claude-mem)**
- Install claude-mem for comprehensive capture
- May conflict with existing hooks/plugins
- Adds background service overhead
- Estimated effort: 1 hour install, ongoing maintenance

**Option C: Custom Integration (Recommended for A.R.C.H.I.E.)**
- Build 3 hooks that talk to existing MCP knowledge base:
  - `SessionStart`: Query KB for recent session handoffs, inject into context
  - `PreCompact`: Save current work summary to KB
  - `SessionEnd`: Write session diary entry to KB
- Leverage existing 22K+ knowledge entries
- No new dependencies
- Fits the existing architecture
- Estimated effort: 2-3 days

---

## Sources

### Official Documentation
- [How Claude remembers your project](https://code.claude.com/docs/en/memory) -- Official memory docs
- [Hooks reference](https://code.claude.com/docs/en/hooks) -- Official hooks docs
- [Best Practices for Claude Code](https://code.claude.com/docs/en/best-practices) -- Official best practices
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) -- Architecture overview
- [Context engineering: memory, compaction, and tool clearing](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools) -- Anthropic cookbook

### Tools & Plugins
- [claude-mem](https://github.com/thedotmack/claude-mem) -- 45,602 stars, v11.0.0
- [memsearch](https://github.com/zilliztech/memsearch) -- 1,124 stars, Markdown-first
- [claude-diary](https://github.com/rlancemartin/claude-diary) -- 353 stars, shell-based
- [napkin](https://github.com/blader/napkin) -- 470 stars, mistake memory
- [vestige](https://github.com/samvallad33/vestige) -- 468 stars, spaced repetition
- [claude-reflect](https://github.com/BayramAnnakov/claude-reflect) -- 879 stars, self-correcting
- [pro-workflow](https://github.com/rohitg00/pro-workflow) -- 1,551 stars, workflow template
- [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) -- Curated plugin list

### Community Analysis
- [Claude Code's Memory: 4 Layers, Still Just Grep and a 200-Line Cap](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)
- [I tested 5 fixes for Claude Code forgetting](https://dev.to/hw20200214/claude-code-forgets-everything-between-sessions-i-tested-5-fixes-199p)
- [I tried 3 different ways to fix Claude Code's memory problem](https://dev.to/gonewx/i-tried-3-different-ways-to-fix-claude-codes-memory-problem-heres-what-actually-worked-30fk)
- [Auto Memory & PreCompact Hooks Explained](https://yuanchang.org/en/posts/claude-code-auto-memory-and-hooks/)
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) -- Anthropic's own guide
- [Inside Claude Code Architecture](https://www.penligent.ai/hackinglabs/inside-claude-code-the-architecture-behind-tools-memory-hooks-and-mcp/)
- [Persistent Memory Architecture for Claude Code](https://dev.to/suede/the-architecture-of-persistent-memory-for-claude-code-17d)
- [Claude Code Memory Management Complete Guide 2026](https://medium.com/data-science-collective/claude-code-memory-management-the-complete-guide-2026-b0df6300c4e8)
