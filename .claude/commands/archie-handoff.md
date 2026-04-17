# A.R.C.H.I.E. Session Handoff — Show + Validate

Mid-session utility: display the current session handoff file and flag any staleness or missing fields. Useful for checking whether the handoff is actually ready for a clean close, without running the full /archie-end protocol.

## What to do

1. **Read the handoff**

   Read `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` in full.

2. **Display the current content** — print it verbatim so the user sees exactly what the next session will see first.

3. **Validate required fields** — check that the handoff has:
   - [ ] Status paragraph
   - [ ] Branches held table (or "none" explicit)
   - [ ] Session commits table (or "none" explicit)
   - [ ] Closed tasks list (or "none" explicit)
   - [ ] "For next session to start fresh" numbered section with concrete first actions
   - [ ] Date in H1 matches today (or explain why it shouldn't)

4. **Check staleness** — compare the handoff's `originSessionId` to the current session id (from `/mnt/archie_brain/.claude/hooks/session-stats.sh`). If different, the handoff is from a prior session and today's progress is not yet recorded.

5. **Report** — print a concise validation result:

   ```
   ## Handoff Status
   **File:** ~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md
   **Origin session:** <id> · **Current session:** <id> · **Match:** yes / no
   **Last updated (H1 date):** <date>
   **Required fields:** <N>/<required_count> present
   **Missing fields:** <list or "none">
   **Freshness:** current / stale / first-of-session
   ```

6. **Offer next action** — if stale or incomplete:
   - "Run `/archie-save` to refresh the handoff now"
   - "Run `/archie-end` when closing out"

## Notes

- This command does NOT modify any file.
- Read-only. Safe to run anytime.
- Useful before `/archie-end` to preview what next session will read, or before a context-heavy continuation to decide whether to save now.
