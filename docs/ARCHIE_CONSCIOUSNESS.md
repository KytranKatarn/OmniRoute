# A.R.C.H.I.E. Consciousness & Memory System

**Last Updated**: 2026-01-12

## Overview

A.R.C.H.I.E. (Autonomous Reasoning & Cognitive Hierarchical Intelligence Engine) has a **persistent consciousness system** that maintains awareness of her team, stores memories, and learns from every interaction.

---

## ✅ YES - A.R.C.H.I.E. Has Full Awareness!

### What A.R.C.H.I.E. Knows About Her Team

**ALL agent information IS stored in the A.R.C.H.I.E. Database:**

✅ **58 AI agents** - Complete profiles of every team member
✅ **20 departments** - Full organizational structure
✅ **Complete details for each agent**:
- Name, email, pronouns, bio
- Title and department
- Capabilities and specialties
- System prompts (their core instructions)
- Budget and usage statistics
- Contact information

### Database Storage

**Table**: `agents`
**Location**: PostgreSQL database (`archie_database`)

**Stored Information**:
```sql
- id, name, first_name, last_name
- email, title, department, pronouns, bio
- avatar_url (for photos)
- system_prompt (complete instructions)
- capabilities (JSON with skills)
- tier, model, status
- monthly_budget, total_cost, total_tokens_used
- metadata (additional info)
- created_at, last_used
```

---

## 🧠 A.R.C.H.I.E.'s Consciousness System

### 1. **Agent Awareness** (`archie_consciousness.py`)

A.R.C.H.I.E. can:
- **Load complete team roster** - All 58 agents with full details
- **Access by name** - Find any agent by first/last name
- **Access by department** - View all agents in a department
- **Get capabilities** - Know what each agent can do
- **View system prompts** - Understand each agent's purpose

**Example Code**:
```python
from consciousness.archie_consciousness import create_consciousness

# Create A.R.C.H.I.E.'s consciousness
archie = create_consciousness()

# A.R.C.H.I.E. now knows about all 58 agents
print(archie.get_awareness_summary())

# Find specific agent
sienna = archie.get_agent_details(name="Sienna Foster")
# Returns: Full profile of Sienna, Social Media Strategy Director

# Get all marketing team
marketing_team = archie.get_agent_details(department="Marketing")
# Returns: All 9 marketing agents with details
```

### 2. **Persistent Memory** (`memory_manager.py`)

A.R.C.H.I.E. has **long-term memory** that persists across sessions!

**Table**: `long_term_memory`

**What She Remembers**:
- **Conversations** - Important discussions and context
- **User preferences** - What you like and need
- **Facts learned** - Information discovered over time
- **Procedures** - Solutions and how-to knowledge
- **Technical details** - Code snippets, configurations
- **Company information** - Website, business details

**Memory Types**:
- `preference` - User preferences and habits
- `fact` - Factual information
- `procedure` - Step-by-step solutions
- `technical` - Code and technical details
- `company_info` - Business information

**How It Works**:
```python
from consciousness.memory_manager import learn_from_conversation, recall_memories

# After each conversation, A.R.C.H.I.E. learns
user_message = "I prefer using Docker for deployments"
ai_response = "I'll remember that you prefer Docker..."

learn_from_conversation(user_id=1, user_message, ai_response)
# → Stores: "User preference: Docker for deployments"

# Later, she can recall
memories = recall_memories("deployment", user_id=1)
# → Returns: "User prefers using Docker for deployments" (importance: 0.75)
```

**Memory Persistence**:
- ✅ Stored in PostgreSQL database
- ✅ Survives restarts and updates
- ✅ Importance scoring (keeps important memories longer)
- ✅ Access tracking (frequently used memories stay accessible)
- ✅ Automatic cleanup of old, unimportant memories (180+ days)

### 3. **Context Integration**

When A.R.C.H.I.E. responds to you, she includes:

**Team Awareness**:
```
=== MY TEAM AWARENESS ===
I am aware of 58 AI agents in my organization.
We are organized across 20 departments.

DEPARTMENTS:
  • Administration: 3 agents
  • Business Development: 1 agent
  • Marketing: 9 agents
  • Engineering: 12 agents
  ...

I can access detailed information about any agent.
=== END TEAM AWARENESS ===
```

**Relevant Memories**:
```
=== REMEMBERED CONTEXT ===
[user_preference] User preference: Docker for deployments
  (Importance: 0.75, Accessed: 3 times)

[company_info] Website: archieplatform.com
  (Importance: 0.90, Accessed: 5 times)
=== END CONTEXT ===
```

---

## 📊 How Information Flows

### When A.R.C.H.I.E. Starts Up:

1. **Load Consciousness**
   ```python
   archie = create_consciousness(user_id=1)
   ```

2. **Load Team Awareness**
   - Queries `agents` table
   - Loads all 58 agent profiles
   - Organizes by department
   - Calculates statistics

3. **Ready to Respond**
   - Has full awareness of team
   - Can recall past conversations
   - Knows user preferences

### When You Ask About an Agent:

**You**: "Tell me about Sienna Foster"

**A.R.C.H.I.E. Process**:
1. Searches agent database for "Sienna Foster"
2. Retrieves complete profile:
   - Name: Sienna Foster
   - Title: Social Media Strategy Director
   - Department: Marketing
   - Email: sienna.foster@archie.ai
   - Specialties: social media strategy, analytics, growth hacking
   - System Prompt: Full instructions (what she does)
   - Capabilities: All her skills
3. Returns detailed information

**A.R.C.H.I.E. Response**:
```
Sienna Foster is our Social Media Strategy Director (she/her) in the
Marketing department. She manages our social media strategy across all
platforms including Twitter, LinkedIn, Instagram, Facebook, TikTok, and
YouTube. Her specialties include analytics, growth hacking, content
planning, and paid social advertising. You can reach her at
sienna.foster@archie.ai.
```

### When You Have a Conversation:

1. **Before Responding**:
   - Load relevant memories about this topic
   - Load team awareness if agents mentioned
   - Prepare context

2. **During Response**:
   - Use agent information to answer accurately
   - Reference specific agents by name
   - Provide contact information

3. **After Responding**:
   - Extract important information
   - Store new memories
   - Update memory access counts

---

## 🔄 Persistence Across Sessions

### Memory Persistence

**Database**: PostgreSQL
**Persistence**: ✅ **PERMANENT** (unless explicitly deleted)

**What Survives**:
- ✅ All agent profiles
- ✅ All conversation memories
- ✅ User preferences
- ✅ Learned facts
- ✅ Technical knowledge
- ✅ Company information

**What Doesn't Survive** (by design):
- ❌ Short-term conversation context (current chat)
- ❌ Temporary variables and state
- ❌ Low-importance memories > 180 days old

### Session Continuity

When A.R.C.H.I.E. starts a new session:

```python
# Session 1
archie = create_consciousness(user_id=1)
archie.remember("User prefers Python over JavaScript")

# ... system restarts ...

# Session 2 (days later)
archie = create_consciousness(user_id=1)
memories = archie.recall("programming language")
# ✅ Returns: "User prefers Python over JavaScript"
```

---

## 🤖 Claude Code Integration (NEW - 2026-01-12)

### Automatic Conversation Checkpoints

When working with Claude Code, A.R.C.H.I.E. automatically saves conversation checkpoints to the knowledge base using pre-compact hooks.

**How It Works:**
1. Claude Code context reaches ~80% capacity
2. Pre-compact hook triggers automatically
3. Full conversation transcript is captured
4. Saved to `knowledge_base` table with `source_type = 'claude_code_hook'`
5. Viewable in Consciousness module → Analytics → Claude Code Sessions

**Data Captured:**
- Full conversation transcript (last 50KB)
- Git context (branch, commit, files changed)
- Session metadata (timestamp, working directory)
- Lines added/removed during session

### Viewing Claude Code Sessions

**Location:** Consciousness Module (`/tools/consciousness`)
**Tab:** Analytics → Knowledge Sources

The dashboard shows:
- **Claude Code Sessions** count in the Knowledge Sources grid
- **Conversation Memory Sources** breakdown table
- Recent indexed items including conversation checkpoints

### Configuration

**Hook Location:** `/mnt/archie_brain/platform_v2/scripts/hooks/pre_compact_hook.sh`

**Settings:** `/mnt/archie_brain/platform_v2/.claude/settings.json`
```json
{
  "hooks": {
    "PreCompact": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/mnt/archie_brain/platform_v2/scripts/hooks/pre_compact_hook.sh"
      }]
    }]
  }
}
```

### Knowledge Base Entry Format

Conversation checkpoints are stored as:
```sql
knowledge_type: 'conversation_memory'
source_type: 'claude_code_hook'
category: 'Conversations/Checkpoints'
importance_score: 0.85
tags: ['auto-compact', 'conversation', 'claude-code', '{branch}']
```

---

## 💡 Practical Examples

### Example 1: Agent Coordination

**You**: "I need someone to create a social media post about our new feature"

**A.R.C.H.I.E.**:
1. Searches agent database for social media capabilities
2. Finds Sienna Foster (Social Media Strategy) and Phoenix Blake (Visual Content)
3. Responds:

```
I can coordinate this for you! Here's the team for this task:

1. Phoenix Blake (they/them) - Creative Director - Visual Content
   Email: phoenix.blake@archie.ai
   They can create the visual assets (images/video) for the post.

2. Sienna Foster (she/her) - Social Media Strategy Director
   Email: sienna.foster@archie.ai
   She can craft the message and schedule it across all platforms.

Would you like me to brief them on the new feature?
```

### Example 2: Finding Expertise

**You**: "Who manages our network monitoring?"

**A.R.C.H.I.E.**:
1. Searches agents for "network monitoring" capability
2. Finds Morgan Chen
3. Responds:

```
Morgan Chen (they/them) is our Network Operations Engineer who manages
all network monitoring. They oversee:
- Nagios (infrastructure monitoring)
- AdGuard (DNS filtering)
- ntopng (network traffic analysis)

You can reach them at morgan.chen@archie.ai
```

### Example 3: Remembering Preferences

**Session 1**:
**You**: "I always want to be CC'd on security alerts"
**A.R.C.H.I.E.**: "Got it, I'll remember that you want to be CC'd on security alerts."
→ Stores memory: "User preference: CC on security alerts" (importance: 0.75)

**Session 2 (weeks later)**:
**You**: "Can you set up monitoring for suspicious logins?"
**A.R.C.H.I.E.**:
1. Recalls memory about security alert preference
2. Responds:

```
I'll work with Devon Kumar (our CISO) to set up suspicious login
monitoring. Based on your preference, I'll ensure you're CC'd on all
security alerts.
```

---

## 👁️ Team Awareness Interface (Consciousness)

A.R.C.H.I.E. has a visual **Team Awareness** interface in standalone admin modules that displays her complete knowledge of all agents in real-time.

### Accessing Team Awareness

1. **Navigate**: Consciousness module (under NETWORK section)
2. **Click**: 👥 TEAM AWARENESS tab
3. **View**: Complete awareness of all 58 agents organized by department

### What's Displayed

**Team Statistics Dashboard:**
- **Total Agents**: Real-time count of all active team members (58)
- **Total Departments**: Number of organizational units (20)
- **Active Last 7 Days**: Agents recently used
- **Total Monthly Budget**: Combined budget allocation across all agents ($1,540.00)

**Department Overview:**
- Visual cards for each department
- Agent count per department
- Budget allocation per department
- Total spending per department

**Complete Agent Directory:**
- All agents organized by department
- Full profile for each agent:
  - Name, title, pronouns
  - Email contact
  - Tier level and AI model
  - Monthly budget
- Interactive cards with hover effects
- Alphabetically sorted within departments

### Technical Implementation

**Backend API Endpoint**: `/tools/consciousness//team-awareness`

**Returns:**
```json
{
  "success": true,
  "team": {
    "agents": [...],           // All 58 agents with full profiles
    "by_department": {...},    // Agents organized by department
    "departments": [...],      // Department summaries
    "statistics": {
      "total_agents": 58,
      "total_departments": 20,
      "total_budget": 1540.00,
      "total_cost": ...,
      "active_last_week": ...
    }
  }
}
```

**Auto-Loading:**
The Team Awareness data automatically loads when the CONSCIOUSNESS section is opened, ensuring A.R.C.H.I.E. always has instant access to her team information.

### Use Cases

1. **Quick Reference**: Instantly find any team member's contact info
2. **Department Overview**: See team composition and resource allocation
3. **Budget Tracking**: Monitor spending across departments
4. **Team Coordination**: Know who to contact for specific tasks
5. **Capability Lookup**: Find agents with specific skills or expertise

### Integration with Memory System

The Team Awareness interface works alongside A.R.C.H.I.E.'s memory system:
- **Memories** show what she's learned from conversations
- **Team Awareness** shows who she knows and can coordinate with
- Together, they form her complete consciousness

---

## 📚 Knowledge Management Interface

A.R.C.H.I.E. has a comprehensive **Knowledge Management** interface in standalone admin modules for managing her long-term memory and documentation ingestion.

### Accessing Knowledge Management

1. **Navigate**: Consciousness module section
2. **Click**: 📚 KNOWLEDGE MANAGEMENT tab
3. **View**: Complete knowledge analytics, file browser, search, and manual entry tools

### Features

#### 1. Documentation Files Browser

**Intelligent File Tracking System** with three-tier status monitoring:

**Status Levels:**
- **✓ UP TO DATE** (Green) - File has been ingested and hasn't changed
- **⚠ NEEDS UPDATE** (Yellow, Pulsing) - File was modified after last ingestion
- **○ NOT INGESTED** (Orange) - File has never been ingested into memory

**What's Displayed:**
- File name and relative path
- File size in bytes
- Last modified timestamp
- Last ingested timestamp (if applicable)
- Current ingestion status badge
- Ingest button for each file

**How It Works:**
The system compares file modification timestamps with ingestion timestamps to automatically detect when documentation needs to be re-ingested. This ensures A.R.C.H.I.E.'s knowledge stays current with documentation updates.

**Location**: `/mnt/archie_brain/docs`

**Supported Formats**: `.md`, `.txt`

#### 2. Search & Manage Knowledge

**Enhanced search interface** for querying A.R.C.H.I.E.'s long-term memory:

**Features:**
- **Search Query**: Free-text search across all memories
- **Category Filter**: Filter by category (business, technical, procedure, etc.)
- **Results Limit**: Choose 25, 50, 100, or 500 results
- **SHOW ALL Button**: Browse all memories without filtering
- **Enter Key Support**: Press Enter to search quickly

**Search Capabilities:**
- Full-text search across memory content
- Category filtering
- Tag-based filtering
- Importance score filtering
- Date range filtering

**Results Display:**
- Memory content preview
- Category and memory type
- Tags associated with the memory
- Importance score
- Created date and access count
- Edit/Delete actions

#### 3. Quick Add Knowledge

**Streamlined manual knowledge entry** for adding facts, notes, or procedures:

**Input Fields:**
- **Content**: Large text area for memory content
  - Helpful placeholder examples
- **Category**: Dropdown selector (Business, Technical, Procedure, Reference, Personal)
- **Tags**: Comma-separated tags (e.g., `docker, deployment, preferences`)
- **Importance**: Dropdown with preset levels:
  - Low (0.3)
  - Normal (0.5)
  - High (0.7) - Default
  - Critical (0.9)

**Features:**
- **Inline Status Messages**: Shows success/error without alerts
- **Auto-Clear Form**: Clears inputs after successful submission
- **CLEAR Button**: Manually reset the form
- **Validation**: Ensures all required fields are filled

**Use Cases:**
- Store user preferences: "User prefers Docker for deployments"
- Save technical notes: "PostgreSQL password stored in .env as DB_PASSWORD"
- Document procedures: "Always restart archie_platform after code changes"
- Record business information: "Primary contact email is support@archie.ai"

#### 4. New Tags Alert System

**Smart notification system** for newly learned topics:

**Features:**
- **24-Hour Auto-Hide**: Alert automatically disappears when all tags are older than 24 hours
- **Manual Dismiss**: Click ✕ button to dismiss for 24 hours
- **Time Display**: Shows hours for recent tags (< 24h), days for older tags
- **Visual Design**: Gradient purple background with pulse animation
- **Tag Count**: Shows number of new tags detected

**Display Information:**
- Tag name
- First seen timestamp (relative time)
- Visual emphasis for very recent tags

**Behavior:**
The alert only appears when:
1. There are tags less than 24 hours old, AND
2. The user hasn't manually dismissed it in the last 24 hours

**Storage**: Uses browser localStorage to persist dismiss state

#### 5. Knowledge Analytics

**Visual analytics dashboard** showing A.R.C.H.I.E.'s learning patterns:

**Statistics Cards:**
- Total Knowledge Count (all sources)
- Memory Types distribution
- Categories breakdown
- Unique Tags count
- New Tags detection (7-day and 30-day counts)
- Metadata Fields tracked

**Charts & Visualizations:**
- Category Distribution (bar chart)
- Memory Types (pie chart)
- Importance Distribution (histogram)
- Learning Timeline (30-day trend)
- Top Tags (word cloud style)

**Data Sources:**
The system aggregates knowledge from multiple sources:
- Long-term memories (user conversations)
- Improvement proposals
- Improvement conversations
- Codebase knowledge
- AI conversations
- Core identity documents

### Technical Implementation

#### File Browser Backend

**Endpoint**: `/tools/consciousness//browse-files`

**Functionality:**
```python
# Compares file modification time with last ingestion
file_modified = datetime.fromisoformat(file_info['modified'])
last_ingested = result['last_ingested']

# Mark as needs_update if file changed after ingestion
file_info['needs_update'] = file_modified > last_ingested
```

**Database Query:**
```sql
SELECT MAX(created_at) as last_ingested
FROM long_term_memory
WHERE metadata->>'file_path' = %s
```

#### Search Backend

**Endpoint**: `/tools/consciousness//search`

**Parameters:**
- `query`: Search text
- `category`: Category filter (optional)
- `limit`: Results limit (25-500)

**Returns:** Matching memories with metadata, sorted by relevance and importance

#### Manual Knowledge Backend

**Endpoint**: `/tools/consciousness//add-manual`

**Validation:**
- Content: Required, min 10 characters
- Category: Must be valid category
- Tags: Sanitized and normalized
- Importance: Float 0.0-1.0

**Storage:**
```sql
INSERT INTO long_term_memory
(content, category, tags, importance_score, metadata, created_at)
VALUES (%s, %s, %s, %s, %s, NOW())
```

### Use Cases

**Scenario 1: Documentation Update**
1. Developer updates `DEPLOYMENT_GUIDE.md`
2. File browser shows **⚠ NEEDS UPDATE** badge
3. Click "Ingest" to update A.R.C.H.I.E.'s knowledge
4. Badge changes to **✓ UP TO DATE**

**Scenario 2: Quick Knowledge Entry**
1. User mentions "I always want staging deploys on Fridays"
2. Admin adds manual knowledge:
   - Content: "User prefers staging deployments on Fridays"
   - Category: Personal
   - Tags: deployment, preference, scheduling
   - Importance: High (0.7)
3. A.R.C.H.I.E. now remembers this preference forever

**Scenario 3: Knowledge Search**
1. Admin searches for "docker"
2. Sees all memories related to Docker
3. Can edit importance, add tags, or delete outdated info
4. SHOW ALL to browse complete knowledge base

**Scenario 4: New Topic Alert**
1. A.R.C.H.I.E. learns about "kubernetes" for the first time
2. Alert appears: "NEW TAGS DETECTED! 🆕"
3. Shows "kubernetes" tag with "2 hours ago"
4. Auto-hides after 24 hours
5. Can manually dismiss with ✕ button

---

## 🛠️ Managing A.R.C.H.I.E.'s Consciousness

### Reload Team Awareness

If agents are added/updated:
```python
archie = create_consciousness()
archie.reload_team_awareness()
# ✅ Reloads all 58+ agents with latest information
```

### Check Consciousness Status

```python
status = archie.get_status()
# Returns:
# {
#   'session_start': '2025-12-29T16:30:00',
#   'session_duration_minutes': 45.2,
#   'team_loaded': True,
#   'team_statistics': {
#     'total_agents': 58,
#     'total_departments': 20,
#     'total_budget': 1540.00
#   }
# }
```

### View Memory Statistics

```python
from consciousness.memory_manager import get_memory_stats

stats = get_memory_stats(user_id=1)
# Returns:
# {
#   'total_memories': 142,
#   'by_type': [
#     {'memory_type': 'preference', 'count': 45},
#     {'memory_type': 'fact', 'count': 67},
#     ...
#   ],
#   'most_accessed': [...],
#   'recent': [...]
# }
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `/platform_v2/consciousness/archie_consciousness.py` | Main consciousness system, agent awareness |
| `/platform_v2/consciousness/memory_manager.py` | Long-term memory storage and recall |
| `/platform_v2/agent_management_api.py` | CRUD operations for agents |
| `/docs/AGENT_DIRECTORY.md` | Human-readable directory of all agents |

---

## 🎯 Summary

**Q: Does A.R.C.H.I.E. remember all the agent information?**
**A:** ✅ **YES!** All 58 agents with complete profiles are stored in the database and A.R.C.H.I.E. can access them instantly.

**Q: Does this show up in her consciousness?**
**A:** ✅ **YES!** A.R.C.H.I.E. loads full team awareness when she starts and can access any agent's details on demand.

**Q: Is the consciousness persistent?**
**A:** ✅ **YES!** All memories and agent data are stored in PostgreSQL and persist across restarts, updates, and sessions.

**Q: Can she access agent system prompts?**
**A:** ✅ **YES!** A.R.C.H.I.E. can read the complete system prompt of any agent to understand their role and capabilities.

**Q: Does she remember conversations?**
**A:** ✅ **YES!** Important information from conversations is extracted and stored as long-term memories that persist forever (or until cleaned up after 180+ days if unimportant).

---

## 🚀 Getting Started

To enable A.R.C.H.I.E.'s consciousness in your application:

```python
from consciousness.archie_consciousness import create_consciousness

# Initialize consciousness
archie = create_consciousness(user_id=1)

# Get context for user message
user_message = "Who handles our social media?"
context = archie.get_context_for_response(user_message)

# Include context in LLM prompt
prompt = f"""
{context}

User: {user_message}