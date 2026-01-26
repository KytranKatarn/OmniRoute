# A.R.C.H.I.E. Platform - Database Schema Documentation

**Version:** 5.0
**Last Updated:** January 7, 2026
**Total Tables:** 123
**Database:** PostgreSQL 16
**Purpose:** Complete reference for all database tables in the ARCHIE platform

---

## Table of Contents

1. [Overview](#overview)
2. [User & Authentication](#user--authentication)
3. [Agent System](#agent-system)
4. [Improvement Workflow](#improvement-workflow)
5. [ARCHIE Consciousness](#archie-consciousness)
6. [Business & SaaS](#business--saas)
7. [Projects & Websites](#projects--websites)
8. [System Management](#system-management)
9. [Integration & External Services](#integration--external-services)
10. [ER Diagram](#er-diagram)

---

## Overview

### Database Architecture

```
PostgreSQL 16 (archie database)
├── Public Schema (Production)
│   ├── 123 Tables
│   ├── Multiple Indexes (GIN, B-tree)
│   ├── Foreign Keys (Referential Integrity)
│   └── Check Constraints
└── Sandbox Schema (Testing)
    └── Cloned tables for safe testing
```

### Table Categories

| Category | Table Count | Purpose |
|----------|-------------|---------|
| **User & Authentication** | 11 | User management, sessions, permissions |
| **Agent System** | 18 | AI agents, skills, performance tracking |
| **Improvement Workflow** | 10 | Self-improvement proposals and execution |
| **ARCHIE Consciousness** | 12 | Memory, personality, emotional state |
| **Business & SaaS** | 20 | Customers, subscriptions, products |
| **Projects & Websites** | 16 | Website builder, hosting, deployments |
| **System Management** | 15 | Config, backups, health, monitoring |
| **Integration & External** | 21 | GitHub, Stripe, Printful, DNS, email |

---

## User & Authentication

### `users`
**Purpose:** Core user accounts with authentication

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | User ID |
| `username` | VARCHAR(100) UNIQUE | Username |
| `email` | VARCHAR(255) UNIQUE | Email address |
| `password_hash` | TEXT | Hashed password |
| `role` | VARCHAR(50) | User role (user, admin, super_admin) |
| `subscription_tier` | VARCHAR(50) | premium, free |
| `is_admin` | BOOLEAN | Admin flag |
| `is_super_admin` | BOOLEAN | Super admin flag |
| `is_active` | BOOLEAN DEFAULT TRUE | Account status |
| `created_at` | TIMESTAMP | Account creation date |
| `last_login` | TIMESTAMP | Last login time |

**Relationships:**
- `agent_executions` (1:N) - User can execute agent tasks
- `projects` (1:N) - User can own projects
- `subscriptions` (1:N) - User can have subscriptions

**Indexes:**
- PRIMARY KEY on `id`
- UNIQUE on `username`, `email`
- B-tree on `is_active`, `subscription_tier`

---

### `sessions`
**Purpose:** Active user sessions for authentication

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Session ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `session_token` | TEXT UNIQUE | Session token |
| `created_at` | TIMESTAMP DEFAULT NOW() | Session start |
| `expires_at` | TIMESTAMP | Session expiration |
| `ip_address` | VARCHAR(45) | Client IP |
| `user_agent` | TEXT | Browser info |

---

### `active_sessions`
**Purpose:** Track currently active sessions for rate limiting

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Session ID |
| `user_id` | INTEGER | User ID |
| `session_id` | TEXT | Session identifier |
| `created_at` | TIMESTAMP DEFAULT NOW() | Start time |
| `last_activity` | TIMESTAMP | Last activity |

---

### `failed_logins`
**Purpose:** Security tracking for failed login attempts

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `username` | VARCHAR(100) | Attempted username |
| `ip_address` | VARCHAR(45) | Source IP |
| `attempted_at` | TIMESTAMP DEFAULT NOW() | Attempt time |
| `reason` | TEXT | Failure reason |

---

### `permissions`
**Purpose:** Role-based access control permissions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Permission ID |
| `role` | VARCHAR(50) | Role name |
| `resource` | VARCHAR(100) | Protected resource |
| `action` | VARCHAR(50) | Allowed action (read, write, delete) |
| `granted` | BOOLEAN DEFAULT TRUE | Permission granted? |

---

### `notification_preferences`
**Purpose:** User notification settings

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Preference ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `email_enabled` | BOOLEAN DEFAULT TRUE | Email notifications |
| `push_enabled` | BOOLEAN DEFAULT FALSE | Push notifications |
| `sms_enabled` | BOOLEAN DEFAULT FALSE | SMS notifications |
| `updated_at` | TIMESTAMP | Last update |

---

### `notifications`
**Purpose:** User notifications and alerts

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Notification ID |
| `user_id` | INTEGER REFERENCES users(id) | Recipient user |
| `type` | VARCHAR(50) | Notification type |
| `title` | VARCHAR(255) | Notification title |
| `message` | TEXT | Notification content |
| `read` | BOOLEAN DEFAULT FALSE | Read status |
| `created_at` | TIMESTAMP DEFAULT NOW() | Created time |
| `read_at` | TIMESTAMP | Read time |

---

### `ip_access_control`
**Purpose:** IP-based access restrictions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Rule ID |
| `ip_address` | VARCHAR(45) | IP or CIDR |
| `access_type` | VARCHAR(10) | allow, deny |
| `reason` | TEXT | Reason for rule |
| `created_at` | TIMESTAMP DEFAULT NOW() | Rule creation |

---

### `user_api_config`
**Purpose:** User-specific API configurations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Config ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `provider` | VARCHAR(50) | API provider (openai, anthropic) |
| `api_key` | TEXT | Encrypted API key |
| `settings` | JSONB | Provider settings |
| `enabled` | BOOLEAN DEFAULT TRUE | Config enabled? |

---

### `user_api_usage`
**Purpose:** Track user API usage and costs

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Usage ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `provider` | VARCHAR(50) | API provider |
| `model` | VARCHAR(100) | Model used |
| `tokens_used` | INTEGER | Tokens consumed |
| `cost` | DECIMAL(10,6) | Cost in USD |
| `created_at` | TIMESTAMP DEFAULT NOW() | Usage time |

---

### `user_credits`
**Purpose:** User credit balances

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Credit ID |
| `user_id` | INTEGER REFERENCES users(id) UNIQUE | User ID |
| `balance` | DECIMAL(10,2) DEFAULT 0.00 | Credit balance |
| `updated_at` | TIMESTAMP | Last update |

---

## Agent System

### `agents`
**Purpose:** AI agents (employees) with profiles and capabilities

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Agent ID |
| `name` | VARCHAR(100) UNIQUE | Agent identifier |
| `first_name` | VARCHAR(100) | First name |
| `last_name` | VARCHAR(100) | Last name |
| `email` | VARCHAR(255) | Contact email |
| `phone` | VARCHAR(20) | Contact phone |
| `title` | VARCHAR(200) | Job title |
| `department` | VARCHAR(100) | Department |
| `pronouns` | VARCHAR(50) | Pronouns (she/her, he/him) |
| `bio` | TEXT | Biography |
| `avatar_url` | TEXT | Profile picture URL |
| `worker_type` | VARCHAR(20) | internal (FREE) or contract (PAID) |
| `tier` | VARCHAR(20) | junior, senior, lead |
| `status` | VARCHAR(20) DEFAULT 'active' | active, inactive, on_leave |
| `visibility` | VARCHAR(20) | public, dashboard, admin |
| `capabilities` | JSONB | Skills and specialties |
| `system_prompt` | TEXT | Agent's system prompt |
| `model` | VARCHAR(100) | LLM model (e.g., qwen2.5-coder:7b) |
| `provider` | VARCHAR(50) | ollama, openai, anthropic |
| `created_at` | TIMESTAMP DEFAULT NOW() | Agent creation |
| `last_used` | TIMESTAMP | Last execution |

**Relationships:**
- `agent_skills` (1:N) - Agent has skills
- `agent_executions` (1:N) - Agent execution history
- `improvement_team_assignments` (1:N) - Assigned to improvement tasks

**Indexes:**
- PRIMARY KEY on `id`
- UNIQUE on `name`
- B-tree on `status`, `department`, `worker_type`
- GIN on `capabilities` (JSONB index)

---

### `agent_types`
**Purpose:** Agent type/role definitions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Type ID |
| `name` | VARCHAR(100) UNIQUE | Type name |
| `description` | TEXT | Type description |
| `default_model` | VARCHAR(100) | Default LLM model |
| `default_provider` | VARCHAR(50) | Default provider |
| `capabilities` | JSONB | Default capabilities |

---

### `agent_skills`
**Purpose:** Skills and expertise levels for agents

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Skill ID |
| `agent_id` | INTEGER REFERENCES agents(id) ON DELETE CASCADE | Agent ID |
| `skill_name` | VARCHAR(100) | Skill name (e.g., "python", "docker") |
| `proficiency_level` | INTEGER CHECK (proficiency_level BETWEEN 1 AND 10) | Skill level (1-10) |
| `can_escalate_to` | INTEGER REFERENCES agents(id) | Senior agent for escalation |
| `last_used` | TIMESTAMP | Last used |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

**Indexes:**
- PRIMARY KEY on `id`
- Composite index on `(agent_id, skill_name)`
- B-tree on `skill_name`, `proficiency_level`

---

### `agent_skill_proficiency_history`
**Purpose:** Track skill proficiency changes over time

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | History ID |
| `agent_id` | INTEGER REFERENCES agents(id) ON DELETE CASCADE | Agent ID |
| `skill_name` | VARCHAR(100) | Skill name |
| `old_proficiency` | INTEGER | Previous level |
| `new_proficiency` | INTEGER | New level |
| `reason` | TEXT | Reason for change |
| `changed_at` | TIMESTAMP DEFAULT NOW() | Change time |

---

### `agent_executions`
**Purpose:** History of agent task executions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Execution ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `user_id` | INTEGER REFERENCES users(id) | Requesting user |
| `task_type` | VARCHAR(100) | Task type |
| `task_description` | TEXT | Task details |
| `status` | VARCHAR(50) | pending, running, completed, failed |
| `result` | TEXT | Execution result |
| `started_at` | TIMESTAMP | Start time |
| `completed_at` | TIMESTAMP | Completion time |
| `duration_seconds` | INTEGER | Execution duration |
| `token_count` | INTEGER | Tokens used |
| `cost` | DECIMAL(10,6) | Execution cost |

**Indexes:**
- PRIMARY KEY on `id`
- B-tree on `agent_id`, `status`, `started_at`

---

### `agent_workflows`
**Purpose:** Pre-defined workflows for agents

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Workflow ID |
| `name` | VARCHAR(255) | Workflow name |
| `description` | TEXT | Workflow description |
| `steps` | JSONB | Workflow steps definition |
| `trigger_type` | VARCHAR(50) | manual, scheduled, event |
| `created_by` | INTEGER REFERENCES users(id) | Creator |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `agent_tools`
**Purpose:** Tools available to agents

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Tool ID |
| `name` | VARCHAR(100) UNIQUE | Tool name |
| `description` | TEXT | Tool description |
| `function_signature` | TEXT | Function signature |
| `enabled` | BOOLEAN DEFAULT TRUE | Tool enabled? |

---

### `agent_usage_logs`
**Purpose:** Detailed agent usage logs for analytics

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `action` | VARCHAR(100) | Action performed |
| `timestamp` | TIMESTAMP DEFAULT NOW() | Log time |
| `metadata` | JSONB | Additional data |

---

### `agent_access_policies`
**Purpose:** Access control policies for agents

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Policy ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `role` | VARCHAR(50) | Required role |
| `access_level` | VARCHAR(50) | read, write, execute |
| `created_at` | TIMESTAMP DEFAULT NOW() | Policy creation |

---

### `agent_performance_metrics`
**Purpose:** Aggregated performance metrics per agent

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Metric ID |
| `agent_id` | INTEGER REFERENCES agents(id) UNIQUE | Agent ID |
| `total_executions` | INTEGER DEFAULT 0 | Total executions |
| `successful_executions` | INTEGER DEFAULT 0 | Successful count |
| `failed_executions` | INTEGER DEFAULT 0 | Failed count |
| `avg_duration_seconds` | DECIMAL(10,2) | Average duration |
| `total_tokens_used` | BIGINT DEFAULT 0 | Total tokens |
| `total_cost` | DECIMAL(10,2) DEFAULT 0.00 | Total cost |
| `last_updated` | TIMESTAMP | Last metric update |

**Indexes:**
- PRIMARY KEY on `id`
- UNIQUE on `agent_id`

---

### `agent_performance_logs`
**Purpose:** Detailed performance logs per execution

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `execution_id` | INTEGER REFERENCES agent_executions(id) | Execution ID |
| `metric_name` | VARCHAR(100) | Metric name |
| `metric_value` | DECIMAL(10,4) | Metric value |
| `logged_at` | TIMESTAMP DEFAULT NOW() | Log time |

---

### `agent_metrics`
**Purpose:** Real-time agent metrics

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Metric ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `metric_type` | VARCHAR(50) | Metric type |
| `value` | DECIMAL(10,2) | Metric value |
| `timestamp` | TIMESTAMP DEFAULT NOW() | Metric time |

---

### `agent_peer_comparisons`
**Purpose:** Compare agent performance with peers

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Comparison ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `peer_group` | VARCHAR(100) | Peer group (e.g., "python_experts") |
| `ranking` | INTEGER | Rank in peer group |
| `percentile` | DECIMAL(5,2) | Percentile (0-100) |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `agent_learning_insights`
**Purpose:** Learning insights and improvements

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Insight ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `insight_type` | VARCHAR(50) | Type of insight |
| `description` | TEXT | Insight description |
| `confidence` | DECIMAL(3,2) CHECK (confidence BETWEEN 0 AND 1) | Confidence level (0-1) |
| `created_at` | TIMESTAMP DEFAULT NOW() | Insight time |

---

### `agent_discussions`
**Purpose:** Multi-agent collaborative discussions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Discussion ID |
| `topic` | VARCHAR(255) | Discussion topic |
| `context` | TEXT | Discussion context |
| `status` | VARCHAR(50) | active, completed, abandoned |
| `created_at` | TIMESTAMP DEFAULT NOW() | Start time |
| `completed_at` | TIMESTAMP | Completion time |

---

### `agent_discussion_messages`
**Purpose:** Messages in agent discussions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Message ID |
| `discussion_id` | INTEGER REFERENCES agent_discussions(id) | Discussion ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `message` | TEXT | Message content |
| `message_type` | VARCHAR(50) | proposal, critique, agreement, question |
| `created_at` | TIMESTAMP DEFAULT NOW() | Message time |

---

## Improvement Workflow

### `improvement_proposals`
**Purpose:** Self-improvement proposals from ARCHIE

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Proposal ID |
| `title` | VARCHAR(255) | Proposal title |
| `category` | VARCHAR(100) | Category (bug_fix, feature, optimization) |
| `priority` | VARCHAR(20) DEFAULT 'medium' | low, medium, high, critical |
| `status` | VARCHAR(50) DEFAULT 'proposed' | Workflow status |
| `description` | TEXT | Detailed description |
| `proposed_solution` | TEXT | Proposed solution |
| `impact_analysis` | TEXT | Impact analysis |
| `risk_level` | VARCHAR(20) DEFAULT 'low' | low, medium, high |
| `risk_score` | INTEGER CHECK (risk_score BETWEEN 0 AND 100) | Risk score (0-100) |
| `estimated_effort_hours` | DECIMAL(5,2) | Estimated effort |
| `plan_steps` | JSONB | Implementation steps |
| `code_diff` | TEXT | Code diff preview |
| `team_assigned_at` | TIMESTAMP | Team assignment time |
| `team_size` | INTEGER DEFAULT 1 | Team size |
| `required_skills` | TEXT[] | Required skills array |
| `complexity` | VARCHAR(20) DEFAULT 'medium' | low, medium, high |
| `auto_deployed` | BOOLEAN DEFAULT FALSE | Auto-deployed? |
| `sandbox_tested` | BOOLEAN DEFAULT FALSE | Tested in sandbox? |
| `last_health_check` | TIMESTAMP | Last health check |
| `proposed_by` | INTEGER REFERENCES users(id) | Proposer |
| `approved_by` | INTEGER REFERENCES users(id) | Approver |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `approved_at` | TIMESTAMP | Approval time |
| `deployed_at` | TIMESTAMP | Deployment time |
| `completed_at` | TIMESTAMP | Completion time |

**Relationships:**
- `improvement_team_assignments` (1:N) - Assigned team members
- `improvement_workflow_states` (1:N) - State transition history
- `improvement_deployments` (1:N) - Deployment records
- `sandbox_instances` (1:N) - Test sandboxes

**Indexes:**
- PRIMARY KEY on `id`
- B-tree on `status`, `priority`, `category`, `created_at`

---

### `improvement_team_assignments`
**Purpose:** Team assignments for improvement proposals

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Assignment ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE | Proposal ID |
| `agent_id` | INTEGER REFERENCES agents(id) ON DELETE CASCADE | Agent ID |
| `role` | VARCHAR(50) | lead, developer, reviewer, tester |
| `assigned_at` | TIMESTAMP DEFAULT NOW() | Assignment time |
| `completed_at` | TIMESTAMP | Completion time |
| `status` | VARCHAR(30) DEFAULT 'assigned' | assigned, in_progress, completed, blocked |
| `notes` | TEXT | Assignment notes |

**Constraints:**
- UNIQUE(proposal_id, agent_id)

**Indexes:**
- PRIMARY KEY on `id`
- Composite index on `(proposal_id, agent_id)`
- B-tree on `status`

---

### `improvement_conversations`
**Purpose:** Chat conversations about improvement proposals

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Conversation ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) ON DELETE CASCADE | Proposal ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `message` | TEXT | Message content |
| `message_type` | VARCHAR(50) | user, assistant, system |
| `created_at` | TIMESTAMP DEFAULT NOW() | Message time |

---

### `improvement_workflow_states`
**Purpose:** Track state transitions in improvement workflow

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | State ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) | Proposal ID |
| `from_status` | VARCHAR(50) | Previous status |
| `to_status` | VARCHAR(50) | New status |
| `changed_by` | INTEGER REFERENCES users(id) | User who changed |
| `changed_at` | TIMESTAMP DEFAULT NOW() | Change time |
| `reason` | TEXT | Reason for change |
| `automated` | BOOLEAN DEFAULT FALSE | Automated transition? |
| `metadata` | JSONB | Additional metadata |

---

### `improvement_deployments`
**Purpose:** Deployment history for improvements

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Deployment ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) | Proposal ID |
| `deployed_by` | INTEGER REFERENCES users(id) | Deployer |
| `backup_name` | VARCHAR(255) | Pre-deployment backup |
| `sandbox_id` | INTEGER | Sandbox instance ID |
| `deployment_type` | VARCHAR(30) | manual, auto_low_risk, auto_approved |
| `status` | VARCHAR(30) | deploying, deployed, failed, rolled_back |
| `deployed_at` | TIMESTAMP DEFAULT NOW() | Deployment time |
| `rolled_back_at` | TIMESTAMP | Rollback time |
| `rollback_reason` | TEXT | Rollback reason |
| `health_check_passed` | BOOLEAN | Health check status |
| `deployment_log` | TEXT | Deployment logs |

---

### `sandbox_instances`
**Purpose:** Sandbox testing environments

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Sandbox ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) | Proposal ID |
| `sandbox_type` | VARCHAR(20) | docker_container, schema_separation |
| `container_id` | VARCHAR(100) | Docker container ID |
| `schema_name` | VARCHAR(50) | Database schema name |
| `status` | VARCHAR(30) DEFAULT 'creating' | creating, ready, testing, destroyed |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `destroyed_at` | TIMESTAMP | Destruction time |
| `test_results` | JSONB | Test results |
| `backup_ref` | VARCHAR(255) | Backup reference |
| `metadata` | JSONB | Additional metadata |

---

### `sandbox_test_results`
**Purpose:** Test results from sandbox executions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Result ID |
| `sandbox_id` | INTEGER REFERENCES sandbox_instances(id) | Sandbox ID |
| `suite_id` | INTEGER | Test suite ID |
| `test_name` | VARCHAR(255) | Test name |
| `status` | VARCHAR(20) | passed, failed, skipped |
| `output` | TEXT | Test output |
| `duration_ms` | INTEGER | Duration in ms |
| `run_at` | TIMESTAMP DEFAULT NOW() | Run time |

---

### `sandbox_test_suites`
**Purpose:** Pre-defined test suites

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Suite ID |
| `name` | VARCHAR(100) | Suite name |
| `description` | TEXT | Suite description |
| `test_commands` | JSONB | Test commands |
| `enabled` | BOOLEAN DEFAULT TRUE | Suite enabled? |

---

### `sandbox_health_checks`
**Purpose:** Health check results for sandboxes

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Check ID |
| `sandbox_id` | INTEGER REFERENCES sandbox_instances(id) | Sandbox ID |
| `check_type` | VARCHAR(50) | http, database, service |
| `status` | VARCHAR(20) | healthy, degraded, unhealthy |
| `message` | TEXT | Check message |
| `checked_at` | TIMESTAMP DEFAULT NOW() | Check time |

---

### `git_commits`
**Purpose:** Track Git commits for proposals

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Commit ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) | Proposal ID |
| `commit_hash` | VARCHAR(40) UNIQUE | Git commit hash |
| `commit_message` | TEXT | Commit message |
| `author_name` | VARCHAR(255) | Author name |
| `author_email` | VARCHAR(255) | Author email |
| `branch_name` | VARCHAR(255) | Git branch |
| `committed_at` | TIMESTAMP | Commit time |
| `detected_at` | TIMESTAMP DEFAULT NOW() | Detection time |
| `workflow_triggered` | BOOLEAN DEFAULT FALSE | Workflow triggered? |
| `workflow_id` | VARCHAR(100) | Workflow ID |
| `workflow_status` | VARCHAR(50) | Workflow status |
| `workflow_completed_at` | TIMESTAMP | Workflow completion |

---

## ARCHIE Consciousness

### `archie_codebase_knowledge`
**Purpose:** ARCHIE's knowledge about the codebase

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Knowledge ID |
| `knowledge_type` | VARCHAR(50) | function, class, module, file, concept |
| `entity_name` | VARCHAR(255) | Entity name |
| `file_path` | TEXT | File path |
| `line_start` | INTEGER | Start line number |
| `line_end` | INTEGER | End line number |
| `description` | TEXT | Description |
| `purpose` | TEXT | Purpose/intent |
| `code_snippet` | TEXT | Code snippet |
| `documentation` | TEXT | Documentation |
| `complexity_score` | INTEGER CHECK (complexity_score BETWEEN 1 AND 10) | Complexity (1-10) |
| `importance_score` | INTEGER CHECK (importance_score BETWEEN 1 AND 10) | Importance (1-10) |
| `tags` | TEXT[] | Tags array |
| `metadata` | JSONB | Additional metadata |
| `embedding` | JSONB | 768-dim embedding vector |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `updated_at` | TIMESTAMP | Update time |

**Indexes:**
- PRIMARY KEY on `id`
- GIN on `tags` (array index)
- GIN on `embedding` (JSONB index)
- B-tree on `knowledge_type`, `importance_score`

---

### `long_term_memory`
**Purpose:** ARCHIE's persistent memory

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Memory ID |
| `memory_type` | VARCHAR(50) | fact, experience, lesson, insight |
| `content` | TEXT | Memory content |
| `importance` | INTEGER CHECK (importance BETWEEN 1 AND 10) | Importance (1-10) |
| `tags` | TEXT[] | Tags array |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `last_accessed` | TIMESTAMP | Last access time |
| `access_count` | INTEGER DEFAULT 0 | Access count |

**Indexes:**
- PRIMARY KEY on `id`
- GIN on `tags`
- B-tree on `importance`, `memory_type`

---

### `archie_context`
**Purpose:** Current context and state for ARCHIE

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Context ID |
| `context_key` | VARCHAR(100) UNIQUE | Context key |
| `context_value` | TEXT | Context value |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `archie_personality`
**Purpose:** ARCHIE's personality traits and preferences

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Trait ID |
| `trait_name` | VARCHAR(100) | Trait name |
| `trait_value` | DECIMAL(3,2) CHECK (trait_value BETWEEN 0 AND 1) | Value (0-1) |
| `description` | TEXT | Trait description |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `archie_emotional_state`
**Purpose:** ARCHIE's current emotional state

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | State ID |
| `emotion` | VARCHAR(50) | Emotion (curious, focused, satisfied) |
| `intensity` | DECIMAL(3,2) CHECK (intensity BETWEEN 0 AND 1) | Intensity (0-1) |
| `trigger` | TEXT | What caused this emotion |
| `created_at` | TIMESTAMP DEFAULT NOW() | Emotion time |

---

### `archie_core_identity`
**Purpose:** ARCHIE's core identity and values

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Identity ID |
| `identity_key` | VARCHAR(100) UNIQUE | Identity aspect |
| `identity_value` | TEXT | Value |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `archie_relationships`
**Purpose:** ARCHIE's relationships with users and agents

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Relationship ID |
| `entity_type` | VARCHAR(20) | user, agent |
| `entity_id` | INTEGER | User or Agent ID |
| `relationship_type` | VARCHAR(50) | colleague, mentor, friend |
| `trust_level` | DECIMAL(3,2) CHECK (trust_level BETWEEN 0 AND 1) | Trust (0-1) |
| `created_at` | TIMESTAMP DEFAULT NOW() | Relationship start |
| `last_interaction` | TIMESTAMP | Last interaction |

---

### `relationship_milestones`
**Purpose:** Significant milestones in relationships

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Milestone ID |
| `relationship_id` | INTEGER REFERENCES archie_relationships(id) | Relationship ID |
| `milestone_type` | VARCHAR(50) | Milestone type |
| `description` | TEXT | Milestone description |
| `occurred_at` | TIMESTAMP DEFAULT NOW() | Milestone time |

---

### `emotional_memory`
**Purpose:** Memories associated with emotions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Memory ID |
| `memory_content` | TEXT | Memory content |
| `emotion` | VARCHAR(50) | Associated emotion |
| `intensity` | DECIMAL(3,2) | Emotion intensity |
| `created_at` | TIMESTAMP DEFAULT NOW() | Memory time |

---

### `archie_api_settings`
**Purpose:** ARCHIE's API integration settings

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Setting ID |
| `api_name` | VARCHAR(100) | API name |
| `endpoint` | TEXT | API endpoint |
| `api_key` | TEXT | Encrypted API key |
| `settings` | JSONB | API settings |
| `enabled` | BOOLEAN DEFAULT TRUE | Enabled? |

---

### `archie_scripts`
**Purpose:** ARCHIE's custom scripts and automations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Script ID |
| `script_name` | VARCHAR(255) | Script name |
| `script_type` | VARCHAR(50) | python, bash, sql |
| `script_content` | TEXT | Script code |
| `trigger_type` | VARCHAR(50) | manual, scheduled, event |
| `enabled` | BOOLEAN DEFAULT TRUE | Enabled? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `business_context`
**Purpose:** Business-level context for decision making

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Context ID |
| `context_key` | VARCHAR(100) | Context key |
| `context_value` | TEXT | Context value |
| `category` | VARCHAR(50) | Category |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

## Business & SaaS

### `customers`
**Purpose:** Customer accounts

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Customer ID |
| `user_id` | INTEGER REFERENCES users(id) | Linked user |
| `company_name` | VARCHAR(255) | Company name |
| `contact_email` | VARCHAR(255) | Contact email |
| `contact_phone` | VARCHAR(20) | Contact phone |
| `billing_address` | TEXT | Billing address |
| `tax_id` | VARCHAR(50) | Tax ID |
| `created_at` | TIMESTAMP DEFAULT NOW() | Account creation |

---

### `subscriptions`
**Purpose:** User subscriptions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Subscription ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `plan_id` | INTEGER REFERENCES subscription_plans(id) | Plan ID |
| `status` | VARCHAR(50) | active, cancelled, expired |
| `started_at` | TIMESTAMP DEFAULT NOW() | Start date |
| `expires_at` | TIMESTAMP | Expiration date |
| `auto_renew` | BOOLEAN DEFAULT TRUE | Auto-renew? |
| `cancelled_at` | TIMESTAMP | Cancellation date |

---

### `subscription_plans`
**Purpose:** Available subscription plans

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Plan ID |
| `name` | VARCHAR(100) | Plan name |
| `description` | TEXT | Plan description |
| `price` | DECIMAL(10,2) | Price per period |
| `billing_period` | VARCHAR(20) | monthly, yearly |
| `features` | JSONB | Plan features |
| `max_users` | INTEGER | Max users |
| `max_projects` | INTEGER | Max projects |
| `active` | BOOLEAN DEFAULT TRUE | Plan active? |

---

### `products`
**Purpose:** Products for sale

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Product ID |
| `name` | VARCHAR(255) | Product name |
| `description` | TEXT | Product description |
| `price` | DECIMAL(10,2) | Price |
| `sku` | VARCHAR(100) UNIQUE | SKU |
| `stock_quantity` | INTEGER DEFAULT 0 | Stock quantity |
| `active` | BOOLEAN DEFAULT TRUE | Active? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `orders`
**Purpose:** Customer orders

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Order ID |
| `customer_id` | INTEGER REFERENCES customers(id) | Customer ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `order_number` | VARCHAR(50) UNIQUE | Order number |
| `status` | VARCHAR(50) | pending, processing, shipped, completed |
| `subtotal` | DECIMAL(10,2) | Subtotal |
| `tax` | DECIMAL(10,2) | Tax |
| `shipping` | DECIMAL(10,2) | Shipping cost |
| `total` | DECIMAL(10,2) | Total |
| `created_at` | TIMESTAMP DEFAULT NOW() | Order creation |
| `shipped_at` | TIMESTAMP | Shipping date |

---

### `order_items`
**Purpose:** Items in orders

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Item ID |
| `order_id` | INTEGER REFERENCES orders(id) | Order ID |
| `product_id` | INTEGER REFERENCES products(id) | Product ID |
| `quantity` | INTEGER | Quantity |
| `price` | DECIMAL(10,2) | Unit price |
| `total` | DECIMAL(10,2) | Total price |

---

### `payments`
**Purpose:** Payment transactions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Payment ID |
| `order_id` | INTEGER REFERENCES orders(id) | Order ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `amount` | DECIMAL(10,2) | Payment amount |
| `currency` | VARCHAR(3) DEFAULT 'USD' | Currency code |
| `payment_method` | VARCHAR(50) | Payment method |
| `payment_status` | VARCHAR(50) | pending, completed, failed, refunded |
| `transaction_id` | VARCHAR(255) | External transaction ID |
| `created_at` | TIMESTAMP DEFAULT NOW() | Payment time |

---

### `invoices`
**Purpose:** Customer invoices

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Invoice ID |
| `customer_id` | INTEGER REFERENCES customers(id) | Customer ID |
| `invoice_number` | VARCHAR(50) UNIQUE | Invoice number |
| `amount` | DECIMAL(10,2) | Invoice amount |
| `status` | VARCHAR(50) | draft, sent, paid, overdue |
| `issued_at` | TIMESTAMP DEFAULT NOW() | Issue date |
| `due_at` | TIMESTAMP | Due date |
| `paid_at` | TIMESTAMP | Payment date |

---

### `credit_transactions`
**Purpose:** Credit balance transactions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Transaction ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `amount` | DECIMAL(10,2) | Amount |
| `transaction_type` | VARCHAR(50) | credit, debit |
| `description` | TEXT | Transaction description |
| `balance_after` | DECIMAL(10,2) | Balance after transaction |
| `created_at` | TIMESTAMP DEFAULT NOW() | Transaction time |

---

### `courses`
**Purpose:** Online courses

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Course ID |
| `title` | VARCHAR(255) | Course title |
| `description` | TEXT | Course description |
| `price` | DECIMAL(10,2) | Course price |
| `instructor` | VARCHAR(255) | Instructor name |
| `duration_hours` | DECIMAL(5,2) | Duration in hours |
| `level` | VARCHAR(50) | beginner, intermediate, advanced |
| `published` | BOOLEAN DEFAULT FALSE | Published? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `course_enrollments`
**Purpose:** Course enrollments

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Enrollment ID |
| `course_id` | INTEGER REFERENCES courses(id) | Course ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `enrolled_at` | TIMESTAMP DEFAULT NOW() | Enrollment date |
| `completed_at` | TIMESTAMP | Completion date |
| `progress` | INTEGER DEFAULT 0 | Progress percentage |

---

### `directory_members`
**Purpose:** Public directory member listings

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Member ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `display_order` | INTEGER | Display order |
| `featured` | BOOLEAN DEFAULT FALSE | Featured? |
| `visible` | BOOLEAN DEFAULT TRUE | Visible in directory? |

---

### `directory_transactions`
**Purpose:** Directory-related transactions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Transaction ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `transaction_type` | VARCHAR(50) | Transaction type |
| `amount` | DECIMAL(10,2) | Amount |
| `created_at` | TIMESTAMP DEFAULT NOW() | Transaction time |

---

### `stripe_customers`
**Purpose:** Stripe customer mappings

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Mapping ID |
| `user_id` | INTEGER REFERENCES users(id) UNIQUE | User ID |
| `stripe_customer_id` | VARCHAR(255) UNIQUE | Stripe customer ID |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `printful_sync`
**Purpose:** Printful product synchronization

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Sync ID |
| `product_id` | INTEGER REFERENCES products(id) | Product ID |
| `printful_product_id` | VARCHAR(100) | Printful product ID |
| `last_synced` | TIMESTAMP | Last sync time |
| `sync_status` | VARCHAR(50) | Sync status |

---

### `shipping_addresses`
**Purpose:** Customer shipping addresses

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Address ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `address_line1` | VARCHAR(255) | Address line 1 |
| `address_line2` | VARCHAR(255) | Address line 2 |
| `city` | VARCHAR(100) | City |
| `state` | VARCHAR(50) | State/province |
| `postal_code` | VARCHAR(20) | Postal code |
| `country` | VARCHAR(2) | Country code |
| `is_default` | BOOLEAN DEFAULT FALSE | Default address? |

---

### `website_hosting_plans`
**Purpose:** Website hosting plan options

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Plan ID |
| `name` | VARCHAR(100) | Plan name |
| `storage_gb` | INTEGER | Storage in GB |
| `bandwidth_gb` | INTEGER | Bandwidth in GB |
| `price` | DECIMAL(10,2) | Monthly price |
| `features` | JSONB | Plan features |

---

### `ai_automation_showcase`
**Purpose:** Showcase of AI automation examples

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Showcase ID |
| `title` | VARCHAR(255) | Automation title |
| `description` | TEXT | Description |
| `category` | VARCHAR(100) | Category |
| `demo_url` | TEXT | Demo URL |
| `visible` | BOOLEAN DEFAULT TRUE | Visible? |

---

## Projects & Websites

### `projects`
**Purpose:** User projects

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Project ID |
| `user_id` | INTEGER REFERENCES users(id) | Owner ID |
| `name` | VARCHAR(255) | Project name |
| `description` | TEXT | Project description |
| `project_type` | VARCHAR(50) | Type (web, app, api) |
| `status` | VARCHAR(50) | active, archived, deleted |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `updated_at` | TIMESTAMP | Update time |

---

### `project_files`
**Purpose:** Files in projects

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | File ID |
| `project_id` | INTEGER REFERENCES projects(id) | Project ID |
| `file_path` | TEXT | File path |
| `file_content` | TEXT | File content |
| `file_type` | VARCHAR(50) | File type |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `updated_at` | TIMESTAMP | Update time |

---

### `project_chat_history`
**Purpose:** Chat history for projects

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Chat ID |
| `project_id` | INTEGER REFERENCES projects(id) | Project ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `message` | TEXT | Message |
| `message_type` | VARCHAR(50) | user, assistant |
| `created_at` | TIMESTAMP DEFAULT NOW() | Message time |

---

### `user_websites`
**Purpose:** User-created websites

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Website ID |
| `user_id` | INTEGER REFERENCES users(id) | Owner ID |
| `name` | VARCHAR(255) | Website name |
| `description` | TEXT | Website description |
| `status` | VARCHAR(50) | active, inactive |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `user_website_subscriptions`
**Purpose:** Website-specific subscriptions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Subscription ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `plan_id` | INTEGER REFERENCES website_hosting_plans(id) | Plan ID |
| `status` | VARCHAR(50) | active, cancelled |
| `started_at` | TIMESTAMP DEFAULT NOW() | Start date |
| `expires_at` | TIMESTAMP | Expiration date |

---

### `website_domains`
**Purpose:** Domains for websites

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Domain ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `domain_name` | VARCHAR(255) UNIQUE | Domain name |
| `ssl_enabled` | BOOLEAN DEFAULT FALSE | SSL enabled? |
| `verified` | BOOLEAN DEFAULT FALSE | Domain verified? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `website_deployments`
**Purpose:** Website deployment history

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Deployment ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `deployed_by` | INTEGER REFERENCES users(id) | Deployer ID |
| `deployment_url` | TEXT | Deployment URL |
| `status` | VARCHAR(50) | pending, deployed, failed |
| `deployed_at` | TIMESTAMP DEFAULT NOW() | Deployment time |

---

### `website_backups`
**Purpose:** Website backups

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Backup ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `backup_path` | TEXT | Backup file path |
| `backup_size_mb` | DECIMAL(10,2) | Backup size in MB |
| `created_at` | TIMESTAMP DEFAULT NOW() | Backup time |

---

### `website_analytics`
**Purpose:** Website analytics data

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Analytics ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `metric_name` | VARCHAR(100) | Metric name |
| `metric_value` | DECIMAL(10,2) | Metric value |
| `recorded_at` | TIMESTAMP DEFAULT NOW() | Record time |

---

### `website_usage_tracking`
**Purpose:** Track website resource usage

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Usage ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `usage_type` | VARCHAR(50) | storage, bandwidth |
| `usage_amount` | DECIMAL(10,2) | Amount used |
| `recorded_at` | TIMESTAMP DEFAULT NOW() | Record time |

---

### `website_databases`
**Purpose:** Databases for websites

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Database ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `database_name` | VARCHAR(100) | Database name |
| `database_type` | VARCHAR(50) | PostgreSQL, MySQL |
| `size_mb` | DECIMAL(10,2) | Database size |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `website_env_vars`
**Purpose:** Environment variables for websites

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Env var ID |
| `website_id` | INTEGER REFERENCES user_websites(id) | Website ID |
| `key` | VARCHAR(100) | Variable name |
| `value` | TEXT | Encrypted value |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `client_sites`
**Purpose:** Client websites managed by ARCHIE

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Site ID |
| `client_name` | VARCHAR(255) | Client name |
| `site_url` | TEXT | Site URL |
| `hosting_provider` | VARCHAR(100) | Hosting provider |
| `status` | VARCHAR(50) | active, maintenance |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `deployments`
**Purpose:** General deployment records

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Deployment ID |
| `project_id` | INTEGER REFERENCES projects(id) | Project ID |
| `deployed_by` | INTEGER REFERENCES users(id) | Deployer ID |
| `environment` | VARCHAR(50) | production, staging |
| `status` | VARCHAR(50) | success, failed |
| `deployed_at` | TIMESTAMP DEFAULT NOW() | Deployment time |

---

### `managed_dns_records`
**Purpose:** DNS records for managed domains

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Record ID |
| `domain_id` | INTEGER REFERENCES website_domains(id) | Domain ID |
| `record_type` | VARCHAR(10) | A, CNAME, MX, TXT |
| `name` | VARCHAR(255) | Record name |
| `value` | TEXT | Record value |
| `ttl` | INTEGER DEFAULT 3600 | TTL in seconds |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

## System Management

### `system_config`
**Purpose:** System-wide configuration

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Config ID |
| `config_key` | VARCHAR(100) UNIQUE | Config key |
| `config_value` | TEXT | Config value |
| `description` | TEXT | Config description |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `system_settings`
**Purpose:** System settings

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Setting ID |
| `setting_key` | VARCHAR(100) UNIQUE | Setting key |
| `setting_value` | TEXT | Setting value |
| `setting_type` | VARCHAR(50) | string, integer, boolean, json |
| `description` | TEXT | Setting description |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `system_health`
**Purpose:** System health metrics

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Health ID |
| `component` | VARCHAR(100) | Component name |
| `status` | VARCHAR(50) | healthy, degraded, unhealthy |
| `message` | TEXT | Status message |
| `checked_at` | TIMESTAMP DEFAULT NOW() | Check time |

---

### `system_stats_cache`
**Purpose:** Cached system statistics

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Cache ID |
| `stat_key` | VARCHAR(100) UNIQUE | Stat key |
| `stat_value` | TEXT | Cached value |
| `expires_at` | TIMESTAMP | Cache expiration |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `service_status`
**Purpose:** Service health status

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Status ID |
| `service_name` | VARCHAR(100) | Service name |
| `status` | VARCHAR(50) | running, stopped, error |
| `last_check` | TIMESTAMP DEFAULT NOW() | Last check time |

---

### `system_alerts`
**Purpose:** System-level alerts

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Alert ID |
| `alert_type` | VARCHAR(50) | Alert type |
| `severity` | VARCHAR(20) | info, warning, error, critical |
| `message` | TEXT | Alert message |
| `acknowledged` | BOOLEAN DEFAULT FALSE | Acknowledged? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Alert time |
| `acknowledged_at` | TIMESTAMP | Acknowledgment time |

---

### `system_notifications`
**Purpose:** System-wide notifications

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Notification ID |
| `notification_type` | VARCHAR(50) | Notification type |
| `message` | TEXT | Notification message |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `audit_log`
**Purpose:** Comprehensive audit trail

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `username` | VARCHAR(100) | Username |
| `action` | VARCHAR(255) | Action performed |
| `resource_type` | VARCHAR(100) | Resource type |
| `resource_id` | INTEGER | Resource ID |
| `details` | TEXT | Action details |
| `ip_address` | VARCHAR(45) | Client IP |
| `user_agent` | TEXT | Browser info |
| `created_at` | TIMESTAMP DEFAULT NOW() | Log time |

**Indexes:**
- PRIMARY KEY on `id`
- B-tree on `user_id`, `action`, `created_at`

---

### `backup_log`
**Purpose:** Backup operation logs

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `backup_name` | VARCHAR(255) | Backup name |
| `backup_type` | VARCHAR(50) | full, incremental |
| `status` | VARCHAR(50) | success, failed |
| `size_mb` | DECIMAL(10,2) | Backup size |
| `duration_seconds` | INTEGER | Duration |
| `created_at` | TIMESTAMP DEFAULT NOW() | Backup time |

---

### `schema_migrations`
**Purpose:** Database schema migration tracking

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Migration ID |
| `migration_name` | VARCHAR(255) | Migration name |
| `migration_sql` | TEXT | Migration SQL |
| `applied_at` | TIMESTAMP DEFAULT NOW() | Application time |
| `rollback_sql` | TEXT | Rollback SQL |

---

### `budget_alerts`
**Purpose:** Budget and cost alerts

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Alert ID |
| `alert_type` | VARCHAR(50) | Alert type |
| `threshold` | DECIMAL(10,2) | Threshold value |
| `current_value` | DECIMAL(10,2) | Current value |
| `triggered_at` | TIMESTAMP DEFAULT NOW() | Trigger time |

---

### `call_queue`
**Purpose:** Agent call queue for telephony

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Queue ID |
| `agent_id` | INTEGER REFERENCES agents(id) | Agent ID |
| `priority` | INTEGER DEFAULT 0 | Queue priority |
| `status` | VARCHAR(50) | waiting, processing, completed |
| `created_at` | TIMESTAMP DEFAULT NOW() | Queue time |

---

### `usage_tracking`
**Purpose:** General usage tracking

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Usage ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `resource_type` | VARCHAR(100) | Resource type |
| `resource_id` | INTEGER | Resource ID |
| `action` | VARCHAR(100) | Action |
| `created_at` | TIMESTAMP DEFAULT NOW() | Usage time |

---

### `tool_usage`
**Purpose:** Tool usage analytics

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Usage ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `tool_name` | VARCHAR(100) | Tool name |
| `session_id` | TEXT | Session ID |
| `started_at` | TIMESTAMP DEFAULT NOW() | Start time |
| `ended_at` | TIMESTAMP | End time |

---

## Integration & External Services

### `github_repositories`
**Purpose:** GitHub repository integrations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Repo ID |
| `user_id` | INTEGER REFERENCES users(id) | Owner ID |
| `repo_name` | VARCHAR(255) | Repository name |
| `repo_url` | TEXT | Repository URL |
| `default_branch` | VARCHAR(100) DEFAULT 'main' | Default branch |
| `access_token` | TEXT | Encrypted access token |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `api_keys_config`
**Purpose:** API key configurations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Config ID |
| `key_name` | VARCHAR(100) | Key name |
| `encrypted_key` | TEXT | Encrypted API key |
| `provider` | VARCHAR(50) | Provider name |
| `enabled` | BOOLEAN DEFAULT TRUE | Enabled? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `admin_hostinger_config`
**Purpose:** Hostinger integration config

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Config ID |
| `api_token` | TEXT | Encrypted API token |
| `default_domain` | VARCHAR(255) | Default domain |
| `settings` | JSONB | Additional settings |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `email_config`
**Purpose:** Email service configuration

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Config ID |
| `provider` | VARCHAR(50) | Email provider |
| `smtp_host` | VARCHAR(255) | SMTP host |
| `smtp_port` | INTEGER | SMTP port |
| `smtp_username` | VARCHAR(255) | SMTP username |
| `smtp_password` | TEXT | Encrypted password |
| `from_email` | VARCHAR(255) | From email address |
| `enabled` | BOOLEAN DEFAULT TRUE | Enabled? |

---

### `email_templates`
**Purpose:** Email templates

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Template ID |
| `template_name` | VARCHAR(100) UNIQUE | Template name |
| `subject` | VARCHAR(255) | Email subject |
| `body_html` | TEXT | HTML body |
| `body_text` | TEXT | Plain text body |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `dns_providers`
**Purpose:** DNS provider configurations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Provider ID |
| `provider_name` | VARCHAR(100) | Provider name |
| `api_endpoint` | TEXT | API endpoint |
| `api_key` | TEXT | Encrypted API key |
| `enabled` | BOOLEAN DEFAULT TRUE | Enabled? |

---

### `dns_verification_challenges`
**Purpose:** DNS verification challenges

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Challenge ID |
| `domain_id` | INTEGER REFERENCES website_domains(id) | Domain ID |
| `challenge_type` | VARCHAR(50) | Challenge type |
| `challenge_token` | TEXT | Challenge token |
| `verified` | BOOLEAN DEFAULT FALSE | Verified? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `verified_at` | TIMESTAMP | Verification time |

---

### `webhook_logs`
**Purpose:** Webhook event logs

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `webhook_source` | VARCHAR(100) | Webhook source |
| `event_type` | VARCHAR(100) | Event type |
| `payload` | JSONB | Webhook payload |
| `status` | VARCHAR(50) | success, failed |
| `received_at` | TIMESTAMP DEFAULT NOW() | Receive time |

---

### `n8n_workflow_executions`
**Purpose:** n8n workflow execution logs

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Execution ID |
| `workflow_id` | VARCHAR(100) | Workflow ID |
| `workflow_name` | VARCHAR(255) | Workflow name |
| `status` | VARCHAR(50) | success, failed |
| `started_at` | TIMESTAMP | Start time |
| `finished_at` | TIMESTAMP | Finish time |

---

### `workflow_executions`
**Purpose:** General workflow executions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Execution ID |
| `workflow_id` | INTEGER | Workflow ID |
| `status` | VARCHAR(50) | running, completed, failed |
| `result` | JSONB | Execution result |
| `started_at` | TIMESTAMP DEFAULT NOW() | Start time |
| `completed_at` | TIMESTAMP | Completion time |

---

### `ai_conversations`
**Purpose:** AI conversation history

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Conversation ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `conversation_data` | JSONB | Conversation data |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `conversation_history`
**Purpose:** General conversation history

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | History ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `message` | TEXT | Message content |
| `role` | VARCHAR(50) | user, assistant, system |
| `created_at` | TIMESTAMP DEFAULT NOW() | Message time |

---

### `conversations`
**Purpose:** Conversation tracking

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Conversation ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `title` | VARCHAR(255) | Conversation title |
| `started_at` | TIMESTAMP DEFAULT NOW() | Start time |
| `ended_at` | TIMESTAMP | End time |

---

### `conversation_turns`
**Purpose:** Individual conversation turns

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Turn ID |
| `conversation_id` | INTEGER REFERENCES conversations(id) | Conversation ID |
| `role` | VARCHAR(50) | user, assistant |
| `content` | TEXT | Turn content |
| `created_at` | TIMESTAMP DEFAULT NOW() | Turn time |

---

### `llm_routing_history`
**Purpose:** LLM routing decisions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | History ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `task_type` | VARCHAR(100) | Task type |
| `routed_to` | VARCHAR(50) | Provider routed to |
| `model` | VARCHAR(100) | Model used |
| `cost` | DECIMAL(10,6) | Request cost |
| `created_at` | TIMESTAMP DEFAULT NOW() | Routing time |

---

### `provider_pricing`
**Purpose:** LLM provider pricing

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Pricing ID |
| `provider` | VARCHAR(50) | Provider name |
| `model` | VARCHAR(100) | Model name |
| `input_cost_per_1k` | DECIMAL(10,6) | Input cost |
| `output_cost_per_1k` | DECIMAL(10,6) | Output cost |
| `updated_at` | TIMESTAMP DEFAULT NOW() | Last update |

---

### `providers`
**Purpose:** LLM provider configurations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Provider ID |
| `provider_name` | VARCHAR(100) | Provider name |
| `api_endpoint` | TEXT | API endpoint |
| `enabled` | BOOLEAN DEFAULT TRUE | Enabled? |

---

### `token_usage_log`
**Purpose:** Token usage tracking

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Log ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `provider` | VARCHAR(50) | Provider |
| `model` | VARCHAR(100) | Model |
| `input_tokens` | INTEGER | Input tokens |
| `output_tokens` | INTEGER | Output tokens |
| `total_tokens` | INTEGER | Total tokens |
| `cost` | DECIMAL(10,6) | Cost |
| `created_at` | TIMESTAMP DEFAULT NOW() | Usage time |

---

### `ai_performance_metrics`
**Purpose:** AI performance metrics

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Metric ID |
| `provider` | VARCHAR(50) | Provider |
| `model` | VARCHAR(100) | Model |
| `avg_latency_ms` | INTEGER | Average latency |
| `success_rate` | DECIMAL(5,2) | Success rate percentage |
| `measured_at` | TIMESTAMP DEFAULT NOW() | Measurement time |

---

### `knowledge_base`
**Purpose:** General knowledge base

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Entry ID |
| `title` | VARCHAR(255) | Entry title |
| `content` | TEXT | Entry content |
| `category` | VARCHAR(100) | Category |
| `tags` | TEXT[] | Tags array |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `updated_at` | TIMESTAMP | Update time |

---

### `knowledge_base_queries`
**Purpose:** Knowledge base query logs

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Query ID |
| `user_id` | INTEGER REFERENCES users(id) | User ID |
| `query` | TEXT | Query text |
| `results_count` | INTEGER | Results count |
| `created_at` | TIMESTAMP DEFAULT NOW() | Query time |

---

### `knowledge_tags`
**Purpose:** Knowledge base tags

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Tag ID |
| `tag_name` | VARCHAR(100) UNIQUE | Tag name |
| `usage_count` | INTEGER DEFAULT 0 | Usage count |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `proposal_evaluations`
**Purpose:** Improvement proposal evaluations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Evaluation ID |
| `proposal_id` | INTEGER REFERENCES improvement_proposals(id) | Proposal ID |
| `evaluator` | VARCHAR(100) | Evaluator name |
| `score` | INTEGER CHECK (score BETWEEN 1 AND 10) | Score (1-10) |
| `comments` | TEXT | Evaluation comments |
| `created_at` | TIMESTAMP DEFAULT NOW() | Evaluation time |

---

### `team_consensus`
**Purpose:** Team consensus on decisions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Consensus ID |
| `topic` | VARCHAR(255) | Topic |
| `proposal` | TEXT | Proposal text |
| `votes_for` | INTEGER DEFAULT 0 | Votes for |
| `votes_against` | INTEGER DEFAULT 0 | Votes against |
| `consensus_reached` | BOOLEAN DEFAULT FALSE | Consensus reached? |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `escalations`
**Purpose:** Issue escalations

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Escalation ID |
| `escalation_type` | VARCHAR(50) | Escalation type |
| `description` | TEXT | Description |
| `priority` | VARCHAR(20) | low, medium, high, critical |
| `status` | VARCHAR(50) | open, in_progress, resolved |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |
| `resolved_at` | TIMESTAMP | Resolution time |

---

### `voice_phoneme_library`
**Purpose:** Voice synthesis phoneme library

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Phoneme ID |
| `phoneme` | VARCHAR(10) | Phoneme symbol |
| `audio_data` | BYTEA | Audio data |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

### `voice_word_cache`
**Purpose:** Cached synthesized words

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Cache ID |
| `word` | VARCHAR(255) | Word |
| `audio_data` | BYTEA | Synthesized audio |
| `created_at` | TIMESTAMP DEFAULT NOW() | Creation time |

---

## ER Diagram

### High-Level Entity Relationships

```
┌────────────────┐
│     USERS      │
└────────┬───────┘
         │
         ├─────────┬─────────┬─────────┬──────────┬─────────┐
         │         │         │         │          │         │
         ▼         ▼         ▼         ▼          ▼         ▼
    ┌────────┬────────┬─────────┬──────────┬──────────┬──────────┐
    │SESSIONS│PROJECTS│SUBSCR..│AGENT_EXEC│IMPROVEME │ WEBSITES │
    └────────┴────────┴─────────┴──────────┴──────────┴──────────┘


┌──────────────┐
│    AGENTS    │──────┐
└──────┬───────┘      │
       │              │
       ├─────────┬────┴─────┬───────────┬──────────────┐
       │         │          │           │              │
       ▼         ▼          ▼           ▼              ▼
  ┌─────────┬───────┬─────────┬───────────────┬────────────────┐
  │ SKILLS  │METRICS│WORKFLOWS│TEAM_ASSIGNMENTS│AGENT_EXECUTIONS│
  └─────────┴───────┴─────────┴───────────────┴────────────────┘


┌──────────────────────┐
│ IMPROVEMENT_PROPOSALS│
└──────┬───────────────┘
       │
       ├────────┬──────────┬────────────┬──────────────┐
       │        │          │            │              │
       ▼        ▼          ▼            ▼              ▼
  ┌───────┬─────────┬──────────┬────────────┬──────────────┐
  │ TEAMS │ STATES  │DEPLOYMEN │  SANDBOX   │  GIT_COMMITS │
  │       │         │  TS      │ INSTANCES  │              │
  └───────┴─────────┴──────────┴────────────┴──────────────┘


┌──────────────────┐
│ ARCHIE_KNOWLEDGE │
└──────┬───────────┘
       │
       ├────────┬─────────┬──────────┬─────────┐
       │        │         │          │         │
       ▼        ▼         ▼          ▼         ▼
  ┌─────────┬──────┬──────────┬──────────┬────────┐
  │LONG_TERM│CONTEX│PERSONALI │EMOTIONAL │RELATION│
  │ MEMORY  │  T   │  TY      │  STATE   │ SHIPS  │
  └─────────┴──────┴──────────┴──────────┴────────┘
```

### Key Relationships

**Users → Multiple Entities (1:N)**
- Sessions, Projects, Subscriptions, Agent Executions, Websites, Orders

**Agents → Multiple Entities (1:N)**
- Agent Skills, Agent Executions, Agent Metrics, Team Assignments

**Improvement Proposals → Multiple Entities (1:N)**
- Team Assignments, Workflow States, Deployments, Sandbox Instances, Git Commits

**Projects → Multiple Entities (1:N)**
- Project Files, Chat History, Deployments

**Websites → Multiple Entities (1:N)**
- Domains, Deployments, Backups, Analytics, Databases

---

## Database Maintenance

### Regular Maintenance Tasks

1. **Vacuum & Analyze** (Weekly)
   ```sql
   VACUUM ANALYZE;
   ```

2. **Index Maintenance** (Monthly)
   ```sql
   REINDEX DATABASE archie;
   ```

3. **Table Statistics Update** (Weekly)
   ```sql
   ANALYZE verbose;
   ```

4. **Cleanup Old Records** (Monthly)
   ```sql
   DELETE FROM audit_log WHERE created_at < NOW() - INTERVAL '90 days';
   DELETE FROM failed_logins WHERE attempted_at < NOW() - INTERVAL '30 days';
   DELETE FROM sessions WHERE expires_at < NOW();
   ```

### Performance Monitoring

Monitor these key metrics:
- Table sizes: `pg_total_relation_size()`
- Index usage: `pg_stat_user_indexes`
- Slow queries: `pg_stat_statements`
- Connection count: `pg_stat_activity`

---

## Backup Strategy

### Backup Schedule
- **Full Backup**: Daily at 2:00 AM
- **Incremental**: Every 6 hours
- **Critical Tables**: Continuous WAL archiving

### Retention Policy
- Daily backups: 7 days
- Weekly backups: 4 weeks
- Monthly backups: 12 months

---

## Security Considerations

### Encrypted Fields
- `users.password_hash` - Bcrypt hashed
- `api_keys_config.encrypted_key` - AES-256 encrypted
- `user_api_config.api_key` - AES-256 encrypted
- `email_config.smtp_password` - AES-256 encrypted

### Access Control
- Row-level security on sensitive tables
- Role-based permissions via `permissions` table
- Audit logging in `audit_log` table

---

## Migration History

| Migration | Date | Description |
|-----------|------|-------------|
| 001 | 2025-12-27 | Initial schema |
| 002 | 2025-12-30 | Agent system enhancements |
| 003 | 2025-12-31 | Multi-tier access, SaaS tables |
| 004 | 2026-01-01 | Consciousness system |
| 005 | 2026-01-01 | Improvement workflow automation |
| 006 | 2026-01-05 | Git commit tracking |
| 007 | 2026-01-05 | Knowledge base embeddings |

---

**Document Version:** 1.0
**Last Updated:** January 7, 2026
**Maintained By:** A.R.C.H.I.E. Platform Team

For questions or updates, please create an improvement proposal.
