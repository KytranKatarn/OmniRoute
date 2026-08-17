"""Platform Intelligence Service — system introspection for Consciousness.

Relocated from tools/blueprint/blueprint_intelligence.py (Decision #431).
Provides DB schema, API endpoint listing, and system health.
Used by Dev HQ (schema/endpoints tabs) and System Operations (health).
"""

import logging
import subprocess
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional

import psutil
from database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ======================
# CACHING SYSTEM
# ======================

_cache = {}
_cache_lock = threading.Lock()

CACHE_TTL = {
    "schema": 300,  # 5 minutes
    "health": 60,  # 1 minute
}


def get_cached(key: str, ttl_key: str = None) -> Optional[Dict]:
    """Get cached value if not expired."""
    with _cache_lock:
        if key in _cache:
            cached_time, data = _cache[key]
            ttl = CACHE_TTL.get(ttl_key or key, 60)
            if time.time() - cached_time < ttl:
                return data
    return None


def set_cached(key: str, data: Dict) -> None:
    """Store value in cache."""
    with _cache_lock:
        _cache[key] = (time.time(), data)


# ======================
# DATABASE SCHEMA
# ======================


def get_database_schema() -> Dict[str, Any]:
    """Get comprehensive database schema information."""
    cached = get_cached("schema")
    if cached:
        return cached

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        )
        tables_raw = cur.fetchall()

        # Row counts: ONE planner-estimate query over pg_class.reltuples instead
        # of a COUNT(*) per table. The per-table COUNT(*) loop scanned all ~827
        # tables per request and hung the endpoint long before the cache could
        # populate (Dev HQ task #5705). reltuples is an estimate (refreshed by
        # VACUUM/ANALYZE) — the payload labels it via row_counts_estimated.
        cur.execute(
            """
            SELECT c.relname AS table_name,
                   GREATEST(c.reltuples::bigint, 0) AS est_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """
        )
        row_estimates = {r["table_name"]: r["est_rows"] for r in cur.fetchall()}

        tables = []
        total_rows = 0

        # Batch the per-table metadata into FOUR set-returning queries instead of
        # four queries PER table (~3,300 round-trips across ~827 tables) — the
        # remaining half of the #5705 hang after the COUNT(*) loop was replaced
        # with the reltuples estimate above.
        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable,
                   column_default, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """
        )
        columns_by_table = {}
        for c in cur.fetchall():
            row = dict(c)
            columns_by_table.setdefault(row.pop("table_name"), []).append(row)

        cur.execute(
            """
            SELECT c.relname AS table_name, a.attname AS column_name
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                 AND a.attnum = ANY(i.indkey)
            WHERE n.nspname = 'public' AND i.indisprimary
        """
        )
        pks_by_table = {}
        for r in cur.fetchall():
            pks_by_table.setdefault(r["table_name"], []).append(r["column_name"])

        # #5708: pg_catalog-native FK query. The information_schema 3-way join
        # (table_constraints × key_column_usage × constraint_column_usage) was
        # measured at 42.1s schema-wide — 84% of the endpoint's ~50s — while
        # this pg_constraint form answers in ~27ms. The WITH ORDINALITY pairing
        # also fixes a correctness bug: constraint_column_usage cross-products
        # the columns of a multi-column FK; conkey/confkey pair them by position.
        cur.execute(
            """
            SELECT rel.relname AS table_name,
                   att.attname AS column_name,
                   frel.relname AS foreign_table,
                   fatt.attname AS foreign_column
            FROM pg_constraint con
            JOIN pg_class rel  ON rel.oid  = con.conrelid
            JOIN pg_class frel ON frel.oid = con.confrelid
            JOIN LATERAL unnest(con.conkey)  WITH ORDINALITY AS ck(attnum, ord) ON TRUE
            JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = ck.ord
            JOIN pg_attribute att  ON att.attrelid  = con.conrelid  AND att.attnum  = ck.attnum
            JOIN pg_attribute fatt ON fatt.attrelid = con.confrelid AND fatt.attnum = fk.attnum
            WHERE con.contype = 'f' AND rel.relnamespace = 'public'::regnamespace
        """
        )
        fks_by_table = {}
        for fk in cur.fetchall():
            row = dict(fk)
            fks_by_table.setdefault(row.pop("table_name"), []).append(row)

        cur.execute(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes WHERE schemaname = 'public'
        """
        )
        idx_by_table = {}
        for i in cur.fetchall():
            row = dict(i)
            idx_by_table.setdefault(row.pop("tablename"), []).append(row)

        for t in tables_raw:
            table_name = t["table_name"]
            columns = columns_by_table.get(table_name, [])

            # Planner estimate (see the pg_class query above) — NOT an exact
            # COUNT(*). Views/foreign tables not in pg_class relkind r/p -> 0.
            row_count = int(row_estimates.get(table_name, 0))
            total_rows += row_count

            tables.append(
                {
                    "name": table_name,
                    "type": t["table_type"],
                    "row_count": row_count,
                    "columns": columns,
                    "column_count": len(columns),
                    "primary_keys": pks_by_table.get(table_name, []),
                    "foreign_keys": fks_by_table.get(table_name, []),
                    "indexes": idx_by_table.get(table_name, []),
                }
            )

        cur.execute(
            """
            SELECT table_name as view_name, view_definition
            FROM information_schema.views
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        )
        views = [dict(v) for v in cur.fetchall()]

        cur.execute(
            """
            SELECT routine_name, routine_type, data_type as return_type
            FROM information_schema.routines
            WHERE routine_schema = 'public'
            ORDER BY routine_name
        """
        )
        functions = [dict(f) for f in cur.fetchall()]

        cur.execute(
            """
            SELECT trigger_name, event_manipulation as event,
                   event_object_table as table_name, action_timing as timing
            FROM information_schema.triggers
            WHERE trigger_schema = 'public'
            ORDER BY trigger_name
        """
        )
        triggers = [dict(t) for t in cur.fetchall()]

        result = {
            "success": True,
            "tables": tables,
            "views": views,
            "functions": functions,
            "triggers": triggers,
            "summary": {
                "total_tables": len(tables),
                "total_views": len(views),
                "total_functions": len(functions),
                "total_triggers": len(triggers),
                "total_rows": total_rows,
                # Row counts come from pg_class.reltuples planner estimates,
                # not COUNT(*) — see get_database_schema() (#5705).
                "row_counts_estimated": True,
            },
        }
        set_cached("schema", result)
        return result
    except Exception as e:
        logger.error(f"Error getting schema: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ======================
# API ENDPOINTS
# ======================


def get_api_endpoints() -> Dict[str, Any]:
    """Get all registered API endpoints from Flask app."""
    try:
        from flask import current_app

        endpoints = []

        for rule in current_app.url_map.iter_rules():
            if "static" in rule.endpoint:
                continue

            methods = [m for m in rule.methods if m not in ["HEAD", "OPTIONS"]]
            parts = rule.endpoint.split(".")
            category = parts[0] if len(parts) > 1 else "core"

            view_func = current_app.view_functions.get(rule.endpoint)
            docstring = view_func.__doc__ if view_func and view_func.__doc__ else None

            endpoints.append(
                {
                    "endpoint": rule.endpoint,
                    "path": str(rule),
                    "methods": methods,
                    "category": category,
                    "description": (docstring.strip().split("\n")[0] if docstring else None),
                    "has_args": bool(rule.arguments),
                }
            )

        endpoints.sort(key=lambda x: x["path"])

        categories = {}
        for ep in endpoints:
            cat = ep["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(ep)

        return {
            "success": True,
            "endpoints": endpoints,
            "categories": categories,
            "total": len(endpoints),
        }
    except Exception as e:
        logger.error(f"Error getting endpoints: {e}")
        return {"success": False, "error": str(e)}


# ======================
# SYSTEM HEALTH
# ======================


def get_system_health() -> Dict[str, Any]:
    """Get comprehensive system health information."""
    cached = get_cached("health")
    if cached:
        return cached

    health = {
        "success": True,
        "timestamp": datetime.now().isoformat(),
        "system": {},
        "docker": {},
        "database": {},
        "services": [],
    }

    try:
        health["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory": {
                "total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
                "percent": psutil.virtual_memory().percent,
            },
            "disk": {
                "total_gb": round(psutil.disk_usage("/").total / (1024**3), 2),
                "used_gb": round(psutil.disk_usage("/").used / (1024**3), 2),
                "percent": psutil.disk_usage("/").percent,
            },
            "uptime_hours": round(
                (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds() / 3600,
                1,
            ),
        }
    except Exception as e:
        health["system"] = {"error": str(e)}

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Image}}|{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            containers = []
            for line in result.stdout.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 4:
                        containers.append(
                            {
                                "name": parts[0],
                                "status": parts[1],
                                "image": parts[2],
                                "ports": parts[3],
                                "healthy": "Up" in parts[1],
                            }
                        )
            health["docker"] = {
                "containers": containers,
                "total": len(containers),
                "healthy": len([c for c in containers if c["healthy"]]),
            }
    except Exception as e:
        health["docker"] = {"error": str(e)}

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT count(*) FROM pg_stat_activity")
        conn_count = cur.fetchone()["count"]
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
        db_size = cur.fetchone()["size"]
        cur.execute("SELECT pg_postmaster_start_time()")
        start_time = cur.fetchone()["pg_postmaster_start_time"]

        health["database"] = {
            "connected": True,
            "connections": conn_count,
            "size": db_size,
            "uptime_hours": (
                round(
                    (datetime.now(start_time.tzinfo) - start_time).total_seconds() / 3600,
                    1,
                )
                if start_time
                else None
            ),
        }
    except Exception as e:
        health["database"] = {"connected": False, "error": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    import requests

    services = [
        {"name": "Platform", "endpoint": "http://localhost:3000/api/health"},
        {"name": "Ollama", "endpoint": "http://localhost:11434/api/tags"},
    ]

    for svc in services:
        try:
            resp = requests.get(svc["endpoint"], timeout=5)
            health["services"].append(
                {
                    "name": svc["name"],
                    "status": "healthy" if resp.status_code == 200 else "unhealthy",
                    "response_time_ms": int(resp.elapsed.total_seconds() * 1000),
                }
            )
        except Exception as e:
            health["services"].append({"name": svc["name"], "status": "unreachable", "error": str(e)})

    set_cached("health", health)
    return health
