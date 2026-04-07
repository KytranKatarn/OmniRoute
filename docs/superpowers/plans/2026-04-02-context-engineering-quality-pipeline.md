# Context Engineering — Quality-Gated Knowledge Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop junk from entering the knowledge base, score existing entries, and make search return relevant results by adding LLM-based quality scoring, tiered search rebalancing, and a periodic cleanup job.

**Architecture:** Add a `quality_score` column (0.0-1.0) to `knowledge_base`. New entries pass through an LLM quality gate before storage — entries scoring below 0.3 are rejected, 0.3-0.5 are flagged for review. Search ranking multiplies `similarity * type_weight * quality_score` so high-quality curated content always outranks auto-generated noise. A periodic agent loop job re-scores stale entries and archives dead weight.

**Tech Stack:** PostgreSQL (migration), Python (services), Ollama Bridge dispatch (LLM scoring), APScheduler (agent loop job)

**Project:** #215 — Context Engineering

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `database/migrations/XXX_quality_score.sql` | Add quality_score, review_status columns | Create |
| `platform_v2/services/quality_scoring_service.py` | LLM-based quality scoring logic | Create |
| `ai_bridge/knowledge_cards.py` | Gate new cards through quality scorer before save | Modify |
| `ai_bridge/consciousness_scheduler.py` | Gate conversation_memory entries | Modify |
| `platform_v2/mcp_server/tools/knowledge.py` | Integrate quality_score into search ranking | Modify |
| `platform_v2/tools/consciousness/memory_service.py` | Integrate quality_score into semantic search | Modify |
| `platform_v2/services/rag_service.py` | Filter low-quality from RAG context | Modify |
| `ai_bridge/agent_loop_jobs.py` | Add periodic quality review + cleanup job | Modify |
| `platform_v2/tools/consciousness/knowledge_routes.py` | Add quality distribution endpoint for dashboard | Modify |

---

### Task 1: Database Migration — Add Quality Columns

**Files:**
- Create: `database/migrations/160_knowledge_quality_score.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 160: Add quality scoring columns to knowledge_base
-- Supports Quality-Gated Knowledge Pipeline (Project #215)

-- Quality score: LLM-assessed content quality (0.0-1.0)
-- NULL = not yet scored, 0.0 = garbage, 1.0 = exceptional
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS quality_score NUMERIC(3,2) DEFAULT NULL;

-- Review status: tracks quality gate state
-- pending = awaiting first score, scored = has quality_score,
-- flagged = needs human review (0.3-0.5), rejected = below threshold
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending';

-- When the quality score was last computed
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS quality_scored_at TIMESTAMP DEFAULT NULL;

-- Index for efficient queries: find unscored, find flagged, sort by quality
CREATE INDEX IF NOT EXISTS idx_kb_quality_score ON knowledge_base(quality_score)
    WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_kb_review_status ON knowledge_base(review_status);
CREATE INDEX IF NOT EXISTS idx_kb_unscored ON knowledge_base(review_status)
    WHERE review_status = 'pending';

-- Composite index for search ranking: quality + importance together
CREATE INDEX IF NOT EXISTS idx_kb_quality_importance
    ON knowledge_base(quality_score DESC, importance_score DESC)
    WHERE quality_score IS NOT NULL;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/160_knowledge_quality_score.sql
```

Expected: `ALTER TABLE` + `CREATE INDEX` messages, no errors.

- [ ] **Step 3: Verify columns exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\d knowledge_base" | grep -E "quality_score|review_status|quality_scored_at"
```

Expected: Three new columns visible with correct types.

- [ ] **Step 4: Check current entry distribution**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT knowledge_type, COUNT(*) as cnt, COUNT(quality_score) as scored FROM knowledge_base WHERE knowledge_type NOT LIKE 'archie_v1%' GROUP BY knowledge_type ORDER BY cnt DESC;"
```

Expected: All `scored` counts = 0 (nothing scored yet). Note total counts per type for later verification.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/160_knowledge_quality_score.sql
git commit -m "feat(kb): add quality_score, review_status columns to knowledge_base — Project #215"
```

---

### Task 2: Quality Scoring Service — LLM-Based Scorer

**Files:**
- Create: `platform_v2/services/quality_scoring_service.py`

- [ ] **Step 1: Create the quality scoring service**

This service takes a knowledge_base entry and asks the local LLM to rate its quality on 4 dimensions: relevance (is this useful for platform development?), accuracy (is the information correct/current?), actionability (can someone act on this?), and uniqueness (does this add something not already in the KB?). Returns a 0.0-1.0 composite score.

```python
"""Quality Scoring Service — LLM-based knowledge entry quality assessment.

Scores knowledge_base entries on relevance, accuracy, actionability, uniqueness.
Used by: knowledge_cards.py (gate new entries), agent_loop (periodic re-scoring).

Import:
    from services.quality_scoring_service import score_entry, batch_score_entries
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Quality thresholds
QUALITY_REJECT = 0.3      # Below this: rejected outright
QUALITY_FLAG = 0.5         # Below this: flagged for review
QUALITY_ACCEPT = 0.5       # At or above: accepted

# Prompt for LLM quality assessment
QUALITY_PROMPT = """You are a knowledge base quality assessor for A.R.C.H.I.E., a software platform management system.

Rate this knowledge entry on 4 dimensions (each 0.0 to 1.0):

1. **Relevance** — Is this useful for platform development, operations, or decision-making? Generic filler scores 0.1. Specific platform knowledge scores 0.9.
2. **Accuracy** — Is the information correct, specific, and current? Vague summaries score 0.2. Precise facts with context score 0.9.
3. **Actionability** — Can someone act on this? "Code exists" scores 0.1. "Use function X in file Y for Z" scores 0.9.
4. **Uniqueness** — Does this add value beyond what's already obvious from reading the code? Restating file names scores 0.1. Explaining non-obvious patterns scores 0.9.

Entry to assess:
---
Type: {knowledge_type}
Title: {title}
Content: {content}
---

Respond with ONLY valid JSON (no markdown, no explanation):
{{"relevance": 0.X, "accuracy": 0.X, "actionability": 0.X, "uniqueness": 0.X, "reason": "one sentence"}}"""


def score_entry(
    entry_id: int,
    title: str,
    content: str,
    knowledge_type: str,
    save_to_db: bool = True,
) -> Optional[Dict[str, Any]]:
    """Score a single knowledge entry using LLM.

    Args:
        entry_id: knowledge_base.id
        title: Entry title
        content: Entry content (will be truncated to 2000 chars)
        knowledge_type: e.g. 'knowledge_card', 'conversation_memory'
        save_to_db: Whether to persist the score to DB

    Returns:
        Dict with quality_score, dimensions, reason, or None on failure.
    """
    from ai_bridge.bridge_dispatcher import get_dispatcher

    # Truncate content to avoid token overflow
    content_truncated = (content or "")[:2000]

    prompt = QUALITY_PROMPT.format(
        knowledge_type=knowledge_type,
        title=title or "(no title)",
        content=content_truncated,
    )

    try:
        dispatcher = get_dispatcher()
        result = dispatcher.dispatch_json(
            prompt=prompt,
            capability="classify",
            timeout=60,
        )

        if not result or not isinstance(result, dict):
            logger.warning("Quality scorer: empty or invalid LLM response for entry %d", entry_id)
            return None

        # Extract dimension scores
        relevance = float(result.get("relevance", 0))
        accuracy = float(result.get("accuracy", 0))
        actionability = float(result.get("actionability", 0))
        uniqueness = float(result.get("uniqueness", 0))
        reason = result.get("reason", "")

        # Composite score: weighted average
        # Relevance and actionability matter most for search utility
        quality_score = round(
            relevance * 0.30 + accuracy * 0.25 + actionability * 0.25 + uniqueness * 0.20,
            2,
        )

        # Determine review status
        if quality_score < QUALITY_REJECT:
            review_status = "rejected"
        elif quality_score < QUALITY_FLAG:
            review_status = "flagged"
        else:
            review_status = "scored"

        scoring_result = {
            "quality_score": quality_score,
            "review_status": review_status,
            "dimensions": {
                "relevance": relevance,
                "accuracy": accuracy,
                "actionability": actionability,
                "uniqueness": uniqueness,
            },
            "reason": reason,
        }

        if save_to_db:
            _persist_score(entry_id, quality_score, review_status, scoring_result)

        return scoring_result

    except Exception as e:
        logger.error("Quality scorer failed for entry %d: %s", entry_id, e)
        return None


def _persist_score(entry_id: int, quality_score: float, review_status: str, full_result: dict):
    """Save quality score to database."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE knowledge_base
                   SET quality_score = %s,
                       review_status = %s,
                       quality_scored_at = NOW(),
                       memory_metadata = COALESCE(memory_metadata, '{}'::jsonb) || %s::jsonb
                   WHERE id = %s""",
                (
                    quality_score,
                    review_status,
                    json.dumps({"quality_assessment": full_result}),
                    entry_id,
                ),
            )
    except Exception as e:
        logger.error("Failed to persist quality score for entry %d: %s", entry_id, e)


def batch_score_entries(
    batch_size: int = 20,
    target_types: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Score a batch of unscored entries. Returns counts by status.

    Args:
        batch_size: How many entries to score in this batch
        target_types: Optional list of knowledge_types to target (default: all)

    Returns:
        Dict with counts: {"scored": N, "flagged": N, "rejected": N, "failed": N}
    """
    counts = {"scored": 0, "flagged": 0, "rejected": 0, "failed": 0}

    try:
        with get_db_cursor() as (conn, cur):
            type_filter = ""
            params = [batch_size]
            if target_types:
                placeholders = ",".join(["%s"] * len(target_types))
                type_filter = f"AND knowledge_type IN ({placeholders})"
                params = list(target_types) + [batch_size]

            cur.execute(
                f"""SELECT id, title, content, knowledge_type
                    FROM knowledge_base
                    WHERE review_status = 'pending'
                    AND knowledge_type NOT LIKE 'archie_v1%%'
                    {type_filter}
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT %s""",
                params,
            )
            entries = cur.fetchall()
    except Exception as e:
        logger.error("Failed to fetch unscored entries: %s", e)
        return counts

    for entry in entries:
        result = score_entry(
            entry_id=entry["id"],
            title=entry["title"],
            content=entry["content"],
            knowledge_type=entry["knowledge_type"],
            save_to_db=True,
        )
        if result:
            counts[result["review_status"]] += 1
        else:
            counts["failed"] += 1

    logger.info(
        "Quality scoring batch: %d scored, %d flagged, %d rejected, %d failed",
        counts["scored"], counts["flagged"], counts["rejected"], counts["failed"],
    )
    return counts


def get_quality_stats() -> Dict[str, Any]:
    """Get quality score distribution stats for dashboard."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT
                    review_status,
                    COUNT(*) as cnt,
                    ROUND(AVG(quality_score)::numeric, 2) as avg_score
                FROM knowledge_base
                WHERE knowledge_type NOT LIKE 'archie_v1%%'
                GROUP BY review_status
                ORDER BY cnt DESC
            """)
            rows = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*) as total,
                    COUNT(quality_score) as scored_count
                FROM knowledge_base
                WHERE knowledge_type NOT LIKE 'archie_v1%%'
            """)
            totals = cur.fetchone()

            return {
                "total_entries": totals["total"],
                "scored_entries": totals["scored_count"],
                "coverage": round(totals["scored_count"] / max(totals["total"], 1) * 100, 1),
                "by_status": {r["review_status"]: {"count": r["cnt"], "avg_score": float(r["avg_score"] or 0)} for r in rows},
            }
    except Exception as e:
        logger.error("Failed to get quality stats: %s", e)
        return {}
```

- [ ] **Step 2: Verify the service loads without import errors**

```bash
docker exec archie_platform python3 -c "from services.quality_scoring_service import score_entry, batch_score_entries, get_quality_stats; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/quality_scoring_service.py
git commit -m "feat(kb): add LLM-based quality scoring service — Project #215"
```

---

### Task 3: Gate New Knowledge Cards Through Quality Scorer

**Files:**
- Modify: `ai_bridge/knowledge_cards.py:70-120` (save_knowledge_card function)

The goal: after a knowledge card is saved to DB, immediately score it. If it scores below QUALITY_REJECT (0.3), soft-delete it by setting `review_status = 'rejected'`. The card stays in DB but won't appear in search.

- [ ] **Step 1: Add quality scoring to save_knowledge_card**

In `ai_bridge/knowledge_cards.py`, find the `save_knowledge_card()` function. After the INSERT that saves the card and returns the `card_id`, add quality scoring:

```python
# At the top of the file, add import:
import threading
```

After the existing INSERT block that sets `card_id` (around line 130-140, after `card_id = cur.fetchone()[0]` or similar), add:

```python
        # Quality gate: score asynchronously to not block card creation
        if card_id:
            def _score_async(cid, t, c, kt):
                try:
                    from services.quality_scoring_service import score_entry
                    score_entry(cid, t, c, kt, save_to_db=True)
                except Exception as e:
                    logger.debug("Async quality scoring failed for card %d: %s", cid, e)

            threading.Thread(
                target=_score_async,
                args=(card_id, card.title, card.summary, f"knowledge_card_{card.card_type}"),
                daemon=True,
            ).start()
```

- [ ] **Step 2: Verify the modified file loads**

```bash
docker exec archie_platform python3 -c "from ai_bridge.knowledge_cards import save_knowledge_card; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/knowledge_cards.py
git commit -m "feat(kb): gate new knowledge cards through quality scorer — Project #215"
```

---

### Task 4: Gate Conversation Memory Through Quality Scorer

**Files:**
- Modify: `ai_bridge/consciousness_scheduler.py` (hourly_conversation_consolidation function, around line 201-249)

Same pattern as Task 3: after conversation_memory entries are inserted into knowledge_base, score them asynchronously.

- [ ] **Step 1: Add quality scoring to conversation consolidation**

In `consciousness_scheduler.py`, find the block where conversation_memory entries are INSERT'd into knowledge_base (around lines 201-249). After the insert and commit, add:

```python
        # Quality gate: score the new conversation memory entry
        if new_entry_id:  # the ID returned from INSERT
            def _score_conv(eid, t, c):
                try:
                    from services.quality_scoring_service import score_entry
                    score_entry(eid, t, c, "conversation_memory", save_to_db=True)
                except Exception as e:
                    logger.debug("Async quality scoring failed for conversation %d: %s", eid, e)

            import threading
            threading.Thread(
                target=_score_conv,
                args=(new_entry_id, title, content),
                daemon=True,
            ).start()
```

Note: The exact variable names (`new_entry_id`, `title`, `content`) depend on what the existing code uses — read the actual INSERT block to match the variable names of the returned ID and the title/content being inserted.

- [ ] **Step 2: Verify the modified file loads**

```bash
docker exec archie_platform python3 -c "from ai_bridge.consciousness_scheduler import ConsciousnessScheduler; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add ai_bridge/consciousness_scheduler.py
git commit -m "feat(kb): gate conversation memory through quality scorer — Project #215"
```

---

### Task 5: Integrate Quality Score Into MCP Search Ranking

**Files:**
- Modify: `platform_v2/mcp_server/tools/knowledge.py:87-112` (search_knowledge_handler)

Currently, search ranking is `similarity * type_weight`. We add `quality_score` as a third factor: `similarity * type_weight * quality_factor`. Entries with `quality_score IS NULL` (not yet scored) get a neutral factor of 0.7. Entries with `review_status = 'rejected'` are excluded entirely.

- [ ] **Step 1: Update the semantic search result formatting**

In `knowledge.py`, find the loop that formats semantic results (around line 96-112). Replace the scoring block:

Find this code (approximately lines 96-112):
```python
            formatted = []
            for r in semantic_results:
                kt = r.get("knowledge_type", "")
                weight = type_weights.get(kt, 0.8)
                sim = r.get("similarity", 0.5)
                formatted.append(
                    {
                        "id": r.get("id"),
                        "type": kt,
                        "title": r.get("title", ""),
                        "content": (r.get("content", "") or "")[:500],
                        "category": r.get("category"),
                        "tags": r.get("tags") or [],
                        "relevance_score": round(float(sim) * weight, 4),
                    }
                )
```

Replace with:
```python
            formatted = []
            for r in semantic_results:
                kt = r.get("knowledge_type", "")
                # Skip rejected entries
                if r.get("review_status") == "rejected":
                    continue
                weight = type_weights.get(kt, 0.8)
                # Match knowledge_card_* subtypes to base weight
                if kt.startswith("knowledge_card"):
                    weight = type_weights.get("knowledge_card", 1.1)
                sim = r.get("similarity", 0.5)
                # Quality factor: scored entries use their score, unscored get 0.7 (neutral)
                qs = r.get("quality_score")
                quality_factor = float(qs) if qs is not None else 0.7
                formatted.append(
                    {
                        "id": r.get("id"),
                        "type": kt,
                        "title": r.get("title", ""),
                        "content": (r.get("content", "") or "")[:500],
                        "category": r.get("category"),
                        "tags": r.get("tags") or [],
                        "relevance_score": round(float(sim) * weight * quality_factor, 4),
                        "quality_score": float(qs) if qs is not None else None,
                    }
                )
```

- [ ] **Step 2: Update the text search fallback (same file, ~line 145+)**

The text search fallback SQL also needs to exclude rejected entries. Find the WHERE clause in the text search query and add:

```sql
AND (review_status IS NULL OR review_status != 'rejected')
```

And include `quality_score` in the SELECT list so the same quality_factor logic can apply to text search results.

- [ ] **Step 3: Verify the MCP server loads**

```bash
docker exec archie_platform python3 -c "from mcp_server.tools.knowledge import search_knowledge_handler; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/mcp_server/tools/knowledge.py
git commit -m "feat(kb): integrate quality_score into MCP search ranking — Project #215"
```

---

### Task 6: Update Semantic Search to Return Quality Fields

**Files:**
- Modify: `platform_v2/tools/consciousness/memory_service.py:125-211` (semantic_search function)

The semantic_search function fetches rows with embeddings but doesn't currently SELECT `quality_score` or `review_status`. The MCP search handler (Task 5) needs these fields in the results.

- [ ] **Step 1: Update the SQL SELECT in semantic_search**

Find the SQL query in `semantic_search()` (around line 161-169) that fetches rows. Add `quality_score` and `review_status` to the SELECT list:

In the existing SELECT, add:
```sql
quality_score, review_status
```

Also add a WHERE filter to exclude rejected entries:
```sql
AND (review_status IS NULL OR review_status != 'rejected')
```

- [ ] **Step 2: Pass quality fields through in the result dicts**

In the result formatting (around line 190-200), ensure each result dict includes:
```python
"quality_score": row.get("quality_score"),
"review_status": row.get("review_status"),
```

- [ ] **Step 3: Verify the service loads**

```bash
docker exec archie_platform python3 -c "from tools.consciousness.memory_service import semantic_search; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/memory_service.py
git commit -m "feat(kb): include quality_score in semantic search results — Project #215"
```

---

### Task 7: Filter Low-Quality From RAG Context

**Files:**
- Modify: `platform_v2/services/rag_service.py:50-71` (get_rag_context function)

RAG context is injected into LLM prompts by the Bridge. Low-quality entries waste prompt tokens and can mislead the LLM.

- [ ] **Step 1: Add quality filter to get_rag_context**

In `rag_service.py`, modify the `get_rag_context()` function. After fetching results with `search_knowledge()`, filter out low-quality entries before building the context string:

Find:
```python
    results = search_knowledge(query, limit=5, knowledge_types=knowledge_types)
    if not results:
        return ""
```

Replace with:
```python
    results = search_knowledge(query, limit=8, knowledge_types=knowledge_types)
    # Filter out low-quality entries from RAG context (stricter than search)
    results = [
        r for r in results
        if r.get("quality_score") is None or r.get("quality_score", 0) >= 0.5
    ][:5]
    if not results:
        return ""
```

Note: We fetch 8 to have headroom after filtering, then cap at 5.

- [ ] **Step 2: Verify the service loads**

```bash
docker exec archie_platform python3 -c "from services.rag_service import get_rag_context; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/rag_service.py
git commit -m "feat(kb): filter low-quality entries from RAG context — Project #215"
```

---

### Task 8: Agent Loop Job — Periodic Quality Scoring

**Files:**
- Modify: `ai_bridge/agent_loop.py` (add new job registration)
- Create: `ai_bridge/services/quality_review_job.py` (job implementation)

Add agent loop job #59 (or next available): runs every 2 hours, scores 50 unscored entries per batch, prioritizing knowledge_card and conversation_memory types first.

- [ ] **Step 1: Create the job implementation**

```python
"""Quality Review Job — periodic LLM scoring of knowledge base entries.

Agent Loop Job: runs every 2 hours, scores 50 unscored entries per batch.
Prioritizes: knowledge_card_* and conversation_memory first, then github_file.

Import:
    from services.quality_review_job import run_quality_review
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def run_quality_review() -> Dict[str, Any]:
    """Score unscored knowledge entries in priority order.

    Priority: knowledge_card_* > conversation_memory > vault_note > github_file

    Returns:
        Dict with scoring results and stats.
    """
    try:
        from services.quality_scoring_service import batch_score_entries, get_quality_stats
    except ImportError as e:
        logger.error("Cannot import quality_scoring_service: %s", e)
        return {"success": False, "error": str(e)}

    results = {"success": True, "batches": []}

    # Phase 1: Score knowledge_cards first (highest noise ratio)
    batch1 = batch_score_entries(
        batch_size=25,
        target_types=None,  # Score all types, ordered by importance_score DESC
    )
    results["batches"].append({"phase": "general", **batch1})

    # Get updated stats
    stats = get_quality_stats()
    results["stats"] = stats

    total = sum(b.get("scored", 0) + b.get("flagged", 0) + b.get("rejected", 0) for b in results["batches"])
    logger.info(
        "Quality review complete: %d entries scored, coverage: %s%%",
        total, stats.get("coverage", "?"),
    )

    return results
```

- [ ] **Step 2: Register the job in agent_loop.py**

Find the job registration section in `agent_loop.py` (where other APScheduler jobs are added). Add:

```python
# Job #59: Knowledge Quality Review (every 2 hours)
try:
    from services.quality_review_job import run_quality_review
    scheduler.add_job(
        run_quality_review,
        'interval',
        hours=2,
        id='quality_review',
        name='Knowledge Quality Review',
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Job #59: Knowledge Quality Review registered (every 2h)")
except ImportError:
    logger.warning("Job #59: quality_review_job not available, skipping")
```

Note: Read the actual agent_loop.py to match the exact pattern used for job registration. The file uses a specific pattern — follow it exactly.

- [ ] **Step 3: Verify the job module loads**

```bash
docker exec archie_platform python3 -c "from services.quality_review_job import run_quality_review; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/services/quality_review_job.py ai_bridge/agent_loop.py
git commit -m "feat(kb): add periodic quality review agent loop job #59 — Project #215"
```

---

### Task 9: Backfill Existing Knowledge Cards

**Files:**
- No new files — uses `quality_scoring_service.batch_score_entries()` via one-off script

Score the existing ~3,500 knowledge_card entries. At 50/batch every 2 hours, this would take ~140 hours. Instead, run a one-time larger batch.

- [ ] **Step 1: Run initial backfill of knowledge_cards (largest noise source)**

```bash
docker exec archie_platform python3 -c "
from services.quality_scoring_service import batch_score_entries
# Score 200 knowledge_cards in one shot (takes ~10 min with local LLM)
result = batch_score_entries(batch_size=200, target_types=['knowledge_card_bug_fix', 'knowledge_card_feature', 'knowledge_card_refactor', 'knowledge_card_optimization', 'knowledge_card_pattern'])
print(result)
"
```

Expected: Dict showing counts of scored/flagged/rejected entries. Monitor for LLM timeouts.

- [ ] **Step 2: Check quality distribution after backfill**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT review_status, COUNT(*) as cnt, ROUND(AVG(quality_score)::numeric, 2) as avg
FROM knowledge_base
WHERE knowledge_type LIKE 'knowledge_card_%' AND quality_score IS NOT NULL
GROUP BY review_status ORDER BY cnt DESC;
"
```

Expected: Distribution across scored/flagged/rejected. If >50% are rejected, the knowledge_card generation prompt in knowledge_analyzer.py needs improvement (separate project).

- [ ] **Step 3: Run backfill for conversation_memory entries**

```bash
docker exec archie_platform python3 -c "
from services.quality_scoring_service import batch_score_entries
result = batch_score_entries(batch_size=100, target_types=['conversation_memory'])
print(result)
"
```

- [ ] **Step 4: Verify search quality improvement**

Test the same query that returned bad results before:

```bash
docker exec archie_platform python3 -c "
import asyncio
from mcp_server.tools.knowledge import search_knowledge_handler
result = asyncio.run(search_knowledge_handler({'query': 'context engineering memory retrieval', 'limit': 5}))
for r in result.get('results', []):
    print(f\"{r.get('relevance_score', 0):.3f} [{r.get('type')}] q={r.get('quality_score', '?')} {r.get('title', '')[:60]}\")
"
```

Expected: Results should be more relevant, with rejected junk entries excluded.

- [ ] **Step 5: No commit needed** — this is a data operation, not code.

---

### Task 10: Quality Dashboard Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/knowledge_routes.py`

Add an API endpoint so the Consciousness dashboard can show quality distribution.

- [ ] **Step 1: Add quality stats endpoint**

In `knowledge_routes.py`, find where routes are registered and add:

```python
@bp.route("/api/knowledge/quality-stats")
@admin_required
def knowledge_quality_stats():
    """Get quality score distribution for dashboard."""
    try:
        from services.quality_scoring_service import get_quality_stats
        stats = get_quality_stats()
        return jsonify({"success": True, **stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

Note: Follow the exact decorator and registration pattern used by other routes in this file. If it uses `register_knowledge_routes(bp, admin_required)`, add the route inside that function.

- [ ] **Step 2: Deploy and test**

```bash
docker compose restart archie_platform
```

Wait 30 seconds, then:

```bash
curl -s http://192.168.1.200:3000/tools/consciousness/api/knowledge/quality-stats -b "session=<admin_cookie>" | python3 -m json.tool
```

Expected: JSON with total_entries, scored_entries, coverage percentage, by_status breakdown.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/knowledge_routes.py
git commit -m "feat(kb): add quality stats API endpoint to Consciousness — Project #215"
```

---

### Task 11: Deploy, Verify End-to-End, Log Decision

- [ ] **Step 1: Deploy**

```bash
docker compose restart archie_platform
```

Wait 30 seconds for startup.

- [ ] **Step 2: Verify no import errors**

```bash
docker logs archie_platform 2>&1 | tail -80 | grep -i "error\|exception\|failed"
```

Expected: No new errors related to quality_scoring_service or quality_review_job.

- [ ] **Step 3: Verify agent loop job registered**

```bash
docker logs archie_platform 2>&1 | grep -i "quality"
```

Expected: Line showing "Job #59: Knowledge Quality Review registered"

- [ ] **Step 4: Test MCP search with quality ranking**

Use the ARCHIE MCP tool to search and verify quality_score appears in results:

```
mcp search_knowledge "bridge dispatcher migration"
```

Expected: Results include `quality_score` field. Rejected entries should not appear.

- [ ] **Step 5: Log architectural decision**

```
mcp log_decision "Quality-Gated Knowledge Pipeline: LLM-based scoring (4 dimensions: relevance, accuracy, actionability, uniqueness), entries below 0.3 rejected, 0.3-0.5 flagged. Search ranking: similarity * type_weight * quality_factor. Agent loop job #59 scores 25 entries/2h. Project #215."
```

- [ ] **Step 6: Update project status**

```
mcp update_project_understanding "Project #215 Context Engineering — Phase A+D complete: quality_score column, LLM scoring service, search rebalancing, agent loop job #59, backfill started"
```
