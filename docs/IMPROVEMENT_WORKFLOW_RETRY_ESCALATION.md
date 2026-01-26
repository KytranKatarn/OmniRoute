# Improvement Workflow: Test-Retry Loop + Contractor Escalation

**Created**: 2026-01-14
**Status**: Implementation In Progress
**Plan File**: `/home/kytran/.claude/plans/jazzy-exploring-fox.md`

---

## Overview

This document describes the implementation of an automated test-fail-retry loop with contractor escalation for the A.R.C.H.I.E. Improvements Lab.

### Goals
1. Automatically retry failed tests up to 3 times
2. Pass failure context to agents for smarter regeneration
3. Escalate to external AI contractors after max retries
4. Enable real-time chat between human and contractors
5. Enforce strict queue (one proposal at a time)
6. Give agents unique personalities in chat

---

## System Flow

```
CodeRabbit Issue → Proposal → Team Assignment → Code Generation
                                                      ↓
                                               Sandbox Testing
                                                      ↓
                                              ┌─────────────┐
                                              │ Tests Pass? │
                                              └─────────────┘
                                                      │
                            ┌─────────────────────────┴──────────────────────────┐
                           YES                                                   NO
                            │                                                    │
                            ▼                                                    ▼
                    ┌───────────────┐                                 ┌─────────────────┐
                    │ Ready for     │                                 │ Retry < 3?      │
                    │ Review/Deploy │                                 └─────────────────┘
                    └───────────────┘                                          │
                                                           ┌───────────────────┴───────────────────┐
                                                          YES                                      NO
                                                           │                                       │
                                                           ▼                                       ▼
                                                 ┌─────────────────┐                    ┌──────────────────┐
                                                 │ Same Agent      │                    │ ESCALATE TO      │
                                                 │ Retries with    │                    │ CONTRACTOR       │
                                                 │ Failure Context │                    └──────────────────┘
                                                 └─────────────────┘                             │
                                                           │                                     ▼
                                                           │                         ┌──────────────────┐
                                                           │                         │ Human + Contractor│
                                                           │                         │ Chat in UI       │
                                                           │                         └──────────────────┘
                                                           │                                     │
                                                           │                    ┌────────────────┼────────────────┐
                                                           │                    │                │                │
                                                           │                    ▼                ▼                ▼
                                                           │            ┌────────────┐   ┌────────────┐   ┌────────────┐
                                                           │            │ Apply Fix  │   │ Try Other  │   │ Human Only │
                                                           │            │ & Retest   │   │ Contractor │   │ Investigation│
                                                           │            └────────────┘   └────────────┘   └────────────┘
                                                           │                    │
                                                           └────────────────────┘
```

---

## Implementation Phases

### Phase 0: Contractor Setup
Ensure 1 contractor agent per external AI provider:
- Claude Contractor (Anthropic)
- GPT Contractor (OpenAI)
- Gemini Contractor (Google)
- Grok Contractor (X-AI)
- Meta Contractor (Meta)
- Copilot Contractor (Microsoft)
- Perplexity Contractor (Perplexity)

### Phase 1: Database Migration
Add columns to `improvement_proposals`:
```sql
-- Retry tracking
test_retry_count INTEGER DEFAULT 0
test_failure_context JSONB

-- Escalation tracking
escalation_status VARCHAR(50)  -- none, contractor_consulting, human_reviewing, human_only
contractor_proposal JSONB
contractor_agent_id INTEGER
escalated_at TIMESTAMP
```

Add columns to `agents`:
```sql
-- Personality system
personality_prompt TEXT
communication_style VARCHAR(50)
memory_context JSONB
```

### Phase 2: Queue System
Enforce ONE proposal at a time:
- `sandbox_queue.py` - Queue management
- Block new processing if another is active
- Track queue position and wait times

### Phase 3: Test Retry Handler
New file: `/ai_bridge/test_retry_handler.py`
- `handle_test_failure()` - Decide retry vs escalate
- `build_failure_context()` - Extract test details
- `trigger_agent_retry()` - Call same agent with context
- `escalate_to_contractor()` - Send to external AI

### Phase 4: Contractor Integration
Modify `/ai_bridge/archie_bridge.py`:
- Route to correct API based on contractor
- Pass failure context in prompt
- Store contractor proposal for human review

### Phase 5: Fluid Chat System
New file: `/ai_bridge/chat_handler.py`
- WebSocket endpoint for real-time messaging
- Agent routing (internal vs contractor)
- "Typing" indicators
- Message history with context

### Phase 6: Agent Personality
- Unique personality prompts per agent
- Communication style (formal, casual, technical)
- Memory of past interactions
- Work history context

### Phase 7: UI COMPLETE REBUILD (Required)

**Problem**: Current `improvements_lab.html` is 4,340 lines with ~100 JS functions - a frankenstein of multiple implementation attempts that has broken event handlers and mixed paradigms.

**Solution**: Complete UI rebuild with modular architecture.

See **Phase 9: UI Redesign** below for full details.

### Phase 8: Blueprint Integration
Update roadmap and module status

---

## Key Files

| File | Purpose |
|------|---------|
| `migrations/025_test_retry_loop.sql` | Database schema changes |
| `ai_bridge/test_retry_handler.py` | Retry + escalation logic |
| `ai_bridge/chat_handler.py` | WebSocket real-time chat |
| `platform_v2/sandbox_queue.py` | Strict queue enforcement |
| `tools/improvements/routes.py` | API endpoints |
| `templates/tools/improvements_lab.html` | UI updates |

---

## API Endpoints (New)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/proposals/<id>/retry` | POST | Manual retry trigger |
| `/proposals/escalated` | GET | List escalated proposals |
| `/proposals/<id>/contractor-chat` | POST | Send message to contractor |
| `/proposals/<id>/apply-contractor-fix` | POST | Apply contractor's fix |
| `/proposals/<id>/escalate-to-human-only` | POST | Mark as too complex |
| `/ws/chat/proposal/<id>` | WebSocket | Real-time chat |

---

## Success Criteria

- [ ] Proposals queue one-at-a-time
- [ ] Failed tests trigger automatic retry (up to 3x)
- [ ] After 3 failures, contractor is consulted
- [ ] Human can chat with contractor in real-time
- [ ] Agents have unique personalities in chat
- [ ] All changes documented
- [ ] Blueprint Module updated
- [ ] End-to-end workflow tested

---

## Related Documentation

- [Improvement Workflow Complete Guide](IMPROVEMENT_WORKFLOW_COMPLETE_GUIDE.md)
- [Master Status and Roadmap](MASTER_STATUS_AND_ROADMAP_2026.md)
- [Agent Directory](AGENT_DIRECTORY.md)
- [Database Schema](DATABASE_SCHEMA_DOCUMENTATION.md)

---

---

## Phase 9: UI Redesign (CRITICAL)

### Current State Analysis

**File**: `templates/tools/improvements_lab.html`
- **Lines**: 4,340
- **Functions**: ~100 JavaScript functions
- **Modals**: 3 (createPlanModal, proposalDetailModal, sandboxViewerModal)
- **Issues**:
  - Mixed implementation approaches from previous iterations
  - Broken event handlers (buttons don't respond)
  - Hardcoded URLs that may not match current routes
  - Duplicate/conflicting function definitions
  - No separation of concerns (HTML, CSS, JS all inline)
  - Impossible to maintain or debug

### UI Architecture Redesign

#### Option A: Modular Single Page (Recommended)
Split into logical components while keeping Flask templates:

```
templates/tools/improvements_lab/
├── base.html              # Main layout (extends base.html)
├── components/
│   ├── proposal_list.html      # Proposal grid/list view
│   ├── proposal_detail.html    # Single proposal view
│   ├── sandbox_viewer.html     # Sandbox management
│   ├── escalation_panel.html   # Contractor chat & escalation
│   ├── queue_status.html       # Queue visualization
│   └── filters.html            # Status/category filters
└── js/
    ├── proposals.js            # Proposal CRUD operations
    ├── sandbox.js              # Sandbox management
    ├── chat.js                 # Contractor chat
    └── queue.js                # Queue management
```

#### Option B: React/Vue Component Library
For future consideration - full SPA approach with API-only backend.

### New UI Layout Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ IMPROVEMENTS LAB                                               [User] [?]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─────────────────────────────────────┐  ┌────────────────────────────────┐ │
│ │ 📋 QUEUE STATUS                     │  │ 🔍 FILTERS                     │ │
│ │ Currently Testing: Proposal #68     │  │ [All] [Pending] [Testing]      │ │
│ │ Queue: 3 waiting                    │  │ [Escalated] [Deployed]         │ │
│ │ [View Queue →]                      │  │ Category: [All ▼]              │ │
│ └─────────────────────────────────────┘  └────────────────────────────────┘ │
│                                                                             │
│ ┌───────────────────────────────────────────────────────────────────────────┤
│ │ PROPOSALS                                              [+ New Proposal]  │ │
│ ├───────────────────────────────────────────────────────────────────────────┤
│ │                                                                          │ │
│ │ ┌──────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ #68 - SQL Injection Fix                           🔴 ESCALATED       │ │ │
│ │ │ Category: Security | Priority: High | Retries: 3/3                   │ │ │
│ │ │ Contractor: Claude (Anthropic) - Awaiting Response                   │ │ │
│ │ │ [View Details] [Chat with Contractor] [Apply Fix]                    │ │ │
│ │ └──────────────────────────────────────────────────────────────────────┘ │ │
│ │                                                                          │ │
│ │ ┌──────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ #67 - Add Dark Mode Toggle                        🟡 TESTING         │ │ │
│ │ │ Category: UI | Priority: Medium | Retry: 1/3                         │ │ │
│ │ │ Agent: Marcus (Security Engineer)                                    │ │ │
│ │ │ [View Sandbox] [View Logs] [Cancel]                                  │ │ │
│ │ └──────────────────────────────────────────────────────────────────────┘ │ │
│ │                                                                          │ │
│ └───────────────────────────────────────────────────────────────────────────┘
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Proposal Detail View (Modal or Page)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROPOSAL #68: SQL Injection Fix                                      [×]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─────────────────────────────────┐  ┌────────────────────────────────────┐ │
│ │ 📋 DETAILS                      │  │ 🧪 SANDBOX                         │ │
│ │ Status: Escalated               │  │ Type: Schema Separation            │ │
│ │ Category: Security              │  │ Status: Ready                      │ │
│ │ Priority: High                  │  │ Schema: sandbox_prop_68            │ │
│ │ Complexity: High                │  │ Created: 2026-01-14 10:30          │ │
│ │ Created: 2026-01-14             │  │                                    │ │
│ │                                 │  │ [▶️ Run Tests] [📄 Logs] [🗑️ Destroy] │ │
│ └─────────────────────────────────┘  └────────────────────────────────────┘ │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🔄 RETRY STATUS                                                         │ │
│ │ Attempts: ●●●○  (3/3 exhausted)                                        │ │
│ │ Last Error: SQL injection vulnerability detected in routes.py:45       │ │
│ │ Recurring Pattern: Same vulnerability in 3 attempts                     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🔬 TEST RESULTS                                                         │ │
│ │ Passed: 2 | Failed: 1 | Duration: 4.2s                                 │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ ✅ test_basic_query      PASS   0.1s                                │ │ │
│ │ │ ✅ test_connection       PASS   0.2s                                │ │ │
│ │ │ ❌ test_sql_injection    FAIL   3.9s                                │ │ │
│ │ │    Error: SQL injection vulnerability detected                      │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 💬 CONTRACTOR CONSULTATION                                              │ │
│ │ Contractor: Claude (Anthropic)                                          │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ [System] Escalated to Claude (Anthropic)           14:30            │ │ │
│ │ │ [Claude] I've analyzed the code. The issue is...   14:31            │ │ │
│ │ │ [You] Can you show me the specific fix?            14:32            │ │ │
│ │ │ [Claude] Here's the parameterized query fix:       14:32            │ │ │
│ │ │          ```python                                                  │ │ │
│ │ │          cur.execute("SELECT * FROM users WHERE id = %s", (id,))    │ │ │
│ │ │          ```                                                        │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ │ ┌─────────────────────────────────────────────────────────────────────┐ │ │
│ │ │ Type message...                                            [Send]  │ │ │
│ │ └─────────────────────────────────────────────────────────────────────┘ │ │
│ │                                                                         │ │
│ │ [✅ Apply Contractor Fix] [🔄 Try Another Contractor] [⚠️ Human Only]   │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ACTIONS                                                                 │ │
│ │ [Reset Retries] [Re-run Tests] [View Code Changes] [Deploy to Prod]    │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Steps

#### Step 1: Create Base Structure
```bash
mkdir -p templates/tools/improvements_lab/components
mkdir -p static/js/improvements_lab
```

#### Step 2: Extract and Refactor JavaScript
Move JS into separate files with clear responsibilities:

| File | Responsibility |
|------|----------------|
| `proposals.js` | Load, filter, create, approve, reject proposals |
| `sandbox.js` | Create, test, destroy sandboxes |
| `chat.js` | Contractor chat, message history |
| `queue.js` | Queue status, position tracking |
| `ui.js` | Notifications, modals, common UI |

#### Step 3: Build Component Templates
Each component as a Jinja2 macro or partial:

```html
{# components/proposal_card.html #}
{% macro proposal_card(proposal) %}
<div class="proposal-card" data-id="{{ proposal.id }}">
    <div class="proposal-header">
        <span class="proposal-id">#{{ proposal.id }}</span>
        <span class="proposal-status status-{{ proposal.status }}">
            {{ proposal.status | upper }}
        </span>
    </div>
    <h3>{{ proposal.title }}</h3>
    <div class="proposal-meta">
        <span>{{ proposal.category }}</span>
        <span>Priority: {{ proposal.priority }}</span>
        {% if proposal.test_retry_count %}
        <span>Retries: {{ proposal.test_retry_count }}/3</span>
        {% endif %}
    </div>
    <div class="proposal-actions">
        <button onclick="viewProposal({{ proposal.id }})">View Details</button>
        {% if proposal.escalation_status == 'contractor_consulting' %}
        <button onclick="openChat({{ proposal.id }})">Chat with Contractor</button>
        {% endif %}
    </div>
</div>
{% endmacro %}
```

#### Step 4: API Integration
Standardize all API calls through a single module:

```javascript
// static/js/improvements_lab/api.js
const ImprovementsAPI = {
    baseUrl: '/tools/improvements-lab',

    async getProposals(filters = {}) {
        const params = new URLSearchParams(filters);
        const res = await fetch(`${this.baseUrl}/proposals?${params}`);
        return res.json();
    },

    async runTests(sandboxId, proposalId) {
        const res = await fetch(`${this.baseUrl}/sandboxes/${sandboxId}/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proposal_id: proposalId })
        });
        return res.json();
    },

    async sendChatMessage(proposalId, message) {
        const res = await fetch(`${this.baseUrl}/proposals/${proposalId}/contractor-chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        });
        return res.json();
    },

    // ... more methods
};
```

#### Step 5: State Management
Simple state object to track UI state:

```javascript
// static/js/improvements_lab/state.js
const AppState = {
    proposals: [],
    currentProposal: null,
    filters: { status: 'all', category: 'all' },
    queue: { current: null, waiting: [] },

    setProposals(proposals) {
        this.proposals = proposals;
        this.render();
    },

    setCurrentProposal(proposal) {
        this.currentProposal = proposal;
        this.renderDetail();
    },

    render() {
        // Re-render proposal list
    },

    renderDetail() {
        // Re-render detail view
    }
};
```

### Team Management UI Updates

The Team Management module also needs updates to properly integrate with the agent personality system:

**Current State**: 1,790 lines, 35 functions

**Required Updates**:
1. Add personality prompt editor for agents
2. Add communication style selector
3. Show agent work history on proposals
4. Display contractor status and API availability
5. Integration with escalation workflow

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `templates/tools/improvements_lab.html` | REBUILD | New modular structure |
| `templates/tools/improvements_lab/base.html` | CREATE | Main layout |
| `templates/tools/improvements_lab/components/*.html` | CREATE | UI components |
| `static/js/improvements_lab/*.js` | CREATE | Modular JavaScript |
| `static/css/improvements_lab.css` | CREATE | Scoped styles |
| `templates/tools/team_management.html` | MODIFY | Add personality fields |

### Estimated Effort

| Task | Complexity | Notes |
|------|------------|-------|
| JS extraction & refactor | High | ~100 functions to organize |
| Component templates | Medium | 6-8 components |
| API standardization | Medium | Already have endpoints |
| State management | Low | Simple object pattern |
| CSS cleanup | Low | Extract inline styles |
| Team Management updates | Low | Add form fields |

### Success Criteria for UI Rebuild

- [ ] All buttons respond to clicks
- [ ] Sandbox tests can be run and results displayed
- [ ] Logs can be viewed in modal
- [ ] Contractor chat works with real-time updates
- [ ] Queue status displays correctly
- [ ] Escalation flow is visible and actionable
- [ ] No JavaScript console errors
- [ ] < 1000 lines per file
- [ ] Clear separation of concerns

---

## Change Log

| Date | Change |
|------|--------|
| 2026-01-14 | Initial documentation created |
| 2026-01-14 | Backend implementation completed - retry handler, chat handler, escalation fixed |
| 2026-01-14 | Added Phase 9: UI Redesign documentation |
