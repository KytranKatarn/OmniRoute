# Improvement Workflow Optimization Plan

**Date Created:** 2025-12-31
**Status:** ✅ APPROVED - Implementation Started 2026-01-01
**Objective:** Transform the improvement proposals system into an automated, team-based workflow with Claude Code-style chat, safety protocols, and intelligent agent assignment

---

## 📋 Executive Summary

This plan will create a comprehensive improvement workflow that:
- Automates proposal routing and team assignment
- Implements internal-first staffing (staff → contractors)
- Adds development sandbox for safe testing
- Integrates Claude Code-style interactive development chat
- Establishes backup/test/deploy/revert safety protocol
- Uses A.R.C.H.I.E. to build and manage implementation teams

---

## 🎯 Current State Analysis

### Problems Identified:
1. ❌ Proposals stuck in "Pending" with no action available
2. ❌ "Escalate to Senior" button doesn't work properly
3. ❌ No automated workflow or team assignment
4. ❌ Chat doesn't reliably create proposals from natural language
5. ❌ No development sandbox for testing
6. ❌ Manual backup integration before code changes
7. ❌ No internal-first contractor routing

### Current System Capabilities:

**Improvement Proposals:**
- 📊 **Database**: `improvement_proposals` table (22 fields) + `improvement_conversations` table
- 🔄 **Workflow States**: proposed → pending_approval → approved → deployed → executed/failed/escalated
- 🛠️ **20+ API Endpoints**: Full CRUD, approval, rejection, execution, escalation
- 💬 **Chat Integration**: improvement_chat.py with 3 main functions
- 🤖 **Auto-Detection**: Runs every 6 hours, detects 5 types of issues
- ⚙️ **Manager Class**: Handles test→approve→deploy→execute flow

**Agent System:**
- 👥 **73+ Agents**: Across 8+ departments (Ops, QA, Engineering, Sales, etc.)
- 💰 **Worker Types**: 'internal' (FREE - Ollama) vs 'contract' (PAID - API providers)
- 🎯 **Skills System**: agent_skills table with proficiency levels + escalation chains
- 📞 **Call Queue**: Priority-based assignment for telephony/chat
- ❌ **Gap**: NO team assignment logic for improvements

**Backup & Safety:**
- 💾 **Backup Manager**: 11-component backups (database, platform, AI bridge, docs, etc.)
- ⏮️ **Restore**: Auto-generated rollback.sh scripts per backup
- 🔒 **Safety Checks**: Syntax validation, security scanning, health checks
- 🐳 **Docker**: Production-only (no dev/staging environment)
- ⚠️ **Gap**: Manual migrations, no automated sandbox

---

## 🏗️ Architecture Overview

### Enhanced Workflow (Target State):
```
User Chat Request
    ↓
Enhanced Chat (Claude Code Style)
├─ Natural Language Understanding
├─ Auto-Create Proposal
├─ Show Code Diffs/Preview
├─ Step-by-Step Guidance
└─ Direct File Editing
    ↓
Auto-Team Assignment Engine
├─ Analyze Required Skills
├─ Match to Agent Capabilities
├─ Internal First (FREE agents)
├─ Fallback to Contractors (PAID)
└─ Build Multi-Agent Team
    ↓
Automated Safety Protocol
├─ Auto-Backup (via Backup Manager)
├─ Create Sandbox (Docker or Schema)
├─ Run Tests in Sandbox
└─ Validation Gates
    ↓
Team Implementation
├─ Assign Tasks to Team Members
├─ Track Progress
├─ Real-Time Updates
└─ Quality Checks
    ↓
Deployment Decision
├─ Auto-Deploy (Low Risk)
├─ Admin Approval (High Risk)
└─ Rollback Available
    ↓
Post-Deployment
├─ Monitor for Issues
├─ Auto-Rollback on Failure
├─ Learning/Feedback Loop
└─ Update Agent Skills
```

### User Preferences (From Q&A):
- ✅ **Sandbox**: Hybrid (Full container for major, schema for minor)
- ✅ **Chat**: Full Claude Code experience (all 4 features)
- ✅ **Team Assignment**: Fully automatic
- ✅ **External Integrations**: Phase 4+ (Future)

---

## 🔧 Components to Build

### 1. Enhanced Chat System (Claude Code Style)
**Goal**: Transform chat into interactive development assistant

**Features**:
- ✅ Natural language proposal creation (e.g., "optimize error handling" → auto-creates proposal)
- ✅ Code diff visualization (before/after comparison with syntax highlighting)
- ✅ Step-by-step implementation guidance (breaks work into phases)
- ✅ Direct file editing with "Apply" button (like Claude Code)
- ✅ Real-time feedback and validation
- ✅ Conversation context retention

**Files to Modify**:
- `/mnt/archie_brain/ai_bridge/improvement_chat.py` - Enhance chat_about_improvements()
- `/mnt/archie_brain/platform_v2/templates/ (now modular templates)` - Add diff viewer UI
- New file: `/mnt/archie_brain/ai_bridge/code_diff_engine.py` - Diff generation

### 2. Team Assignment Engine
**Goal**: Automatically build and assign teams to improvements

**Core Algorithm**:
```python
1. Analyze proposal (category, priority, complexity)
2. Determine required skills from category
3. Query agents with matching skills
4. Filter by worker_type (internal first)
5. Check availability (last_used, current assignments)
6. Build team (1-3 agents based on complexity)
7. Create team_assignments records
8. Notify team members
```

**Internal-First Routing**:
- Query `SELECT * FROM agents WHERE worker_type='internal' AND status='active'`
- If no match or over-capacity → escalate to contractors
- Track fallback reason for learning

**Files to Create**:
- `/mnt/archie_brain/ai_bridge/team_assignment_engine.py` - Core engine
- `/mnt/archie_brain/platform_v2/team_assignment_api.py` - API wrapper

**Files to Modify**:
- `/mnt/archie_brain/ai_bridge/improvement_engine.py` - Add auto-assignment on proposal creation

### 3. Development Sandbox (Hybrid Approach)
**Goal**: Safe testing environment before production

**Sandbox Types**:

**A. Full Docker Container (Major Changes)**:
```yaml
# New service in docker-compose.yml
archie_sandbox:
  image: archie_brain-archie_platform
  container_name: archie_sandbox
  environment:
    FLASK_ENV: sandbox
    DB_HOST: archie_sandbox_db
  ports:
    - "3001:3000"  # Different port
  volumes:
    - ./sandbox:/app
    - ./backups:/backups:ro  # Read-only backups

archie_sandbox_db:
  image: postgres:15
  container_name: archie_sandbox_db
  environment:
    POSTGRES_DB: archie_sandbox
```

**B. Schema Separation (Minor Changes)**:
```sql
CREATE SCHEMA IF NOT EXISTS sandbox;
SET search_path TO sandbox, public;
-- Clone tables into sandbox schema
CREATE TABLE sandbox.improvement_proposals AS
  SELECT * FROM public.improvement_proposals;
```

**Decision Logic**:
- High priority OR risk_level='high' → Full container
- Medium/Low priority → Schema separation
- User can override

**Files to Create**:
- `/mnt/archie_brain/platform_v2/sandbox_manager.py` - Sandbox orchestration
- `/mnt/archie_brain/platform_v2/docker-compose.sandbox.yml` - Sandbox config

### 4. Safety Protocol Integration
**Goal**: Automated backup → test → deploy → rollback

**Workflow**:
```python
def safe_deploy(proposal_id):
    # 1. Auto-backup
    backup_name = f"pre_improvement_{proposal_id}_{timestamp}"
    create_backup(name=backup_name, type='critical')

    # 2. Create sandbox
    sandbox_id = create_sandbox(proposal_id, risk_level)

    # 3. Apply changes in sandbox
    apply_code_changes(sandbox_id, proposal.code_changes)

    # 4. Run tests
    test_results = run_sandbox_tests(sandbox_id)

    # 5. Validation gate
    if not test_results.passed:
        rollback(backup_name)
        return FAILED

    # 6. Deploy to production
    deploy_to_production(proposal_id)

    # 7. Health check
    if not health_check_passed():
        auto_rollback(backup_name)
        return ROLLED_BACK

    return SUCCESS
```

**Files to Create**:
- `/mnt/archie_brain/platform_v2/safe_deployment_protocol.py`

**Files to Modify**:
- `/mnt/archie_brain/platform_v2/tools/improvements/manager.py` - Integrate safe_deploy()
- `/mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py` - Add API trigger

### 5. Workflow Automation
**Goal**: End-to-end automation with safety checks

**Auto-Progression Rules**:
```python
# Status transitions
proposed → (chat creates) → pending_approval
pending_approval → (team assigned) → in_progress
in_progress → (team completes) → ready_for_test
ready_for_test → (tests pass) → approved
approved → (backup created) → deploying
deploying → (health check pass) → deployed
deployed → (24hr monitoring) → completed

# Auto-escalation triggers
- stuck_in_pending > 48 hours → escalate
- test_failures > 3 → escalate
- deployment_failed → auto-rollback + escalate
```

**Files to Create**:
- `/mnt/archie_brain/ai_bridge/workflow_automator.py`
- `/mnt/archie_brain/ai_bridge/escalation_handler.py`

---

## 🗄️ Database Changes Required

### New Tables:

```sql
-- Team assignments for improvements
CREATE TABLE improvement_team_assignments (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    role VARCHAR(50), -- 'lead', 'developer', 'reviewer', 'tester'
    assigned_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(30) DEFAULT 'assigned', -- 'assigned', 'in_progress', 'completed', 'blocked'
    notes TEXT,
    UNIQUE(proposal_id, agent_id)
);

-- Sandbox instances
CREATE TABLE sandbox_instances (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id),
    sandbox_type VARCHAR(20), -- 'docker_container' or 'schema_separation'
    container_id VARCHAR(100), -- Docker container ID if applicable
    schema_name VARCHAR(50), -- Schema name if schema separation
    status VARCHAR(30) DEFAULT 'creating', -- 'creating', 'ready', 'testing', 'destroyed'
    created_at TIMESTAMP DEFAULT NOW(),
    destroyed_at TIMESTAMP,
    test_results JSONB,
    backup_ref VARCHAR(255), -- Reference to pre-deployment backup
    metadata JSONB
);

-- Deployment history tracking
CREATE TABLE improvement_deployments (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id),
    deployed_by INTEGER REFERENCES users(id),
    backup_name VARCHAR(255),
    sandbox_id INTEGER REFERENCES sandbox_instances(id),
    deployment_type VARCHAR(30), -- 'manual', 'auto_low_risk', 'auto_approved'
    status VARCHAR(30), -- 'deploying', 'deployed', 'failed', 'rolled_back'
    deployed_at TIMESTAMP DEFAULT NOW(),
    rolled_back_at TIMESTAMP,
    rollback_reason TEXT,
    health_check_passed BOOLEAN,
    deployment_log TEXT
);

-- Workflow state tracking
CREATE TABLE improvement_workflow_states (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id),
    from_status VARCHAR(50),
    to_status VARCHAR(50),
    changed_by INTEGER REFERENCES users(id),
    changed_at TIMESTAMP DEFAULT NOW(),
    reason TEXT,
    automated BOOLEAN DEFAULT false,
    metadata JSONB
);
```

### Existing Table Modifications:

```sql
-- Add new fields to improvement_proposals
ALTER TABLE improvement_proposals
ADD COLUMN IF NOT EXISTS team_assigned_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS team_size INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS required_skills TEXT[],
ADD COLUMN IF NOT EXISTS complexity VARCHAR(20) DEFAULT 'medium', -- 'low', 'medium', 'high'
ADD COLUMN IF NOT EXISTS auto_deployed BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS sandbox_tested BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS last_health_check TIMESTAMP,
ADD COLUMN IF NOT EXISTS code_diff TEXT; -- Stores diff for preview

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_team_assignments_proposal ON improvement_team_assignments(proposal_id);
CREATE INDEX IF NOT EXISTS idx_team_assignments_agent ON improvement_team_assignments(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_sandbox_proposal ON sandbox_instances(proposal_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_states_proposal ON improvement_workflow_states(proposal_id, changed_at);
```

---

## 📊 Implementation Plan (6 Phases)

### **PHASE 1: Foundation & Immediate Fixes** (Week 1)
**Goal**: Fix current issues and lay groundwork

**Tasks**:
1. **Fix Stuck Proposals** (HIGH PRIORITY)
   - Add timeout detection: proposals in 'pending' > 48hrs auto-escalate
   - Create admin action: "Unstick Proposal" button
   - File: `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)` (add endpoint)

2. **Fix Escalation Button** (HIGH PRIORITY)
   - Debug escalation endpoint at line 3031
   - Verify notification creation (currently fails if notifications table missing)
   - Test escalation workflow end-to-end
   - File: `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)` (lines 3031-3074)

3. **Database Schema Updates**
   - Run migration to add new tables (improvement_team_assignments, sandbox_instances, etc.)
   - Add new columns to improvement_proposals
   - Create indexes
   - File: Create `/mnt/archie_brain/platform_v2/migrations/005_improvement_workflow_enhancement.sql`

4. **Basic Team Assignment Logic**
   - Create team_assignment_engine.py skeleton
   - Implement internal-first algorithm
   - Add manual team assignment API
   - Files: Create `/mnt/archie_brain/ai_bridge/team_assignment_engine.py`

**Testing**:
- ✓ Stuck proposals can be unstuck
- ✓ Escalation creates notification correctly
- ✓ Team assignment returns valid agents

**Deliverables**:
- Migration 005 applied
- Escalation working
- Basic team assignment API

---

### **PHASE 2: Enhanced Chat & Proposal Creation** (Week 2)
**Goal**: Claude Code-style chat interface

**Tasks**:
1. **Natural Language Proposal Creation**
   - Enhance chat_about_improvements() to detect improvement requests
   - Auto-create proposals from chat context
   - Keywords: "optimize", "improve", "fix", "enhance", "add feature"
   - File: `/mnt/archie_brain/ai_bridge/improvement_chat.py` (lines 54-286)

2. **Code Diff Engine**
   - Create diff generation system
   - Integrate with python difflib
   - Generate before/after comparisons
   - Store diffs in improvement_proposals.code_diff
   - Files: Create `/mnt/archie_brain/ai_bridge/code_diff_engine.py`

3. **Diff Viewer UI**
   - Add diff visualization to chat interface
   - Side-by-side comparison with syntax highlighting
   - Use Monaco Editor or similar
   - File: `/mnt/archie_brain/platform_v2/templates/ (now modular templates)` (improvements chat section)

4. **Step-by-Step Guidance**
   - Break proposals into implementation steps
   - Store in improvement_proposals.plan_steps (existing JSONB field)
   - Display progressive checklist in UI
   - Track completion per step

5. **File Editing Interface**
   - Add "Apply Changes" button to diff viewer
   - Call API to apply code changes
   - Show confirmation + validation
   - File: `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)` (create /improvements/apply-changes endpoint)

**Testing**:
- ✓ Chat creates proposals from natural language
- ✓ Diff viewer shows correct before/after
- ✓ Steps display and track correctly
- ✓ Apply changes works and validates

**Deliverables**:
- Enhanced chat with NLP
- Working diff viewer
- Step-by-step guidance system
- File editing capability

---

### **PHASE 3: Automated Team Assignment** (Week 3)
**Goal**: Fully automatic team building and assignment

**Tasks**:
1. **Skill Matching Algorithm**
   - Map proposal categories to required skills
   - Query agent_skills table for matches
   - Score agents by proficiency level
   - File: `/mnt/archie_brain/ai_bridge/team_assignment_engine.py` (expand)

2. **Internal-First Routing**
   - Implement cost-aware selection
   - Prioritize worker_type='internal'
   - Fallback to 'contract' if no internal match
   - Track fallback reasons for learning
   - File: `/mnt/archie_brain/ai_bridge/team_assignment_engine.py`

3. **Team Size Determination**
   - Low complexity → 1 agent
   - Medium complexity → 2 agents (lead + developer)
   - High complexity → 3 agents (lead + developer + reviewer)
   - Store in improvement_proposals.team_size

4. **Auto-Assignment on Proposal Creation**
   - Hook into proposal creation workflow
   - Trigger team assignment automatically
   - Create improvement_team_assignments records
   - Send notifications to assigned agents
   - File: `/mnt/archie_brain/ai_bridge/improvement_engine.py` (modify propose_improvement())

5. **Team Management UI**
   - Display assigned team in proposal detail view
   - Show agent roles and status
   - Allow admin override/reassignment
   - File: `/mnt/archie_brain/platform_v2/templates/ (now modular templates)`

**Testing**:
- ✓ Low priority → internal agents assigned
- ✓ High priority with no internal match → contracts assigned
- ✓ Team size matches complexity
- ✓ Notifications sent to team members

**Deliverables**:
- Fully automated team assignment
- Internal-first routing working
- Team management UI

---

### **PHASE 4: Development Sandbox** (Week 4)
**Goal**: Safe testing environment

**Tasks**:
1. **Sandbox Decision Logic**
   - Analyze proposal risk_level and priority
   - High risk/priority → Docker container
   - Low/medium → Schema separation
   - File: Create `/mnt/archie_brain/platform_v2/sandbox_manager.py`

2. **Docker Sandbox**
   - Create docker-compose.sandbox.yml
   - Define archie_sandbox and archie_sandbox_db services
   - Implement container lifecycle management
   - API endpoints: create, start, stop, destroy
   - Files: Create `/mnt/archie_brain/docker-compose.sandbox.yml`, `/mnt/archie_brain/platform_v2/sandbox_docker.py`

3. **Schema Sandbox**
   - Create sandbox schema in existing database
   - Clone tables with CREATE TABLE AS SELECT
   - Implement schema cleanup on completion
   - File: `/mnt/archie_brain/platform_v2/sandbox_schema.py`

4. **Sandbox Testing Harness**
   - Apply code changes to sandbox
   - Run syntax validation
   - Run security scans
   - Run health checks
   - Capture test results
   - File: `/mnt/archie_brain/platform_v2/sandbox_test_runner.py`

5. **Sandbox UI**
   - Show sandbox status in proposal view
   - Display test results
   - View sandbox logs
   - Manual sandbox creation option
   - File: `/mnt/archie_brain/platform_v2/templates/ (now modular templates)`

**Testing**:
- ✓ High risk proposals use Docker sandbox
- ✓ Low risk proposals use schema sandbox
- ✓ Sandboxes isolate changes correctly
- ✓ Test results captured accurately

**Deliverables**:
- Hybrid sandbox system operational
- Automated sandbox creation
- Test harness working
- Sandbox management UI

---

### **PHASE 5: Safety Protocol & Deployment** (Week 5)
**Goal**: Automated backup, deploy, rollback

**Tasks**:
1. **Pre-Deployment Backup Integration**
   - Trigger backup via Backup Manager API
   - Use existing create_backup() function
   - Store backup reference in sandbox_instances.backup_ref
   - File: `/mnt/archie_brain/platform_v2/safe_deployment_protocol.py` (create)

2. **Deployment Pipeline**
   - Validate sandbox tests passed
   - Create pre-deployment backup
   - Apply changes to production
   - Run health checks
   - Update improvement_deployments table
   - File: `/mnt/archie_brain/platform_v2/safe_deployment_protocol.py`

3. **Auto-Rollback System**
   - Monitor health checks post-deployment
   - Detect failures (HTTP 500, service down, etc.)
   - Trigger automatic rollback
   - Execute backup rollback.sh script
   - Notify admin of rollback
   - File: `/mnt/archie_brain/platform_v2/auto_rollback.py` (create)

4. **Deployment Decision Engine**
   - Low risk + tests passed → auto-deploy
   - High risk → require admin approval
   - Failed tests → block deployment
   - File: `/mnt/archie_brain/platform_v2/deployment_decision.py` (create)

5. **Deployment Monitoring**
   - 24-hour monitoring window post-deployment
   - Track errors, performance, health
   - Auto-rollback on threshold breach
   - File: `/mnt/archie_brain/platform_v2/deployment_monitor.py` (create)

**Testing**:
- ✓ Backup created before every deployment
- ✓ Health check failures trigger rollback
- ✓ Auto-deploy works for low-risk changes
- ✓ High-risk requires admin approval

**Deliverables**:
- Safe deployment protocol
- Auto-rollback system
- Deployment monitoring
- Risk-based approval gates

---

### **PHASE 6: Workflow Automation & Polish** (Week 6)
**Goal**: End-to-end automation and refinement

**Tasks**:
1. **Workflow Automator**
   - Implement auto-status progression
   - Detect stuck proposals (timeout triggers)
   - Auto-escalation for failures
   - Auto-completion on success
   - File: `/mnt/archie_brain/ai_bridge/workflow_automator.py` (create)

2. **Escalation Handler**
   - Enhanced escalation logic
   - Skill-based escalation chains (use agent_skills.can_escalate_to)
   - Multi-level escalation (agent → senior → admin)
   - Escalation notifications
   - File: `/mnt/archie_brain/ai_bridge/escalation_handler.py` (create)

3. **Learning & Feedback Loop**
   - Track success/failure patterns
   - Update agent proficiency scores
   - Improve team assignment algorithm
   - Store insights in long_term_memory
   - File: `/mnt/archie_brain/ai_bridge/improvement_learning.py` (create)

4. **Dashboard Enhancements**
   - Real-time workflow visualization
   - Team performance metrics
   - Deployment success rates
   - Cost tracking (internal vs contractor usage)
   - File: `/mnt/archie_brain/platform_v2/templates/ (now modular templates)` (improvements dashboard)

5. **Documentation & Training**
   - Update /docs/ with new workflow
   - Create user guide for chat-based improvements
   - Admin guide for team management
   - File: Create `/mnt/archie_brain/docs/IMPROVEMENT_WORKFLOW_GUIDE_2026.md`

**Testing**:
- ✓ End-to-end workflow completes automatically
- ✓ Escalations route correctly
- ✓ Learning improves over time
- ✓ Dashboard shows accurate metrics

**Deliverables**:
- Fully automated workflow
- Intelligent escalation
- Self-improving system
- Complete documentation

---

## 📁 Critical Files Summary

### Existing Files to Modify:
| File | Purpose | Key Changes |
|------|---------|-------------|
| `/mnt/archie_brain/ai_bridge/improvement_chat.py` | Chat system | Enhance NLP, add diff generation |
| `/mnt/archie_brain/ai_bridge/improvement_engine.py` | Detection engine | Add auto-team assignment hook |
| `/mnt/archie_brain/platform_v2/tools/improvements/manager.py` | Workflow manager | Integrate safe deployment |
| `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)` | Admin API | Fix escalation (line 3031), add endpoints |
| `/mnt/archie_brain/platform_v2/templates/ (now modular templates)` | Admin UI | Add diff viewer, team UI, sandbox status |
| `/mnt/archie_brain/platform_v2/tools/backup_manager/backup_manager_routes.py` | Backup system | Add API trigger for automated backups |
| `/mnt/archie_brain/docker-compose.yml` | Docker config | Add sandbox services |

### New Files to Create:
| File | Purpose |
|------|---------|
| `/mnt/archie_brain/platform_v2/migrations/005_improvement_workflow_enhancement.sql` | Database migration |
| `/mnt/archie_brain/ai_bridge/team_assignment_engine.py` | Team building algorithm |
| `/mnt/archie_brain/ai_bridge/code_diff_engine.py` | Code diff generation |
| `/mnt/archie_brain/platform_v2/sandbox_manager.py` | Sandbox orchestration |
| `/mnt/archie_brain/platform_v2/sandbox_docker.py` | Docker sandbox management |
| `/mnt/archie_brain/platform_v2/sandbox_schema.py` | Schema sandbox management |
| `/mnt/archie_brain/platform_v2/sandbox_test_runner.py` | Sandbox testing harness |
| `/mnt/archie_brain/platform_v2/safe_deployment_protocol.py` | Deployment pipeline |
| `/mnt/archie_brain/platform_v2/auto_rollback.py` | Auto-rollback system |
| `/mnt/archie_brain/platform_v2/deployment_decision.py` | Risk-based deployment |
| `/mnt/archie_brain/platform_v2/deployment_monitor.py` | Post-deployment monitoring |
| `/mnt/archie_brain/ai_bridge/workflow_automator.py` | Workflow automation |
| `/mnt/archie_brain/ai_bridge/escalation_handler.py` | Smart escalation |
| `/mnt/archie_brain/ai_bridge/improvement_learning.py` | Feedback loop |
| `/mnt/archie_brain/docker-compose.sandbox.yml` | Sandbox Docker config |
| `/mnt/archie_brain/docs/IMPROVEMENT_WORKFLOW_GUIDE_2026.md` | User documentation |

---

## 🧪 Testing Strategy

### Phase 1 Testing:
- ✓ Escalation endpoint returns 200, creates notification
- ✓ Stuck proposal detection fires after 48hrs
- ✓ Migration 005 applies without errors
- ✓ Team assignment returns valid agents (internal first)

### Phase 2 Testing:
- ✓ Chat detects improvement keywords and creates proposals
- ✓ Diff engine generates accurate before/after comparisons
- ✓ Diff viewer displays correctly with syntax highlighting
- ✓ Apply changes validates and applies code correctly

### Phase 3 Testing:
- ✓ Internal agents assigned before contractors
- ✓ Team size matches complexity (1/2/3 agents)
- ✓ Agent notifications sent on assignment
- ✓ Skills matching algorithm scores correctly

### Phase 4 Testing:
- ✓ Docker sandbox creates and starts successfully
- ✓ Schema sandbox clones tables correctly
- ✓ High-risk proposals use Docker, low-risk use schema
- ✓ Sandbox test runner captures results accurately

### Phase 5 Testing:
- ✓ Backup created before every deployment
- ✓ Health check failures trigger auto-rollback
- ✓ Low-risk auto-deploys, high-risk requires approval
- ✓ Rollback restores system to pre-deployment state

### Phase 6 Testing:
- ✓ End-to-end workflow (chat → team → test → deploy) completes
- ✓ Escalation chains route through multiple levels
- ✓ Learning system improves assignment over time
- ✓ Dashboard metrics update in real-time

---

## 🚀 Future Enhancements (Phase 7+)

These features are **deferred** per user preference but documented for future:

### Cursor AI / OpenCode Integration
- Local LLM team collaboration
- Code generation assistance
- Real-time code suggestions during implementation

### archie_bridge Self-Learning
- Automatic skill proficiency updates based on success
- Pattern recognition for common improvements
- Predictive team assignment based on historical data

### Advanced Features
- Multi-agent code review system
- Automated regression testing
- Performance benchmarking in sandbox
- Cost optimization recommendations
- Agent workload balancing
- Geographic distribution of agents
- Natural language code generation
- Integration with external IDEs

---

## ✅ Success Criteria

### Immediate (Phase 1):
- ✅ No proposals stuck in "pending" > 48hrs
- ✅ Escalation button works and creates notifications
- ✅ Database migration applied successfully
- ✅ Basic team assignment API functional

### Short-term (Phases 2-3):
- ✅ Chat reliably creates proposals from natural language
- ✅ Diff viewer shows changes before implementation
- ✅ Teams auto-assigned using internal agents first
- ✅ Contractors only used when necessary

### Medium-term (Phases 4-5):
- ✅ All improvements tested in sandbox before production
- ✅ Automated backups before every deployment
- ✅ Auto-rollback on deployment failure
- ✅ Zero downtime deployments for low-risk changes

### Long-term (Phase 6):
- ✅ 90%+ of improvements handled end-to-end automatically
- ✅ Internal agent utilization > 70% (cost savings)
- ✅ Deployment success rate > 95%
- ✅ Average time-to-deployment < 24 hours
- ✅ Self-improving system (better over time)

---

## 📊 Expected Outcomes

### Efficiency Gains:
- **Time to Deploy**: 3-5 days → < 24 hours (80% reduction)
- **Manual Intervention**: 100% → <10% (90% automation)
- **Internal Agent Usage**: 0% → 70%+ (significant cost savings)
- **Deployment Failures**: Unknown → <5% (with auto-rollback)

### Quality Improvements:
- **Pre-deployment Testing**: 0% → 100% (all improvements tested)
- **Backup Coverage**: Manual → 100% automated
- **Rollback Capability**: Manual → Automatic
- **Success Tracking**: None → Complete audit trail

### Cost Optimization:
- **Contractor Usage**: Ad-hoc → Only when necessary
- **Failed Deployments**: Expensive → Minimal (auto-rollback)
- **Development Time**: High → Significantly reduced
- **Operational Overhead**: Manual → Automated

---

## 📖 Documentation Plan

### User-Facing Documentation:
1. **Chat-Based Improvement Guide** - How to request improvements via chat
2. **Team Assignment Explained** - Understanding how teams are built
3. **Sandbox Testing Guide** - What happens in the sandbox
4. **Deployment Process** - What to expect during deployment

### Admin Documentation:
1. **Team Management Guide** - Overriding assignments, managing agents
2. **Sandbox Administration** - Creating, monitoring, destroying sandboxes
3. **Deployment Monitoring** - Understanding health checks and rollbacks
4. **Escalation Handling** - Managing escalated improvements

### Developer Documentation:
1. **API Reference** - All new endpoints and their usage
2. **Database Schema** - New tables and relationships
3. **Workflow Diagrams** - Visual representation of processes
4. **Extension Guide** - How to add new features

All documentation will be created in `/mnt/archie_brain/docs/` and referenced in TODAYS_IMPROVEMENTS updates.

---

**Status:** ✅ APPROVED - Implementation Started 2026-01-01
**Estimated Timeline:** 6 weeks (6 phases)
**Total New Files:** 16
**Total Modified Files:** 7
**Database Changes:** 4 new tables, 8 new columns, 4 indexes

🎯 **This plan transforms the improvement workflow from manual and error-prone to fully automated, safe, and self-improving.**
