"""
A.R.C.H.I.E. Fleet Proxy — Subdomain routing for B.E.A.C.O.N. dashboards
==========================================================================
Routes *.fleet.kytranempowerment.com requests to the correct node's BEACON
dashboard via mesh VPN or LAN IP.

Registered as a before_request handler on the Flask app.
When the Host header matches *.fleet.*, extracts the node name,
looks up its address, and proxies the request to node:3001.
"""

import logging
import re

import requests as http_requests
from flask import request, Response, abort

logger = logging.getLogger("archie.fleet_proxy")

FLEET_DOMAIN_PATTERN = re.compile(
    r"^([a-z0-9][a-z0-9\-]*)\.fleet\.kytranempowerment\.com",
    re.IGNORECASE,
)

# Cache node name → address mapping (refreshed every 60s by mesh health job)
_node_cache = {}
_cache_age = 0


def _lookup_node_address(node_name):
    """Look up a node's best reachable address by name (case-insensitive)."""
    import time

    global _node_cache, _cache_age

    # Refresh cache every 30s
    if time.time() - _cache_age > 30 or not _node_cache:
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT node_name, hostname, mesh_ip, vpn_ip
                       FROM remote_nodes
                       WHERE approval_status = 'approved' AND is_active = true"""
                )
                _node_cache = {}
                for row in cur.fetchall():
                    name = (row["node_name"] or "").lower().replace(" ", "-")
                    addr = row.get("mesh_ip") or row.get("hostname") or row.get("vpn_ip")
                    if name and addr:
                        _node_cache[name] = addr
            _cache_age = time.time()
        except Exception as e:
            logger.warning("Fleet proxy cache refresh failed: %s", e)

    # Try exact match, then fuzzy
    key = node_name.lower().replace(" ", "-")
    return _node_cache.get(key)


def fleet_proxy_handler():
    """before_request handler — intercepts *.fleet.* subdomain requests."""
    host = request.host.split(":")[0]  # Strip port
    match = FLEET_DOMAIN_PATTERN.match(host)
    if not match:
        return None  # Not a fleet subdomain, continue normal routing

    node_name = match.group(1)
    node_addr = _lookup_node_address(node_name)

    if not node_addr:
        abort(404, description=f"Fleet node '{node_name}' not found or offline")

    # Proxy the request to the node's BEACON dashboard
    target_url = f"http://{node_addr}:3001{request.path}"
    if request.query_string:
        target_url += f"?{request.query_string.decode()}"

    try:
        # Forward the request
        resp = http_requests.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() not in ("host", "transfer-encoding")},
            data=request.get_data(),
            timeout=15,
            allow_redirects=False,
        )

        # Build response, preserving status and headers
        excluded_headers = {"transfer-encoding", "content-encoding", "content-length"}
        headers = [(k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded_headers]

        return Response(resp.content, resp.status_code, headers)

    except http_requests.Timeout:
        abort(504, description=f"Fleet node '{node_name}' timed out")
    except http_requests.ConnectionError:
        abort(502, description=f"Fleet node '{node_name}' unreachable")
    except Exception as e:
        logger.error("Fleet proxy error for %s: %s", node_name, e)
        abort(502, description=f"Fleet proxy error: {e}")


def register_fleet_proxy(app):
    """Register the fleet proxy as a before_request handler."""
    app.before_request(fleet_proxy_handler)
    logger.info("Fleet proxy registered for *.fleet.kytranempowerment.com")
