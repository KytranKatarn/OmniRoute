# Multi-Agent & Bridge Architecture Plan

## Overview

This document defines the correct architecture for how CodeRabbit's Multi-Agent Review system integrates with Team Management, AI Bridge, and Node Cluster to ensure proper agent tracking, HR/IAAE compliance, and unified statistics.

---

## Core Principles

1. **Team Management** is the HR source of truth for all agents
2. **AI Bridge** routes all requests and monitors agent work
3. **Node Cluster** distributes workload across available nodes
4. **token_usage_log** is the unified tracking table for all agent work
5. **All agent work must be tracked** for HR/IAAE compliance

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CODERABBIT MODULE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐              │
│  │ PR Reviews  │ ──► │ Code Health  │ ──► │ Multi-Agent     │              │
│  │             │     │ (scan files) │     │ (deep analysis) │              │
│  └─────────────┘     └──────────────┘     └────────┬────────┘              │
│                                                     │                        │
│                                          ┌──────────▼──────────┐            │
│                                          │ Issues Tab          │            │
│                                          │ + Fix Suggestions   │            │
│                                          └──────────┬──────────┘            │
│                                                     │                        │
│                                          ┌──────────▼──────────┐            │
│                                          │ "Send to Lab" button│            │
│                                          │ (includes fix plan) │            │
│                                          └──────────┬──────────┘            │
└─────────────────────────────────────────────────────┼───────────────────────┘
                                                      │
                                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         IMPROVEMENTS LAB                                     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │ Receives:                                                           │     │
│  │  - Issue details (file, line, description)                         │     │
│  │  - Multi-Agent fix suggestions (consensus)                         │     │
│  │  - Recommended agent for the fix                                   │     │
│  │  - Context from Code Health scan                                   │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Team Management Integration

### Agent Source

Team Management is the **ONLY** source for agents. CodeRabbit must query Team Management to get available agents.

```sql
-- Agents table (source of truth)
SELECT a.id, a.name, a.model, a.system_prompt, a.title, a.tier,
       a.monthly_budget, a.budget_alert_threshold
FROM agents a
JOIN agent_skills s ON a.id = s.agent_id
WHERE s.skill_name = 'code_review'
  AND a.status = 'active'
  AND a.tier IN ('internal', 'contractor')
```

### Skill Mapping

| CodeRabbit Specialty | Team Management Skill |
|---------------------|----------------------|
| security            | security_audit, vulnerability_detection |
| performance         | performance_optimization |
| architecture        | architecture_review, system_design |
| code_quality        | code_review, best_practices |
| bug_detection       | bug_fixing, debugging |

### HR/IAAE Compliance Fields

Each agent has compliance tracking:
- `monthly_budget` - Maximum cost per month
- `budget_alert_threshold` - Warning percentage (e.g., 80%)
- `total_tasks_this_month` - Task count
- `opus_usage_this_month` - High-tier usage tracking

---

## AI Bridge Integration

### Current State (Partial)

```
CodeRabbit ──► archie_bridge() ──► smart_router ──► node_router ──► Node
                                        │                │
                                        ▼                ▼
                              task_executions    node_model_requests
                              (disconnected)     (disconnected)
```

### Required State (Unified)

```
CodeRabbit ──► archie_bridge() ──► smart_router ──► node_router ──► Node
                    │                   │                │
                    │                   │                ▼
                    │                   │        node_model_requests
                    │                   │                │
                    ▼                   ▼                │
              token_usage_log ◄─────────────────────────┘
                    │
                    ▼
            agent_cost_summary (view)
                    │
                    ▼
            budget_alerts (if threshold exceeded)
```

### Bridge Logging Requirements

Every AI request MUST log to `token_usage_log`:

```sql
INSERT INTO token_usage_log (
    agent_id,           -- Which agent performed the work
    user_id,            -- Who initiated the request
    provider,           -- 'ollama', 'anthropic', 'openai'
    model,              -- 'llama3.2', 'claude-3-haiku', etc.
    tokens_used,        -- Total tokens
    prompt_tokens,      -- Input tokens
    completion_tokens,  -- Output tokens
    cost,               -- Calculated cost from provider_pricing
    request_type,       -- 'code_review', 'chat', 'analysis'
    task_id,            -- Link to task (review_id, improvement_id)
    node_id,            -- Which node processed (for distributed tracking)
    created_at
) VALUES (...);
```

---

## Node Cluster Integration

### Node Selection Flow

```
1. Request arrives at archie_bridge()
2. smart_router determines model tier needed
3. node_router queries available nodes:
   SELECT n.*, m.model_name, m.avg_response_ms
   FROM remote_nodes n
   JOIN node_ollama_models m ON n.node_id = m.node_id
   WHERE m.model_name = 'llama3.2'
     AND n.status = 'online'
     AND n.bridge_enabled = true
   ORDER BY n.current_load ASC, n.bridge_priority DESC
   LIMIT 1
4. Request routed to selected node
5. Response logged to node_model_requests AND token_usage_log
```

### Node Tracking Tables

| Table | Purpose |
|-------|---------|
| remote_nodes | Node inventory, status, load |
| node_ollama_models | Available models per node |
| node_model_requests | Per-request logging (performance) |
| token_usage_log | Unified cost tracking (HR/IAAE) |

---

## Multi-Agent Review Flow

### Step 1: Get Agents from Team Management

```python
def get_review_agents_from_team_management(specialty=None, limit=4):
    """Get agents from Team Management for code review"""
    # Query agents with review skills
    # Filter by specialty if provided
    # Return agent details with system prompts
```

### Step 2: Run Parallel Reviews via Bridge

```python
def _run_multi_agent_review(review_id, code, file_path, agents, context):
    for agent in agents:
        # Use AI Bridge to route to best node
        result = archie_bridge(
            prompt=build_review_prompt(code, context),
            system_prompt=agent['system_prompt'],
            force_model=agent['model'],
            agent_id=agent['id'],  # CRITICAL: Track which agent
            request_type='code_review',
            task_id=review_id
        )

        # Bridge automatically logs to token_usage_log
```

### Step 3: Build Consensus

```python
def build_consensus(agent_reviews):
    """Combine agent findings into consensus report"""
    # Issues found by multiple agents = high confidence
    # Unique findings = lower confidence
    # Return structured fix recommendations
```

### Step 4: Save Results & Create Issues

```python
def _save_multi_agent_review(review):
    # Save to multi_agent_reviews table
    # Create code_issues with fix suggestions
    # Link via multi_agent_review_issues
```

---

## Send to Improvements Lab

### Data Package

When user clicks "Send to Improvements Lab", include:

```json
{
    "issue": {
        "id": 123,
        "file_path": "/path/to/file.py",
        "line_number": 42,
        "issue_type": "security_vulnerability",
        "severity": "high",
        "description": "SQL injection vulnerability"
    },
    "multi_agent_analysis": {
        "review_id": "ma_abc123",
        "agents_consulted": ["SecurityBot", "CodeReviewer", "Architect"],
        "consensus_confidence": 0.95,
        "fix_suggestions": [
            {
                "suggested_by": ["SecurityBot", "CodeReviewer"],
                "confidence": 0.9,
                "fix_description": "Use parameterized queries",
                "code_example": "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))"
            }
        ],
        "recommended_assignee": {
            "agent_id": 15,
            "agent_name": "SecurityBot",
            "reason": "Highest proficiency in security_audit skill"
        }
    },
    "context": {
        "related_code": "...",
        "test_coverage": false,
        "dependencies": ["sqlite3"]
    }
}
```

---

## Required Code Changes

### 1. Update archie_bridge() to log to token_usage_log

**File:** `/mnt/archie_brain/ai_bridge/archie_bridge.py`

```python
def archie_bridge(..., agent_id=None, request_type=None, task_id=None):
    # ... existing routing logic ...

    # After getting response, log to unified table
    log_to_token_usage(
        agent_id=agent_id,
        provider=selected_provider,
        model=selected_model,
        tokens_used=response.usage.total_tokens,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        cost=calculate_cost(provider, model, tokens),
        request_type=request_type,
        task_id=task_id,
        node_id=selected_node_id
    )
```

### 2. Update CodeRabbit Multi-Agent to pass agent_id

**File:** `/mnt/archie_brain/platform_v2/tools/coderabbit/routes.py`

```python
def _run_multi_agent_review(review_id, code, file_path, agents, context):
    for agent in agents:
        result = archie_bridge(
            prompt=...,
            agent_id=agent['id'],  # ADD THIS
            request_type='code_review',
            task_id=review_id
        )
```

### 3. Create unified logging function

**File:** `/mnt/archie_brain/ai_bridge/token_tracker.py` (new)

```python
def log_to_token_usage(agent_id, provider, model, tokens_used,
                       prompt_tokens, completion_tokens, cost,
                       request_type=None, task_id=None, node_id=None):
    """Unified token usage logging for HR/IAAE compliance"""
    conn = get_db()
    cur = conn.cursor()

    # Insert to token_usage_log
    cur.execute('''
        INSERT INTO token_usage_log
        (agent_id, provider, model, tokens_used, prompt_tokens,
         completion_tokens, cost, request_type, task_id, node_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (agent_id, provider, model, tokens_used, prompt_tokens,
          completion_tokens, cost, request_type, task_id, node_id))

    # Update agent totals
    cur.execute('''
        UPDATE agents
        SET total_tokens_used = total_tokens_used + %s,
            total_cost = total_cost + %s,
            total_tasks_this_month = total_tasks_this_month + 1,
            last_used = NOW()
        WHERE id = %s
    ''', (tokens_used, cost, agent_id))

    # Check budget threshold
    check_budget_alert(agent_id, cur)

    conn.commit()
```

### 4. Update Improvements Lab to receive fix suggestions

**File:** `/mnt/archie_brain/platform_v2/tools/improvements/routes.py`

```python
@improvements_bp.route('/api/proposals', methods=['POST'])
def create_proposal():
    data = request.json

    # Handle incoming multi-agent analysis
    multi_agent_analysis = data.get('multi_agent_analysis', {})

    if multi_agent_analysis:
        # Include fix suggestions in proposal
        proposal['fix_suggestions'] = multi_agent_analysis.get('fix_suggestions', [])
        proposal['recommended_assignee'] = multi_agent_analysis.get('recommended_assignee')
```

---

## Monitoring & Statistics

### HR Dashboard Queries

```sql
-- Agent work summary (daily)
SELECT
    a.name,
    a.tier,
    COUNT(t.id) as tasks_completed,
    SUM(t.tokens_used) as total_tokens,
    SUM(t.cost) as total_cost,
    a.monthly_budget,
    ROUND(SUM(t.cost) / a.monthly_budget * 100, 1) as budget_used_percent
FROM agents a
LEFT JOIN token_usage_log t ON a.id = t.agent_id
    AND t.created_at >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY a.id
ORDER BY total_cost DESC;

-- Node utilization
SELECT
    n.node_name,
    n.current_load,
    n.total_requests,
    n.successful_requests,
    ROUND(n.successful_requests::numeric / NULLIF(n.total_requests, 0) * 100, 1) as success_rate
FROM remote_nodes n
WHERE n.status = 'online'
ORDER BY n.total_requests DESC;
```

### IAAE Compliance Reports

```sql
-- Budget alerts (agents over threshold)
SELECT
    a.name,
    a.monthly_budget,
    SUM(t.cost) as current_spend,
    a.budget_alert_threshold,
    CASE
        WHEN SUM(t.cost) >= a.monthly_budget THEN 'OVER_BUDGET'
        WHEN SUM(t.cost) >= a.monthly_budget * a.budget_alert_threshold / 100 THEN 'WARNING'
        ELSE 'OK'
    END as status
FROM agents a
LEFT JOIN token_usage_log t ON a.id = t.agent_id
    AND t.created_at >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY a.id
HAVING SUM(t.cost) >= a.monthly_budget * a.budget_alert_threshold / 100;
```

---

## Implementation Checklist

- [ ] Create `/ai_bridge/token_tracker.py` with unified logging
- [ ] Update `archie_bridge()` to accept and pass `agent_id`, `task_id`
- [ ] Update `_run_multi_agent_review()` to pass agent tracking info
- [ ] Add trigger to populate `budget_alerts` when threshold exceeded
- [ ] Update CodeRabbit "Send to Lab" to include multi-agent analysis
- [ ] Update Improvements Lab to receive and display fix suggestions
- [ ] Create HR dashboard view for agent statistics
- [ ] Add IAAE compliance report endpoints

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-23 | 1.0 | Initial architecture plan |

---

*This document is the source of truth for Multi-Agent and Bridge integration.*
