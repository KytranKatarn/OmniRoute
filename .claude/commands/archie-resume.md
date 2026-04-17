# A.R.C.H.I.E. Project Resume — Auto Phase Detection

Resume a phased project from where the last session left off. Automatically detects the active phase and loads the right context.

## Step 1: Find Active Phased Projects

Call `mcp__archie__get_projects` with `status: "active"` to get all active projects.

If no active projects, say: "No active projects found. Use `/archie-project` to create one or `/checkpoint` to activate an existing project."

## Step 2: Select Project

If one active project: select it automatically.
If multiple: present a numbered list and ask the user which to resume. Prefer the one with highest priority.

If the user provided an argument (e.g., `/archie-resume 217`), use that project ID directly.

## Step 3: Get Project State

Call `mcp__archie__get_project_details` with the selected project ID.

Analyze the tasks to determine the current phase:
- Group tasks by phase markers in titles (e.g., "Phase 1:", "Phase 2:", "P1:", "P2:", or numbered patterns)
- If no explicit phase markers, group by completion status: completed tasks = past phases, pending = current phase
- The **current phase** is the one with a mix of completed and pending tasks, or the first fully-pending group

## Step 4: Find the Implementation Plan

Search for plan files matching the project:

```
Glob: docs/superpowers/plans/*{project-slug}*.md
Glob: docs/superpowers/plans/*{keywords-from-project-name}*.md
Glob: docs/superpowers/plans/*{YYYY-MM-DD}*.md     # date-prefix, useful when plan was written recently
```

If the session handoff (Step 5) explicitly names the "active plan file" for the current work, use that path directly — it's more reliable than inferring from project slug. If multiple plans found via glob, select the one matching the current phase (e.g., "phase2" or "phase3" in filename).

If a plan is found, read it to extract the current phase's tasks with their step-by-step instructions.

## Step 5: Load Session Handoff

Read the session handoff file for additional context:
- `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md`

Extract the "What To Do Next" and "Key Context" sections.

## Step 6: Search Knowledge Base

Two searches:

1. **Project-scoped mistakes** — `mcp__archie__search_knowledge` with project name + current phase, types: ["mistake_learned"], limit: 5. Past failures on THIS project.

2. **Recent general corrections (always)** — `mcp__archie__search_knowledge` with query "correction mistake failure lesson learned", types: ["mistake_learned"], limit: 10. Cross-cutting patterns Claude has learned recently, regardless of project. Highest-value mistakes (like subagent audit failures, rules drift) apply everywhere.

Read both sets. Mention any that relate to today's task before starting work.

## Step 7: Present Resume Summary

Print a concise resume briefing:

```
## Resuming: [Project Name]

**Phase**: [Current Phase Number] — [Phase Name]
**Progress**: [X/Y tasks complete in this phase]
**Plan**: [path to plan file, or "no plan found"]

### Completed This Project
- [List completed tasks briefly]

### Current Phase Tasks (Pending)
- [ ] [Task title] — [one-line description]
- [ ] [Task title] — [one-line description]

### Context from Last Session
[Key points from session handoff]

### Mistakes to Avoid
[Any relevant mistake_learned entries]

**Ready to continue. Starting with: [first pending task in current phase]**
```

## Step 8: Offer Execution Mode

Ask the user:

> "How would you like to proceed?"
> 1. **Execute plan** — I'll work through tasks using subagent-driven development
> 2. **Review first** — Let me walk you through what's planned before we start
> 3. **Adjust scope** — Let's modify the plan before executing

Wait for the user's choice before proceeding.

## Notes

- This skill works for ANY phased project, not just ARCHIE Code CLI
- If there's no plan file, offer to create one using the writing-plans skill
- If the project has no phase structure, treat all pending tasks as "Phase: Current"
- Always run `/archie-boot` first if the session hasn't been initialized
