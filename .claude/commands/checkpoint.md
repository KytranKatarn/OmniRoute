# Dev HQ Checkpoint

Perform a project checkpoint by following these steps in order:

## 1. Fetch Active Projects

Call `mcp__archie__get_projects_brief` to get all active projects. Present the list and select the most relevant one (prefer the project with the most recent activity or the one currently in-progress).

## 2. Get Project Details

Call `mcp__archie__get_project_details` with the selected project's ID. Display a summary to the user:

- **Project name** and **status**
- **Tasks completed** vs **tasks pending** (counts)
- **Last activity** timestamp and description

## 3. Ask the User Three Questions

Prompt the user with all three questions at once:

1. **What work was just completed?** — List any pending tasks from the project so the user can reference them by name or number. These will be marked done.
2. **Any architectural decisions to log?** — Briefly describe the decision, context, and rationale. Say "none" to skip.
3. **Any roadmap updates?** — New milestones, scope changes, or timeline shifts. Say "none" to skip.

Wait for the user's response before proceeding.

## 4. Execute Updates

Based on the user's answers:

- **Completed work**: For each task identified, call `mcp__archie__complete_task` with the task ID and a completion note.
- **Decisions**: For each decision, call `mcp__archie__log_decision` with the project ID, decision title, description, and rationale.
- **Roadmap updates**: For each update, call `mcp__archie__store_memory` with `knowledge_type: "vault_note"` and include `"roadmap"` in the tags array. Use the project name as context in the title.

## 5. Update Project Understanding

Call `mcp__archie__update_project_understanding` with the project ID and a brief summary of what was checkpointed (tasks completed, decisions logged, roadmap changes noted).

## 6. Confirm

Print a concise checkpoint summary showing what was recorded.
