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
                    """SELECT node_name, mesh_ip
                       FROM remote_nodes
                       WHERE status = 'online'
                         AND mesh_ip IS NOT NULL
                         AND heartbeat > NOW() - INTERVAL '2 minutes'
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
