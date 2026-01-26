# Code Sentinel Module Documentation

**Module:** Code Sentinel - Team-Powered Code Review & Security Analysis
**Version:** 3.0.0
**Category:** DEVELOPMENT
**Status:** Active
**Route:** `/tools/code_sentinel`
**Last Updated:** 2026-01-24

---

## Overview

Code Sentinel is an AI-powered code review and security analysis module that leverages the A.R.C.H.I.E. multi-agent system for comprehensive code scanning. It evolved from the CodeRabbit module with significant enhancements including Bridge routing, team-based reviews, and deeper integration with the Improvements Lab workflow.

### Key Capabilities
- **Multi-Agent Code Reviews**: 4+ specialized agents analyze code in parallel
- **Security Vulnerability Scanning**: OWASP-aware pattern detection
- **Code Quality Analysis**: Best practices, SOLID principles, code smells
- **AI + Static Hybrid Analysis**: Falls back to pattern matching when AI unavailable
- **Bridge Routing Integration**: Smart agent selection from R&D Core station
- **Improvements Lab Integration**: Seamless issue-to-proposal workflow

---

## Features

### 1. Code Health Scanner (Tab 1: 🏥 Code Health)

The primary scanning interface with a two-panel layout:

**File Browser Panel (Left)**
- Directory tree with collapsible folders
- Search/filter functionality
- Multi-select checkboxes for batch operations
- Modified file indicators (orange "MODIFIED" badge)
- File size and status display

**Scan Panel (Right)**
- Quick Scan: Fast AI-powered single file analysis
- Team Scan: Multi-agent parallel review (4+ agents)
- Quality score (0-100) with color coding
- Issue list with severity badges
- Suggestions and fix recommendations

**Scanning Modes**
| Mode | Description | Agents Used |
|------|-------------|-------------|
| Quick Scan | Fast AI analysis | 1 (fastest available) |
| Team Scan | Multi-agent consensus review | 4+ (R&D Core team) |
| Batch Scan | Multiple files in parallel | 1 per file (batched) |
| Rescan Modified | Only changed files | 1 (fastest available) |

### 2. Issue Tracking (Tab 2: 🐛 Issues)

Comprehensive issue management with two-panel layout:

**Issues List Panel (Left)**
- Filterable issue list
- Severity color coding (Critical/High/Medium/Low)
- Multi-select for batch operations
- Status indicators (Open, Fixed, In Lab)

**Issue Detail Panel (Right)**
- Full issue description and context
- Agent review cards (when team-scanned)
- Synthesis reports (AI-generated summaries)
- Hotfix code (AI-generated fixes)
- Action buttons for workflow

**Available Actions**
| Action | Description |
|--------|-------------|
| 🤖 Team Scan | Run multi-agent review on issue |
| 📝 Generate Report | Create synthesis report |
| 🔧 Generate Hotfix | AI-generate fix code |
| 📤 Send to Lab | Create improvement proposal |
| ✓ Mark Fixed | Close the issue |

### 3. Team Activity (Tab 3: 📋 Activity)

Activity logging and team statistics:

**Statistics Cards**
- Total Scans (all time)
- Today's Scans
- Issues Found
- Active Team Members

**Activity Log**
- Chronological scan history
- Agent attribution
- Scan type and results
- Relative timestamps

---

## Architecture

### Multi-Agent Review System

Code Sentinel uses specialized agents from the R&D Core station:

```
┌─────────────────────────────────────────────────────────┐
│                    Code Sentinel                         │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │
│  │  Security   │   │ Code Review │   │Architecture │   │
│  │   Agent     │   │   Agent     │   │   Agent     │   │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   │
│         │                 │                 │           │
│         └────────────┬────┴────────────────┘           │
│                      │                                  │
│              ┌───────▼───────┐                         │
│              │   Consensus   │                         │
│              │   Builder     │                         │
│              └───────┬───────┘                         │
│                      │                                  │
│              ┌───────▼───────┐                         │
│              │ Final Issues  │                         │
│              └───────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

**Agent Specialties**
| Specialty | Focus Areas |
|-----------|-------------|
| Security | SQL injection, XSS, secrets, OWASP, auth bypass |
| Code Review | SOLID, DRY, code smells, naming, documentation |
| Architecture | Design patterns, modularity, scalability |
| Bug Fixing | Edge cases, error handling, race conditions |

### Bridge Routing Integration

Code Sentinel integrates with the A.R.C.H.I.E. Bridge for intelligent agent routing:

```python
# Agent selection flow
1. get_station_agents('RND_CORE')     # Get R&D Core team
2. check_team_capability(task_type)    # Verify capability
3. request_additional_support()        # Request backup if needed
4. get_best_agent_for_task()          # Select optimal agent
```

**Model Speed Rankings**
| Rank | Model | Use Case |
|------|-------|----------|
| 1 | qwen2.5-coder:7b | Batch scanning, quick scans |
| 2 | starcoder2:7b | General code review |
| 3 | deepseek-coder-v2:16b | Detailed analysis |
| 4 | deepseek-coder:33b | Complex security |
| 5 | codellama:34b | Architecture review |
| 6 | claude-sonnet-4 | Thorough analysis |
| 7 | gpt-4 | Maximum quality |

---

## Database Schema

### Primary Tables (7 Code Sentinel-specific)

#### code_scans
```sql
CREATE TABLE code_scans (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL,
    scan_type VARCHAR(50) DEFAULT 'manual',
    issues_found INTEGER DEFAULT 0,
    security_issues INTEGER DEFAULT 0,
    quality_score DECIMAL(5,2),
    scan_result JSONB,
    scanned_by VARCHAR(100),
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### code_issues
```sql
CREATE TABLE code_issues (
    id SERIAL PRIMARY KEY,
    scan_id INTEGER REFERENCES code_scans(id),
    file_path VARCHAR(500),
    line_number INTEGER,
    issue_type VARCHAR(50),        -- 'security', 'quality', 'performance', 'style'
    severity VARCHAR(20),          -- 'critical', 'high', 'medium', 'low'
    message TEXT,
    suggestion TEXT,
    status VARCHAR(20) DEFAULT 'open',  -- 'open', 'fixed', 'false_positive', 'wontfix'
    fixed_by VARCHAR(100),
    fixed_at TIMESTAMP,
    proposal_id INTEGER REFERENCES improvement_proposals(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### code_fixes
```sql
CREATE TABLE code_fixes (
    id SERIAL PRIMARY KEY,
    issue_id INTEGER REFERENCES code_issues(id),
    file_path VARCHAR(500),
    fixed_by VARCHAR(100),
    fix_description TEXT,
    pr_number INTEGER,
    pr_url VARCHAR(500),
    commit_sha VARCHAR(100),
    fixed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### pull_requests
```sql
CREATE TABLE pull_requests (
    id SERIAL PRIMARY KEY,
    pr_number INTEGER,
    repo VARCHAR(200),
    title VARCHAR(500),
    state VARCHAR(20),
    author VARCHAR(100),
    url VARCHAR(500),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    merged_at TIMESTAMP,
    additions INTEGER,
    deletions INTEGER,
    changed_files INTEGER,
    labels JSONB,
    metadata JSONB,
    synced_at TIMESTAMP,
    UNIQUE(repo, pr_number)
);
```

#### review_comparisons
```sql
CREATE TABLE review_comparisons (
    id SERIAL PRIMARY KEY,
    comparison_id VARCHAR(100) UNIQUE,
    file_path VARCHAR(500),
    code_snippet TEXT,
    status VARCHAR(20),
    multi_agent_review_id VARCHAR(100),
    sentinel_issues JSONB,
    correlation_data JSONB,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

### Shared Tables Used
- `knowledge_base` - False positive learnings (type: 'mistake_learned')
- `agents` - Agent registry with capabilities
- `station_assignments` - R&D Core team mapping
- `improvement_proposals` - Linked proposals

---

## API Endpoints

### Status & Configuration (4 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main dashboard view |
| GET | `/api/status` | Module health check |
| GET | `/api/ai-status` | Ollama availability |
| GET | `/api/config` | Configuration settings |

### Code Health Scanning (11 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/health/scan` | Scan single file |
| POST | `/api/health/batch-scan` | Batch scan files |
| GET | `/api/health/stats` | Health statistics |
| GET | `/api/health/scans` | Scan history |
| GET | `/api/health/issues` | Get issues |
| POST | `/api/health/issues/scan-false-positives` | Flag false positives |
| POST | `/api/health/issues/<id>/fix` | Mark issue fixed |
| GET | `/api/health/fixes` | Get fixed issues |
| GET | `/api/health/files` | List scanned files |
| GET | `/api/health/files-needing-rescan` | Modified files |
| GET | `/api/health/directory` | Directory listing |

### Multi-Agent Review (5 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/multi-agent/review` | Start team review |
| GET | `/api/multi-agent/review/<id>` | Get review status |
| GET | `/api/multi-agent/reviews-by-file` | Reviews by file |
| GET | `/api/multi-agent/agents` | Available agents |
| GET | `/api/multi-agent/nodes` | Available nodes |

### Issue Workflow (8 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/issues/multi-agent-status` | Multi-agent status |
| POST | `/api/issues/send-to-improvements` | Send to Lab |
| POST | `/api/issues/update-from-improvement` | Lab callback |
| POST | `/api/issues/<id>/generate-synthesis` | Generate report |
| POST | `/api/issues/<id>/generate-hotfix` | Generate fix |
| POST | `/api/issues/<id>/send-to-lab` | Send single to Lab |
| POST | `/api/issues/lab-webhook` | Lab webhook |
| GET | `/api/issues/<id>/status` | Issue status |

### Review Comparison (5 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/compare-reviews` | Compare reviews |
| POST | `/api/review-compare/start` | Start comparison |
| GET | `/api/review-compare/<id>` | Get comparison |
| POST | `/api/review-compare/send-to-improvements` | Send to Lab |
| GET | `/api/review-compare/stats` | Comparison stats |

### Git Operations (14 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/git/status` | Repository status |
| GET | `/api/git/branches` | List branches |
| POST | `/api/git/fetch` | Fetch from remote |
| POST | `/api/git/pull` | Pull from remote |
| POST | `/api/git/push` | Push to remote |
| POST | `/api/git/stage-all` | Stage all changes |
| POST | `/api/git/commit` | Create commit |
| POST | `/api/git/create-pr` | Create pull request |
| GET | `/api/git/pr-info` | PR information |
| GET | `/api/git/suggest-splits` | Suggest PR splits |
| POST | `/api/git/create-split-branch` | Create split branch |
| POST | `/api/git/create-branch` | Create branch |
| POST | `/api/git/checkout` | Checkout branch |
| POST | `/api/git/delete-branch` | Delete branch |

### Pull Request Management (6 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/recent-prs` | Recent pull requests |
| GET | `/api/prs/local` | Locally cached PRs |
| POST | `/api/prs/sync` | Sync from GitHub |
| POST | `/api/pr/request-review` | Request review |
| GET | `/api/pr/<number>/review-comments` | Review comments |
| POST | `/api/pr/<number>/merge` | Merge PR |

### GitHub Integration (6 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/webhooks/github` | GitHub webhook |
| GET | `/api/github/issues` | List issues |
| POST | `/api/github/issues` | Create issue |
| PATCH | `/api/github/issues/<number>` | Update issue |
| GET | `/api/github/actions/runs` | Workflow runs |
| POST | `/api/github/actions/runs/<id>/rerun` | Rerun workflow |

### Repository Management (3 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/repos` | List repositories |
| POST | `/api/repos` | Add repository |
| DELETE | `/api/repos/<path:repo>` | Remove repository |

### Statistics & Activity (4 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Review statistics |
| GET | `/api/station-team` | R&D Core team |
| GET | `/api/activity` | Activity log |
| GET | `/api/file/<path>` | Get file content |

**Total: 56+ API Endpoints**

---

## Issue Detection

### Security Issues (Critical/High)

| Pattern | Severity | Description |
|---------|----------|-------------|
| `eval()` / `exec()` | Critical | Code injection risk |
| f-string SQL | Critical | SQL injection |
| Hardcoded passwords | Critical | Exposed credentials |
| `innerHTML` | High | XSS vulnerability |
| Bare `except:` | High | Silent error swallowing |
| `shell=True` | High | Command injection |

### Quality Issues (Medium/Low)

| Pattern | Severity | Description |
|---------|----------|-------------|
| TODO comments | Medium | Incomplete work |
| Long lines (>120) | Medium | Readability |
| `console.log` | Low | Debug code |
| `print()` | Low | Debug statements |
| Missing docstrings | Low | Documentation |

### Safe Patterns (Not Flagged)

```python
# Parameterized queries - SAFE
execute("SELECT * FROM x WHERE id = %s", (param,))
execute("...%(name)s...", {'name': val})

# Environment variables - SAFE
api_key = os.getenv('API_KEY')

# Authorization headers - SAFE
headers = {'Authorization': f'Bearer {token}'}
```

---

## Quality Scoring Algorithm

```
Base Score: 100

Deductions:
- Critical issues: -25 each
- High issues:     -15 each
- Medium issues:   -5 each
- Low issues:      -2 each

Minimum Score: 0
Maximum Score: 100
```

**Score Thresholds**
| Score Range | Color | Status |
|-------------|-------|--------|
| 80-100 | Green | Healthy |
| 60-79 | Yellow | Needs attention |
| 40-59 | Orange | Poor quality |
| 0-39 | Red | Critical issues |

---

## Configuration

### Environment Variables

```bash
# GitHub Integration
GITHUB_TOKEN=<personal_access_token>
GITHUB_REPOS=owner/repo1,owner/repo2

# Ollama (Local LLM)
OLLAMA_PRIMARY=192.168.1.246:11434
OLLAMA_SECONDARY=192.168.1.245:11434

# Database
DB_HOST=archie_database
DB_PORT=5432
DB_NAME=archie
DB_USER=archie
DB_PASSWORD=<password>
```

### Default Repositories

```python
GITHUB_REPOS = [
    'KytranKatarn/archie-platform',
    'KytranKatarn/kytranempowerment-site'
]
```

### Feature Flags

```python
BRIDGE_ROUTING_AVAILABLE = True   # AI Bridge integration
NODE_ROUTING_AVAILABLE = True     # GPU cluster routing
```

---

## Integration with A.R.C.H.I.E. Systems

### AI Bridge Integration
- Routes scans to R&D Core station agents
- Smart agent selection based on task type
- Automatic support requests when team lacks capability
- Model speed optimization for batch operations

### Knowledge Base Integration
- Stores false positive learnings
- Category: `code_health`, Type: `mistake_learned`
- 50 pattern cache for future scan filtering
- 1.3x priority weight for learned patterns

### Improvements Lab Integration
- Send issues directly to Lab as proposals
- Bidirectional status tracking
- Webhook callbacks for completion
- Auto-categorization (security, performance, quality)

### Sandbox Manager Integration
- Issues flow through Lab to Sandbox
- Isolated testing environment
- Success: Deploy and mark fixed
- Failure: Record mistake, return for revision

---

## Workflow Examples

### Single File Scan
```bash
curl -X POST http://localhost:3000/tools/code_sentinel/api/health/scan \
  -H "Content-Type: application/json" \
  -d '{"file_path": "platform_v2/app.py"}'
```

### Multi-Agent Review
```bash
curl -X POST http://localhost:3000/tools/code_sentinel/api/multi-agent/review \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def example(): pass",
    "file_path": "example.py",
    "context": "Review for security issues"
  }'
```

### Check AI Status
```bash
curl http://localhost:3000/tools/code_sentinel/api/ai-status
```

### Send Issue to Lab
```bash
curl -X POST http://localhost:3000/tools/code_sentinel/api/issues/send-to-improvements \
  -H "Content-Type: application/json" \
  -d '{"issue_ids": [1, 2, 3]}'
```

---

## UI Theme

### Color Palette
| Color | Hex | Usage |
|-------|-----|-------|
| Red | `#FF6B6B` | Primary actions, critical issues |
| Green | `#00ff41` | Success, healthy, scan panel |
| Cyan | `#00FFFF` | Highlights, accents |
| Orange | `#FFAA00` | Warnings, file browser |
| Purple | `#8B5CF6` | Activity, reviews |

### Typography
- **Primary**: JetBrains Mono (monospace)
- **Display**: Orbitron (headers)

### Design System
- Shared A.R.C.H.I.E. design tokens
- Shield Blue cyberpunk aesthetic
- Animated progress indicators
- Responsive grid layouts

---

## File Structure

```
/platform_v2/tools/code_sentinel/
├── __init__.py              # Blueprint initialization
└── routes.py                # 56+ API endpoints (6,970 lines)

/platform_v2/templates/tools/
└── code_sentinel.html       # Full UI template (5,595 lines)
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 3.0.0 | 2026-01-24 | Renamed from CodeRabbit, consolidated tabs, Bridge routing |
| 2.2.1 | 2026-01-16 | CI workflow for automated testing |
| 2.2.0 | 2026-01-15 | Git Manager consolidation |
| 2.1.0 | 2026-01-15 | Improvements Lab integration |
| 2.0.0 | 2026-01-15 | Modified file detection, PR status, bidirectional tracking |
| 1.1.0 | 2026-01-13 | Send to Improvements workflow |
| 1.0.0 | 2026-01-12 | Initial release (as CodeRabbit) |

### v3.0.0 Changes - Code Sentinel Release
- **Renamed**: CodeRabbit → Code Sentinel
- **Consolidated Tabs**: 6 tabs → 3 tabs (Code Health, Issues, Activity)
- **Removed**: Standalone Git, PR Reviews, GitHub Issues, Actions tabs
- **Added**: Bridge routing for agent selection
- **Added**: Team-based multi-agent scanning
- **Enhanced**: R&D Core station integration
- **Improved**: Consensus building from multiple agents

---

## Related Documentation

- [Improvements Lab Workflow](IMPROVEMENTS_LAB_WORKFLOW.md)
- [Bridge Station Architecture](BRIDGE_STATION_ARCHITECTURE.md)
- [Multi-Agent Bridge Architecture](MULTI_AGENT_BRIDGE_ARCHITECTURE.md)
- [Agent Directory](AGENT_DIRECTORY.md)

---

**Author:** A.R.C.H.I.E. Platform
**Last Updated:** 2026-01-24
