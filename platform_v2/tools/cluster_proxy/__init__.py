"""Cluster Proxy — hub-as-egress HTTP proxy for VPS fleet nodes.

VPS products (gov-watch, civic-watch, etc.) route blocked external
HTTP requests through this endpoint so the hub's residential IP
is used instead of the Hostinger datacenter IP.

Usage from VPS:
    POST http://192.168.1.200:3000/api/proxy/fetch
    Headers: X-Proxy-Key: <CLUSTER_PROXY_KEY>
    Body: {"url": "https://open.canada.ca/...", "method": "GET"}
"""

from .routes import register_proxy_routes

__all__ = ["register_proxy_routes"]
