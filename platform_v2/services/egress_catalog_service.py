"""Egress catalog (#4007 — S.C.O.U.T. browse-from-country).

The catalog of egress endpoints a session may route its authenticated fetches
through. Sourced live from `remote_nodes` (mesh-only, never hardcoded) so the
UI offers exactly the online CPU outposts — plus the synthetic 'hub' default.

`egress_ready` reflects whether the node actually runs a SOCKS5 proxy
(extra_capabilities.socks5_egress=true, stamped after the proxy rollout +
exit-IP verification). Nodes that aren't ready are listed but not selectable,
so the UI never offers a dead proxy.
"""

from __future__ import annotations

from typing import Optional

HUB = {
    "node_name": "hub",
    "country": "Canada (hub direct)",
    "region": "local",
    "mesh_ip": None,
    "egress_ready": True,
}


def list_egress_nodes() -> list:
    """Hub + online CPU outposts (region != local, not the ingress beacon)."""
    from database import get_db_cursor

    out = [dict(HUB)]
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT node_name,
                      extra_capabilities->>'region'            AS region,
                      extra_capabilities->>'location_country'  AS country,
                      mesh_ip,
                      (extra_capabilities->>'socks5_egress') = 'true' AS egress_ready
                 FROM remote_nodes
                WHERE status = 'online'
                  AND last_heartbeat > NOW() - INTERVAL '2 minutes'
                  AND mesh_ip IS NOT NULL
                  AND COALESCE(extra_capabilities->>'region', 'local') <> 'local'
                  AND COALESCE(deployment_mode, '') <> 'beacon'
                ORDER BY country, node_name"""
        )
        for r in cur.fetchall():
            d = dict(r)
            d["egress_ready"] = bool(d.get("egress_ready"))
            out.append(d)
    return out


def is_valid_egress(pref: Optional[str]) -> bool:
    """True if pref is hub/auto/None or a currently egress-READY node.

    Validated at set-time so the UI can't pin a session to a dead proxy. A node
    that goes offline LATER is handled at fetch time (preference-not-pin → hub).
    """
    if (pref or "").strip().lower() in {"", "hub", "auto"}:
        return True
    return any(n["node_name"] == pref and n["egress_ready"] for n in list_egress_nodes())
