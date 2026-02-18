# Security & Network Module Rebuild — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the security_network module into a 7-tab security operations center with AdGuard DNS, Hostinger public DNS, Blink camera surveillance, Argus recon, vulnerability scanning, access control, reports, and AI agent automation.

**Architecture:** Flask blueprint module at `/platform_v2/tools/security_network/` with 7 service files (one per integration), a rebuilt HTML template following the System Operations tab pattern (lazy-loaded subtabs), and 6 new PostgreSQL tables. The `/frontend-design` skill will be used for the template rebuild following LCARS design standards.

**Tech Stack:** Flask, PostgreSQL (psycopg2), AdGuard REST API, Hostinger REST API, Home Assistant REST API, Argus CLI (argus-recon), Meraki Python SDK (optional), Lucide icons, CSS custom properties (`--archie-*`)

**Design Doc:** `docs/plans/2026-02-18-security-network-rebuild-design.md`

**Dev HQ:** Project #94 (Platform UI Overhaul), Task #630 (Redesign: Security & Network)

---

## Phase 1: Foundation (Tasks 1-6)

### Task 1: Database Migration — New Tables

**Files:**
- Create: `database/migrations/082_security_network_rebuild.sql`

**Step 1: Write the migration SQL**

Create the 6 new tables with indexes as specified in the design doc:

```sql
-- Security & Network Module Rebuild
-- Migration 082: New tables for agent actions, recon scans, scan results,
--                camera events, DNS changes, and reports

BEGIN;

-- Agent automation suggestions and actions
CREATE TABLE IF NOT EXISTS security_agent_actions (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    reasoning TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    data JSONB,
    executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Argus scan history
CREATE TABLE IF NOT EXISTS security_recon_scans (
    id SERIAL PRIMARY KEY,
    module_name VARCHAR(100) NOT NULL,
    target VARCHAR(500) NOT NULL,
    options JSONB,
    status VARCHAR(20) DEFAULT 'running',
    results JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    triggered_by VARCHAR(50) DEFAULT 'user'
);

-- Vulnerability scan results
CREATE TABLE IF NOT EXISTS security_scan_results (
    id SERIAL PRIMARY KEY,
    scanner VARCHAR(50) NOT NULL,
    target VARCHAR(500) NOT NULL,
    severity VARCHAR(20),
    finding VARCHAR(500),
    details JSONB,
    scan_id INTEGER REFERENCES security_recon_scans(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Camera motion events (cached from HA)
CREATE TABLE IF NOT EXISTS security_camera_events (
    id SERIAL PRIMARY KEY,
    camera_entity VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    location VARCHAR(100),
    thumbnail_url TEXT,
    data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- DNS management audit trail
CREATE TABLE IF NOT EXISTS security_dns_changes (
    id SERIAL PRIMARY KEY,
    source VARCHAR(20) NOT NULL,
    action VARCHAR(50) NOT NULL,
    domain VARCHAR(500),
    details JSONB,
    changed_by VARCHAR(50) DEFAULT 'user',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Generated security reports
CREATE TABLE IF NOT EXISTS security_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    date_range_start TIMESTAMP,
    date_range_end TIMESTAMP,
    content JSONB,
    format VARCHAR(10) DEFAULT 'json',
    file_path TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_agent_actions_status ON security_agent_actions(status);
CREATE INDEX IF NOT EXISTS idx_agent_actions_category ON security_agent_actions(category);
CREATE INDEX IF NOT EXISTS idx_agent_actions_created ON security_agent_actions(created_at);
CREATE INDEX IF NOT EXISTS idx_recon_scans_status ON security_recon_scans(status);
CREATE INDEX IF NOT EXISTS idx_scan_results_severity ON security_scan_results(severity);
CREATE INDEX IF NOT EXISTS idx_camera_events_camera ON security_camera_events(camera_entity);
CREATE INDEX IF NOT EXISTS idx_camera_events_type ON security_camera_events(event_type);
CREATE INDEX IF NOT EXISTS idx_camera_events_created ON security_camera_events(created_at);
CREATE INDEX IF NOT EXISTS idx_dns_changes_source ON security_dns_changes(source);
CREATE INDEX IF NOT EXISTS idx_dns_changes_created ON security_dns_changes(created_at);

COMMIT;
```

**Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/082_security_network_rebuild.sql
```

Expected: `BEGIN`, `CREATE TABLE` x6, `CREATE INDEX` x10, `COMMIT`

**Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt security_*"
```

Expected: 6 new tables listed (plus existing `security_auto_block_settings`, `security_events`, `security_ip_access`, `security_ssl_monitors`)

**Step 4: Commit**

```bash
git add database/migrations/082_security_network_rebuild.sql
git commit -m "feat(db): add security_network rebuild tables (migration 082)"
```

---

### Task 2: AdGuard Service — Full API Client

**Files:**
- Create: `platform_v2/tools/security_network/adguard_service.py`
- Reference: `platform_v2/tools/security_network/stack_integration.py` (existing `AdGuardLocalAPI` for pattern)

**Step 1: Write the AdGuard service**

This replaces the basic `AdGuardLocalAPI` in `stack_integration.py` with a comprehensive client covering all AdGuard API endpoints needed for the DNS Management tab.

```python
"""
AdGuard Home Full API Service
==============================
Comprehensive client for AdGuard Home REST API.
Covers: status, stats, query log, filtering, DNS rewrites, clients.
"""

import os
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime


class AdGuardService:
    """Full AdGuard Home API client"""

    def __init__(self):
        host = os.getenv("ADGUARD_HOST", "network_adguard")
        port = int(os.getenv("ADGUARD_PORT", "80"))
        self.base_url = f"http://{host}:{port}"
        self.fallback_url = "http://192.168.1.200:5355"
        self.username = os.getenv("ADGUARD_USER", "archie_admin")
        self.password = os.getenv("ADGUARD_PASS", "")
        self._active_url = None

    def _request(self, method: str, endpoint: str, data: Any = None,
                 params: dict = None, timeout: int = 10) -> Optional[Any]:
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
    def get_query_log(self, limit: int = 100, offset: int = 0,
                      search: str = None, response_status: str = None) -> Optional[Dict]:
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
        return self._request("POST", "filtering/add_url",
                             {"name": name, "url": url, "whitelist": False})

    def remove_filter(self, url: str) -> Optional[Dict]:
        return self._request("POST", "filtering/remove_url",
                             {"url": url, "whitelist": False})

    def toggle_filter(self, url: str, enabled: bool) -> Optional[Dict]:
        return self._request("POST", "filtering/set_url",
                             {"url": url, "data": {"enabled": enabled}})

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
        return self._request("POST", "rewrite/add",
                             {"domain": domain, "answer": answer})

    def delete_rewrite(self, domain: str, answer: str) -> Optional[Dict]:
        return self._request("POST", "rewrite/delete",
                             {"domain": domain, "answer": answer})

    # --- Clients ---
    def get_clients(self) -> Optional[Dict]:
        return self._request("GET", "clients")

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

    # --- Protection ---
    def set_protection(self, enabled: bool) -> Optional[Dict]:
        return self._request("POST", "dns_config",
                             {"protection_enabled": enabled})
```

**Step 2: Verify the service loads in the container**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from tools.security_network.adguard_service import AdGuardService
svc = AdGuardService()
print('Status:', svc.get_status())
print('Health:', svc.check_health())
"
```

Expected: Status shows AdGuard version info, Health returns True

**Step 3: Commit**

```bash
git add platform_v2/tools/security_network/adguard_service.py
git commit -m "feat(security): add comprehensive AdGuard API service"
```

---

### Task 3: Hostinger DNS Service

**Files:**
- Create: `platform_v2/tools/security_network/hostinger_service.py`

**Step 1: Write the Hostinger service**

```python
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

    def _request(self, method: str, endpoint: str, data: Any = None,
                 timeout: int = 15) -> Optional[Any]:
        if not self.available:
            return None
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = requests.request(method, url, headers=self._headers(),
                                    json=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json() if resp.content else {"status": "ok"}
        except Exception as e:
            return {"error": str(e)}

    # --- DNS Records ---
    def get_dns_records(self, domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request("GET", f"dns/v1/domains/{domain}/dns-records")

    def add_dns_record(self, record_type: str, name: str, value: str,
                       ttl: int = 3600, domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request("POST", f"dns/v1/domains/{domain}/dns-records", {
            "type": record_type,
            "name": name,
            "content": value,
            "ttl": ttl,
        })

    def update_dns_record(self, record_id: str, record_type: str, name: str,
                          value: str, ttl: int = 3600, domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request("PUT", f"dns/v1/domains/{domain}/dns-records", {
            "overwrite": False,
            "records": [{"type": record_type, "name": name, "content": value, "ttl": ttl}],
        })

    def delete_dns_record(self, record_type: str = None, name: str = None,
                          domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        params = {}
        if record_type:
            params["type"] = record_type
        if name:
            params["name"] = name
        return self._request("DELETE", f"dns/v1/domains/{domain}/dns-records", params)

    def validate_dns_records(self, records: List[Dict], domain: str = None) -> Optional[Any]:
        domain = domain or self.domain
        return self._request("POST", f"dns/v1/domains/{domain}/dns-records/validate",
                             {"records": records})

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
        return result is not None and "error" not in result
```

**Step 2: Commit**

```bash
git add platform_v2/tools/security_network/hostinger_service.py
git commit -m "feat(security): add Hostinger DNS API service"
```

---

### Task 4: Home Assistant Surveillance Service

**Files:**
- Create: `platform_v2/tools/security_network/ha_surveillance_service.py`

**Step 1: Write the HA surveillance service**

```python
"""
Home Assistant Surveillance Service
====================================
Camera management via HA REST API for Blink cameras.
Provides: snapshots, motion events, arm/disarm, camera states.
"""

import os
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime


class HASurveillanceService:
    """Home Assistant camera integration"""

    # Known Blink cameras from HA device registry
    CAMERAS = {
        "driveway": {"entity": "camera.driveway", "location": "Driveway", "area": "driveway"},
        "front_yard": {"entity": "camera.front_yard", "location": "Front Yard", "area": "front_yard"},
        "backyard": {"entity": "camera.backyard", "location": "Backyard", "area": "backyard"},
        "porch_camera": {"entity": "camera.porch_camera", "location": "Porch", "area": "porch"},
        "doorbell": {"entity": "camera.doorbell", "location": "Porch (Doorbell)", "area": "porch"},
    }

    ALARM_ENTITY = "alarm_control_panel.blink_home"

    def __init__(self):
        self.base_url = os.getenv("HA_URL", "http://192.168.1.200:8123")
        self.token = os.getenv("HA_API_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, timeout: int = 10) -> Optional[Any]:
        if not self.available:
            return None
        try:
            resp = requests.get(f"{self.base_url}/api/{endpoint}",
                                headers=self._headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.json() if resp.content else None
        except Exception:
            return None

    def _post(self, endpoint: str, data: dict = None, timeout: int = 10) -> Optional[Any]:
        if not self.available:
            return None
        try:
            resp = requests.post(f"{self.base_url}/api/{endpoint}",
                                 headers=self._headers(), json=data or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json() if resp.content else {"status": "ok"}
        except Exception:
            return None

    def _get_raw(self, endpoint: str, timeout: int = 15) -> Optional[bytes]:
        """Get raw bytes (for camera snapshots)"""
        if not self.available:
            return None
        try:
            resp = requests.get(f"{self.base_url}/api/{endpoint}",
                                headers=self._headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    # --- Camera States ---
    def get_all_cameras(self) -> List[Dict]:
        """Get state of all known cameras with attributes"""
        cameras = []
        for cam_id, info in self.CAMERAS.items():
            state = self._get(f"states/{info['entity']}")
            if state:
                # Get motion sensor state
                motion_entity = f"binary_sensor.{cam_id}_motion_detected"
                motion_state = self._get(f"states/{motion_entity}")
                # Get battery state
                battery_entity = f"binary_sensor.{cam_id}_battery"
                battery_state = self._get(f"states/{battery_entity}")

                cameras.append({
                    "id": cam_id,
                    "entity": info["entity"],
                    "location": info["location"],
                    "area": info["area"],
                    "state": state.get("state", "unknown"),
                    "attributes": state.get("attributes", {}),
                    "motion": motion_state.get("state", "off") if motion_state else "unknown",
                    "battery_ok": battery_state.get("state", "on") if battery_state else "unknown",
                    "last_updated": state.get("last_updated", ""),
                })
            else:
                cameras.append({
                    "id": cam_id, "entity": info["entity"],
                    "location": info["location"], "area": info["area"],
                    "state": "unavailable", "attributes": {},
                    "motion": "unknown", "battery_ok": "unknown",
                    "last_updated": "",
                })
        return cameras

    def get_camera_snapshot(self, camera_id: str) -> Optional[bytes]:
        """Get latest camera snapshot as image bytes"""
        info = self.CAMERAS.get(camera_id)
        if not info:
            return None
        return self._get_raw(f"camera_proxy/{info['entity']}")

    def trigger_snapshot(self, camera_id: str) -> bool:
        """Force camera to take a new snapshot"""
        info = self.CAMERAS.get(camera_id)
        if not info:
            return False
        result = self._post("services/blink/trigger_camera", {
            "entity_id": info["entity"]
        })
        return result is not None

    # --- Arm / Disarm ---
    def get_alarm_state(self) -> Optional[Dict]:
        return self._get(f"states/{self.ALARM_ENTITY}")

    def arm_system(self) -> bool:
        result = self._post("services/alarm_control_panel/alarm_arm_away", {
            "entity_id": self.ALARM_ENTITY
        })
        return result is not None

    def disarm_system(self) -> bool:
        result = self._post("services/alarm_control_panel/alarm_disarm", {
            "entity_id": self.ALARM_ENTITY
        })
        return result is not None

    # --- Motion Events ---
    def get_recent_events(self, hours: int = 24) -> List[Dict]:
        """Get recent motion/state change events from HA history"""
        events = []
        for cam_id, info in self.CAMERAS.items():
            motion_entity = f"binary_sensor.{cam_id}_motion_detected"
            history = self._get(f"history/period?filter_entity_id={motion_entity}&minimal_response")
            if history and isinstance(history, list) and len(history) > 0:
                for entry in history[0]:
                    if entry.get("state") == "on":
                        events.append({
                            "camera": cam_id,
                            "location": info["location"],
                            "event_type": "motion",
                            "timestamp": entry.get("last_changed", ""),
                        })
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events

    def check_health(self) -> bool:
        if not self.available:
            return False
        result = self._get("states")
        return isinstance(result, list)
```

**Step 2: Commit**

```bash
git add platform_v2/tools/security_network/ha_surveillance_service.py
git commit -m "feat(security): add Home Assistant surveillance service for Blink cameras"
```

---

### Task 5: Argus Reconnaissance Service

**Files:**
- Create: `platform_v2/tools/security_network/argus_service.py`

**Step 1: Install Argus in the Docker container**

```bash
docker exec archie_platform pip install argus-recon 2>&1 | tail -5
```

Expected: `Successfully installed argus-recon-X.X.X`

If pip install fails (some CLI tools don't install cleanly), fall back to:
```bash
docker exec archie_platform pip install requests dnspython whois python-nmap 2>&1 | tail -5
```

**Step 2: Write the Argus wrapper service**

```python
"""
Argus Reconnaissance Service
==============================
Wrapper for Argus CLI toolkit and direct Python recon capabilities.
Curated ~25 modules from Argus's 135 for home network security.
"""

import os
import json
import subprocess
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime
import psycopg2
from psycopg2.extras import Json


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# Curated module list — most useful for home/small network
CURATED_MODULES = {
    "network": [
        {"id": "dns_lookup", "name": "DNS Lookup", "description": "Resolve domain to IP addresses"},
        {"id": "reverse_dns", "name": "Reverse DNS", "description": "IP to hostname resolution"},
        {"id": "whois", "name": "WHOIS Lookup", "description": "Domain registration info"},
        {"id": "port_scan", "name": "Port Scan", "description": "Scan for open ports on target"},
        {"id": "traceroute", "name": "Traceroute", "description": "Network path to target"},
        {"id": "dnssec_check", "name": "DNSSEC Check", "description": "Validate DNSSEC configuration"},
        {"id": "tls_check", "name": "TLS/SSL Check", "description": "Analyze TLS certificate and cipher suites"},
        {"id": "ip_geolocation", "name": "IP Geolocation", "description": "Geographic location of IP"},
    ],
    "web": [
        {"id": "tech_detect", "name": "Technology Detection", "description": "Identify web technologies in use"},
        {"id": "header_analysis", "name": "Header Analysis", "description": "HTTP security header check"},
        {"id": "subdomain_enum", "name": "Subdomain Enumeration", "description": "Find subdomains of a domain"},
        {"id": "robots_txt", "name": "robots.txt Parser", "description": "Parse and analyze robots.txt"},
        {"id": "sitemap_parse", "name": "Sitemap Parser", "description": "Parse XML sitemap"},
        {"id": "cors_check", "name": "CORS Check", "description": "Test CORS misconfiguration"},
        {"id": "ssl_cert_info", "name": "SSL Certificate Info", "description": "Detailed certificate analysis"},
    ],
    "threat_intel": [
        {"id": "virustotal", "name": "VirusTotal Lookup", "description": "Check domain/IP against VT database"},
        {"id": "shodan", "name": "Shodan Search", "description": "Search Shodan for exposed services"},
        {"id": "hibp_check", "name": "HIBP Breach Check", "description": "Check email in breach databases"},
        {"id": "ip_reputation", "name": "IP Reputation", "description": "Check IP against threat feeds"},
        {"id": "malware_check", "name": "Malware Domain Check", "description": "Check domain against malware lists"},
    ],
    "discovery": [
        {"id": "crawler", "name": "Web Crawler", "description": "Crawl and map website structure"},
        {"id": "dir_brute", "name": "Directory Discovery", "description": "Find hidden directories and files"},
        {"id": "js_analysis", "name": "JavaScript Analysis", "description": "Analyze JS files for sensitive data"},
        {"id": "email_harvest", "name": "Email Harvester", "description": "Find email addresses from target"},
    ],
}


class ArgusService:
    """Argus reconnaissance toolkit wrapper"""

    def __init__(self):
        self.argus_available = self._check_argus()

    def _check_argus(self) -> bool:
        """Check if Argus CLI is installed"""
        try:
            result = subprocess.run(
                ["python3", "-m", "argus", "--version"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_modules(self) -> Dict[str, List[Dict]]:
        """Get curated module list"""
        return CURATED_MODULES

    def get_module_count(self) -> int:
        return sum(len(mods) for mods in CURATED_MODULES.values())

    def start_scan(self, module_id: str, target: str, options: dict = None,
                   triggered_by: str = "user") -> Optional[int]:
        """Start a scan and return scan ID"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO security_recon_scans (module_name, target, options, status, triggered_by)
                VALUES (%s, %s, %s, 'running', %s) RETURNING id
            """, (module_id, target, Json(options or {}), triggered_by))
            scan_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

            # Run scan in background thread
            thread = threading.Thread(
                target=self._execute_scan,
                args=(scan_id, module_id, target, options or {}),
                daemon=True
            )
            thread.start()
            return scan_id
        except Exception:
            return None

    def _execute_scan(self, scan_id: int, module_id: str, target: str, options: dict):
        """Execute scan in background and store results"""
        results = {}
        try:
            # Use Python libraries directly for reliability
            if module_id == "dns_lookup":
                results = self._dns_lookup(target)
            elif module_id == "reverse_dns":
                results = self._reverse_dns(target)
            elif module_id == "whois":
                results = self._whois_lookup(target)
            elif module_id == "port_scan":
                results = self._port_scan(target, options)
            elif module_id == "header_analysis":
                results = self._header_analysis(target)
            elif module_id == "tls_check":
                results = self._tls_check(target)
            elif module_id == "ssl_cert_info":
                results = self._ssl_cert_info(target)
            else:
                # Try Argus CLI for other modules
                results = self._run_argus_cli(module_id, target)

            status = "completed"
        except Exception as e:
            results = {"error": str(e)}
            status = "failed"

        # Store results
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                UPDATE security_recon_scans
                SET results = %s, status = %s, completed_at = NOW()
                WHERE id = %s
            """, (Json(results), status, scan_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    def _dns_lookup(self, target: str) -> Dict:
        import socket
        try:
            results = socket.getaddrinfo(target, None)
            ips = list(set(r[4][0] for r in results))
            return {"domain": target, "addresses": ips, "count": len(ips)}
        except Exception as e:
            return {"error": str(e)}

    def _reverse_dns(self, target: str) -> Dict:
        import socket
        try:
            hostname = socket.gethostbyaddr(target)
            return {"ip": target, "hostname": hostname[0], "aliases": hostname[1]}
        except Exception as e:
            return {"error": str(e)}

    def _whois_lookup(self, target: str) -> Dict:
        try:
            import whois
            w = whois.whois(target)
            return {
                "domain": target,
                "registrar": str(w.registrar) if w.registrar else None,
                "creation_date": str(w.creation_date) if w.creation_date else None,
                "expiration_date": str(w.expiration_date) if w.expiration_date else None,
                "name_servers": list(w.name_servers) if w.name_servers else [],
            }
        except Exception as e:
            return {"error": str(e)}

    def _port_scan(self, target: str, options: dict) -> Dict:
        """Basic port scan using sockets"""
        import socket
        ports = options.get("ports", [22, 53, 80, 443, 3000, 5432, 8080, 8123, 8443])
        open_ports = []
        for port in ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((target, port))
                if result == 0:
                    open_ports.append(port)
                sock.close()
            except Exception:
                pass
        return {"target": target, "open_ports": open_ports, "scanned": len(ports)}

    def _header_analysis(self, target: str) -> Dict:
        url = target if target.startswith("http") else f"https://{target}"
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            security_headers = {
                "Strict-Transport-Security": resp.headers.get("Strict-Transport-Security"),
                "Content-Security-Policy": resp.headers.get("Content-Security-Policy"),
                "X-Content-Type-Options": resp.headers.get("X-Content-Type-Options"),
                "X-Frame-Options": resp.headers.get("X-Frame-Options"),
                "X-XSS-Protection": resp.headers.get("X-XSS-Protection"),
                "Referrer-Policy": resp.headers.get("Referrer-Policy"),
            }
            missing = [h for h, v in security_headers.items() if not v]
            return {
                "url": url, "status_code": resp.status_code,
                "headers": security_headers,
                "missing_headers": missing,
                "score": f"{(6 - len(missing))}/6",
            }
        except Exception as e:
            return {"error": str(e)}

    def _tls_check(self, target: str) -> Dict:
        import ssl
        import socket
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=target) as s:
                s.settimeout(5)
                s.connect((target, 443))
                cert = s.getpeercert()
                return {
                    "domain": target,
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "not_before": cert.get("notBefore"),
                    "not_after": cert.get("notAfter"),
                    "version": s.version(),
                    "cipher": s.cipher(),
                }
        except Exception as e:
            return {"error": str(e)}

    def _ssl_cert_info(self, target: str) -> Dict:
        return self._tls_check(target)

    def _run_argus_cli(self, module_id: str, target: str) -> Dict:
        """Fallback: run Argus CLI module"""
        try:
            result = subprocess.run(
                ["python3", "-m", "argus", "-m", module_id, "-t", target, "--json"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"raw_output": result.stdout}
            return {"error": result.stderr or "Scan failed"}
        except subprocess.TimeoutExpired:
            return {"error": "Scan timed out"}
        except Exception as e:
            return {"error": str(e)}

    def get_scan(self, scan_id: int) -> Optional[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM security_recon_scans WHERE id = %s", (scan_id,))
            result = cur.fetchone()
            cur.close()
            conn.close()
            return dict(result) if result else None
        except Exception:
            return None

    def get_scan_history(self, limit: int = 50) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, module_name, target, status, started_at, completed_at, triggered_by
                FROM security_recon_scans ORDER BY started_at DESC LIMIT %s
            """, (limit,))
            results = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in results]
        except Exception:
            return []

    def check_health(self) -> bool:
        return True  # Always available (uses built-in Python libs as fallback)
```

**Step 3: Commit**

```bash
git add platform_v2/tools/security_network/argus_service.py
git commit -m "feat(security): add Argus reconnaissance service with curated modules"
```

---

### Task 6: Agent Automation Service

**Files:**
- Create: `platform_v2/tools/security_network/agent_automation.py`

**Step 1: Write the agent automation service**

```python
"""
Security Agent Automation Service
==================================
Manages agent suggestions, auto-actions, and configuration.
Default: suggest-only. Per-category auto-mode toggleable.
"""

import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor, Json


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# Default agent configuration
DEFAULT_CONFIG = {
    "mode": "suggest",  # "suggest" or "auto"
    "paused": False,
    "categories": {
        "dns": {"auto_enabled": False, "description": "DNS filtering and blocking"},
        "camera": {"auto_enabled": False, "description": "Camera arm/disarm scheduling"},
        "scanning": {"auto_enabled": False, "description": "Auto-scan new devices"},
        "access": {"auto_enabled": False, "description": "Auto-block after threshold"},
        "filters": {"auto_enabled": False, "description": "Auto-update filter lists"},
    },
}


class AgentAutomationService:
    """Agent suggestion and automation manager"""

    def __init__(self):
        self._config = None

    def get_config(self) -> Dict:
        """Get current agent configuration from DB or defaults"""
        if self._config:
            return self._config
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT setting_value FROM security_auto_block_settings
                WHERE setting_key = 'agent_config'
            """)
            result = cur.fetchone()
            cur.close()
            conn.close()
            if result:
                self._config = json.loads(result["setting_value"])
                return self._config
        except Exception:
            pass
        self._config = DEFAULT_CONFIG.copy()
        return self._config

    def save_config(self, config: Dict) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO security_auto_block_settings (setting_key, setting_value)
                VALUES ('agent_config', %s)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value
            """, (json.dumps(config),))
            conn.commit()
            cur.close()
            conn.close()
            self._config = config
            return True
        except Exception:
            return False

    def set_mode(self, mode: str) -> bool:
        config = self.get_config()
        config["mode"] = mode
        return self.save_config(config)

    def set_paused(self, paused: bool) -> bool:
        config = self.get_config()
        config["paused"] = paused
        return self.save_config(config)

    def toggle_category_auto(self, category: str, enabled: bool) -> bool:
        config = self.get_config()
        if category in config.get("categories", {}):
            config["categories"][category]["auto_enabled"] = enabled
            return self.save_config(config)
        return False

    def is_auto_enabled(self, category: str) -> bool:
        config = self.get_config()
        if config.get("paused"):
            return False
        if config.get("mode") != "auto":
            return False
        return config.get("categories", {}).get(category, {}).get("auto_enabled", False)

    # --- Suggestions ---
    def create_suggestion(self, category: str, title: str, description: str,
                          reasoning: str, data: dict = None) -> Optional[int]:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO security_agent_actions
                (action_type, category, title, description, reasoning, status, data)
                VALUES ('suggest', %s, %s, %s, %s, 'pending', %s) RETURNING id
            """, (category, title, description, reasoning, Json(data or {})))
            action_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return action_id
        except Exception:
            return None

    def approve_suggestion(self, suggestion_id: int) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                UPDATE security_agent_actions
                SET status = 'approved', executed_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """, (suggestion_id,))
            affected = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            return affected > 0
        except Exception:
            return False

    def dismiss_suggestion(self, suggestion_id: int) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                UPDATE security_agent_actions
                SET status = 'dismissed', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """, (suggestion_id,))
            affected = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            return affected > 0
        except Exception:
            return False

    def get_pending_suggestions(self, category: str = None, limit: int = 50) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            if category:
                cur.execute("""
                    SELECT * FROM security_agent_actions
                    WHERE status = 'pending' AND category = %s
                    ORDER BY created_at DESC LIMIT %s
                """, (category, limit))
            else:
                cur.execute("""
                    SELECT * FROM security_agent_actions
                    WHERE status = 'pending'
                    ORDER BY created_at DESC LIMIT %s
                """, (limit,))
            results = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in results]
        except Exception:
            return []

    def get_action_history(self, limit: int = 100) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT * FROM security_agent_actions
                ORDER BY created_at DESC LIMIT %s
            """, (limit,))
            results = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in results]
        except Exception:
            return []

    def log_auto_action(self, category: str, title: str, description: str,
                        reasoning: str, data: dict = None, success: bool = True) -> Optional[int]:
        """Log an automatically executed action"""
        status = "executed" if success else "failed"
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO security_agent_actions
                (action_type, category, title, description, reasoning, status, data, executed_at)
                VALUES ('auto_execute', %s, %s, %s, %s, %s, %s, NOW()) RETURNING id
            """, (category, title, description, reasoning, status, Json(data or {})))
            action_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return action_id
        except Exception:
            return None
```

**Step 2: Commit**

```bash
git add platform_v2/tools/security_network/agent_automation.py
git commit -m "feat(security): add agent automation service with suggest/auto modes"
```

---

## Phase 2: Routes & API (Tasks 7-8)

### Task 7: Rebuild Routes — API Endpoints

**Files:**
- Modify: `platform_v2/tools/security_network/routes.py` (major rewrite)

**Context:** The existing routes.py (1329 lines) has scanner endpoints, basic AdGuard stats, IP access control, SSL monitoring. We keep all existing functionality but reorganize and add new endpoints for the 7-tab structure. This is the largest single task.

**Step 1: Rewrite routes.py with all new API endpoints**

The new routes.py should:
1. Import all new services (adguard_service, hostinger_service, ha_surveillance_service, argus_service, agent_automation)
2. Keep existing endpoints that still work (scanner, IP access, SSL monitoring)
3. Add all new endpoints from the design doc Section 7

Key structure:
- `GET /` — Main page render
- `/api/dashboard/*` — Dashboard stats aggregation
- `/api/dns/adguard/*` — All AdGuard endpoints
- `/api/dns/hostinger/*` — All Hostinger endpoints
- `/api/surveillance/*` — Camera endpoints
- `/api/recon/*` — Argus endpoints
- `/api/agent/*` — Agent automation endpoints
- `/api/reports/*` — Report endpoints
- Keep existing: `/api/scanners/*`, `/api/security/*`, `/api/adguard/*` (legacy compat)

**Important:** This file is too large to put entirely in the plan. The implementing agent should:
1. Read the current `routes.py` fully
2. Keep all existing route functions that are still needed
3. Add new service imports at the top
4. Add new route groups below existing ones
5. Ensure the main `index()` route still renders the template

**Step 2: Test that the module loads**

```bash
docker compose restart archie_platform && sleep 5
curl -s http://192.168.1.200:3000/tools/security-network/ -o /dev/null -w "%{http_code}"
```

Expected: `302` (redirect to login) or `200` (if session active)

**Step 3: Test key API endpoints**

```bash
# AdGuard stats
curl -s http://192.168.1.200:3000/tools/security-network/api/dns/adguard/stats -b cookies.txt | python3 -m json.tool | head -10

# Camera list (will fail gracefully if no HA token yet)
curl -s http://192.168.1.200:3000/tools/security-network/api/surveillance/cameras -b cookies.txt | python3 -m json.tool | head -10
```

**Step 4: Commit**

```bash
git add platform_v2/tools/security_network/routes.py
git commit -m "feat(security): rebuild routes with full API for 7-tab module"
```

---

### Task 8: Template Rebuild — 7-Tab Frontend

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html` (full rebuild)

**REQUIRED:** Use `/frontend-design` skill for this task. Follow LCARS design standards from Dev HQ.

**Step 1: Rebuild the template**

The template should follow the System Operations tab pattern:
- `{% extends "base.html" %}` with `{% block module_name %}security-network{% endblock %}`
- Security red accent color (`--archie-accent: var(--archie-red)`)
- 7 main tabs with `data-tab` attributes and lazy-loading
- DNS Management tab has 6 subtabs
- Responsive at 374px / 717px / 1280px breakpoints

**Tab nav structure:**
```html
<div class="tab-nav">
    <button class="tab-btn active" data-tab="dashboard">Dashboard</button>
    <button class="tab-btn" data-tab="dns">DNS Management</button>
    <button class="tab-btn" data-tab="surveillance">Surveillance</button>
    <button class="tab-btn" data-tab="recon">Reconnaissance</button>
    <button class="tab-btn" data-tab="scanning">Vulnerability Scanning</button>
    <button class="tab-btn" data-tab="access">Access Control</button>
    <button class="tab-btn" data-tab="reports">Reports</button>
</div>
```

**JavaScript patterns (from System Operations):**
- Tab switching: toggle `.active` on button and content div
- Lazy loading: `*TabLoaded` flags, load data on first visit
- Fetch APIs with `/tools/security-network/api/...` prefix
- Error handling: show error cards on fetch failure
- Auto-refresh: configurable polling for query log and camera snapshots

**Step 2: Test at all breakpoints**

Use Playwright or manual testing at 374px, 717px, 1280px.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "feat(security): rebuild template with 7-tab design using frontend-design skill"
```

---

## Phase 3: Integration & Polish (Tasks 9-12)

### Task 9: Meraki Service (Optional)

**Files:**
- Create: `platform_v2/tools/security_network/meraki_service.py`

**Step 1: Write the Meraki service**

Tiered integration:
- Tier 1 (no API key): Use HA device tracker data
- Tier 2 (with API key): Full Meraki Dashboard API via `meraki` Python SDK

```bash
docker exec archie_platform pip install meraki 2>&1 | tail -3
```

**Step 2: Commit**

```bash
git add platform_v2/tools/security_network/meraki_service.py
git commit -m "feat(security): add optional Meraki WiFi integration (tiered)"
```

---

### Task 10: Environment Variables

**Files:**
- Modify: `.env` (root)
- Modify: `platform_v2/.env`

**Step 1: Add new environment variables**

Add to both `.env` files:
```env
# AdGuard Home (update existing if needed)
ADGUARD_HOST=network_adguard
ADGUARD_PORT=80
ADGUARD_USER=archie_admin
ADGUARD_PASS=<existing>

# Hostinger DNS API
HOSTINGER_API_KEY=
HOSTINGER_DOMAIN=kytranempowerment.com

# Home Assistant
HA_URL=http://192.168.1.200:8123
HA_API_TOKEN=

# Argus API keys (optional)
VIRUSTOTAL_API_KEY=
SHODAN_API_KEY=

# Meraki (optional)
MERAKI_API_KEY=
```

**Step 2: Commit**

```bash
git add .env platform_v2/.env
git commit -m "feat(config): add env vars for security module integrations"
```

**Note:** User needs to fill in HA_API_TOKEN (generate Long-Lived Access Token in HA UI) and HOSTINGER_API_KEY before those features work.

---

### Task 11: Update Module Registry & RBAC

**Files:**
- Modify: `platform_v2/module_registry.py`

**Step 1: Verify/update the module registration**

Check that the security_network module entry has correct description reflecting the rebuild. Update if needed.

**Step 2: Commit if changes made**

---

### Task 12: Responsive Testing & Playwright Screenshots

**Files:**
- Create: `platform_v2/tests/test_security_network_redesign.mjs`

**Step 1: Write Playwright test**

Following the existing test pattern in `platform_v2/tests/`:

```javascript
// Test Security & Network module at all breakpoints
// Captures screenshots for before/after comparison

import { chromium } from 'playwright';

const BASE_URL = 'http://192.168.1.200:3000';
const BREAKPOINTS = [
    { name: 'mobile', width: 374, height: 812 },
    { name: 'tablet', width: 717, height: 1024 },
    { name: 'desktop', width: 1280, height: 800 },
];

// ... login, navigate to /tools/security-network, screenshot each tab at each breakpoint
```

**Step 2: Run tests**

```bash
npx playwright test platform_v2/tests/test_security_network_redesign.mjs
```

**Step 3: Commit**

```bash
git add platform_v2/tests/test_security_network_redesign.mjs
git commit -m "test(security): add Playwright responsive test for redesigned module"
```

---

## Task Dependencies

```
Task 1 (DB migration) ──────┐
Task 2 (AdGuard service) ───┤
Task 3 (Hostinger service) ─┤
Task 4 (HA surveillance) ───┼──→ Task 7 (Routes rebuild) ──→ Task 8 (Template) ──→ Task 12 (Testing)
Task 5 (Argus service) ─────┤
Task 6 (Agent automation) ──┘
                                Task 9 (Meraki - optional, parallel)
                                Task 10 (Env vars - parallel with Task 7)
                                Task 11 (Registry check - after Task 7)
```

Tasks 1-6 can run in parallel. Task 7 depends on all of them. Task 8 depends on Task 7. Tasks 9-11 can be done in parallel with or after Task 8. Task 12 is last.

---

## Dev HQ Updates Required

After completion:
- `mcp complete_task` for Task #630 (Redesign: Security & Network)
- `mcp update_project_understanding` for Project #94
- `mcp store_memory` with vault_note summarizing the rebuild
- `mcp log_decision` for any runtime architectural decisions made during implementation
