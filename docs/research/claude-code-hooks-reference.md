# Claude Code Hooks System -- Research Report

**Date**: 2026-04-05 | **Depth**: Standard | **Status**: Complete

---

## 1. All Available Hook Events (21 total)

### Events supporting ALL 4 hook types (command, http, prompt, agent):

| Event | Matcher field | Description |
|-------|--------------|-------------|
| `PreToolUse` | tool_name (regex) | Fires before a tool call executes. Can block/allow/deny/modify input |
| `PostToolUse` | tool_name (regex) | Fires after a tool succeeds. Cannot undo actions |
| `PostToolUseFailure` | tool_name (regex) | Fires after a tool fails |
| `PermissionRequest` | tool_name (regex) | Fires when permission is requested. Can auto-allow/deny |
| `Stop` | stop_reason | Fires when Claude finishes responding (not just task completion) |
| `SubagentStop` | stop_reason | Fires when a subagent finishes |
| `TaskCompleted` | task_id | Fires when a task is completed |
| `TaskCreated` | task_id | Fires when a task is created |
| `UserPromptSubmit` | prompt (regex) | Fires before Claude processes user input. Can block prompts & inject context |

### Events supporting command + http hooks only (NOT prompt/agent):

| Event | Matcher field | Description |
|-------|--------------|-------------|
| `ConfigChange` | config_key | Fires on configuration changes. Can block changes |
| `CwdChanged` | new_cwd | Fires when working directory changes |
| `Elicitation` | elicitation_type | Fires on elicitation events |
| `ElicitationResult` | elicitation_type | Fires on elicitation results |
| `FileChanged` | file_path | Fires when a file changes on disk |
| `InstructionsLoaded` | instructions_type | Fires when CLAUDE.md or similar instructions load |
| `Notification` | notification_type | Fires when Claude Code sends a notification |
| `PermissionDenied` | tool_name | Fires when permission is denied |
| `PostCompact` | n/a | Fires after context compaction |
| `PreCompact` | n/a | Fires before context compaction |
| `SessionEnd` | reason (exit/sigint/error) | Fires when session ends |
| `StopFailure` | n/a | Fires on API errors. Output/exit code ignored |
| `SubagentStart` | agent_type | Fires when a subagent starts |
| `TeammateIdle` | teammate_id | Fires when a teammate becomes idle |
| `WorktreeCreate` | worktree_path | Fires when a worktree is created |
| `WorktreeRemove` | worktree_path | Fires when a worktree is removed |

### SessionStart (command hooks ONLY):

| Event | Matcher field | Description |
|-------|--------------|-------------|
| `SessionStart` | startup/resume/clear/compact | Fires on session init. ONLY `type: "command"` supported |

**SessionStart matchers:**
- `startup` -- new session
- `resume` -- `--resume`, `--continue`, or `/resume`
- `clear` -- `/clear`
- `compact` -- auto or manual compaction

---

## 2. Configuration Format

Hooks go in settings.json under the `"hooks"` key:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/script.sh",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "cat ~/.claude/session-context.txt"
          }
        ]
      }
    ]
  }
}
```

### Hook Locations (scope hierarchy):

| Location | Scope | Shareable |
|----------|-------|-----------|
| `~/.claude/settings.json` | All projects | No, local to machine |
| `.claude/settings.json` | Single project | Yes, committable |
| `.claude/settings.local.json` | Single project | No, gitignored |
| Managed policy settings | Organization-wide | Yes, admin-controlled |
| Plugin `hooks/hooks.json` | When plugin enabled | Yes, bundled with plugin |
| Skill/agent frontmatter | While component active | Yes, in component file |

---

## 3. Four Hook Handler Types

| Type | Description | Available on |
|------|-------------|-------------|
| `command` | Runs a shell command. Input via stdin JSON, output via exit codes + stdout | All events |
| `http` | POSTs JSON to a URL endpoint | All except SessionStart |
| `prompt` | Single-turn LLM evaluation (yes/no decision) | 9 events (see list above) |
| `agent` | Spawns a subagent with tool access (Read, Grep, Glob) | 9 events (see list above) |

### Common handler fields:
- `type` (required): `"command"`, `"http"`, `"prompt"`, or `"agent"`
- `if` (optional): Permission rule syntax filter, e.g. `"Bash(git *)"` or `"Edit(*.ts)"`
- `timeout` (optional): Max execution time in seconds (default 10 minutes)
- `async` (optional, command only): Run in background without blocking Claude

---

## 4. How Hooks Inject Context

### Method 1: stdout text (SessionStart)
Any text a SessionStart command writes to stdout is added directly to Claude's context:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [{ "type": "command", "command": "echo 'Always use rg instead of grep'" }]
      }
    ]
  }
}
```

### Method 2: JSON `systemMessage` field
Return JSON with `systemMessage` to inject a system-level message into the conversation:
```json
{"systemMessage": "Tests failed after editing file.ts: error details here"}
```

### Method 3: JSON `additionalContext` (PreToolUse)
PreToolUse hooks can inject additional context for Claude alongside allowing/denying:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "additionalContext": "Remember: this file uses tabs not spaces"
  }
}
```

### Context cap: 10,000 characters max per hook output injection.

---

## 5. Decision Control

### PreToolUse decisions:
- `"allow"` -- skip interactive permission prompt (deny rules still apply)
- `"deny"` -- cancel the tool call, send reason to Claude
- `"ask"` -- show permission prompt to user as normal
- `"defer"` -- exit process with tool call preserved (headless/SDK mode)
- `updatedInput` -- modify tool arguments before execution

### Other events (UserPromptSubmit, PostToolUse, Stop, etc.):
- `"block"` -- blocks the action
- Omit `decision` or exit 0 without JSON to allow

### Exit codes:
- **Exit 0**: Allow (or parse JSON for finer control)
- **Exit 2**: Block with stderr message shown to user
- Any other exit code: Hook error, ignored

---

## 6. Can Hooks Modify Claude's Behavior?

**YES, in several ways:**

1. **Block tool calls** (PreToolUse exit 2 or deny) -- forces Claude to use different tools
2. **Rewrite tool input** (PreToolUse `updatedInput`) -- modifies arguments before execution
3. **Inject context** (systemMessage, additionalContext, stdout) -- adds information Claude reads
4. **Block prompts** (UserPromptSubmit exit 2) -- prevents certain user inputs from being processed
5. **Block responses** (Stop with `"block"`) -- prevents Claude from finishing until conditions met
6. **Auto-approve permissions** (PermissionRequest allow) -- removes interactive prompts
7. **Re-inject context after compaction** (SessionStart compact) -- restores lost context

---

## 7. Settings.json Hooks vs Plugin Hooks

| Aspect | settings.json hooks | Plugin hooks |
|--------|-------------------|--------------|
| Location | `~/.claude/settings.json` or `.claude/settings.json` | `hooks/hooks.json` inside plugin dir |
| Scope | Global or per-project | Active only when plugin is enabled |
| Sharing | Commit `.claude/settings.json` to repo | Bundled with plugin package |
| Management | Edit JSON directly | Installed/uninstalled with plugin |
| Format | Identical JSON schema | Identical JSON schema |
| Override | Enterprise `allowManagedHooksOnly` can block all | Also blocked by that policy |

Skills and agents can also define hooks in their **frontmatter** -- these are active only while that skill/agent is running.

---

## 8. Practical Memory/Persistence Examples

### Auto-load context on every session start:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{
          "type": "command",
          "command": "cat /path/to/project-context.md && git log --oneline -5"
        }]
      }
    ]
  }
}
```

### Re-inject context after compaction:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [{
          "type": "command",
          "command": "echo 'CRITICAL: Always use bridge dispatcher. Never direct Ollama. User is REMOTE at 192.168.1.200.'"
        }]
      }
    ]
  }
}
```

### Persist environment variables via CLAUDE_ENV_FILE:
SessionStart hooks can write to `$CLAUDE_ENV_FILE` to set environment variables that persist across the entire session.

### Run async tests after file writes:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{
          "type": "command",
          "command": "/path/to/run-tests.sh",
          "async": true,
          "timeout": 300
        }]
      }
    ]
  }
}
```

### Auto-format on file write:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [{
          "type": "command",
          "command": "prettier --write $CLAUDE_FILE_PATHS"
        }]
      }
    ]
  }
}
```

### Block dangerous commands:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "command": "/path/to/validate-command.sh"
        }]
      }
    ]
  }
}
```

### Match MCP tools:
MCP tools follow naming `mcp__<server>__<tool>`. Use regex: `mcp__memory__.*` matches all memory server tools.

---

## 9. Common Input Fields (all events)

| Field | Description |
|-------|-------------|
| `session_id` | Current session identifier |
| `transcript_path` | Path to conversation JSON |
| `cwd` | Current working directory |
| `hook_event_name` | Which event triggered this hook |
| `tool_name` | (tool events) The tool being used |
| `tool_input` | (tool events) Arguments passed to the tool |
| `tool_response` | (PostToolUse) Result returned by the tool |
| `prompt` | (UserPromptSubmit) The user's input text |
| `source` | (SessionStart) startup/resume/clear/compact |
| `model` | (SessionStart) The model being used |

---

## Sources

- [Hooks Reference (official)](https://code.claude.com/docs/en/hooks)
- [Hooks Guide (official)](https://code.claude.com/docs/en/hooks-guide)
- [Plugins Reference (official)](https://code.claude.com/docs/en/plugins-reference)
- [claude-code-hooks-mastery (GitHub)](https://github.com/disler/claude-code-hooks-mastery)
- [everything-claude-code hooks/memory-persistence (GitHub)](https://github.com/affaan-m/everything-claude-code/tree/main/hooks/memory-persistence)
- [eesel.ai Claude Code hooks guide](https://www.eesel.ai/blog/hooks-in-claude-code)
- [claudefa.st session lifecycle hooks](https://claudefa.st/blog/tools/hooks/session-lifecycle-hooks)
- [SmartScope hooks guide](https://smartscope.blog/en/generative-ai/claude/claude-code-hooks-guide/)
