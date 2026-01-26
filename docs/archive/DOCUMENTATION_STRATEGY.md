# A.R.C.H.I.E. Documentation Strategy & Best Practices

**Created**: 2025-12-29
**Purpose**: Guide for maintaining comprehensive, useful documentation

---

## 📋 Current Documentation Status

### ✅ What We Have (Good Coverage)

1. **AGENT_DIRECTORY.md** - Complete agent roster with visual interface docs
2. **ARCHIE_CONSCIOUSNESS.md** - Memory and awareness system
3. **ADMIN_REFERENCE.md** - Admin panel reference
4. **DEPLOYMENT_INSTRUCTIONS.md** - How to deploy the platform
5. **BACKUP_RECOVERY_GUIDE.md** - Backup and recovery procedures
6. **FILE_STRUCTURE_MASTER.md** - Codebase organization
7. **UPDATES_2025-12-29.md** - Recent changes log

### 🚨 Critical Missing Documents

These should be created to improve maintainability:

#### 1. **CHANGELOG.md** (CRITICAL)
**Purpose**: Standardized version history

**Format**: Follow [Keep a Changelog](https://keepachangelog.com/) convention
```markdown
# Changelog

All notable changes to A.R.C.H.I.E. Platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Feature additions go here

### Changed
- Changes in existing functionality

### Deprecated
- Soon-to-be removed features

### Removed
- Now removed features

### Fixed
- Bug fixes

### Security
- Security updates

## [1.2.0] - 2025-12-29

### Added
- Agent Directory visual interface with profile pictures
- Clickable agent cards with detailed modal
- Knowledge Management file browser with three-tier status tracking
- New Tags alert system with auto-hide and manual dismiss
- SHOW ALL button for browsing all memories

### Changed
- Quick Add Knowledge importance changed to dropdown (was number input)
- Search interface optimized with results limit selector
- Agent cards now display profile pictures (80x80px circular avatars)

### Removed
- Redundant "Ingest from DOCS Directory" section
```

**Why**: Industry standard, easy to scan, machine-readable

---

#### 2. **API_REFERENCE.md** (HIGH PRIORITY)
**Purpose**: Document all backend API endpoints

**Format**:
```markdown
# A.R.C.H.I.E. Platform - API Reference

## Admin Panel Endpoints

### Consciousness & Memory

#### GET /tools/admin/consciousness/stats
Returns comprehensive consciousness statistics.

**Authentication**: Required (login_required)

**Response**:
```json
{
  "success": true,
  "total_knowledge": 178,
  "memory_types": [...],
  "categories": [...],
  "tags": 60,
  "new_tags": [...]
}
```

**Used By**: Admin Panel → CONSCIOUSNESS → Knowledge Analytics

---

#### POST /tools/admin/consciousness/browse-files
Browse documentation files with ingestion status.

**Authentication**: Required

**Request Body**:
```json
{
  "path": "/mnt/archie_brain/docs"
}
```

**Response**:
```json
{
  "success": true,
  "files": [
    {
      "name": "ADMIN_REFERENCE.md",
      "path": "ADMIN_REFERENCE.md",
      "size": 9530,
      "modified": "2025-12-27T15:15:00",
      "ingested": true,
      "last_ingested": "2025-12-29T18:00:00",
      "needs_update": false
    }
  ]
}
```

**File**: `tools/admin/routes.py` (line 3040)
```

**Why**: Helps developers understand available endpoints, request/response formats

---

#### 3. **DATABASE_SCHEMA.md** (HIGH PRIORITY)
**Purpose**: Document database structure

**Format**:
```markdown
# A.R.C.H.I.E. Database Schema

**Database**: PostgreSQL 16
**Container**: archie_database

## Tables Overview

| Table | Purpose | Records (approx) |
|-------|---------|------------------|
| agents | AI team member profiles | 58 |
| long_term_memory | A.R.C.H.I.E.'s persistent memory | 178 |
| conversations | Chat history | ~1000 |
| agent_types | Agent type definitions | 20 |
| users | User accounts | 10 |

---

## Table: agents

**Purpose**: Stores AI agent profiles and metadata

**Columns**:
| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | UUID | NO | gen_random_uuid() | Primary key |
| name | VARCHAR(200) | NO | - | Full agent name |
| first_name | VARCHAR(100) | NO | - | First name |
| last_name | VARCHAR(100) | NO | - | Last name |
| email | VARCHAR(200) | YES | - | Contact email |
| title | VARCHAR(200) | NO | - | Job title |
| department | VARCHAR(100) | YES | - | Department |
| pronouns | VARCHAR(50) | YES | - | Preferred pronouns |
| bio | TEXT | YES | - | Biography |
| avatar_url | VARCHAR(500) | YES | - | Profile picture URL |
| system_prompt | TEXT | YES | - | Agent's system prompt |
| capabilities | JSONB | YES | - | Skills, tools, specialties |
| tier | INTEGER | NO | 1 | Tier level (1-3) |
| model | VARCHAR(100) | NO | - | Claude model ID |
| monthly_budget | DECIMAL(10,2) | YES | - | Budget allocation |
| total_cost | DECIMAL(10,2) | YES | 0 | Lifetime cost |
| total_tokens_used | BIGINT | YES | 0 | Lifetime tokens |
| status | VARCHAR(50) | NO | 'active' | active/inactive |
| created_at | TIMESTAMP | NO | NOW() | Creation time |
| last_used | TIMESTAMP | YES | - | Last execution |

**Indexes**:
- PRIMARY KEY on `id`
- INDEX on `department`
- INDEX on `status`
- INDEX on `email`

**Relationships**:
- `type_id` → `agent_types.id` (foreign key)

---

## Table: long_term_memory

**Purpose**: A.R.C.H.I.E.'s persistent knowledge base

**Columns**:
| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | NO | Primary key |
| content | TEXT | NO | Memory content |
| category | VARCHAR(100) | YES | business/technical/procedure/etc |
| memory_type | VARCHAR(100) | YES | Type classification |
| tags | TEXT[] | YES | Array of tags |
| importance_score | DECIMAL(3,2) | YES | 0.0-1.0 importance |
| metadata | JSONB | YES | Additional metadata |
| user_id | INTEGER | YES | Related user |
| access_count | INTEGER | YES | Times accessed |
| created_at | TIMESTAMP | NO | When stored |
| last_accessed | TIMESTAMP | YES | Last retrieval |

**Indexes**:
- PRIMARY KEY on `id`
- GIN INDEX on `tags`
- INDEX on `category`
- INDEX on `created_at DESC`
- INDEX on `importance_score DESC`

**Sample Query**:
```sql
-- Get all memories about Docker
SELECT * FROM long_term_memory
WHERE 'docker' = ANY(tags)
ORDER BY importance_score DESC, created_at DESC;
```
```

**Why**: Essential for database migrations, troubleshooting, new developer onboarding

---

#### 4. **TROUBLESHOOTING.md** (MEDIUM PRIORITY)
**Purpose**: Common issues and solutions

**Format**:
```markdown
# A.R.C.H.I.E. Platform - Troubleshooting Guide

## Common Issues

### Issue: Container fails to start
**Symptoms**: `docker-compose up` exits immediately
**Cause**: Missing environment variables
**Solution**:
```bash
# Check .env file exists
ls -la /mnt/archie_brain/.env

# Verify required variables
grep -E "SECRET_KEY|DB_PASSWORD|FLASK_SECRET_KEY" .env

# If missing, regenerate
python3 /mnt/archie_brain/scripts/generate_secrets.py
```

---

### Issue: "No module named 'pytz'" error
**Symptoms**: Platform crashes with import error
**Cause**: Missing Python dependency
**Solution**:
```bash
# Install inside container
docker exec archie_platform pip install pytz

# OR rebuild container
docker-compose build archie_platform
docker-compose restart archie_platform
```

---

### Issue: File browser not showing files
**Symptoms**: Documentation Files Browser is empty
**Cause**: Path issue in loadFilesBrowser() function
**Solution**: Check that path is hardcoded to `/mnt/archie_brain/docs`
**File**: templates/tools/admin.html (line 3148)

---

### Issue: Agent Directory shows no agents
**Symptoms**: Directory grid is empty
**Cause**: Database connection issue or agents not loaded
**Solution**:
```bash
# Check database
docker exec archie_database psql -U archie -d archie -c "SELECT COUNT(*) FROM agents WHERE status='active';"

# Should return 58

# If 0, run migration
docker exec archie_platform python3 /mnt/archie_brain/database/migrations/add_content_creators.py
```
```

**Why**: Saves time debugging, helps new developers

---

#### 5. **ARCHITECTURE.md** (MEDIUM PRIORITY)
**Purpose**: High-level system architecture

**Format**:
```markdown
# A.R.C.H.I.E. Platform - System Architecture

## Overview

A.R.C.H.I.E. is a containerized platform built on Flask + PostgreSQL + n8n.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                   (archie_network)                       │
│                                                          │
│  ┌──────────────┐     ┌──────────────┐                 │
│  │   archie_    │────▶│   archie_    │                 │
│  │  platform    │     │  database    │                 │
│  │  (Flask)     │     │ (PostgreSQL) │                 │
│  │  Port 3000   │     │  Port 5432   │                 │
│  └──────────────┘     └──────────────┘                 │
│         │                                               │
│         │                                               │
│  ┌──────────────┐     ┌──────────────┐                 │
│  │  archie_n8n  │     │archie_nginx_ │                 │
│  │  (Workflows) │────▶│     n8n      │                 │
│  │  Port 5678   │     │ Port 5679    │                 │
│  └──────────────┘     └──────────────┘                 │
└─────────────────────────────────────────────────────────┘
         │                      │
         ▼                      ▼
    External Users        Automation Webhooks
```

## Components

### archie_platform (Flask Application)
- **Technology**: Python 3.11 + Flask + Gunicorn
- **Purpose**: Main web application and admin panel
- **Key Features**:
  - Agent management
  - Consciousness system
  - Long-term memory
  - Admin tools
- **File**: `/platform_v2/`
- **Entry Point**: `app.py`

### archie_database (PostgreSQL)
- **Technology**: PostgreSQL 16-alpine
- **Purpose**: Persistent data storage
- **Tables**: agents, long_term_memory, conversations, etc.
- **Backup**: Daily automated backups to `/backups/`

### archie_n8n (Workflow Automation)
- **Technology**: n8n (Node.js)
- **Purpose**: Workflow automation and agent orchestration
- **Access**: Via nginx reverse proxy on port 5679

## Data Flow

### User Interaction Flow:
1. User accesses admin panel → `http://localhost:3000`
2. Flask serves `templates/tools/admin.html`
3. JavaScript makes API calls → `/tools/admin/*` endpoints
4. Backend queries PostgreSQL database
5. Response returned as JSON
6. Frontend renders data

### Memory Storage Flow:
1. User has conversation with A.R.C.H.I.E.
2. `consciousness/memory_manager.py` extracts important info
3. Stored in `long_term_memory` table with tags
4. Future queries can recall this memory
5. Access count incremented on retrieval

### Agent Execution Flow:
1. User requests agent task
2. System loads agent profile from database
3. Constructs prompt with system_prompt + task
4. Calls Claude API with agent's model
5. Stores execution record
6. Updates usage statistics (cost, tokens)
```

**Why**: Helps understand system design, guides architectural decisions

---

#### 6. **DEVELOPMENT_GUIDE.md** (MEDIUM PRIORITY)
**Purpose**: Setup and development workflow

**Format**:
```markdown
# A.R.C.H.I.E. Platform - Development Guide

## Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local testing)
- Git
- Text editor (VS Code recommended)

## Initial Setup

### 1. Clone Repository
```bash
git clone <repo-url>
cd archie_brain
```

### 2. Generate Secrets
```bash
python3 scripts/generate_secrets.py
# Creates .env file with secure keys
```

### 3. Start Platform
```bash
docker-compose up -d
# Wait 30-60 seconds for initialization
```

### 4. Verify Running
```bash
docker-compose ps
# All services should be "Up"

curl http://localhost:3000/health
# Should return: {"status": "healthy"}
```

## Development Workflow

### Making Changes to Platform Code

**Frontend (HTML/CSS/JavaScript)**:
1. Edit files in `/platform_v2/templates/`
2. Restart platform: `docker-compose restart archie_platform`
3. Hard refresh browser: Ctrl+Shift+R

**Backend (Python)**:
1. Edit files in `/platform_v2/` or `/platform_v2/tools/`
2. Clear Python cache: `find /mnt/archie_brain/platform_v2 -type d -name __pycache__ -exec rm -rf {} +`
3. Restart platform: `docker-compose restart archie_platform`
4. Check logs: `docker logs archie_platform --tail 50`

**Database Migrations**:
1. Create migration script in `/database/migrations/`
2. Run: `docker exec archie_platform python3 /mnt/archie_brain/database/migrations/your_migration.py`
3. Verify: `docker exec archie_database psql -U archie -d archie -c "SELECT * FROM your_table LIMIT 5;"`

### Code Style Guidelines

**Python**:
- PEP 8 style guide
- 4 spaces indentation
- Docstrings for functions
- Type hints recommended

**JavaScript**:
- camelCase for variables
- async/await for API calls
- Clear function names
- Comments for complex logic

**File Organization**:
```
platform_v2/
├── app.py              # Main Flask application
├── tools/
│   ├── admin/
│   │   ├── routes.py   # Admin panel backend
│   │   └── __init__.py
│   └── ...
├── templates/
│   ├── tools/
│   │   └── admin.html  # Admin panel frontend
│   └── ...
└── consciousness/
    ├── archie_consciousness.py  # Awareness system
    └── memory_manager.py        # Memory operations
```

## Testing

### Manual Testing Checklist
- [ ] Platform starts without errors
- [ ] Admin panel loads at http://localhost:3000/tools/admin
- [ ] Agent Directory shows 58 agents
- [ ] Consciousness section loads statistics
- [ ] File browser displays files
- [ ] Search knowledge works
- [ ] Add manual knowledge works

### Database Testing
```bash
# Connect to database
docker exec -it archie_database psql -U archie -d archie

# Check agent count
SELECT COUNT(*) FROM agents WHERE status='active';
# Should be 58

# Check memory count
SELECT COUNT(*) FROM long_term_memory;

# Exit
\q
```

## Debugging

### View Logs
```bash
# Platform logs
docker logs archie_platform -f

# Database logs
docker logs archie_database -f

# All services
docker-compose logs -f
```

### Common Debug Commands
```bash
# Restart everything
docker-compose restart

# Rebuild platform
docker-compose build archie_platform
docker-compose up -d archie_platform

# Database shell
docker exec -it archie_database psql -U archie -d archie

# Platform shell
docker exec -it archie_platform bash
```
```

**Why**: Onboards new developers quickly, standardizes workflow

---

#### 7. **CONTRIBUTING.md** (LOW PRIORITY)
**Purpose**: Guidelines for contributors

**Format**:
```markdown
# Contributing to A.R.C.H.I.E. Platform

## How to Contribute

1. **Document First**: Before making changes, document what you plan to do
2. **Test Locally**: Always test changes before committing
3. **Update Docs**: Update documentation to match your changes
4. **Follow Conventions**: Use existing code style and patterns

## Pull Request Process

1. Create feature branch: `git checkout -b feature/your-feature`
2. Make changes
3. Test thoroughly
4. Update documentation
5. Commit with clear message
6. Submit PR with description

## Commit Message Format

```
type(scope): Brief description

Detailed explanation of what changed and why.

Fixes #issue_number
```

**Types**: feat, fix, docs, style, refactor, test, chore

**Examples**:
- `feat(directory): Add profile pictures to agent cards`
- `fix(consciousness): Fix file browser path issue`
- `docs(api): Document consciousness endpoints`

## Code Review Checklist

- [ ] Code follows existing patterns
- [ ] No hardcoded credentials
- [ ] Functions have docstrings
- [ ] Changes tested manually
- [ ] Documentation updated
- [ ] No console.log() left in code
- [ ] Database migrations included if needed
```

**Why**: Maintains code quality, helps future contributors

---

#### 8. **SECURITY.md** (MEDIUM PRIORITY)
**Purpose**: Security considerations and best practices

**Format**:
```markdown
# A.R.C.H.I.E. Platform - Security Guidelines

## Credentials Management

### ✅ DO
- Store secrets in `.env` file (NOT committed to git)
- Use environment variables for API keys
- Rotate secrets regularly
- Use strong, random passwords

### ❌ DON'T
- Hardcode credentials in source code
- Commit `.env` to version control
- Share credentials in documentation
- Use default/weak passwords

## Current Security Measures

1. **Environment Variables**:
   - All secrets in `.env` file
   - `.gitignore` prevents committing secrets
   - `generate_secrets.py` creates secure random keys

2. **Database**:
   - PostgreSQL only accessible from Docker network
   - Port 5432 bound to localhost only
   - User credentials in environment variables

3. **Web Application**:
   - Flask secret key for session security
   - Login required decorator on admin endpoints
   - No direct SQL queries from user input

## Vulnerability Reporting

If you discover a security vulnerability, please email:
security@archie.ai (replace with actual contact)

**DO NOT** open public GitHub issues for security vulnerabilities.
```

**Why**: Protects the platform, guides secure development

---

## 📁 Suggested Documentation Organization

### Directory Structure
```
/docs/
├── README.md                       # Overview & quick start
├── CHANGELOG.md                    # Version history ⭐ NEW
│
├── getting-started/
│   ├── QUICK_START.md             # 5-minute setup
│   ├── DEPLOYMENT_INSTRUCTIONS.md  # Full deployment
│   └── DEVELOPMENT_GUIDE.md       # Dev setup ⭐ NEW
│
├── architecture/
│   ├── ARCHITECTURE.md            # System design ⭐ NEW
│   ├── DATABASE_SCHEMA.md         # DB structure ⭐ NEW
│   └── FILE_STRUCTURE_MASTER.md   # Existing
│
├── features/
│   ├── ARCHIE_CONSCIOUSNESS.md    # Existing (updated)
│   ├── AGENT_DIRECTORY.md         # Existing (updated)
│   ├── BUSINESS_AGENTS_GUIDE.md   # Existing
│   └── AI_POWERED_APPS.md         # Existing
│
├── api/
│   └── API_REFERENCE.md           # Endpoints ⭐ NEW
│
├── operations/
│   ├── ADMIN_REFERENCE.md         # Existing
│   ├── BACKUP_RECOVERY_GUIDE.md   # Existing
│   ├── DEPLOYMENT_CHECKLIST.md    # Existing
│   └── TROUBLESHOOTING.md         # Common issues ⭐ NEW
│
├── contributing/
│   ├── CONTRIBUTING.md            # Contribution guide ⭐ NEW
│   ├── SECURITY.md                # Security practices ⭐ NEW
│   └── DOCUMENTATION_STRATEGY.md  # This file ⭐ NEW
│
└── archive/
    ├── UPDATES_2025-12-29.md      # Move old updates here
    ├── BACKUP_MANAGER_FIX_SUMMARY.md
    └── SESSION_HANDOFF.md         # Move session-specific docs
```

---

## 🔄 Documentation Workflow

### When Making Changes

**REQUIRED STEPS** (every change):
1. ✅ Make code changes
2. ✅ Test changes locally
3. ✅ Update CHANGELOG.md with entry
4. ✅ Update relevant feature docs
5. ✅ Restart platform and verify
6. ✅ Commit with descriptive message

**Example Workflow**:
```bash
# 1. Make changes
vim /mnt/archie_brain/platform_v2/templates/tools/admin.html

# 2. Test
docker-compose restart archie_platform
# Open browser and test

# 3. Document in CHANGELOG
vim /mnt/archie_brain/docs/CHANGELOG.md
# Add entry under [Unreleased] section

# 4. Update feature docs
vim /mnt/archie_brain/docs/ARCHIE_CONSCIOUSNESS.md
# Add new feature description

# 5. Commit
git add .
git commit -m "feat(consciousness): Add new tags alert system with auto-hide

- Added 24-hour auto-hide functionality
- Added manual dismiss button
- Uses localStorage for persistence

Updated documentation:
- CHANGELOG.md
- ARCHIE_CONSCIOUSNESS.md"

# 6. Push
git push origin main
```

---

## 📝 Documentation Templates

### Feature Documentation Template

```markdown
# Feature Name

**Last Updated**: YYYY-MM-DD
**Status**: Active/Beta/Deprecated

## Overview

Brief description of what this feature does and why it exists.

## Accessing the Feature

1. Navigate to: Path/to/feature
2. Click: Button name
3. View: What appears

## Features & Capabilities

### Feature 1: Name
Description of feature 1

**How to Use**:
1. Step 1
2. Step 2
3. Step 3

**Example**:
```
Example usage
```

### Feature 2: Name
Description of feature 2

## Technical Implementation

**Backend Endpoint**: `/path/to/endpoint`

**Request**:
```json
{
  "param": "value"
}
```

**Response**:
```json
{
  "success": true,
  "data": {}
}
```

**Files**:
- `backend_file.py` (line XX)
- `frontend_file.html` (line YY)

## Use Cases

### Scenario 1: Name
1. User does X
2. System does Y
3. Result is Z

### Scenario 2: Name
1. Different scenario
2. Different flow

## Troubleshooting

### Issue: Problem description
**Solution**: How to fix

### Issue: Another problem
**Solution**: Another fix
```

---

### Changelog Entry Template

```markdown
## [Version] - YYYY-MM-DD

### Added
- New feature description [#PR_NUMBER]
- Another new feature [#PR_NUMBER]

### Changed
- Modified behavior description [#PR_NUMBER]
- Another change [#PR_NUMBER]

### Fixed
- Bug fix description [#PR_NUMBER]
- Another bug fix [#PR_NUMBER]

### Deprecated
- Feature that will be removed [#PR_NUMBER]

### Removed
- Removed feature [#PR_NUMBER]

### Security
- Security improvement [#PR_NUMBER]
```

---

## 🎯 Priorities for Implementation

### Immediate (This Week):
1. ⭐ **CHANGELOG.md** - Start tracking versions properly
2. ⭐ **API_REFERENCE.md** - Document existing endpoints
3. ⭐ **DATABASE_SCHEMA.md** - Document database structure

### Short-term (This Month):
4. **TROUBLESHOOTING.md** - Capture common issues
5. **ARCHITECTURE.md** - High-level system design
6. **DEVELOPMENT_GUIDE.md** - Onboarding for developers

### Long-term (As Needed):
7. **CONTRIBUTING.md** - When opening to contributors
8. **SECURITY.md** - As security practices mature
9. Reorganize docs into subdirectories (when > 30 files)

---

## 🔍 Documentation Quality Checklist

Good documentation should be:
- [ ] **Accurate**: Matches current implementation
- [ ] **Complete**: Covers all major features
- [ ] **Clear**: Easy to understand
- [ ] **Current**: Updated with changes
- [ ] **Discoverable**: Easy to find
- [ ] **Examples**: Includes real examples
- [ ] **Formatted**: Consistent markdown style
- [ ] **Indexed**: Listed in README

---

## 💡 Best Practices

### DO:
- ✅ Update docs when you change code
- ✅ Use clear, descriptive headings
- ✅ Include code examples
- ✅ Add diagrams when helpful
- ✅ Link between related docs
- ✅ Date your documentation
- ✅ Use markdown formatting
- ✅ Keep sentences concise

### DON'T:
- ❌ Let docs get outdated
- ❌ Assume prior knowledge
- ❌ Use vague language
- ❌ Skip examples
- ❌ Write walls of text
- ❌ Duplicate information
- ❌ Forget to link files

---

## 🚀 Quick Reference

### When to Update Which Doc

| Change Type | Update These Docs |
|-------------|-------------------|
| New feature | CHANGELOG.md + feature doc + API_REFERENCE.md (if endpoints) |
| Bug fix | CHANGELOG.md + TROUBLESHOOTING.md (if common) |
| Breaking change | CHANGELOG.md + all affected feature docs + MIGRATION_GUIDE.md |
| New endpoint | API_REFERENCE.md + CHANGELOG.md |
| Database change | DATABASE_SCHEMA.md + CHANGELOG.md |
| Architecture change | ARCHITECTURE.md + CHANGELOG.md |
| Security update | SECURITY.md + CHANGELOG.md |

---

**Remember**: Documentation is code. Treat it with the same care and attention.
