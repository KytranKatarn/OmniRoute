"""Blueprint Intelligence Hub - Central data aggregation for A.R.C.H.I.E.

Provides comprehensive platform intelligence including:
- Database schema introspection
- API endpoint documentation
- System health monitoring
- Dependency tracking
- Backup status
- Agent directory
- Knowledge base integration
- Snapshot comparison
"""

import os
import sys
import json
import logging
import subprocess
import psutil
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ======================
# CACHING SYSTEM
# ======================
# Cache slow operations to improve Blueprint page load time

_cache = {}
_cache_lock = threading.Lock()

# Cache TTL in seconds
CACHE_TTL = {
    "schema": 300,  # 5 minutes - DB schema rarely changes
    "dependencies": 3600,  # 1 hour - pip packages rarely change
    "health": 60,  # 1 minute - health can change frequently
}


def get_cached(key: str, ttl_key: str = None) -> Optional[Dict]:
    """Get cached value if not expired."""
    with _cache_lock:
        if key in _cache:
            cached_time, data = _cache[key]
            ttl = CACHE_TTL.get(ttl_key or key, 60)
            if time.time() - cached_time < ttl:
                logger.info(f"[Cache HIT] {key} (age: {int(time.time() - cached_time)}s)")
                return data
            logger.info(f"[Cache EXPIRED] {key}")
    return None


def set_cached(key: str, data: Dict) -> None:
    """Store value in cache."""
    with _cache_lock:
        _cache[key] = (time.time(), data)
        logger.info(f"[Cache SET] {key}")


# Platform paths
# Note: Inside Docker, /mnt/archie_brain has docs/ai_bridge, /app has platform_v2 code
PLATFORM_ROOT = "/mnt/archie_brain"
APP_ROOT = "/app"  # platform_v2 code inside Docker
PLATFORM_V2 = APP_ROOT  # Use Docker path for tools/templates
BACKUPS_DIR = "/backups"  # Mounted separately in Docker
# Note: DOCS_DIR removed — docs now live in knowledge_base table.
# Use docs_migration.py to populate, Mission Control Knowledge tab to browse.


# ======================
# AUTO-SYNC
# ======================


def auto_sync_if_stale() -> Dict[str, Any]:
    """Check if last blueprint_sync is older than 5 minutes. If so, re-sync."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT updated_at FROM knowledge_base
            WHERE source_type = 'blueprint_sync'
            ORDER BY updated_at DESC
            LIMIT 1
        """
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and row["updated_at"]:
            age = (datetime.now() - row["updated_at"]).total_seconds()
            if age < 300:  # Less than 5 minutes old
                return {"synced": False, "reason": "data_fresh", "age_seconds": int(age)}

        # Stale or no data — trigger sync
        result = sync_blueprint_to_knowledge_base()
        return {"synced": True, "result": result}

    except Exception as e:
        logger.error(f"Auto-sync check failed: {e}")
        return {"synced": False, "error": str(e)}


# ======================
# DATABASE SCHEMA VIEWER
# ======================


def get_database_schema() -> Dict[str, Any]:
    """Get comprehensive database schema information."""
    # Check cache first
    cached = get_cached("schema")
    if cached:
        return cached

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get all tables
        cur.execute(
            """
            SELECT
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        )
        tables_raw = cur.fetchall()

        tables = []
        total_rows = 0

        for t in tables_raw:
            table_name = t["table_name"]

            # Get columns
            cur.execute(
                """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """,
                (table_name,),
            )
            columns = [dict(c) for c in cur.fetchall()]

            # Get row count
            try:
                cur.execute(f'SELECT COUNT(*) as count FROM "{table_name}"')
                row_count = cur.fetchone()["count"]
                total_rows += row_count
            except:
                row_count = 0

            # Get primary key
            cur.execute(
                """
                SELECT a.attname as column_name
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s::regclass AND i.indisprimary
            """,
                (table_name,),
            )
            pk_result = cur.fetchall()
            primary_keys = [r["column_name"] for r in pk_result]

            # Get foreign keys
            cur.execute(
                """
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table,
                    ccu.column_name AS foreign_column
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = %s
            """,
                (table_name,),
            )
            foreign_keys = [dict(fk) for fk in cur.fetchall()]

            # Get indexes
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = %s
            """,
                (table_name,),
            )
            indexes = [dict(i) for i in cur.fetchall()]

            tables.append(
                {
                    "name": table_name,
                    "type": t["table_type"],
                    "row_count": row_count,
                    "columns": columns,
                    "column_count": len(columns),
                    "primary_keys": primary_keys,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
                }
            )

        # Get views
        cur.execute(
            """
            SELECT table_name as view_name, view_definition
            FROM information_schema.views
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        )
        views = [dict(v) for v in cur.fetchall()]

        # Get functions
        cur.execute(
            """
            SELECT
                routine_name,
                routine_type,
                data_type as return_type
            FROM information_schema.routines
            WHERE routine_schema = 'public'
            ORDER BY routine_name
        """
        )
        functions = [dict(f) for f in cur.fetchall()]

        # Get triggers
        cur.execute(
            """
            SELECT
                trigger_name,
                event_manipulation as event,
                event_object_table as table_name,
                action_timing as timing
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


# ====================
# API DOCUMENTATION
# ====================


def get_api_endpoints() -> Dict[str, Any]:
    """Get all registered API endpoints from Flask app."""
    try:
        from flask import current_app

        endpoints = []

        for rule in current_app.url_map.iter_rules():
            # Skip static files
            if "static" in rule.endpoint:
                continue

            methods = [m for m in rule.methods if m not in ["HEAD", "OPTIONS"]]

            # Determine category from endpoint name
            parts = rule.endpoint.split(".")
            category = parts[0] if len(parts) > 1 else "core"

            # Get docstring if available
            view_func = current_app.view_functions.get(rule.endpoint)
            docstring = view_func.__doc__ if view_func and view_func.__doc__ else None

            endpoints.append(
                {
                    "endpoint": rule.endpoint,
                    "path": str(rule),
                    "methods": methods,
                    "category": category,
                    "description": docstring.strip().split("\n")[0] if docstring else None,
                    "has_args": bool(rule.arguments),
                }
            )

        # Sort by path
        endpoints.sort(key=lambda x: x["path"])

        # Group by category
        categories = {}
        for ep in endpoints:
            cat = ep["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(ep)

        return {"success": True, "endpoints": endpoints, "categories": categories, "total": len(endpoints)}
    except Exception as e:
        logger.error(f"Error getting endpoints: {e}")
        return {"success": False, "error": str(e)}


# ====================
# SYSTEM HEALTH
# ====================


def get_system_health() -> Dict[str, Any]:
    """Get comprehensive system health information."""
    # Check cache first
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
        # System resources (interval=0.1 for faster response, less accurate but good enough)
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
                (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds() / 3600, 1
            ),
        }
    except Exception as e:
        health["system"] = {"error": str(e)}

    # Docker containers
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

    # Database health
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Connection count
        cur.execute("SELECT count(*) FROM pg_stat_activity")
        conn_count = cur.fetchone()["count"]

        # Database size
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
        db_size = cur.fetchone()["size"]

        # Uptime
        cur.execute("SELECT pg_postmaster_start_time()")
        start_time = cur.fetchone()["pg_postmaster_start_time"]

        health["database"] = {
            "connected": True,
            "connections": conn_count,
            "size": db_size,
            "uptime_hours": (
                round((datetime.now(start_time.tzinfo) - start_time).total_seconds() / 3600, 1) if start_time else None
            ),
        }

        cur.close()
        conn.close()
    except Exception as e:
        health["database"] = {"connected": False, "error": str(e)}

    # Service checks
    services = [
        {"name": "Platform", "endpoint": "http://localhost:3000/api/health"},
        {"name": "Ollama", "endpoint": "http://localhost:11434/api/tags"},
    ]

    import requests

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


# ====================
# DEPENDENCY TRACKER
# ====================


def get_dependencies() -> Dict[str, Any]:
    """Get Python package dependencies and versions."""
    # Check cache first - this is slow due to pip --outdated check
    cached = get_cached("dependencies")
    if cached:
        return cached

    try:
        result = subprocess.run(["pip", "list", "--format=json"], capture_output=True, text=True, timeout=30)

        packages = []
        if result.returncode == 0:
            packages = json.loads(result.stdout)

        # Check for outdated
        outdated_result = subprocess.run(
            ["pip", "list", "--outdated", "--format=json"], capture_output=True, text=True, timeout=60
        )

        outdated = {}
        if outdated_result.returncode == 0:
            for pkg in json.loads(outdated_result.stdout):
                outdated[pkg["name"]] = {"current": pkg["version"], "latest": pkg["latest_version"]}

        # Categorize packages
        core_packages = ["flask", "psycopg2", "requests", "gunicorn", "python-dotenv", "jinja2"]
        ai_packages = ["anthropic", "openai", "ollama", "tiktoken", "transformers"]
        dev_packages = ["pytest", "black", "flake8", "mypy", "pylint"]

        categorized = {"core": [], "ai": [], "dev": [], "other": []}

        for pkg in packages:
            pkg_info = {
                "name": pkg["name"],
                "version": pkg["version"],
                "outdated": pkg["name"] in outdated,
                "latest": outdated.get(pkg["name"], {}).get("latest"),
            }

            name_lower = pkg["name"].lower()
            if name_lower in core_packages:
                categorized["core"].append(pkg_info)
            elif name_lower in ai_packages:
                categorized["ai"].append(pkg_info)
            elif name_lower in dev_packages:
                categorized["dev"].append(pkg_info)
            else:
                categorized["other"].append(pkg_info)

        # Get Python version
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        result = {
            "success": True,
            "python_version": python_version,
            "packages": packages,
            "categorized": categorized,
            "summary": {
                "total": len(packages),
                "outdated": len(outdated),
                "core": len(categorized["core"]),
                "ai": len(categorized["ai"]),
            },
        }
        set_cached("dependencies", result)
        return result
    except Exception as e:
        logger.error(f"Error getting dependencies: {e}")
        return {"success": False, "error": str(e)}


# ====================
# BACKUP STATUS
# ====================


def get_backup_status() -> Dict[str, Any]:
    """Get backup status synced with Backup Manager module.

    Uses the same metadata.json parsing as Backup Manager for consistency.
    Includes deployment backups from database.
    """
    try:
        backups = []
        total_size = 0

        if os.path.exists(BACKUPS_DIR):
            for item in sorted(os.listdir(BACKUPS_DIR), reverse=True):
                item_path = os.path.join(BACKUPS_DIR, item)

                if os.path.isdir(item_path):
                    # Check for metadata.json (Backup Manager format)
                    metadata_file = os.path.join(item_path, "metadata.json")
                    metadata = None

                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, "r") as f:
                                metadata = json.load(f)
                        except:
                            pass

                    # Calculate directory size
                    dir_size = 0
                    file_count = 0
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            try:
                                dir_size += os.path.getsize(os.path.join(root, f))
                                file_count += 1
                            except:
                                pass

                    total_size += dir_size

                    # Use metadata if available (Backup Manager format), else parse from name
                    if metadata:
                        backups.append(
                            {
                                "name": item,
                                "path": item_path,
                                "size_bytes": dir_size,
                                "size_mb": round(dir_size / (1024 * 1024), 2),
                                "file_count": file_count,
                                "created": metadata.get(
                                    "timestamp", datetime.fromtimestamp(os.path.getctime(item_path)).isoformat()
                                ),
                                "type": metadata.get("type", "unknown"),
                                "description": metadata.get("description", ""),
                                "components": metadata.get("components", []),
                                "build_number": metadata.get("build_number"),
                                "has_metadata": True,
                            }
                        )
                    else:
                        # Fallback for older backups without metadata
                        backups.append(
                            {
                                "name": item,
                                "path": item_path,
                                "size_bytes": dir_size,
                                "size_mb": round(dir_size / (1024 * 1024), 2),
                                "file_count": file_count,
                                "created": datetime.fromtimestamp(os.path.getctime(item_path)).isoformat(),
                                "type": "full" if "Full" in item else "partial" if "partial" in item else "unknown",
                                "description": "",
                                "components": [],
                                "build_number": None,
                                "has_metadata": False,
                            }
                        )

        # Get deployment backups from database
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                dep.backup_name,
                dep.deployed_at,
                dep.status,
                ip.title as proposal_title
            FROM improvement_deployments dep
            JOIN improvement_proposals ip ON dep.proposal_id = ip.id
            WHERE dep.backup_name IS NOT NULL
            ORDER BY dep.deployed_at DESC
            LIMIT 20
        """
        )
        deployment_backups = [dict(row) for row in cur.fetchall()]

        # Convert timestamps
        for db in deployment_backups:
            if db.get("deployed_at"):
                db["deployed_at"] = db["deployed_at"].isoformat()

        cur.close()
        conn.close()

        # Get backup type distribution
        type_counts = {}
        for b in backups:
            btype = b.get("type", "unknown")
            type_counts[btype] = type_counts.get(btype, 0) + 1

        return {
            "success": True,
            "backups": backups[:20],  # Limit to 20 most recent
            "deployment_backups": deployment_backups,
            "summary": {
                "total_backups": len(backups),
                "total_size_gb": round(total_size / (1024**3), 2),
                "latest": backups[0]["name"] if backups else None,
                "latest_date": backups[0]["created"] if backups else None,
                "deployment_backups_count": len(deployment_backups),
                "type_distribution": type_counts,
                "with_metadata": len([b for b in backups if b.get("has_metadata")]),
            },
            "backup_manager_url": "/tools/backup_manager/",  # Link to full Backup Manager
        }
    except Exception as e:
        logger.error(f"Error getting backup status: {e}")
        return {"success": False, "error": str(e)}


# ====================
# AGENT DIRECTORY
# ====================


def get_agent_directory() -> Dict[str, Any]:
    """Get comprehensive agent directory synced with Team Management data.

    Includes:
    - Basic agent info (name, type, status)
    - Skills (top 5 from agent_skills)
    - Proposal counts (from improvement_proposals)
    - Execution metrics (from agent_executions) - Team Management sync
    - Budget info (from agents table) - Team Management sync
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get all agents with details including Team Management metrics
        cur.execute(
            """
            SELECT
                a.*,
                (SELECT COUNT(*) FROM improvement_proposals WHERE assigned_agent_id = a.id) as proposal_count,
                (SELECT COUNT(*) FROM improvement_proposals WHERE assigned_agent_id = a.id AND status = 'deployed') as deployed_count,
                COALESCE((SELECT COUNT(*) FROM agent_executions WHERE agent_id = a.id), 0) as total_executions,
                COALESCE((SELECT COUNT(*) FROM agent_executions WHERE agent_id = a.id AND status = 'failed'), 0) as failed_executions,
                COALESCE((SELECT ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - started_at)))::numeric, 2)
                         FROM agent_executions WHERE agent_id = a.id AND completed_at IS NOT NULL), 0) as avg_duration_seconds
            FROM agents a
            ORDER BY a.worker_type, a.name
        """
        )
        agents = cur.fetchall()

        # Get skills for each agent
        for agent in agents:
            cur.execute(
                """
                SELECT skill_name, proficiency_level
                FROM agent_skills
                WHERE agent_id = %s
                ORDER BY proficiency_level DESC
                LIMIT 5
            """,
                (agent["id"],),
            )
            agent["top_skills"] = [dict(s) for s in cur.fetchall()]

        # Categorize by worker type
        internal = [dict(a) for a in agents if a["worker_type"] == "internal"]
        contractors = [dict(a) for a in agents if a["worker_type"] in ("contractor", "contract")]
        humans = [dict(a) for a in agents if a["worker_type"] == "human"]

        # Get department breakdown (using worker_type as pseudo-departments)
        cur.execute(
            """
            SELECT
                worker_type as name,
                COUNT(*) as agent_count
            FROM agents
            GROUP BY worker_type
            ORDER BY agent_count DESC
        """
        )
        departments = [dict(d) for d in cur.fetchall()]

        # Get station assignments - simplified without bridge_stations
        station_assignments = []
        try:
            cur.execute(
                """
                SELECT
                    sa.station_id,
                    a.name as agent_name,
                    sa.role
                FROM station_assignments sa
                JOIN agents a ON sa.agent_id = a.id
                WHERE sa.is_active = true
                ORDER BY sa.station_id
            """
            )
            station_assignments = [dict(s) for s in cur.fetchall()]
        except Exception:
            pass  # Table might not exist

        # Convert timestamps and calculate totals
        total_executions = 0
        total_budget = 0
        total_cost = 0

        for agent in internal + contractors + humans:
            for key in ["created_at", "last_active", "hired_at"]:
                if agent.get(key):
                    agent[key] = agent[key].isoformat()

            # Sum up Team Management metrics
            total_executions += agent.get("total_executions", 0) or 0
            total_budget += float(agent.get("monthly_budget", 0) or 0)
            total_cost += float(agent.get("total_cost", 0) or 0)

            # Convert Decimal types to float for JSON serialization
            if agent.get("avg_duration_seconds"):
                agent["avg_duration_seconds"] = float(agent["avg_duration_seconds"])
            if agent.get("monthly_budget"):
                agent["monthly_budget"] = float(agent["monthly_budget"])
            if agent.get("total_cost"):
                agent["total_cost"] = float(agent["total_cost"])

        return {
            "success": True,
            "internal": internal,
            "contractors": contractors,
            "humans": humans,
            "departments": departments,
            "station_assignments": station_assignments,
            "summary": {
                "total": len(agents),
                "internal": len(internal),
                "contractors": len(contractors),
                "humans": len(humans),
                "active": len([a for a in agents if a.get("status") == "active"]),
                # Team Management metrics
                "total_executions": total_executions,
                "total_budget": round(total_budget, 2),
                "total_cost": round(total_cost, 2),
            },
        }
    except Exception as e:
        logger.error(f"Error getting agent directory: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ====================
# SNAPSHOT COMPARISON
# ====================


def compare_inventory_snapshots(old_id: int, new_id: int) -> Dict[str, Any]:
    """Compare two inventory snapshots to show changes."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get both snapshots
        cur.execute("SELECT * FROM platform_inventory WHERE id = %s", (old_id,))
        old_snapshot = cur.fetchone()

        cur.execute("SELECT * FROM platform_inventory WHERE id = %s", (new_id,))
        new_snapshot = cur.fetchone()

        if not old_snapshot or not new_snapshot:
            return {"success": False, "error": "Snapshot not found"}

        old_data = (
            old_snapshot["inventory_data"]
            if isinstance(old_snapshot["inventory_data"], dict)
            else json.loads(old_snapshot["inventory_data"])
        )
        new_data = (
            new_snapshot["inventory_data"]
            if isinstance(new_snapshot["inventory_data"], dict)
            else json.loads(new_snapshot["inventory_data"])
        )

        # Compare docs
        old_docs = set(f["name"] for f in old_data.get("docs", {}).get("files", []))
        new_docs = set(f["name"] for f in new_data.get("docs", {}).get("files", []))

        # Compare tools
        old_tools = set(m["name"] for m in old_data.get("tools", {}).get("modules", []))
        new_tools = set(m["name"] for m in new_data.get("tools", {}).get("modules", []))

        # Compare migrations
        old_migrations = set(f["name"] for f in old_data.get("migrations", {}).get("files", []))
        new_migrations = set(f["name"] for f in new_data.get("migrations", {}).get("files", []))

        comparison = {
            "success": True,
            "old_snapshot": {"id": old_id, "date": old_snapshot["snapshot_at"].isoformat()},
            "new_snapshot": {"id": new_id, "date": new_snapshot["snapshot_at"].isoformat()},
            "changes": {
                "docs": {
                    "added": list(new_docs - old_docs),
                    "removed": list(old_docs - new_docs),
                    "count_change": len(new_docs) - len(old_docs),
                },
                "tools": {
                    "added": list(new_tools - old_tools),
                    "removed": list(old_tools - new_tools),
                    "count_change": len(new_tools) - len(old_tools),
                },
                "migrations": {
                    "added": list(new_migrations - old_migrations),
                    "removed": list(old_migrations - new_migrations),
                    "count_change": len(new_migrations) - len(old_migrations),
                },
                "size_change_mb": round((new_snapshot["total_size_mb"] or 0) - (old_snapshot["total_size_mb"] or 0), 2),
            },
        }

        return comparison
    except Exception as e:
        logger.error(f"Error comparing snapshots: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ====================
# KNOWLEDGE BASE INTEGRATION
# ====================


def sync_blueprint_to_knowledge_base() -> Dict[str, Any]:
    """Sync Blueprint intelligence data to knowledge base for A.R.C.H.I.E. access."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        synced = []

        # 1. Sync database schema summary
        schema = get_database_schema()
        if schema.get("success"):
            schema_content = f"""# A.R.C.H.I.E. Database Schema Summary

## Overview
- Total Tables: {schema['summary']['total_tables']}
- Total Views: {schema['summary']['total_views']}
- Total Functions: {schema['summary']['total_functions']}
- Total Rows: {schema['summary']['total_rows']:,}

## Key Tables
"""
            for table in schema["tables"][:20]:  # Top 20 tables
                schema_content += (
                    f"- **{table['name']}**: {table['row_count']:,} rows, {table['column_count']} columns\n"
                )

            cur.execute(
                """
                INSERT INTO knowledge_base (title, content, knowledge_type, source_type, importance_score, tags)
                VALUES (%s, %s, 'vault_note', 'blueprint_sync', 0.85, %s)
                ON CONFLICT (title) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            """,
                ("DATABASE_SCHEMA_SUMMARY", schema_content, ["database", "schema", "architecture", "blueprint"]),
            )
            synced.append("database_schema")

        # 2. Sync system health snapshot
        health = get_system_health()
        if health.get("success"):
            health_content = f"""# A.R.C.H.I.E. System Health Snapshot

## System Resources
- CPU Usage: {health['system'].get('cpu_percent', 'N/A')}%
- Memory: {health['system'].get('memory', {}).get('used_gb', 'N/A')} / {health['system'].get('memory', {}).get('total_gb', 'N/A')} GB ({health['system'].get('memory', {}).get('percent', 'N/A')}%)
- Disk: {health['system'].get('disk', {}).get('used_gb', 'N/A')} / {health['system'].get('disk', {}).get('total_gb', 'N/A')} GB ({health['system'].get('disk', {}).get('percent', 'N/A')}%)

## Docker Containers
"""
            for container in health.get("docker", {}).get("containers", []):
                status = "✅" if container.get("healthy") else "❌"
                health_content += f"- {status} **{container['name']}**: {container['status']}\n"

            health_content += f"""
## Database
- Connected: {health['database'].get('connected', False)}
- Size: {health['database'].get('size', 'N/A')}
- Connections: {health['database'].get('connections', 'N/A')}

*Last updated: {health['timestamp']}*
"""

            cur.execute(
                """
                INSERT INTO knowledge_base (title, content, knowledge_type, source_type, importance_score, tags)
                VALUES (%s, %s, 'vault_note', 'blueprint_sync', 0.7, %s)
                ON CONFLICT (title) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            """,
                ("SYSTEM_HEALTH_STATUS", health_content, ["system", "health", "monitoring", "blueprint"]),
            )
            synced.append("system_health")

        # 3. Sync agent directory summary
        agents = get_agent_directory()
        if agents.get("success"):
            agent_content = f"""# A.R.C.H.I.E. Agent Directory

## Summary
- Total Agents: {agents['summary']['total']}
- Internal Agents: {agents['summary']['internal']}
- Contractor Agents: {agents['summary']['contractors']}
- Human Operators: {agents['summary']['humans']}
- Active: {agents['summary']['active']}

## Departments
"""
            for dept in agents.get("departments", []):
                agent_content += f"- **{dept['name']}**: {dept['agent_count']} agents\n"

            agent_content += "\n## Top Internal Agents\n"
            for agent in agents.get("internal", [])[:10]:
                agent_content += (
                    f"- **{agent['name']}** ({agent.get('role', 'N/A')}): {agent.get('proposal_count', 0)} proposals\n"
                )

            cur.execute(
                """
                INSERT INTO knowledge_base (title, content, knowledge_type, source_type, importance_score, tags)
                VALUES (%s, %s, 'vault_note', 'blueprint_sync', 0.8, %s)
                ON CONFLICT (title) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            """,
                ("AGENT_DIRECTORY_SUMMARY", agent_content, ["agents", "team", "directory", "blueprint"]),
            )
            synced.append("agent_directory")

        conn.commit()

        return {"success": True, "synced": synced, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error syncing to knowledge base: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ====================
# MODULE CODE SYNC
# ====================


def sync_module_code_to_knowledge() -> Dict[str, Any]:
    """Sync module routes.py code to knowledge_base for A.R.C.H.I.E. retrieval.

    Stores each module's routes.py as a code_snippet in knowledge_base,
    making it easier for A.R.C.H.I.E. to reference module code during
    conversations and code generation.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        synced = []
        skipped = []
        errors = []

        tools_dir = os.path.join(PLATFORM_V2, "tools")

        if not os.path.exists(tools_dir):
            return {"success": False, "error": "Tools directory not found"}

        for module_name in sorted(os.listdir(tools_dir)):
            module_path = os.path.join(tools_dir, module_name)

            # Skip non-directories and private directories
            if not os.path.isdir(module_path) or module_name.startswith("_"):
                continue

            routes_path = os.path.join(module_path, "routes.py")

            if not os.path.exists(routes_path):
                skipped.append(module_name)
                continue

            try:
                # Read the routes.py file
                with open(routes_path, "r") as f:
                    content = f.read()

                # Get file stats
                stat = os.stat(routes_path)
                file_size = stat.st_size
                modified_at = datetime.fromtimestamp(stat.st_mtime)

                # Count lines and extract endpoint count
                lines = content.count("\n") + 1
                endpoint_count = content.count("@") + content.count("def ")

                # Create knowledge base entry
                title = f"MODULE_CODE_{module_name.upper()}"

                kb_content = f"""# {module_name} Module - Routes Code

## Module Info
- **Path:** `/platform_v2/tools/{module_name}/routes.py`
- **Lines:** {lines}
- **Size:** {file_size} bytes
- **Last Modified:** {modified_at.isoformat()}
- **Estimated Endpoints:** ~{endpoint_count // 2}

## Source Code

```python
{content[:50000]}  # Truncate very large files
```
"""

                # Insert/update in knowledge_base (delete existing then insert)
                cur.execute(
                    """
                    DELETE FROM knowledge_base
                    WHERE title = %s AND knowledge_type = 'code_snippet' AND source_type = 'module_code_sync'
                """,
                    (title,),
                )

                cur.execute(
                    """
                    INSERT INTO knowledge_base (title, content, knowledge_type, source_type, importance_score, tags)
                    VALUES (%s, %s, 'code_snippet', 'module_code_sync', 0.75, %s)
                """,
                    (title, kb_content, [module_name, "routes", "api", "module", "code"]),
                )

                synced.append({"module": module_name, "lines": lines, "size": file_size})

            except Exception as e:
                errors.append({"module": module_name, "error": str(e)})

        conn.commit()

        return {
            "success": True,
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "summary": {
                "synced_count": len(synced),
                "skipped_count": len(skipped),
                "error_count": len(errors),
                "total_lines": sum(m["lines"] for m in synced),
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error syncing module code: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ====================
# QUICK ACTIONS
# ====================


def execute_quick_action(action: str) -> Dict[str, Any]:
    """Execute a quick action."""
    allowed_actions = {
        "restart_platform": "docker-compose restart archie_platform",
        "restart_database": "docker-compose restart archie_database",
        "clear_cache": "docker exec archie_platform rm -rf /tmp/cache/*",
        "vacuum_database": 'docker exec archie_database psql -U archie -d archie -c "VACUUM ANALYZE"',
        "check_logs": "docker logs archie_platform --tail 50",
    }

    if action not in allowed_actions:
        return {"success": False, "error": f"Unknown action: {action}"}

    try:
        result = subprocess.run(
            allowed_actions[action], shell=True, capture_output=True, text=True, timeout=60, cwd=PLATFORM_ROOT
        )

        return {
            "success": result.returncode == 0,
            "action": action,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timestamp": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Action timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ====================
# CONSCIOUSNESS INTEGRATION
# ====================


def get_consciousness_summary() -> Dict[str, Any]:
    """Get comprehensive consciousness data for Blueprint integration.

    Provides full scope of Consciousness module data:
    - Memory stats by type
    - Recent memories (last 10)
    - Emotional state with 7-day trends
    - Knowledge base breakdown
    - Active conversations
    - Backlinks and resources counts
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get memory stats
        memory_stats = {"total_memories": 0, "episodic": 0, "semantic": 0, "procedural": 0}
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_memories,
                    COUNT(*) FILTER (WHERE memory_type = 'episodic') as episodic,
                    COUNT(*) FILTER (WHERE memory_type = 'semantic') as semantic,
                    COUNT(*) FILTER (WHERE memory_type = 'procedural') as procedural
                FROM agent_memory
                WHERE deleted_at IS NULL
            """
            )
            memory_stats = dict(cur.fetchone())
        except Exception:
            conn.rollback()

        # Get recent memories (last 10)
        recent_memories = []
        try:
            cur.execute(
                """
                SELECT
                    id, memory_type, content, importance, created_at
                FROM agent_memory
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 10
            """
            )
            for row in cur.fetchall():
                r = dict(row)
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
                # Truncate long content for display
                if r.get("content") and len(r["content"]) > 200:
                    r["content"] = r["content"][:200] + "..."
                recent_memories.append(r)
        except Exception:
            conn.rollback()

        # Get emotional state with 7-day trend
        emotional_stats = {"avg_energy": 0, "avg_stress": 0, "current_mood": "neutral"}
        emotional_trends = []
        try:
            # Current 24h average
            cur.execute(
                """
                SELECT
                    AVG(energy_level) as avg_energy,
                    AVG(stress_level) as avg_stress
                FROM agent_emotional_state
                WHERE recorded_at > NOW() - INTERVAL '24 hours'
            """
            )
            result = cur.fetchone()
            if result and result["avg_energy"]:
                emotional_stats = {
                    "avg_energy": round(float(result["avg_energy"]), 2),
                    "avg_stress": round(float(result["avg_stress"] or 0), 2),
                    "current_mood": (
                        "positive"
                        if float(result["avg_energy"]) > 0.6
                        else "neutral" if float(result["avg_energy"]) > 0.4 else "tired"
                    ),
                }

            # 7-day trend data for charts
            cur.execute(
                """
                SELECT
                    DATE(recorded_at) as date,
                    AVG(energy_level) as energy,
                    AVG(stress_level) as stress
                FROM agent_emotional_state
                WHERE recorded_at > NOW() - INTERVAL '7 days'
                GROUP BY DATE(recorded_at)
                ORDER BY date
            """
            )
            for row in cur.fetchall():
                emotional_trends.append(
                    {
                        "date": row["date"].isoformat() if row["date"] else None,
                        "energy": round(float(row["energy"] or 0), 2),
                        "stress": round(float(row["stress"] or 0), 2),
                    }
                )
        except Exception:
            conn.rollback()

        # Get knowledge base stats
        cur.execute(
            """
            SELECT
                knowledge_type,
                COUNT(*) as count
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY count DESC
        """
        )
        knowledge_stats = [dict(row) for row in cur.fetchall()]
        total_knowledge = sum(k["count"] for k in knowledge_stats)

        # Get active conversations count
        active_conversations = 0
        try:
            cur.execute(
                """
                SELECT COUNT(DISTINCT conversation_id) as count
                FROM agent_memory
                WHERE created_at > NOW() - INTERVAL '24 hours'
                AND conversation_id IS NOT NULL
            """
            )
            result = cur.fetchone()
            active_conversations = result["count"] if result else 0
        except Exception:
            conn.rollback()

        # Get backlinks count (if table exists)
        backlinks_count = 0
        try:
            cur.execute("SELECT COUNT(*) as count FROM knowledge_backlinks")
            backlinks_count = cur.fetchone()["count"]
        except Exception:
            conn.rollback()

        # Get resources count (if table exists)
        resources_count = 0
        try:
            cur.execute("SELECT COUNT(*) as count FROM agent_resources")
            resources_count = cur.fetchone()["count"]
        except Exception:
            conn.rollback()

        # Get recent activity
        cur.execute(
            """
            SELECT
                'proposal' as type,
                title,
                proposed_at as created_at
            FROM improvement_proposals
            ORDER BY proposed_at DESC
            LIMIT 5
        """
        )
        recent_activity = []
        for row in cur.fetchall():
            r = dict(row)
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            recent_activity.append(r)

        return {
            "success": True,
            "memory": memory_stats,
            "recent_memories": recent_memories,
            "emotional": emotional_stats,
            "emotional_trends": emotional_trends,
            "knowledge": knowledge_stats,
            "total_knowledge": total_knowledge,
            "active_conversations": active_conversations,
            "backlinks_count": backlinks_count,
            "resources_count": resources_count,
            "recent_activity": recent_activity,
            "consciousness_url": "/tools/consciousness/",  # Link to full Consciousness module
        }
    except Exception as e:
        logger.error(f"Error getting consciousness summary: {e}")
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()
