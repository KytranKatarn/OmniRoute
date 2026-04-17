# A.R.C.H.I.E. Session End — Full Close-Out Protocol

Complete end-of-session ritual. Saves everything, commits, provides a clean handoff. **Pushes are GATED on the GitHub Push Freeze** — see Step 0.

## Step 0: Check the GitHub Push Freeze

**If today is on or before 2026-04-30:** do NOT push, do NOT open PRs. Minutes cap is blown (even with Pro). Commit locally, register the branch in Repair Bay's Pending Push Queue (or the inventory table in `feedback_github-actions-minutes.md` if the panel isn't live yet), and hand off for May.

If today is on or after 2026-05-01, verify workflows are re-enabled (`gh workflow list --all`) before pushing. Push Repair Bay's queue in the listed order, one PR at a time.

## Step 1: Commit All Work (push-gated)

```
1. Run `git status` — check for uncommitted changes
2. If changes exist: stage, commit with descriptive message
3. If freeze is ACTIVE (≤2026-04-30): DO NOT push. Add/update the branch row in Repair Bay's Pending Push Queue.
4. If freeze is LIFTED (≥2026-05-01): push to current branch, open PR if applicable.
5. If on a feature branch with a PR: note the PR number and status.
```

## Step 2: Complete Dev HQ Tasks

```
1. `mcp__archie__complete_task` for any tasks finished this session
2. `mcp__archie__log_decision` for any architectural choices made
3. `mcp__archie__update_project_understanding` for projects worked on
```

## Step 3: Store Memories

```
1. `mcp__archie__store_memory` — any important learnings (use mistake_learned for errors)
2. Update MEMORY.md if new memory files were created
```

## Step 4: Update Session Handoff

Edit `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` with:
- Complete list of what was done
- Clear "first steps next session" with specific commands/actions
- Any blockers, critical issues, or debugging context
- Key technical notes (paths, IDs, gotchas)

## Step 5: Session Stats

Print a comprehensive session report:

```
## Session Complete

**Duration:** [start time] — [end time]
**Branch:** [branch name]
**Commits:** [count] ([files changed], +[insertions]/-[deletions])
**PR:** #[number] ([status])

### Completed
- [bullet list of what was done]

### Decisions Logged
- [ADR numbers and titles]

### For Next Session
1. [first priority]
2. [second priority]
3. [third priority]

**Plan tier:** Max 20x | **Session usage:** [if known]
```

## Step 6: Final Note

End with: "Session saved. Next session: start with `/archie-boot` or `/archie-resume`."
