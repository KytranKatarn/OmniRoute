# Consciousness Visualization Guide

**Module:** Consciousness Dashboard
**Phase:** 28 - Consciousness Optimization & Admin Ops Integration
**Status:** Active

---

## Overview

The Consciousness Module provides comprehensive visualization of A.R.C.H.I.E.'s knowledge base, emotional state, learning patterns, and activity feed. Phase 28 introduced a complete UI overhaul with Chart.js and D3.js integration.

## Dashboard Tabs

### 1. Overview
Quick-glance dashboard with:
- **Stats Grid:** Total memories, vault notes, learned mistakes, improvement proposals
- **Mini Charts:** Knowledge growth trend, type distribution pie chart
- **Quick Access Cards:** Navigation to other modules

### 2. Emotional State
Monitors A.R.C.H.I.E.'s emotional health:
- **Mood Indicator:** Current mood with emoji (happy, curious, focused, neutral, confused, frustrated)
- **Energy Gauge:** 0.0-1.0 scale
- **Confidence Gauge:** 0.0-1.0 scale
- **Stress Level:** Warning if > 0.85 (IAAE compliance)
- **Timeline Chart:** 7-day emotional history

### 3. Knowledge Charts
Full-size data visualizations:
- **Growth Line Chart:** Knowledge entries over last 30 days
- **Type Pie Chart:** Distribution by type (vault_note, mistake_learned, etc.)
- **Category Bar Chart:** Breakdown by category
- **Importance Doughnut:** Distribution by importance score ranges

### 4. Knowledge Graph
Interactive D3.js force-directed graph:
- **Nodes:** Knowledge entries (sized by importance_score)
- **Edges:** Backlinks between entries
- **Filters:** Filter by type (vault_note, github_file, etc.)
- **Click Interaction:** View entry details

### 5. Activity Feed
Real-time activity monitoring:
- **Event Types:** Knowledge additions, agent executions, proposals, conversations
- **Time Windows:** 5m, 15m, 1h, 24h
- **Type Filters:** All, Knowledge, Agents, Proposals
- **Auto-refresh:** Updates automatically

### 6. Tools
Navigation cards to other Consciousness features:
- Memory Explorer
- Analytics Dashboard
- Emotional Timeline
- Learning Records
- Brain Search
- Graph Visualization

---

## Technical Implementation

### Libraries Used
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
```

### Auto-Refresh
Stats update every 30 seconds via JavaScript:
```javascript
setInterval(loadOverviewStats, 30000);
```

---

## API Endpoints

### Statistics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/consciousness/stats` | Knowledge base statistics |
| GET | `/consciousness/emotional-state` | Current emotional state |
| GET | `/consciousness/emotions/timeline` | 7-day emotional history |

### Knowledge
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/consciousness/knowledge/graph` | Knowledge graph data |
| GET | `/consciousness/knowledge/<id>/backlinks` | Entry backlinks |
| GET | `/consciousness/knowledge/growth` | Growth over time |

### Activity Feed
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/consciousness/activity-feed` | Aggregated activity events |
| GET | `/consciousness/activity-stats` | Activity statistics |

### Activity Feed Parameters
```
?since=<ISO timestamp>    # Events after this time
?limit=<number>           # Max events to return (default: 50)
?type=<type>              # Filter by event type
```

---

## Data Sources

### Knowledge Base Types
| Type | Description | Weight |
|------|-------------|--------|
| `vault_note` | Curated Obsidian documentation | 1.2x |
| `mistake_learned` | Error prevention knowledge | 1.3x |
| `improvement` | Code change records | 1.0x |
| `code_snippet` | Proven code patterns | 1.1x |
| `github_file` | Indexed repository files | 0.8x |
| `conversation_memory` | Dynamic learning | 0.8x |

### Emotional State Sources
- `agent_emotional_state` table
- Sentiment analysis from conversations
- Stress detection from workload

### Activity Feed Sources
- `knowledge_base` (new entries)
- `agent_executions` (task completions)
- `improvement_proposals` (proposal activity)
- `conversation_sessions` (chat sessions)
- `llm_alerts` (system alerts)

---

## Customization

### Theme Variables
```css
:root {
    --consciousness-primary: #FF00FF;    /* Magenta */
    --consciousness-secondary: #00FFFF;  /* Cyan */
    --consciousness-bg: #0d1117;
    --consciousness-panel: #161b22;
    --consciousness-border: #30363d;
}
```

### Chart Colors
```javascript
const chartColors = {
    primary: '#FF00FF',
    secondary: '#00FFFF',
    success: '#10B981',
    warning: '#FFAA00',
    error: '#FF4444'
};
```

---

## Sample Queries

### Get Knowledge Growth
```sql
SELECT
    DATE(created_at) as date,
    COUNT(*) as count
FROM knowledge_base
WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY date;
```

### Get Type Distribution
```sql
SELECT
    entry_type,
    COUNT(*) as count
FROM knowledge_base
GROUP BY entry_type
ORDER BY count DESC;
```

### Get Emotional Timeline
```sql
SELECT
    DATE(recorded_at) as date,
    AVG(energy) as avg_energy,
    AVG(confidence) as avg_confidence,
    AVG(stress_level) as avg_stress
FROM agent_emotional_state
WHERE recorded_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(recorded_at)
ORDER BY date;
```

---

## Files Modified

| File | Changes |
|------|---------|
| `consciousness_dashboard.html` | Complete UI rewrite with 6 tabs |
| `routes.py` | Added `/activity-feed` and `/activity-stats` endpoints |

---

## Related Documentation

- [A.R.C.H.I.E. Consciousness](ARCHIE_CONSCIOUSNESS.md)
- [Knowledge Base Schema](DATABASE_SCHEMA_DOCUMENTATION.md)
- [Memory Manager](../ai_bridge/conversation_ingest.py)

---

**Last Updated:** 2026-01-17 (Phase 28)
