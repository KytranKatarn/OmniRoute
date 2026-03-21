"""
Hostinger API Integration — Delegates to Security Network's HostingerService
=============================================================================
Thin wrapper that provides the HostingerAPI interface for Website Studio routes
while delegating all DNS operations to the shared HostingerService singleton
from Security Network (Decision #249 — unified module integration).

Preset methods (GitHub Pages, Vercel, Netlify) are website-specific logic
that compose multiple DNS operations.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-21
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Import the shared HostingerService from Security Network
try:
    from tools.security_network.hostinger_service import HostingerService

    _shared_service = HostingerService()
    _SERVICE_AVAILABLE = _shared_service.available
except Exception as e:
    logger.warning("HostingerService not available: %s", e)
    _shared_service = None
    _SERVICE_AVAILABLE = False


class HostingerAPI:
    """
    Hostinger API client — delegates to Security Network's HostingerService.

    Maintains the same interface used by Website Studio routes so no
    route changes are needed.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._service = _shared_service

    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Direct API request via shared service."""
        if not self._service:
            return {"success": False, "error": "Hostinger service not available"}
        try:
            result = self._service._request(method, endpoint, data)
            if result is not None:
                return {"success": True, "data": result}
            return {"success": False, "error": "No response from API"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def is_configured(self) -> bool:
        """Check if API key is configured."""
        return _SERVICE_AVAILABLE

    # =========================================================================
    # DOMAINS
    # =========================================================================

    def list_domains(self) -> Dict:
        """List all domains in the Hostinger account."""
        if not self._service:
            return {"success": False, "error": "Service not available"}
        result = self._service.get_domain_list()
        if result is not None:
            return {"success": True, "data": result}
        return {"success": False, "error": "Failed to list domains"}

    def get_domain(self, domain: str) -> Dict:
        """Get details for a specific domain."""
        return self._request("GET", f"/api/dns/domain/{domain}")

    # =========================================================================
    # DNS RECORDS
    # =========================================================================

    def get_dns_records(self, domain: str) -> Dict:
        """Get all DNS records for a domain."""
        if not self._service:
            return {"success": False, "error": "Service not available"}
        result = self._service.get_dns_records(domain)
        if result is not None:
            return {"success": True, "data": result}
        return {"success": False, "error": "Failed to get DNS records"}

    def add_dns_record(
        self,
        domain: str,
        record_type: str,
        name: str,
        value: str,
        ttl: int = 3600,
        priority: int = None,
    ) -> Dict:
        """Add a new DNS record."""
        if not self._service:
            return {"success": False, "error": "Service not available"}
        result = self._service.add_dns_record(
            name=name,
            record_type=record_type.upper(),
            content=value,
            ttl=ttl,
            priority=priority or 0,
            domain=domain,
        )
        if result is not None:
            return {"success": True, "data": result}
        return {"success": False, "error": "Failed to add DNS record"}

    def update_dns_record(self, domain: str, record_id: str, value: str = None, ttl: int = None) -> Dict:
        """Update an existing DNS record."""
        if not self._service:
            return {"success": False, "error": "Service not available"}
        result = self._service.update_dns_record(record_id=record_id, content=value, ttl=ttl, domain=domain)
        if result is not None:
            return {"success": True, "data": result}
        return {"success": False, "error": "Failed to update DNS record"}

    def delete_dns_record(self, domain: str, record_id: str) -> Dict:
        """Delete a DNS record."""
        return self._request("DELETE", f"/api/dns/domain/{domain}/records/{record_id}")

    # =========================================================================
    # QUICK DNS PRESETS (website-specific composites)
    # =========================================================================

    def set_github_pages(self, domain: str, username: str, use_apex: bool = True) -> Dict:
        """Configure domain for GitHub Pages."""
        results = []
        if use_apex:
            github_ips = [
                "185.199.108.153",
                "185.199.109.153",
                "185.199.110.153",
                "185.199.111.153",
            ]
            for ip in github_ips:
                result = self.add_dns_record(domain, "A", "@", ip)
                results.append(result)
        cname_value = f"{username}.github.io"
        result = self.add_dns_record(domain, "CNAME", "www", cname_value)
        results.append(result)
        return {"success": all(r.get("success") for r in results), "results": results}

    def set_vercel(self, domain: str) -> Dict:
        """Configure domain for Vercel deployment."""
        results = []
        results.append(self.add_dns_record(domain, "A", "@", "76.76.21.21"))
        results.append(self.add_dns_record(domain, "CNAME", "www", "cname.vercel-dns.com"))
        return {"success": all(r.get("success") for r in results), "results": results}

    def set_netlify(self, domain: str, site_name: str) -> Dict:
        """Configure domain for Netlify deployment."""
        results = []
        results.append(self.add_dns_record(domain, "CNAME", "@", f"{site_name}.netlify.app"))
        results.append(self.add_dns_record(domain, "CNAME", "www", f"{site_name}.netlify.app"))
        return {"success": all(r.get("success") for r in results), "results": results}

    # =========================================================================
    # SSL / HOSTING INFO
    # =========================================================================

    def get_ssl_status(self, domain: str) -> Dict:
        """Get SSL certificate status for a domain."""
        return self._request("GET", f"/api/ssl/domain/{domain}")

    def get_hosting_info(self) -> Dict:
        """Get hosting account information."""
        return self._request("GET", "/api/hosting")


# Singleton instance
_hostinger_api = None


def get_hostinger_api() -> HostingerAPI:
    """Get or create the Hostinger API instance."""
    global _hostinger_api
    if _hostinger_api is None:
        _hostinger_api = HostingerAPI()
    return _hostinger_api
