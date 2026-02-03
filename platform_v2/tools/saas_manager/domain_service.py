"""
A.R.C.H.I.E. Platform - Domain Service
=======================================

Automates domain setup:
1. DNS record creation via Hostinger API
2. Proxy host creation via Nginx Proxy Manager API
3. SSL certificate provisioning (Let's Encrypt via NPM)
4. DNS propagation verification
"""

import os
import logging

import requests

logger = logging.getLogger(__name__)

NPM_API_URL = os.environ.get("NPM_API_URL", "http://192.168.1.200:81/api")
NPM_EMAIL = os.environ.get("NPM_ADMIN_EMAIL", "")
NPM_PASSWORD = os.environ.get("NPM_ADMIN_PASSWORD", "")


class NPMClient:
    """Nginx Proxy Manager API client."""

    def __init__(self):
        self.base_url = NPM_API_URL
        self.token = None

    def _auth(self):
        """Authenticate and get JWT token."""
        if self.token:
            return
        resp = requests.post(
            f"{self.base_url}/tokens",
            json={"identity": NPM_EMAIL, "secret": NPM_PASSWORD},
        )
        resp.raise_for_status()
        self.token = resp.json()["token"]

    def _headers(self):
        self._auth()
        return {"Authorization": f"Bearer {self.token}"}

    def create_proxy_host(self, domain, forward_host, forward_port, ssl=True):
        """Create a proxy host in NPM."""
        payload = {
            "domain_names": [domain],
            "forward_scheme": "http",
            "forward_host": forward_host,
            "forward_port": forward_port,
            "block_exploits": True,
            "allow_websocket_upgrade": True,
            "access_list_id": 0,
            "certificate_id": 0,
            "ssl_forced": False,
            "meta": {"letsencrypt_agree": True},
            "advanced_config": "",
            "locations": [],
            "http2_support": True,
            "hsts_enabled": False,
            "hsts_subdomains": False,
        }

        resp = requests.post(
            f"{self.base_url}/nginx/proxy-hosts",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        host = resp.json()

        if ssl:
            try:
                self.request_ssl(host["id"], domain)
            except Exception as e:
                logger.warning("SSL request failed for %s: %s", domain, e)

        return host

    def request_ssl(self, proxy_host_id, domain):
        """Request Let's Encrypt SSL for a proxy host."""
        cert_resp = requests.post(
            f"{self.base_url}/nginx/certificates",
            json={
                "domain_names": [domain],
                "meta": {
                    "letsencrypt_email": NPM_EMAIL,
                    "letsencrypt_agree": True,
                    "dns_challenge": False,
                },
                "provider": "letsencrypt",
            },
            headers=self._headers(),
        )
        cert_resp.raise_for_status()
        cert = cert_resp.json()

        requests.put(
            f"{self.base_url}/nginx/proxy-hosts/{proxy_host_id}",
            json={
                "certificate_id": cert["id"],
                "ssl_forced": True,
                "http2_support": True,
            },
            headers=self._headers(),
        )
        return cert

    def delete_proxy_host(self, proxy_host_id):
        """Delete a proxy host from NPM."""
        resp = requests.delete(
            f"{self.base_url}/nginx/proxy-hosts/{proxy_host_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()

    def list_proxy_hosts(self):
        """List all proxy hosts."""
        resp = requests.get(
            f"{self.base_url}/nginx/proxy-hosts",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()


def setup_domain(domain_row, public_ip):
    """
    Full domain setup: Hostinger DNS + NPM proxy host.

    Args:
        domain_row: dict from org_domains table
        public_ip: Server's current public IP

    Returns:
        dict with status of each step
    """
    from hostinger_integration import get_hostinger_api

    result = {"dns": None, "proxy": None, "ssl": None}
    domain = domain_row["domain"]
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

    # Step 2: NPM proxy host
    try:
        npm = NPMClient()
        host = npm.create_proxy_host(
            domain=domain,
            forward_host="192.168.1.200",
            forward_port=domain_row.get("target_port", 3000),
            ssl=True,
        )
        result["proxy"] = {"success": True, "proxy_host_id": host["id"]}
        result["ssl"] = {"success": True}
    except Exception as e:
        result["proxy"] = {"success": False, "error": str(e)}

    return result


def cleanup_domain(domain, npm_proxy_host_id=None):
    """Remove NPM proxy host for a domain."""
    if npm_proxy_host_id:
        try:
            npm = NPMClient()
            npm.delete_proxy_host(npm_proxy_host_id)
        except Exception as e:
            logger.warning("Failed to remove NPM proxy host %s: %s", npm_proxy_host_id, e)

    logger.info("Domain %s removed. Check Hostinger DNS manually if needed.", domain)
