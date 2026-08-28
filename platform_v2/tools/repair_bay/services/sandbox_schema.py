"""
Schema-Based Sandbox Manager for A.R.C.H.I.E.
Creates isolated PostgreSQL schemas for low-risk code changes

Uses PostgreSQL schema separation to create lightweight sandboxes:
- Faster than Docker containers
- Lower resource usage
- Ideal for database-only changes or low-risk improvements
- Full data isolation within same database
"""

import os
from database import _get_db_password
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from typing import Dict, List
from datetime import datetime


class SchemaSandboxManager:
    """
    Manages PostgreSQL schema-based sandboxes for testing code changes.

    Workflow:
    1. Create/recreate 'sandbox' schema (single reusable sandbox)
    2. Clone tables from 'public' schema
    3. Apply code changes (database changes only)
    4. Run tests
    5. Drop schema when done or reuse for next proposal
    """

    def __init__(self):
        self.schema_prefix = "sandbox"  # Single sandbox schema name
        self.excluded_tables = [
            "spatial_ref_sys",  # PostGIS system table
            "geography_columns",
            "geometry_columns",
            "raster_columns",
            "raster_overviews",
        ]

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def create_schema(
        self,
        sandbox_id: int,
        proposal_id: int,
        clone_data: bool = True,
        tables_to_clone: List[str] = None,
    ) -> Dict:
        """
        Create a new sandbox schema.

        Args:
            sandbox_id: Unique sandbox ID
            proposal_id: Related improvement proposal ID
            clone_data: Whether to clone data (True) or just structure (False)
            tables_to_clone: Specific tables to clone (None = all tables)

        Returns:
            {
                'success': True,
                'schema_name': 'sandbox',
                'tables_cloned': 42,
                'rows_cloned': 15234,
                'created_at': '2026-01-01T...'
            }
        """
        # Always use 'sandbox' as the schema name (not sandbox_123, etc.)
        schema_name = "sandbox"

        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if schema already exists - if so, drop it first (single sandbox design)
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name = %s
            """,
                (schema_name,),
            )

            if cur.fetchone():
                print(f"🔄 Dropping existing {schema_name} schema to recreate it...")
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
                conn.commit()
                print(f"✅ Old {schema_name} schema dropped")

            # Create schema
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            conn.commit()

            # Get list of tables to clone
            if tables_to_clone:
                tables = tables_to_clone
            else:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """
                )
                tables = [row["table_name"] for row in cur.fetchall() if row["table_name"] not in self.excluded_tables]

            tables_cloned = 0
            total_rows = 0

            # Clone each table
            for table in tables:
                try:
                    if clone_data:
                        # Clone structure and data
                        cur.execute(
                            sql.SQL(
                                """
                            CREATE TABLE {}.{} AS
                            SELECT * FROM public.{}
                        """
                            ).format(
                                sql.Identifier(schema_name),
                                sql.Identifier(table),
                                sql.Identifier(table),
                            )
                        )
                    else:
                        # Clone structure only
                        cur.execute(
                            sql.SQL(
                                """
                            CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)
                        """
                            ).format(
                                sql.Identifier(schema_name),
                                sql.Identifier(table),
                                sql.Identifier(table),
                            )
                        )

                    # Get row count
                    cur.execute(
                        sql.SQL(
                            """
                        SELECT COUNT(*) as count FROM {}.{}
                    """
                        ).format(sql.Identifier(schema_name), sql.Identifier(table))
                    )
                    row_count = cur.fetchone()["count"]
                    total_rows += row_count

                    tables_cloned += 1
                    conn.commit()

                except Exception as table_error:
                    # Log error but continue with other tables
                    print(f"Warning: Failed to clone table {table}: {table_error}")
                    conn.rollback()

            # NOTE: We intentionally do NOT set a global search_path via ALTER DATABASE
            # because it would pollute all database connections. Each operation should
            # use qualified table names (schema.table) or session-level SET search_path.

            cur.close()
            conn.close()

            return {
                "success": True,
                "schema_name": schema_name,
                "tables_cloned": tables_cloned,
                "rows_cloned": total_rows,
                "created_at": datetime.now().isoformat(),
            }

        except Exception as e:
            # Cleanup on error
            try:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
                conn.commit()
            except Exception:
                pass

            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def destroy_schema(self, schema_name: str = None, sandbox_id: int = None) -> Dict:
        """
        Destroy a sandbox schema and cleanup resources.

        Args:
            schema_name: Schema name
            sandbox_id: Sandbox ID (will derive schema name)

        Returns:
            {
                'success': True,
                'destroyed_at': '2026-01-01T...'
            }
        """
        if sandbox_id and not schema_name:
            schema_name = f"{self.schema_prefix}{sandbox_id}"

        if not schema_name:
            return {"success": False, "error": "Must provide schema_name or sandbox_id"}

        conn = self.get_db()
        cur = conn.cursor()

        try:
            # Drop schema with CASCADE to remove all objects
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
            conn.commit()

            cur.close()
            conn.close()

            return {
                "success": True,
                "schema_name": schema_name,
                "destroyed_at": datetime.now().isoformat(),
            }

        except Exception as e:
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def execute_query(self, schema_name: str, query: str, params: tuple = None, fetch: bool = True) -> Dict:
        """
        Execute a query in the sandbox schema.

        Args:
            schema_name: Sandbox schema name
            query: SQL query to execute
            params: Query parameters
            fetch: Whether to fetch and return results

        Returns:
            {
                'success': True,
                'rows': [...],  # if fetch=True
                'rowcount': 5
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Set search_path to sandbox schema
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))

            # Execute query
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)

            rowcount = cur.rowcount

            if fetch and cur.description:
                rows = [dict(row) for row in cur.fetchall()]
            else:
                rows = []

            conn.commit()
            cur.close()
            conn.close()

            return {"success": True, "rows": rows, "rowcount": rowcount}

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def clone_table(
        self,
        schema_name: str,
        table_name: str,
        source_schema: str = "public",
        clone_data: bool = True,
    ) -> Dict:
        """
        Clone a single table into the sandbox schema.

        Useful for selective cloning after sandbox creation.

        Args:
            schema_name: Target sandbox schema
            table_name: Table to clone
            source_schema: Source schema (default: 'public')
            clone_data: Clone data or just structure

        Returns:
            {
                'success': True,
                'rows_cloned': 123
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            if clone_data:
                # Clone with data
                cur.execute(
                    sql.SQL(
                        """
                    CREATE TABLE {}.{} AS
                    SELECT * FROM {}.{}
                """
                    ).format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                        sql.Identifier(source_schema),
                        sql.Identifier(table_name),
                    )
                )
            else:
                # Clone structure only
                cur.execute(
                    sql.SQL(
                        """
                    CREATE TABLE {}.{} (LIKE {}.{} INCLUDING ALL)
                """
                    ).format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                        sql.Identifier(source_schema),
                        sql.Identifier(table_name),
                    )
                )

            # Get row count
            cur.execute(
                sql.SQL(
                    """
                SELECT COUNT(*) as count FROM {}.{}
            """
                ).format(sql.Identifier(schema_name), sql.Identifier(table_name))
            )
            row_count = cur.fetchone()["count"]

            conn.commit()
            cur.close()
            conn.close()

            return {"success": True, "rows_cloned": row_count}

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def compare_schemas(self, schema1: str, schema2: str = "public") -> Dict:
        """
        Compare sandbox schema with production schema.

        Returns differences in table structure and row counts.

        Args:
            schema1: Sandbox schema name
            schema2: Schema to compare against (default: 'public')

        Returns:
            {
                'success': True,
                'tables_only_in_schema1': [...],
                'tables_only_in_schema2': [...],
                'row_count_differences': {...}
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get tables in schema1
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                AND table_type = 'BASE TABLE'
            """,
                (schema1,),
            )
            tables1 = set(row["table_name"] for row in cur.fetchall())

            # Get tables in schema2
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                AND table_type = 'BASE TABLE'
            """,
                (schema2,),
            )
            tables2 = set(row["table_name"] for row in cur.fetchall())

            # Find differences
            only_in_1 = list(tables1 - tables2)
            only_in_2 = list(tables2 - tables1)
            common = tables1 & tables2

            # Compare row counts for common tables
            row_count_diffs = {}
            for table in common:
                cur.execute(
                    sql.SQL(
                        """
                    SELECT
                        (SELECT COUNT(*) FROM {}.{}) as count1,
                        (SELECT COUNT(*) FROM {}.{}) as count2
                """
                    ).format(
                        sql.Identifier(schema1),
                        sql.Identifier(table),
                        sql.Identifier(schema2),
                        sql.Identifier(table),
                    )
                )
                counts = cur.fetchone()
                if counts["count1"] != counts["count2"]:
                    row_count_diffs[table] = {
                        schema1: counts["count1"],
                        schema2: counts["count2"],
                        "diff": counts["count1"] - counts["count2"],
                    }

            cur.close()
            conn.close()

            return {
                "success": True,
                "tables_only_in_schema1": only_in_1,
                "tables_only_in_schema2": only_in_2,
                "row_count_differences": row_count_diffs,
                "common_tables": len(common),
            }

        except Exception as e:
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def get_schema_size(self, schema_name: str) -> Dict:
        """
        Get the disk size of a sandbox schema.

        Returns:
            {
                'success': True,
                'schema_name': 'sandbox_123',
                'size_bytes': 1234567,
                'size_mb': 1.18,
                'table_count': 42
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get total size
            cur.execute(
                """
                SELECT
                    pg_size_pretty(SUM(pg_total_relation_size(schemaname||'.'||tablename))::bigint) as size_pretty,
                    SUM(pg_total_relation_size(schemaname||'.'||tablename))::bigint as size_bytes,
                    COUNT(*) as table_count
                FROM pg_tables
                WHERE schemaname = %s
            """,
                (schema_name,),
            )

            result = cur.fetchone()
            cur.close()
            conn.close()

            if result:
                size_bytes = result["size_bytes"] or 0
                return {
                    "success": True,
                    "schema_name": schema_name,
                    "size_bytes": size_bytes,
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "size_pretty": result["size_pretty"],
                    "table_count": result["table_count"],
                }
            else:
                return {"success": False, "error": f"Schema {schema_name} not found"}

        except Exception as e:
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def create_schema_sandbox(sandbox_id: int, proposal_id: int) -> Dict:
    """Quick function to create schema sandbox"""
    manager = SchemaSandboxManager()
    return manager.create_schema(sandbox_id, proposal_id)


def destroy_schema_sandbox(sandbox_id: int) -> Dict:
    """Quick function to destroy schema sandbox"""
    manager = SchemaSandboxManager()
    return manager.destroy_schema(sandbox_id=sandbox_id)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Schema Sandbox Manager - Test Mode")
    print("=" * 60)

    manager = SchemaSandboxManager()

    # Test 1: Check database connectivity
    print("\n1. DATABASE CONNECTIVITY:")
    print("-" * 60)
    try:
        conn = manager.get_db()
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        print(f"✓ Connected to PostgreSQL")
        print(f"  Version: {version[:50]}...")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"✗ Database connection failed: {e}")

    print("\n✅ Schema Sandbox Manager loaded successfully!")
