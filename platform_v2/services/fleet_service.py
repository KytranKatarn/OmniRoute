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

import json
import logging
import re
import subprocess
import time

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
    # --- added 2026-09-11 ------------------------------------------------
    # The A.R.M.A.D.A. map pinned 6 of 26 active contractors and said "26
    # providers active" next to them. Three of the twenty misses were pure KEY
    # mismatches — the coordinates were already sitting here under a name no
    # provider row uses. `anthropic`, `cloudflare`, `grok`, `google` and
    # `ollama` above match NOTHING in contractor_providers; the real keys are:
    "claude": {"city": "San Francisco, CA", "lat": 37.7891, "lon": -122.4020},
    "cloudflare_ai": {"city": "San Francisco, CA", "lat": 37.7806, "lon": -122.3900},
    "xai": {"city": "San Francisco, CA", "lat": 37.7750, "lon": -122.4180},
    # Well-known head offices for the rest:
    "groq": {"city": "Mountain View, CA", "lat": 37.3900, "lon": -122.0800},
    "perplexity": {"city": "San Francisco, CA", "lat": 37.7850, "lon": -122.4000},
    "deepseek": {"city": "Hangzhou, China", "lat": 30.2741, "lon": 120.1551},
    "qwen3_cloud": {"city": "Hangzhou, China", "lat": 30.2500, "lon": 120.2100},
    "minimax_cloud": {"city": "Shanghai, China", "lat": 31.2304, "lon": 121.4737},
    "replicate": {"city": "San Francisco, CA", "lat": 37.7700, "lon": -122.4130},
    "replicate_audio": {"city": "San Francisco, CA", "lat": 37.7700, "lon": -122.4130},
    "fal_ai": {"city": "San Francisco, CA", "lat": 37.7820, "lon": -122.4090},
    "cerebras": {"city": "Sunnyvale, CA", "lat": 37.3688, "lon": -122.0363},
    "stability_ai": {"city": "London, UK", "lat": 51.5074, "lon": -0.1278},
    "stability_audio": {"city": "London, UK", "lat": 51.5074, "lon": -0.1278},
    "elevenlabs": {"city": "New York, NY", "lat": 40.7128, "lon": -74.0060},
    # Self-hosted: these run on OUR hardware, so the hub is not an approximation
    # here — it is the literal location.
    "comfyui": {"city": "Montreal, QC", "lat": 45.5017, "lon": -73.5673},
    "ollama_diffuser": {"city": "Montreal, QC", "lat": 45.5017, "lon": -73.5673},
    # ⚠️ omniroute is SELF-HOSTED, not a third-party router. Its row reads
    # "OmniRoute (self-hosted gateway)" and its base_url is
    # http://omniroute:20128/v1 — a Docker service name, i.e. a container on the
    # hub (verified running, 2026-09-11). It was first excluded here on the
    # strength of the word "route" in its name, alongside OpenRouter; reading the
    # base_url settles it. The hub is its literal location.
    "omniroute": {"city": "Montreal, QC", "lat": 45.5017, "lon": -73.5673},
    # DELIBERATELY ABSENT — openrouter and pollinations. openrouter
    # (openrouter.ai) is a genuine third-party ROUTER: it brokers to whichever
    # upstream wins, so it has no single inference location and pinning it to an
    # office would draw a fact that is not true. pollinations
    # (image.pollinations.ai) has no location I can confirm, and inventing one
    # for a map is fabricating data. They stay unmapped, and the panel's label
    # says "N of M contractors mapped" instead of implying every row has a pin.
}

# ⚠️ A head office is NOT where inference runs — a US provider serves from
# datacenters worldwide. These pins show WHO the fleet can reach, not where the
# GPU is. The convention predates this dict's expansion; it is kept, not fixed,
# because per-request datacenter attribution is not something we measure.

HUB_LOCATION = {"city": "Montreal, QC", "lat": 45.5017, "lon": -73.5673}


# Providers whose MODELS run on our own GPUs. Deliberately a short explicit set,
# because it is NOT derivable: omniroute and claude are also reached at an
# address we own, but they broker to someone else's compute. A panel that calls
# all four "hosted" is claiming we run Claude, which we do not.
LOCAL_COMPUTE_PROVIDERS = frozenset({"comfyui", "ollama_diffuser"})


def is_self_hosted_url(base_url):
    """True when we call this provider at an address on our OWN infrastructure.

    Derived from the URL, never from a name list, so adding a self-hosted
    provider needs no code change. The four live cases are all distinguishable
    this way (measured 2026-09-11):

        http://archie_comfyui:8188    docker service name — no dot in the host
        http://archie_diffuser:11435  docker service name
        http://omniroute:20128/v1     docker service name
        http://localhost:7682/v1      loopback

    versus every external one, which is an https:// public FQDN.

    ⚠️ SELF-HOSTED IS ABOUT THE ENDPOINT, NOT THE COMPUTE. omniroute is a
    gateway and claude is a local proxy to Anthropic — both answer here, both
    do their thinking elsewhere. Use ``LOCAL_COMPUTE_PROVIDERS`` for the
    stronger claim.

    Fail-safe: anything unparseable reads as EXTERNAL. Mislabelling a cloud API
    as ours understates where data goes, which is the expensive direction.
    """
    if not base_url:
        return False
    try:
        raw = str(base_url).strip()
        # sentinel values that are not URLs at all (qwen3_cloud/minimax_cloud
        # carry "ollama_cloud_proxy") are external by definition
        if "://" not in raw:
            return False
        host = raw.split("://", 1)[1].split("/", 1)[0].split("@")[-1]
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        host = host.strip("[]").lower()
        # ⚠️ An EMPTY host must be external. "://" parses to host "" which has
        # no dot, so the bare-docker-service rule below fires and calls it ours
        # — fail-OPEN, in the one direction that understates where data goes.
        if not host:
            return False
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return True
        if "." not in host:  # bare docker service name
            return True
        if host.endswith(".local") or host.endswith(".internal"):
            return True
        octets = host.split(".")
        if len(octets) == 4 and all(o.isdigit() for o in octets):
            a, b = int(octets[0]), int(octets[1])
            # RFC1918 + the 100.64.0.0/10 Headscale mesh
            if a == 10 or a == 127:
                return True
            if a == 172 and 16 <= b <= 31:
                return True
            if a == 192 and b == 168:
                return True
            if a == 100 and 64 <= b <= 127:
                return True
        return False
    except Exception:  # noqa: BLE001 — a display classifier never raises
        return False


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


def live_nodes():
    """Nodes that still EXIST — the accessor any display panel should use.

    ``list_nodes()`` deliberately returns every row, retired hardware included,
    because node MANAGEMENT needs to see a retired node to act on it. Every
    read-only panel wants the opposite, and on 2026-09-11 the A.R.M.A.D.A. fleet
    map was rendering Beacon plus the three EU/Asia outposts retired on
    2026-08-29 — machines whose subscriptions are cancelled — as live pins and
    index entries.

    That is the THIRD instance of this exact shape: LOADED MODELS rendered the
    same three outposts from ``model_load_state`` (#3290), and NODE HEALTH on
    the same page filtered correctly all along. The bug is never the table — it
    is each panel deciding for itself whether to filter. This is the one place
    to decide it.

    ⚠️ Not a hard-coded name list: it filters on ``status``, so retiring the
    next node needs no code change. ``retired`` is the only excluded value —
    ``offline``/``unknown`` nodes still render, because a node that is down is
    news and a node that no longer exists is noise.
    """
    return [n for n in list_nodes() if (n.get("status") or "").lower() != "retired"]


# ---------------------------------------------------------------------------
# Headscale mesh — who is CONNECTED, which is a different question from who
# runs work. The A.R.M.A.D.A. map only ever read remote_nodes, so a device on
# the mesh with no fleet row could not appear at any zoom: on 2026-09-11
# headscale had 7 members online while the map drew 5. The two invisible ones
# were shuttle-kytran (100.64.0.9, a personal device) and archie-starbase-subnet
# (100.64.0.1, the archie_tailscale LAN subnet router).
# ---------------------------------------------------------------------------

_MESH_TTL_S = 60.0
_mesh_cache = {"at": 0.0, "rows": []}


def _mesh_tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]


def _norm_name(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def mesh_members():
    """Headscale's view of the tailnet. FAIL-SAFE: never raises, never blocks.

    Shells to the headscale container the same way the authkey route already
    does (fleet_mesh_routes.py) — archie_platform mounts the docker socket.

    ⚠️ On ANY failure this returns the LAST GOOD list, or [] if there has never
    been one. A mesh section that vanishes is honest; a fleet map that 500s
    because a side panel could not reach headscale is not. Cached for 60s
    because /api/fleet-map is on a 30s refresh and this is a subprocess.
    """
    now = time.monotonic()
    if _mesh_cache["rows"] and (now - _mesh_cache["at"]) < _MESH_TTL_S:
        return _mesh_cache["rows"]
    try:
        out = subprocess.run(
            ["docker", "exec", "archie_headscale", "headscale", "nodes", "list", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0:
            logger.debug("mesh_members: headscale exited %s", out.returncode)
            return _mesh_cache["rows"]
        rows = json.loads(out.stdout)
    except Exception as exc:  # noqa: BLE001 — a display source never breaks its caller
        logger.debug("mesh_members: unavailable (%s)", exc)
        return _mesh_cache["rows"]

    members = []
    for m in rows or []:
        ips = m.get("ip_addresses") or []
        members.append(
            {
                "name": m.get("given_name") or m.get("name") or "unknown",
                "mesh_ip": next((i for i in ips if ":" not in i), ""),
                "online": bool(m.get("online")),
            }
        )
    _mesh_cache.update(at=now, rows=members)
    return members


def mesh_only_members(nodes):
    """Mesh members that are NOT one of the fleet nodes we already draw.

    Matched by mesh IP first, then by NAME — every alphanumeric token of the
    headscale given_name appearing in the node's name. Both are needed, measured
    against the live tailnet:

      starship-246   -> IP 100.64.0.3 matches remote_nodes            (IP)
      archie-starbase-> its row stores mesh_ip 'host.docker.internal',
                        which is not a mesh IP at all, so ONLY the name
                        rescues the hub from listing as a stranger  (NAME)
      shuttle-kytran -> neither matches; genuinely mesh-only

    ⚠️ The 'host.docker.internal' value in remote_nodes.mesh_ip for the hub is a
    DATA BUG (headscale says 100.64.0.4). The name fallback hides it here rather
    than fixing it — deliberately, because remote_nodes is fleet identity and
    correcting a row is the owner's call, not a side effect of a UI change.
    """
    ips = {(n.get("mesh_ip") or "").strip() for n in (nodes or [])}
    ips.discard("")
    names = [_norm_name(n.get("name") or n.get("node_name")) for n in (nodes or [])]
    out = []
    for m in mesh_members():
        if m["mesh_ip"] and m["mesh_ip"] in ips:
            continue
        toks = _mesh_tokens(m["name"])
        if toks and any(all(t in nm for t in toks) for nm in names):
            continue
        out.append(m)
    return out


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

    # Nodes from DB — live only; a retired node is not a place work can run
    nodes_raw = live_nodes()
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
                # Where we CONNECT (derived from base_url) and, separately,
                # whether the model actually runs here. A self-hosted endpoint
                # sits at the hub, so the panel lists it under HOSTED instead of
                # dropping a fourth pin on top of the hub marker.
                "self_hosted": is_self_hosted_url(p.get("base_url")),
                "local_compute": key in LOCAL_COMPUTE_PROVIDERS,
            }
        )

    # ── ONE hub, not two ────────────────────────────────────────────────
    # `hub` above is hardcoded from HUB_LOCATION, and remote_nodes ALSO carries a
    # real row for the same machine ("Archie Starbase", deployment_mode
    # 'starbase'). They sat 22 m apart (45.5017/-73.5673 vs 45.5019/-73.5674),
    # so the tab drew two pins and listed two rows for ONE computer — while the
    # stat line said 5 nodes and the index showed 6.
    #
    # The DB row wins: it is the canonical identity every other panel shows, and
    # it carries real hardware/status/heartbeat instead of a frozen literal. The
    # row is flagged is_hub so a renderer can draw it once; it STAYS in `nodes`
    # so the fleet count keeps counting the machine it is.
    #
    # ⚠️ EXACT match on 'starbase'. Citadel is 'starbase_outpost', and a
    # substring test ("starbase" in mode) flags it as a second hub — the same
    # class of bug as everything else on this tab: a check that is nearly right.
    hub_node = next((n for n in nodes if (n.get("deployment_mode") or "") == "starbase"), None)
    if hub_node:
        hub_node["is_hub"] = True
        hub = dict(
            hub,
            name=hub_node.get("name") or hub["name"],
            lat=hub_node.get("lat") if hub_node.get("lat") is not None else hub["lat"],
            lon=hub_node.get("lon") if hub_node.get("lon") is not None else hub["lon"],
            status=hub_node.get("status") or hub["status"],
            node_id=hub_node.get("node_id"),
        )

    return {"hub": hub, "nodes": nodes, "providers": providers, "mesh": mesh_only_members(nodes)}


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
