"""
AdGuard Home Full API Service
==============================
Comprehensive client for AdGuard Home REST API.
Covers: status, stats, query log, filtering, DNS rewrites, clients.
"""

import logging
import os
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class ProtectedRewriteError(Exception):
    """Refused to repoint a control-plane hostname at a host that cannot serve it."""

    def __init__(self, domain: str, answer: str, reason: str):
        self.domain = domain
        self.answer = answer
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# PROTECTED REWRITES (task #5219)
#
# INCIDENT 2026-07-26. During hub recovery all 15 AdGuard rewrites were repointed
# to 192.168.1.200 as a batch. One of them was mesh.kytranempowerment.com — the
# Headscale CONTROL PLANE, which is TLS-only: clients are handed back headscale's
# configured server_url (https://mesh...) and must reach it over 443. The hub Caddy
# standing up during recovery was HTTP-only (auto_https off). Pointing mesh. at it
# made the control plane unreachable and BOTH LAN Starships dropped off the mesh.
# Reverting that single rewrite to Beacon brought them back in ~2 minutes.
#
# The owner had flagged it in advance — "wasnt this on beacon ?" — and the question
# was answered in general terms without checking it against that specific hostname.
# A categorical answer cannot discharge a specific warning; hence a machine-checked
# rule rather than a remembered one.
#
# NOTE the sibling trap already documented in .claude/rules/fleet.md: the
# archie_tailscale container pins mesh. via extra_hosts, and that pin silently
# killed the node for 23 days when NPM was decommissioned and the hub lost its :443
# listener. Same hostname, same class of failure — a DNS/pin change made against a
# host that cannot serve the scheme.
#
# A hostname belongs here when pointing it somewhere wrong breaks the CONTROL PLANE
# rather than one service.
# ---------------------------------------------------------------------------
PROTECTED_REWRITES: Dict[str, Dict[str, Any]] = {
    "mesh.kytranempowerment.com": {
        "required_ports": (443,),
        "reason": (
            "mesh.kytranempowerment.com is the Headscale CONTROL PLANE and is TLS-only "
            "(clients are handed back https://mesh... as server_url and must reach it on "
            "443). Pointing it at a host with no TLS listener severs node enrollment and "
            "drops LAN nodes off the mesh — this exact change cost both Starships on "
            "2026-07-26. Target must be listening on 443."
        ),
    },
}


def _normalize_domain(domain: str) -> str:
    return (domain or "").strip().rstrip(".").lower()


def check_rewrite_allowed(domain: str, answer: str, probe_timeout: float = 3.0):
    """Return (allowed, reason). Verifies a PROTECTED hostname's new target can serve it.

    Fail-CLOSED for protected hostnames: if the target does not answer on a required
    port we refuse, because the failure mode being prevented (a severed control plane)
    is far worse than a refused DNS edit. Unprotected hostnames always pass.
    """
    rule = PROTECTED_REWRITES.get(_normalize_domain(domain))
    if not rule:
        return True, None

    target = (answer or "").strip()
    if not target:
        return False, rule["reason"]

    try:
        from services.node_reachability import probe_node
    except Exception:  # pragma: no cover - import guard only
        logger.warning("node_reachability unavailable — allowing protected rewrite unverified")
        return True, None

    result = probe_node(target, rule["required_ports"], timeout=probe_timeout)
    if result.reachable:
        return True, None

    ports = "/".join(str(p) for p in rule["required_ports"])
    return False, f"{rule['reason']} {target} is not listening on {ports}."


class AdGuardService:
    """Full AdGuard Home API client"""

    def __init__(self):
        host = os.getenv("ADGUARD_HOST", "host.docker.internal")
        port = int(os.getenv("ADGUARD_PORT", "5354"))
        self.base_url = f"http://{host}:{port}"
        _fallback_host = os.getenv("ARCHIE_HOST", "192.168.1.200")
        self.fallback_url = f"http://{_fallback_host}:5354"
        self.username = os.getenv("ADGUARD_USER", "kytran")
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
        # AdGuard's filtering/set_url requires the FULL data object
        # (name + url + enabled) plus whitelist — sending only {"enabled": ...}
        # is rejected (HTTP 400). Look up the filter's current name by URL.
        name = url
        status = self.get_filtering_status()
        if status:
            for f in status.get("filters") or []:
                if f.get("url") == url:
                    name = f.get("name") or url
                    break
        return self._request(
            "POST",
            "filtering/set_url",
            {"url": url, "whitelist": False, "data": {"enabled": enabled, "name": name, "url": url}},
        )

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

    def add_rewrite(self, domain: str, answer: str, force: bool = False) -> Optional[Dict]:
        """Add/repoint a DNS rewrite.

        Refuses to point a PROTECTED control-plane hostname at a target that is not
        serving the scheme it requires (#5219). `force=True` is the deliberate
        override for an operator who knows the target is about to start listening.
        """
        allowed, reason = (True, None) if force else check_rewrite_allowed(domain, answer)
        if not allowed:
            logger.error("REFUSED protected DNS rewrite %s -> %s: %s", domain, answer, reason)
            raise ProtectedRewriteError(domain, answer, reason)
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

    # --- Blocked Services ---
    def get_blocked_services_all(self) -> Optional[List]:
        """Get full catalog of available services that can be blocked."""
        return self._request("GET", "blocked_services/all")

    def get_blocked_services(self) -> Optional[List]:
        """Get currently blocked services."""
        return self._request("GET", "blocked_services/list")

    def set_blocked_services(self, service_ids: List[str]) -> Optional[Any]:
        """Set global blocked services list."""
        return self._request("POST", "blocked_services/set", service_ids)

    # --- Protection ---
    def set_protection(self, enabled: bool) -> Optional[Dict]:
        return self._request("POST", "dns_config", {"protection_enabled": enabled})
