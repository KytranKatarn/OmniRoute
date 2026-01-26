# A.R.C.H.I.E. BRIDGE Module Plan

**Created:** 2026-01-16
**Status:** Planning
**Priority:** High - Core Infrastructure

---

## Vision Statement

The **A.R.C.H.I.E. BRIDGE** is the central command center for all AI/LLM operations, inspired by a starship bridge concept. It provides:
- Visual monitoring of all LLM connections (local + remote)
- Station-based workflow with agents assigned to roles
- Real-time traffic monitoring and health checks
- Integration with Team Management for agent assignment
- Future: VPN remote nodes, Mining Pool integration

**Command Structure:**
- **Captain:** Kytran (Admin/Owner)
- **First Officer:** A.R.C.H.I.E. (AI Co-founder, access to Consciousness)

---

## Current Infrastructure

### Existing Database Schema (Already Implemented)

| Table | Purpose | Status |
|-------|---------|--------|
| `archie_core_identity` | A.R.C.H.I.E.'s identity (name, role, personality_profile) | ✅ Active |
| `archie_emotional_state` | Mood tracking, relationship strength | ✅ Active |
| `archie_personality` | Personality traits configuration | ✅ Active |
| `emotional_memory` | Emotional event history | ✅ Active |
| `voice_phoneme_library` | Voice DNA phonemes with emotion context | ✅ Active |
| `voice_word_cache` | Synthesized word audio cache | ✅ Active |
| `agents` | Team members with LLM assignments | ✅ Active |
| `agent_skills` | 959 skills across 75 agents | ✅ Active |
| `token_usage_log` | LLM usage tracking | ✅ Active |

### Current LLM Connections

| Provider | Host | Models | Type |
|----------|------|--------|------|
| Ollama (Local) | 192.168.1.246:11434 | qwen2.5-coder:7b, deepseek-coder-v2:16b, llama3.1:8b | Internal (FREE) |
| Claude API | api.anthropic.com | claude-sonnet-4, claude-opus-4 | Contractor (PAID) |
| OpenAI API | api.openai.com | gpt-4, gpt-4o | Contractor (PAID) |
| Grok API | api.x.ai | grok-beta | Contractor (PAID) |
| Gemini API | generativelanguage.googleapis.com | gemini-2.0-flash | Contractor (PAID) |

### Existing Modules by Category

| Category | Modules | LLM Needs |
|----------|---------|-----------|
| **CREATION** | Project Builder, Game Studio, Media Studio, Content Studio | Code generation, creative writing |
| **DEVELOPMENT** | Code Editor, CodeRabbit, Sandbox Manager | Code analysis, reviews, debugging |
| **BUSINESS_TOOLS** | CRM, Invoicing, Email, Scheduler, Store, Call Center | Data processing, communication |
| **STANDALONE_APPS** | DOC, Therapy, Fitness, StockBot, Archie Pool | Specialized AI tasks |
| **ADMIN** | Improvements Lab, Consciousness, Team Management, Blueprint, Backup | System management |

---

## Bridge Architecture

### Proposed Station Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        A.R.C.H.I.E. BRIDGE COMMAND                          │
│                     ═══════════════════════════════════                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│    ┌───────────────────────────────────────────────────────────────────┐   │
│    │                      MAIN VIEWSCREEN                               │   │
│    │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│    │   │ LLM Status  │  │ Active Req  │  │ System Load │              │   │
│    │   │ 5/6 Online  │  │    147      │  │    34%      │              │   │
│    │   └─────────────┘  └─────────────┘  └─────────────┘              │   │
│    │                                                                    │   │
│    │   Real-time Traffic Flow / Connection Map                         │   │
│    └───────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│    ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│    │  HELM   │ │  OPS    │ │ SCIENCE │ │ COMMS   │ │ ENGINE  │           │
│    │ Router  │ │Business │ │  Dev    │ │  Chat   │ │Creation │           │
│    │ ┌─────┐ │ │ ┌─────┐ │ │ ┌─────┐ │ │ ┌─────┐ │ │ ┌─────┐ │           │
│    │ │Agent│ │ │ │Agent│ │ │ │Agent│ │ │ │ARCHIE│ │ │ │Agent│ │           │
│    │ └─────┘ │ │ └─────┘ │ │ └─────┘ │ │ └─────┘ │ │ └─────┘ │           │
│    │deepseek│ │ │ qwen  │ │ │claude │ │ │ Core  │ │ │ gpt-4 │           │
│    │ ░░░░░░ │ │ │ ░░░░░ │ │ │ ░░░░░ │ │ │ ░░░░░ │ │ │ ░░░░░ │           │
│    │ 23 req │ │ │ 45 req│ │ │ 12 req│ │ │ 67 req│ │ │ 8 req │           │
│    └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘           │
│                                                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐ │
│    │ CAPTAIN: Kytran (Admin)  │  FIRST OFFICER: A.R.C.H.I.E. (AI)       │ │
│    │ Status: On Duty          │  Status: Active | Mood: Supportive       │ │
│    └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Station Definitions

| Station | Purpose | Default LLM | Covers Modules |
|---------|---------|-------------|----------------|
| **HELM** | Request routing, load balancing | deepseek-coder-v2:16b | Core routing decisions |
| **OPS** (Operations) | Business processes | qwen2.5-coder:7b | CRM, Invoicing, Email, Scheduler |
| **SCIENCE** | Code analysis, development | claude-sonnet-4 | CodeRabbit, Improvements Lab, Sandbox |
| **COMMS** (Communications) | User interaction, chat | A.R.C.H.I.E. (personality) | A.R.C.H.I.E. Chat, Social Media, Call Center |
| **ENGINE** (Engineering) | Content creation | gpt-4 / gemini | Project Builder, Website Designer, Media Studio |

### A.R.C.H.I.E.'s Role

- **Always answers at COMMS station** - Her voice, her personality
- **Routes internally** based on request type
- **Access to Consciousness** - Full memory and emotional context
- **Personality Profile:** supportive (0.95), caring (0.90), professional (0.85), innovative (0.85)
- **Voice DNA:** Smart, soft, supportive (phoneme library ready)

---

## Implementation Phases

### Phase A: Bridge UI (Visual Dashboard)
**Complexity:** Medium | **Priority:** HIGH

**Tasks:**
- [ ] Create `/tools/bridge/` route and blueprint
- [ ] Design Bridge template with station layout
- [ ] Real-time stats cards (LLM status, active requests, system load)
- [ ] Station cards with agent avatars and activity indicators
- [ ] Captain/First Officer status bar
- [ ] Dark cyberpunk theme matching platform style
- [ ] Click station → navigate to related modules

**Files to Create:**
- `platform_v2/tools/bridge/__init__.py`
- `platform_v2/tools/bridge/routes.py`
- `platform_v2/templates/tools/bridge.html`

### Phase B: LLM Connection Monitor
**Complexity:** Medium | **Priority:** HIGH

**Tasks:**
- [ ] Create `llm_connections` database table
- [ ] Health check background service (30s interval)
- [ ] Connection status API endpoint
- [ ] Separate "Connections" tab showing:
  - IP addresses, ports, status
  - Model availability per connection
  - Request counts, latency metrics
  - Online/Offline/Degraded indicators
- [ ] Alert system for connection failures

**Database Schema:**
```sql
CREATE TABLE llm_connections (
    id SERIAL PRIMARY KEY,
    connection_name VARCHAR(100),
    connection_type VARCHAR(20), -- 'local', 'api', 'vpn'
    host VARCHAR(255),
    port INTEGER,
    api_key_configured BOOLEAN DEFAULT FALSE,
    models_available TEXT[],
    status VARCHAR(20) DEFAULT 'unknown',
    last_health_check TIMESTAMP,
    latency_ms INTEGER,
    total_requests INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Phase C: Station/Agent Assignment
**Complexity:** Low | **Priority:** MEDIUM

**Tasks:**
- [ ] Add `station` column to agents table
- [ ] Drag-and-drop agent assignment UI
- [ ] Station configuration modal
- [ ] Save/load station assignments
- [ ] Show agent avatar, name, current LLM at each station

### Phase D: Traffic Logging & Analytics (Future)
**Complexity:** Medium | **Priority:** LOW

**Tasks:**
- [ ] Enhanced request logging with station routing
- [ ] Traffic visualization (requests over time)
- [ ] Cost analytics by station
- [ ] Performance metrics dashboard

### Phase E: VPN Remote Nodes (Future)
**Complexity:** High | **Priority:** LOW

**Tasks:**
- [ ] Design remote node client software
- [ ] VPN connection management
- [ ] Node registration and authentication
- [ ] Version enforcement (client must match server)
- [ ] Load balancing across nodes
- [ ] Failover when node goes offline

**Architecture:**
```
┌─────────────────┐     VPN      ┌─────────────────┐
│ ARCHIE_BRIDGE   │◄────────────►│ Remote Node #1  │
│ (Master Server) │              │ (Contributor)   │
│                 │              │ - Ollama        │
│ 192.168.1.x     │              │ - GPU: RTX 3080 │
└─────────────────┘              └─────────────────┘
         ▲
         │ VPN
         ▼
┌─────────────────┐
│ Remote Node #2  │
│ (Contributor)   │
│ - Ollama        │
│ - GPU: RTX 4090 │
└─────────────────┘
```

### Phase F: Mining Pool Integration (Future)
**Complexity:** High | **Priority:** LOW

**Tasks:**
- [ ] Review mining pool documentation (user to provide)
- [ ] Design dual-purpose scheduler (AI tasks vs mining)
- [ ] Integrate with Bridge for resource management
- [ ] Reward system for contributors
- [ ] Blockchain-based authentication (optional)

---

## Database Enhancements Required

### New Tables

```sql
-- LLM Connection Registry
CREATE TABLE llm_connections (
    id SERIAL PRIMARY KEY,
    connection_name VARCHAR(100) NOT NULL,
    connection_type VARCHAR(20) NOT NULL, -- 'local', 'api', 'vpn_node'
    host VARCHAR(255) NOT NULL,
    port INTEGER,
    api_endpoint VARCHAR(500),
    api_key_env_var VARCHAR(100),
    models_available TEXT[],
    status VARCHAR(20) DEFAULT 'unknown',
    last_health_check TIMESTAMP,
    last_error TEXT,
    latency_ms INTEGER,
    total_requests INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 10,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Station Configuration
CREATE TABLE bridge_stations (
    id SERIAL PRIMARY KEY,
    station_code VARCHAR(20) UNIQUE NOT NULL, -- 'HELM', 'OPS', 'SCIENCE', etc.
    station_name VARCHAR(100) NOT NULL,
    description TEXT,
    default_agent_id INTEGER REFERENCES agents(id),
    default_connection_id INTEGER REFERENCES llm_connections(id),
    modules_covered TEXT[],
    position_x INTEGER, -- For visual layout
    position_y INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Station Assignments (which agent is at which station)
CREATE TABLE station_assignments (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES bridge_stations(id),
    agent_id INTEGER REFERENCES agents(id),
    assigned_at TIMESTAMP DEFAULT NOW(),
    assigned_by INTEGER REFERENCES users(id),
    is_current BOOLEAN DEFAULT TRUE,
    UNIQUE(station_id, agent_id, is_current)
);
```

### Updates to Existing Tables

```sql
-- Add station reference to agents
ALTER TABLE agents ADD COLUMN current_station_id INTEGER REFERENCES bridge_stations(id);

-- Add connection tracking to token_usage_log
ALTER TABLE token_usage_log ADD COLUMN connection_id INTEGER REFERENCES llm_connections(id);
ALTER TABLE token_usage_log ADD COLUMN station_code VARCHAR(20);
```

---

## UI/UX Guidelines

### Theme
- Dark cyberpunk matching platform style (`#010409` background)
- Station accent colors:
  - HELM: Blue `#0EA5E9`
  - OPS: Orange `#FFAA00`
  - SCIENCE: Purple `#8B5CF6`
  - COMMS: Cyan `#00FFFF`
  - ENGINE: Green `#00ff41`

### Interactive Elements
- Drag-and-drop agents between stations
- Click station → view detailed activity / navigate to modules
- Click LLM connection → view metrics / configure
- Real-time updates via WebSocket or polling

### A.R.C.H.I.E.'s Presence
- Always visible at COMMS station
- Show current mood from `archie_emotional_state`
- Voice DNA status indicator
- Quick access to Consciousness module

---

## Integration Points

### With Team Management
- Pull agent list with skills and model assignments
- Skill-based routing recommendations
- Budget tracking per agent

### With archie_bridge.py
- Bridge UI reflects actual routing decisions
- Station assignments inform routing logic
- Connection health affects model selection

### With Consciousness
- A.R.C.H.I.E.'s emotional state visible on Bridge
- Memory access for contextual responses
- Personality profile drives communication style

---

## Future Roadmap

| Phase | Feature | Target |
|-------|---------|--------|
| A | Bridge UI | Q1 2026 |
| B | LLM Monitor | Q1 2026 |
| C | Station Assignment | Q1 2026 |
| D | Traffic Analytics | Q2 2026 |
| E | VPN Remote Nodes | Q3 2026 |
| F | Mining Pool | Q4 2026 |

---

## Questions for User

1. **Mining Pool Documents:** Please share the mining pool files so we can integrate the vision properly.

2. **A.R.C.H.I.E.'s Voice:** The Voice DNA tables exist but are empty. Do you have audio samples or want to generate them with TTS?

3. **Station Count:** Based on modules, I suggest 5 stations. Want more or fewer?

4. **Remote Node Client:** Should we start designing the client software architecture now?

---

*This plan integrates with: Team Management, Consciousness, archie_bridge.py, and prepares for Mining Pool integration.*
