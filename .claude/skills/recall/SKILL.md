---
name: recall
description: Full context restore — reads handoff, git state, active tasks, and current fire. Run when resuming work or when context feels lost.
---

# /recall — Full Context Restore

Run this immediately. No preamble. Output the full state.

## Step 1: Read the handoff

Read `/home/kytran/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` — first session entry only (top to first `---`).

Extract and output:
- **Status** (one line: what is broken RIGHT NOW)
- **Next 3-5 actions** (verbatim from handoff)
- **Files touched last session**
- **Outstanding unfixed items**

## Step 2: Read git state

Run: `cd /mnt/archie_brain && git status --short && git log --oneline -5`

Output:
- **Current branch**
- **Modified files** (staged + unstaged)
- **Last 5 commits**

## Step 3: Load active tasks

Call `mcp__archie__get_my_tasks(status='in_progress')` and `mcp__archie__get_my_tasks(status='pending', limit=5)`

Output: task names + IDs only, one line each.

## Step 4: Output the summary block

Format:

```
## RECALL SUMMARY — [timestamp]

BRANCH: <branch>
MODIFIED: <files>

CURRENT FIRE: <one line>

NEXT ACTIONS:
1. <action>
2. <action>
3. <action>

OPEN TASKS: <count> in_progress, <count> pending

OWNER: kytran@kytranempowerment.com (email+password; SSO removed) — gmail is the BACKUP Google account for external sign-ins, admin@ is for agents only
```

## Hard rule

Do NOT ask clarifying questions after this. The handoff is the source of truth.
If the handoff is >7 days old, say so and ask Kytran what changed.
