# A.R.C.H.I.E. Agent Delegation System

**Updated:** 2025-12-30

## 🎯 Overview

The Agent Delegation System shows **which employee (agent) is handling each task** and provides visual indicators for **Internal Staff (FREE)** vs **Contractors (PAID)**.

---

## 📊 Agent Identity Structure

### Database Schema

All agents have the following identity fields (from `add_agent_identities.sql`):

```sql
ALTER TABLE agents
    ADD COLUMN first_name VARCHAR(100),
    ADD COLUMN last_name VARCHAR(100),
    ADD COLUMN email VARCHAR(255) UNIQUE,
    ADD COLUMN title VARCHAR(200),
    ADD COLUMN department VARCHAR(100),
    ADD COLUMN bio TEXT,
    ADD COLUMN avatar_url VARCHAR(500),
    ADD COLUMN pronouns VARCHAR(50) DEFAULT 'they/them',
    ADD COLUMN worker_type VARCHAR(20) DEFAULT 'internal';  -- NEW: internal or contract
```

### Agent Types

**Internal Staff (worker_type='internal'):**
- Local LLM models (Ollama)
- FREE - no API costs
- Examples: deepseek-coder-v2:16b, qwen2.5-coder:7b, llama3.1:8b

**Contractors (worker_type='contract'):**
- External API models
- PAID - per-token costs
- Examples: Claude Sonnet 4, GPT-4o, Grok Beta

---

## 🖥️ Admin Control Panel Integration

### Location
- **Admin Menu** → **👥 DIRECTORY** (Agent Directory)
- **Admin Menu** → **🔧 IMPROVEMENTS** (Improvements Chat)

### Directory Display

Each agent card shows:

1. **Worker Type Badge** (at top of card)
   - ✓ **INTERNAL STAFF (FREE)** - Green background
   - ⚠️ **CONTRACTOR (PAID)** - Red background

2. **Personal Identity**
   - Avatar (from avatar_url or generated)
   - First Name + Last Name
   - Pronouns (they/them, she/her, he/him, etc.)
   - Email

3. **Professional Info**
   - Title (job title)
   - Department
   - Agent Type
   - Bio

4. **Performance Metrics**
   - Tier (1-4 stars)
   - Model (LLM model name)
   - Monthly Budget
   - Total Cost

### Visual Indicators

**Internal Staff Cards:**
- Border: Green (#00FF00)
- Badge: Green background with ✓ checkmark
- Cost: Shows in green

**Contractor Cards:**
- Border: Red (#FF4444)
- Badge: Red background with ⚠️ warning icon
- Cost: Shows in red
- Hover: Red glow effect

---

## 💬 Improvements Chat Integration

### How It Works

When you send a message in the Improvements chat:

1. **Delegation System** selects best agent:
   - Analyzes task keywords
   - Matches to department
   - Prefers Internal Staff (FREE) first
   - Falls back to Contractors if needed

2. **Response Shows Delegation:**
   ```
   🤖 A.R.C.H.I.E.
   ✓ INTERNAL STAFF (FREE) | Operations Specialist - Operations

   [Agent's response to your message...]
   ```

3. **Audit Trail Created:**
   - Execution ID stored in `agent_executions` table
   - HR/Finance can query by execution_id
   - Complete record: who, what, when, cost

### Backend Files

**File:** `/mnt/archie_brain/ai_bridge/agent_delegation.py`

Key Functions:
- `select_best_agent_for_task()` - Chooses appropriate agent
- `execute_with_delegation()` - Runs task and shows delegation
- `get_agent_directory()` - Returns all agents with worker_type
- `get_execution_audit_trail()` - HR/Finance audit access

**File:** `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)`

Route: `@admin_bp.route('/improvements/chat', methods=['POST'])`
- Uses `execute_with_delegation()` instead of direct archie_bridge
- Returns delegation info, execution record, audit trail

Route: `@admin_bp.route('/agent-directory', methods=['GET'])`
- Returns ALL agent fields including identities
- Includes worker_type for visual indicators

---

## 📋 Complete Agent Fields

### Returned by `/tools/team-management/`:

```javascript
{
    id: 1,
    name: "Agent Name",               // Full display name
    first_name: "Jane",               // First name
    last_name: "Smith",               // Last name
    email: "jane.smith@archie.ai",   // Email address
    title: "Senior Developer",        // Job title
    department: "Engineering",        // Department
    pronouns: "she/her",             // Preferred pronouns
    bio: "Specialized in...",        // Biography
    avatar_url: "https://...",       // Profile picture URL
    tier: 3,                         // Tier (1-4)
    model: "deepseek-coder-v2:16b", // LLM model
    system_prompt: "You are...",     // System prompt
    capabilities: {...},             // JSON capabilities
    monthly_budget: 0.00,            // Budget (0 for internal)
    total_cost: 0.00,                // Lifetime cost
    total_tokens_used: 12500,        // Lifetime tokens
    status: "active",                // Status
    created_at: "2025-01-01...",    // Created timestamp
    last_used: "2025-12-30...",     // Last used timestamp
    worker_type: "internal",         // internal or contract
    agent_type: "Code Specialist",   // Agent type name
    category: "technical"            // Category
}
```

---

## 🎨 UI Components

### Directory Card HTML Structure

```html
<!-- Worker Type Badge -->
<div style="background: {badgeColor}; border: 1px solid {borderColor}; ...">
    {✓ INTERNAL STAFF (FREE) or ⚠️ CONTRACTOR (PAID)}
</div>

<!-- Avatar & Name -->
<div style="display: flex; gap: 15px;">
    <img src="{avatarUrl}" alt="{fullName}" style="border: 3px solid {borderColor};">
    <div>
        <div>{First Name Last Name}</div>
        <div>{pronouns}</div>
        <div>{Tier stars}</div>
    </div>
</div>

<!-- Title & Department -->
<div>{title}</div>
<div>{department} • {agent_type}</div>

<!-- Bio -->
<div>{bio substring...}</div>

<!-- Capabilities -->
<div>{specialty badges...}</div>

<!-- Contact & Metrics -->
<div>
    📧 {email}
    🤖 {model}
    {monthly_budget}
    Total: {total_cost}
</div>
```

### Improvements Chat Delegation Badge

```html
<div style="background: {badgeColor}; border: 1px solid {badgeColor}; ...">
    <span>{icon}</span>
    <span>{INTERNAL STAFF (FREE) or CONTRACTOR (PAID)}</span>
    <span>|</span>
    <span>{employee_name}</span>
    <span>-</span>
    <span>{department}</span>
</div>
```

---

## 🔍 Agent Selection Logic

### Department Keyword Mapping

```python
department_keywords = {
    'Engineering': ['code', 'bug', 'develop', 'implement', 'refactor', 'api'],
    'Quality Assurance': ['test', 'qa', 'quality', 'verify', 'validate'],
    'Documentation': ['document', 'readme', 'guide', 'explain'],
    'Infrastructure': ['deploy', 'server', 'database', 'devops'],
    'Security': ['security', 'auth', 'permission', 'vulnerability'],
    'Data Science': ['data', 'analysis', 'ml', 'model', 'analytics'],
    'Marketing': ['marketing', 'content', 'campaign', 'seo'],
    'Customer Support': ['support', 'help', 'customer', 'issue'],
    'Operations': ['optimize', 'process', 'efficiency', 'workflow'],
    'Finance': ['cost', 'budget', 'revenue', 'financial']
}
```

### Selection Priority

1. **Match keywords** to detect department
2. **Prefer Internal Staff** (worker_type='internal')
3. **Order by last_used** (least recently used gets priority)
4. **Fallback to any active agent** if no match

---

## 📊 Audit Trail

### agent_executions Table

Every task delegation creates a record:

```sql
CREATE TABLE agent_executions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL,              -- Which employee
    user_id INTEGER,                        -- Who requested
    task_description TEXT NOT NULL,         -- What they did
    status VARCHAR(50) NOT NULL,            -- running, completed, failed
    started_at TIMESTAMP DEFAULT NOW(),     -- When started
    completed_at TIMESTAMP,                 -- When finished
    duration_seconds INTEGER,               -- How long
    tokens_used INTEGER,                    -- Resources used
    cost DECIMAL(10, 4),                   -- Cost in USD
    input_data JSONB,                      -- Full task details
    result JSONB,                          -- Full response
    error TEXT,                            -- Error if failed
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Audit Trail Reference Format

Every response includes:
```
execution_id:12345|agent:8|user:1|timestamp:2025-12-30T18:00:00
```

HR/Finance can query:
```sql
SELECT * FROM agent_executions WHERE id = 12345;
```

---

## 🔧 Maintenance Notes

### IMPORTANT: Don't Break Old Code

**Before modifying agent queries:**
1. ✅ Check `/mnt/archie_brain/docs/` for schema documentation
2. ✅ Review `add_agent_identities.sql` for field list
3. ✅ Test with existing UI components
4. ✅ Update documentation after changes

### Required Fields for Directory UI

The JavaScript expects these fields (ALWAYS include in queries):
- `first_name`, `last_name`
- `email`, `title`, `department`
- `pronouns`, `bio`, `avatar_url`
- `tier`, `model`, `capabilities`
- `monthly_budget`, `total_cost`, `total_tokens_used`
- `status`, `created_at`, `last_used`
- `worker_type` (NEW - for delegation system)
- `agent_type`, `category` (from agent_types JOIN)

### Files That Query Agents

1. `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)`
   - Route: `/agent-directory`
   - Query: ALL fields listed above

2. `/mnt/archie_brain/ai_bridge/agent_delegation.py`
   - Function: `select_best_agent_for_task()`
   - Query: Core fields + worker_type

3. `/mnt/archie_brain/platform_v2/templates/ (now modular templates)`
   - Function: `displayAgentDirectory()`
   - Expects: All identity fields + worker_type

---

## ✅ Testing Checklist

### Directory
- [ ] All agent names display (first_name + last_name)
- [ ] Avatars load correctly
- [ ] Pronouns show below names
- [ ] Worker type badges display (green for internal, red for contractors)
- [ ] Border colors match worker type
- [ ] Email, title, department all visible
- [ ] Clicking card opens correct agent profile
- [ ] Export CSV includes all fields

### Improvements Chat
- [ ] Messages send without errors
- [ ] Delegation badge appears on A.R.C.H.I.E. messages
- [ ] Shows correct employee name and department
- [ ] Internal staff shows green badge
- [ ] Contractors show red badge with warning icon
- [ ] Memory indicators still work
- [ ] Audit trail reference included in response

---

## 📚 Related Documentation

- `/mnt/archie_brain/docs/BUSINESS_AGENTS_GUIDE.md` - Agent roster
- `/mnt/archie_brain/docs/AGENT_OPTIMIZATION_SUMMARY.md` - 73 agents breakdown
- `/mnt/archie_brain/docs/SELF_IMPROVEMENT_SYSTEM.md` - Improvements system
- `/mnt/archie_brain/docs/EMPLOYEE_AUDIT_TRAIL.md` - HR/Finance tracking
- `/mnt/archie_brain/docs/IMPROVEMENTS_SYSTEM_FIXES.md` - Recent fixes and enhancements
- `/mnt/archie_brain/database/migrations/add_agent_identities.sql` - Schema

---

## 🔄 Recent Updates (2025-12-30)

### Improvements Chat Integration
The Improvements chat in the standalone admin modules now fully integrates with the delegation system:
- Shows which employee (agent) is handling each conversation
- Visual badges: ✓ Green for Internal Staff (FREE), ⚠️ Red for Contractors (PAID)
- Complete audit trail in `agent_executions` table
- Memory integration with RAG (Retrieval Augmented Generation)

### Import Error Fixes
All import errors resolved with try/except fallbacks in:
- `archie_bridge.py`
- `improvement_chat.py`
- `improvement_engine.py`

See [IMPROVEMENTS_SYSTEM_FIXES.md](./IMPROVEMENTS_SYSTEM_FIXES.md) for complete details.

---

**Last Updated:** 2026-01-15
**Version:** 1.2
**Status:** ✅ Active

---

## 🆕 V2 Code Generation Integration (2026-01-15)

### prefer_contractor Parameter

The `select_best_agent_for_task()` function now supports a `prefer_contractor` parameter for routing complex tasks to external AI:

```python
from agent_delegation import select_best_agent_for_task

# Simple task - use internal agent (FREE)
agent = select_best_agent_for_task(
    task_description="Fix typo in comments",
    department_preference="Engineering",
    prefer_contractor=False  # Default
)

# Complex task - prefer contractor (PAID)
agent = select_best_agent_for_task(
    task_description="Fix SQL injection vulnerability",
    department_preference="Engineering",
    prefer_contractor=True  # Uses Claude/GPT-4 if available
)
```

### When to Use prefer_contractor=True

| Scenario | Recommendation |
|----------|----------------|
| Simple code fixes | `False` - Internal agents sufficient |
| Complex security issues | `True` - Better accuracy needed |
| Multi-file refactors | `True` - Complex reasoning required |
| After 3 retry failures | `True` - Escalate to contractor |
| Critical production bugs | `True` - Can't afford mistakes |

### Code Generation V2 Integration

The V2 Code Generation Engine uses Team Management for model selection:

```python
from code_generation_engine import generate_code_for_proposal

result = generate_code_for_proposal(
    proposal_id=123,
    proposal_title="Security Fix",
    proposal_description="...",
    category="security",
    prefer_contractor=True  # Routes to Claude/GPT-4
)
```

See `/docs/CODE_GENERATION_ENGINE_V2.md` for full documentation.
