# Improvements Lab Workflow Documentation

**Date:** January 14, 2026
**Status:** Phase 12 - In Progress
**Purpose:** Document the complete Improvements Lab workflow from proposal to deployment

---

## Overview

The Improvements Lab is A.R.C.H.I.E.'s self-improvement system that:
1. Creates improvement proposals (manual or from CodeRabbit scans)
2. Generates AI-powered implementation plans
3. Applies code changes in isolated sandboxes
4. Runs automated tests
5. Deploys approved changes to production

---

## Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     PROPOSAL CREATION                            │
│  CodeRabbit Scan → Auto-create proposal with file/line info     │
│  Manual → User creates proposal with description                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     REGENERATE PLAN                              │
│  1. CodeGenerationEngine receives proposal                       │
│  2. AI (llama3.1:8b) generates code changes                     │
│  3. Parser extracts FILE/ACTION/OLD_CONTENT/NEW_CONTENT         │
│  4. plan_steps saved to proposal                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        EXECUTE                                   │
│  1. Create pre-deployment backup                                │
│  2. WorkflowOrchestrator starts                                 │
│  3. Create sandbox (schema_separation or docker)                │
│  4. Apply code changes to sandbox                               │
│  5. Run test suites                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
              Tests PASS           Tests FAIL
                    │                   │
                    ▼                   ▼
            ready_for_review      Retry (1-3x)
                    │                   │
                    │           After 3 failures:
                    │           Escalate to Contractor
                    │                   │
                    ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                        DEPLOY                                    │
│  1. Apply changes to production                                 │
│  2. Restart affected services                                   │
│  3. Run health checks                                           │
│  4. Auto-rollback if issues detected                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 1. Regenerate Plan (`/proposals/<id>/regenerate-plan`)

**File:** `tools/improvements/routes.py`

Uses `CodeGenerationEngine` to generate AI-powered implementation plans:

```python
from code_generation_engine import generate_code_for_proposal

code_result = generate_code_for_proposal(
    proposal_id=proposal_id,
    proposal_title=title,
    proposal_description=description,
    category=category,
    target_files=target_files  # From CodeRabbit metadata
)
```

The AI generates structured code changes in this format:
```
FILE: path/to/file.py
ACTION: modify
DESCRIPTION: What this change does

OLD_CONTENT:
```python
old code here
```

NEW_CONTENT:
```python
new code here
```
```

### 2. Execute (`/proposals/<id>/execute`)

**File:** `tools/improvements/routes.py`

Orchestrates the full execution pipeline:

1. **Check plan_steps exist** - Returns error if missing
2. **Create backup** - Uses `create_backup()` from backup_manager
3. **Run WorkflowOrchestrator** - Handles sandbox + code application + tests

```python
from workflow_orchestrator import execute_workflow

result = execute_workflow(proposal_id)
```

### 3. Test Runner (`sandbox_test_runner.py`)

**File:** `ai_bridge/sandbox_test_runner.py`

Runs configured test suites and records results:

| Test Suite | Command | Required |
|------------|---------|----------|
| Python Syntax Check | `python3 -c "import ast; ..."` | Yes |
| Basic Health Check | `python3 -c "print(1+1)"` | Yes |
| Security Scan | Checks recent files for injection patterns | No |

**Test Status Logic:**
- Only **required** test failures block deployment
- Non-required failures are warnings (logged but don't block)

### 4. Logs Endpoint (`/sandboxes/<id>/logs`)

**File:** `tools/improvements/routes.py`

Returns comprehensive logs including:
- Sandbox status and metadata
- Code application results (files modified/created)
- Test results from `sandbox_test_results` table
- Overall test summary

---

## Database Tables

### improvement_proposals

| Column | Type | Description |
|--------|------|-------------|
| id | INT | Primary key |
| title | VARCHAR | Proposal title |
| description | TEXT | Full description |
| status | VARCHAR | pending, approved, executing, tested, deployed |
| plan_steps | JSONB | AI-generated execution steps |
| test_retry_count | INT | Number of test retries (max 3) |
| escalation_status | VARCHAR | none, contractor_consulting, human_only |
| metadata | JSONB | Source info, AI generation details |

### sandbox_instances

| Column | Type | Description |
|--------|------|-------------|
| id | INT | Primary key |
| proposal_id | INT | FK to proposal |
| sandbox_type | VARCHAR | schema_separation or docker_container |
| status | VARCHAR | ready, testing, tested, failed, destroyed |
| test_results | JSONB | Summary of test results |
| metadata | JSONB | Application results, logs |

### sandbox_test_results

| Column | Type | Description |
|--------|------|-------------|
| id | INT | Primary key |
| sandbox_id | INT | FK to sandbox |
| test_name | VARCHAR | Name of test |
| status | VARCHAR | passed, failed, error |
| output | TEXT | Test output |
| error_message | TEXT | Error details if failed |

---

## API Endpoints

### Proposals

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/proposals` | GET | List all proposals |
| `/proposals/<id>` | GET | Get single proposal |
| `/proposals/<id>/approve` | POST | Approve proposal |
| `/proposals/<id>/reject` | POST | Reject proposal |
| `/proposals/<id>/regenerate-plan` | POST | Generate AI plan |
| `/proposals/<id>/execute` | POST | Execute proposal |
| `/proposals/<id>/deploy-to-production` | POST | Deploy to production |
| `/proposals/<id>/retry` | POST | Trigger manual retry |
| `/proposals/<id>/retry-status` | GET | Get retry count |
| `/proposals/<id>/reset-retries` | POST | Reset retry count |

### Sandboxes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/proposals/<id>/sandbox` | GET | Get sandbox for proposal |
| `/proposals/<id>/sandbox/create` | POST | Create sandbox |
| `/sandboxes/<id>/test` | POST | Run tests |
| `/sandboxes/<id>/logs` | GET | Get logs and test results |
| `/sandboxes/<id>` | DELETE | Destroy sandbox |

---

## Retry & Escalation System

**File:** `ai_bridge/test_retry_handler.py`

When tests fail:

1. **Retry 1-3:** Same agent regenerates code with failure context
2. **After 3 failures:** Escalate to external contractor (Claude, GPT, etc.)
3. **Contractor consultation:** Human reviews contractor's proposal via chat
4. **Final options:** Apply fix, try another contractor, or human-only investigation

```python
from test_retry_handler import handle_test_failure

result = handle_test_failure(proposal_id, test_results)
# Returns: {'action': 'retry' | 'escalate', ...}
```

---

## Known Issues & TODOs

### Still Needed (Phase 12)

- [ ] **Clear old test results** - When running new tests, clear previous results
- [ ] **Request Fix button** - When viewing errors in logs, assign to team member
- [ ] **Team assignment tracking** - Track who created/edited files
- [ ] **Test full deployment** - End-to-end production deployment testing

### Security Scan Patterns

Currently checks for:
- SQL injection: `.format()` with request data
- Code injection: `eval()`/`exec()` with user input
- Command injection: `os.system`/`subprocess` with user input

---

## Files Modified (Phase 12)

| File | Changes |
|------|---------|
| `tools/improvements/routes.py` | Fixed execute, regenerate-plan, logs endpoints |
| `ai_bridge/code_generation_engine.py` | Fixed markdown parser for AI responses |
| `ai_bridge/sandbox_test_runner.py` | Fixed test status logic |
| `static/js/improvements_lab/api.js` | Added regeneratePlan(), fixed executeProposal() |
| `static/js/improvements_lab/app.js` | Added regeneratePlan() function and UI button |

---

## Related Documentation

- `/docs/BACKUP_MANAGER_GUIDE.md` - Backup system documentation
- `/docs/MASTER_STATUS_AND_ROADMAP_2026.md` - Overall roadmap
- `/docs/TROUBLESHOOTING.md` - Common issues and fixes

---

**Last Updated:** January 14, 2026
