---
name: archie-search
description: Search the A.R.C.H.I.E. knowledge base (25,989 entries, 99% embedded) with the right query idioms. Invoke when the user asks "have we seen this", "what did we decide about X", "any past mistakes on Y", or before building anything new. Always search before building — answers usually exist.
---

# A.R.C.H.I.E. Knowledge Base — Search Idioms

KB is the platform's long-term memory. Every past mistake, decision, vault note, and conversation is searchable.

## Stack

```
knowledge_base table (25,989+ rows, 99% with embeddings)
├── vault_note         — design docs, runbooks, roadmaps
├── mistake_learned    — past errors with prevention notes (1.3x weight)
├── conversation_memory — session summaries
├── code_snippet       — useful reference snippets
├── github_file        — ingested GitHub files
└── knowledge_card_*   — analysis-pipeline output
```

## Primary tool

```python
mcp__archie__search_knowledge(
    query="...",              # semantic + text — both weighted
    types=["mistake_learned"], # filter (optional, array)
    category="dispatch",      # further filter (optional)
    limit=10,                 # default 10, max 50
)
```

Returns ranked results with `relevance_score` (0-1). Score >0.5 is a solid match.

## Common queries — copy these

### Before building anything new
```python
search_knowledge(query="<what you're about to build>", limit=5)
search_knowledge(query="<topic>", types=["mistake_learned"], limit=5)
```

### Recalling past context on a project/topic
```python
mcp__archie__recall_context(topic="translation coverage")
```
Returns blended summary across memory types — faster than raw search for "what's been done on X".

### Check mistake history before risky action
```python
search_knowledge(
    query="<risky action — e.g. docker compose, VPS credentials, decommission agent>",
    types=["mistake_learned"],
    limit=5,
)
```

### Find architecture decisions
```python
search_knowledge(query="<topic> ADR decision", types=["vault_note"])
# OR query project_decisions table directly via mcp__archie__get_projects + decisions
```

### Find code references
```python
search_knowledge(query="ON CONFLICT translation_gaps", types=["code_snippet", "github_file"])
```

### Module capability deep-dive
```python
search_knowledge(category="module_capability")
# Returns all 36 module audits — see docs/generated/module-capability-index.md for the index
```

## Quick-search (summary only)

`mcp__archie__search_knowledge_brief` returns titles + 1-line summaries only. Use when listing candidates before drilling in.

## When semantic fails — fall back to SQL

Some queries don't embed well (exact error strings, specific filenames). For those:

```sql
SELECT id, title, knowledge_type, LEFT(content, 120) AS preview
FROM knowledge_base
WHERE content ILIKE '%exact_string%'
ORDER BY importance_score DESC NULLS LAST
LIMIT 10;
```

Run via `docker exec archie_database psql -U archie -d archie`.

## Interpreting results

- `relevance_score > 0.6` — strong match, read fully
- `0.4–0.6` — related but skim first
- `< 0.4` — probably noise, skip unless your query was vague
- `importance_score` on `mistake_learned` — prioritize 0.7+ over recent-but-trivial

## Write results back

If your search turns up nothing AND you solve a real problem, store the solution:

```python
mcp__archie__store_memory(
    memory_type="mistake_learned" OR "vault_note",
    title="...",
    content="...",
    category="<module or topic>",
    tags=["tag1", "tag2"],
    importance=0.8,  # 0.0-1.0
)
```

Next session finds it. See `/archie-patterns` for the write patterns.

## Rules

- **Search before building** — Rule #2 of the platform. Answer is almost always already there.
- **Don't rely on stale counts** — `25,989 entries` was snapshot at session start; use the tool for current number.
- **Don't trust one result** — get top 3-5 before assuming you understand. Multiple hits usually tell a fuller story than a single top match.
