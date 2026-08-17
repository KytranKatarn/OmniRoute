"""
Hostinger DNS API Service
==========================
Client for Hostinger REST API domain/DNS management.
API Reference: https://developers.hostinger.com/
"""

import os
import requests
from typing import Optional, Dict, Any, List


class HostingerService:
    """Hostinger DNS API client"""

    def __init__(self):
        self.api_key = os.getenv("HOSTINGER_API_KEY", "")
        self.base_url = "https://developers.hostinger.com/api"
        self.domain = os.getenv("HOSTINGER_DOMAIN", "kytranempowerment.com")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, endpoint: str, data: Any = None, timeout: int = 15) -> Optional[Any]:
        if not self.available:
            return None
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = requests.request(method, url, headers=self._headers(), json=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json() if resp.content else {"status": "ok"}
        except Exception as e:
            return {"error": str(e)}

    # --- DNS Records ---
    def get_dns_records(self, domain: str = None) -> Optional[Any]:
        """Get all DNS records for a domain zone."""
        domain = domain or self.domain
        return self._request("GET", f"dns/v1/zones/{domain}")

    def get_a_records(self, domain: str = None) -> List[Dict]:
        """Get only A records, formatted for display."""
        records = self.get_dns_records(domain)
        if not records or isinstance(records, dict) and "error" in records:
            return []
        return [r for r in records if r.get("type") == "A"]

    def add_dns_record(
        self, record_type: str, name: str, value: str, ttl: int = 300, domain: str = None
    ) -> Optional[Any]:
        """Add a DNS record (non-destructive, overwrite=false)."""
        domain = domain or self.domain
        return self._request(
            "PUT",
            f"dns/v1/zones/{domain}",
            {
                "zone": [
                    {
                        "name": name,
                        "type": record_type,
                        "ttl": ttl,
                        "records": [{"content": value}],
                    }
                ],
                "overwrite": False,
            },
        )

    def update_dns_record(
        self, record_type: str, name: str, value: str, ttl: int = 300, domain: str = None
    ) -> Optional[Any]:
        """Update an existing DNS record (overwrites matching name+type)."""
        domain = domain or self.domain
        return self._request(
            "PUT",
            f"dns/v1/zones/{domain}",
            {
                "zone": [
                    {
                        "name": name,
                        "type": record_type,
                        "ttl": ttl,
                        "records": [{"content": value}],
                    }
                ],
                "overwrite": True,
            },
        )

    def update_dns_records_bulk(self, records: List[Dict], overwrite: bool = True, domain: str = None) -> Optional[Any]:
        """Bulk update DNS records. Each record: {name, type, ttl, content}."""
        domain = domain or self.domain
        zone = []
        for r in records:
            zone.append(
                {
                    "name": r["name"],
                    "type": r.get("type", "A"),
                    "ttl": r.get("ttl", 300),
                    "records": [{"content": r["content"]}],
                }
            )
        return self._request(
            "PUT",
            f"dns/v1/zones/{domain}",
            {"zone": zone, "overwrite": overwrite},
        )

    def delete_dns_zone(self, domain: str = None) -> Optional[Any]:
        """Delete entire DNS zone (use with caution)."""
        domain = domain or self.domain
        return self._request("DELETE", f"dns/v1/zones/{domain}")

    def delete_dns_records(self, record_type: str, name: str, domain: str = None) -> Optional[Any]:
        """Delete the DNS record(s) matching name+type (NOT the whole zone).

        Uses Hostinger's filtered-delete: DELETE dns/v1/zones/{domain} with a
        ``filters`` body scoping the deletion to one name+type pair.
        """
        domain = domain or self.domain
        return self._request(
            "DELETE",
            f"dns/v1/zones/{domain}",
            {"filters": [{"name": name, "type": record_type}]},
        )

    # --- Domain Info ---
    def get_domain_list(self) -> Optional[Any]:
        """List all domains in portfolio."""
        return self._request("GET", "domains/v1/portfolio")

    def get_public_ip(self) -> Optional[str]:
        """Get current public IP address."""
        try:
            resp = requests.get("https://api.ipify.org", timeout=10)
            ip = resp.text.strip()
            if ip and all(c.isdigit() or c == "." for c in ip):
                return ip
        except Exception:
            pass
        return None

    def check_health(self) -> bool:
        """Verify Hostinger API connectivity."""
        if not self.available:
            return False
        result = self.get_dns_records()
        return isinstance(result, list)
