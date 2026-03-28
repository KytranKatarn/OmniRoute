"""
core/subdomain_manager.py -- Subdomain and custom domain provisioning via Hostinger DNS API.

Provides:
- provision_subdomain(slug) -- creates A record for {slug}.kytranempowerment.com
- provision_custom_domain(domain, tenant_id) -- for paid clients
- check_subdomain_health(slug) -- DNS resolution check
- check_custom_domain_health(domain) -- DNS resolution check

Note: Requires KBS_HOSTINGER_API_KEY env var to be set for actual DNS provisioning.
Without the API key, provisioning is skipped gracefully.
"""

import logging
import os
import socket
from typing import Optional

import requests

from core.database import get_db_cursor

logger = logging.getLogger(__name__)


def _get_hostinger_api_key() -> str:
    return os.getenv("KBS_HOSTINGER_API_KEY", "")


def _get_base_domain() -> str:
    return os.getenv("KBS_BASE_DOMAIN", "kytranempowerment.com")


def _get_subdomain_target() -> str:
    return os.getenv("KBS_SUBDOMAIN_TARGET", "192.168.1.200")


def _get_api_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_hostinger_api_key()}",
        "Content-Type": "application/json",
    }


def provision_subdomain(slug: str) -> dict:
    """Create an A record for {slug}.{base_domain} pointing to the KBS server.

    Args:
        slug: Tenant slug (e.g. 'acme-corp').

    Returns:
        Dict with 'subdomain', 'fqdn', 'status'.

    Raises:
        ValueError: If slug is empty.
        requests.RequestException: On API failure.
    """
    if not slug:
        raise ValueError("Slug is required for subdomain provisioning")

    api_key = _get_hostinger_api_key()
    if not api_key:
        logger.warning("KBS_HOSTINGER_API_KEY not set -- skipping DNS provisioning for %s", slug)
        return {"subdomain": slug, "fqdn": f"{slug}.{_get_base_domain()}", "status": "skipped"}

    base_domain = _get_base_domain()
    target = _get_subdomain_target()
    fqdn = f"{slug}.{base_domain}"

    url = f"https://api.hostinger.com/api/dns/v1/domains/{base_domain}/records"
    payload = {
        "records": [
            {
                "type": "A",
                "name": slug,
                "content": target,
                "ttl": 3600,
            }
        ]
    }

    try:
        resp = requests.put(url, json=payload, headers=_get_api_headers(), timeout=15)
        resp.raise_for_status()
        logger.info("Provisioned subdomain %s -> %s", fqdn, target)
        return {"subdomain": slug, "fqdn": fqdn, "status": "provisioned", "target": target}
    except requests.RequestException as exc:
        logger.error("Failed to provision subdomain %s: %s", fqdn, exc)
        raise


def provision_custom_domain(domain: str, tenant_id: int) -> dict:
    """Register a custom domain for a paid tenant.

    Records the domain on the tenant settings. DNS must be configured by the client.

    Args:
        domain: Custom domain (e.g. 'app.acme.com').
        tenant_id: Tenant ID.

    Returns:
        Dict with 'domain', 'status', 'instructions'.
    """
    if not domain:
        raise ValueError("Domain is required")

    target = _get_subdomain_target()

    with get_db_cursor(commit=True) as (conn, cur):
        import json

        cur.execute(
            """
            UPDATE tenants
            SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (json.dumps({"custom_domain": domain}), tenant_id),
        )

    logger.info("Registered custom domain %s for tenant %s", domain, tenant_id)

    return {
        "domain": domain,
        "tenant_id": tenant_id,
        "status": "registered",
        "instructions": f"Point your domain {domain} to {target} via A record.",
    }


def check_subdomain_health(slug: str) -> dict:
    """Check if a subdomain resolves correctly.

    Args:
        slug: Tenant slug.

    Returns:
        Dict with 'fqdn', 'resolves', 'ip', 'expected_ip', 'correct'.
    """
    base_domain = _get_base_domain()
    fqdn = f"{slug}.{base_domain}"
    target = _get_subdomain_target()

    try:
        ip = socket.gethostbyname(fqdn)
        resolves = True
        correct = ip == target
    except socket.gaierror:
        ip = None
        resolves = False
        correct = False

    return {
        "fqdn": fqdn,
        "resolves": resolves,
        "ip": ip,
        "expected_ip": target,
        "correct": correct,
    }


def check_custom_domain_health(domain: str) -> dict:
    """Check if a custom domain resolves to the KBS server."""
    target = _get_subdomain_target()

    try:
        ip = socket.gethostbyname(domain)
        resolves = True
        correct = ip == target
    except socket.gaierror:
        ip = None
        resolves = False
        correct = False

    return {
        "domain": domain,
        "resolves": resolves,
        "ip": ip,
        "expected_ip": target,
        "correct": correct,
    }
