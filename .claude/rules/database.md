---
globs: ["database/**", "platform_v2/database.py", "platform_v2/services/**"]
---

# Database Rules

## Connection
- Host: `192.168.1.200` (from outside Docker) or `archie_database` (container name)
- Docker: `docker exec -it archie_database psql -U archie -d archie`
- Python: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`

## Common Table Gotchas
- `unified_projects.name` (NOT `title`)
- `unified_tasks.priority` is INTEGER
- `unified_projects.slug` is NOT NULL
- `project_decisions.decision`/`context` (NOT `description`/`rationale`)
- `telegram_users` (NOT `telegram_linked_accounts`)
- `system_notifications` CHECK: info/warning/error/success/reminder/alert/briefing only
- JSONB fields need `psycopg2.Json()` wrapper

## Services Layer (ADR-075)
- `services/knowledge_service.py` (9 funcs) — owns knowledge_base
- `services/project_service.py` (6 funcs) — owns projects/tasks
- Data ownership: knowledge_base -> Consciousness, projects/tasks -> Dev HQ

## Migrations
- Path: `database/migrations/NNN_description.sql`
- Run: `docker exec archie_database psql -U archie -d archie -f /path/to/migration.sql`
- Always idempotent (ON CONFLICT DO UPDATE or IF NOT EXISTS)

### ⚠️ The command above is for PLATFORM migrations ONLY (2026-10-02)

**This does not apply to every product's migrations.** What The Fact ships its
own Postgres on a **different host**, and its table names overlap with the
platform's (`parliament.*`, `wtf.*`), so targeting the wrong database does not
error — it writes to a database nothing serves from, and reports success.

Measured 2026-10-02: WTF migrations 085–087 were applied to the hub's local `wtf`
database before anyone established that WTF runs on Citadel. The hub has a
database named `wtf` with real data (4,156 `election_candidates`) and **no WTF
workload on it** — nothing errors, nothing shows up, and it has to be reverted by
hand. Read `what-the-fact/migrations/README.md` before touching any `what-the-fact`
migration; it carries the Citadel host, container, and credentials.

Other products with their own datastore (KBS, C.R.E.D.) have the same hazard —
confirm the target host before running DDL, not just the target schema.

## ⚠️ Query traps — an EMPTY result is not a PASS (2026-07-28, KB #285009)

These cost three wrong conclusions in a single session. All the same shape: a query
that FAILED looked identical to a query that found nothing.

**`psql` writes errors to STDERR.** With `-tAc` (and any pipeline that drops stderr)
a bad column name prints *nothing* and reads as "no rows".

```bash
# ❌ an error here is INVISIBLE — looks like an empty table
docker exec archie_database psql -U archie -d archie -tAc "SELECT ..." | sed 's/^/  /'

# ✅ always merge stderr, and prove a write happened
docker exec archie_database psql -U archie -d archie -c "UPDATE ... RETURNING id, status;" 2>&1
```

- **An UPDATE is verified by `RETURNING` + a follow-up SELECT** — never by the absence
  of output. `UPDATE ... SET result = ...` failed silently for minutes because the
  column is `execution_result`; the rows were untouched while the run looked clean.
- **String concat with a NULL yields NULL**, so `SELECT a||' '||b` returns an empty
  line when any column is NULL. Use `COALESCE(col,'-')` in concatenated output, or
  just use `-c` table mode.
- **Long SQL through the shell**: embedded `"` / backticks get mangled by shell
  expansion (this silently truncated an UPDATE mid-statement). Pipe a quoted heredoc
  to `docker exec -i ... psql` instead of passing `-c "..."`, and use `$TAG$…$TAG$`
  dollar-quoting for prose containing quotes.

**Same shape in code, not just SQL**: a regex that matches NOTHING yields `False`,
which is exactly what a passing check prints. Assert the search MATCHED before
trusting its boolean — prefer `grep -n` output you can read over a derived predicate.

## `agents` table gotchas (2026-07-28)

- **Names are DOTTED.** `ILIKE '%HAVEN%'` does **not** match `H.A.V.E.N.` — use
  `replace(name,'.','') ILIKE '%HAVEN%'`. (Same root as the `propose_hire`
  duplicate-name bug, task #5272.)
- **There is no `is_active` column** — use `shift_state` (`active` / `barracked` /
  `deployed` / …). **There is no `model_preference` column** either. Both were
  guessed in a query and produced the silent-stderr failure above.
- `unified_tasks` has **no `work_notes` column** — long-form notes go in
  `description`. `autonomy_approval_queue` uses **`execution_result`**, not `result`.
