# A.R.C.H.I.E. Session Save — Mid-Session Checkpoint

Quick-save your current session state without closing out. Like a game save point.

## What to do

1. **Commit uncommitted work** — Check `git status`. If there are staged/modified tracked files, commit them to the current branch with a descriptive message.

2. **Update session handoff** — Edit `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` with:
   - What was done so far this session
   - What's currently in progress
   - Any blockers or issues discovered
   - Key technical notes for continuity

3. **Store important memories** — If anything important was learned this session that should persist:
   - `mcp__archie__store_memory` for new knowledge
   - `mcp__archie__log_decision` for architectural choices
   - `mcp__archie__complete_task` for finished tasks

4. **Show session summary with context check** — Pull stats from the hook + check the context budget:

   ```bash
   bash /mnt/archie_brain/.claude/hooks/session-stats.sh | python3 -m json.tool
   ```

   Print:
   ```
   ## Session Checkpoint
   **Branch:** <current branch>
   **Commits this session:** <count>
   **Files changed:** <count>
   **Context:** <context_pct> % (<context_k> K / 1000 K)
   **Status:** <what's in progress>
   **Next:** <what to do next>
   ```

   **If context_pct ≥ 50 %:** add a banner and recommend closing instead of continuing:
   ```
   ⚠️  CONTEXT OVER 50% — quality degrades past this point.
   Recommend /archie-end to close cleanly and resume in a fresh session.
   ```

   If context_pct < 40 %: just continue — plenty of room.

5. **Continue working** — If context is healthy. If context_pct ≥ 50 %, STOP and let the user decide whether to push through or close.
