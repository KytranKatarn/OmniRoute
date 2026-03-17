"""
Hostinger API Integration
==========================
Integration with Hostinger API for domain and DNS management.

API Documentation: https://developers.hostinger.com/

Author: A.R.C.H.I.E. Platform
Date: 2026-01-16
Phase: 22
"""

import os
import requests
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class HostingerAPI:
    """
    Hostinger API client for domain and DNS management.

    Environment Variables:
        HOSTINGER_API_KEY: Your Hostinger API key

    Usage:
        api = HostingerAPI()
        domains = api.list_domains()
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("HOSTINGER_API_KEY", "")
        self.base_url = "https://api.hostinger.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make an API request to Hostinger"""
        url = f"{self.base_url}{endpoint}"

        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=self.headers, params=data, timeout=30)
            elif method.upper() == "POST":
                response = requests.post(url, headers=self.headers, json=data, timeout=30)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=self.headers, json=data, timeout=30)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=self.headers, timeout=30)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}

            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            elif response.status_code == 204:
                return {"success": True, "message": "Operation completed"}
            else:
                return {
                    "success": False,
                    "error": response.text,
                    "status_code": response.status_code,
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timed out"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Hostinger API error: {e}")
            return {"success": False, "error": str(e)}

    def is_configured(self) -> bool:
        """Check if API key is configured"""
        return bool(self.api_key)

    # =========================================================================
    # DOMAINS
    # =========================================================================

    def list_domains(self) -> Dict:
        """
        List all domains in the Hostinger account.

        Returns:
            {
                'success': True,
                'data': [
                    {
                        'domain': 'example.com',
                        'status': 'active',
                        'expires_at': '2027-01-16',
                        'nameservers': ['ns1.dns-parking.com', 'ns2.dns-parking.com']
                    }
                ]
            }
        """
        return self._request("GET", "/domains")

    def get_domain(self, domain: str) -> Dict:
        """
        Get details for a specific domain.

        Args:
            domain: The domain name (e.g., 'example.com')

        Returns:
            Domain details including DNS settings
        """
        return self._request("GET", f"/domains/{domain}")

    # =========================================================================
    # DNS RECORDS
    # =========================================================================

    def get_dns_records(self, domain: str) -> Dict:
        """
        Get all DNS records for a domain.

        Args:
            domain: The domain name

        Returns:
            List of DNS records (A, CNAME, MX, TXT, etc.)
        """
        return self._request("GET", f"/domains/{domain}/dns")

    def add_dns_record(
        self,
        domain: str,
        record_type: str,
        name: str,
        value: str,
        ttl: int = 3600,
        priority: int = None,
    ) -> Dict:
        """
        Add a new DNS record.

        Args:
            domain: The domain name
            record_type: Type of record (A, AAAA, CNAME, MX, TXT, NS)
            name: Record name (@ for root, or subdomain)
            value: Record value (IP address, hostname, etc.)
            ttl: Time to live in seconds (default 3600)
            priority: Priority for MX records

        Returns:
            Created record details
        """
        data = {"type": record_type.upper(), "name": name, "value": value, "ttl": ttl}

        if priority is not None and record_type.upper() == "MX":
            data["priority"] = priority

        return self._request("POST", f"/domains/{domain}/dns", data)

    def update_dns_record(self, domain: str, record_id: str, value: str = None, ttl: int = None) -> Dict:
        """
        Update an existing DNS record.

        Args:
            domain: The domain name
            record_id: The ID of the record to update
            value: New value (optional)
            ttl: New TTL (optional)

        Returns:
            Updated record details
        """
        data = {}
        if value is not None:
            data["value"] = value
        if ttl is not None:
            data["ttl"] = ttl

        if not data:
            return {"success": False, "error": "No update data provided"}

        return self._request("PUT", f"/domains/{domain}/dns/{record_id}", data)

    def delete_dns_record(self, domain: str, record_id: str) -> Dict:
        """
        Delete a DNS record.

        Args:
            domain: The domain name
            record_id: The ID of the record to delete

        Returns:
            Success status
        """
        return self._request("DELETE", f"/domains/{domain}/dns/{record_id}")

    # =========================================================================
    # QUICK DNS PRESETS
    # =========================================================================

    def set_github_pages(self, domain: str, username: str, use_apex: bool = True) -> Dict:
        """
        Configure domain for GitHub Pages.

        Args:
            domain: The domain name
            username: GitHub username
            use_apex: If True, configures apex domain; if False, configures www subdomain

        Returns:
            Status of DNS changes
        """
        results = []

        if use_apex:
            # A records for apex domain (GitHub's IP addresses)
            github_ips = [
                "185.199.108.153",
                "185.199.109.153",
                "185.199.110.153",
                "185.199.111.153",
            ]

            for ip in github_ips:
                result = self.add_dns_record(domain, "A", "@", ip)
                results.append(result)

        # CNAME for www
        cname_value = f"{username}.github.io"
        result = self.add_dns_record(domain, "CNAME", "www", cname_value)
        results.append(result)

        return {"success": all(r.get("success") for r in results), "results": results}

    def set_vercel(self, domain: str) -> Dict:
        """
        Configure domain for Vercel deployment.

        Args:
            domain: The domain name

        Returns:
            Status of DNS changes
        """
        results = []

        # A record for apex
        result = self.add_dns_record(domain, "A", "@", "76.76.21.21")
        results.append(result)

        # CNAME for www
        result = self.add_dns_record(domain, "CNAME", "www", "cname.vercel-dns.com")
        results.append(result)

        return {"success": all(r.get("success") for r in results), "results": results}

    def set_netlify(self, domain: str, site_name: str) -> Dict:
        """
        Configure domain for Netlify deployment.

        Args:
            domain: The domain name
            site_name: Your Netlify site name

        Returns:
            Status of DNS changes
        """
        results = []

        # CNAME for apex (Netlify supports apex via CNAME flattening)
        result = self.add_dns_record(domain, "CNAME", "@", f"{site_name}.netlify.app")
        results.append(result)

        # CNAME for www
        result = self.add_dns_record(domain, "CNAME", "www", f"{site_name}.netlify.app")
        results.append(result)

        return {"success": all(r.get("success") for r in results), "results": results}

    # =========================================================================
    # SSL / HOSTING INFO
    # =========================================================================

    def get_ssl_status(self, domain: str) -> Dict:
        """
        Get SSL certificate status for a domain.

        Args:
            domain: The domain name

        Returns:
            SSL certificate details
        """
        return self._request("GET", f"/domains/{domain}/ssl")

    def get_hosting_info(self) -> Dict:
        """
        Get hosting account information.

        Returns:
            Hosting plan details, usage, etc.
        """
        return self._request("GET", "/hosting")


# Singleton instance
_hostinger_api = None


def get_hostinger_api() -> HostingerAPI:
    """Get or create the Hostinger API instance"""
    global _hostinger_api
    if _hostinger_api is None:
        _hostinger_api = HostingerAPI()
    return _hostinger_api
