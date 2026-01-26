# A.R.C.H.I.E. Admin Panel - Section Guide

## Overview

This document clarifies the purpose of each admin section and how they interconnect.

---

## Agent-Related Sections

### 1. AGENTS (🤖 AGENT MANAGEMENT)
**Location:** Admin Panel → A.R.C.H.I.E. → AGENTS

**Purpose:** Operational agent management and task execution

**Features:**
- Execute agent tasks
- Filter by tier level (⭐ to ⭐⭐⭐⭐)
- View agent capabilities
- Assign tasks to specific agents

**When to Use:**
- Need to execute a task with a specific agent
- Want to see agents by skill tier
- Need to manage agent workload

**Data Source:** `/tools/team-management/`

---

### 2. DIRECTORY (👥 AGENT DIRECTORY)
**Location:** Admin Panel → BUSINESS → DIRECTORY

**Purpose:** Comprehensive organizational directory and reference

**Features:**
- Complete agent directory (58 agents)
- Statistics dashboard (budget, cost, departments)
- Filter by department (20 departments)
- Export agent list
- Visual agent cards with profile pictures

**When to Use:**
- Need to find an agent by department
- Want to see organizational structure
- Need budget/cost information
- Looking up agent contact info

**Data Source:** `/tools/team-management/`

**Documentation:** `/docs/AGENT_DIRECTORY.md`

---

## Configuration Sections

### 3. CONFIGURATION (⚙️ CONFIGURATION)
**Location:** Admin Panel → SYSTEM → CONFIGURATION

**Purpose:** System-wide settings and API configuration

**Key Subsections:**

#### A. AI PROVIDER CONFIGURATION
**Purpose:** Configure AI model providers (Claude, OpenAI, Gemini, Grok)

**Features:**
- Add/edit API keys for each provider
- Set default provider
- Test connections
- View which agents use which providers

**Connection to Agents:**
- Each agent is assigned an AI model (claude-sonnet-4, opus-4-5, etc.)
- API keys configured here enable agents to function
- Missing API keys cause agents to fallback to local models

**Example Flow:**
1. Add Claude API key in Configuration
2. Test connection ✅
3. Agents using Claude models now have access
4. View which agents use Claude in Directory

#### B. CONTRACT AGENTS & REQUIRED APIs
**Purpose:** Show which agents require external API keys

**Features:**
- List of "contract" agents (require paid APIs)
- Shows which API each agent needs
- Fallback information (uses free internal models if API missing)

**Connection to Directory:**
- Click agent name → Opens agent detail in Directory
- See full agent profile and capabilities

#### C. GITHUB INTEGRATION
**Purpose:** Configure GitHub for repository operations

**Features:**
- GitHub token management
- Test GitHub connection
- Configure default username/email
- Auto-deploy and auto-commit settings

**Connection to Other Sections:**
- GitHub notifications appear in Notifications Center
- Clone/index operations tracked in Directory

---

## How Everything Connects

```
┌─────────────────────────────────────────────────────────┐
│           CONFIGURATION (System Settings)               │
│                                                         │
│  ┌────────────────────────────────────────────────┐   │
│  │    AI PROVIDER CONFIGURATION                   │   │
│  │  - Claude API Key                              │   │
│  │  - OpenAI API Key                              │   │
│  │  - Gemini API Key                              │   │
│  │  - Grok API Key                                │   │
│  └────────────────┬───────────────────────────────┘   │
│                   │                                     │
└───────────────────┼─────────────────────────────────────┘
                    │ Enables API Access
                    ▼
┌─────────────────────────────────────────────────────────┐
│              AGENTS (Task Execution)                    │
│  - Execute tasks                                        │
│  - Filter by tier                                       │
│  - Assign work                                          │
│  - Uses APIs configured above                           │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ Same agent data, different view
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│           DIRECTORY (Organization Reference)            │
│  - View all 58 agents                                   │
│  - Filter by department                                 │
│  - See budget/costs                                     │
│  - Export data                                          │
│  - Shows which API each agent uses                      │
└─────────────────────────────────────────────────────────┘
                 │
                 │ All actions create notifications
                 ▼
┌─────────────────────────────────────────────────────────┐
│       NOTIFICATIONS (Centralized Alerts)                │
│  - Agent task results                                   │
│  - API connection status                                │
│  - Configuration changes                                │
│  - All admin operations                                 │
└─────────────────────────────────────────────────────────┘
```

---

## AI Provider Configuration → Agents Connection

### How It Works

1. **Add API Key in Configuration:**
   ```
   Configuration → AI Provider Configuration → Add Claude API Key
   ```

2. **Test Connection:**
   ```
   Click "Test" → Success notification
   ```

3. **Agents Use API:**
   ```
   Agents section → Select agent → Execute task → Uses configured API
   ```

4. **View in Directory:**
   ```
   Directory → Agent card → Shows "AI Model: claude-sonnet-4"
   ```

### Agent-to-API Mapping

| Agent Type | Required API | Fallback |
|------------|--------------|----------|
| Contract Agents | External API (Claude, OpenAI) | Internal staff (free) |
| Staff Agents | Local models | N/A |

**View Mapping:** Configuration → Contract Agents & Required APIs section

---

## Common Workflows

### Workflow 1: Configure New AI Provider
1. Go to **Configuration**
2. Scroll to **AI PROVIDER CONFIGURATION**
3. Enter API key for provider (e.g., Claude)
4. Click **Test** button
5. Success notification appears
6. Click **Save All Settings**
7. Agents using that provider now have access

### Workflow 2: Find Agent by Department
1. Go to **Directory**
2. Click department filter button (e.g., "Engineering")
3. View all agents in that department
4. Click agent card for full details
5. See which API/model they use

### Workflow 3: Execute Agent Task
1. Go to **Agents**
2. Filter by tier if needed
3. Click agent card
4. Click "Execute Task"
5. Enter task description
6. Results appear in Notifications

### Workflow 4: Check API Usage
1. Go to **Directory**
2. View stats dashboard (shows total budget/cost)
3. Click individual agent
4. See "Monthly Budget" and "Total Cost"
5. View which AI model they're using

---

## Frequently Asked Questions

### Q: Why are there two agent sections?
**A:** They serve different purposes:
- **AGENTS** = Operational (execute tasks, manage workload)
- **DIRECTORY** = Reference (find agents, view organization)

### Q: Where do I configure AI provider API keys?
**A:** Configuration → AI PROVIDER CONFIGURATION section

### Q: How do I know which agents need which APIs?
**A:** Configuration → CONTRACT AGENTS & REQUIRED APIs section

### Q: Where can I see all agents with their departments?
**A:** Directory section (has department filtering)

### Q: How do I execute a task with a specific agent?
**A:** Agents section → Click agent → Execute Task

### Q: Where do notifications appear?
**A:** Click 🔔 NOTIFICATIONS in sidebar header

### Q: Can I export the agent list?
**A:** Yes, in Directory section → Export button

---

## Best Practices

1. **Configure APIs First:** Always set up AI provider APIs in Configuration before using agents
2. **Test Connections:** Use the "Test" button to verify APIs work
3. **Check Directory for Reference:** Use Directory for organizational information
4. **Use Agents for Tasks:** Use Agents section when you need to execute work
5. **Monitor Notifications:** All actions create notifications - review them regularly
6. **Review Budget:** Check Directory stats dashboard for cost management

---

## Related Documentation

- **Notification System:** `/docs/notification-system.md`
- **Agent Directory:** `/docs/AGENT_DIRECTORY.md`
- **Agent Delegation:** `/docs/AGENT_DELEGATION_SYSTEM.md`
- **Business Agents:** `/docs/BUSINESS_AGENTS_GUIDE.md`

---

**Last Updated:** December 31, 2025
**Version:** 1.0
