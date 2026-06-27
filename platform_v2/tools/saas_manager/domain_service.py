"""
A.R.C.H.I.E. Platform - Domain Service
=======================================

Automates domain setup:
1. DNS record creation via Hostinger API
2. DNS propagation verification

NPM proxy-host creation + Let's-Encrypt-via-NPM SSL steps were removed
2026-06-27 (NPM decommissioned; Beacon/Caddy is the hub front door and handles
external ingress + SSL). ADR-853 / KB #276161.
"""

import logging

logger = logging.getLogger(__name__)


def setup_domain(domain_row, public_ip):
    """
    Domain setup: Hostinger DNS A record.

    Proxy/SSL provisioning via Nginx Proxy Manager was removed —
    Beacon/Caddy is the front door now.

    Args:
        domain_row: dict from org_domains table
        public_ip: Server's current public IP

    Returns:
        dict with status of each step
    """
    from services.hostinger_integration import get_hostinger_api

    result = {"dns": None, "proxy": None, "ssl": None}
    subdomain = domain_row["subdomain"]
    root_domain = domain_row["root_domain"]

    # Step 1: Hostinger DNS
    try:
        api = get_hostinger_api()
        dns_result = api.add_dns_record(
            domain=root_domain,
            record_type="A",
            name=subdomain or "@",
            value=public_ip,
            ttl=3600,
        )
        result["dns"] = {"success": True, "record": dns_result}
    except Exception as e:
        result["dns"] = {"success": False, "error": str(e)}

    return result


def cleanup_domain(domain, npm_proxy_host_id=None):
    """Remove a domain. (Proxy-host teardown removed — Beacon/Caddy is the front door now.)

    npm_proxy_host_id is accepted for backward compatibility but ignored.
    """
    logger.info("Domain %s removed. Check Hostinger DNS manually if needed.", domain)
