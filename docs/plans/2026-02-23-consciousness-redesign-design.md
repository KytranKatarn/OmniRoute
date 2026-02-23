# Consciousness Module Full Redesign — Design Document

**Date**: 2026-02-23
**Project**: UI Overhaul (#94)
**Status**: Approved

---

## Goal

Full LCARS visual redesign of the Consciousness module — ARCHIE's brain. Consolidate 9 tabs to 7, split the monolithic routes.py (9,844 lines) into focused files, add cross-module integration with Dev HQ and Bridge Command, complete i18n translations for Bridge + Dev HQ + Consciousness, and verify the Bridge-only translation pipeline (ADR-013).

## Architecture

### Current State (Problems)
- `routes.py`: 9,844 lines, 150+ endpoints in one file
- `consciousness_dashboard.html`: 6,653 lines, all JS inline
- No external JS file
- No cross-module integration (Consciousness, Dev HQ, Bridge are siloed)
- Missing translations for Bridge and Dev HQ modules
- Voice DNA is a separate tab but belongs with agent profiles

### Target State
```
tools/consciousness/
├── __init__.py              # Blueprint registration (unchanged)
├── routes.py                # Main page render + Dashboard tab APIs (~300 lines)
├── knowledge_routes.py      # Knowledge tab APIs
├── team_routes.py           # Team/Agent personnel APIs
├── insights_routes.py       # Analytics + Sessions + Improvements APIs
├── languages_routes.py      # Languages tab APIs
├── github_routes.py         # GitHub tab APIs
├── integration_routes.py    # NEW: Cross-module + pipeline monitor APIs
├── processing_routes.py     # Existing processing endpoints (keep)
├── templates/
│   └── consciousness_dashboard.html  # Rebuilt LCARS template (~2,500 lines)
└── (existing support files unchanged)
```

### External JS
- `platform_v2/static/js/consciousness.js` — tab switching, API helpers, charts
- Same pattern as `devhq.js`: `api()` helper for route-prefixed fetch calls

### API-First
All tabs load data via JSON APIs prefixed `/consciousness/api/...`

---

## Tab Structure (7 tabs, consolidated from 9)

| # | Tab | Icon | Merged From | Key Elements |
|---|-----|------|-------------|-------------|
| 1 | Dashboard | tachometer-alt | Dashboard + Analytics overview | ARCHIE's self-portrait |
| 2 | Knowledge | brain | Memory/Knowledge | KB browser, processing, embeddings |
| 3 | Team | users | Team + Voice DNA | Agent personnel files with voice |
| 4 | Insights | chart-line | Analytics + Sessions + Improvements | Processing stats, session history, proposals |
| 5 | Languages | language | Languages | Translation management (4 sub-tabs) |
| 6 | GitHub | github | GitHub | Repo indexing, search, files |
| 7 | Integration | plug | **NEW** | Cross-module hub, pipeline monitor |

---

## Tab 1: Dashboard — ARCHIE's Self-Portrait

ARCHIE sees herself: her knowledge, her agents, her projects, her emotional state.

### Top Row — 4 Stat Cards
1. **Knowledge**: Total active entries | Embedding coverage % | Category count
2. **Agent Fleet**: Total agents | Active now | Avg wellness score (mood+energy composite)
3. **Projects**: Active projects (from `unified_projects`) | Tasks in-progress | Completion rate
4. **System**: Platform uptime | Last health check result | Integration status (green/yellow/red)

### Middle Row — Live Feeds
- **Recent Activity** (left 60%): Blended chronological feed from knowledge processing, agent actions, project updates, bridge interactions. Last 24h, 15 items. Each entry links to source module.
- **Emotional Pulse** (right 40%): Fleet-wide emotional snapshot — avg mood/energy/stress across all agents. Burnout alerts if any agent's stress > 0.8. Mini sparklines for trend.

### Bottom Row — Quick Insights
- **Top Categories**: Horizontal bar chart of most-populated knowledge categories
- **Agent Leaderboard**: Top 5 agents by task completion (last 7 days)
- **Integration Health**: Status badges for Dev HQ, Bridge, Ollama, GitHub, IAAE — green/yellow/red with last-sync time

### Data Sources
- Knowledge: `knowledge_base` table (count, embedding coverage)
- Agents: `agent_profiles` + `agent_emotional_states` + `agent_skills`
- Projects: `unified_projects` + `unified_tasks` (via Dev HQ API or direct DB)
- System: `service_health_history` + `service_status`
- Activity: `knowledge_base` (recent), `bridge_interaction_log` (recent), `agent_activity_log` (recent)

---

## Tab 2: Knowledge — Knowledge Base Browser

### Sub-tabs: Browser | Processing | Categories | Embeddings

**Browser**:
- Searchable, filterable table: title, type, category, embedding status, created date
- Filters: knowledge type (7 types), category, has_embedding, date range
- Click row → detail modal with full content, AI analysis, metadata
- Bulk actions: re-embed, re-categorize, archive

**Processing**:
- Queue of entries currently being analyzed/embedded
- Real-time progress: entries processed / total, estimated completion
- Processing log: recent analysis results with extracted tags/categories

**Categories**:
- Category list with entry counts
- Merge categories, rename, view entries per category
- Auto-categorization status

**Embeddings**:
- Coverage dashboard: % embedded (active vs archived)
- Batch operations: embed all unembedded, re-embed stale
- Dimension info: 768-dim arctic-embed-cpu

---

## Tab 3: Team — Agent Command Center (Personnel Files)

Bridge Command = where agents ARE (operations, stations, dispatch).
Consciousness Team = who agents ARE (identity, personality, skills, wellness).

### Agent Roster Grid
Card per agent showing:
- Avatar + name + role
- Station assignment (badge, links to Bridge Command)
- Personality summary (1-2 trait words)
- Skills count
- Emotional status: mood/energy/stress mini-bars (color-coded)
- IAAE compliance badge (green ✓ / yellow ⚠ / red ✗)
- Voice DNA: mini play button for sample
- Learning history: count of learned items

### Agent Profile Modal (click to expand)
- **Identity**: Full name, role, backstory, communication style
- **Personality**: All traits with values, personality archetype
- **Skills**: Matrix with proficiency levels, learning progress
- **Wellness**: Emotional timeline chart (30 days) — mood, energy, stress lines
- **Ethics**: IAAE compliance log, recent constraints/overrides, ATHENA assessments
- **Voice**: Engine (Kokoro/XTTS), language, emotion settings, sample playback
- **Learning**: Recent knowledge extracted, lessons learned
- **Bridge Link**: "View in Bridge Command →" button

### Data Sources
- `agent_profiles`, `agent_personalities`, `agent_skills`, `agent_emotional_states`
- `agent_ethics_constraints`, `iaae_compliance_log`, `governance_audit_log`
- `agent_voice_profiles`, `agent_learning_log`
- Cross-link: Bridge station assignments from `bridge_stations` + `station_agents`

---

## Tab 4: Insights — Analytics + Sessions + Improvements

### Sub-tabs: Analytics | Sessions | Improvements

**Analytics**:
- AI processing stats: requests/day, tokens consumed, avg response time
- Model usage breakdown: pie chart by model (dolphin3, qwen3, haiku, etc.)
- Trend charts: processing volume over 7/30 days
- Knowledge growth: entries added per day

**Sessions**:
- Collaboration session list: Claude bridge interactions, multi-turn conversations
- Filterable by date, agent, topic
- Click → session detail with full transcript
- Learning extractions from each session

**Improvements**:
- Scan results: what was found, severity, recommendations
- Proposals: pending, approved, deployed status
- Deployment history: what was auto-deployed vs human-approved

---

## Tab 5: Languages — Translation Management

Same 4 sub-tabs rebuilt with LCARS:

**Dashboard**: Coverage stats per module (cards showing % complete for Dashboard, Bridge, Dev HQ, Consciousness). Overall stats. "Generate Missing" bulk action per module.

**Browser**: Translation table with inline editing. Filter by language, module, status. Search by key or text.

**Review**: Queue of `pending_review` translations. Approve/reject with one click.

**Glossary**: Translation memory entries. Add/edit/delete terms. Consistency checking.

### Translation Completion Scope
- Audit and complete: Bridge module keys
- Audit and complete: Dev HQ module keys
- Full i18n for new Consciousness template from day one
- Verify all translation requests route through Bridge (ADR-013)

---

## Tab 6: GitHub — Repository Integration

### Sub-tabs: Repos | Search | Files

**Repos**: List of indexed repositories. Last indexed date, file count, status. Re-index button. Add new repo.

**Search**: Full-text search across indexed files. Uses embeddings for semantic search. Results show file path, relevant snippet, similarity score.

**Files**: Browse indexed file content. Tree view by repo → directory → file.

---

## Tab 7: Integration — Cross-Module Hub (NEW)

### Status Dashboard
Connection health for each integrated system:
- **Dev HQ**: Projects count, last task update, API reachable
- **Bridge Command**: Station count, active agents, API reachable
- **Ollama**: Model count, GPU status, API reachable
- **GitHub**: Indexed repos, last index time, API reachable
- **IAAE**: Governance active, last ethics event, API reachable

### Translation Pipeline Monitor
Visual pipeline diagram:
```
Request → Bridge API → Smart Router → Model Selection → LLM Call → Response
```
- Each step shows: status (green/red), latency, last execution
- **Test Pipeline** button: sends a test translation ("Hello" → French), traces each step
- Results: route taken, model used, response time, Bridge log entry ID

### ADR-013 Compliance Checker
- Scans codebase for direct Ollama calls outside of `archie_bridge.py`
- Shows: compliant modules (green), violations found (red), scan date
- One-click scan button

### Cross-Module Activity
- **From Dev HQ**: Last 5 project updates, recent decisions
- **From Bridge**: Last 5 dispatch events, station changes
- **From IAAE**: Last 5 governance events

---

## Visual Design

All tabs follow the LCARS gold-standard established by Dashboard + Bridge + Dev HQ:
- Framed header with module title and icon navigation
- Tab pills with active state highlighting
- Stat cards with icon, label, value, trend indicator
- Data tables with hover states, alternating rows
- Modals with LCARS-styled headers and close buttons
- Responsive: 3 breakpoints (374px, 717px, 1280px)
- Dark theme with amber/gold LCARS accents
- Full `data-i18n` attributes on all user-facing strings

---

## Cross-Module Linking Strategy

### Consciousness → Bridge
- Agent card → "View in Bridge Command" link (`/bridge#stations`)
- Station badge on agent cards links to Bridge station view

### Consciousness → Dev HQ
- Dashboard project cards link to Dev HQ project detail
- Integration tab shows live Dev HQ data

### Bridge → Consciousness
- Agent in station roster → "View Personnel File" link (`/consciousness#team`)
- Dispatch detail → agent profile link

### Dev HQ → Consciousness
- Knowledge browser → link to Consciousness knowledge tab
- Integration status → link to Consciousness integration tab

---

## Translation Pipeline Verification

### What We're Verifying
Per ADR-013, ALL LLM calls must route through `archie_bridge.py`. This ensures:
- Agent assignment and tracking
- Bridge dashboard visibility
- IAAE governance compliance
- Smart router escalation
- HR labor tracking

### Test Cases
1. **Translation request**: POST to translation service → verify Bridge log entry created
2. **Knowledge analysis**: Trigger analysis → verify Bridge log entry
3. **Direct Ollama detection**: Scan for imports of `requests` or `httpx` calling Ollama port outside bridge

### Completion Targets
- Bridge module: audit keys, generate missing translations (7 languages)
- Dev HQ module: audit keys, generate missing translations (7 languages)
- Consciousness module: full i18n from day one (all 8 languages)

---

## Data Dependencies (Existing Tables Used)

### Agent System (22+ tables)
`agent_profiles`, `agent_personalities`, `agent_skills`, `agent_emotional_states`, `agent_ethics_constraints`, `agent_voice_profiles`, `agent_learning_log`, `iaae_compliance_log`, `governance_audit_log`, `agent_activity_log`, `bridge_stations`, `station_agents`

### Knowledge System
`knowledge_base` (~5K active, 768-dim embeddings), `knowledge_processing_queue`

### Project System
`unified_projects`, `unified_tasks`, `project_decisions`

### Translation System
`translations`, `translation_memory`, `user_language_preferences`

### GitHub System
`github_indexed_files`, `github_repos`

### Monitoring
`service_health_history`, `service_status`, `mcp_tool_usage`, `bridge_interaction_log`

---

## No New Tables Required

All data already exists in existing tables. This redesign is purely a UI/UX overhaul + route reorganization + cross-module integration. No new migrations needed.
