"""Makes all agents aware of platform modules they can use."""

import logging
from database import get_db_cursor
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


def update_agent_module_awareness():
    """Update all agents with current module information."""
    from module_registry import MODULES

    # Build module catalog for agents
    module_catalog = []
    for m in MODULES:
        if not m.enabled:
            continue
        module_catalog.append(
            {
                "id": m.id,
                "name": m.name,
                "route": m.route,
                "category": m.category.value,
                "description": m.description.replace("<br>", " - "),
                "admin_only": m.minimum_role == "ADMIN",
                "permissions": m.required_permissions,
            }
        )

    # Build catalog text for agents
    catalog_text = "# Platform Module Catalog\n\n"
    for m in module_catalog:
        access = "ADMIN ONLY" if m["admin_only"] else "All Users"
        catalog_text += f"## {m['name']} ({m['route']})\n{m['description']}\nAccess: {access}\n\n"

    # Store as a knowledge entry accessible to all agents
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO knowledge_base (title, content, category, importance, tags, knowledge_type)
            VALUES ('Agent Module Catalog', %s, 'agent_reference', 0.9, %s, 'vault_note')
            ON CONFLICT (title) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            """,
            (catalog_text, Json(["agent-awareness", "module-catalog", "auto-generated"])),
        )

    # Update each agent's metadata with module awareness flag.
    # Single-writer path: route through agent_service.update_agent so the
    # agents table only has one canonical mutation surface (Project #241
    # Track C.1). update_agent REPLACES metadata wholesale, so we read the
    # current row first and merge in Python to preserve other keys.
    from services import agent_service

    awareness_patch = {
        "module_catalog_version": len(module_catalog),
        "has_module_awareness": True,
    }

    agents_updated = 0
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id, name, metadata FROM agents WHERE status IN ('active', 'inactive')")
        agents = cur.fetchall()

    for agent in agents:
        try:
            existing = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            merged = {**existing, **awareness_patch}
            if agent_service.update_agent(agent["id"], metadata=merged):
                agents_updated += 1
        except Exception as exc:
            logger.warning(f"[Agent Awareness] Failed to update agent {agent.get('id')}: {exc}")

    logger.info(f"[Agent Awareness] Updated {agents_updated} agents with {len(module_catalog)} module catalog")
    return len(module_catalog)
