# Phase 3: Shared Service Layer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplicate SQL between Dev HQ and Consciousness by extracting shared queries into `platform_v2/services/`.

**Architecture:** Two thin Python service modules (`knowledge_service.py`, `project_service.py`) that encapsulate DB queries. Consumer modules import the service instead of writing inline SQL. Uses the existing `database.get_db_connection` context manager.

**Tech Stack:** Python, psycopg2, Flask (no new dependencies)

---

### Task 1: Create knowledge_service.py

**Files:**
- Create: `platform_v2/services/__init__.py`
- Create: `platform_v2/services/knowledge_service.py`

**Step 1: Create the services package**

```bash
mkdir -p /mnt/archie_brain/platform_v2/services
```

Create `platform_v2/services/__init__.py`:
```python
"""Shared service layer for cross-module database queries."""
```

**Step 2: Write knowledge_service.py**

This extracts the common knowledge_base queries that Dev HQ currently duplicates.
Key functions needed (based on Dev HQ's 6 consumer endpoints):

- `get_knowledge_stats()` — total count + embedding coverage (used by Dev HQ `api_overview`)
- `search_knowledge(search, category, knowledge_type, limit, offset)` — paginated browse with filters (used by Dev HQ `api_knowledge`)
- `get_categories()` — distinct category list (used by Dev HQ `api_knowledge`)
- `get_entry(entry_id)` — single entry by ID (used by Dev HQ `api_knowledge_detail` and `api_docs_detail`)
- `get_doc_modules()` — module doc counts grouped by doc_type (used by Dev HQ `api_docs_modules`)
- `search_docs(search, doc_type, module, limit, offset)` — paginated doc browse (used by Dev HQ `api_docs_list`)
- `create_doc(title, content, doc_type, category, module)` — insert vault_note (used by Dev HQ `api_docs_create`)
- `update_doc(doc_id, **fields)` — partial update (used by Dev HQ `api_docs_update`)
- `delete_entry(entry_id)` — delete by ID (used by Dev HQ `api_docs_delete`)

```python
"""Knowledge service — shared queries for knowledge_base table.

Owner: Consciousness module (38 endpoints)
Consumers: Dev HQ (6 endpoints — browse, module docs CRUD)

Import:
    from services.knowledge_service import get_knowledge_stats, search_knowledge
"""

import json
import logging

import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_knowledge_stats():
    """Return total entries and embedding coverage (excludes archived v1)."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                FROM knowledge_base
                WHERE knowledge_type != 'archie_v1'
            """)
            row = cur.fetchone()
            total = row["total"] if row else 0
            embedded = row["embedded"] if row else 0
            return {
                "total": total,
                "embedded": embedded,
                "coverage": round((embedded / total) * 100, 1) if total > 0 else 0,
            }
        finally:
            cur.close()


def search_knowledge(search="", category="", knowledge_type="", limit=50, offset=0):
    """Paginated knowledge browse with optional filters.

    Returns: {"entries": [...], "total": int, "categories": [...]}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            where_clauses = []
            params = []
            if search:
                where_clauses.append(
                    "(content ILIKE %s OR file_name ILIKE %s OR tags::text ILIKE %s)"
                )
                params.extend(["%" + search + "%"] * 3)
            if knowledge_type:
                where_clauses.append("knowledge_type = %s")
                params.append(knowledge_type)
            if category:
                where_clauses.append("primary_category = %s")
                params.append(category)
            where_sql = (
                (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
            )

            cur.execute(
                f"SELECT COUNT(*) as count FROM knowledge_base WHERE 1=1{where_sql}",
                params,
            )
            total = cur.fetchone()["count"]

            cur.execute(
                f"""SELECT id, file_name, file_path, primary_category,
                sub_category, tags, knowledge_type, importance_score,
                is_documentation, created_at, updated_at,
                LEFT(content, 300) as snippet
                FROM knowledge_base WHERE 1=1{where_sql}
                ORDER BY importance_score DESC, updated_at DESC
                LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            entries = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT DISTINCT primary_category FROM knowledge_base"
                " WHERE primary_category IS NOT NULL ORDER BY 1"
            )
            categories = [r["primary_category"] for r in cur.fetchall()]

            return {"entries": entries, "total": total, "categories": categories}
        finally:
            cur.close()


def get_entry(entry_id):
    """Fetch a single knowledge_base entry by ID. Returns dict or None."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM knowledge_base WHERE id = %s", (entry_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()


def get_doc_modules():
    """Return modules with documentation, grouped by doc_type.

    Returns: {"module_name": {"coder": N, "user": N}, ...}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT memory_metadata->>'module' as module,
                       memory_metadata->>'doc_type' as doc_type,
                       COUNT(*) as count
                FROM knowledge_base
                WHERE knowledge_type = 'vault_note'
                  AND memory_metadata->>'doc_type' IS NOT NULL
                  AND memory_metadata->>'module' IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 1, 2
            """)
            rows = cur.fetchall()
            modules = {}
            for row in rows:
                mod = row["module"]
                if mod not in modules:
                    modules[mod] = {"coder": 0, "user": 0}
                modules[mod][row["doc_type"]] = row["count"]
            return modules
        finally:
            cur.close()


def search_docs(search="", doc_type="", module="", limit=50, offset=0):
    """Paginated documentation browse with filters.

    Returns: {"entries": [...], "total": int}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            where_clauses = [
                "knowledge_type = 'vault_note'",
                "memory_metadata->>'doc_type' IS NOT NULL",
            ]
            params = []
            if search:
                where_clauses.append(
                    "(content ILIKE %s OR file_name ILIKE %s OR title ILIKE %s)"
                )
                params.extend(["%" + search + "%"] * 3)
            if doc_type == "user":
                where_clauses.append("memory_metadata->>'doc_type' = 'user'")
            elif doc_type == "coder":
                where_clauses.append("memory_metadata->>'doc_type' = 'coder'")
            if module:
                where_clauses.append("memory_metadata->>'module' = %s")
                params.append(module)
            where_sql = " AND ".join(where_clauses)

            cur.execute(
                f"SELECT COUNT(*) as count FROM knowledge_base WHERE {where_sql}",
                params,
            )
            total = cur.fetchone()["count"]

            cur.execute(
                f"""SELECT id, file_name, title, primary_category, sub_category,
                tags, knowledge_type, importance_score, memory_metadata,
                created_at, updated_at,
                LEFT(content, 200) as snippet
                FROM knowledge_base WHERE {where_sql}
                ORDER BY importance_score DESC, updated_at DESC
                LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            entries = [dict(r) for r in cur.fetchall()]

            return {"entries": entries, "total": total}
        finally:
            cur.close()


def create_doc(title, content, doc_type="coder", category="", module=""):
    """Create a documentation entry (vault_note). Returns new entry ID."""
    importance = 0.95 if doc_type == "coder" else 0.90
    meta_dict = {"doc_type": doc_type}
    if module:
        meta_dict["module"] = module
    metadata = json.dumps(meta_dict)

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO knowledge_base
                (content, file_name, knowledge_type, importance_score,
                 is_documentation, primary_category, title,
                 memory_metadata, created_at, updated_at)
                VALUES (%s, %s, 'vault_note', %s, true, %s, %s, %s::jsonb, NOW(), NOW())
                RETURNING id""",
                (content, title, importance, category, title, metadata),
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
            return new_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def update_doc(doc_id, **fields):
    """Update a documentation entry. Supports: content, title, category, doc_type, module.

    Returns: number of rows affected (0 = not found).
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            sets = []
            params = []
            if "content" in fields:
                sets.append("content = %s")
                params.append(fields["content"])
            if "title" in fields:
                sets.append("title = %s")
                params.append(fields["title"])
                sets.append("file_name = %s")
                params.append(fields["title"])
            if "category" in fields:
                sets.append("primary_category = %s")
                params.append(fields["category"])
            if "doc_type" in fields or "module" in fields:
                meta_update = {}
                if "doc_type" in fields:
                    meta_update["doc_type"] = fields["doc_type"]
                if "module" in fields:
                    meta_update["module"] = fields["module"]
                sets.append(
                    "memory_metadata = COALESCE(memory_metadata, '{}'::jsonb) || %s::jsonb"
                )
                params.append(json.dumps(meta_update))
            if not sets:
                return 0
            sets.append("updated_at = NOW()")
            params.append(doc_id)
            cur.execute(
                f"UPDATE knowledge_base SET {', '.join(sets)} WHERE id = %s",
                params,
            )
            conn.commit()
            return cur.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def delete_entry(entry_id):
    """Delete a knowledge_base entry by ID. Returns rows affected (0 = not found)."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("DELETE FROM knowledge_base WHERE id = %s", (entry_id,))
            conn.commit()
            return cur.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
```

**Step 3: Commit**

```bash
git add platform_v2/services/__init__.py platform_v2/services/knowledge_service.py
git commit -m "feat(services): add knowledge_service.py shared query layer"
```

---

### Task 2: Create project_service.py

**Files:**
- Create: `platform_v2/services/project_service.py`

**Step 1: Write project_service.py**

This extracts the project/task queries that Consciousness currently duplicates from Dev HQ's domain.
Key functions needed (based on Consciousness's 7 consumer queries):

- `get_project_stats()` — active/completed project counts (used by Consciousness `api_dashboard_summary`)
- `get_task_stats()` — in_progress/completed/total task counts (used by Consciousness `api_dashboard_summary`)
- `get_active_project_count()` — simple count (used by Consciousness `integration_health`)
- `get_recent_projects(limit)` — latest projects (used by Consciousness `api_devhq_summary`)
- `get_recent_decisions(limit)` — latest decisions (used by Consciousness `api_devhq_summary`)
- `get_recent_activity(limit)` — blended activity feed (used by Consciousness `api_dashboard_summary`)

```python
"""Project service — shared queries for unified_projects/tasks/decisions tables.

Owner: Dev HQ module (10+ CRUD endpoints)
Consumers: Consciousness (6 read-only queries — dashboard, integration health)

Import:
    from services.project_service import get_project_stats, get_recent_activity
"""

import logging

from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_project_stats():
    """Count active and completed projects.

    Returns: {"active": int, "completed": int}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT
                    count(*) FILTER (WHERE status = 'active') as active,
                    count(*) FILTER (WHERE status = 'completed') as completed
                FROM unified_projects
            """)
            row = cur.fetchone()
            return {
                "active": row["active"] if row else 0,
                "completed": row["completed"] if row else 0,
            }
        finally:
            cur.close()


def get_task_stats():
    """Count in_progress, completed, and total tasks.

    Returns: {"in_progress": int, "done": int, "total": int}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT
                    count(*) FILTER (WHERE status = 'in_progress') as in_progress,
                    count(*) FILTER (WHERE status = 'completed') as done,
                    count(*) as total
                FROM unified_tasks
            """)
            row = cur.fetchone()
            return {
                "in_progress": row["in_progress"] if row else 0,
                "done": row["done"] if row else 0,
                "total": row["total"] if row else 0,
            }
        finally:
            cur.close()


def get_active_project_count():
    """Return count of active projects (for health checks)."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT count(*) as cnt FROM unified_projects WHERE status = 'active'"
            )
            row = cur.fetchone()
            return row["cnt"] if row else 0
        finally:
            cur.close()


def get_recent_projects(limit=5):
    """Return most recent projects, ordered by created_at DESC.

    Returns: list of dicts with id, name, status, priority, created_at
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT id, name, status, priority, created_at
                FROM unified_projects ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()


def get_recent_decisions(limit=5):
    """Return most recent architectural decisions.

    Returns: list of dicts with title, decision, context, created_at
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT title, decision, context, created_at
                FROM project_decisions ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()


def get_recent_activity(limit=15):
    """Blended activity feed: knowledge + bridge + completed tasks.

    Returns: list of dicts with source, description, created_at, icon
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                (SELECT 'knowledge' as source,
                        COALESCE(NULLIF(title, ''), 'Untitled entry') as description,
                        created_at, 'book-open' as icon
                 FROM knowledge_base
                 WHERE knowledge_type != 'archie_v1'
                 ORDER BY created_at DESC LIMIT 5)
                UNION ALL
                (SELECT 'bridge' as source,
                        COALESCE(NULLIF(task_description, ''),
                                 'Bridge task #' || id) as description,
                        created_at, 'radio' as icon
                 FROM task_execution_log
                 ORDER BY created_at DESC LIMIT 5)
                UNION ALL
                (SELECT 'project' as source,
                        COALESCE(NULLIF(title, ''), 'Completed task') as description,
                        created_at, 'folder-kanban' as icon
                 FROM unified_tasks
                 WHERE status = 'completed'
                 ORDER BY created_at DESC LIMIT 5)
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
```

**Step 2: Commit**

```bash
git add platform_v2/services/project_service.py
git commit -m "feat(services): add project_service.py shared query layer"
```

---

### Task 3: Wire Dev HQ routes to knowledge_service

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

Replace inline knowledge_base SQL in these 9 route functions with calls to `knowledge_service`:

| Route Function | Lines | Service Call |
|---|---|---|
| `api_overview()` | 104-116 | `knowledge_service.get_knowledge_stats()` |
| `api_knowledge()` | 402-461 | `knowledge_service.search_knowledge(...)` |
| `api_knowledge_detail()` | 464-479 | `knowledge_service.get_entry(entry_id)` |
| `api_docs_modules()` | 801-833 | `knowledge_service.get_doc_modules()` |
| `api_docs_list()` | 836-892 | `knowledge_service.search_docs(...)` |
| `api_docs_detail()` | 895-911 | `knowledge_service.get_entry(doc_id)` |
| `api_docs_create()` | 914-952 | `knowledge_service.create_doc(...)` |
| `api_docs_update()` | 955-1004 | `knowledge_service.update_doc(...)` |
| `api_docs_delete()` | 1007-1024 | `knowledge_service.delete_entry(doc_id)` |

**Step 1: Add import**

Add to the imports section (around line 11):
```python
from services import knowledge_service
```

**Step 2: Replace api_overview knowledge stats (lines 104-116)**

Replace the inline `cur.execute(...)` + result parsing with:
```python
kb_stats = knowledge_service.get_knowledge_stats()
knowledge_count = kb_stats["total"]
embedding_coverage = kb_stats["coverage"]
```

**Step 3: Replace api_knowledge (lines 402-461)**

Replace entire function body with:
```python
def api_knowledge():
    search = request.args.get("search", "")
    category = request.args.get("category", "")
    knowledge_type = request.args.get("knowledge_type", "")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    try:
        result = knowledge_service.search_knowledge(
            search=search, category=category, knowledge_type=knowledge_type,
            limit=limit, offset=offset,
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 4: Replace api_knowledge_detail (lines 464-479)**

```python
def api_knowledge_detail(entry_id):
    try:
        entry = knowledge_service.get_entry(entry_id)
        if not entry:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True, "entry": entry})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 5: Replace api_docs_modules (lines 801-833)**

```python
def api_docs_modules():
    """Return list of modules that have documentation, with doc counts."""
    try:
        modules = knowledge_service.get_doc_modules()
        return jsonify({"success": True, "modules": modules})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 6: Replace api_docs_list (lines 836-892)**

```python
def api_docs_list():
    """List module documentation entries from knowledge_base."""
    search = request.args.get("search", "")
    doc_type = request.args.get("doc_type", "")
    module = request.args.get("module", "")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    try:
        result = knowledge_service.search_docs(
            search=search, doc_type=doc_type, module=module,
            limit=limit, offset=offset,
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 7: Replace api_docs_detail (lines 895-911)**

```python
def api_docs_detail(doc_id):
    """Get full content of a documentation entry."""
    try:
        entry = knowledge_service.get_entry(doc_id)
        if not entry:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True, "entry": entry})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 8: Replace api_docs_create (lines 914-952)**

```python
def api_docs_create():
    """Create a new documentation entry."""
    data = request.get_json()
    if not data or not data.get("content"):
        return jsonify({"success": False, "error": "Content is required"}), 400
    try:
        new_id = knowledge_service.create_doc(
            title=data.get("title", "Untitled Document"),
            content=data["content"],
            doc_type=data.get("doc_type", "coder"),
            category=data.get("category", ""),
            module=data.get("module", ""),
        )
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 9: Replace api_docs_update (lines 955-1004)**

```python
def api_docs_update(doc_id):
    """Update a documentation entry."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400
    try:
        fields = {}
        for key in ("content", "title", "category", "doc_type", "module"):
            if key in data:
                fields[key] = data[key]
        if not fields:
            return jsonify({"success": False, "error": "No valid fields"}), 400
        affected = knowledge_service.update_doc(doc_id, **fields)
        if affected == 0:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 10: Replace api_docs_delete (lines 1007-1024)**

```python
def api_docs_delete(doc_id):
    """Delete a documentation entry."""
    try:
        affected = knowledge_service.delete_entry(doc_id)
        if affected == 0:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 11: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "refactor(devhq): replace inline knowledge SQL with knowledge_service"
```

---

### Task 4: Wire Consciousness routes to project_service

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py` (lines 143-188)
- Modify: `platform_v2/tools/consciousness/integration_routes.py` (lines 43, 160-171)

Replace inline unified_projects/tasks/decisions SQL with calls to `project_service`:

| File | Function | Lines | Service Call |
|---|---|---|---|
| routes.py | `api_dashboard_summary()` | 143-149 | `project_service.get_project_stats()` |
| routes.py | `api_dashboard_summary()` | 154-161 | `project_service.get_task_stats()` |
| routes.py | `api_dashboard_summary()` | 166-188 | `project_service.get_recent_activity()` |
| integration_routes.py | `integration_health()` | 43 | `project_service.get_active_project_count()` |
| integration_routes.py | `api_devhq_summary()` | 160-164 | `project_service.get_recent_projects()` |
| integration_routes.py | `api_devhq_summary()` | 167-171 | `project_service.get_recent_decisions()` |

**Step 1: Add imports**

In `routes.py` imports section:
```python
from services import project_service
```

In `integration_routes.py` imports section:
```python
from services import project_service
```

**Step 2: Replace dashboard summary queries in routes.py**

In `api_dashboard_summary()`, replace the 3 inline queries (project stats, task stats, activity feed) with:
```python
proj_stats = project_service.get_project_stats()
task_stats = project_service.get_task_stats()
activity = project_service.get_recent_activity()
```

Keep the rest of the dashboard summary (agents, wellness, etc.) untouched.

**Step 3: Replace integration queries in integration_routes.py**

In `integration_health()`, replace `SELECT count(*) ... FROM unified_projects` with:
```python
active_count = project_service.get_active_project_count()
```

In `api_devhq_summary()`, replace both inline queries with:
```python
projects = project_service.get_recent_projects(5)
decisions = project_service.get_recent_decisions(5)
```

**Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/routes.py platform_v2/tools/consciousness/integration_routes.py
git commit -m "refactor(consciousness): replace inline project SQL with project_service"
```

---

### Task 5: Integration verification

**Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

Wait 15 seconds for startup.

**Step 2: Test Dev HQ knowledge endpoints**

```bash
# Overview (knowledge stats)
curl -s -b cookies.txt http://192.168.1.200:3000/dev-hq/api/overview | python3 -m json.tool | head -5

# Knowledge browse
curl -s -b cookies.txt 'http://192.168.1.200:3000/dev-hq/api/knowledge?limit=3' | python3 -m json.tool | head -10

# Knowledge detail
curl -s -b cookies.txt http://192.168.1.200:3000/dev-hq/api/knowledge/1 | python3 -m json.tool | head -5

# Doc modules
curl -s -b cookies.txt http://192.168.1.200:3000/dev-hq/api/docs/modules | python3 -m json.tool | head -10

# Doc list
curl -s -b cookies.txt 'http://192.168.1.200:3000/dev-hq/api/docs/list?limit=3' | python3 -m json.tool | head -10
```

All should return `"success": true`.

**Step 3: Test Consciousness endpoints**

```bash
# Dashboard summary (project stats, task stats, activity)
curl -s -b cookies.txt http://192.168.1.200:3000/consciousness/api/dashboard/summary | python3 -m json.tool | head -15

# Integration health
curl -s -b cookies.txt http://192.168.1.200:3000/consciousness/api/integration/health | python3 -m json.tool | head -10

# DevHQ summary
curl -s -b cookies.txt http://192.168.1.200:3000/consciousness/api/integration/devhq-summary | python3 -m json.tool | head -10
```

All should return `"success": true`.

**Step 4: Final commit and push**

```bash
git add -A
git commit -m "refactor(phase3): shared service layer for knowledge + project queries"
git push
```

**Step 5: Update Dev HQ**

- Complete tasks #707 and #708
- Log ADR for the shared service layer decision
- Update project understanding
