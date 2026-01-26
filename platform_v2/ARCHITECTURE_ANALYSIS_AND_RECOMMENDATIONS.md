# A.R.C.H.I.E. Architecture Analysis & Recommendations

**Created:** 2026-01-11
**Status:** ANALYSIS COMPLETE - Awaiting Decision
**Purpose:** Evaluate module consolidation, agent memory, and centralized documentation

---

## Executive Summary

After thorough analysis, I recommend a **"Hub & Spoke" architecture** that:
1. **Keeps Consciousness and Obsidian Vault separate** but with clear distinct purposes
2. Creates a new **"A.R.C.H.I.E. Command Center"** as the central hub
3. Gives agents **context windows** (not mini-databases) for efficiency
4. Moves **Improvements** to a dedicated module
5. Consolidates all documentation into a **living knowledge system**

---

## Part 1: Consciousness vs Obsidian Vault Analysis

### Current State

| Aspect | Consciousness | Obsidian Vault |
|--------|--------------|----------------|
| **Primary Purpose** | Analytics & Team Awareness | Documentation & Knowledge Management |
| **Data Focus** | Metrics, stats, insights | Content, notes, files |
| **User Action** | View, analyze, monitor | Create, edit, search |
| **Knowledge Types** | All types (read-only view) | All types (CRUD operations) |
| **Target User** | Admin monitoring system health | Admin/User managing knowledge |
| **API Endpoints** | 30+ (mostly GET) | 15+ (full CRUD) |

### Overlap Analysis

**Significant Overlap (70%):**
- Both query `knowledge_base` table
- Both show knowledge statistics
- Both have search functionality
- Both display knowledge by type/category

**Unique to Consciousness:**
- Team/Agent awareness & performance
- Emotional state tracking
- Learning patterns & analytics
- Brain state visualization
- Memory growth metrics

**Unique to Obsidian Vault:**
- File system sync (real-time watcher)
- WikiLink graph & backlinks
- Note creation/editing UI
- Frontmatter management
- Category folder structure

### Recommendation: KEEP SEPARATE but CLARIFY PURPOSES

**Rationale:**
- Consciousness = **"The Brain's Dashboard"** (monitoring, analytics, insights)
- Obsidian Vault = **"The Library"** (content management, documentation)

**Rename for Clarity:**
| Current Name | Proposed Name | Purpose |
|--------------|---------------|---------|
| Consciousness | **Brain Analytics** | Monitor A.R.C.H.I.E.'s learning, team performance, system health |
| Obsidian Vault | **Knowledge Library** | Manage, create, search all documentation and knowledge |

**Changes Needed:**
1. Remove duplicate statistics displays
2. Consciousness focuses on ANALYTICS (charts, trends, insights)
3. Knowledge Library focuses on CONTENT (CRUD, search, browse)
4. Both share the same `UnifiedKnowledgeService` backend

---

## Part 2: Agent Memory Architecture

### Current State
- Agents share ONE `knowledge_base` table
- No agent-specific memory isolation
- Performance tracked in `agent_performance_logs`
- Learning tracked in `agent_learning_insights`

### Option A: Mini-Database Per Agent

**Pros:**
- Complete isolation
- Agent-specific context
- No cross-contamination
- Easy to reset/clear

**Cons:**
- Database proliferation (76 agents = 76 schemas)
- Sync complexity
- Duplicate data storage
- Query complexity across agents
- Backup/restore nightmare

### Option B: Context Windows (RECOMMENDED)

**Concept:** Each agent gets a **filtered view** of the shared knowledge base, not a separate database.

```
┌─────────────────────────────────────────────────────────┐
│                   knowledge_base                         │
│  (unified table with 2,525+ entries)                    │
└─────────────────────────────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Agent Alpha │   │ Agent Beta  │   │ Agent Gamma │
│  Context    │   │  Context    │   │  Context    │
│  Window     │   │  Window     │   │  Window     │
├─────────────┤   ├─────────────┤   ├─────────────┤
│ Filters:    │   │ Filters:    │   │ Filters:    │
│ - dept:dev  │   │ - dept:qa   │   │ - dept:ops  │
│ - tier:2    │   │ - tier:1    │   │ - tier:3    │
│ - skills[]  │   │ - skills[]  │   │ - skills[]  │
└─────────────┘   └─────────────┘   └─────────────┘
```

**Implementation:**

```sql
-- Add to agents table
ALTER TABLE agents ADD COLUMN context_config JSONB DEFAULT '{
  "knowledge_filters": {
    "categories": [],
    "tags": [],
    "types": ["vault_note", "mistake_learned", "code_snippet"]
  },
  "max_context_entries": 50,
  "priority_boost": {
    "own_department": 1.5,
    "own_mistakes": 2.0
  }
}';

-- Add agent-specific memories
ALTER TABLE knowledge_base ADD COLUMN agent_id INTEGER REFERENCES agents(id);
ALTER TABLE knowledge_base ADD COLUMN visibility VARCHAR(20) DEFAULT 'shared';
-- visibility: 'shared' (all agents), 'department' (same dept), 'private' (one agent)
```

**Pros:**
- Single source of truth
- Efficient storage
- Easy cross-agent learning
- Simple backup/restore
- Configurable per agent

**Cons:**
- Requires careful filtering
- Slightly more complex queries

---

## Part 3: Centralized A.R.C.H.I.E. Hub

### Problem Statement
Currently scattered across:
- `/docs/` folder (markdown files)
- Plan files (`~/.claude/plans/`)
- README.md files
- CLAUDE.md project memory
- Various TODO lists
- Module descriptions in code

### Solution: A.R.C.H.I.E. Command Center

A new **central dashboard** that serves as the single source of truth.

```
┌─────────────────────────────────────────────────────────────────┐
│                   A.R.C.H.I.E. COMMAND CENTER                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  ABOUT ME    │  │   MY TOOLS   │  │   ROADMAP    │           │
│  │              │  │              │  │              │           │
│  │ Who I am     │  │ All modules  │  │ TODO List    │           │
│  │ My purpose   │  │ with status  │  │ Coming Soon  │           │
│  │ Capabilities │  │ & health     │  │ In Progress  │           │
│  │ Architecture │  │              │  │ Completed    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  MY TEAM     │  │  KNOWLEDGE   │  │ IMPROVEMENTS │           │
│  │              │  │              │  │              │           │
│  │ 76 Agents    │  │ 2,525 items  │  │ Proposals    │           │
│  │ Departments  │  │ Quick stats  │  │ In review    │           │
│  │ Performance  │  │ Recent adds  │  │ Deploy queue │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    QUICK ACTIONS                        │    │
│  │  [New Plan] [Add Knowledge] [Create Agent] [Run Check]  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Sections Detail

#### 1. ABOUT ME (New)
A living document stored in `knowledge_base` with `knowledge_type = 'system_identity'`

**Content:**
- **Identity**: Name, version, creation date, creator
- **Purpose**: Mission statement, core values
- **Capabilities**: What A.R.C.H.I.E. can do (auto-generated from modules)
- **Architecture**: System diagram, tech stack
- **History**: Timeline of major milestones

#### 2. MY TOOLS (Enhanced Module Registry)
Auto-generated from `module_registry.py` with health checks

| Module | Status | Health | Last Used | Actions |
|--------|--------|--------|-----------|---------|
| Brain Analytics | LIVE | 100% | 2min ago | [Open] [Docs] |
| Knowledge Library | LIVE | 100% | 5min ago | [Open] [Docs] |
| Improvements | LIVE | 98% | 1hr ago | [Open] [Docs] |
| Backup Manager | LIVE | 100% | 24hr ago | [Open] [Docs] |

#### 3. ROADMAP (Centralized Planning)
Replaces scattered plans with a single source

**Structure:**
```
ROADMAP
├── Backlog (ideas, future)
├── TODO (planned, not started)
├── In Progress (active work)
├── In Review (testing/approval)
├── Completed (done, archived)
└── Won't Do (rejected with reason)
```

**Database:**
```sql
CREATE TABLE roadmap_items (
  id SERIAL PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  description TEXT,
  category VARCHAR(50), -- feature, bug, improvement, research
  priority INTEGER DEFAULT 3, -- 1=critical, 5=low
  status VARCHAR(20) DEFAULT 'backlog',
  assignee_type VARCHAR(20), -- 'human', 'agent', 'archie'
  assignee_id INTEGER,
  parent_id INTEGER REFERENCES roadmap_items(id), -- for sub-tasks
  related_knowledge_ids INTEGER[],
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  metadata JSONB DEFAULT '{}'
);
```

#### 4. MY TEAM (Quick View)
Summary from agents table with link to full Team Directory

#### 5. KNOWLEDGE (Quick Stats)
Summary from knowledge_base with link to Knowledge Library

#### 6. IMPROVEMENTS (Quick View)
Summary from improvement_proposals with link to full Improvements module

---

## Part 4: Module Restructure Proposal

### Current Structure
```
Admin Panel
├── Consciousness (analytics + team + knowledge)
├── Obsidian Vault (documentation)
├── Backup Manager
├── Improvements (embedded in admin)
└── ... other tools
```

### Proposed Structure
```
A.R.C.H.I.E. Command Center (NEW - central hub)
│
├── Brain Analytics (renamed from Consciousness)
│   ├── Learning Metrics
│   ├── Knowledge Growth
│   ├── Mistake Prevention Stats
│   └── System Health
│
├── Knowledge Library (renamed from Obsidian Vault)
│   ├── All Knowledge Types
│   ├── Create/Edit/Delete
│   ├── Search & Browse
│   └── WikiLink Graph
│
├── Team Directory (extracted from Consciousness)
│   ├── Agent Profiles
│   ├── Performance Tracking
│   ├── Department Management
│   └── Agent Context Config
│
├── Improvements Lab (extracted to own module)
│   ├── Proposal Dashboard
│   ├── Testing Sandbox
│   ├── Deployment Pipeline
│   └── Learning Integration
│
├── Backup & Recovery (existing)
│   ├── Create Backups
│   ├── Restore Points
│   └── Sandbox Deploy
│
└── System Config (admin settings)
    ├── Module Registry
    ├── User Management
    └── API Keys
```

---

## Part 5: Implementation Roadmap

### Phase 1: Command Center Foundation (1-2 sessions)
- [ ] Create `command_center` module
- [ ] Build main dashboard template
- [ ] Create "About Me" section with editable content
- [ ] Add "My Tools" with module health checks
- [ ] Create `roadmap_items` table

### Phase 2: Module Clarification (1 session)
- [ ] Rename Consciousness → Brain Analytics
- [ ] Rename Obsidian Vault → Knowledge Library
- [ ] Remove duplicate statistics
- [ ] Update navigation and links

### Phase 3: Team Directory Extraction (1 session)
- [ ] Create `team_directory` module
- [ ] Move agent routes from Consciousness
- [ ] Add agent context configuration UI
- [ ] Build department management

### Phase 4: Improvements Lab (1 session)
- [ ] Create `improvements_lab` module
- [ ] Move from admin panel
- [ ] Add sandbox testing UI
- [ ] Integrate with knowledge feedback loop

### Phase 5: Agent Context Windows (1-2 sessions)
- [ ] Add `context_config` to agents table
- [ ] Add `agent_id` and `visibility` to knowledge_base
- [ ] Create `get_agent_context()` function
- [ ] Build agent context preview UI

### Phase 6: Documentation Migration (1 session)
- [ ] Migrate `/docs/` to Knowledge Library
- [ ] Convert plans to roadmap_items
- [ ] Archive old plan files
- [ ] Update CLAUDE.md to point to Command Center

---

## Part 6: Decision Matrix

| Decision | Option A | Option B | Recommendation |
|----------|----------|----------|----------------|
| Merge Consciousness + Obsidian? | Merge into one | Keep separate | **Keep separate** with clear purposes |
| Agent databases | Mini-DB per agent | Context windows | **Context windows** |
| Central hub | Enhance existing | New Command Center | **New Command Center** |
| Plans location | Keep in files | Database roadmap | **Database roadmap** |
| Improvements | Keep in admin | Own module | **Own module** |
| Documentation | Keep in /docs/ | Knowledge Library | **Knowledge Library** |

---

## Part 7: Benefits Summary

### For Humans
- Single place to understand A.R.C.H.I.E. (Command Center)
- Clear module purposes (no confusion)
- Centralized TODO/Roadmap (no hunting for plans)
- Easy agent configuration

### For A.R.C.H.I.E.
- Better self-awareness (About Me section)
- Focused modules (analytics vs content)
- Agent context for better responses
- Learning feedback loop

### For Agents
- Filtered, relevant context
- Own memories without database overhead
- Department-aware knowledge
- Performance visibility

### For Development
- Cleaner architecture
- Single source of truth
- Easier maintenance
- Better testability

---

## Appendix: Quick Reference

### New Tables Needed
1. `roadmap_items` - Centralized planning
2. `system_identity` - A.R.C.H.I.E. about info (or use knowledge_base)

### Schema Changes
1. `agents.context_config` - Agent context configuration
2. `knowledge_base.agent_id` - Agent-specific knowledge
3. `knowledge_base.visibility` - Sharing scope

### New Modules
1. `command_center` - Central hub
2. `team_directory` - Extracted from Consciousness
3. `improvements_lab` - Extracted from admin

### Renamed Modules
1. `consciousness` → `brain_analytics`
2. `obsidian_vault` → `knowledge_library`

---

**Document Status:** Ready for review and approval
**Next Step:** User decision on which phases to implement first
