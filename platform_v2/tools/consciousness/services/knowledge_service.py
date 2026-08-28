"""Knowledge service — shared queries for knowledge_base table.

Owner: Consciousness module (38 endpoints)
Consumers: Dev HQ (6 endpoints — browse, module docs CRUD)

Import:
    from services.knowledge_service import get_knowledge_stats, search_knowledge
"""

import json
import logging

from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_knowledge_stats():
    """Return total entries and embedding coverage (excludes archived v1).
    Returns: {"total": int, "embedded": int, "coverage": float}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded
                FROM knowledge_base
                WHERE knowledge_type != 'archie_v1'
            """
            )
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
                where_clauses.append("(content ILIKE %s OR file_name ILIKE %s OR tags::text ILIKE %s)")
                params.extend(["%" + search + "%"] * 3)
            if knowledge_type:
                where_clauses.append("knowledge_type = %s")
                params.append(knowledge_type)
            if category:
                where_clauses.append("primary_category = %s")
                params.append(category)
            where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

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
                "SELECT DISTINCT primary_category FROM knowledge_base" " WHERE primary_category IS NOT NULL ORDER BY 1"
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
            cur.execute(
                """
                SELECT memory_metadata->>'module' as module,
                       memory_metadata->>'doc_type' as doc_type,
                       COUNT(*) as count
                FROM knowledge_base
                WHERE knowledge_type = 'vault_note'
                  AND memory_metadata->>'doc_type' IS NOT NULL
                  AND memory_metadata->>'module' IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 1, 2
            """
            )
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
                where_clauses.append("(content ILIKE %s OR file_name ILIKE %s OR title ILIKE %s)")
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
                sets.append("memory_metadata = COALESCE(memory_metadata, '{}'::jsonb) || %s::jsonb")
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
