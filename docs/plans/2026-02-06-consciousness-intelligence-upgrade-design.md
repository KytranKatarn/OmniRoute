# ARCHIE Consciousness Intelligence Upgrade - Design Document

**Phase:** 82
**Created:** 2026-02-06
**Status:** Approved, Ready for Implementation

---

## Executive Summary

Transform ARCHIE from a "storage system" to a "learning system" through AI-powered knowledge extraction. Currently, ARCHIE stores 3,390+ knowledge entries but performs no semantic analysis. This upgrade adds:

- **AI-powered analysis** using Claude API for deep insights
- **Semantic embeddings** using Ollama (nomic-embed-text) for similarity search
- **Knowledge graph** with 15 relationship types connecting concepts
- **Manual batch processing** with category selection and cost controls
- **Hybrid search** (70% vector + 30% keyword) for intelligent retrieval
- **Markdown export** for human-readable, Git-friendly knowledge cards

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Strategy | Hybrid | Ollama for embeddings (free), Claude for analysis (quality) |
| External API | Claude API | Familiar, good at code analysis, existing account |
| Processing Mode | Manual trigger | Full cost control, category-based batch selection |
| Embedding Storage | pgvector | Native PostgreSQL, keeps data unified |
| Embedding Model | nomic-embed-text | 768 dims, good quality, ~270MB |
| Knowledge Storage | DB primary + Markdown export | Fast queries + human-readable |
| Relationship Complexity | Rich ontology (15 types) | Expressive knowledge graph |
| Notifications | Activity feed only | No interruptions |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INGESTION SOURCES                           │
├─────────────────────────────────────────────────────────────────────┤
│  Conversation Logs    │    GitHub Repos    │    Claude Code Hooks   │
│     (1,000+ files)    │   (2,077 indexed)  │      (57 entries)      │
└──────────┬────────────┴─────────┬──────────┴───────────┬────────────┘
           │                      │                      │
           ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE ANALYZER                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Claude API      │  │  Ollama Local    │  │  Pattern         │  │
│  │  (Deep Analysis) │  │  (Embeddings)    │  │  Extraction      │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
└──────────┬────────────────────────┬─────────────────────┬───────────┘
           │                        │                     │
           ▼                        ▼                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         KNOWLEDGE STORAGE                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ PostgreSQL       │  │ pgvector         │  │ Markdown         │  │
│  │ (Primary)        │  │ (Embeddings)     │  │ (Export)         │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema Changes

### 1. Enable pgvector

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Modify knowledge_base table

```sql
-- Add embedding column (768 dimensions for nomic-embed-text)
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS ai_analysis JSONB;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS analysis_version INTEGER DEFAULT 0;

-- Add full-text search vector
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_kb_embedding ON knowledge_base
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_kb_search ON knowledge_base USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_kb_analysis_version ON knowledge_base(analysis_version);
```

### 3. Create knowledge_relationships table

```sql
CREATE TABLE IF NOT EXISTS knowledge_relationships (
    id SERIAL PRIMARY KEY,
    from_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    to_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,
    strength FLOAT DEFAULT 0.5 CHECK (strength >= 0 AND strength <= 1),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(from_id, to_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_kr_from ON knowledge_relationships(from_id);
CREATE INDEX IF NOT EXISTS idx_kr_to ON knowledge_relationships(to_id);
CREATE INDEX IF NOT EXISTS idx_kr_type ON knowledge_relationships(relationship_type);
```

### 4. Create processing_log table

```sql
CREATE TABLE IF NOT EXISTS knowledge_processing_log (
    id SERIAL PRIMARY KEY,
    batch_id UUID NOT NULL,
    source_type VARCHAR(50),
    source_id VARCHAR(255),
    status VARCHAR(20),  -- 'pending', 'processing', 'completed', 'failed', 'skipped'
    knowledge_ids INTEGER[],  -- IDs of created knowledge entries
    relationships_created INTEGER DEFAULT 0,
    tokens_used INTEGER,
    processing_time_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 5. Relationship Types (15 types)

| Type | Meaning | Example |
|------|---------|---------|
| `related_to` | General conceptual relation | Docker → Containers |
| `part_of` | Component/parent relationship | Flask Blueprint → Flask App |
| `uses` | Depends on or utilizes | API Route → Database |
| `extends` | Builds upon or enhances | Custom Logger → Python Logging |
| `implements` | Realizes a concept/pattern | AuthMiddleware → JWT Pattern |
| `solves` | Addresses a problem | Connection Pool → Too Many Connections |
| `causes` | Leads to or triggers | Memory Leak → OOM Error |
| `contradicts` | Conflicts with | Sync IO → Async Pattern |
| `supersedes` | Replaces older knowledge | New API → Deprecated API |
| `prerequisite_of` | Must understand first | SQL → PostgreSQL |
| `alternative_to` | Different approach to same goal | Redis → Memcached |
| `learned_from` | Source attribution | Concept → Conversation ID |
| `similar_to` | Semantically close | Docker Compose → Kubernetes |
| `example_of` | Concrete instance | User Auth Code → Auth Pattern |
| `applies_to` | Relevant context/domain | Pattern → Python Projects |

---

## Knowledge Card Structure

### Data Model

```python
@dataclass
class KnowledgeCard:
    # Core identification
    title: str              # "Docker Networking: Bridge vs Host Mode"
    card_type: str          # 'concept', 'pattern', 'problem-solution', 'example', 'reference'

    # Content tiers
    summary: str            # 2-3 sentences (for quick retrieval)
    detailed: str           # Full explanation with context
    code_examples: list     # Relevant snippets with language tags

    # Classification
    topics: list[str]       # ['docker', 'networking', 'containers']
    technologies: list[str] # ['docker-compose', 'linux']
    difficulty: str         # 'beginner', 'intermediate', 'advanced'

    # Provenance
    source_type: str        # 'conversation', 'github', 'claude_hook'
    source_ref: str         # File path or conversation ID
    confidence: float       # 0.0-1.0 (AI's confidence in extraction)

    # Relationships
    relationships: list[dict]  # [{'type': 'uses', 'target_id': 123}]
```

### Markdown Export Format

```
knowledge_cards/
├── concepts/
│   ├── docker-networking-bridge-vs-host.md
│   └── postgresql-connection-pooling.md
├── patterns/
│   ├── python-singleton-pattern.md
│   └── flask-blueprint-structure.md
├── problem-solutions/
│   ├── docker-container-dns-resolution.md
│   └── postgres-connection-refused.md
├── examples/
│   └── flask-jwt-authentication.md
├── references/
│   └── archie-api-endpoints.md
└── daily-logs/
    ├── 2026-02-06.md
    └── 2026-02-07.md
```

### Sample Markdown Card

```markdown
# Docker Networking: Bridge vs Host Mode

**Type:** concept | **Confidence:** 0.85 | **Difficulty:** intermediate

## Summary

Docker bridge networks isolate containers with virtual interfaces, while host
mode shares the host's network stack directly. Bridge is default and recommended
for most cases; host mode is useful when network performance is critical.

## Detailed Explanation

### Bridge Mode (Default)
- Creates virtual ethernet bridge (docker0)
- Each container gets own IP in bridge subnet
- Port mapping required for external access (-p flag)
- Containers can communicate via container names

### Host Mode
- Container shares host's network namespace
- No network isolation from host
- No port mapping needed (uses host ports directly)
- Better performance, less security

## Code Examples

```bash
# Bridge network (default)
docker network create my-bridge
docker run --network my-bridge --name web nginx
docker run --network my-bridge --name api python-app

# Host mode
docker run --network host nginx
```

```yaml
# docker-compose.yml
services:
  web:
    image: nginx
    network_mode: bridge  # default
  db:
    image: postgres
    network_mode: host    # use host networking
```

## Related Concepts

- [[container-dns-resolution]] (solves)
- [[docker-compose-networking]] (extends)
- [[kubernetes-networking]] (similar_to)

## Relationships

| Type | Target | Strength |
|------|--------|----------|
| part_of | Docker Fundamentals | 0.9 |
| prerequisite_of | Docker Compose | 0.7 |
| solves | Container Communication | 0.8 |

---
*Source: conversation_20260205_143022 | Extracted: 2026-02-06 14:32:05*
*Knowledge ID: 3421 | Analysis Version: 1*
```

---

## File Structure

### New Files

```
ai_bridge/
├── knowledge_analyzer.py      # AI-powered extraction (Claude + Ollama)
├── semantic_search.py         # Hybrid vector + keyword search
├── knowledge_cards.py         # Card generation & Markdown export
├── embedding_service.py       # Ollama embedding wrapper
├── relationship_mapper.py     # Knowledge graph relationships
└── cost_controller.py         # API usage tracking & limits

platform_v2/tools/consciousness/
├── processing_routes.py       # Manual batch processing API
└── templates/
    └── consciousness_dashboard.html  # Add AI Processing tab

knowledge_cards/               # Markdown exports
├── concepts/
├── patterns/
├── problem-solutions/
├── examples/
├── references/
└── daily-logs/
```

### Modified Files

```
ai_bridge/
├── conversation_ingest.py     # Add AI analysis pipeline
├── archie_bridge.py           # Integrate new analyzers
└── consciousness_scheduler.py # Remove auto-processing

platform_v2/tools/consciousness/
├── routes.py                  # Add processing endpoints
└── log_ingestor.py           # Integrate Knowledge Analyzer
```

---

## Hybrid Semantic Search

### Algorithm

```python
def search(query: str, limit=10, filters=None) -> list[SearchResult]:
    # 1. Generate query embedding via Ollama
    query_embedding = embedding_service.generate(query)

    # 2. Vector similarity search (pgvector) - 70% weight
    vector_results = db.execute("""
        SELECT id, title, summary,
               1 - (embedding <=> %s) as vector_score
        FROM knowledge_base
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s
        LIMIT %s
    """, (query_embedding, query_embedding, limit * 2))

    # 3. Keyword search (PostgreSQL FTS) - 30% weight
    keyword_results = db.execute("""
        SELECT id, title, summary,
               ts_rank_cd(search_vector, plainto_tsquery(%s)) as text_score
        FROM knowledge_base
        WHERE search_vector @@ plainto_tsquery(%s)
        ORDER BY text_score DESC
        LIMIT %s
    """, (query, query, limit * 2))

    # 4. Score fusion
    # final_score = (0.7 * norm_vector) + (0.3 * norm_keyword)
    return fuse_results(vector_results, keyword_results, limit)
```

### Query Type Optimization

| Query Type | Primary Match | Example |
|------------|---------------|---------|
| Conceptual | Vector (semantic) | "how to handle database connections" |
| Exact match | Keyword (BM25) | "ERROR: connection refused" |
| Mixed | Hybrid fusion | "docker networking bridge mode" |

---

## Manual Processing UI

### Backlog Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│  🧠 AI KNOWLEDGE PROCESSING                              [Refresh]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐ │
│  │ Conversations│  │   GitHub     │  │ Claude Hooks │  │ Total   │ │
│  │    1,247     │  │    2,077     │  │      57      │  │  3,381  │ │
│  │   pending    │  │   pending    │  │   pending    │  │ pending │ │
│  │  ⚡ 0 done   │  │  ⚡ 0 done   │  │  ⚡ 0 done   │  │         │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  PROCESS BATCH                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Category: [Conversations ▼]    Batch Size: [50    ]         │   │
│  │                                                              │   │
│  │ Sort by: [○ Oldest first  ● Largest first  ○ Random]        │   │
│  │                                                              │   │
│  │ [👁 Preview]    [🚀 Process]    [📊 Est. Cost: ~$0.45]      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  PROCESSING LOG                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 14:32:05 ✓ conversation_20260201_143022                     │   │
│  │          → 3 concepts, 1 problem-solution, 7 relationships  │   │
│  │ 14:32:08 ✓ conversation_20260201_150815                     │   │
│  │          → 1 concept, 2 patterns                            │   │
│  │ 14:32:12 ⚠ snapshot_20260201_160000 (skipped: too short)   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### API Endpoints

```
POST /tools/consciousness/api/processing/start
  Body: { category: "conversations", batch_size: 50, sort: "largest" }
  Returns: { batch_id, estimated_tokens, estimated_cost }

GET  /tools/consciousness/api/processing/status/{batch_id}
  Returns: { status, processed, total, current_item, log }

POST /tools/consciousness/api/processing/cancel/{batch_id}
  Returns: { cancelled: true, processed_before_cancel: 23 }

GET  /tools/consciousness/api/processing/backlog
  Returns: { conversations: 1247, github: 2077, claude_hooks: 57 }

POST /tools/consciousness/api/processing/estimate
  Body: { category: "conversations", batch_size: 50 }
  Returns: { tokens: 45000, cost_usd: 0.45, items: [...] }
```

---

## Cost Controls

### Limits

```python
class CostController:
    DAILY_TOKEN_LIMIT = 500_000      # ~$7.50/day max
    BATCH_TOKEN_LIMIT = 50_000       # Per batch run
    WARN_THRESHOLD_USD = 1.00        # Warn before processing
```

### Pre-Processing Checks

1. Estimate tokens before API call
2. Warn if batch exceeds $1.00
3. Block if daily limit reached
4. Skip items >50KB with warning

### Error Handling

| Error | Response |
|-------|----------|
| Claude rate limit | Pause 60s, retry 3x, stop batch |
| Claude API error | Log, skip item, continue |
| Ollama connection fail | Skip embedding, save analysis |
| Database error | Rollback, log, stop batch |
| Invalid content | Skip with warning |

### Safeguards

- Transaction per item
- Checkpoint every 10 items
- Processing lock (prevent double-run)
- Hash-based duplicate detection

---

## Implementation Phases

### Phase 1: Foundation (~1 hour)

- [ ] 1.1 Install pgvector extension in PostgreSQL
- [ ] 1.2 Run database migrations (new columns, tables, indexes)
- [ ] 1.3 Pull nomic-embed-text model to Ollama
- [ ] 1.4 Create `embedding_service.py`
- [ ] 1.5 Create `cost_controller.py`

### Phase 2: Knowledge Analyzer (~2-3 hours)

- [ ] 2.1 Create `knowledge_analyzer.py` base class
- [ ] 2.2 Implement `analyze_conversation()` method
- [ ] 2.3 Implement `analyze_code_file()` method
- [ ] 2.4 Implement `analyze_github_repo()` method
- [ ] 2.5 Create `knowledge_cards.py` for card structure

### Phase 3: Relationships & Search (~1-2 hours)

- [ ] 3.1 Create `relationship_mapper.py`
- [ ] 3.2 Create `semantic_search.py`
- [ ] 3.3 Add search API endpoints to routes.py
- [ ] 3.4 Integrate search into existing UI

### Phase 4: Processing Pipeline (~1-2 hours)

- [ ] 4.1 Create `processing_routes.py` (batch API)
- [ ] 4.2 Modify `log_ingestor.py` (integrate analyzer)
- [ ] 4.3 Modify `conversation_ingest.py` (add AI pipeline)
- [ ] 4.4 Update `consciousness_scheduler.py` (remove auto)

### Phase 5: UI & Export (~1-2 hours)

- [ ] 5.1 Add AI Processing tab to consciousness dashboard
- [ ] 5.2 Create `knowledge_cards/` directory structure
- [ ] 5.3 Implement Markdown export in `knowledge_cards.py`
- [ ] 5.4 Add backlog counters to dashboard
- [ ] 5.5 Add real-time processing log viewer

### Phase 6: Integration & Testing (~1 hour)

- [ ] 6.1 Test full pipeline with 5 sample items
- [ ] 6.2 Verify embeddings stored correctly
- [ ] 6.3 Verify relationships created
- [ ] 6.4 Test hybrid search
- [ ] 6.5 Process small batch (10 items) end-to-end
- [ ] 6.6 Fix any issues
- [ ] 6.7 Commit and document

---

## Success Criteria

1. **Embeddings working**: Can generate and store 768-dim vectors
2. **AI analysis working**: Claude extracts structured insights
3. **Search working**: Hybrid search returns relevant results
4. **Relationships working**: Knowledge graph has connections
5. **UI working**: Can select category, see costs, process batches
6. **Export working**: Markdown files generated in knowledge_cards/

---

## Dependencies

### Python Packages

```
anthropic>=0.18.0    # Claude API client
pgvector>=0.2.0      # PostgreSQL vector support (Python bindings)
```

### System Requirements

```bash
# PostgreSQL extension (run in database)
CREATE EXTENSION vector;

# Ollama model
ollama pull nomic-embed-text
```

---

## API Reference

### Claude API Usage

```python
# Analysis prompt template
CONVERSATION_ANALYSIS_PROMPT = """
Analyze this conversation and extract structured knowledge.

Return JSON with:
{
  "cards": [
    {
      "title": "...",
      "card_type": "concept|pattern|problem-solution|example",
      "summary": "2-3 sentences",
      "detailed": "full explanation",
      "code_examples": ["..."],
      "topics": ["..."],
      "technologies": ["..."],
      "difficulty": "beginner|intermediate|advanced",
      "confidence": 0.0-1.0
    }
  ],
  "relationships": [
    {
      "from_title": "...",
      "to_concept": "...",
      "type": "uses|extends|solves|...",
      "strength": 0.0-1.0
    }
  ]
}

Conversation:
User: {user_message}
AI: {ai_response}
"""
```

### Ollama Embedding API

```python
# POST http://192.168.1.200:11434/api/embeddings
{
  "model": "nomic-embed-text",
  "prompt": "text to embed"
}

# Response
{
  "embedding": [0.123, -0.456, ...]  # 768 floats
}
```

---

## Notes

- Daily API costs capped at ~$7.50 (500K tokens)
- All processing is manual trigger only
- Markdown export is supplementary (DB is source of truth)
- Relationships are bidirectional queries but stored once
- Embeddings regenerated if model changes (track model version)

---

*Document created: 2026-02-06*
*Ready for implementation*
