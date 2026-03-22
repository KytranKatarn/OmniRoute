# Cursor IDE & Local LLM Coding Assistants Research
**Date**: 2026-03-22 | **Depth**: Standard | **Researcher**: Claude Code

---

## 1. Cursor IDE Overview

### What It Is
Cursor is a full IDE built on VS Code with AI integrated directly into the editor workflow. Unlike GitHub Copilot (which adds AI to VS Code via extension), Cursor forked VS Code and rebuilt the editor around AI — every feature designed for AI-assisted development.

### Key Features
- **Tab Completion**: Context-aware autocomplete (better than Copilot)
- **Composer Mode**: Multi-file refactoring with up to 8 parallel agents
- **Deep Codebase Awareness**: Semantically indexes entire repositories
- **Chat Panel**: Ask questions about your codebase with file references
- **Auto Mode**: Automatically selects cost-efficient model (unlimited on Pro)
- **CLI (Jan 2026)**: Agent modes and cloud handoff from terminal
- **MCP Support**: Up to 40 tools, stdio/SSE/Streamable HTTP transports
- **Multi-model**: Switch between models per-request

### AI Models Supported
- Claude 4 Sonnet / Claude 4 Opus
- GPT-5 / GPT-4 Turbo
- Gemini 2.5 Pro / Flash
- Custom models via OpenAI-compatible API (including Ollama)

### Pricing (Post-June 2025 Overhaul)
| Plan | Price | Credits | Notes |
|------|-------|---------|-------|
| Hobby | Free | Limited | 50 slow premium requests |
| Pro | $20/mo | $20 credit pool | Unlimited Tab + Auto mode |
| Business | $40/mo | $40 credit pool | Admin dashboard, SSO, audit logs |
| Enterprise | Custom | Custom | Self-hosted option, SOC2 |

**Credit system**: Auto mode is unlimited and free. Manually selecting premium models (Claude Sonnet, GPT-4) draws from credit pool. ~225 Claude Sonnet requests or ~550 Gemini requests per $20.

**Controversy**: June 2025 pricing change caused backlash (users went from ~500 requests to ~225). Cursor issued public apology July 4, 2025.

### Self-Hosted Options
- **No self-hosted option** for Hobby/Pro/Business plans
- **Enterprise plan** offers self-hosted deployment (custom pricing)
- This is a significant limitation for security-sensitive environments

---

## 2. Open Source Cursor Alternatives

### Top Alternatives (Ranked)

#### Continue.dev (Best Overall)
- **Type**: VS Code / JetBrains extension (open-source)
- **License**: Apache 2.0
- **Key Features**: Autocomplete, chat, inline editing, agent mode
- **LLM Support**: Any model — Ollama, OpenAI, Anthropic, local, cloud
- **MCP Support**: Yes — stdio and SSE transports
- **Ollama Integration**: First-class support, pre-configured model blocks
- **Best For**: Developers who want to stay in VS Code with full model flexibility
- **URL**: https://continue.dev

#### Cline
- **Type**: VS Code extension (open-source)
- **License**: Apache 2.0
- **Key Features**: Full diff-based review, terminal access, browser automation
- **LLM Support**: Any model via API (Ollama, OpenAI, Anthropic, etc.)
- **MCP Support**: Yes
- **Best For**: Developers who want agent-style coding in VS Code with transparency
- **URL**: https://cline.bot

#### Aider
- **Type**: CLI tool (open-source)
- **License**: Apache 2.0
- **Key Features**: Git-integrated AI edits, scriptable, voice coding
- **LLM Support**: Ollama, OpenAI, Anthropic, any OpenAI-compatible API
- **MCP Support**: Limited (not primary focus)
- **Best For**: Terminal-native developers who want git-integrated AI edits
- **URL**: https://aider.chat

#### Void Editor
- **Type**: Standalone IDE (VS Code fork, open-source)
- **License**: MIT
- **Key Features**: Closest to Cursor's standalone experience
- **Status**: **Development paused** — features may be broken
- **Best For**: Those wanting a Cursor-like IDE without vendor lock-in
- **URL**: https://github.com/voideditor/void

#### Other Notable Projects
- **Tabby**: Self-hosted AI coding assistant with enterprise features
- **Supermaven**: Fast autocomplete (acquired by Cursor in 2024)
- **Codium/Qodo**: AI-powered test generation
- **avante.nvim**: Cursor-like experience for Neovim users

### There Is No "OpenCursor" Project
No project specifically called "OpenCursor" exists. The closest equivalent is Void Editor (VS Code fork with AI), but it's paused.

---

## 3. Best Local Coding Models (2025-2026)

### Tier 1: Flagship (Require 24GB+ VRAM or CPU offload)

| Model | Params | VRAM (Q4) | Notes |
|-------|--------|-----------|-------|
| **Qwen3-Coder** | 80B (3B active MoE) | ~20GB | Best free coding model, 256K context |
| **Qwen2.5-Coder 32B** | 32B | 22-24GB | Competitive with GPT-4o on Aider benchmarks |
| **DeepSeek-Coder-V2** | 236B MoE | 24GB+ | 300+ languages, state-of-the-art |
| **Codestral 22B** | 22B | ~16GB | Mistral's code model, permissive license |

### Tier 2: Mid-Range (8-16GB VRAM)

| Model | Params | VRAM (Q4) | Notes |
|-------|--------|-----------|-------|
| **Qwen2.5-Coder 14B** | 14B | ~10GB | Beats CodeStral-22B and DeepSeek-33B |
| **Qwen3-Coder 30B (A3B MoE)** | 30B (3B active) | ~8-10GB | Small MoE variant |
| **DeepSeek-Coder 6.7B** | 6.7B | ~5GB | Solid for its size |

### Tier 3: Fits 8GB VRAM

| Model | Params | VRAM (Q4) | Notes |
|-------|--------|-----------|-------|
| **Qwen2.5-Coder 7B** | 7B | ~5-6GB | Best 7B coding model |
| **StarCoder2 7B** | 7B | ~5GB | Good multi-language support |
| **CodeLlama 7B** | 7B | ~5GB | Meta's coding model |
| **Qwen3 8B** | 8B | ~6GB | General + coding |

### Hardware Compatibility for YOUR Setup

#### Hub: 128GB RAM + M4000 (8GB VRAM)
- **GPU inference**: Limited to 7-8B models (Qwen2.5-Coder 7B is best choice)
- **CPU inference**: Can run ANY model up to 70B+ using RAM (slow but works)
- **Qwen2.5-Coder 32B on CPU**: ~22GB RAM at Q4, feasible but slow (~5-15 tok/s)
- **Recommendation**: Run Qwen2.5-Coder 7B on GPU for speed, 32B on CPU for quality

#### Node .246: RTX 3070 (8GB VRAM) + 32GB RAM
- **GPU inference**: Same limit — 7-8B models max on GPU
- **CPU offload**: Can run 14B models with partial GPU offload
- **Recommendation**: Qwen2.5-Coder 7B on GPU, or 14B with layers split GPU/CPU

---

## 4. Cursor + Ollama Integration

### How It Works
Cursor supports connecting to local Ollama instances via OpenAI-compatible API, but with a significant workaround:

### Setup Steps
1. Install Ollama, pull desired model (`ollama pull qwen2.5-coder:7b`)
2. Run `ollama serve` (default: `http://localhost:11434`)
3. **Problem**: Cursor blocks direct localhost access for security
4. **Workaround**: Use ngrok to create tunnel: `ngrok http 11434`
5. In Cursor Settings > Models: enter model name + ngrok URL as API endpoint
6. Alternative: Use `llm-router` reverse proxy for model switching

### Limitations
- **No native Ollama support** — requires ngrok tunnel or reverse proxy
- **No GPU awareness** — Cursor doesn't know about your hardware
- **Quality gap** — local 7B models significantly worse than Claude/GPT-4
- **Tab completion** — local models are too slow for real-time autocomplete
- **Context window** — local models have smaller context than cloud models
- **No official support** — Cursor community forum shows ongoing requests for native Ollama

### For Your Network Setup
Since your Ollama runs on 192.168.1.200:11434, you could:
- Point Cursor to `http://192.168.1.200:11434/v1` as OpenAI-compatible endpoint
- This might work without ngrok since it's not localhost
- Model quality would be limited to what fits in 8GB VRAM

---

## 5. MCP (Model Context Protocol) Support

### Cursor MCP Support
- **Status**: Supported (tools only, not resources yet)
- **Limit**: Up to 40 tools from MCP servers
- **Transport**: stdio, SSE, Streamable HTTP
- **Config**: `.cursor/mcp.json` file (similar to `.mcp.json` for Claude Code)
- **One-click install**: Curated MCP server marketplace

### Your Existing MCP Tools Compatibility
Your `.mcp.json` has 78+ tools (Archie platform, design-systems, context-mode, etc.):
- **Compatible**: MCP servers using stdio transport would work in Cursor
- **Limitation**: Cursor caps at 40 tools — you'd need to choose a subset
- **Resource gap**: Cursor doesn't support MCP resources yet
- **Custom servers**: Your archie MCP server would need testing

### Continue.dev MCP Support
- Supports MCP servers via stdio and SSE
- No 40-tool limit documented
- Better for your use case with 78+ tools

### Cline MCP Support
- Full MCP support
- Used heavily with local models + MCP

---

## 6. Migration Considerations: Claude Code to Cursor

### What You Would LOSE

| Capability | Impact |
|-----------|--------|
| **Terminal-native workflow** | Cursor is GUI-first; CLI added Jan 2026 but less mature |
| **Deep autonomous refactoring** | Claude Code excels at multi-file, monorepo refactoring |
| **Token efficiency** | Claude Code uses 5.5x fewer tokens than Cursor for same tasks |
| **128GB RAM context** | Claude Code (Opus 4.6) has 1M token context window |
| **Docker/SSH integration** | Claude Code runs commands directly; Cursor needs terminal panel |
| **Full MCP tool access** | 78 tools vs Cursor's 40-tool cap |
| **No vendor lock-in on IDE** | Claude Code works in any terminal |
| **Cost predictability** | Max API subscription vs Cursor's credit depletion model |

### What You Would GAIN

| Capability | Impact |
|-----------|--------|
| **Tab completion** | Real-time code suggestions while typing (killer feature) |
| **Visual diff review** | Inline code changes with accept/reject |
| **VS Code ecosystem** | Extensions, themes, debugger integration |
| **Multi-model switching** | Use GPT-5, Claude, Gemini per-request |
| **Codebase indexing** | Semantic search across entire repo |
| **Lower cost floor** | $20/mo Pro vs variable Claude Code costs |
| **GUI comfort** | Better for visual learners and UI-oriented work |
| **Local LLM option** | Can use Ollama models (with limitations) |

### Recommended Strategy for A.R.C.H.I.E.

**Don't migrate — augment.** Use both tools for their strengths:

1. **Keep Claude Code** for:
   - Autonomous multi-file refactoring
   - Infrastructure/Docker/deployment tasks
   - MCP-heavy workflows (78 tools)
   - Complex debugging across platform_v2

2. **Add Continue.dev** (free, open-source) for:
   - Tab completion while coding
   - Quick inline edits
   - Local Ollama model usage (Qwen2.5-Coder 7B on GPU)
   - Full MCP support without tool limits

3. **Consider Cursor Pro** ($20/mo) only if:
   - You want the best tab completion experience
   - You're willing to deal with credit limits
   - You don't need more than 40 MCP tools

4. **Skip Void/Aider** — Void is paused, Aider overlaps with Claude Code

---

## Sources

### Cursor IDE
- [Models & Pricing | Cursor Docs](https://cursor.com/docs/models-and-pricing)
- [Cursor Pricing Explained 2026 | Vantage](https://www.vantage.sh/blog/cursor-pricing-explained)
- [Cursor AI Complete Guide 2026 | Local AI Master](https://localaimaster.com/tools/cursor-ai-complete-guide)
- [Cursor AI Review 2026 | NxCode](https://www.nxcode.io/resources/news/cursor-review-2026)
- [Cursor June 2025 Pricing Blog](https://cursor.com/blog/june-2025-pricing)

### Open Source Alternatives
- [10+ Best Open Source Cursor Alternatives | OpenAlternative](https://openalternative.co/alternatives/cursor)
- [Top 9 Cursor Alternatives | Cline](https://cline.bot/blog/top-9-cursor-alternatives-in-2025-best-open-source-ai-dev-tools-for-developers)
- [Open Source Cursor Alternatives 2026 | Scopir](https://scopir.com/posts/open-source-cursor-alternatives/)
- [Void Editor | GitHub](https://github.com/voideditor/void)

### Local Coding Models
- [Best Local AI Coding Models March 2026 | Local AI Master](https://localaimaster.com/models/best-local-ai-coding-models)
- [Best Local Coding Models Ranked 2026 | InsiderLLM](https://insiderllm.com/guides/best-local-coding-models-2026/)
- [Ollama VRAM Requirements 2026 | LocalLLM.in](https://localllm.in/blog/ollama-vram-requirements-for-local-llms)
- [5 Open-Source Coding LLMs 2026 | Labellerr](https://www.labellerr.com/blog/best-coding-llms/)

### Cursor + Ollama
- [Use Local LLM with Cursor and Ollama | DEV Community](https://dev.to/0xkoji/use-local-llm-with-cursor-2h4i)
- [Running Local LLMs for Cursor IDE | Chandpriyankara](http://www.chandpriyankara.com/2025/10/running-local-llms-for-cursor-ide-quick.html)
- [Running Local AI Models in Cursor | Medium](https://themeansquare.medium.com/running-local-ai-models-in-cursor-the-complete-guide-4290fe0383fa)
- [Ollama Native Support Request | Cursor Forum](https://forum.cursor.com/t/add-support-for-ollama-natively/27291)

### MCP Support
- [MCP | Cursor Docs](https://cursor.com/docs/context/mcp)
- [MCP Servers for Cursor | Cursor Directory](https://cursor.directory/plugins)
- [Using Ollama with Continue | Continue Docs](https://docs.continue.dev/guides/ollama-guide)
- [MCP Ollama Integration with Continue.dev | Medium](https://medium.com/@greg.witt625/mcp-ollama-server-integration-with-continue-dev-58811b637c94)

### Claude Code vs Cursor
- [Claude Code vs Cursor 2026 | Builder.io](https://www.builder.io/blog/cursor-vs-claude-code)
- [Claude Code vs Cursor | Northflank](https://northflank.com/blog/claude-code-vs-cursor-comparison)
- [Claude Code vs Cursor | Qodo](https://www.qodo.ai/blog/claude-code-vs-cursor/)
- [Testing AI Coding Agents 2025 | Render](https://render.com/blog/ai-coding-agents-benchmark)
- [Claude Code vs Cursor 2026 | NxCode](https://www.nxcode.io/resources/news/claude-code-vs-cursor-which-is-better-2026)
