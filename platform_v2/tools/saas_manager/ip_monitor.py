"""
A.R.C.H.I.E. Platform - Public IP Monitor
==========================================

Periodically checks the server's public IP address.
On change: logs to org_ip_history, updates all Hostinger DNS records.
"""

import logging
import urllib.request

from database import get_db_cursor

logger = logging.getLogger(__name__)

_IP_PROVIDERS = [
    "https://api.ipify.org",
    "https://ifconfig.me",
    "https://icanhazip.com",
]


def get_public_ip():
    """Detect current public IP using multiple providers for redundancy."""
    for url in _IP_PROVIDERS:
        try:
            return urllib.request.urlopen(url, timeout=5).read().decode().strip()
        except Exception:
            continue
    raise RuntimeError("Could not detect public IP from any provider")


def check_and_update_ip():
    """
    Check public IP. If changed, log and update DNS records.

    Returns:
        dict with current_ip, changed, old_ip, updated_domains
    """
    current_ip = get_public_ip()

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT ip_address FROM org_ip_history ORDER BY detected_at DESC LIMIT 1")
        last = cur.fetchone()
        old_ip = last["ip_address"] if last else None
        changed = old_ip != current_ip

        if changed:
            cur.execute("INSERT INTO org_ip_history (ip_address) VALUES (%s)", (current_ip,))
            logger.info("Public IP changed: %s -> %s", old_ip, current_ip)

    updated_domains = []
    if changed and old_ip:
        updated_domains = _update_dns_records(current_ip)

    return {
        "current_ip": current_ip,
        "changed": changed,
        "old_ip": old_ip,
        "updated_domains": updated_domains,
    }


def _update_dns_records(new_ip):
    """Update all Hostinger DNS A records to point to new IP."""
    from hostinger_integration import get_hostinger_api

    updated = []
    api = get_hostinger_api()

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT DISTINCT root_domain FROM org_domains
            WHERE dns_provider = 'hostinger' AND dns_status = 'verified'
        """
        )
        root_domains = [r["root_domain"] for r in cur.fetchall()]

    for root in root_domains:
        try:
            records = api.get_dns_records(root)
            if records.get("success"):
                for rec in records.get("data", []):
                    if rec.get("type") == "A":
                        api.update_dns_record(
                            domain=root,
                            record_id=rec["id"],
                            record_type="A",
                            name=rec["name"],
                            content=new_ip,
                            ttl=rec.get("ttl", 3600),
                        )
                        updated.append(f"{rec['name']}.{root}")
        except Exception as e:
            logger.error("Failed to update DNS for %s: %s", root, e)

    return updated
