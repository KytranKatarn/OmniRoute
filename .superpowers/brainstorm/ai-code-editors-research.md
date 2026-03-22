# Open-Source AI Code Editors & CLI Tools -- Research Report
**Date**: 2026-03-22 | **Depth**: Standard | **Status**: Complete

---

## 1. Comprehensive Tool Comparison

| Tool | License | Ollama/Local? | MCP Support? | Interface | Stars | Active? | Claude Code Parity |
|------|---------|---------------|--------------|-----------|-------|---------|-------------------|
| **OpenCode** | MIT | Yes (native) | Yes (stdio+HTTP) | CLI/TUI (Go) | ~120K | Very active (800+ contributors) | HIGH -- closest CLI equivalent |
| **Aider** | Apache 2.0 | Yes (ollama_chat/ prefix) | Via MCP server (pip install aider-mcp) | CLI (Python) | ~75K+ | Very active | HIGH -- git-native, multi-file |
| **Cline** | Apache 2.0 | Yes (Ollama/LM Studio) | Yes (best-in-class MCP) | VS Code extension | ~57K | Very active (v3.66, 4M+ installs) | HIGH -- autonomous agent in IDE |
| **Continue.dev** | Apache 2.0 | Yes (native) | Yes (MCP context provider) | VS Code / JetBrains | ~25K+ | Very active | MEDIUM -- autocomplete + chat, less agentic |
| **Void Editor** | MIT (YC-backed) | Yes (native) | Yes (native) | Standalone IDE (VS Code fork) | ~15K+ | PAUSED -- exploring new ideas | MEDIUM -- agent mode exists but dev paused |
| **OpenHands** | MIT | Yes (Ollama, needs 22K ctx) | Partial (tool use) | Web UI + CLI | ~68K | Very active ($18.8M Series A) | HIGH -- full autonomous agent |
| **Tabby** | Apache 2.0 | Yes (via API) | Yes (MCP server plugin) | VS Code / JetBrains / Vim | ~25K+ | Active | LOW -- autocomplete focused, no agentic editing |
| **Zed** | GPL v3 + AGPL | Yes (auto-discovers Ollama) | Yes (native MCP) | Standalone IDE (Rust) | ~55K+ | Very active | MEDIUM -- agent mode with file/terminal access |
| **Windsurf** | Proprietary (Cognition AI) | Limited (custom endpoints) | Yes (MCP servers) | Standalone IDE (VS Code fork) | N/A (proprietary) | Active (acquired by Cognition) | HIGH -- but NOT open source, $15/mo |
| **Codium/Cody** | Apache 2.0 (Sourcegraph) | Via custom endpoints | Yes | VS Code | ~25K+ | Active (rebranded to Amp) | MEDIUM -- context-aware but less agentic |

### Not Found
- **"OpenCursor"**: No project by this exact name exists. The open-source Cursor alternatives are Void Editor, Zed, and Cline. Void is the most direct VS Code-fork equivalent.

---

## 2. Best Local Coding Models (March 2026)

### Fits in 8GB VRAM (M4000 territory)

| Model | Size (disk) | VRAM (Q4_K_M) | Best For | HumanEval | Notes |
|-------|-------------|---------------|----------|-----------|-------|
| **Qwen 2.5 Coder 7B** | ~4.5GB | ~4.2GB | Autocomplete/FIM | 88.4% | KING of autocomplete at 8GB. Best FIM model period. |
| **Qwen3 8B** | ~5GB | ~5GB | Chat, debugging, code review | ~85% | Good general reasoning + coding |
| **DeepSeek R1 0528 Qwen3 8B** | ~5GB | ~5GB | Reasoning-heavy tasks | ~83% | Slow (chain-of-thought) but thorough |
| **NVIDIA Nemotron Nano 9B** | ~5.5GB | ~5.5GB | Coding tasks | ~86% | Strong coding benchmark scores |
| **Llama 3.1 8B** | ~4.7GB | ~4.5GB | General coding | ~78% | Good all-rounder, large community |
| **Mistral 7B** | ~4.1GB | ~4GB | General coding | ~72% | Fast inference, decent quality |
| **DeepSeek Coder V2 Lite** | ~5GB | ~5GB | Reasoning + code | ~80% | MoE architecture, efficient |

### Needs More VRAM / CPU-only for Hub (128GB RAM)

| Model | Size (disk) | RAM needed (CPU) | Best For | Notes |
|-------|-------------|-----------------|----------|-------|
| **Qwen3-Coder 30B-A3B** | ~18GB | ~20GB | Full agentic coding | MoE, only 3B active params. Top local agent model. |
| **DeepSeek Coder V2 (236B)** | ~130GB | ~140GB | Maximum quality | Needs your full 128GB RAM. Slow but best local quality. |
| **Devstral Small 2 (24B)** | ~14GB | ~16GB | Agentic coding | Recommended by OpenHands for local use |
| **Qwen 2.5 Coder 32B** | ~18GB | ~20GB | Agentic + autocomplete | Best balance of quality and speed for CPU |
| **Codestral 22B** | ~13GB | ~15GB | Code generation | Mistral's coding model, strong FIM |

### Recommended Strategy for A.R.C.H.I.E. Hub (M4000 8GB VRAM, 128GB RAM)

1. **GPU slot**: Qwen 2.5 Coder 7B (autocomplete/FIM) -- 4.2GB VRAM, fast inference
2. **CPU primary**: Qwen3-Coder 30B-A3B (agentic tasks) -- MoE, only ~20GB RAM
3. **CPU secondary**: Qwen 2.5 Coder 32B (complex multi-file edits) -- ~20GB RAM
4. **Node .246 (RTX 3070 8GB)**: Same GPU model + can run 14B models in VRAM

---

## 3. Can These Tools Replicate Claude Code?

### What Claude Code Does
- Autonomous multi-file editing with planning
- Terminal command execution
- Git integration (commits, diffs)
- Web search and documentation lookup
- MCP server integration
- Context-aware codebase understanding
- Interactive approval workflow

### Replication Assessment

| Capability | OpenCode | Aider | Cline | OpenHands | Zed |
|-----------|----------|-------|-------|-----------|-----|
| Multi-file editing | Yes | Yes | Yes | Yes | Yes |
| Terminal execution | Yes | Limited | Yes | Yes (sandboxed) | Yes |
| Git integration | Yes | Yes (auto-commit) | Via terminal | Yes | Via terminal |
| Planning/reasoning | Model-dependent | Model-dependent | Model-dependent | Yes (built-in) | Model-dependent |
| MCP servers | Yes | Via aider-mcp | Yes (best) | Partial | Yes |
| Web browsing | No | No | Yes (browser) | Yes (browser) | Yes (web search) |
| Approval workflow | Yes | Yes (confirm) | Yes (per-action) | Yes (configurable) | Yes |
| Codebase search | Yes (LSP) | Yes (repo map) | Yes (file search) | Yes | Yes (native) |

### Verdict

**OpenCode** is the closest open-source CLI equivalent to Claude Code. It has:
- 75+ provider support including Ollama
- Full agentic workflow (file edit, bash, search)
- MCP support (stdio + HTTP)
- TUI interface similar to Claude Code
- 120K+ stars, massive community
- Session persistence (SQLite)

**Aider** is the best for pure git-integrated pair programming. Its repo-map feature gives excellent codebase awareness, and auto-commits are a standout feature. Less "agentic" than Claude Code but more focused.

**Cline** is the best if you want to stay in VS Code. Its MCP support is the deepest of any tool, and the approval workflow mirrors Claude Code's approach. 4M+ installs prove production readiness.

**OpenHands** is the most autonomous -- it can run full development tasks end-to-end with browser, terminal, and file access. Best for "give it a task and walk away" workflows. The V1 SDK (coming April 2026) removes mandatory Docker.

### Critical Caveat: Model Quality Matters

All these tools are only as good as the model behind them. With Ollama local models:
- **7-8B models**: Good for autocomplete, simple edits. Struggle with multi-file planning.
- **30-32B models** (CPU): Approaching usable for agentic tasks. Qwen3-Coder 30B-A3B is the sweet spot.
- **70B+ models**: Near cloud quality but need 64GB+ RAM and are slow.
- **Cloud models via API**: Still significantly better for complex autonomous coding.

For A.R.C.H.I.E.'s use case (128GB RAM hub), Qwen3-Coder 30B-A3B via Ollama + OpenCode or Aider would give the best local-only experience. For maximum capability, using Claude/GPT API keys with these tools matches or exceeds Claude Code for most tasks.

---

## 4. Quick-Start Recommendations

### For A.R.C.H.I.E. Platform Integration

1. **Install OpenCode**: `go install github.com/opencode-ai/opencode@latest` or `curl -fsSL https://opencode.ai/install | bash`
   - Configure with Ollama backend pointing to 192.168.1.200:11434
   - Add your existing MCP servers from `.mcp.json`

2. **Install Aider**: `pip install aider-chat`
   - Run: `aider --model ollama_chat/qwen2.5-coder:32b`
   - Set context: `--map-tokens 4096` for repo awareness

3. **Pull recommended models**:
   ```bash
   ollama pull qwen2.5-coder:7b      # GPU autocomplete (4.2GB)
   ollama pull qwen3-coder:30b-a3b   # CPU agentic (20GB)
   ollama pull qwen2.5-coder:32b     # CPU complex edits (20GB)
   ```

---

## Sources

- [OpenCode CLI Guide 2026](https://yuv.ai/learn/opencode-cli)
- [OpenCode GitHub](https://github.com/opencode-ai/opencode)
- [Aider Ollama Docs](https://aider.chat/docs/llms/ollama.html)
- [Aider MCP Server](https://github.com/disler/aider-mcp-server)
- [Cline GitHub](https://github.com/cline/cline)
- [Cline Ollama Docs](https://docs.cline.bot/running-models-locally/ollama)
- [Cline vs Cursor 2026](https://serenitiesai.com/articles/cline-vs-cursor-2026)
- [Continue.dev Ollama Guide](https://docs.continue.dev/guides/ollama-guide)
- [Continue MCP Setup](https://docs.continue.dev/customize/deep-dives/mcp)
- [Void Editor](https://voideditor.com/)
- [OpenHands Docs](https://docs.openhands.dev/openhands/usage/llms/local-llms)
- [OpenHands GitHub](https://github.com/All-Hands-AI/OpenHands)
- [Tabby ML](https://github.com/TabbyML/tabby)
- [Zed AI Docs](https://zed.dev/docs/ai/overview)
- [Zed Ollama Integration](https://docs.ollama.com/integrations/zed)
- [Windsurf](https://windsurf.com/)
- [Best Local Coding Models 2026](https://insiderllm.com/guides/best-local-coding-models-2026/)
- [Best LLMs for 8GB VRAM](https://localllm.in/blog/best-local-llms-8gb-vram-2025)
- [Local Alternatives to Claude Code](https://insiderllm.com/guides/local-alternatives-claude-code-2026/)
- [Claude Code Alternatives](https://www.digitalocean.com/resources/articles/claude-code-alternatives)
- [Open Source Cursor Alternatives](https://openalternative.co/alternatives/cursor)
- [OpenCode vs Claude Code](https://www.openaitoolshub.org/en/blog/opencode-vs-claude-code)
