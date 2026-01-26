# A.R.C.H.I.E. Knowledge Search

Search the platform's knowledge base and codebase efficiently.

## Arguments
$ARGUMENTS - Search query (e.g., "authentication", "database connection")

## Instructions

### 1. Search Knowledge Base First (Fastest)

Use MCP tool if available:
```
mcp: search_knowledge("$ARGUMENTS")
```

Or via API:
```bash
curl -s "http://localhost:3000/tools/consciousness/api/knowledge/search?q=$ARGUMENTS" | python3 -m json.tool
```

### 2. Search Codebase (Use Subagent)

For broad searches, delegate to Explore agent:
```
Task(subagent_type="Explore", prompt="Find where $ARGUMENTS is implemented")
```

### 3. Search Documentation

```bash
grep -r "$ARGUMENTS" /mnt/archie_brain/docs/ --include="*.md" -l
```

### 4. Search Database Schema

```sql
-- Run in database
SELECT table_name, column_name
FROM information_schema.columns
WHERE column_name ILIKE '%$ARGUMENTS%';
```

## Quick Lookups

| What | Command |
|------|---------|
| Module exists? | `ls /mnt/archie_brain/platform_v2/tools/ \| grep $ARGUMENTS` |
| Table exists? | `docker exec archie_database psql -U archie -d archie -c "\dt *$ARGUMENTS*"` |
| Doc exists? | `ls /mnt/archie_brain/docs/ \| grep -i $ARGUMENTS` |
| API endpoint? | `grep -r "$ARGUMENTS" /mnt/archie_brain/platform_v2/tools/*/routes.py` |

## Token-Efficient Search Order

1. MCP tools (cheapest)
2. API endpoints (fast, summarized)
3. Targeted grep (specific files)
4. Explore subagent (comprehensive but uses more tokens)
