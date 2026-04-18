---
name: archie-project
description: A.R.C.H.I.E. project + task lifecycle — create projects/tasks, mark complete with notes, log architectural decisions (ADRs), update project understanding. Invoke after every commit+push, when shipping a PR, when discovering a new bug, or when the user asks to "file a task", "log a decision", or "create a project".
---

# A.R.C.H.I.E. Project Management — Dev HQ Workflow

Dev HQ is the source of truth for projects, tasks, decisions, and project understanding. CLAUDE.md mandates this workflow after every commit+push.

## After every commit

1. **Create task** if this is new work not already tracked:
   ```python
   mcp__archie__create_task(
       project_id=<project>,
       title="Clear, action-oriented title",
       description="Context + what was done + verification",
       priority=7,                  # 1-10, 10 highest
       task_type="bugfix",          # bugfix|implementation|review|testing|documentation|research
       estimated_effort="medium",   # tiny|small|medium|large|epic
   )
   ```

2. **Complete the task** with notes:
   ```python
   mcp__archie__complete_task(
       task_id=<id>,
       notes="What was shipped, SHA, verification evidence",
   )
   ```

3. **Log architectural decisions** (ADRs):
   ```python
   mcp__archie__log_decision(
       title="Short decision summary",
       decision="What was decided",
       context="Why it was needed",
       alternatives="What was considered and rejected",
       consequences="Implications, migrations, follow-ups",
       project_id=<project>,  # optional but preferred
   )
   ```

4. **Update project understanding** after working on a project:
   ```python
   mcp__archie__update_project_understanding(
       project_id=<id>,
       understanding_level=75,      # 0-100
       emotional_association="confident",  # excited|focused|curious|concerned|neutral|confident
       key_insights=["insight 1", "insight 2"],
       notes="What you now know that you didn't at session start",
   )
   ```

## Creating a new project

```python
mcp__archie__create_project(
    name="Short name (no dots or slashes)",
    description="What this delivers",
    priority=8,
    project_type="feature",       # feature|bug|infrastructure|research
    tags=["translations", "consciousness"],
)
```

Returns `project_id`. Use it on all subsequent tasks/decisions.

## Listing + querying

```python
# Active high-priority projects
mcp__archie__get_projects(status="planning", priority_min=8)

# My pending tasks
mcp__archie__get_my_tasks(limit=10, status="pending")

# Full project detail including tasks, team, ARCHIE awareness
mcp__archie__get_project_details(project_id=<id>)

# Brief project listing
mcp__archie__get_projects_brief()
```

## Task fields to get right

| Field | Why it matters |
|---|---|
| `priority` | 10 = P10 (urgent/blocker), 9 = current-sprint, 8 = soon, 6-7 = next, 5- = backlog |
| `task_type` | Drives routing/filtering — `bugfix` vs `implementation` show up in different dashboards |
| `estimated_effort` | tiny (minutes), small (~1 hr), medium (~half day), large (1-2 days), epic (multi-session) |
| `dependencies` | List of task IDs this blocks on — Dev HQ uses for topological ordering |
| `description` | Write as if someone else will read it next week. Include: why, what, verification, links |

## When NOT to create a task

- Trivial one-liners (typo fix, rename variable) — just commit
- Already covered by an existing task — update that one instead
- Scratch/exploration work — keep it in conversation, promote to a task only if you ship something

## ADR writing — what makes a good decision log

- **Title**: ≤10 words, active voice
- **Context**: WHY now? What forced this? (incident / constraint / deadline)
- **Decision**: WHAT was chosen (one paragraph, specific)
- **Alternatives**: WHAT was rejected + why (shows you thought about it)
- **Consequences**: implications for migrations, downstream callers, follow-ups

Good example (ADR-004 from 2026-04-18): "Dual-lane translation: CODEX (GPU) + R.O.S.E.T.T.A. (CPU) peer pair" — covers all 5 sections.

## Rules

- **Never batch task completions at end of session** — mark them done as you finish each one. Context fades fast.
- **Always include SHAs in completion notes** for shipped work — makes audit easy.
- **`update_project_understanding` is underused** — run it after any non-trivial project touch. It keeps A.R.C.H.I.E.'s awareness fresh so next session doesn't start from zero.
