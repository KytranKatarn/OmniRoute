"""
Hostinger DNS Integration for Website Designer
Provides DNS management via Hostinger API with mock mode fallback.
"""

import os
import psycopg2
import psycopg2.extras
import requests

DB_HOST = os.environ.get("DB_HOST", "192.168.1.200")
DB_NAME = os.environ.get("DB_NAME", "archie")
DB_USER = os.environ.get("DB_USER", "archie")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_PORT = os.environ.get("DB_PORT", "5432")

HOSTINGER_API_BASE = "https://api.hostinger.com/v1"

GITHUB_PAGES_A_RECORDS = [
    "185.199.108.153",
    "185.199.109.153",
    "185.199.110.153",
    "185.199.111.153",
]


class HostingerAPI:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.mock_mode = not bool(api_key)

    def is_configured(self):
        return not self.mock_mode

    def _request(self, method, path, json=None):
        url = f"{HOSTINGER_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        response = requests.request(method, url, headers=headers, json=json, timeout=30)
        response.raise_for_status()
        return response.json()

    def list_domains(self):
        if self.mock_mode:
            return {
                "mock": True,
                "domains": [
                    {
                        "domain": "example.com",
                        "status": "active",
                        "expires_at": "2027-01-01",
                        "auto_renew": True,
                    },
                    {
                        "domain": "mysite.net",
                        "status": "active",
                        "expires_at": "2026-06-15",
                        "auto_renew": False,
                    },
                ],
            }
        data = self._request("GET", "/domains")
        return {"mock": False, "domains": data.get("data", [])}

    def get_dns_records(self, domain):
        if self.mock_mode:
            return {
                "mock": True,
                "records": [
                    {
                        "id": "mock-1",
                        "type": "A",
                        "name": "@",
                        "content": "192.0.2.1",
                        "ttl": 3600,
                        "priority": None,
                    },
                    {
                        "id": "mock-2",
                        "type": "CNAME",
                        "name": "www",
                        "content": domain,
                        "ttl": 3600,
                        "priority": None,
                    },
                    {
                        "id": "mock-3",
                        "type": "MX",
                        "name": "@",
                        "content": f"mail.{domain}",
                        "ttl": 3600,
                        "priority": 10,
                    },
                ],
            }
        data = self._request("GET", f"/domains/{domain}/dns/records")
        return {"mock": False, "records": data.get("data", [])}

    def add_dns_record(self, domain, record_type, name, content, ttl=3600, priority=None):
        if self.mock_mode:
            return {
                "mock": True,
                "success": True,
                "record": {
                    "id": "mock-new",
                    "type": record_type,
                    "name": name,
                    "content": content,
                    "ttl": ttl,
                    "priority": priority,
                },
            }
        payload = {"type": record_type, "name": name, "content": content, "ttl": ttl}
        if priority is not None:
            payload["priority"] = priority
        data = self._request("POST", f"/domains/{domain}/dns/records", json=payload)
        return {"mock": False, "success": True, "record": data.get("data", {})}

    def update_dns_record(self, domain, record_id, content=None, ttl=None):
        if self.mock_mode:
            return {
                "mock": True,
                "success": True,
                "record_id": record_id,
                "content": content,
                "ttl": ttl,
            }
        payload = {}
        if content is not None:
            payload["content"] = content
        if ttl is not None:
            payload["ttl"] = ttl
        data = self._request("PATCH", f"/domains/{domain}/dns/records/{record_id}", json=payload)
        return {"mock": False, "success": True, "record": data.get("data", {})}

    def delete_dns_record(self, domain, record_id):
        if self.mock_mode:
            return {"mock": True, "success": True, "record_id": record_id}
        self._request("DELETE", f"/domains/{domain}/dns/records/{record_id}")
        return {"mock": False, "success": True, "record_id": record_id}

    def apply_preset(self, domain, preset_type, target=None):
        results = []

        if preset_type == "github_pages":
            # Add 4 A records pointing to GitHub Pages IPs
            for ip in GITHUB_PAGES_A_RECORDS:
                result = self.add_dns_record(domain, "A", "@", ip, ttl=3600)
                results.append(result)

            # Add CNAME for www -> GitHub Pages target
            cname_target = target if target else f"{domain}.github.io"
            result = self.add_dns_record(domain, "CNAME", "www", cname_target, ttl=3600)
            results.append(result)

            return {
                "mock": self.mock_mode,
                "success": True,
                "preset": preset_type,
                "records_added": len(results),
                "results": results,
            }

        return {
            "mock": self.mock_mode,
            "success": False,
            "error": f"Unknown preset type: {preset_type}",
        }


def get_hostinger_api(user_id):
    """Factory: loads Hostinger credentials from user_integrations table."""
    api_key = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT credentials
            FROM user_integrations
            WHERE user_id = %s AND service = 'hostinger'
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row and row["credentials"]:
            creds = row["credentials"]
            api_key = creds.get("api_key") if isinstance(creds, dict) else None
        cur.close()
        conn.close()
    except Exception:
        pass

    return HostingerAPI(api_key=api_key)
