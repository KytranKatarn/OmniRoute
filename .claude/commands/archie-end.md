# A.R.C.H.I.E. Session End — Full Close-Out Protocol

Complete end-of-session ritual. Saves everything, commits, provides a clean handoff. Pushes follow the rate-respect policy — not a blanket freeze.

## Step 0: GitHub Rate Check

Run `gh api /rate_limit` before any push. `core` remaining > 4,000 = safe. If below 1,000 or you see a 403 secondary-rate-limit today, hold pushes for 60 min.

## Step 1: Commit All Work + Push

```
1. Run `git status` — check for uncommitted changes
2. If changes exist: stage, commit with descriptive message
3. Push to current branch (respect rate-check from Step 0)
4. If the branch is ready for review, open a PR with gh pr create
5. If on a feature branch with a PR: note the PR number and status
6. Prefer batching several branches into a single PR where they share a theme
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
