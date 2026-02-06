# ARCHIE Consciousness Intelligence Upgrade - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform ARCHIE from a storage system to a learning system with AI-powered knowledge extraction, semantic search, and knowledge graph relationships.

**Architecture:** Hybrid LLM approach using Ollama (nomic-embed-text) for embeddings and Claude API for deep analysis. Manual batch processing with category selection. pgvector for semantic search in PostgreSQL.

**Tech Stack:** Python, PostgreSQL + pgvector, Ollama, Claude API (anthropic), Flask

---

## Pre-Implementation Checklist

Before starting, verify:
- [ ] Ollama running at http://192.168.1.200:11434
- [ ] PostgreSQL accessible via Docker (archie_database)
- [ ] Claude API key available in environment
- [ ] Platform running at http://192.168.1.200:3000

---

## Phase 1: Foundation

### Task 1.1: Install pgvector Extension

**Files:**
- Create: `/mnt/archie_brain/scripts/install_pgvector.sql`

**Step 1: Create migration script**

Create file with SQL to enable vector extension and verify installation.

**Step 2: Run migration in database**

Run: `docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/scripts/install_pgvector.sql`

Expected: CREATE EXTENSION and version output

**Step 3: Commit**

```bash
git add scripts/install_pgvector.sql
git commit -m "chore(db): add pgvector extension for semantic embeddings"
```

---

### Task 1.2: Database Schema Migration

**Files:**
- Create: `/mnt/archie_brain/scripts/phase82_schema_migration.sql`

**Changes:**
1. Add embedding vector(768) column to knowledge_base
2. Add ai_analysis JSONB column
3. Add search_vector tsvector with GIN index
4. Create knowledge_relationships table
5. Create knowledge_processing_log table
6. Create api_usage_daily table
7. Add trigger for auto-updating search_vector

**Step 1: Create schema migration script**
**Step 2: Run migration**
**Step 3: Verify columns added**
**Step 4: Commit**

---

### Task 1.3: Pull nomic-embed-text Model

**Step 1: Pull embedding model to Ollama**

Run: `curl -X POST http://192.168.1.200:11434/api/pull -d '{"name": "nomic-embed-text"}'`

**Step 2: Verify model available**
**Step 3: Test embedding generation (expect 768 dimensions)**

---

### Task 1.4: Create Embedding Service

**Files:**
- Create: `/mnt/archie_brain/ai_bridge/embedding_service.py`

**Contents:**
- EmbeddingService class with generate() and generate_batch() methods
- Health check function
- Singleton accessor get_embedding_service()
- Convenience function generate_embedding()

**Step 1: Create module**
**Step 2: Test in container**
**Step 3: Commit**

---

### Task 1.5: Create Cost Controller

**Files:**
- Create: `/mnt/archie_brain/ai_bridge/cost_controller.py`

**Contents:**
- CostController class with usage tracking
- Daily token limits (500K/day)
- Batch cost estimation
- Usage logging to api_usage_daily table

**Step 1: Create module**
**Step 2: Test in container**
**Step 3: Commit**

---

## Phase 2: Knowledge Analyzer

### Task 2.1: Create Knowledge Analyzer Base

**Files:**
- Create: `/mnt/archie_brain/ai_bridge/knowledge_analyzer.py`

**Contents:**
- KnowledgeCard dataclass
- ExtractedRelationship dataclass
- AnalysisResult dataclass
- KnowledgeAnalyzer class with Claude API integration
- analyze_conversation() method
- analyze_code_file() method
- JSON response parsing

**Step 1: Create module**
**Step 2: Test health check**
**Step 3: Commit**

---

### Task 2.2: Create Knowledge Cards Module

**Files:**
- Create: `/mnt/archie_brain/ai_bridge/knowledge_cards.py`

**Contents:**
- save_knowledge_card() function
- export_to_markdown() function
- ensure_directories() function
- get_export_stats() function
- Markdown template generation

**Step 1: Create module**
**Step 2: Create directory structure**
**Step 3: Commit**

---

### Task 2.3: Create Semantic Search Module

**Files:**
- Create: `/mnt/archie_brain/ai_bridge/semantic_search.py`

**Contents:**
- SearchResult dataclass
- SemanticSearch class
- Hybrid search (70% vector + 30% keyword)
- Score fusion algorithm
- Keyword-only fallback search

**Step 1: Create module**
**Step 2: Test keyword search**
**Step 3: Commit**

---

### Task 2.4: Create Relationship Mapper

**Files:**
- Create: `/mnt/archie_brain/ai_bridge/relationship_mapper.py`

**Contents:**
- RELATIONSHIP_TYPES list (15 types)
- RelationshipMapper class
- create_relationship() method
- find_related() method
- get_graph_stats() method

**Step 1: Create module**
**Step 2: Test graph stats**
**Step 3: Commit**

---

## Phase 3: Processing Pipeline

### Task 3.1: Create Processing Routes

**Files:**
- Create: `/mnt/archie_brain/platform_v2/tools/consciousness/processing_routes.py`

**Endpoints:**
- GET /api/processing/status - Overall status and backlog
- GET /api/processing/backlog - Detailed backlog counts
- POST /api/processing/estimate - Cost estimation
- POST /api/processing/start - Start batch processing
- POST /api/processing/generate-embeddings - Generate missing embeddings

**Step 1: Create routes module**
**Step 2: Register routes**
**Step 3: Commit**

---

## Phase 4: UI Updates

### Task 4.1: Add AI Processing Tab to Dashboard

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/templates/tools/consciousness_dashboard.html`

**Changes:**
1. Add AI Processing tab button
2. Add tab content with:
   - Backlog stats cards (conversations, github, hooks, embeddings)
   - Cost status display
   - Batch processing form (category, size, estimate, process buttons)
   - Processing log viewer
3. Add JavaScript functions (loadProcessingStatus, estimateBatch, startProcessing)
4. Add tab handler

**Step 1-4: Implement changes**
**Step 5: Commit**

---

## Phase 5: Integration & Testing

### Task 5.1: Install Required Python Package

**Step 1: Add anthropic to requirements**
**Step 2: Install in container**

---

### Task 5.2: Test Full Pipeline

**Step 1: Test embedding service health**
**Step 2: Test knowledge analyzer health**
**Step 3: Test semantic search**

---

### Task 5.3: Restart Platform and Verify

**Step 1: Copy template and restart**
**Step 2: Check logs for errors**
**Step 3: Test API endpoints**

---

### Task 5.4: Final Commit

Commit all Phase 82 changes with comprehensive message.

---

## Verification Checklist

After implementation, verify:

- [ ] pgvector extension installed
- [ ] nomic-embed-text model available in Ollama
- [ ] Embedding service health check passes
- [ ] Knowledge analyzer health check passes
- [ ] Semantic search returns results
- [ ] AI Processing tab visible in dashboard
- [ ] Backlog counters show correct numbers
- [ ] Cost estimate works
- [ ] Can process small batch (1-2 items)
- [ ] Knowledge cards created in database
- [ ] Markdown files exported to knowledge_cards/
- [ ] Relationships created in knowledge_relationships table

---

## File Summary

**New Files (9):**
- scripts/install_pgvector.sql
- scripts/phase82_schema_migration.sql
- ai_bridge/embedding_service.py
- ai_bridge/cost_controller.py
- ai_bridge/knowledge_analyzer.py
- ai_bridge/knowledge_cards.py
- ai_bridge/semantic_search.py
- ai_bridge/relationship_mapper.py
- platform_v2/tools/consciousness/processing_routes.py

**Modified Files (1):**
- platform_v2/templates/tools/consciousness_dashboard.html

---

*Plan created: 2026-02-06*
*Estimated implementation time: 8-12 hours*
*Ready for execution with superpowers:executing-plans*
