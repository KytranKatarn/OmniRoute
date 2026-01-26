# Conversation Triage System
## Consciousness Station Knowledge Pipeline

**Created:** January 16, 2026
**Status:** PLANNING
**Phase:** 42 (Proposed)

---

## Problem Statement

Currently:
- Pre-compact hook saves raw conversation transcripts (370+ entries)
- No intelligent extraction of valuable knowledge
- Consciousness station has Admin staff, not knowledge workers
- Mistakes, code snippets, and insights are buried in raw text
- No automated learning loop from Claude Code sessions

---

## Solution: Conversation Triage Pipeline

### 1. Staff Reassignment (Consciousness Station)

Move knowledge-focused agents to Consciousness station:

| Agent | Current Dept | Role at Consciousness |
|-------|--------------|----------------------|
| Knowledge Curator | (new) | Triages raw conversations |
| Error Analyst | (new) | Extracts mistakes and solutions |
| Code Archivist | (new) | Extracts reusable code snippets |
| Learning Synthesizer | (new) | Creates actionable insights |

### 2. Triage Pipeline Stages

```
┌─────────────────────────────────────────────────────────────────┐
│                    RAW CONVERSATION                              │
│                  (from pre-compact hook)                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAGE 1: CLASSIFICATION                             │
│  • Topic detection (what was discussed?)                        │
│  • Phase detection (planning, coding, debugging, etc.)          │
│  • Urgency scoring (errors = high, chat = low)                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ ERROR TRIAGE  │  │ CODE TRIAGE   │  │ INSIGHT TRIAGE│
│ • Mistakes    │  │ • Snippets    │  │ • Decisions   │
│ • Fixes       │  │ • Patterns    │  │ • Architecture│
│ • Prevention  │  │ • Functions   │  │ • Lessons     │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAGE 2: KNOWLEDGE EXTRACTION                       │
│  • Parse conversation for specific patterns                     │
│  • Extract structured data                                      │
│  • Assign categories and tags                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAGE 3: KNOWLEDGE BASE INSERTION                   │
│  • mistake_learned entries (importance: 0.95)                   │
│  • code_snippet entries (importance: 0.85)                      │
│  • improvement entries (importance: 0.80)                       │
│  • vault_note entries (importance: 0.90)                        │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Knowledge Types to Extract

#### A. Mistakes Learned
```json
{
  "type": "mistake_learned",
  "pattern": "Error patterns like 'column X does not exist', 'undefined is not a function'",
  "extraction": {
    "error_message": "The exact error",
    "cause": "Why it happened",
    "solution": "How it was fixed",
    "prevention": "How to avoid in future"
  },
  "importance": 0.95
}
```

#### B. Code Snippets
```json
{
  "type": "code_snippet",
  "pattern": "Code blocks in conversations (```python, ```javascript, etc.)",
  "extraction": {
    "language": "python/javascript/sql/etc",
    "purpose": "What the code does",
    "code": "The actual code",
    "context": "Where it's used"
  },
  "importance": 0.85
}
```

#### C. Architecture Decisions
```json
{
  "type": "improvement",
  "pattern": "Discussions about design choices, 'we should...', 'let's use...'",
  "extraction": {
    "decision": "What was decided",
    "alternatives": "What was considered",
    "rationale": "Why this choice",
    "files_affected": ["list of files"]
  },
  "importance": 0.80
}
```

#### D. Insights & Learnings
```json
{
  "type": "vault_note",
  "pattern": "Summaries, conclusions, 'this means...', 'in summary...'",
  "extraction": {
    "topic": "What was learned",
    "key_points": ["bullet points"],
    "related_files": ["list"],
    "future_implications": "How this affects future work"
  },
  "importance": 0.90
}
```

### 4. Implementation Files

```
/mnt/archie_brain/platform_v2/
├── conversation_triage/
│   ├── __init__.py
│   ├── classifier.py         # Stage 1: Classification
│   ├── extractors/
│   │   ├── error_extractor.py    # Mistake extraction
│   │   ├── code_extractor.py     # Code snippet extraction
│   │   └── insight_extractor.py  # Decision/insight extraction
│   ├── triage_pipeline.py    # Main orchestrator
│   └── routes.py             # API endpoints
├── scripts/hooks/
│   └── pre_compact_hook.sh   # Updated to trigger triage
```

### 5. API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/triage/process` | POST | Trigger triage on a conversation |
| `/api/triage/queue` | GET | View pending conversations |
| `/api/triage/stats` | GET | Triage statistics |
| `/api/triage/extract/errors` | GET | View extracted errors |
| `/api/triage/extract/snippets` | GET | View extracted snippets |

### 6. Bridge Integration

The Consciousness station on the Bridge will display:
- Triage queue status
- Recent extractions
- Knowledge growth metrics
- Agent activity (who is triaging what)

### 7. Database Tables

```sql
-- New table for triage queue
CREATE TABLE IF NOT EXISTS conversation_triage_queue (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES knowledge_base(id),
    status VARCHAR(20) DEFAULT 'pending', -- pending, processing, completed, failed
    priority INTEGER DEFAULT 5,
    assigned_agent_id INTEGER REFERENCES agents(id),
    classification JSONB,
    extractions JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Index for quick lookups
CREATE INDEX idx_triage_status ON conversation_triage_queue(status);
CREATE INDEX idx_triage_priority ON conversation_triage_queue(priority DESC);
```

---

## Implementation Phases

### Phase 42A: Core Pipeline (Priority: HIGH)
- [ ] Create `conversation_triage/` module
- [ ] Implement classifier.py
- [ ] Implement error_extractor.py
- [ ] Implement code_extractor.py
- [ ] Create database migration for triage_queue

### Phase 42B: Hook Integration
- [ ] Update pre_compact_hook.sh to queue for triage
- [ ] Create session_end_hook.sh triage trigger
- [ ] Add manual triage endpoint

### Phase 42C: UI & Monitoring
- [ ] Add Triage tab to Consciousness module
- [ ] Create Bridge widget for triage stats
- [ ] Add notification for high-priority items

### Phase 42D: Agent Assignment
- [ ] Reassign/create Consciousness station agents
- [ ] Create agent triage workflows
- [ ] Implement automated triage scheduling

---

## Success Metrics

1. **Knowledge Growth**: 10+ extracted items per conversation (vs 1 raw entry now)
2. **Error Prevention**: Mistakes found in past sessions prevent future errors
3. **Code Reuse**: Code snippets searchable and reusable
4. **Learning Loop**: Insights improve future A.R.C.H.I.E. responses

---

## Related Documentation

- `/docs/IAAE_GOVERNANCE_FRAMEWORK.md` - Memory management compliance
- `/docs/ARCHIE_CONSCIOUSNESS.md` - Consciousness system overview
- `/docs/LEARNING_LOOP_GUIDE.md` - Learning architecture
