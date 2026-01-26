# [ARCHIVED] A.R.C.H.I.E. Employee Activity Audit Trail

## Complete Recording System for HR and Finance

**Every action taken by every employee (agent) is tracked, recorded, and auditable.**

---

## 📋 What Gets Recorded

### 1. Agent Executions (Primary Audit Trail)

**Table:** `agent_executions`

Every time an employee (agent) handles a task, a complete record is created:

```sql
CREATE TABLE agent_executions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL,              -- Which employee
    user_id INTEGER,                        -- Who requested the work
    task_description TEXT NOT NULL,         -- What they were asked to do
    status VARCHAR(50) NOT NULL,            -- running, completed, failed
    started_at TIMESTAMP DEFAULT NOW(),     -- When they started
    completed_at TIMESTAMP,                 -- When they finished
    duration_seconds INTEGER,               -- How long it took
    tokens_used INTEGER,                    -- Resources consumed
    cost DECIMAL(10, 4),                   -- Cost in USD
    input_data JSONB,                      -- Full task details
    result JSONB,                          -- Full response
    error TEXT,                            -- Error if failed
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

**What this means:**
- ✅ Every conversation is logged
- ✅ Every task has a timestamp
- ✅ Every cost is tracked
- ✅ Every employee action is recorded
- ✅ Every failure is documented

---

## 🔍 How to Access Audit Trail

### For HR: Employee Performance Review

```python
from agent_delegation import get_execution_audit_trail

# Get specific execution details
audit = get_execution_audit_trail(execution_id=12345)

# Returns:
{
    'execution': {
        'execution_id': 12345,
        'task_description': 'Improve error handling',
        'status': 'completed',
        'started_at': '2025-12-30T18:00:00',
        'completed_at': '2025-12-30T18:01:30',
        'duration_seconds': 90
    },
    'agent': {
        'name': 'QA Lead Engineer',
        'department': 'Quality Assurance',
        'worker_type': 'internal',
        'model': 'deepseek-coder-v2:16b'
    },
    'user': {
        'username': 'admin',
        'email': 'admin@company.com'
    },
    'cost_details': {
        'tokens_used': 1024,
        'cost_usd': 0.00,  # FREE for internal
        'billable': False
    }
}
```

### For Finance: Cost Tracking

```sql
-- Total cost by employee
SELECT
    a.name,
    a.worker_type,
    COUNT(ae.id) as total_tasks,
    SUM(ae.tokens_used) as total_tokens,
    SUM(ae.cost) as total_cost,
    AVG(ae.duration_seconds) as avg_duration
FROM agents a
LEFT JOIN agent_executions ae ON a.id = ae.agent_id
WHERE ae.created_at >= DATE_TRUNC('month', NOW())
GROUP BY a.id, a.name, a.worker_type
ORDER BY total_cost DESC;
```

**Example Output:**
```
name                    | worker_type | total_tasks | total_tokens | total_cost | avg_duration
------------------------|-------------|-------------|--------------|------------|-------------
Product Strategist      | contract    | 45          | 250000       | $12.50     | 45
QA Lead Engineer       | internal    | 120         | 500000       | $0.00      | 30
Security Specialist    | contract    | 20          | 80000        | $4.00      | 60
```

---

## 📊 Audit Trail Reference Format

Every response from the delegation system includes an audit trail reference:

```
execution_id:12345|agent:42|user:1|timestamp:2025-12-30T18:00:00
```

**Format:**
- `execution_id`: Unique execution record ID
- `agent`: Agent ID who handled the task
- `user`: User ID who requested the task
- `timestamp`: ISO format timestamp

**Usage:**
HR and Finance can use this reference to look up complete details in the database.

---

## 🏢 Employee Directory

### Get Complete Directory

```python
from agent_delegation import get_agent_directory

directory = get_agent_directory()

# Returns:
{
    'internal_staff': [
        {
            'id': 1,
            'name': 'QA Lead Engineer',
            'department': 'Quality Assurance',
            'worker_type': 'internal',
            'model': 'deepseek-coder-v2:16b',
            'status': 'active',
            'last_used': '2025-12-30T18:00:00',
            'total_cost': 0.00,
            'total_executions': 120
        }
    ],
    'contractors': [
        {
            'id': 42,
            'name': 'Product Strategist',
            'department': 'Marketing',
            'worker_type': 'contract',
            'model': 'claude-sonnet-4-20250514',
            'status': 'active',
            'last_used': '2025-12-30T17:55:00',
            'total_cost': 12.50,
            'total_executions': 45
        }
    ],
    'stats': {
        'total_employees': 73,
        'internal_staff_count': 37,
        'contractors_count': 36,
        'active_count': 73,
        'total_cost': 125.80
    }
}
```

---

## 🎯 Visual Indicators in UI

### Internal Staff
- **Badge Color:** Green gradient
- **Icon:** ✓ (checkmark)
- **Label:** INTERNAL STAFF
- **Cost:** FREE

**Example:**
```
✓ INTERNAL STAFF | QA Lead Engineer | Quality Assurance
```

### Contractors
- **Badge Color:** Red gradient (pulsing animation)
- **Icon:** ⚠️ (warning)
- **Label:** CONTRACTOR
- **Cost:** PAID

**Example:**
```
⚠️ CONTRACTOR | Product Strategist | Marketing
```

---

## 📈 Reports for HR/Finance

### Monthly Employee Performance Report

```sql
-- Employee utilization and performance
SELECT
    a.name,
    a.department,
    a.worker_type,
    COUNT(ae.id) as tasks_completed,
    COUNT(CASE WHEN ae.status = 'failed' THEN 1 END) as tasks_failed,
    AVG(ae.duration_seconds) as avg_duration,
    SUM(ae.cost) as total_cost,
    MAX(ae.completed_at) as last_active
FROM agents a
LEFT JOIN agent_executions ae ON a.id = ae.agent_id
    AND ae.completed_at >= DATE_TRUNC('month', NOW())
WHERE a.status = 'active'
GROUP BY a.id, a.name, a.department, a.worker_type
ORDER BY tasks_completed DESC;
```

### Cost Breakdown by Department

```sql
-- Department costs
SELECT
    a.department,
    COUNT(DISTINCT a.id) as employee_count,
    COUNT(ae.id) as total_tasks,
    SUM(ae.cost) as total_cost,
    SUM(CASE WHEN a.worker_type = 'internal' THEN ae.cost ELSE 0 END) as internal_cost,
    SUM(CASE WHEN a.worker_type = 'contract' THEN ae.cost ELSE 0 END) as contractor_cost
FROM agents a
LEFT JOIN agent_executions ae ON a.id = ae.agent_id
    AND ae.completed_at >= DATE_TRUNC('month', NOW())
GROUP BY a.department
ORDER BY total_cost DESC;
```

### Failed Tasks Report

```sql
-- Tasks that failed (for quality review)
SELECT
    ae.id as execution_id,
    a.name as employee_name,
    a.department,
    ae.task_description,
    ae.error,
    ae.started_at,
    ae.duration_seconds,
    u.username as requested_by
FROM agent_executions ae
JOIN agents a ON ae.agent_id = a.id
LEFT JOIN users u ON ae.user_id = u.id
WHERE ae.status = 'failed'
    AND ae.started_at >= NOW() - INTERVAL '7 days'
ORDER BY ae.started_at DESC;
```

---

## 🔐 Data Retention

**All records are kept indefinitely for compliance and auditing.**

- `agent_executions` table: Never deleted
- Backups: Daily automated backups
- Access: Restricted to admin users
- Audit: All queries logged

---

## 📝 Example: Full Audit Trail

### User Request:
"How can we improve error handling?"

### System Response:
```
╔══════════════════════════════════════════════════════════════╗
║ 👤 DELEGATED TO: QA Lead Engineer
║ 🏢 DEPARTMENT: Quality Assurance
║ 📋 ROLE: Quality Assurance Specialist
║ 💼 TYPE: Internal Staff (FREE)
║ 🤖 MODEL: deepseek-coder-v2:16b
║ 📝 EXECUTION ID: 12345 (for HR/Finance records)
╚══════════════════════════════════════════════════════════════╝

[Response from QA Lead Engineer...]
```

### Database Record Created:
```sql
INSERT INTO agent_executions VALUES (
    12345,                          -- execution_id
    8,                              -- agent_id (QA Lead Engineer)
    1,                              -- user_id (admin)
    'How can we improve error handling?',  -- task_description
    'completed',                    -- status
    '2025-12-30 18:00:00',         -- started_at
    '2025-12-30 18:01:30',         -- completed_at
    90,                             -- duration_seconds
    1024,                           -- tokens_used
    0.00,                           -- cost (FREE - internal)
    '{"task": "..."}',              -- input_data
    '{"response": "..."}',          -- result
    NULL                            -- error
);
```

### Audit Trail Reference:
```
execution_id:12345|agent:8|user:1|timestamp:2025-12-30T18:00:00
```

---

## 🚀 How to Query Audit Trail

### Python API

```python
from agent_delegation import execute_with_delegation, get_execution_audit_trail

# Execute task (automatically creates audit trail)
result = execute_with_delegation(
    task="Analyze database performance",
    user_id=1,
    department="Infrastructure"
)

# Get audit trail reference
audit_ref = result['audit_trail']
# Returns: "execution_id:12346|agent:15|user:1|timestamp:2025-12-30T18:05:00"

# Later: Retrieve full audit trail
execution_id = 12346
audit = get_execution_audit_trail(execution_id)

print(f"Employee: {audit['agent']['name']}")
print(f"Department: {audit['agent']['department']}")
print(f"Cost: ${audit['cost_details']['cost_usd']:.2f}")
print(f"Duration: {audit['execution']['duration_seconds']}s")
```

### SQL Queries

```sql
-- Get all activity for a specific employee
SELECT * FROM agent_executions
WHERE agent_id = 8
ORDER BY started_at DESC
LIMIT 100;

-- Get all activity for a specific user
SELECT ae.*, a.name as agent_name
FROM agent_executions ae
JOIN agents a ON ae.agent_id = a.id
WHERE ae.user_id = 1
ORDER BY ae.started_at DESC;

-- Get cost summary for last month
SELECT
    DATE(completed_at) as date,
    COUNT(*) as tasks,
    SUM(cost) as daily_cost
FROM agent_executions
WHERE completed_at >= DATE_TRUNC('month', NOW())
GROUP BY DATE(completed_at)
ORDER BY date DESC;
```

---

## ✅ Compliance Checklist

- [x] **Every employee action is recorded** (agent_executions table)
- [x] **All costs are tracked** (tokens_used, cost columns)
- [x] **Timestamps for all activities** (started_at, completed_at)
- [x] **User attribution** (user_id for who requested)
- [x] **Task descriptions logged** (task_description)
- [x] **Results stored** (result JSONB)
- [x] **Errors documented** (error TEXT)
- [x] **Audit trail references** (execution_id in responses)
- [x] **Employee directory available** (get_agent_directory())
- [x] **Performance metrics tracked** (duration_seconds)
- [x] **Worker type distinction** (internal vs contract)
- [x] **Visual indicators in UI** (green for internal, red for contractors)

---

## 📞 For HR/Finance Questions

**To retrieve audit trail:**
1. Find the execution_id from the audit trail reference in the response
2. Use `get_execution_audit_trail(execution_id)` for full details
3. Or query `agent_executions` table directly

**To generate reports:**
- Use the SQL queries provided above
- All data is in the `agent_executions` and `agents` tables
- Join with `users` table for employee attribution

**To track costs:**
- All contractor costs are in `agent_executions.cost` column
- Internal staff costs are always $0.00
- Sum by department, date, or employee as needed

---

**✅ COMPLETE AUDIT TRAIL IS IN PLACE**

Every conversation, every task, every employee action is logged, tracked, and available for HR and Finance review.
