"""Fleet Service — wraps fleet infrastructure: nodes, cloud providers, usage tracking.

Reads from existing tables: remote_nodes, node_agents, contractor_providers,
external_api_keys, cloud_model_usage, provider_pricing.

Import:
    from services.fleet_service import (
        list_nodes, get_node_status, get_node_agents,
        list_providers, get_provider_status, get_usage_summary,
        get_fleet_map_data,
    )
"""

import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Known cloud provider headquarters for map pins
PROVIDER_LOCATIONS = {
    "ollama": {"city": "Montreal, QC", "lat": 45.5017, "lon": -73.5673},
    "openai": {"city": "San Francisco, CA", "lat": 37.7627, "lon": -122.4170},
    "anthropic": {"city": "San Francisco, CA", "lat": 37.7891, "lon": -122.4020},
    "google": {"city": "Mountain View, CA", "lat": 37.3861, "lon": -122.0839},
    "gemini": {"city": "Mountain View, CA", "lat": 37.4000, "lon": -122.0650},
    "mistral": {"city": "Paris, France", "lat": 48.8566, "lon": 2.3522},
    "cohere": {"city": "Toronto, ON", "lat": 43.6532, "lon": -79.3832},
    "grok": {"city": "San Francisco, CA", "lat": 37.7750, "lon": -122.4180},
    "together": {"city": "San Francisco, CA", "lat": 37.7680, "lon": -122.4050},
    "huggingface": {"city": "New York, NY", "lat": 40.7484, "lon": -73.9967},
    "cloudflare": {"city": "San Francisco, CA", "lat": 37.7806, "lon": -122.3900},
}

HUB_LOCATION = {"city": "Montreal, QC", "lat": 45.5017, "lon": -73.5673}


# ---------------------------------------------------------------------------
# Node Management
# ---------------------------------------------------------------------------


def list_nodes():
    """Return all nodes with status, hardware, location.

    Returns list of dicts with: id, node_name, hostname, status,
    gpu_model, gpu_vram_gb, ram_gb, latitude, longitude,
    last_heartbeat, deployment_mode, mesh_ip, region.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, node_name, hostname, status,
                   gpu_model, gpu_vram_gb, ram_gb, cpu_model,
                   latitude, longitude, last_heartbeat,
                   deployment_mode, mesh_ip, region,
                   extra_capabilities
            FROM remote_nodes
            ORDER BY node_name
            """
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_node_status(node_id):
    """Get detailed node status including deployed agents and loaded models.

    Returns dict with node info + agents list + agent_count.
    Returns None if node not found.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, node_name, hostname, status,
                   gpu_model, gpu_vram_gb, ram_gb,
                   latitude, longitude, last_heartbeat,
                   deployment_mode, mesh_ip, region,
                   cpu_model, os_info
            FROM remote_nodes
            WHERE id = %s
            """,
            (node_id,),
        )
        node = cur.fetchone()
        if not node:
            return None

        result = dict(node)
        result["agents"] = get_node_agents(node_id)
        result["agent_count"] = len(result["agents"])

        # Count loaded models from model_load_state if available
        try:
            cur.execute(
                """
                SELECT COUNT(*) as model_count
                FROM model_load_state
                WHERE host = %s AND is_loaded = true
                """,
                (result.get("hostname", ""),),
            )
            row = cur.fetchone()
            result["loaded_model_count"] = row["model_count"] if row else 0
        except Exception:
            result["loaded_model_count"] = 0

        return result


def get_node_agents(node_id):
    """Get agents deployed to a specific node.

    Returns list from node_agents joined with agents table for
    display_name, department.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT na.id, na.hub_agent_id, na.source_agent_id,
                   na.node_id, na.status, na.model, na.created_at,
                   na.display_name AS node_display_name,
                   a.display_name, a.name AS agent_code_name, a.department
            FROM node_agents na
            LEFT JOIN agents a ON a.id = COALESCE(na.hub_agent_id, na.source_agent_id)
            WHERE na.node_id = %s
            ORDER BY a.display_name
            """,
            (node_id,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cloud Provider Management
# ---------------------------------------------------------------------------


def list_providers():
    """Return all cloud providers with status, tier, capabilities, and usage.

    Joins contractor_providers with external_api_keys for budget info.
    Returns list with: provider_key, base_url, default_model, tier_position,
    capabilities, is_active, monthly_budget_usd, current_month_cost_usd.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT cp.id, cp.provider_key, cp.base_url, cp.default_model,
                   cp.tier_position, cp.capabilities, cp.is_active,
                   eak.monthly_budget_usd, eak.current_month_cost_usd
            FROM contractor_providers cp
            LEFT JOIN external_api_keys eak
                ON eak.provider = cp.provider_key
            ORDER BY cp.tier_position, cp.provider_key
            """
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            row = dict(r)
            row["monthly_budget_usd"] = (
                float(row["monthly_budget_usd"]) if row["monthly_budget_usd"] is not None else None
            )
            row["current_month_cost_usd"] = (
                float(row["current_month_cost_usd"]) if row["current_month_cost_usd"] is not None else None
            )
            result.append(row)
        return result


def get_provider_status(provider_key):
    """Get detailed provider status including pricing and recent usage.

    Returns provider info + pricing rows + usage summary (last 30 days).
    Returns None if provider not found.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT cp.id, cp.provider_key, cp.base_url, cp.default_model,
                   cp.tier_position, cp.capabilities, cp.is_active,
                   eak.monthly_budget_usd, eak.current_month_cost_usd
            FROM contractor_providers cp
            LEFT JOIN external_api_keys eak
                ON eak.provider = cp.provider_key
            WHERE cp.provider_key = %s
            """,
            (provider_key,),
        )
        provider = cur.fetchone()
        if not provider:
            return None

        result = dict(provider)
        result["monthly_budget_usd"] = (
            float(result["monthly_budget_usd"]) if result.get("monthly_budget_usd") is not None else None
        )
        result["current_month_cost_usd"] = (
            float(result["current_month_cost_usd"]) if result.get("current_month_cost_usd") is not None else None
        )

        # Get pricing rows
        cur.execute(
            """
            SELECT model, input_cost_per_1m, output_cost_per_1m
            FROM provider_pricing
            WHERE provider = %s
            ORDER BY model
            """,
            (provider_key,),
        )
        result["pricing"] = [dict(r) for r in cur.fetchall()]

        # Get usage summary (last 30 days)
        result["usage"] = get_usage_summary(provider_key=provider_key, days=30)

        return result


def get_usage_summary(provider_key=None, days=30):
    """Get usage summary from cloud_model_usage.

    If provider_key given, filter to that provider.
    Returns: total_calls, total_tokens, total_cost, by_model breakdown.
    """
    with get_db_cursor() as (conn, cur):
        where_clause = "WHERE created_at >= NOW() - INTERVAL '%s days'"
        params = [days]

        if provider_key:
            where_clause += " AND provider = %s"
            params.append(provider_key)

        # Totals
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_calls,
                COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS total_tokens,
                COALESCE(SUM(cost_usd), 0) AS total_cost
            FROM cloud_model_usage
            {where_clause}
            """,
            params,
        )
        row = cur.fetchone()
        result = {
            "total_calls": row["total_calls"] if row else 0,
            "total_tokens": int(row["total_tokens"]) if row else 0,
            "total_cost": float(row["total_cost"]) if row else 0.0,
        }

        # By-model breakdown
        cur.execute(
            f"""
            SELECT model_name,
                   COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens,
                   COALESCE(SUM(cost_usd), 0) AS cost
            FROM cloud_model_usage
            {where_clause}
            GROUP BY model_name
            ORDER BY cost DESC
            """,
            params,
        )
        result["by_model"] = [
            {
                "model": r["model_name"],
                "calls": r["calls"],
                "tokens": int(r["tokens"]),
                "cost": float(r["cost"]),
            }
            for r in cur.fetchall()
        ]

        # Distinct providers actually used (exclude local fleet labels)
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT provider) AS cnt
            FROM cloud_model_usage
            {where_clause}
            AND provider NOT IN ('ollama_cloud', 'ollama_local')
            """,
            params,
        )
        row2 = cur.fetchone()
        result["distinct_providers"] = int(row2["cnt"]) if row2 else 0

        # Total registered providers
        cur.execute("SELECT COUNT(*) AS cnt FROM contractor_providers")
        row3 = cur.fetchone()
        result["registered_providers"] = int(row3["cnt"]) if row3 else 0

        return result


# ---------------------------------------------------------------------------
# Fleet Map Data
# ---------------------------------------------------------------------------


def get_fleet_map_data():
    """Return all map pins for the fleet visualization.

    Returns dict with:
    - hub: {name, lat, lon, status}
    - nodes: [{name, hostname, lat, lon, status, gpu, ram, deployment_mode}]
    - providers: [{provider_key, city, lat, lon, is_active, tier, budget, usage, capabilities}]
    """
    # Hub
    hub = {
        "name": "A.R.C.H.I.E. Hub",
        "lat": HUB_LOCATION["lat"],
        "lon": HUB_LOCATION["lon"],
        "city": HUB_LOCATION["city"],
        "status": "online",
    }

    # Nodes from DB
    nodes_raw = list_nodes()
    nodes = []
    for n in nodes_raw:
        node_id = n.get("id")
        agents = get_node_agents(node_id) if node_id else []
        caps = n.get("extra_capabilities") or {}
        nodes.append(
            {
                "node_id": node_id,
                "name": n.get("node_name", "Unknown"),
                "hostname": n.get("hostname", ""),
                "lat": (
                    float(n["latitude"])
                    if n.get("latitude")
                    else (float(caps["geo_lat"]) if caps.get("geo_lat") else None)
                ),
                "lon": (
                    float(n["longitude"])
                    if n.get("longitude")
                    else (float(caps["geo_lon"]) if caps.get("geo_lon") else None)
                ),
                "status": n.get("status", "unknown"),
                "gpu": n.get("gpu_model", ""),
                "gpu_vram_gb": n.get("gpu_vram_gb"),
                "ram": n.get("ram_gb"),
                "cpu_model": n.get("cpu_model", "") or caps.get("cpu_model", ""),
                "mesh_ip": n.get("mesh_ip", ""),
                "last_heartbeat": (n["last_heartbeat"].isoformat() if n.get("last_heartbeat") else None),
                "deployment_mode": n.get("deployment_mode", ""),
                # Enriched from extra_capabilities
                "region": n.get("region") or caps.get("region", ""),
                "provider": caps.get("provider", ""),
                "location_city": caps.get("location_city", ""),
                "location_country": caps.get("location_country", ""),
                "inference_type": caps.get("inference_type", "gpu"),
                "max_model_gb": caps.get("max_model_gb"),
                "ollama_models": caps.get("ollama_models", []),
                "agents": [
                    {
                        "hub_agent_id": a.get("hub_agent_id"),
                        "display_name": a.get("display_name") or a.get("node_display_name", "Unknown"),
                        "department": a.get("department", ""),
                        "status": a.get("status", ""),
                    }
                    for a in agents
                ],
            }
        )

    # Cloud providers
    providers_raw = list_providers()
    providers = []
    for p in providers_raw:
        key = p.get("provider_key", "")
        loc = PROVIDER_LOCATIONS.get(key, {})
        providers.append(
            {
                "provider_key": key,
                "city": loc.get("city", "Unknown"),
                "lat": loc.get("lat"),
                "lon": loc.get("lon"),
                "is_active": p.get("is_active", False),
                "tier": p.get("tier_position"),
                "budget": float(p["monthly_budget_usd"]) if p.get("monthly_budget_usd") else None,
                "usage": float(p["current_month_cost_usd"]) if p.get("current_month_cost_usd") else None,
                "capabilities": p.get("capabilities"),
            }
        )

    return {"hub": hub, "nodes": nodes, "providers": providers}


# ---------------------------------------------------------------------------
# Cloud Provider Management (Phase 3)
# ---------------------------------------------------------------------------


def register_provider(
    name,
    provider_type="cloud",
    api_key_env_var="",
    tier="free",
    capabilities=None,
    models_available=None,
    api_endpoint="",
    headquarters_city="",
    latitude=None,
    longitude=None,
    monthly_budget=0,
):
    """Register a new cloud provider. Returns provider id."""
    from psycopg2.extras import Json

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO cloud_providers
               (name, provider_type, api_key_env_var, tier,
                capabilities, models_available, api_endpoint,
                headquarters_city, latitude, longitude, monthly_budget)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                name,
                provider_type,
                api_key_env_var,
                tier,
                Json(capabilities or []),
                Json(models_available or []),
                api_endpoint,
                headquarters_city,
                latitude,
                longitude,
                monthly_budget,
            ),
        )
        return cur.fetchone()["id"]


def get_cloud_provider(provider_id):
    """Get a single cloud provider by id. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM cloud_providers WHERE id = %s", (provider_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_cloud_providers():
    """List all cloud providers from the cloud_providers table."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM cloud_providers ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


def record_cloud_usage(
    provider_id,
    model_name,
    tokens_in=0,
    tokens_out=0,
    estimated_cost=0,
    capability="",
    agent_id=None,
):
    """Record a cloud API call and update the provider's monthly usage."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO cloud_usage_log
               (provider_id, agent_id, model_name, tokens_in, tokens_out,
                estimated_cost, capability)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                provider_id,
                agent_id,
                model_name,
                tokens_in,
                tokens_out,
                estimated_cost,
                capability,
            ),
        )
        cur.execute(
            """UPDATE cloud_providers
               SET monthly_usage = COALESCE(monthly_usage, 0) + %s,
                   updated_at = NOW()
               WHERE id = %s""",
            (estimated_cost, provider_id),
        )


def disconnect_node(node_id):
    """Mark a node as offline and return its agents to barracks."""
    from services import agent_service

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT node_name FROM remote_nodes WHERE id = %s", (node_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Node {node_id} not found"}

        node_name = row["node_name"]
        cur.execute(
            "UPDATE remote_nodes SET status = 'offline' WHERE id = %s",
            (node_id,),
        )

        cur.execute(
            """UPDATE node_agents SET status = 'recalled'
               WHERE node_id = (SELECT node_id FROM remote_nodes WHERE id = %s)
               AND status = 'active'
               RETURNING hub_agent_id""",
            (node_id,),
        )
        recalled = cur.fetchall()

    # Single-writer path: agents.shift_state transition goes through
    # agent_service.barracks() so the agents table only has one canonical
    # mutation surface (Project #241 Track C.1).
    for r in recalled:
        if r["hub_agent_id"]:
            agent_service.barracks(r["hub_agent_id"])

    logger.info(
        "fleet_service: disconnected %s, recalled %d agents",
        node_name,
        len(recalled),
    )
    return {
        "success": True,
        "node_name": node_name,
        "recalled_agents": len(recalled),
    }
