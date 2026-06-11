from urllib.parse import urlparse

_GOV_SUFFIXES = (
    ".gc.ca",
    ".canada.ca",
    ".gouv.qc.ca",
    ".seao.ca",
    ".bcbid.gov.bc.ca",
    ".canlii.org",
    ".tpsgc-pwgsc.gc.ca",
)


def select_egress(target_url: str, requested_tier: int = None) -> int:
    if requested_tier is not None:
        return requested_tier
    try:
        domain = urlparse(target_url).netloc.lower()
    except Exception:
        return 1
    for suffix in _GOV_SUFFIXES:
        if domain.endswith(suffix) or domain == suffix.lstrip("."):
            return 1
    return 1  # safe default: hub residential


import logging as _logging

_fleet_logger = _logging.getLogger(__name__)

try:
    from database import get_db  # available inside the scraper container
except ImportError:  # test environments without the DB module
    get_db = None  # type: ignore[assignment]


def discover_fleet_egress() -> list:
    """Query remote_nodes for online fleet nodes — each becomes a Tier 4 egress slot.

    Returns list of {tier, proxy, label} dicts.
    Called every 5 minutes by browser_pool refresh thread.
    """
    try:
        if get_db is None:
            raise RuntimeError("database module not available")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    # column is last_heartbeat (was 'heartbeat' — #4007 fix)
                    """SELECT node_name, mesh_ip
                       FROM remote_nodes
                       WHERE status = 'online'
                         AND mesh_ip IS NOT NULL
                         AND last_heartbeat > NOW() - INTERVAL '2 minutes'
                       ORDER BY node_name""",
                )
                rows = cur.fetchall()
        return [
            {
                "tier": 4,
                "proxy": f"socks5://{r['mesh_ip']}:1080",
                "label": r["node_name"],
            }
            for r in rows
        ]
    except Exception as exc:
        _fleet_logger.warning("Fleet egress discovery failed: %s", exc)
        return []


# ── Per-session egress resolution (#4007 — browse-from-country) ──────────
# A cookie session can declare which outpost its authenticated fetches egress
# through (browser_sessions.egress_pref = a remote_nodes.node_name). Resolve it
# to a SOCKS5 proxy string; PREFERENCE-NOT-PIN — an unset pref, an offline node,
# or a node that doesn't advertise socks5_egress all fall back to hub (None).

import os as _os  # noqa: E402

_SOCKS_USER = _os.getenv("SCOUT_SOCKS_USER", "")
_SOCKS_PASS = _os.getenv("SCOUT_SOCKS_PASS", "")


def _socks_url(mesh_ip: str) -> str:
    auth = f"{_SOCKS_USER}:{_SOCKS_PASS}@" if (_SOCKS_USER and _SOCKS_PASS) else ""
    return f"socks5://{auth}{mesh_ip}:1080"


def resolve_session_egress(agent_id: int, platform: str, explicit_node: str = None):
    """Return a SOCKS5 proxy string for this session's egress, or None (= hub).

    Order: explicit_node (caller pin) → session egress_pref → hub. Only nodes
    that are online AND advertise extra_capabilities.socks5_egress=true resolve
    to a proxy; everything else returns None so the fetch goes hub-direct.
    """
    try:
        if get_db is None:
            return None
        target = (explicit_node or "").strip() or None
        with get_db() as conn:
            with conn.cursor() as cur:
                if target is None:
                    cur.execute(
                        "SELECT egress_pref FROM browser_sessions WHERE agent_id=%s AND platform=%s",
                        (agent_id, platform),
                    )
                    r = cur.fetchone()
                    target = (r["egress_pref"] if r else None) or None
                if not target or target.lower() in ("hub", "auto"):
                    return None
                cur.execute(
                    """SELECT mesh_ip
                         FROM remote_nodes
                        WHERE node_name = %s
                          AND status = 'online'
                          AND mesh_ip IS NOT NULL
                          AND last_heartbeat > NOW() - INTERVAL '2 minutes'
                          AND (extra_capabilities->>'socks5_egress') = 'true'""",
                    (target,),
                )
                node = cur.fetchone()
        if not node:
            _fleet_logger.info(
                "egress pref '%s' for %s/%s not resolvable (offline/unready) — hub fallback",
                target, agent_id, platform,
            )
            return None
        return _socks_url(node["mesh_ip"])
    except Exception as exc:
        _fleet_logger.warning("resolve_session_egress failed (%s) — hub fallback", type(exc).__name__)
        return None
