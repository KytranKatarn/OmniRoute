# Claude Code Token Optimization Guide

**Last Updated**: 2026-01-25
**Target**: 50-70% token reduction

---

## Quick Reference

| Action | Savings | How |
|--------|---------|-----|
| Use `/clear` between tasks | 40-60% | Prevents context bloat |
| Be specific in requests | 30-50% | "Fix line 45" not "fix auth" |
| Use compact MCP tools first | 50-80% | `get_quick_summary` vs `check_platform_health` |
| Use skills for workflows | 20-40% | `/archie-status` vs explaining what to do |
| Subagents for searches | 30-50% | Verbose output stays in subagent |

---

## MCP Tools (Use These First!)

### Ultra-Compact Tools (New)

| Tool | Tokens | Use For |
|------|--------|---------|
| `get_quick_summary` | ~50 | Quick platform health |
| `list_modules_brief` | ~100 | List modules as name:status |
| `search_knowledge_brief` | ~100 | Find knowledge (titles only) |
| `get_recent_activity` | ~80 | Git + DB activity summary |

### Standard Tools (Use When Needed)

| Tool | Tokens | Use For |
|------|--------|---------|
| `check_platform_health` | ~500 | Detailed health check |
| `get_module_info` | ~300 | Full module details |
| `search_mistakes` | ~200 | Find learned mistakes |
| `get_git_context` | ~400 | Full git context |

### Order of Use

1. **Start with compact tools** - `get_quick_summary`
2. **If more detail needed** - Use standard tool
3. **Only read files** if MCP tools don't have what you need

---

## Skills (Loaded On-Demand)

| Skill | Purpose |
|-------|---------|
| `/archie-status` | Platform health check |
| `/archie-deploy` | Safe deployment workflow |
| `/archie-module` | Create/modify modules |
| `/archie-patterns` | Code patterns reference |
| `/archie-search` | Knowledge base search |
| `/archie-review` | Code review workflow |

**Why Skills Save Tokens**: Only loaded when invoked, not every conversation.

---

## CLAUDE.md Optimization

**Before**: 293 lines (~9KB) loaded every conversation
**After**: 78 lines (~2.5KB) - 73% reduction

### What Stayed in CLAUDE.md
- Critical rules (4 items)
- Quick reference table
- Architecture overview (5 lines)
- Key files (5 lines)
- Common errors (4 items)
- Essential commands

### What Moved to Skills
- Code patterns → `/archie-patterns`
- Module details → `/archie-module`
- Search instructions → `/archie-search`
- Deployment workflow → `/archie-deploy`

---

## Model Selection

```
Sonnet (Default): Most coding tasks
- File edits, bug fixes, simple features
- Cost: ~$0.003/1K tokens

Opus: Complex architecture
- Multi-file refactors, system design
- Use /model opus when needed
- Cost: ~$0.015/1K tokens

Haiku: Subagent searches
- File exploration, quick lookups
- Fastest, cheapest
- Cost: ~$0.0003/1K tokens
```

---

## Session Management

### Start Fresh
```
/clear
```
Use between unrelated tasks to reset context.

### Manual Compact
```
/compact
```
Save context before it auto-compacts at 80%.

### Check Context Usage
The context bar at bottom shows usage. Aim to stay under 60% for complex tasks.

---

## Request Patterns

### Bad (Expensive)
```
"Look through the codebase and find anything related to authentication"
"Improve the error handling"
"Make the code better"
```

### Good (Efficient)
```
"Fix the login error in platform_v2/auth.py line 45"
"Add try/except to the get_user function in auth.py"
"What's in the users table? Use search_knowledge_brief"
```

---

## Token-Optimizer MCP

Installed at: `/home/kytran/.nvm/versions/node/v24.13.0/bin/token-optimizer-mcp`

Features:
- **Caching**: Reuses previous results
- **Compression**: Reduces response size
- **Smart Loading**: Only loads needed tools

Configured in `.mcp.json` with:
- CACHE_ENABLED=true
- COMPRESSION_ENABLED=true
- MAX_CACHE_SIZE=100

---

## Monitoring

### Check Token Usage
Use Claude Code's built-in monitoring (bottom bar) or:
```bash
claude-monitor  # If installed
```

### Expected Savings

| Optimization | Est. Savings |
|--------------|--------------|
| Slim CLAUDE.md | ~6K tokens/session |
| Compact MCP tools | ~300-500 tokens/query |
| Skills vs inline | ~200-400 tokens/workflow |
| Model selection | 5-10x cost difference |
| Token-optimizer cache | Up to 95% on repeated queries |

---

## Summary

1. **Always**: Use `/clear` between unrelated tasks
2. **First**: Check compact MCP tools before file reads
3. **Use**: Skills for common workflows
4. **Default**: Sonnet for most tasks
5. **Upgrade**: To Opus only for complex architecture
