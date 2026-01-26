# A.R.C.H.I.E. Project Management

Manage projects, tasks, and documentation using the unified project system.

## Arguments
$ARGUMENTS - Action and parameters (e.g., "list", "create Feature X", "tasks 5")

## Quick Commands

| Command | Description |
|---------|-------------|
| `list` | List all active projects |
| `create [name]` | Create new project |
| `show [id/slug]` | Show project details |
| `tasks [project_id]` | List project tasks |
| `add-task [project_id] [title]` | Add task to project |
| `complete [task_id]` | Mark task complete |
| `decide [title]` | Log architectural decision |

## MCP Tools Available

### Project Management
- `get_projects` - List projects (filter by status/type)
- `get_projects_brief` - Ultra-compact project list (~100 tokens)
- `get_project_details` - Full project info (tasks, team, docs)
- `create_project` - Create new project
- `update_project_status` - Update status/priority

### Task Management
- `get_my_tasks` - Get tasks (filter by project/status)
- `create_task` - Create task in project
- `complete_task` - Mark task done

### Documentation
- `get_project_docs` - Get project documentation
- `log_decision` - Log architectural decision (ADR)

### Team & Activity
- `get_project_team` - List project team members
- `get_activity_feed` - Recent activity feed

### Consciousness (Self-Awareness)
- `log_config_change` - Record configuration change
- `get_config_history` - View config change history
- `update_project_understanding` - Update ARCHIE's project awareness

## Workflow Examples

### Start New Feature
```
1. create_project(name="Feature: User Auth", project_type="feature", priority=8)
2. create_task(project_id=X, title="Design auth flow", task_type="research")
3. create_task(project_id=X, title="Implement login", task_type="implementation")
4. log_decision(project_id=X, title="Use JWT tokens", decision="JWT for stateless auth", context="Need scalable auth")
```

### Daily Standup
```
1. get_projects_brief() - Quick overview
2. get_my_tasks(status="in_progress") - What's being worked on
3. get_activity_feed(limit=10) - Recent changes
```

### Complete Work
```
1. complete_task(task_id=X, notes="Implemented with tests")
2. update_project_understanding(project_id=Y, understanding_level=85, notes="Core functionality complete")
3. log_config_change(config_type="module", change_type="modified", config_path="...", change_reason="...")
```

## Token Efficiency Tips

1. **Use `get_projects_brief` first** - Only ~100 tokens
2. **Filter by status** - `get_my_tasks(status="pending")` instead of all
3. **Use brief mode** - `get_project_docs(project_id=X, brief=True)`

## API Endpoints (Web UI)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/project-manager/api/projects` | GET | List projects |
| `/tools/project-manager/api/projects` | POST | Create project |
| `/tools/project-manager/api/projects/<id>` | GET | Get project details |
| `/tools/project-manager/api/projects/<id>/tasks` | GET | List project tasks |
| `/tools/project-manager/api/tasks` | POST | Create task |
| `/tools/project-manager/api/decisions` | POST | Log decision |
| `/tools/project-manager/api/config-history` | GET | Config history |

## Database Tables

- `unified_projects` - Projects
- `unified_tasks` - Tasks
- `project_documents` - Versioned docs
- `project_decisions` - ADRs
- `project_team` - Team assignments
- `project_activity` - Activity feed
- `archie_project_awareness` - ARCHIE's project understanding
- `archie_config_history` - Configuration changes
