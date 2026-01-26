# Sandbox Manager Documentation

**Module:** Sandbox Manager - Per-Module Testing Environments
**Version:** 1.0.0
**Category:** ADMIN
**Status:** Active
**Route:** `/tools/sandbox-manager`

---

## Overview

Sandbox Manager provides isolated testing environments for each A.R.C.H.I.E. module. It enables safe deployment testing, integrates with the Improvements Lab workflow, and provides AI-powered analysis of test results.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         SHARED SERVICES                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │   Ollama    │  │ Consciousness│  │ Knowledge   │  │  Blueprint  │ │
│  │  (11434)    │  │    API      │  │    Base     │  │   Roadmap   │ │
└──────────────────────────────────────────────────────────────────────┘
         ↑                 ↑                 ↑               ↑
┌────────┴─────────────────┴─────────────────┴───────────────┴─────────┐
│                       MODULE SANDBOXES                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  CodeRabbit │  │ Improvements│  │  AI Bridge  │  │  Platform   │ │
│  │   :3101     │  │    :3102    │  │    :3103    │  │    :3104    │ │
│  │  (Schema)   │  │  (Schema)   │  │  (Docker)   │  │  (Docker)   │ │
└──────────────────────────────────────────────────────────────────────┘
```

## Features

### 1. Per-Module Sandboxes
Each module has its own isolated testing environment:

| Module | Port | Type | Purpose |
|--------|------|------|---------|
| coderabbit | 3101 | Schema | Code scanning changes |
| improvements | 3102 | Schema | Workflow changes |
| ai_bridge | 3103 | Docker | AI routing changes |
| platform | 3104 | Docker | Cross-module changes |
| admin | 3105 | Schema | Admin panel changes |
| consciousness | 3106 | Schema | Memory system changes |

### 2. Sandbox Types
- **Schema-based**: Lightweight, uses PostgreSQL schema isolation (default)
- **Docker-based**: Full container isolation for complex changes

### 3. Visual Access
Each active sandbox provides a full visual environment:
- Access at `http://localhost:{port}/sandbox/dashboard`
- Full A.R.C.H.I.E. dashboard with changes applied
- "SANDBOX MODE" banner displayed

### 4. AI Integration
- Analyzes test failures using AI Bridge
- Suggests fixes based on error patterns
- Records learnings in knowledge_base
- Queries existing knowledge for similar issues

## Database Schema

### module_sandboxes
```sql
CREATE TABLE module_sandboxes (
    id SERIAL PRIMARY KEY,
    module_id VARCHAR(100) NOT NULL UNIQUE,
    sandbox_type VARCHAR(50) DEFAULT 'schema',
    schema_name VARCHAR(100),
    container_name VARCHAR(100),
    port INTEGER,
    status VARCHAR(50) DEFAULT 'inactive',
    current_proposal_id INTEGER REFERENCES improvement_proposals(id),
    total_tests_run INTEGER DEFAULT 0,
    tests_passed INTEGER DEFAULT 0,
    tests_failed INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    last_test_at TIMESTAMP
);
```

### sandbox_config
```sql
CREATE TABLE sandbox_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(100) NOT NULL,
    config_value JSONB NOT NULL,
    module_id VARCHAR(100),  -- NULL = global
    description TEXT,
    UNIQUE(config_key, module_id)
);
```

## API Endpoints

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Sandbox Manager dashboard |
| GET | `/api/status` | Manager status and summary |

### Sandbox Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sandboxes` | List all module sandboxes |
| GET | `/api/sandboxes/{module_id}` | Get specific sandbox |
| POST | `/api/sandboxes/{module_id}/create` | Activate sandbox |
| POST | `/api/sandboxes/{module_id}/destroy` | Destroy sandbox |
| POST | `/api/sandboxes/{module_id}/reset` | Reset to clean state |
| GET | `/api/sandboxes/{module_id}/status` | Detailed status |

### Testing
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sandboxes/{module_id}/test` | Run test suite |

### Configuration
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Get configuration |
| POST | `/api/config` | Update configuration |

### Integration
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/apply-from-coderabbit` | Apply CodeRabbit fix |
| POST | `/api/apply-from-improvements` | Apply proposal |
| POST | `/api/deploy-to-production` | Deploy tested changes |

### Visual Access
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/access/{module_id}` | Redirect to sandbox UI |

## Configuration Options

```python
sandbox_config = {
    'default_sandbox_type': 'schema',    # schema or docker
    'auto_cleanup_hours': 24,            # Auto-destroy inactive sandboxes
    'max_concurrent_sandboxes': 5,       # Limit active sandboxes
    'test_timeout_seconds': 300,         # Max test duration
    'auto_test_on_proposal': True,       # Auto-run tests when queued
    'notify_on_complete': True,          # Send notification on complete
}
```

## Integration Flow

### CodeRabbit to Deployment
```
1. CodeRabbit finds issue
        ↓
2. User clicks "Send to Improvements"
        ↓
3. Improvement proposal created
        ↓
4. Module detected from file path
        ↓
5. Sandbox Manager activates module sandbox
        ↓
6. Changes applied to sandbox
        ↓
7. Test suite runs
        ↓
8. Success: Deploy to production
   Failure: Record mistake_learned
```

### Module Detection
```python
module_paths = {
    'tools/coderabbit/': 'coderabbit',
    'tools/improvements/': 'improvements',
    'tools/consciousness/': 'consciousness',
    'tools/admin/': 'admin',
    'ai_bridge/': 'ai_bridge',
}
# Default: 'platform' for cross-module changes
```

## Docker Compose

Sandboxes are defined in `docker-compose.sandbox.yml`:

```bash
# Start specific module sandbox
docker-compose -f docker-compose.sandbox.yml --profile sandbox_coderabbit up -d

# Start all sandboxes
docker-compose -f docker-compose.sandbox.yml --profile sandbox up -d

# Start legacy single sandbox
SANDBOX_ID=123 docker-compose -f docker-compose.sandbox.yml up archie_sandbox -d
```

## File Structure

```
platform_v2/
├── sandbox_manager.py           # Core sandbox management
├── sandbox_ai_integration.py    # AI analysis integration
├── sandbox_docs_updater.py      # Auto-documentation
├── tools/sandbox_manager/
│   ├── __init__.py
│   └── routes.py                # API routes
└── templates/tools/
    └── sandbox_manager.html     # Dashboard UI

migrations/
└── 020_module_sandboxes.sql     # Database schema

docker-compose.sandbox.yml       # Container definitions
```

## UI Features

### Dashboard
- Module sandbox cards with status indicators
- Active/Testing/Inactive status display
- Current proposal being tested
- Test statistics (passed/failed)

### Actions
- Activate/Destroy sandbox buttons
- "Open Visual" to access sandbox UI
- "Run Tests" to start test suite
- "Details" modal with full info

### Configuration Panel
- Global settings management
- Per-module overrides
- Auto-test and notification toggles

## Usage Examples

### Activate a Sandbox
```bash
curl -X POST http://localhost:3000/tools/sandbox-manager/api/sandboxes/coderabbit/create \
  -H "Content-Type: application/json"
```

### Run Tests
```bash
curl -X POST http://localhost:3000/tools/sandbox-manager/api/sandboxes/coderabbit/test \
  -H "Content-Type: application/json" \
  -d '{"test_suite": "default"}'
```

### Deploy to Production
```bash
curl -X POST http://localhost:3000/tools/sandbox-manager/api/deploy-to-production \
  -H "Content-Type: application/json" \
  -d '{"module_id": "coderabbit", "proposal_id": 123}'
```

## Auto-Documentation

When deployments complete, documentation is auto-updated:

| Event | CHANGELOG.md | TROUBLESHOOTING.md | Knowledge Base |
|-------|--------------|-------------------|----------------|
| Success | Entry added | - | improvement entry |
| Failure | - | Entry added | mistake_learned entry |

## Security

- All routes require `admin:sandbox` permission
- Visual access requires ADMIN role
- Sandboxes share database but use schema isolation
- Full Docker isolation available for sensitive changes

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-13 | Initial release with per-module sandboxes |

---

**Last Updated:** 2026-01-13
**Author:** A.R.C.H.I.E. Platform
