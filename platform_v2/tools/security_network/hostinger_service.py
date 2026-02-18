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
        domain = domain or self.domain
        return self._request("GET", f"dns/v1/domains/{domain}/dns-records")

    def add_dns_record(
        self, record_type: str, name: str, value: str, ttl: int = 3600, domain: str = None
    ) -> Optional[Any]:
        domain = domain or self.domain
        return self._request(
            "POST",
            f"dns/v1/domains/{domain}/dns-records",
            {
                "type": record_type,
                "name": name,
                "content": value,
                "ttl": ttl,
            },
        )

    def update_dns_records(self, records: List[Dict], overwrite: bool = False, domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request(
            "PUT",
            f"dns/v1/domains/{domain}/dns-records",
            {
                "overwrite": overwrite,
                "records": records,
            },
        )

    def delete_dns_records(self, record_type: str = None, name: str = None, domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        params = {}
        if record_type:
            params["type"] = record_type
        if name:
            params["name"] = name
        return self._request("DELETE", f"dns/v1/domains/{domain}/dns-records", params)

    def validate_dns_records(self, records: List[Dict], domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request("POST", f"dns/v1/domains/{domain}/dns-records/validate", {"records": records})

    def reset_dns_zone(self, domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request("POST", f"dns/v1/domains/{domain}/dns-records/reset")

    # --- Domain Info ---
    def get_domain_list(self) -> Optional[Any]:
        return self._request("GET", "domains/v1/portfolio")

    def check_health(self) -> bool:
        if not self.available:
            return False
        result = self.get_domain_list()
        return result is not None and "error" not in (result if isinstance(result, dict) else {})
