# CodeRabbit Module Documentation

> **⚠️ DEPRECATED - This module has been renamed and consolidated**
>
> **CodeRabbit has been replaced by Code Sentinel (v3.0.0)**
>
> See: [`CODE_SENTINEL_MODULE.md`](CODE_SENTINEL_MODULE.md) for current documentation.
>
> **Key Changes:**
> - Module renamed: CodeRabbit → Code Sentinel
> - Route changed: `/tools/coderabbit` → `/tools/code_sentinel`
> - Tabs consolidated: 6 tabs → 3 tabs (Code Health, Issues, Activity)
> - Added: Bridge routing, multi-agent team scanning, R&D Core integration
> - Removed: Standalone Git, PR Reviews, GitHub Issues, Actions tabs (functionality moved to Bridge)
>
> This document is kept for historical reference only.

---

**Module:** CodeRabbit - AI Code Health Scanner & PR Workflow Manager *(DEPRECATED)*
**Version:** 2.0.0 *(Superseded by Code Sentinel v3.0.0)*
**Category:** DEVELOPMENT
**Status:** DEPRECATED
**Route:** `/tools/coderabbit` *(Now: `/tools/code_sentinel`)*
**Last Updated:** 2026-01-15 *(Deprecated: 2026-01-24)*

---

## Overview

CodeRabbit is an AI-powered code health scanner and PR workflow manager that analyzes Python, JavaScript, and HTML files for security vulnerabilities, code quality issues, and best practices. It integrates with GitHub for PR reviews, the A.R.C.H.I.E. knowledge system to learn from scans, and the Improvements Lab for bidirectional issue tracking.

## Features

### 1. Code Health Scanner
- **AI-Powered Analysis**: Uses Ollama (local) for intelligent code review
- **Static Analysis Fallback**: Pattern-based detection when AI unavailable
- **Quality Scoring**: 0-100 score based on issues found
- **Security Scanning**: Detects SQL injection, hardcoded secrets, XSS risks

### 2. Issue Detection
Detects the following issue types:

| Severity | Type | Examples |
|----------|------|----------|
| Critical | Security | eval(), SQL injection, hardcoded passwords |
| High | Security | Bare except, potential injection points |
| Medium | Quality | TODO comments, long lines |
| Low | Style | Print statements, missing docstrings |

### 3. Batch Scanning
- Scan individual files or batch scan 20 files at a time
- Progressive scanning - continues from where you left off
- `__init__.py` files automatically excluded (boilerplate)

### 4. Data Persistence
All scan results are stored in the database:
- `code_scans` - Scan metadata and scores
- `code_issues` - Individual issues with line numbers
- `knowledge_base` - Critical issues added for Consciousness learning
- `improvement_proposals` - Auto-created for critical security issues

### 5. Modified File Detection (v2.0.0)

- **Automatic Detection**: Compares file modification time with last scan timestamp
- **Visual Indicators**: Files needing rescan show orange "MODIFIED" badge
- **Rescan Button**: One-click "Rescan Modified" to batch scan changed files
- **Smart Filtering**: Only files modified after their last scan are flagged

### 6. PR Reviews Tab (v2.0.0)
- **GitHub Integration**: Fetches recent PRs from configured repositories
- **CodeRabbit Review Status**: Shows if PRs were reviewed by CodeRabbit
  - Green badge: "Reviewed" (full review with summary)
  - Blue badge: "Partial" (some comments)
  - Gray badge: "No Review"
- **Request Review**: Button to trigger `@coderabbitai review` on unreviewed PRs
- **Multi-Repo Support**: Filter by repository, color-coded badges

### 7. Bidirectional Issue Tracking (v2.0.0)
- **Proposal Linking**: Issues sent to Improvements Lab are linked via `proposal_id`
- **Status Badges**: Live status from linked proposals
  - Orange "SENT #45" - Proposal pending
  - Green "APPROVED #45" - Ready for testing
  - Blue "TESTING #45" - In sandbox
  - Purple "FIXED #45" - Deployed successfully
  - Red "REJECTED/FAILED #45" - Needs attention
- **Click to Navigate**: Badges link directly to proposal in Improvements Lab

### 8. Scan Cache Persistence (v2.0.0)
- **Session Storage**: Scan results cached in browser sessionStorage
- **Faster Reloads**: Previously scanned files show results immediately
- **Automatic Sync**: Cache updates on new scans

## Database Schema

### code_scans
```sql
CREATE TABLE code_scans (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL,
    scan_type VARCHAR(50) DEFAULT 'manual',
    issues_found INTEGER DEFAULT 0,
    security_issues INTEGER DEFAULT 0,
    quality_score NUMERIC(5,2),
    scan_result JSONB,
    scanned_by VARCHAR(100),
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### code_issues
```sql
CREATE TABLE code_issues (
    id SERIAL PRIMARY KEY,
    scan_id INTEGER REFERENCES code_scans(id),
    file_path VARCHAR(500),
    line_number INTEGER,
    issue_type VARCHAR(50),
    severity VARCHAR(20),
    message TEXT,
    suggestion TEXT,
    status VARCHAR(20) DEFAULT 'open',
    fixed_at TIMESTAMP,
    fixed_by VARCHAR(100),
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL  -- v2.0.0
);

-- Indexes for performance (v2.0.0)
CREATE INDEX idx_code_issues_proposal_id ON code_issues(proposal_id);
CREATE INDEX idx_code_issues_status ON code_issues(status);
```

## API Endpoints

### Status & Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Module status and AI availability |
| GET | `/api/ai-status` | Detailed Ollama connection status |

### Code Health Scanner
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health/directory` | List files for scanning |
| POST | `/api/health/scan` | Scan a single file |
| GET | `/api/health/scans` | Get scan history |
| GET | `/api/health/stats` | Get aggregate statistics |

### Issues Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health/issues` | List issues with proposal status (v2.0.0) |
| POST | `/api/health/issues/{id}/fix` | Mark issue as fixed |
| POST | `/api/issues/send-to-improvements` | Send issues to Improvements Lab |
| GET | `/api/health/fixes` | List recent fixes |

### Modified File Detection (v2.0.0)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health/files-needing-rescan` | Get files modified since last scan |

### PR Reviews (v2.0.0)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/recent-prs` | List recent PRs with CodeRabbit review status |
| POST | `/api/pr/request-review` | Request CodeRabbit review on a PR |
| POST | `/api/prs/sync` | Sync PRs from GitHub to local database |
| GET | `/api/prs/local` | Get locally cached PRs |

## UI Features

### File Browser (Left Panel)
- Collapsible folder structure
- Folder stats: `passed/scanned (total)`
- Color-coded scores on each file
- Search/filter files
- "Scan All" for batch processing

### Results Panel (Right Panel)
- Quality score with color indicator
- Issue list with severity badges
- Suggestions for each issue
- Analysis type badge (AI vs Static)
- "Saved" badge for historical results

### Stats Bar
- Scanned / Total files
- Total issues found
- Security issues count
- Average quality score

## Integration with A.R.C.H.I.E. Systems

### Knowledge Base Integration
When critical/high issues are found:
1. Creates entry in `knowledge_base`
2. Tagged as `code_scan` category
3. Importance score: 0.7 (security) or 0.5 (quality)
4. Searchable by Consciousness module

### Improvement Proposals Integration
For critical security issues:
1. Auto-creates proposal in `improvement_proposals`
2. Category: security, Priority: critical
3. Includes file path, line number, suggestion
4. Appears in Improvements Lab for review

### Send to Improvements Workflow
Manual issue-to-improvement flow added in v1.1.0:

1. **Per-Issue Button**: Each issue has "Send" button to create proposal
2. **Batch Operations**:
   - "Send Critical" - sends all critical/high severity issues
   - "Send Selected" - sends checked issues (with checkboxes)
3. **Integration Flow**:
   ```
   CodeRabbit Issue --> Improvement Proposal --> Sandbox Testing --> Deploy
   ```
4. **Proposal Metadata**: Tracks source=coderabbit, original issue_id

### Sandbox Manager Integration
Issues sent to Improvements Lab flow to Sandbox Manager:
1. Proposal created with module detection from file path
2. Sandbox Manager routes to correct module sandbox
3. Tests run in isolated environment
4. Success: Deploy to production, mark issue fixed
5. Failure: Record mistake_learned, return for revision

## Configuration

### Ollama Settings
```python
OLLAMA_PRIMARY = '192.168.1.246:11434'
OLLAMA_SECONDARY = '192.168.1.245:11434'
```

### Scan Limits
- Max batch size: 20 files
- Max file list: 200 files
- Excluded: `__init__.py`, `__pycache__`, `node_modules`, `_deprecated`

## Usage Examples

### Scan a Single File
```bash
curl -X POST http://localhost:3000/tools/coderabbit/api/health/scan \
  -H "Content-Type: application/json" \
  -d '{"file_path": "platform_v2/app.py", "full_path": "/app/app.py"}'
```

### Get Scan History
```bash
curl http://localhost:3000/tools/coderabbit/api/health/scans?limit=10
```

### Check AI Status
```bash
curl http://localhost:3000/tools/coderabbit/api/ai-status
```

## Scoring Algorithm

```
Base Score: 100
- Critical issues: -25 each
- High issues: -15 each
- Medium issues: -5 each
- Low issues: -2 each
Minimum: 0
```

## File Structure

```
/tools/coderabbit/
    __init__.py
    routes.py           # All API endpoints and logic

/templates/tools/
    coderabbit.html     # UI with file browser and results
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.2.1 | 2026-01-16 | Added CI workflow (.github/workflows/ci.yml) for automated testing |
| 2.2.0 | 2026-01-15 | Git Manager consolidation: Branch management, GitHub Issues tab, GitHub Actions tab |
| 2.1.0 | 2026-01-15 | CodeRabbit → Improvements Lab integration, Create PR UI, Merge PR, full workflow |
| 2.0.0 | 2026-01-15 | Major optimization: Modified file detection, PR review status, bidirectional issue tracking, scan cache persistence, UI polish |
| 1.1.0 | 2026-01-13 | Added Send to Improvements workflow, Sandbox integration |
| 1.0.0 | 2026-01-12 | Initial release with code health scanner |

### v2.2.0 Detailed Changes - Git Manager Consolidation
Consolidated GitHub Manager module functionality into CodeRabbit's Git Manager tab.

**New Features:**
- **Git Manager Tab** (renamed from "Local Git"):
  - Branch selector dropdown for quick switching
  - Create/delete branches with protection for main/master
  - View local and remote branches with tracking info
  - Branch management section with visual indicators

- **GitHub Issues Tab**:
  - List open/closed issues with filtering
  - Create new issues with labels
  - Close/reopen issues directly
  - Issue counts and quick stats

- **GitHub Actions Tab**:
  - View recent workflow runs with status
  - Success/failure/in-progress indicators
  - Re-run failed workflows
  - Workflow run statistics

**New Endpoints (v2.2.0):**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/git/branches` | List all local and remote branches |
| POST | `/api/git/create-branch` | Create new branch with optional checkout |
| POST | `/api/git/checkout` | Switch to a different branch |
| POST | `/api/git/delete-branch` | Delete a local branch (protected branches blocked) |
| GET | `/api/github/issues` | List repository issues (filterable by state) |
| POST | `/api/github/issues` | Create a new GitHub issue |
| PATCH | `/api/github/issues/<number>` | Update issue state (close/reopen) |
| GET | `/api/github/actions/runs` | List recent workflow runs |
| GET | `/api/github/actions/workflows` | List available workflows |
| POST | `/api/github/actions/runs/<id>/rerun` | Re-run a failed workflow |

**Module Consolidation:**
- Disabled standalone GitHub Manager module (`enabled=False`)
- All planned GitHub Manager features now in CodeRabbit
- Tab navigation: PR Reviews | Git Manager | GitHub Issues | Actions | Code Health | Code Issues

### v2.2.1 - CI Workflow Addition
Added GitHub Actions CI workflow for automated code quality checks.

**Workflow File:** `.github/workflows/ci.yml`

**Jobs:**
| Job | Purpose | Status |
|-----|---------|--------|
| Lint & Syntax Check | Python syntax validation, flake8 linting | Non-blocking |
| Security Scan | Bandit security analysis | Non-blocking |
| Docker Build Test | Verify Dockerfile builds successfully | Blocking |

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches

**GitHub Token Permissions Required:**
- `workflow` - To push workflow files
- `actions:read` - To view workflow runs
- `actions:write` - To re-run failed workflows
- `issues:read/write` - To manage issues

### v2.1.0 Detailed Changes - Improvements Lab Integration
- **PR Suggestions to Proposals**: Extract CodeRabbit review suggestions and send to Improvements Lab
- **Create PR UI**: New "Create Pull Request" section in Local Git tab with title, description, base/head branch
- **Merge PR Button**: Merge PRs directly from CodeRabbit after fixes deployed
- **Suggestion Modal**: View all CodeRabbit suggestions with checkboxes, select which to send
- **Auto-Categorization**: Suggestions auto-categorized as security, performance, bug_fix, code_quality
- **PR Context Tracking**: Proposals include pr_number, pr_url, repo in metadata

**New Endpoints (v2.1.0):**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/pr/<number>/review-comments` | Fetch CodeRabbit suggestions from PR |
| POST | `/api/pr/suggestions-to-improvements` | Create proposals from selected suggestions |
| POST | `/api/pr/<number>/merge` | Merge PR into base branch |
| POST | `/api/git/create-pr` | Create new PR from current branch |

**Complete Workflow:**
```
Create Feature Branch → Make Changes → Commit → Push → Create PR (via UI) →
CodeRabbit Reviews → View Suggestions → Send to Improvements Lab →
Test in Sandbox → Deploy Fix → Merge PR
```

### v2.0.0 Detailed Changes
- **Database**: Added `proposal_id` column to `code_issues` for bidirectional tracking
- **Modified File Detection**: New `/api/health/files-needing-rescan` endpoint, "MODIFIED" badges, "Rescan Modified" button
- **PR Reviews**: CodeRabbit review status badges on PRs, "Request Review" button
- **Issue Tracking**: Status-aware badges linking to Improvements Lab proposals
- **UI Polish**: Fixed folder toggle quote escaping, sessionStorage cache persistence
- **Bug Fix**: Git commit parameter mismatch (`stage_all` vs `add_all`)

---

**Last Updated:** 2026-01-15
**Author:** A.R.C.H.I.E. Platform
