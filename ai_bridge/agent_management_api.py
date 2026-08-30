#!/usr/bin/env python3
"""
Agent Management API
CRUD operations for managing AI agents
"""

from psycopg2.extras import RealDictCursor
import os
from db import get_db

# =============================================================================
# LIST AGENTS
# =============================================================================


def list_agents(filters=None):
    """
    List all agents with optional filters

    Args:
        filters (dict): Optional filters like {'department': 'Sales', 'status': 'active'}

    Returns:
        list: List of agent dictionaries
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                a.id,
                a.name,
                a.first_name,
                a.last_name,
                a.email,
                a.title,
                a.department,
                a.pronouns,
                a.bio,
                a.avatar_url,
                a.tier,
                a.status,
                a.model,
                a.system_prompt,
                a.capabilities,
                a.monthly_budget,
                a.budget_alert_threshold,
                a.total_tokens_used,
                a.total_cost,
                a.metadata,
                a.created_at,
                a.last_used,
                at.name as agent_type,
                at.category
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
        """

        conditions = []
        params = []

        if filters:
            if "department" in filters:
                conditions.append("a.department = %s")
                params.append(filters["department"])
            if "status" in filters:
                conditions.append("a.status = %s")
                params.append(filters["status"])
            if "tier" in filters:
                conditions.append("a.tier = %s")
                params.append(filters["tier"])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY a.department, a.first_name"

        cur.execute(query, tuple(params))
        agents = cur.fetchall()

        return [dict(agent) for agent in agents]
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# =============================================================================
# GET SINGLE AGENT
# =============================================================================


def get_agent(agent_id):
    """
    Get a single agent by ID

    Args:
        agent_id (int): Agent ID

    Returns:
        dict: Agent details or None if not found
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.*,
                at.name as agent_type,
                at.category
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.id = %s
        """,
            (agent_id,),
        )

        agent = cur.fetchone()

        return dict(agent) if agent else None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# =============================================================================
# ADD AGENT
# =============================================================================


def add_agent(agent_data):
    """
    Add a new agent

    Args:
        agent_data (dict): Agent information
            Required: name, type_id, tier, model, system_prompt
            Optional: first_name, last_name, email, title, department, bio, pronouns,
                     avatar_url, capabilities, monthly_budget, metadata

    Returns:
        dict: Created agent with ID
    """
    # Single-writer path: Project #241 Track C.3. Pre-flight validation
    # queries stay here (type_id existence + email uniqueness), but the
    # actual agents-table mutation flows through agent_service.
    from services import agent_service as _svc

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if agent type exists
        cur.execute("SELECT id FROM agent_types WHERE id = %s", (agent_data["type_id"],))
        if not cur.fetchone():
            raise ValueError(f"Agent type ID {agent_data['type_id']} not found")

        # Check for duplicate email
        if "email" in agent_data and agent_data["email"]:
            cur.execute("SELECT id FROM agents WHERE email = %s", (agent_data["email"],))
            if cur.fetchone():
                raise ValueError(f"Email {agent_data['email']} already exists")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    # Create via canonical helper
    title = agent_data.get("title")
    agent_id = _svc.create_agent(
        name=agent_data["name"],
        display_name=title or agent_data["name"],
        department=agent_data.get("department") or "Engineering & Technology",
        model=agent_data["model"],
        system_prompt=agent_data["system_prompt"],
        tier=agent_data.get("tier", 1),
        capabilities=agent_data.get("capabilities") or {},
    )

    # Follow-up with extras not in create_agent's core signature
    extras = {}
    for field in (
        "type_id",
        "monthly_budget",
        "budget_alert_threshold",
        "first_name",
        "last_name",
        "email",
        "title",
        "bio",
        "avatar_url",
    ):
        if agent_data.get(field) is not None:
            extras[field] = agent_data[field]
    extras.setdefault("pronouns", agent_data.get("pronouns", "they/them"))
    if agent_data.get("metadata"):
        extras["metadata"] = agent_data["metadata"]
    if agent_data.get("status") and agent_data["status"] != "active":
        extras["status"] = agent_data["status"]
    if extras:
        _svc.update_agent(agent_id, **extras)

    return get_agent(agent_id)


# =============================================================================
# UPDATE AGENT
# =============================================================================


def update_agent(agent_id, updates):
    """
    Update an existing agent

    Args:
        agent_id (int): Agent ID
        updates (dict): Fields to update (any agent field)

    Returns:
        dict: Updated agent
    """
    # Single-writer path: Project #241 Track C.3. Pre-flight validation
    # (existence + email uniqueness) stays here; the mutation flows
    # through agent_service.
    from services import agent_service as _svc

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if agent exists
        cur.execute("SELECT id FROM agents WHERE id = %s", (agent_id,))
        if not cur.fetchone():
            raise ValueError(f"Agent ID {agent_id} not found")

        # Check for duplicate email if updating email
        if "email" in updates and updates["email"]:
            cur.execute(
                "SELECT id FROM agents WHERE email = %s AND id != %s",
                (updates["email"], agent_id),
            )
            if cur.fetchone():
                raise ValueError(f"Email {updates['email']} already exists")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    # Filter to allowed fields and dispatch to canonical helper
    allowed_fields = {
        "name",
        "type_id",
        "tier",
        "status",
        "model",
        "system_prompt",
        "capabilities",
        "monthly_budget",
        "budget_alert_threshold",
        "metadata",
        "first_name",
        "last_name",
        "email",
        "title",
        "department",
        "bio",
        "pronouns",
        "avatar_url",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        raise ValueError("No valid fields to update")

    _svc.update_agent(agent_id, **filtered)
    return get_agent(agent_id)


# =============================================================================
# DELETE AGENT
# =============================================================================


def delete_agent(agent_id, soft_delete=True):
    """
    Delete an agent (soft delete by default)

    Args:
        agent_id (int): Agent ID
        soft_delete (bool): If True, set status to 'inactive', if False, permanently delete

    Returns:
        bool: Success
    """
    # Single-writer path: Project #241 Track C.3. Existence check stays
    # here; the mutation flows through agent_service.delete_agent which
    # handles both soft (status=inactive + shift_state=off_duty) and
    # hard (DELETE) variants via its hard= kwarg.
    from services import agent_service as _svc

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM agents WHERE id = %s", (agent_id,))
        if not cur.fetchone():
            raise ValueError(f"Agent ID {agent_id} not found")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    _svc.delete_agent(agent_id, hard=not soft_delete)
    return True


# =============================================================================
# UPLOAD AVATAR
# =============================================================================


def update_avatar(agent_id, avatar_url):
    """
    Update agent avatar URL

    Args:
        agent_id (int): Agent ID
        avatar_url (str): URL to avatar image

    Returns:
        dict: Updated agent
    """
    return update_agent(agent_id, {"avatar_url": avatar_url})


# =============================================================================
# SEARCH AGENTS
# =============================================================================


def search_agents(query):
    """
    Search agents by name, email, title, or department

    Args:
        query (str): Search query

    Returns:
        list: Matching agents
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        search_pattern = f"%{query}%"

        cur.execute(
            """
            SELECT
                a.id,
                a.first_name,
                a.last_name,
                a.email,
                a.title,
                a.department,
                a.status,
                at.name as agent_type
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE
                a.first_name ILIKE %s
                OR a.last_name ILIKE %s
                OR a.email ILIKE %s
                OR a.title ILIKE %s
                OR a.department ILIKE %s
                OR a.name ILIKE %s
            ORDER BY a.first_name, a.last_name
        """,
            (
                search_pattern,
                search_pattern,
                search_pattern,
                search_pattern,
                search_pattern,
                search_pattern,
            ),
        )

        agents = cur.fetchall()

        return [dict(agent) for agent in agents]
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# =============================================================================
# CLI EXAMPLES
# =============================================================================

if __name__ == "__main__":
    print("Agent Management API - Examples\n")

    # Example 1: List all agents
    print("=" * 70)
    print("Example 1: List all active agents")
    print("=" * 70)
    agents = list_agents({"status": "active"})
    print(f"Found {len(agents)} active agents\n")
    for agent in agents[:5]:  # Show first 5
        print(f"  • {agent['first_name']} {agent['last_name']} - {agent['title']}")

    print("\n" + "=" * 70)
    print("Example 2: Get single agent")
    print("=" * 70)
    agent = get_agent(1)
    if agent:
        print(f"Name: {agent['first_name']} {agent['last_name']}")
        print(f"Email: {agent['email']}")
        print(f"Title: {agent['title']}")
        print(f"Department: {agent['department']}")

    print("\n" + "=" * 70)
    print("Example 3: Search agents")
    print("=" * 70)
    results = search_agents("sales")
    print(f"Found {len(results)} agents matching 'sales'")
    for agent in results:
        print(f"  • {agent['first_name']} {agent['last_name']} - {agent['title']}")

    print("\n" + "=" * 70)
    print("API Functions Available:")
    print("=" * 70)
    print("  • list_agents(filters=None)")
    print("  • get_agent(agent_id)")
    print("  • add_agent(agent_data)")
    print("  • update_agent(agent_id, updates)")
    print("  • delete_agent(agent_id, soft_delete=True)")
    print("  • update_avatar(agent_id, avatar_url)")
    print("  • search_agents(query)")
    print()
