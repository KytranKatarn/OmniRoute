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

   **Context-budget phases** (calibrated from session 14, 2026-04-17):

   | Range | Mode | Banner |
   |-------|------|--------|
   | 0-70 % | Design + build | none — keep going |
   | 70-80 % | Slow-down (patch, polish, fix) | 🟡 Stop new design. Prepare to ship. |
   | 80-90 % | Ship (PRs, pushes, commits only) | 🔴 Wrap up. No new design. |
   | 90 %+ | Emergency | 🔴🔴 /archie-end NOW |

   Print the banner matching the current band. Session 14 demonstrated that high-quality work continues well into the 60s — the old "50 % CRITICAL" rule cut sessions short.

5. **Continue working** — Under 70 %: freely. 70-80 %: only finishing/patching work already in flight; no new architecture. 80-90 %: ship what you have and close. 90 %+: stop.
