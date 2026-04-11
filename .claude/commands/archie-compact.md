# A.R.C.H.I.E. Compact — Context-Aware Memory Compression

Safely compress the conversation context while preserving critical state. Use when the conversation feels heavy or before a long implementation stretch.

## Step 1: Save State Before Compact

Before triggering compact, capture the current working state:

1. Run `bash /mnt/archie_brain/.claude/hooks/session-stats.sh` — get session metrics
2. Note the current state:
   - Branch name and uncommitted changes (`git status --short`)
   - What task is currently in progress
   - Any critical context that would be lost

3. Print a brief state summary:
```
Pre-compact state:
- Branch: [name]
- Task: [what's in progress]
- Uncommitted: [Y/N]
- Session: [messages] msgs, [commits] commits, [elapsed]
```

## Step 2: Commit Uncommitted Work

If there are uncommitted changes, commit them now so nothing is lost during compression.

## Step 3: Write Compact Summary

Write a concise summary of what's been done and what's next to help post-compact context:

```
## Post-Compact Context

### This Session So Far
[2-3 bullet points of major accomplishments]

### Currently Working On
[What was in progress when compact was triggered]

### Key Files Modified
[List of files touched this session]

### Next Steps
[What to do immediately after compact]
```

## Step 4: Trigger Compact

Tell the user: "State saved. Run `/compact` now, then tell me what you'd like to continue with."

## Important Notes
- Compact is a Claude Code built-in — it compresses conversation history
- The session handoff file persists across compacts (it's on disk)
- Git history persists across compacts
- After compact: read session handoff + check git log to restore context
