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
    """Update all Hostinger DNS A records pointing to hub to new IP.

    Uses Hostinger API v1 zone update format:
    zone: [{name, type, ttl, records: [{content}]}]
    Only updates A records that point to a known old hub IP.
    """
    import os

    import requests

    updated = []
    # Use HOSTINGER_API_KEY — same credential used by hostinger_service.py + deploy skill
    api_token = os.getenv("HOSTINGER_API_KEY", "") or os.getenv("HOSTINGER_API_TOKEN", "")
    if not api_token:
        logger.error("DDNS: No HOSTINGER_API_KEY set")
        return updated

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT DISTINCT root_domain FROM org_domains
            WHERE dns_provider = 'hostinger' AND dns_status = 'verified'
        """
        )
        root_domains = [r["root_domain"] for r in cur.fetchall()]

        # Get known old IPs to match against
        cur.execute("SELECT ip_address FROM org_ip_history ORDER BY detected_at DESC LIMIT 5")
        old_ips = {r["ip_address"] for r in cur.fetchall()}

    for root in root_domains:
        try:
            # Get current records
            resp = requests.get(
                f"https://developers.hostinger.com/api/dns/v1/zones/{root}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error("DDNS: Failed to get DNS for %s: %s", root, resp.status_code)
                continue

            records = resp.json()
            # Build zone update — only update A records pointing to old hub IPs
            zone_updates = []
            for rec in records:
                if rec.get("type") == "A":
                    for entry in rec.get("records", []):
                        if entry.get("content") in old_ips:
                            zone_updates.append(
                                {
                                    "name": rec["name"],
                                    "type": "A",
                                    "ttl": rec.get("ttl", 14400),
                                    "records": [{"content": new_ip}],
                                }
                            )
                            updated.append(f"{rec['name']}.{root}")

            if zone_updates:
                put_resp = requests.put(
                    f"https://developers.hostinger.com/api/dns/v1/zones/{root}",
                    headers=headers,
                    json={"overwrite": True, "zone": zone_updates},
                    timeout=10,
                )
                if put_resp.status_code not in (200, 201, 204):
                    logger.error(
                        "DDNS: Failed to update DNS for %s: %s %s",
                        root,
                        put_resp.status_code,
                        put_resp.text[:200],
                    )

        except Exception as e:
            logger.error("Failed to update DNS for %s: %s", root, e)

    return updated
