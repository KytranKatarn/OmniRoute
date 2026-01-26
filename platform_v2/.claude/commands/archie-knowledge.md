# Query A.R.C.H.I.E. Knowledge Base

Search the unified knowledge base for relevant information.

## Arguments
$ARGUMENTS - The search query (e.g., "database connection", "blueprint module", "error handling")

## Instructions

1. Query the knowledge base via API:
   ```bash
   curl -s "http://localhost:3000/tools/consciousness/api/knowledge/search?q=$ARGUMENTS&limit=10"
   ```

2. If API fails, query directly via Docker:
   ```bash
   docker exec archie_platform python3 -c "
   from unified_knowledge_search import unified_knowledge_search
   import json
   results = unified_knowledge_search('$ARGUMENTS', limit=10)
   print(json.dumps(results, indent=2, default=str))
   "
   ```

3. Present the results showing:
   - Title/content snippet
   - Type (vault_note, mistake_learned, etc.)
   - Relevance score
   - Source reference

This searches across all 2,490+ knowledge entries including docs, mistakes learned, and conversation memory.
