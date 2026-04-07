---
name: mcp-reload
description: Reload MCP servers after .mcp.json config changes. Use when MCP config was edited, an MCP server isn't working, MCP tools are missing, or you need to restart MCP connections. Also use when the user says "reload mcp", "restart mcp", "mcp not working", or "fix mcp".
---

# MCP Server Reload

Claude Code does not support hot-reloading MCP servers. When `.mcp.json` changes, a session restart is required. This skill ensures no work is lost during the restart.

## Step 1: Verify the Change

Show the user what changed in `.mcp.json`:

```bash
git diff .mcp.json
```

If there's no git diff (file isn't tracked or was just created), read and summarize the current `.mcp.json` config for the MCP server in question.

Confirm with the user: "This is the MCP change — looks correct?"

## Step 2: Save Session Context

Before restarting, preserve the current work state so the next session can pick up seamlessly.

1. **Update session handoff** — Write to `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`:
   - What was being worked on
   - Why the MCP reload is needed
   - What to do immediately after restart (e.g., "test chrome-devtools MCP", "verify new tool is available")
   - Any uncommitted changes that need attention

2. **Commit if needed** — If there are meaningful uncommitted changes beyond `.mcp.json`, offer to commit them first.

## Step 3: Give Restart Instructions

Tell the user:

> **MCP config updated. To reload, you need to restart this session.**
>
> 1. Type `/exit` or press `Ctrl+C` to end this session
> 2. Run `claude` to start a new session
> 3. The new session will load the updated MCP config automatically
> 4. Run `/archie-resume` to pick up where we left off
>
> Your work context has been saved to the session handoff file.

## Step 4: Post-Restart Verification (for the next session)

After restart, verify the MCP server is working:

1. Call any tool from the reloaded MCP server to confirm connectivity
2. If it fails, check:
   - Is the MCP command installed? (`which <command>` or `npx <package> --help`)
   - Are environment variables set correctly?
   - Does it need `--no-sandbox` or other platform flags?
   - Check `~/.claude/logs/` for MCP connection errors
3. If 2 attempts fail, show the user the error and ask how to proceed

## Common MCP Fixes

| Problem | Fix |
|---------|-----|
| "Missing X server" | Add `--headless` and `--no-sandbox` Chrome flags |
| "command not found" | Install the package: `npm i -g <package>` or use `npx` |
| "ECONNREFUSED" | Check if the service is running on the expected port |
| "timeout" | Increase timeout or check network connectivity |
| Tool missing after restart | Verify tool name in `.mcp.json` matches server's exposed tools |
