---
name: archie-work
description: Start, track, and close a focused work session on a specific A.R.C.H.I.E. project or task. Invoke when the user says "let's work on X", "start working on", "I'm working on the Y feature" — or when beginning a multi-step implementation that should show up in the platform's activity feed and Dev HQ awareness.
---

# A.R.C.H.I.E. Work Session Tracking

Complements `/archie-project` — that one handles lifecycle events (create/complete/decide). This one tracks the *active work* between those events so A.R.C.H.I.E. knows what's in flight, what was touched, and what the session accomplished.

## Start a work session

```python
mcp__archie__start_working_on(
    topic="Translation coverage bug investigation",
    project_id=232,                    # optional but preferred
    task_id=2099,                      # optional
    expected_duration_minutes=90,      # optional estimate
)
```

Returns a `work_session_id`. Stores it in activity feed, surfaces in Consciousness → Dev HQ, and makes A.R.C.H.I.E. aware you're on this track (used for emotional-state proximity scoring).

## Mid-session notes

As you discover things, record them — same pattern as a lab notebook:

```python
mcp__archie__add_work_note(
    session_id=<id>,
    note="Found root cause: agent_budgets counter never decrements",
    note_type="finding",    # finding|decision|blocker|next-step
)
```

Note types drive downstream filtering:
- **finding** — surfaces in post-session summary + KB
- **decision** — auto-promotes to `log_decision` candidate
- **blocker** — flags for escalation if unresolved > 30min
- **next-step** — rolls over to the next session's briefing

## Close the session

```python
mcp__archie__finish_working(
    session_id=<id>,
    outcome="completed",       # completed|paused|blocked|abandoned
    summary="What was accomplished, what's left, links to commits/PRs",
)
```

Generates a conversation_memory entry auto-searchable next session.

## Related activity queries

```python
mcp__archie__get_current_work()        # what am I on right now
mcp__archie__get_work_history(days=7)  # what did I do this week
mcp__archie__get_activity_feed(limit=20)  # platform-wide activity incl. agents
```

## When to start a session vs. just code

| Skip it | Use it |
|---|---|
| Quick one-liner fix | Multi-hour investigation |
| Reading code | Implementing a feature |
| Debugging via REPL | Shipping a PR |
| Already inside a session | Switching to a new topic |

## Pairs with

- `/archie-project` — the task you're working on
- `/archie-search` — recall past work on the same topic (often better than starting fresh)
- `/archie-status` — gut-check the platform before starting deep work

## Rules

- One active session at a time — switch topics via `finish_working` then `start_working_on`.
- **Don't let sessions hang open overnight** — auto-close with outcome=paused if you need to step away mid-task.
- The `summary` field is what future-you will read on `recall_context` — spend 30 seconds on it, not 3.
