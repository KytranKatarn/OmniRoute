"""
AdGuard Home Full API Service
==============================
Comprehensive client for AdGuard Home REST API.
Covers: status, stats, query log, filtering, DNS rewrites, clients.
"""

import os
import requests
from typing import Optional, Dict, Any, List


class AdGuardService:
    """Full AdGuard Home API client"""

    def __init__(self):
        host = os.getenv("ADGUARD_HOST", "network_adguard")
        port = int(os.getenv("ADGUARD_PORT", "80"))
        self.base_url = f"http://{host}:{port}"
        _fallback_host = os.getenv("ARCHIE_HOST", "192.168.1.200")
        self.fallback_url = f"http://{_fallback_host}:5355"
        self.username = os.getenv("ADGUARD_USER", "archie_admin")
        self.password = os.getenv("ADGUARD_PASS", "")
        self._active_url = None

    def _request(
        self, method: str, endpoint: str, data: Any = None, params: dict = None, timeout: int = 10
    ) -> Optional[Any]:
        """Make API request to AdGuard with fallback"""
        urls = [self._active_url] if self._active_url else []
        urls.extend([self.base_url, self.fallback_url])

        for url in urls:
            if not url:
                continue
            try:
                full_url = f"{url}/control/{endpoint}"
                auth = (self.username, self.password) if self.password else None

                if method == "GET":
                    resp = requests.get(full_url, auth=auth, params=params, timeout=timeout)
                elif method == "POST":
                    resp = requests.post(full_url, auth=auth, json=data, timeout=timeout)
                elif method == "DELETE":
                    resp = requests.delete(full_url, auth=auth, json=data, timeout=timeout)
                elif method == "PUT":
                    resp = requests.put(full_url, auth=auth, json=data, timeout=timeout)
                else:
                    continue

                resp.raise_for_status()
                self._active_url = url
                if resp.content:
                    try:
                        return resp.json()
                    except ValueError:
                        return {"status": "ok"}
                return {"status": "ok"}
            except Exception:
                continue

        return None

    # --- Status ---
    def get_status(self) -> Optional[Dict]:
        return self._request("GET", "status")

    def check_health(self) -> bool:
        return self.get_status() is not None

    # --- Statistics ---
    def get_stats(self) -> Optional[Dict]:
        return self._request("GET", "stats")

    def get_stats_config(self) -> Optional[Dict]:
        return self._request("GET", "stats/config")

    # --- Query Log ---
    def get_query_log(
        self, limit: int = 100, offset: int = 0, search: str = None, response_status: str = None
    ) -> Optional[Dict]:
        params = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        if response_status:
            params["response_status"] = response_status
        return self._request("GET", "querylog", params=params)

    def clear_query_log(self) -> Optional[Dict]:
        return self._request("POST", "querylog_clear")

    # --- Filtering ---
    def get_filtering_status(self) -> Optional[Dict]:
        return self._request("GET", "filtering/status")

    def add_filter(self, name: str, url: str, enabled: bool = True) -> Optional[Dict]:
        return self._request("POST", "filtering/add_url", {"name": name, "url": url, "whitelist": False})

    def remove_filter(self, url: str) -> Optional[Dict]:
        return self._request("POST", "filtering/remove_url", {"url": url, "whitelist": False})

    def toggle_filter(self, url: str, enabled: bool) -> Optional[Dict]:
        return self._request("POST", "filtering/set_url", {"url": url, "data": {"enabled": enabled}})

    def refresh_filters(self) -> Optional[Dict]:
        return self._request("POST", "filtering/refresh", {"whitelist": False})

    def get_user_rules(self) -> Optional[Dict]:
        status = self.get_filtering_status()
        if status:
            return {"rules": status.get("user_rules", [])}
        return None

    def set_user_rules(self, rules: List[str]) -> Optional[Dict]:
        return self._request("POST", "filtering/set_rules", {"rules": rules})

    # --- DNS Rewrites ---
    def get_rewrites(self) -> Optional[List]:
        return self._request("GET", "rewrite/list")

    def add_rewrite(self, domain: str, answer: str) -> Optional[Dict]:
        return self._request("POST", "rewrite/add", {"domain": domain, "answer": answer})

    def delete_rewrite(self, domain: str, answer: str) -> Optional[Dict]:
        return self._request("POST", "rewrite/delete", {"domain": domain, "answer": answer})

    # --- Clients ---
    def get_clients(self) -> Optional[Dict]:
        return self._request("GET", "clients")

    def get_persistent_clients(self) -> Optional[List[Dict]]:
        """Get AdGuard persistent client list (named devices with IPs/MACs)."""
        result = self._request("GET", "clients")
        if result and isinstance(result, dict):
            return result.get("clients", [])
        return []

    # --- Filtering Check ---
    def check_host(self, domain: str) -> Optional[Dict]:
        """Check if a domain is blocked by any filter (user rules + all filter lists)."""
        return self._request("GET", "filtering/check_host", params={"name": domain})

    # --- Blocking ---
    def block_domain(self, domain: str) -> bool:
        rules = self.get_user_rules()
        if rules is None:
            return False
        current = rules.get("rules", [])
        block_rule = f"||{domain}^"
        if block_rule not in current:
            current.append(block_rule)
            result = self.set_user_rules(current)
            return result is not None
        return True

    def unblock_domain(self, domain: str) -> bool:
        rules = self.get_user_rules()
        if rules is None:
            return False
        current = rules.get("rules", [])
        block_rule = f"||{domain}^"
        if block_rule in current:
            current.remove(block_rule)
            result = self.set_user_rules(current)
            return result is not None
        return True

    # --- Per-client report ---
    def get_client_report(self, client_ip: str, limit: int = 200) -> Dict:
        """Get per-client DNS report: query count, blocked count, top domains, top blocked."""
        querylog = self.get_query_log(limit=limit, search=client_ip)
        if not querylog or not isinstance(querylog, dict):
            return {
                "total": 0,
                "blocked": 0,
                "top_domains": [],
                "top_blocked": [],
                "recent": [],
            }

        entries = querylog.get("data", [])
        total = len(entries)
        blocked_entries = [e for e in entries if e.get("reason", "") not in ("NotFilteredNotFound", "")]
        blocked = len(blocked_entries)

        # Count domain frequencies
        domain_counts: Dict[str, int] = {}
        blocked_counts: Dict[str, int] = {}
        for e in entries:
            domain = e.get("question", {}).get("name", "")
            if domain:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
                if e.get("reason", "") not in ("NotFilteredNotFound", ""):
                    blocked_counts[domain] = blocked_counts.get(domain, 0) + 1

        top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_blocked = sorted(blocked_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        recent = []
        for e in entries[:20]:
            q = e.get("question", {})
            recent.append(
                {
                    "domain": q.get("name", ""),
                    "type": q.get("type", ""),
                    "blocked": e.get("reason", "") not in ("NotFilteredNotFound", ""),
                    "reason": e.get("reason", ""),
                    "time": e.get("time", ""),
                }
            )

        return {
            "total": total,
            "blocked": blocked,
            "top_domains": [{"domain": d, "count": c} for d, c in top_domains],
            "top_blocked": [{"domain": d, "count": c} for d, c in top_blocked],
            "recent": recent,
        }

    # --- Protection ---
    def set_protection(self, enabled: bool) -> Optional[Dict]:
        return self._request("POST", "dns_config", {"protection_enabled": enabled})
