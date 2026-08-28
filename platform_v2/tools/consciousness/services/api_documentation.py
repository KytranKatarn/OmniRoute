"""
A.R.C.H.I.E. API Documentation System
=====================================
Discovers and documents all Flask API routes in the knowledge base.

This enables A.R.C.H.I.E. to be aware of its own API capabilities and
maintain accurate documentation as the platform evolves.

Usage:
    python3 api_documentation.py discover    # Find and document all routes
    python3 api_documentation.py update      # Update existing + add new
    python3 api_documentation.py stats       # Show documentation stats

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

import os
from database import _get_db_password
import sys
import logging
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime
import re

# Add platform to path
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

logger = logging.getLogger(__name__)


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def discover_routes_from_app():
    """
    Discover all routes from the Flask application.
    Returns list of route info dicts.
    """
    try:
        from app import app

        routes = []
        for rule in app.url_map.iter_rules():
            # Skip static files and internal Flask routes
            if rule.endpoint == "static":
                continue
            if rule.rule.startswith("/static"):
                continue

            # Get the view function
            view_func = app.view_functions.get(rule.endpoint)

            # Extract docstring
            docstring = ""
            if view_func and view_func.__doc__:
                docstring = view_func.__doc__.strip()

            # Determine the module/blueprint
            module = "core"
            if "." in rule.endpoint:
                module = rule.endpoint.split(".")[0]

            # Build route info
            route_info = {
                "path": rule.rule,
                "methods": sorted([m for m in rule.methods if m not in ("HEAD", "OPTIONS")]),
                "endpoint": rule.endpoint,
                "module": module,
                "docstring": docstring,
                "has_params": bool(rule.arguments),
                "params": list(rule.arguments) if rule.arguments else [],
                "is_api": "/api/" in rule.rule or rule.rule.startswith("/api"),
            }

            routes.append(route_info)

        return sorted(routes, key=lambda x: (x["module"], x["path"]))

    except Exception as e:
        logger.error(f"Error discovering routes: {e}", exc_info=True)
        return []


def discover_routes_from_files():
    """
    Alternative: Parse route files directly without importing Flask app.
    More reliable in Docker context.
    """
    routes = []

    # Define route files and their blueprints
    route_files = {
        "tools/admin/routes.py": "admin",
        "tools/improvements/routes.py": "improvements",
        "tools/consciousness/routes.py": "consciousness",
        "tools/backup_manager/routes.py": "backup_manager",
        "tools/website_studio/routes.py": "website_studio",
        "tools/store_builder/routes.py": "store_builder",
        "tools/call_center/routes.py": "call_center",
        "tools/account_center/routes.py": "account_center",
        "tools/creed/admin_routes.py": "creed_admin",
        "tools/security_network/routes.py": "security_network",
        "app.py": "core",
    }

    base_path = "/mnt/archie_brain/platform_v2"

    # Regex to match Flask route decorators
    route_pattern = re.compile(r"@(\w+)\.route\('([^']+)'(?:,\s*methods=\[([^\]]+)\])?\)", re.MULTILINE)

    # Regex to match function definitions and docstrings
    func_pattern = re.compile(r"def\s+(\w+)\([^)]*\):\s*(?:\"\"\"(.*?)\"\"\")?", re.DOTALL)

    for rel_path, module in route_files.items():
        file_path = os.path.join(base_path, rel_path)
        if not os.path.exists(file_path):
            continue

        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Find all route decorators
            for match in route_pattern.finditer(content):
                blueprint = match.group(1)
                path = match.group(2)
                methods_str = match.group(3)

                # Parse methods
                if methods_str:
                    methods = [m.strip().strip("'\"") for m in methods_str.split(",")]
                else:
                    methods = ["GET"]

                # Find the function definition after this decorator
                start_pos = match.end()
                func_match = func_pattern.search(content, start_pos)

                func_name = ""
                docstring = ""
                if func_match and func_match.start() < start_pos + 200:  # Within 200 chars
                    func_name = func_match.group(1)
                    if func_match.group(2):
                        docstring = func_match.group(2).strip().split("\n")[0]  # First line only

                # Determine full path based on blueprint
                full_path = path
                if module == "admin":
                    full_path = "/tools/admin" + path
                elif module == "improvements":
                    full_path = "/tools/improvements" + path
                elif module == "consciousness":
                    full_path = "/tools/consciousness" + path
                elif module == "backup_manager":
                    full_path = "/tools/backup-manager" + path
                elif module == "website_studio":
                    full_path = "/tools/website-studio" + path
                elif module == "store_builder":
                    full_path = "/tools/store-builder" + path
                elif module == "call_center":
                    full_path = "/tools/call-center" + path
                elif module == "account_center":
                    full_path = "/tools/account-center" + path
                elif module == "creed_admin":
                    full_path = "/creed/api/admin" + path
                elif module == "security_network":
                    full_path = "/tools/security-network" + path

                # Extract URL parameters
                params = re.findall(r"<(?:\w+:)?(\w+)>", path)

                route_info = {
                    "path": full_path,
                    "methods": methods,
                    "endpoint": f"{module}.{func_name}",
                    "module": module,
                    "docstring": docstring,
                    "has_params": bool(params),
                    "params": params,
                    "is_api": "/api/" in path or "api" in path.lower(),
                    "source_file": rel_path,
                }

                routes.append(route_info)

        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            continue

    return sorted(routes, key=lambda x: (x["module"], x["path"]))


def save_route_to_knowledge_base(conn, route, update_existing=True):
    """
    Save a single route to the knowledge base.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Create unique source_id for this route
    source_id = f"api:{route['module']}:{route['path']}:{','.join(route['methods'])}"

    # Build documentation content
    methods_str = ", ".join(route["methods"])
    params_str = ", ".join(route["params"]) if route["params"] else "None"

    title = f"API: {methods_str} {route['path']}"

    content = f"""## API Endpoint Documentation

**Path:** `{route['path']}`
**Methods:** {methods_str}
**Module:** {route['module']}
**Endpoint:** {route['endpoint']}

### Description
{route['docstring'] if route['docstring'] else 'No description available.'}

### Parameters
{f"URL Parameters: `{params_str}`" if route['params'] else "No URL parameters."}

### Source
- File: `{route.get('source_file', 'Unknown')}`
- Type: {'API Endpoint' if route['is_api'] else 'Page Route'}

---
*Auto-documented by A.R.C.H.I.E. API Documentation System*
"""

    # Build tags
    tags = ["api", route["module"], "endpoint", "documentation"]
    for method in route["methods"]:
        tags.append(method.lower())
    if route["is_api"]:
        tags.append("rest-api")

    # Build metadata
    metadata = {
        "path": route["path"],
        "methods": route["methods"],
        "module": route["module"],
        "endpoint": route["endpoint"],
        "params": route["params"],
        "is_api": route["is_api"],
        "source_file": route.get("source_file"),
        "documented_at": datetime.now().isoformat(),
        "version": "1.0",
    }

    try:
        # Check if exists
        cur.execute(
            """
            SELECT id FROM knowledge_base
            WHERE knowledge_type = 'api_endpoint' AND source_id = %s
        """,
            (source_id,),
        )

        existing = cur.fetchone()

        if existing and update_existing:
            # Update existing entry
            cur.execute(
                """
                UPDATE knowledge_base
                SET title = %s,
                    content = %s,
                    tags = %s,
                    memory_metadata = %s,
                    updated_at = NOW()
                WHERE id = %s
            """,
                (title, content, tags, Json(metadata), existing["id"]),
            )
            return ("updated", existing["id"])

        elif not existing:
            # Insert new entry
            cur.execute(
                """
                INSERT INTO knowledge_base
                (title, content, knowledge_type, category, tags, importance_score,
                 source_type, source_id, memory_metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    title,
                    content,
                    "api_endpoint",
                    f'API/{route["module"].title()}',
                    tags,
                    0.7,  # Medium-high importance for API docs
                    "api_discovery",
                    source_id,
                    Json(metadata),
                ),
            )
            new_id = cur.fetchone()["id"]
            return ("created", new_id)
        else:
            return ("skipped", existing["id"])

    except Exception as e:
        print(f"Error saving route {route['path']}: {e}")
        return ("error", None)


def document_all_routes(update_existing=True):
    """
    Discover and document all routes in the knowledge base.
    """
    print("🔍 Discovering API routes...")
    routes = discover_routes_from_files()

    print(f"📊 Found {len(routes)} routes")

    if not routes:
        print("❌ No routes found!")
        return

    # Group by module for display
    modules = {}
    for route in routes:
        module = route["module"]
        if module not in modules:
            modules[module] = []
        modules[module].append(route)

    print("\n📦 Routes by module:")
    for module, module_routes in sorted(modules.items()):
        print(f"   {module}: {len(module_routes)} routes")

    # Connect to database
    print("\n💾 Saving to knowledge base...")
    conn = get_db()

    stats = {"created": 0, "updated": 0, "skipped": 0, "error": 0}

    for route in routes:
        action, route_id = save_route_to_knowledge_base(conn, route, update_existing)
        stats[action] += 1

        if action == "created":
            print(f"   ✅ Created: {route['path']}")
        elif action == "updated":
            print(f"   🔄 Updated: {route['path']}")

    conn.commit()
    conn.close()

    print(f"\n📈 Summary:")
    print(f"   Created: {stats['created']}")
    print(f"   Updated: {stats['updated']}")
    print(f"   Skipped: {stats['skipped']}")
    print(f"   Errors: {stats['error']}")
    print(f"   Total: {len(routes)}")


def get_documentation_stats():
    """
    Get statistics about documented APIs.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Count by module
    cur.execute(
        """
        SELECT
            category,
            COUNT(*) as count
        FROM knowledge_base
        WHERE knowledge_type = 'api_endpoint'
        GROUP BY category
        ORDER BY count DESC
    """
    )
    by_module = cur.fetchall()

    # Get total
    cur.execute(
        """
        SELECT COUNT(*) as total FROM knowledge_base
        WHERE knowledge_type = 'api_endpoint'
    """
    )
    total = cur.fetchone()["total"]

    # Get recent updates
    cur.execute(
        """
        SELECT title, updated_at
        FROM knowledge_base
        WHERE knowledge_type = 'api_endpoint'
        ORDER BY updated_at DESC
        LIMIT 5
    """
    )
    recent = cur.fetchall()

    cur.close()
    conn.close()

    print("📊 API Documentation Statistics")
    print("=" * 50)
    print(f"\nTotal Documented APIs: {total}")
    print("\nBy Module:")
    for row in by_module:
        print(f"   {row['category']}: {row['count']}")

    print("\nRecently Updated:")
    for row in recent:
        print(f"   {row['title'][:50]}... ({row['updated_at']})")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 api_documentation.py [discover|update|stats]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "discover":
        document_all_routes(update_existing=False)
    elif command == "update":
        document_all_routes(update_existing=True)
    elif command == "stats":
        get_documentation_stats()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
