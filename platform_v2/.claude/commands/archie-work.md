# A.R.C.H.I.E. Work Context Manager

Start, track, and finish work sessions. Keeps Claude CLI and ARCHIE in sync.

## Arguments
$ARGUMENTS - Command (e.g., "auth module", "status", "done", "note: fixed the bug")

## Quick Commands

| Command | Action |
|---------|--------|
| `[project name]` | Start working on project (creates if new) |
| (no args) | Show current work context |
| `done` | Finish session with auto-summary |
| `done: [summary]` | Finish with custom summary |
| `note: [text]` | Add quick note to session |
| `history` | Show recent work sessions |

## Usage Examples

### Start Working
```
/archie-work auth module
→ Creates/selects "auth module" project, sets as active context
```

### Check Status
```
/archie-work
→ Shows: current project, pending tasks, recent notes
```

### Add Notes During Work
```
/archie-work note: decided to use JWT instead of sessions
/archie-work note: blocker - need API key for auth provider
```

### Finish Session
```
/archie-work done: implemented login and logout endpoints
→ Closes session, logs summary, updates ARCHIE awareness
```

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `start_working_on` | Begin/resume work on project |
| `get_current_work` | Get active work context |
| `add_work_note` | Add note to session |
| `finish_working` | Complete session with summary |
| `set_current_file` | Track file being edited |
| `get_work_history` | View past sessions |

## Workflow

1. **Start**: `/archie-work [what you're building]`
2. **Work**: Make changes, add notes as needed
3. **Finish**: `/archie-work done: [what you accomplished]`

## Auto-Detection

When you say things like:
- "Let's build the auth module" → Starts work session
- "I'm working on the dashboard" → Starts work session
- "Let's continue on the API" → Resumes matching project

## Benefits

- **Persistent Context**: Comes back after `/clear` or new session
- **Shared with ARCHIE**: Web UI sees same active work
- **Decision Tracking**: Notes become project history
- **Progress Visible**: Team members see what's being worked on

## Database Tables

- `work_sessions` - Active/completed work sessions
- `work_notes` - Notes during sessions
- `unified_projects` - Projects being worked on
- `project_activity` - Activity feed

## Tips

1. Start each work session with `/archie-work [topic]`
2. Add notes for important decisions or blockers
3. Always finish with `/archie-work done` to log progress
4. Use `/archie-work history` to see previous work
