"""Auto-generates module documentation for Dev HQ reference."""

import logging
from database import get_db_cursor
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


def generate_module_docs():
    """Scan all modules and generate/update documentation in knowledge_base."""
    from module_registry import MODULES

    updated = 0
    for module in MODULES:
        if not module.enabled:
            continue

        # Build module doc
        doc = {
            "id": module.id,
            "name": module.name,
            "description": module.description,
            "category": module.category.value,
            "route": module.route,
            "permissions": module.required_permissions,
            "minimum_role": module.minimum_role,
        }

        # Count routes
        try:
            from flask import current_app

            route_count = len([r for r in current_app.url_map.iter_rules() if module.route in r.rule])
            doc["route_count"] = route_count
        except Exception:
            doc["route_count"] = 0

        # Store in knowledge_base
        title = f"Module Reference: {module.name}"
        content = (
            f"# {module.name}\n\n{module.description}\n\n"
            f"Category: {module.category.value}\n"
            f"Route: {module.route}\n"
            f"Minimum Role: {module.minimum_role}\n"
            f"Permissions: {', '.join(module.required_permissions) or 'None'}\n"
            f"Routes: {doc['route_count']}\n"
            f"Tags: {', '.join(module.tags)}"
        )

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO knowledge_base (title, content, category, importance, tags, knowledge_type)
                    VALUES (%s, %s, 'module_reference', 0.8, %s, 'vault_note')
                    ON CONFLICT (title) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                    """,
                    (title, content, Json(module.tags + ["module-reference", "auto-generated"])),
                )
            updated += 1
        except Exception as e:
            logger.warning(f"[ModuleDocs] Failed to store docs for {module.name}: {e}")

    logger.info(f"[ModuleDocs] Generated docs for {updated} modules")
    return updated
