# A.R.C.H.I.E. MCP Server Reference

**Version:** 1.0.0 (Phase 50 Complete)
**Date:** January 21, 2026
**Protocol:** Model Context Protocol (MCP)
**Transport:** stdio

---

## Overview

The A.R.C.H.I.E. MCP Server exposes platform capabilities as Model Context Protocol (MCP) tools for AI model integration. It enables Claude Code, Goose, and other MCP-compatible clients to interact with the A.R.C.H.I.E. platform.

### Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     MCP Client (Claude Code)                    │
└─────────────────────────────┬──────────────────────────────────┘
                              │ stdio (JSON-RPC)
                              ▼
┌────────────────────────────────────────────────────────────────┐
│                    A.R.C.H.I.E. MCP Server                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │Knowledge │  │ Creation │  │ Business │  │    Admin     │   │
│  │ 6 tools  │  │ 6 tools  │  │ 7 tools  │  │   8 tools    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
│                    ┌──────────────────┐                        │
│                    │    Advanced      │                        │
│                    │    12 tools      │                        │
│                    └──────────────────┘                        │
└─────────────────────────────┬──────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│                      archie_bridge                              │
│  • Task routing      • Internal staff first                    │
│  • Contractor approval • HR/IAAE logging                       │
└─────────────────────────────┬──────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌──────────────────────┐       ┌──────────────────────────────┐
│ Internal Staff (FREE)│       │ Contractors (Approval Req.)  │
│ 60 Ollama agents     │       │ Claude, GPT-4, Grok, Gemini  │
└──────────────────────┘       └──────────────────────────────┘
```

---

## Installation & Configuration

### Claude Code Integration

Add to `.claude/settings.local.json`:

```json
{
  "mcpServers": {
    "archie": {
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/mnt/archie_brain/platform_v2",
      "env": {
        "DB_HOST": "archie_database",
        "DB_NAME": "archie",
        "DB_USER": "archie",
        "DB_PASSWORD": "your_password",
        "ARCHIE_PLATFORM_URL": "http://localhost:3000"
      }
    }
  }
}
```

### Manual Startup

```bash
cd /mnt/archie_brain/platform_v2
python3 -m mcp_server.server
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_NAME` | `archie` | Database name |
| `DB_USER` | `archie` | Database user |
| `DB_PASSWORD` | `archie_secure_2024` | Database password |
| `ARCHIE_PLATFORM_URL` | `http://localhost:3000` | Platform base URL |

---

## Tool Categories

### Knowledge Tools (6 tools)

Tools for searching, storing, and recalling information from A.R.C.H.I.E.'s unified knowledge base.

| Tool | Permission | Description |
|------|------------|-------------|
| `search_knowledge` | read | Search knowledge base with type-weighted ranking |
| `store_memory` | write | Store new information in long-term memory |
| `get_user_preferences` | read | Retrieve learned user preferences |
| `recall_context` | read | Recall relevant historical context for a topic |
| `learn_preference` | write | Teach a new user preference |
| `get_knowledge_stats` | read | Get knowledge base statistics |

### Creation Tools (6 tools)

Tools for project creation, code generation, and deployment.

| Tool | Permission | Description |
|------|------------|-------------|
| `create_project` | write | Create a new project with templates |
| `list_projects` | read | List all projects with filtering |
| `get_project` | read | Get detailed project information |
| `generate_code` | write | Generate code using AI (routes through archie_bridge) |
| `import_figma_design` | write | Import designs from Figma |
| `deploy_project` | admin | Deploy project to target environment |

### Business Tools (7 tools)

Tools for CRM, invoicing, email, scheduling, and e-commerce.

| Tool | Permission | Description |
|------|------------|-------------|
| `create_invoice` | write | Create a new invoice |
| `list_invoices` | read | List invoices with filtering |
| `send_email` | write | Send email via configured SMTP |
| `schedule_event` | write | Schedule calendar event |
| `manage_contacts` | write | CRM contact management (CRUD) |
| `create_store_product` | write | Add product to store |
| `list_products` | read | List store products |

### Admin Tools (8 tools)

Tools for system administration, agent management, and analytics.

| Tool | Permission | Description |
|------|------------|-------------|
| `assign_agent` | admin | Assign agent to station/task |
| `unassign_agent` | admin | Remove agent from station |
| `get_system_status` | read | Get platform health status |
| `list_agents` | read | List all agents with filtering |
| `run_improvement` | admin | Execute improvement proposal |
| `manage_backup` | admin | Create/restore backups |
| `view_analytics` | read | Get analytics and metrics |
| `get_station_assignments` | read | Get current station assignments |

### Advanced Tools (12 tools)

Tools for workflows, rate limiting, audit logging, and system health.

| Tool | Permission | Description |
|------|------------|-------------|
| `list_workflows` | read | List available workflows |
| `trigger_workflow` | write | Trigger workflow execution |
| `get_workflow_execution` | read | Get workflow execution status |
| `create_workflow` | admin | Create new workflow definition |
| `get_rate_limit_status` | read | Check API rate limit status |
| `record_api_usage` | write | Log API usage for tracking |
| `log_audit_event` | write | Log audit event |
| `search_audit_log` | read | Search audit history |
| `get_audit_summary` | read | Get audit summary statistics |
| `health_check` | read | Comprehensive health check |
| `get_service_status` | read | Get individual service status |
| `get_system_config` | admin | Get system configuration |

---

## Tool Reference

### Knowledge Tools

#### search_knowledge

Search A.R.C.H.I.E.'s unified knowledge base across all types with intelligent ranking.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query - matches against titles and content"
    },
    "types": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Filter by types: mistake_learned, vault_note, code_snippet, github_file, conversation_memory"
    },
    "category": {
      "type": "string",
      "description": "Filter by category (e.g., database, api, frontend)"
    },
    "limit": {
      "type": "integer",
      "default": 10,
      "description": "Max results (max: 50)"
    }
  },
  "required": ["query"]
}
```

**Type Weights:**
- `mistake_learned`: 1.3x (highest priority)
- `vault_note`: 1.2x
- `code_snippet`: 1.1x
- `improvement`: 1.0x
- `github_file`: 0.8x
- `conversation_memory`: 0.8x

**Example:**
```json
{
  "query": "database connection error",
  "types": ["mistake_learned", "code_snippet"],
  "limit": 5
}
```

#### store_memory

Store new information in A.R.C.H.I.E.'s long-term memory.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "content": {
      "type": "string",
      "description": "The content to store (required)"
    },
    "title": {
      "type": "string",
      "description": "Brief title (auto-generated if not provided)"
    },
    "memory_type": {
      "type": "string",
      "enum": ["conversation_memory", "vault_note", "code_snippet", "improvement", "mistake_learned"],
      "default": "conversation_memory"
    },
    "category": {
      "type": "string",
      "default": "general"
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"}
    },
    "importance": {
      "type": "number",
      "default": 0.6,
      "description": "0.0-1.0 importance score"
    }
  },
  "required": ["content"]
}
```

#### recall_context

Recall relevant historical context for a topic including memories, mistakes, and procedures.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "description": "Topic to recall context for"
    },
    "context_type": {
      "type": "string",
      "enum": ["conversation", "fact", "procedure"]
    },
    "limit": {
      "type": "integer",
      "default": 5,
      "description": "Max results per category (max: 20)"
    },
    "include_recent": {
      "type": "boolean",
      "default": true
    }
  },
  "required": ["topic"]
}
```

---

### Creation Tools

#### generate_code

Generate code using AI agents. Routes through archie_bridge for proper contractor approval and task logging.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "prompt": {
      "type": "string",
      "description": "Code generation prompt"
    },
    "language": {
      "type": "string",
      "description": "Target language (python, javascript, etc.)"
    },
    "framework": {
      "type": "string",
      "description": "Framework if applicable (react, flask, etc.)"
    },
    "project_id": {
      "type": "integer",
      "description": "Associate with existing project"
    }
  },
  "required": ["prompt"]
}
```

**Note:** Uses internal Ollama staff first (FREE), escalates to contractors with approval.

---

### Admin Tools

#### assign_agent

Assign an AI agent to a station for task processing.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "agent_id": {
      "type": "integer",
      "description": "Agent ID to assign"
    },
    "station": {
      "type": "string",
      "description": "Target station name",
      "enum": ["COMMAND", "ENGINEERING", "RND", "CREATIVE", "OPERATIONS", "SECURITY", "MEDICAL", "INFRASTRUCTURE", "FINANCE", "HR", "ADMIN", "AWAY_TEAM", "CONSCIOUSNESS", "TRAINING", "LOUNGE"]
    },
    "role": {
      "type": "string",
      "enum": ["primary", "backup", "trainee"]
    }
  },
  "required": ["agent_id", "station"]
}
```

#### get_system_status

Get comprehensive platform health status.

**Response includes:**
- Database connectivity
- Ollama availability
- Active agents count
- Queue status
- Memory usage
- Recent errors

---

### Advanced Tools

#### trigger_workflow

Trigger a predefined workflow.

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "workflow_id": {
      "type": "string",
      "description": "Workflow identifier"
    },
    "parameters": {
      "type": "object",
      "description": "Workflow input parameters"
    },
    "async": {
      "type": "boolean",
      "default": true,
      "description": "Run asynchronously"
    }
  },
  "required": ["workflow_id"]
}
```

#### health_check

Comprehensive health check of all system components.

**Response includes:**
```json
{
  "success": true,
  "status": "healthy",
  "components": {
    "database": {"status": "up", "latency_ms": 5},
    "ollama": {"status": "up", "models_loaded": 21},
    "platform": {"status": "up", "uptime_seconds": 86400},
    "mcp_server": {"status": "up", "tools_loaded": 39}
  },
  "warnings": [],
  "timestamp": "2026-01-21T10:30:00Z"
}
```

---

## Authentication & Security

### API Key Authentication

The MCP server supports API key authentication for external clients:

```python
# In mcp_server/auth.py
def validate_api_key(api_key: str) -> bool:
    """Validate API key against database"""
    # Check mcp_api_keys table
    # Returns user permissions
```

### Permission Levels

| Level | Description |
|-------|-------------|
| `read` | Read-only access to data |
| `write` | Create/modify data |
| `admin` | Full system access |

### Rate Limiting

Default limits (configurable):
- 100 requests/minute per session
- 1000 requests/hour per API key
- Tracked in `mcp_rate_limits` table

---

## Audit Logging

All tool invocations are logged to `mcp_audit_log`:

```sql
CREATE TABLE mcp_audit_log (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(50),
    tool_name VARCHAR(100),
    input_params JSONB,
    output_result JSONB,
    user_id INTEGER,
    duration_ms INTEGER,
    success BOOLEAN,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Error Handling

All tools return consistent error format:

```json
{
  "success": false,
  "error": "Error message here",
  "error_code": "PERMISSION_DENIED",
  "suggestion": "Request admin approval for this operation"
}
```

Common error codes:
- `VALIDATION_ERROR` - Invalid input parameters
- `PERMISSION_DENIED` - Insufficient permissions
- `NOT_FOUND` - Resource not found
- `RATE_LIMITED` - Rate limit exceeded
- `DATABASE_ERROR` - Database connection/query error
- `CONTRACTOR_APPROVAL_REQUIRED` - Needs admin approval for contractor usage

---

## Integration with archie_bridge

Tools that require AI generation route through archie_bridge:

1. **Task Classification** - Determines task type and complexity
2. **Staff Selection** - Picks appropriate internal agent
3. **Local First** - Tries internal Ollama staff (FREE)
4. **Contractor Fallback** - If internal fails, requests contractor approval
5. **Task Logging** - Logs to `task_execution_log` for HR visibility

---

## Troubleshooting

### MCP Server Not Starting

```bash
# Check logs
tail -f /mnt/archie_brain/logs/mcp_server.log

# Verify database connection
psql -h localhost -U archie -d archie -c "SELECT 1"

# Check tool count
python3 -c "from mcp_server.tools import get_all_tools; print(len(get_all_tools()))"
```

### Tools Not Responding

1. Check platform is running: `curl http://localhost:3000/health`
2. Check Ollama: `curl http://192.168.1.246:11434/api/tags`
3. Restart MCP server

### Rate Limit Errors

```sql
-- Check current limits
SELECT * FROM mcp_rate_limits WHERE session_id = 'your-session';

-- Reset limits (admin)
DELETE FROM mcp_rate_limits WHERE session_id = 'your-session';
```

---

## File Locations

| File | Purpose |
|------|---------|
| `/mnt/archie_brain/platform_v2/mcp_server/server.py` | Main server implementation |
| `/mnt/archie_brain/platform_v2/mcp_server/auth.py` | Authentication module |
| `/mnt/archie_brain/platform_v2/mcp_server/tools/__init__.py` | Tool registry |
| `/mnt/archie_brain/platform_v2/mcp_server/tools/knowledge.py` | Knowledge tools (6) |
| `/mnt/archie_brain/platform_v2/mcp_server/tools/creation.py` | Creation tools (6) |
| `/mnt/archie_brain/platform_v2/mcp_server/tools/business.py` | Business tools (7) |
| `/mnt/archie_brain/platform_v2/mcp_server/tools/admin.py` | Admin tools (8) |
| `/mnt/archie_brain/platform_v2/mcp_server/tools/advanced.py` | Advanced tools (12) |
| `/mnt/archie_brain/logs/mcp_server.log` | Server logs |

---

## Related Documentation

- [ARCHIE_BRIDGE_MODULE_PLAN.md](./ARCHIE_BRIDGE_MODULE_PLAN.md) - Bridge routing system
- [LLM_REFERENCE_GUIDE.md](./LLM_REFERENCE_GUIDE.md) - Available LLM models
- [DATABASE_SCHEMA_DOCUMENTATION.md](./DATABASE_SCHEMA_DOCUMENTATION.md) - Full schema reference
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Common issues and fixes

---

**Total Tools:** 39
**Categories:** 5 (Knowledge, Creation, Business, Admin, Advanced)
**Protocol:** MCP over stdio
**Status:** Phase 50 Complete
