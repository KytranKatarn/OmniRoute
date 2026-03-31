# Security Network NOC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Security Network module into a full Network Operations Center with live traffic monitoring, threat defense, and AI-driven autonomous response via V.I.G.I.L.

**Architecture:** 5 data sources (AdGuard, ntopng, Nagios, fail2ban, DDNS) feed into ARCHIE's DB. Security Network module provides the UI + API layer (8 tabs). V.I.G.I.L. agent runs 8 autonomous jobs via the Autonomy module under the Security & Compliance department.

**Tech Stack:** Flask/Jinja2 (existing), PostgreSQL, Docker (ntopng + Redis), AdGuard API, Nagios CGI API, ntopng REST API, fail2ban CLI, APScheduler (agent loop)

**Spec:** `docs/superpowers/specs/2026-03-31-security-network-noc-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `platform_v2/tools/security_network/ntopng_service.py` | ntopng REST API client — bandwidth, flows, hosts, protocol data |
| `platform_v2/tools/security_network/nagios_service.py` | Nagios CGI API client — host/service status, check results |
| `platform_v2/tools/security_network/fail2ban_service.py` | fail2ban CLI wrapper — list jails, ban/unban, jail config |
| `platform_v2/tools/security_network/ddns_service.py` | DDNS management — IP history, manual trigger, status |
| `platform_v2/tools/security_network/traffic_routes.py` | Routes for Traffic tab (bandwidth, flows, protocol data) |
| `platform_v2/tools/security_network/defense_routes.py` | Routes for Defense tab (fail2ban, DDNS, UFW management) |
| `platform_v2/tools/security_network/device_routes.py` | Routes for Devices tab (inventory, user mapping) |
| `platform_v2/tools/security_network/report_routes.py` | Routes for Reports tab (daily, weekly, on-demand) |
| `platform_v2/tools/security_network/noc_routes.py` | Routes for Overview tab (NOC command view, hero stats) |
| `platform_v2/tools/security_network/report_service.py` | Report generation — daily/weekly/threat, PDF, delivery |
| `platform_v2/static/js/security-network.js` | Client-side JS for all 8 tabs |
| `platform_v2/static/css/security-network.css` | Module CSS with `sn-` prefix |
| `database/migrations/060_security_noc_tables.sql` | New tables: traffic_stats, dns_stats, device_users, alerts, ip_history, reports, nagios |
| `network-tools/docker-compose.yml` | Docker compose for ntopng + Redis stack |
| `tests/test_security_network/test_ntopng_service.py` | Tests for ntopng service |
| `tests/test_security_network/test_nagios_service.py` | Tests for Nagios service |
| `tests/test_security_network/test_fail2ban_service.py` | Tests for fail2ban service |
| `tests/test_security_network/test_ddns_service.py` | Tests for DDNS service |
| `tests/test_security_network/test_report_service.py` | Tests for report generation |

### Modified Files
| File | What Changes |
|------|-------------|
| `platform_v2/tools/security_network/__init__.py` | Register new route modules via `register_*_routes(bp, admin_required)` |
| `platform_v2/tools/security_network/routes.py` | Extract traffic/defense/device/report routes to new files, keep scanner + AdGuard + core |
| `platform_v2/tools/security_network/adguard_service.py` | Add stats aggregation methods, client list enrichment |
| `platform_v2/tools/security_network/device_registry_service.py` | Add user mapping CRUD, device-type classification |
| `platform_v2/templates/tools/security_network.html` | Rebuild with 8-tab structure, LCARS NOC layout |
| `ai_bridge/agent_loop.py` | Register 8 V.I.G.I.L. agent loop jobs under Security & Compliance department |
| `docker-compose.yml` (root) | Reference network-tools compose or add ntopng + redis services |
| `platform_v2/.env` | Add NAGIOS_USER, NAGIOS_PASS, NTOPNG_ADMIN_PASSWORD |
| `.env` | Add NAGIOS_USER, NAGIOS_PASS, NTOPNG_ADMIN_PASSWORD |

---

## Phase 1 — Fix & Stabilize (Foundation)

### Task 1: Database Migration — NOC Tables

**Files:**
- Create: `database/migrations/060_security_noc_tables.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 060_security_noc_tables.sql
-- Security Network NOC tables for traffic, DNS, alerts, reports, DDNS, Nagios

BEGIN;

-- Device-to-user mapping (extends network_devices with person assignment)
CREATE TABLE IF NOT EXISTS network_device_users (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(17) UNIQUE NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    device_label VARCHAR(200),
    device_type VARCHAR(50) DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Hourly bandwidth aggregates from ntopng
CREATE TABLE IF NOT EXISTS network_traffic_stats (
    id SERIAL PRIMARY KEY,
    device_mac VARCHAR(17),
    device_ip VARCHAR(45),
    bytes_in BIGINT DEFAULT 0,
    bytes_out BIGINT DEFAULT 0,
    protocol VARCHAR(50),
    hour_bucket TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_traffic_stats_hour ON network_traffic_stats(hour_bucket);
CREATE INDEX IF NOT EXISTS idx_traffic_stats_device ON network_traffic_stats(device_mac);

-- Hourly DNS query aggregates from AdGuard
CREATE TABLE IF NOT EXISTS network_dns_stats (
    id SERIAL PRIMARY KEY,
    client_ip VARCHAR(45),
    total_queries INTEGER DEFAULT 0,
    blocked_queries INTEGER DEFAULT 0,
    top_domains JSONB DEFAULT '[]',
    hour_bucket TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dns_stats_hour ON network_dns_stats(hour_bucket);
CREATE INDEX IF NOT EXISTS idx_dns_stats_client ON network_dns_stats(client_ip);

-- Generated reports
CREATE TABLE IF NOT EXISTS network_daily_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    report_type VARCHAR(50) NOT NULL,
    data_json JSONB NOT NULL,
    pdf_path VARCHAR(500),
    delivered_via JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

-- DDNS IP change history
CREATE TABLE IF NOT EXISTS network_ip_history (
    id SERIAL PRIMARY KEY,
    old_ip VARCHAR(45),
    new_ip VARCHAR(45) NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    dns_updated BOOLEAN DEFAULT FALSE,
    subdomains_updated JSONB DEFAULT '[]'
);

-- NOC alerts
CREATE TABLE IF NOT EXISTS network_alerts (
    id SERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    source VARCHAR(50) NOT NULL,
    title VARCHAR(300) NOT NULL,
    details JSONB DEFAULT '{}',
    auto_action_taken VARCHAR(200),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON network_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON network_alerts(created_at);

-- Cached Nagios check results
CREATE TABLE IF NOT EXISTS nagios_check_results (
    id SERIAL PRIMARY KEY,
    host_name VARCHAR(200) NOT NULL,
    service_description VARCHAR(200) DEFAULT '',
    status VARCHAR(20) NOT NULL,
    output TEXT,
    performance_data TEXT,
    last_check TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nagios_host_service ON nagios_check_results(host_name, COALESCE(service_description, ''));

COMMIT;
```

- [ ] **Step 2: Run the migration**

Run: `docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/060_security_noc_tables.sql`

Note: Copy the migration into the container first:
```bash
docker cp database/migrations/060_security_noc_tables.sql archie_database:/docker-entrypoint-initdb.d/
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/060_security_noc_tables.sql
```

Expected: `CREATE TABLE` x6, `CREATE INDEX` x6

- [ ] **Step 3: Verify tables exist**

Run: `docker exec archie_database psql -U archie -d archie -c "\dt network_*" && docker exec archie_database psql -U archie -d archie -c "\dt nagios_*"`

Expected: 7 new tables listed (network_device_users, network_traffic_stats, network_dns_stats, network_daily_reports, network_ip_history, network_alerts + existing network_devices, and nagios_check_results)

- [ ] **Step 4: Commit**

```bash
git add database/migrations/060_security_noc_tables.sql
git commit -m "feat(security): add NOC database tables — traffic, DNS, alerts, reports, DDNS, Nagios"
```

---

### Task 2: Fix ntopng — Docker Compose with Redis

**Files:**
- Create: `network-tools/docker-compose.yml`

- [ ] **Step 1: Create network-tools docker-compose**

```yaml
# network-tools/docker-compose.yml
# Network monitoring stack: ntopng + Redis
# ntopng uses host networking to capture all traffic on eth0

version: "3.8"

services:
  network_redis:
    image: redis:7-alpine
    container_name: network_redis
    restart: unless-stopped
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - network_redis_data:/data
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.5"
    read_only: true
    tmpfs:
      - /tmp

  network_ntopng:
    image: ntop/ntopng:v6-pinned
    container_name: network_ntopng
    restart: unless-stopped
    network_mode: host
    command: --redis 127.0.0.1:6379 -i eth0 -w 3001 --community
    volumes:
      - network_ntopng_data:/var/lib/ntopng
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "2.0"
    depends_on:
      - network_redis

volumes:
  network_redis_data:
  network_ntopng_data:
```

- [ ] **Step 2: Stop and remove old ntopng container**

```bash
docker stop network_ntopng 2>/dev/null
docker rm network_ntopng 2>/dev/null
```

- [ ] **Step 3: Start the network-tools stack**

Run: `cd /mnt/archie_brain/network-tools && docker compose up -d`

Expected: Both `network_redis` and `network_ntopng` start. ntopng should NOT crash-loop since Redis is now available.

- [ ] **Step 4: Verify ntopng is healthy**

Run: `sleep 10 && docker logs network_ntopng --tail 10`

Expected: No Redis connection errors. Should see `Listening on port 3001` or similar startup confirmation.

- [ ] **Step 5: Verify ntopng web UI**

Run: `curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3001/`

Expected: `200` or `302` (redirect to login)

- [ ] **Step 6: Commit**

```bash
git add network-tools/docker-compose.yml
git commit -m "feat(infra): add network-tools docker-compose — ntopng + Redis for traffic monitoring"
```

---

### Task 3: fail2ban Service — Management Endpoints

**Files:**
- Create: `platform_v2/tools/security_network/fail2ban_service.py`
- Create: `tests/test_security_network/test_fail2ban_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security_network/test_fail2ban_service.py
"""Tests for fail2ban service — CLI wrapper for jail management."""
import pytest
from unittest.mock import patch, MagicMock


class TestFail2banService:
    """Test fail2ban CLI wrapper methods."""

    @patch("subprocess.run")
    def test_get_jails_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Status\n|- Number of jail:\t3\n`- Jail list:\tsshd, nginx-http-auth, recidive\n",
        )
        from platform_v2.tools.security_network.fail2ban_service import Fail2banService
        svc = Fail2banService()
        jails = svc.get_jails()
        assert jails == ["sshd", "nginx-http-auth", "recidive"]

    @patch("subprocess.run")
    def test_get_jail_status_parses_banned(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "Status for the jail: sshd\n"
                "|- Filter\n"
                "|  |- Currently failed:\t5\n"
                "|  |- Total failed:\t120\n"
                "|  `- File list:\t/var/log/auth.log\n"
                "`- Actions\n"
                "   |- Currently banned:\t2\n"
                "   |- Total banned:\t15\n"
                "   `- Banned IP list:\t192.168.1.50 10.0.0.5\n"
            ),
        )
        from platform_v2.tools.security_network.fail2ban_service import Fail2banService
        svc = Fail2banService()
        status = svc.get_jail_status("sshd")
        assert status["currently_banned"] == 2
        assert status["total_banned"] == 15
        assert "192.168.1.50" in status["banned_ips"]
        assert status["currently_failed"] == 5

    @patch("subprocess.run")
    def test_ban_ip_calls_correct_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
        from platform_v2.tools.security_network.fail2ban_service import Fail2banService
        svc = Fail2banService()
        result = svc.ban_ip("sshd", "10.0.0.99")
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "fail2ban-client" in cmd
        assert "banip" in cmd
        assert "10.0.0.99" in cmd

    @patch("subprocess.run")
    def test_unban_ip_calls_correct_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
        from platform_v2.tools.security_network.fail2ban_service import Fail2banService
        svc = Fail2banService()
        result = svc.unban_ip("sshd", "10.0.0.99")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "unbanip" in cmd

    def test_validate_ip_rejects_invalid(self):
        from platform_v2.tools.security_network.fail2ban_service import Fail2banService
        svc = Fail2banService()
        assert svc._validate_ip("192.168.1.1") is True
        assert svc._validate_ip("not-an-ip") is False
        assert svc._validate_ip("'; DROP TABLE users; --") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_fail2ban_service.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'platform_v2.tools.security_network.fail2ban_service'`

- [ ] **Step 3: Write the fail2ban service**

```python
# platform_v2/tools/security_network/fail2ban_service.py
"""fail2ban CLI wrapper for jail management.

Provides read/write access to fail2ban jails via subprocess calls
to fail2ban-client. All commands are validated to prevent injection.
"""
import ipaddress
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

FAIL2BAN_CMD = "fail2ban-client"
TIMEOUT_SECONDS = 10


class Fail2banService:
    """Wraps fail2ban-client CLI for jail management."""

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run a fail2ban-client command safely."""
        cmd = ["sudo", FAIL2BAN_CMD] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )

    def _validate_ip(self, ip: str) -> bool:
        """Validate an IP address to prevent command injection."""
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def _validate_jail_name(self, name: str) -> bool:
        """Validate jail name — alphanumeric + hyphens only."""
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

    def get_status(self) -> dict:
        """Get overall fail2ban status."""
        try:
            result = self._run(["status"])
            if result.returncode != 0:
                return {"error": result.stderr.strip(), "running": False}
            return {"running": True, "raw": result.stdout.strip()}
        except FileNotFoundError:
            return {"error": "fail2ban-client not found", "running": False}
        except subprocess.TimeoutExpired:
            return {"error": "fail2ban-client timed out", "running": False}

    def get_jails(self) -> list[str]:
        """List all configured jail names."""
        try:
            result = self._run(["status"])
            if result.returncode != 0:
                return []
            for line in result.stdout.splitlines():
                if "Jail list:" in line:
                    jails_str = line.split("Jail list:")[1].strip()
                    return [j.strip() for j in jails_str.split(",") if j.strip()]
            return []
        except Exception as e:
            logger.error(f"Failed to get jails: {e}")
            return []

    def get_jail_status(self, jail_name: str) -> dict:
        """Get detailed status for a specific jail."""
        if not self._validate_jail_name(jail_name):
            return {"error": "Invalid jail name"}
        try:
            result = self._run(["status", jail_name])
            if result.returncode != 0:
                return {"error": result.stderr.strip()}

            output = result.stdout
            status = {
                "jail": jail_name,
                "currently_failed": 0,
                "total_failed": 0,
                "currently_banned": 0,
                "total_banned": 0,
                "banned_ips": [],
            }

            for line in output.splitlines():
                line = line.strip()
                if "Currently failed:" in line:
                    status["currently_failed"] = int(line.split(":")[-1].strip())
                elif "Total failed:" in line:
                    status["total_failed"] = int(line.split(":")[-1].strip())
                elif "Currently banned:" in line:
                    status["currently_banned"] = int(line.split(":")[-1].strip())
                elif "Total banned:" in line:
                    status["total_banned"] = int(line.split(":")[-1].strip())
                elif "Banned IP list:" in line:
                    ips_str = line.split(":")[-1].strip()
                    status["banned_ips"] = [ip.strip() for ip in ips_str.split() if ip.strip()]

            return status
        except Exception as e:
            logger.error(f"Failed to get jail status for {jail_name}: {e}")
            return {"error": str(e)}

    def ban_ip(self, jail_name: str, ip: str) -> bool:
        """Ban an IP in a specific jail."""
        if not self._validate_jail_name(jail_name):
            raise ValueError(f"Invalid jail name: {jail_name}")
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        try:
            result = self._run(["set", jail_name, "banip", ip])
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to ban {ip} in {jail_name}: {e}")
            return False

    def unban_ip(self, jail_name: str, ip: str) -> bool:
        """Unban an IP from a specific jail."""
        if not self._validate_jail_name(jail_name):
            raise ValueError(f"Invalid jail name: {jail_name}")
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        try:
            result = self._run(["set", jail_name, "unbanip", ip])
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to unban {ip} from {jail_name}: {e}")
            return False

    def get_all_jail_statuses(self) -> list[dict]:
        """Get status for all jails at once."""
        jails = self.get_jails()
        return [self.get_jail_status(j) for j in jails]
```

- [ ] **Step 4: Create tests directory init**

```bash
mkdir -p tests/test_security_network
touch tests/test_security_network/__init__.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_fail2ban_service.py -v`

Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/security_network/fail2ban_service.py tests/test_security_network/
git commit -m "feat(security): add fail2ban service — list jails, ban/unban IPs, jail status"
```

---

### Task 4: DDNS Service — IP History & Management

**Files:**
- Create: `platform_v2/tools/security_network/ddns_service.py`
- Create: `tests/test_security_network/test_ddns_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security_network/test_ddns_service.py
"""Tests for DDNS service — IP tracking, history, manual trigger."""
import pytest
from unittest.mock import patch, MagicMock


class TestDdnsService:
    """Test DDNS management methods."""

    @patch("builtins.open", create=True)
    def test_get_current_ip_reads_file(self, mock_open):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value="142.169.21.199\n")
        from platform_v2.tools.security_network.ddns_service import DdnsService
        svc = DdnsService()
        ip = svc.get_current_public_ip()
        assert ip == "142.169.21.199"

    @patch("subprocess.run")
    def test_trigger_update_runs_script(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="IP updated\n")
        from platform_v2.tools.security_network.ddns_service import DdnsService
        svc = DdnsService()
        result = svc.trigger_update()
        assert result["success"] is True
        cmd = mock_run.call_args[0][0]
        assert "ddns_updater.sh" in " ".join(cmd)

    def test_get_ip_history_returns_list(self):
        from platform_v2.tools.security_network.ddns_service import DdnsService
        svc = DdnsService()
        with patch.object(svc, "_query_db") as mock_db:
            mock_db.return_value = [
                {"old_ip": "1.1.1.1", "new_ip": "2.2.2.2", "changed_at": "2026-03-30"},
            ]
            history = svc.get_ip_history(limit=10)
            assert len(history) == 1
            assert history[0]["new_ip"] == "2.2.2.2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_ddns_service.py -v`

Expected: FAIL — module not found

- [ ] **Step 3: Write the DDNS service**

```python
# platform_v2/tools/security_network/ddns_service.py
"""DDNS management service — IP tracking, history, manual updates.

Wraps the existing ddns_updater.sh script and provides IP change
history via the network_ip_history table.
"""
import logging
import os
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

DDNS_SCRIPT = "/mnt/archie_brain/scripts/ddns_updater.sh"
DDNS_LAST_IP_FILE = "/mnt/archie_brain/scripts/.ddns_last_ip"
TIMEOUT_SECONDS = 30


class DdnsService:
    """Manages DDNS updates and IP change tracking."""

    def get_current_public_ip(self) -> str | None:
        """Read the last known public IP from the DDNS script's state file."""
        try:
            with open(DDNS_LAST_IP_FILE) as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.warning(f"DDNS last IP file not found: {DDNS_LAST_IP_FILE}")
            return None

    def get_live_public_ip(self) -> str | None:
        """Fetch the current public IP from an external service."""
        try:
            result = subprocess.run(
                ["curl", "-s", "https://api.ipify.org"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.error(f"Failed to fetch public IP: {e}")
            return None

    def trigger_update(self) -> dict:
        """Manually trigger a DDNS update."""
        if not os.path.exists(DDNS_SCRIPT):
            return {"success": False, "error": f"Script not found: {DDNS_SCRIPT}"}
        try:
            result = subprocess.run(
                ["bash", DDNS_SCRIPT],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "DDNS update timed out"}

    def get_status(self) -> dict:
        """Get DDNS overall status."""
        stored_ip = self.get_current_public_ip()
        last_modified = None
        if os.path.exists(DDNS_LAST_IP_FILE):
            mtime = os.path.getmtime(DDNS_LAST_IP_FILE)
            last_modified = datetime.fromtimestamp(mtime).isoformat()
        return {
            "stored_ip": stored_ip,
            "last_updated": last_modified,
            "script_exists": os.path.exists(DDNS_SCRIPT),
        }

    def _query_db(self, query: str, params: tuple = ()) -> list[dict]:
        """Query the database for IP history."""
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_ip_history(self, limit: int = 50) -> list[dict]:
        """Get IP change history from network_ip_history table."""
        return self._query_db(
            "SELECT * FROM network_ip_history ORDER BY changed_at DESC LIMIT %s",
            (limit,),
        )

    def record_ip_change(self, old_ip: str, new_ip: str, dns_updated: bool = False) -> int:
        """Record an IP change in the history table."""
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO network_ip_history (old_ip, new_ip, dns_updated)
                   VALUES (%s, %s, %s) RETURNING id""",
                (old_ip, new_ip, dns_updated),
            )
            return cur.fetchone()[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_ddns_service.py -v`

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/ddns_service.py tests/test_security_network/test_ddns_service.py
git commit -m "feat(security): add DDNS service — IP history, manual trigger, status"
```

---

### Task 5: ntopng Service — REST API Client

**Files:**
- Create: `platform_v2/tools/security_network/ntopng_service.py`
- Create: `tests/test_security_network/test_ntopng_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security_network/test_ntopng_service.py
"""Tests for ntopng REST API client."""
import pytest
from unittest.mock import patch, MagicMock
import json


class TestNtopngService:
    """Test ntopng API wrapper methods."""

    @patch("requests.get")
    def test_get_interfaces(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rc": 0, "rsp": [{"ifid": 0, "ifname": "eth0"}]},
        )
        from platform_v2.tools.security_network.ntopng_service import NtopngService
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        interfaces = svc.get_interfaces()
        assert len(interfaces) == 1
        assert interfaces[0]["ifname"] == "eth0"

    @patch("requests.get")
    def test_get_hosts_returns_host_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rc": 0, "rsp": [
                {"ip": "192.168.1.100", "mac": "AA:BB:CC:DD:EE:FF", "bytes.sent": 1000, "bytes.rcvd": 2000, "name": "laptop"},
            ]},
        )
        from platform_v2.tools.security_network.ntopng_service import NtopngService
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        hosts = svc.get_hosts()
        assert len(hosts) == 1
        assert hosts[0]["ip"] == "192.168.1.100"

    @patch("requests.get")
    def test_get_interface_stats(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rc": 0, "rsp": {
                "bytes": 50000, "packets": 300, "speed": 1000,
            }},
        )
        from platform_v2.tools.security_network.ntopng_service import NtopngService
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        stats = svc.get_interface_stats(ifid=0)
        assert stats["bytes"] == 50000

    @patch("requests.get")
    def test_connection_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        from platform_v2.tools.security_network.ntopng_service import NtopngService
        svc = NtopngService(host="127.0.0.1", port=3001, user="admin", password="test")
        hosts = svc.get_hosts()
        assert hosts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_ntopng_service.py -v`

Expected: FAIL — module not found

- [ ] **Step 3: Write the ntopng service**

```python
# platform_v2/tools/security_network/ntopng_service.py
"""ntopng REST API client — bandwidth, flows, hosts, protocol data.

Connects to ntopng's REST API v2 to pull traffic intelligence.
Docs: https://www.ntop.org/guides/ntopng/api/
"""
import logging
import os
import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("NTOPNG_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("NTOPNG_PORT", "3001"))
DEFAULT_USER = os.getenv("NTOPNG_USER", "admin")
DEFAULT_PASS = os.getenv("NTOPNG_ADMIN_PASSWORD", "")
TIMEOUT = 10


class NtopngService:
    """REST API client for ntopng traffic monitoring."""

    def __init__(self, host=None, port=None, user=None, password=None):
        self.host = host or DEFAULT_HOST
        self.port = port or DEFAULT_PORT
        self.user = user or DEFAULT_USER
        self.password = password or DEFAULT_PASS
        self.base_url = f"http://{self.host}:{self.port}"
        self.session = requests.Session()
        self.session.auth = (self.user, self.password)

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to ntopng API."""
        try:
            url = f"{self.base_url}{endpoint}"
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"ntopng API error: {endpoint} — {e}")
            return {"rc": -1, "rsp": {}}

    def is_healthy(self) -> bool:
        """Check if ntopng is reachable."""
        try:
            resp = self.session.get(f"{self.base_url}/lua/rest/v2/get/ntopng/interfaces.lua", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def get_interfaces(self) -> list[dict]:
        """Get list of monitored network interfaces."""
        data = self._get("/lua/rest/v2/get/ntopng/interfaces.lua")
        return data.get("rsp", [])

    def get_hosts(self, ifid: int = 0) -> list[dict]:
        """Get all active hosts on an interface."""
        data = self._get("/lua/rest/v2/get/host/active.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_host_details(self, host_ip: str, ifid: int = 0) -> dict:
        """Get detailed info for a specific host."""
        data = self._get("/lua/rest/v2/get/host/data.lua", {"ifid": ifid, "host": host_ip})
        return data.get("rsp", {})

    def get_interface_stats(self, ifid: int = 0) -> dict:
        """Get traffic statistics for an interface."""
        data = self._get("/lua/rest/v2/get/interface/data.lua", {"ifid": ifid})
        return data.get("rsp", {})

    def get_top_talkers(self, ifid: int = 0) -> list[dict]:
        """Get top bandwidth consumers."""
        data = self._get("/lua/rest/v2/get/host/top.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_flows(self, ifid: int = 0) -> list[dict]:
        """Get active network flows."""
        data = self._get("/lua/rest/v2/get/flow/active.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_l7_stats(self, ifid: int = 0) -> dict:
        """Get Layer 7 protocol statistics (YouTube, Netflix, etc.)."""
        data = self._get("/lua/rest/v2/get/interface/l7/stats.lua", {"ifid": ifid})
        return data.get("rsp", {})

    def get_host_traffic_history(self, host_ip: str, ifid: int = 0) -> list[dict]:
        """Get historical traffic data for a specific host."""
        data = self._get("/lua/rest/v2/get/host/ts.lua", {"ifid": ifid, "host": host_ip})
        return data.get("rsp", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_ntopng_service.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/ntopng_service.py tests/test_security_network/test_ntopng_service.py
git commit -m "feat(security): add ntopng REST API client — bandwidth, flows, hosts, protocols"
```

---

### Task 6: Nagios Service — CGI API Client

**Files:**
- Create: `platform_v2/tools/security_network/nagios_service.py`
- Create: `tests/test_security_network/test_nagios_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security_network/test_nagios_service.py
"""Tests for Nagios CGI API client."""
import pytest
from unittest.mock import patch, MagicMock


class TestNagiosService:
    """Test Nagios API wrapper methods."""

    @patch("requests.get")
    def test_get_host_status(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"hostlist": {
                "archie": {"status": 2, "plugin_output": "PING OK", "last_check": 1711900000},
            }}},
        )
        from platform_v2.tools.security_network.nagios_service import NagiosService
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        hosts = svc.get_host_status()
        assert "archie" in hosts
        assert hosts["archie"]["plugin_output"] == "PING OK"

    @patch("requests.get")
    def test_get_service_status(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"servicelist": {
                "archie": {
                    "SSH": {"status": 2, "plugin_output": "SSH OK"},
                    "HTTP": {"status": 2, "plugin_output": "HTTP OK"},
                },
            }}},
        )
        from platform_v2.tools.security_network.nagios_service import NagiosService
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        services = svc.get_service_status()
        assert "archie" in services
        assert "SSH" in services["archie"]

    @patch("requests.get")
    def test_is_healthy_returns_true(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        from platform_v2.tools.security_network.nagios_service import NagiosService
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        assert svc.is_healthy() is True

    @patch("requests.get")
    def test_connection_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        from platform_v2.tools.security_network.nagios_service import NagiosService
        svc = NagiosService(host="192.168.1.200", port=8082, user="admin", password="test")
        hosts = svc.get_host_status()
        assert hosts == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_nagios_service.py -v`

Expected: FAIL — module not found

- [ ] **Step 3: Write the Nagios service**

```python
# platform_v2/tools/security_network/nagios_service.py
"""Nagios CGI API client — host/service status, check results.

Connects to Nagios CGI JSON endpoints to pull monitoring data.
Uses statusjson.cgi for host and service status.
"""
import logging
import os
import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("NAGIOS_HOST", "192.168.1.200")
DEFAULT_PORT = int(os.getenv("NAGIOS_PORT", "8082"))
DEFAULT_USER = os.getenv("NAGIOS_USER", "nagiosadmin")
DEFAULT_PASS = os.getenv("NAGIOS_PASS", "")
TIMEOUT = 10


class NagiosService:
    """REST client for Nagios CGI API."""

    def __init__(self, host=None, port=None, user=None, password=None):
        self.host = host or DEFAULT_HOST
        self.port = port or DEFAULT_PORT
        self.user = user or DEFAULT_USER
        self.password = password or DEFAULT_PASS
        self.base_url = f"http://{self.host}:{self.port}/nagios/cgi-bin"
        self.session = requests.Session()
        self.session.auth = (self.user, self.password)

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to Nagios CGI API."""
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Nagios API error: {endpoint} — {e}")
            return {}

    def is_healthy(self) -> bool:
        """Check if Nagios is reachable."""
        try:
            resp = self.session.get(
                f"http://{self.host}:{self.port}/nagios/",
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_host_status(self) -> dict:
        """Get status of all monitored hosts."""
        data = self._get("statusjson.cgi", {"query": "hostlist", "details": "true"})
        return data.get("data", {}).get("hostlist", {})

    def get_service_status(self, host: str = None) -> dict:
        """Get status of all monitored services, optionally filtered by host."""
        params = {"query": "servicelist", "details": "true"}
        if host:
            params["hostname"] = host
        data = self._get("statusjson.cgi", params)
        return data.get("data", {}).get("servicelist", {})

    def get_host_count(self) -> dict:
        """Get count of hosts by status."""
        data = self._get("statusjson.cgi", {"query": "hostcount"})
        return data.get("data", {})

    def get_service_count(self) -> dict:
        """Get count of services by status."""
        data = self._get("statusjson.cgi", {"query": "servicecount"})
        return data.get("data", {})

    def get_problems(self) -> dict:
        """Get all hosts and services in non-OK state."""
        hosts = self.get_host_status()
        services = self.get_service_status()
        problems = {"hosts": {}, "services": {}}
        for name, info in hosts.items():
            if info.get("status", 0) != 2:  # 2 = UP
                problems["hosts"][name] = info
        for host, svcs in services.items():
            for svc_name, svc_info in svcs.items():
                if svc_info.get("status", 0) != 2:  # 2 = OK
                    if host not in problems["services"]:
                        problems["services"][host] = {}
                    problems["services"][host][svc_name] = svc_info
        return problems

    def get_all_for_cache(self) -> list[dict]:
        """Get all host/service data for caching in nagios_check_results table."""
        results = []
        hosts = self.get_host_status()
        for name, info in hosts.items():
            results.append({
                "host_name": name,
                "service_description": "",
                "status": self._status_text(info.get("status", 0), is_host=True),
                "output": info.get("plugin_output", ""),
                "performance_data": info.get("performance_data", ""),
                "last_check": info.get("last_check", 0),
            })
        services = self.get_service_status()
        for host, svcs in services.items():
            for svc_name, svc_info in svcs.items():
                results.append({
                    "host_name": host,
                    "service_description": svc_name,
                    "status": self._status_text(svc_info.get("status", 0), is_host=False),
                    "output": svc_info.get("plugin_output", ""),
                    "performance_data": svc_info.get("performance_data", ""),
                    "last_check": svc_info.get("last_check", 0),
                })
        return results

    @staticmethod
    def _status_text(code: int, is_host: bool) -> str:
        """Convert numeric status to text."""
        if is_host:
            return {1: "PENDING", 2: "UP", 4: "DOWN", 8: "UNREACHABLE"}.get(code, "UNKNOWN")
        return {1: "PENDING", 2: "OK", 4: "WARNING", 8: "UNKNOWN", 16: "CRITICAL"}.get(code, "UNKNOWN")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain && python -m pytest tests/test_security_network/test_nagios_service.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/nagios_service.py tests/test_security_network/test_nagios_service.py
git commit -m "feat(security): add Nagios CGI API client — host/service status, problems, cache sync"
```

---

### Task 7: Defense Routes — fail2ban + DDNS Endpoints

**Files:**
- Create: `platform_v2/tools/security_network/defense_routes.py`
- Modify: `platform_v2/tools/security_network/__init__.py`

- [ ] **Step 1: Write defense routes**

```python
# platform_v2/tools/security_network/defense_routes.py
"""Defense tab routes — fail2ban jail management + DDNS management.

Registered via register_defense_routes(bp, admin_required) in __init__.py.
"""
import logging
from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_defense_routes(bp, admin_required):
    """Register all defense-related routes on the blueprint."""

    # ── fail2ban ──

    @bp.route("/api/fail2ban/status")
    @admin_required
    def fail2ban_status():
        from .fail2ban_service import Fail2banService
        svc = Fail2banService()
        return jsonify({"success": True, "data": svc.get_status()})

    @bp.route("/api/fail2ban/jails")
    @admin_required
    def fail2ban_jails():
        from .fail2ban_service import Fail2banService
        svc = Fail2banService()
        return jsonify({"success": True, "jails": svc.get_all_jail_statuses()})

    @bp.route("/api/fail2ban/jail/<jail_name>")
    @admin_required
    def fail2ban_jail_detail(jail_name):
        from .fail2ban_service import Fail2banService
        svc = Fail2banService()
        status = svc.get_jail_status(jail_name)
        if "error" in status:
            return jsonify({"success": False, "error": status["error"]}), 400
        return jsonify({"success": True, "data": status})

    @bp.route("/api/fail2ban/ban", methods=["POST"])
    @admin_required
    def fail2ban_ban():
        data = request.get_json()
        jail = data.get("jail")
        ip = data.get("ip")
        if not jail or not ip:
            return jsonify({"success": False, "error": "jail and ip required"}), 400
        from .fail2ban_service import Fail2banService
        svc = Fail2banService()
        try:
            result = svc.ban_ip(jail, ip)
            return jsonify({"success": result})
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @bp.route("/api/fail2ban/unban", methods=["POST"])
    @admin_required
    def fail2ban_unban():
        data = request.get_json()
        jail = data.get("jail")
        ip = data.get("ip")
        if not jail or not ip:
            return jsonify({"success": False, "error": "jail and ip required"}), 400
        from .fail2ban_service import Fail2banService
        svc = Fail2banService()
        try:
            result = svc.unban_ip(jail, ip)
            return jsonify({"success": result})
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400

    # ── DDNS ──

    @bp.route("/api/ddns/status")
    @admin_required
    def ddns_status():
        from .ddns_service import DdnsService
        svc = DdnsService()
        status = svc.get_status()
        status["live_ip"] = svc.get_live_public_ip()
        status["ip_changed"] = status["stored_ip"] != status["live_ip"]
        return jsonify({"success": True, "data": status})

    @bp.route("/api/ddns/history")
    @admin_required
    def ddns_history():
        from .ddns_service import DdnsService
        svc = DdnsService()
        limit = request.args.get("limit", 50, type=int)
        return jsonify({"success": True, "history": svc.get_ip_history(limit)})

    @bp.route("/api/ddns/update", methods=["POST"])
    @admin_required
    def ddns_trigger_update():
        from .ddns_service import DdnsService
        svc = DdnsService()
        result = svc.trigger_update()
        return jsonify(result)
```

- [ ] **Step 2: Register routes in __init__.py**

Read `platform_v2/tools/security_network/__init__.py` and add the import. The file currently has:

```python
security_network_bp = Blueprint("security_network", __name__, url_prefix="/tools/security-network")
from . import routes  # noqa: E402
```

Add after the existing imports:

```python
from .defense_routes import register_defense_routes
from .compliance_routes import register_compliance_routes  # already exists if not imported

# Register route modules
def _register_routes():
    from rbac import admin_required
    register_defense_routes(security_network_bp, admin_required)

_register_routes()
```

Note: Read the actual `__init__.py` first to see the exact current pattern, then add the defense_routes registration following the same pattern. The compliance_routes and badge_routes may already be registered — follow their pattern.

- [ ] **Step 3: Deploy and test**

Run: `docker compose restart archie_platform && sleep 5`

Test endpoints:
```bash
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/fail2ban/status | python3 -m json.tool
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/ddns/status | python3 -m json.tool
```

Expected: JSON responses with fail2ban and DDNS status data

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/defense_routes.py platform_v2/tools/security_network/__init__.py
git commit -m "feat(security): add defense routes — fail2ban jail management + DDNS management"
```

---

### Task 8: NOC Overview Routes — Hero Stats + Service Health

**Files:**
- Create: `platform_v2/tools/security_network/noc_routes.py`

- [ ] **Step 1: Write NOC overview routes**

```python
# platform_v2/tools/security_network/noc_routes.py
"""NOC Overview routes — hero stats, service health, alerts feed.

Aggregates data from all security data sources into a single
overview endpoint for the NOC command view.
"""
import logging
from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_noc_routes(bp, admin_required):
    """Register NOC overview routes on the blueprint."""

    @bp.route("/api/noc/overview")
    @admin_required
    def noc_overview():
        """Aggregated NOC command view data."""
        from .adguard_service import AdGuardService
        from .ntopng_service import NtopngService
        from .nagios_service import NagiosService
        from .fail2ban_service import Fail2banService
        from .ddns_service import DdnsService
        import os

        overview = {
            "services": {},
            "hero_stats": {},
            "recent_alerts": [],
        }

        # AdGuard
        try:
            ag = AdGuardService()
            ag_stats = ag.get_stats()
            overview["services"]["adguard"] = {
                "status": "online",
                "clients": ag_stats.get("num_dns_queries", 0),
                "blocked": ag_stats.get("num_blocked_filtering", 0),
            }
            overview["hero_stats"]["dns_queries_24h"] = ag_stats.get("num_dns_queries", 0)
            overview["hero_stats"]["threats_blocked_24h"] = ag_stats.get("num_blocked_filtering", 0)
        except Exception as e:
            overview["services"]["adguard"] = {"status": "error", "error": str(e)}

        # ntopng
        try:
            nt = NtopngService()
            healthy = nt.is_healthy()
            overview["services"]["ntopng"] = {"status": "online" if healthy else "offline"}
            if healthy:
                stats = nt.get_interface_stats()
                overview["hero_stats"]["traffic_bytes"] = stats.get("bytes", 0)
        except Exception as e:
            overview["services"]["ntopng"] = {"status": "error", "error": str(e)}

        # Nagios
        try:
            ng = NagiosService()
            healthy = ng.is_healthy()
            overview["services"]["nagios"] = {"status": "online" if healthy else "offline"}
            if healthy:
                counts = ng.get_host_count()
                overview["hero_stats"]["hosts_up"] = counts.get("up", 0)
                overview["hero_stats"]["hosts_down"] = counts.get("down", 0)
        except Exception as e:
            overview["services"]["nagios"] = {"status": "error", "error": str(e)}

        # fail2ban
        try:
            f2b = Fail2banService()
            status = f2b.get_status()
            overview["services"]["fail2ban"] = {
                "status": "online" if status.get("running") else "offline",
            }
            jails = f2b.get_all_jail_statuses()
            total_banned = sum(j.get("currently_banned", 0) for j in jails)
            overview["hero_stats"]["currently_banned"] = total_banned
        except Exception as e:
            overview["services"]["fail2ban"] = {"status": "error", "error": str(e)}

        # DDNS
        try:
            ddns = DdnsService()
            ddns_status = ddns.get_status()
            overview["services"]["ddns"] = {
                "status": "online" if ddns_status.get("stored_ip") else "offline",
                "ip": ddns_status.get("stored_ip"),
                "last_updated": ddns_status.get("last_updated"),
            }
        except Exception as e:
            overview["services"]["ddns"] = {"status": "error", "error": str(e)}

        # UFW
        try:
            import subprocess
            result = subprocess.run(
                ["sudo", "ufw", "status"],
                capture_output=True, text=True, timeout=5,
            )
            active = "Status: active" in result.stdout
            overview["services"]["ufw"] = {"status": "online" if active else "offline"}
        except Exception as e:
            overview["services"]["ufw"] = {"status": "error", "error": str(e)}

        # Recent alerts from DB
        try:
            from database import get_db_cursor
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, alert_type, severity, source, title, auto_action_taken,
                              created_at FROM network_alerts
                       ORDER BY created_at DESC LIMIT 20"""
                )
                cols = [d[0] for d in cur.description]
                overview["recent_alerts"] = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            pass

        # Network status determination
        service_statuses = [s.get("status") for s in overview["services"].values()]
        if all(s == "online" for s in service_statuses):
            overview["hero_stats"]["network_status"] = "SECURE"
        elif any(s == "error" for s in service_statuses):
            overview["hero_stats"]["network_status"] = "CRITICAL"
        else:
            overview["hero_stats"]["network_status"] = "WARNING"

        return jsonify({"success": True, "data": overview})

    @bp.route("/api/noc/top-consumers")
    @admin_required
    def noc_top_consumers():
        """Top bandwidth consumers from ntopng."""
        from .ntopng_service import NtopngService
        try:
            nt = NtopngService()
            talkers = nt.get_top_talkers()
            return jsonify({"success": True, "data": talkers})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Register in __init__.py**

Add to the `_register_routes()` function:

```python
from .noc_routes import register_noc_routes
register_noc_routes(security_network_bp, admin_required)
```

- [ ] **Step 3: Deploy and test**

Run: `docker compose restart archie_platform && sleep 5`

Test: `curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/noc/overview | python3 -m json.tool`

Expected: JSON with services status, hero stats, and recent alerts

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/noc_routes.py platform_v2/tools/security_network/__init__.py
git commit -m "feat(security): add NOC overview route — aggregated service health + hero stats"
```

---

### Task 9: Traffic + Device Routes

**Files:**
- Create: `platform_v2/tools/security_network/traffic_routes.py`
- Create: `platform_v2/tools/security_network/device_routes.py`

- [ ] **Step 1: Write traffic routes**

```python
# platform_v2/tools/security_network/traffic_routes.py
"""Traffic tab routes — bandwidth, flows, protocol data from ntopng.

Registered via register_traffic_routes(bp, admin_required) in __init__.py.
"""
import logging
from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_traffic_routes(bp, admin_required):
    """Register traffic monitoring routes."""

    @bp.route("/api/traffic/bandwidth")
    @admin_required
    def traffic_bandwidth():
        """Real-time bandwidth from ntopng."""
        from .ntopng_service import NtopngService
        svc = NtopngService()
        ifid = request.args.get("ifid", 0, type=int)
        stats = svc.get_interface_stats(ifid=ifid)
        return jsonify({"success": True, "data": stats})

    @bp.route("/api/traffic/hosts")
    @admin_required
    def traffic_hosts():
        """Active hosts with bandwidth data."""
        from .ntopng_service import NtopngService
        svc = NtopngService()
        ifid = request.args.get("ifid", 0, type=int)
        hosts = svc.get_hosts(ifid=ifid)
        return jsonify({"success": True, "data": hosts})

    @bp.route("/api/traffic/flows")
    @admin_required
    def traffic_flows():
        """Active network flows."""
        from .ntopng_service import NtopngService
        svc = NtopngService()
        ifid = request.args.get("ifid", 0, type=int)
        flows = svc.get_flows(ifid=ifid)
        return jsonify({"success": True, "data": flows})

    @bp.route("/api/traffic/protocols")
    @admin_required
    def traffic_protocols():
        """Layer 7 protocol breakdown."""
        from .ntopng_service import NtopngService
        svc = NtopngService()
        ifid = request.args.get("ifid", 0, type=int)
        l7 = svc.get_l7_stats(ifid=ifid)
        return jsonify({"success": True, "data": l7})

    @bp.route("/api/traffic/history")
    @admin_required
    def traffic_history():
        """Historical traffic stats from DB aggregates."""
        from database import get_db_cursor
        hours = request.args.get("hours", 24, type=int)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT device_mac, device_ip, SUM(bytes_in) as total_in,
                          SUM(bytes_out) as total_out, hour_bucket
                   FROM network_traffic_stats
                   WHERE hour_bucket >= NOW() - INTERVAL '%s hours'
                   GROUP BY device_mac, device_ip, hour_bucket
                   ORDER BY hour_bucket DESC""",
                (hours,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return jsonify({"success": True, "data": rows})
```

- [ ] **Step 2: Write device routes**

```python
# platform_v2/tools/security_network/device_routes.py
"""Devices tab routes — inventory, user mapping, unknown device alerts.

Registered via register_device_routes(bp, admin_required) in __init__.py.
"""
import logging
from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_device_routes(bp, admin_required):
    """Register device management routes."""

    @bp.route("/api/devices/users")
    @admin_required
    def device_user_mappings():
        """Get all device-to-user mappings."""
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT du.*, nd.ip_address, nd.hostname, nd.friendly_name, nd.last_seen_at
                   FROM network_device_users du
                   LEFT JOIN network_devices nd ON du.mac_address = nd.mac_address
                   ORDER BY du.user_name, du.device_label"""
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return jsonify({"success": True, "data": rows})

    @bp.route("/api/devices/users", methods=["POST"])
    @admin_required
    def assign_device_user():
        """Assign a device (MAC) to a user."""
        data = request.get_json()
        mac = data.get("mac_address")
        user_name = data.get("user_name")
        device_label = data.get("device_label", "")
        device_type = data.get("device_type", "unknown")
        if not mac or not user_name:
            return jsonify({"success": False, "error": "mac_address and user_name required"}), 400
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO network_device_users (mac_address, user_name, device_label, device_type)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (mac_address) DO UPDATE SET
                     user_name = EXCLUDED.user_name,
                     device_label = EXCLUDED.device_label,
                     device_type = EXCLUDED.device_type,
                     updated_at = NOW()
                   RETURNING id""",
                (mac, user_name, device_label, device_type),
            )
            row_id = cur.fetchone()[0]
        return jsonify({"success": True, "id": row_id})

    @bp.route("/api/devices/users/<int:mapping_id>", methods=["DELETE"])
    @admin_required
    def remove_device_user(mapping_id):
        """Remove a device-to-user mapping."""
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM network_device_users WHERE id = %s", (mapping_id,))
            if cur.rowcount == 0:
                return jsonify({"success": False, "error": "Mapping not found"}), 404
        return jsonify({"success": True})

    @bp.route("/api/devices/consumption")
    @admin_required
    def device_consumption():
        """Per-device consumption summary for the last N hours."""
        hours = request.args.get("hours", 24, type=int)
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT ts.device_mac, ts.device_ip,
                          COALESCE(du.user_name, 'Unknown') as user_name,
                          COALESCE(du.device_label, nd.friendly_name, nd.hostname, ts.device_ip) as device_name,
                          SUM(ts.bytes_in) as total_bytes_in,
                          SUM(ts.bytes_out) as total_bytes_out,
                          SUM(ts.bytes_in + ts.bytes_out) as total_bytes
                   FROM network_traffic_stats ts
                   LEFT JOIN network_device_users du ON ts.device_mac = du.mac_address
                   LEFT JOIN network_devices nd ON ts.device_mac = nd.mac_address
                   WHERE ts.hour_bucket >= NOW() - INTERVAL '%s hours'
                   GROUP BY ts.device_mac, ts.device_ip, du.user_name, du.device_label, nd.friendly_name, nd.hostname
                   ORDER BY total_bytes DESC""",
                (hours,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return jsonify({"success": True, "data": rows})

    @bp.route("/api/devices/consumption/by-user")
    @admin_required
    def user_consumption():
        """Per-user consumption summary (grouped devices)."""
        hours = request.args.get("hours", 24, type=int)
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT COALESCE(du.user_name, 'Unknown') as user_name,
                          COUNT(DISTINCT ts.device_mac) as device_count,
                          SUM(ts.bytes_in) as total_bytes_in,
                          SUM(ts.bytes_out) as total_bytes_out,
                          SUM(ts.bytes_in + ts.bytes_out) as total_bytes
                   FROM network_traffic_stats ts
                   LEFT JOIN network_device_users du ON ts.device_mac = du.mac_address
                   WHERE ts.hour_bucket >= NOW() - INTERVAL '%s hours'
                   GROUP BY du.user_name
                   ORDER BY total_bytes DESC""",
                (hours,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return jsonify({"success": True, "data": rows})
```

- [ ] **Step 3: Register both in __init__.py**

Add to `_register_routes()`:

```python
from .traffic_routes import register_traffic_routes
from .device_routes import register_device_routes
register_traffic_routes(security_network_bp, admin_required)
register_device_routes(security_network_bp, admin_required)
```

- [ ] **Step 4: Deploy and test**

Run: `docker compose restart archie_platform && sleep 5`

Test:
```bash
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/traffic/bandwidth | python3 -m json.tool
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/devices/users | python3 -m json.tool
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/traffic_routes.py platform_v2/tools/security_network/device_routes.py platform_v2/tools/security_network/__init__.py
git commit -m "feat(security): add traffic + device routes — bandwidth, flows, user mapping, consumption"
```

---

### Task 10: Report Routes + Service

**Files:**
- Create: `platform_v2/tools/security_network/report_service.py`
- Create: `platform_v2/tools/security_network/report_routes.py`

- [ ] **Step 1: Write report service**

```python
# platform_v2/tools/security_network/report_service.py
"""Report generation service — daily, weekly, threat reports.

Generates reports from aggregated traffic and DNS data,
stores in network_daily_reports, delivers via Telegram + email.
"""
import json
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


class ReportService:
    """Generates and delivers network consumption reports."""

    def generate_daily_device_report(self, report_date: date = None) -> dict:
        """Generate per-device daily consumption report."""
        if report_date is None:
            report_date = date.today() - timedelta(days=1)

        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            # Traffic data
            cur.execute(
                """SELECT ts.device_mac, ts.device_ip,
                          COALESCE(du.user_name, 'Unknown') as user_name,
                          COALESCE(du.device_label, nd.friendly_name, nd.hostname, ts.device_ip) as device_name,
                          SUM(ts.bytes_in) as bytes_in,
                          SUM(ts.bytes_out) as bytes_out
                   FROM network_traffic_stats ts
                   LEFT JOIN network_device_users du ON ts.device_mac = du.mac_address
                   LEFT JOIN network_devices nd ON ts.device_mac = nd.mac_address
                   WHERE ts.hour_bucket::date = %s
                   GROUP BY ts.device_mac, ts.device_ip, du.user_name, du.device_label, nd.friendly_name, nd.hostname
                   ORDER BY (SUM(ts.bytes_in) + SUM(ts.bytes_out)) DESC""",
                (report_date,),
            )
            traffic_cols = [d[0] for d in cur.description]
            traffic = [dict(zip(traffic_cols, r)) for r in cur.fetchall()]

            # DNS data
            cur.execute(
                """SELECT ds.client_ip,
                          SUM(ds.total_queries) as queries,
                          SUM(ds.blocked_queries) as blocked
                   FROM network_dns_stats ds
                   WHERE ds.hour_bucket::date = %s
                   GROUP BY ds.client_ip""",
                (report_date,),
            )
            dns_cols = [d[0] for d in cur.description]
            dns_map = {}
            for row in cur.fetchall():
                d = dict(zip(dns_cols, row))
                dns_map[d["client_ip"]] = d

        # Merge traffic + DNS
        devices = []
        for t in traffic:
            device = {
                **t,
                "total_bytes": (t.get("bytes_in") or 0) + (t.get("bytes_out") or 0),
                "dns_queries": dns_map.get(t["device_ip"], {}).get("queries", 0),
                "dns_blocked": dns_map.get(t["device_ip"], {}).get("blocked", 0),
            }
            devices.append(device)

        report = {
            "report_date": str(report_date),
            "report_type": "daily_device",
            "total_devices": len(devices),
            "total_bytes": sum(d["total_bytes"] for d in devices),
            "devices": devices,
        }

        # Store in DB
        self._store_report(report_date, "daily_device", report)
        return report

    def generate_daily_user_report(self, report_date: date = None) -> dict:
        """Generate per-user daily consumption report (grouped devices)."""
        if report_date is None:
            report_date = date.today() - timedelta(days=1)

        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT COALESCE(du.user_name, 'Unknown') as user_name,
                          COUNT(DISTINCT ts.device_mac) as device_count,
                          SUM(ts.bytes_in) as bytes_in,
                          SUM(ts.bytes_out) as bytes_out
                   FROM network_traffic_stats ts
                   LEFT JOIN network_device_users du ON ts.device_mac = du.mac_address
                   WHERE ts.hour_bucket::date = %s
                   GROUP BY du.user_name
                   ORDER BY (SUM(ts.bytes_in) + SUM(ts.bytes_out)) DESC""",
                (report_date,),
            )
            cols = [d[0] for d in cur.description]
            users = [dict(zip(cols, r)) for r in cur.fetchall()]

        for u in users:
            u["total_bytes"] = (u.get("bytes_in") or 0) + (u.get("bytes_out") or 0)

        report = {
            "report_date": str(report_date),
            "report_type": "daily_user",
            "total_users": len(users),
            "total_bytes": sum(u["total_bytes"] for u in users),
            "users": users,
        }

        self._store_report(report_date, "daily_user", report)
        return report

    def _store_report(self, report_date: date, report_type: str, data: dict) -> int:
        """Store a generated report in the database."""
        from database import get_db_cursor
        from psycopg2.extras import Json
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO network_daily_reports (report_date, report_type, data_json)
                   VALUES (%s, %s, %s) RETURNING id""",
                (report_date, report_type, Json(data)),
            )
            return cur.fetchone()[0]

    def get_reports(self, report_type: str = None, limit: int = 30) -> list[dict]:
        """List generated reports."""
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            if report_type:
                cur.execute(
                    """SELECT id, report_date, report_type, delivered_via, created_at
                       FROM network_daily_reports WHERE report_type = %s
                       ORDER BY report_date DESC LIMIT %s""",
                    (report_type, limit),
                )
            else:
                cur.execute(
                    """SELECT id, report_date, report_type, delivered_via, created_at
                       FROM network_daily_reports
                       ORDER BY report_date DESC LIMIT %s""",
                    (limit,),
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def get_report_detail(self, report_id: int) -> dict | None:
        """Get full report data by ID."""
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM network_daily_reports WHERE id = %s", (report_id,))
            if cur.rowcount == 0:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, cur.fetchone()))
```

- [ ] **Step 2: Write report routes**

```python
# platform_v2/tools/security_network/report_routes.py
"""Reports tab routes — daily, weekly, on-demand report generation.

Registered via register_report_routes(bp, admin_required) in __init__.py.
"""
import logging
from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_report_routes(bp, admin_required):
    """Register report routes."""

    @bp.route("/api/reports/list")
    @admin_required
    def report_list():
        from .report_service import ReportService
        svc = ReportService()
        report_type = request.args.get("type")
        limit = request.args.get("limit", 30, type=int)
        reports = svc.get_reports(report_type=report_type, limit=limit)
        return jsonify({"success": True, "data": reports})

    @bp.route("/api/reports/<int:report_id>")
    @admin_required
    def report_detail(report_id):
        from .report_service import ReportService
        svc = ReportService()
        report = svc.get_report_detail(report_id)
        if not report:
            return jsonify({"success": False, "error": "Report not found"}), 404
        return jsonify({"success": True, "data": report})

    @bp.route("/api/reports/generate", methods=["POST"])
    @admin_required
    def report_generate():
        """On-demand report generation."""
        from .report_service import ReportService
        from datetime import date, datetime
        svc = ReportService()
        data = request.get_json() or {}
        report_type = data.get("type", "daily_device")
        date_str = data.get("date")
        report_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()

        if report_type == "daily_device":
            report = svc.generate_daily_device_report(report_date)
        elif report_type == "daily_user":
            report = svc.generate_daily_user_report(report_date)
        else:
            return jsonify({"success": False, "error": f"Unknown report type: {report_type}"}), 400

        return jsonify({"success": True, "data": report})
```

- [ ] **Step 3: Register in __init__.py**

Add to `_register_routes()`:

```python
from .report_routes import register_report_routes
register_report_routes(security_network_bp, admin_required)
```

- [ ] **Step 4: Deploy and test**

Run: `docker compose restart archie_platform && sleep 5`

Test: `curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/reports/list | python3 -m json.tool`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/report_service.py platform_v2/tools/security_network/report_routes.py platform_v2/tools/security_network/__init__.py
git commit -m "feat(security): add report service + routes — daily device/user reports, on-demand generation"
```

---

## Phase 2 — Dashboard UI

### Task 11: Security Network Template — 8-Tab LCARS Layout

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html`
- Create: `platform_v2/static/css/security-network.css`
- Create: `platform_v2/static/js/security-network.js`

This is a large UI task. The implementation should:

- [ ] **Step 1: Read the existing template**

Read `platform_v2/templates/tools/security_network.html` to understand current structure, then read a reference module template (e.g., `templates/tools/department_hq.html`) for the LCARS tab pattern.

- [ ] **Step 2: Create the CSS file**

Create `platform_v2/static/css/security-network.css` with `sn-` prefixed classes following the LCARS design system. Include styles for:
- 8 tab buttons with color-coded accents matching the spec
- NOC hero stats cards (4 across)
- Service health panel (green/yellow/red indicators)
- Activity feed (scrollable list)
- Bandwidth bar charts
- Defense management panels
- Device inventory table with user mapping

Reference `platform_v2/static/css/department-hq.css` for the tab pattern.

- [ ] **Step 3: Create the JS file**

Create `platform_v2/static/js/security-network.js` with:
- `switchSecurityTab(tabName)` — tab switching with data loading
- `loadNocOverview()` — fetches `/api/noc/overview`, renders hero stats + service health + alerts
- `loadTrafficData()` — fetches bandwidth, hosts, protocols from traffic routes
- `loadDnsData()` — fetches AdGuard stats and renders query log
- `loadDevices()` — fetches device inventory + user mappings
- `loadDefense()` — fetches fail2ban jails + DDNS status
- `loadReports()` — fetches report list
- Auto-refresh: Overview tab polls every 30s, Traffic tab polls every 10s
- `api()` helper function (follow `consciousness.js` pattern)

- [ ] **Step 4: Rebuild the template**

Rewrite `security_network.html` with 8 tabs: Overview, Traffic, DNS, Devices, Defense, Scanners, Compliance, Reports. Each tab is a `<div id="sn-tab-{name}">` container. Include the CSS and JS files. Follow LCARS frame pattern from existing modules.

- [ ] **Step 5: Deploy and screenshot**

Run: `docker compose restart archie_platform`

Use Playwright MCP to screenshot:
1. Overview tab at 1920px
2. Each additional tab
3. Mobile breakpoints (480px, 768px)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/templates/tools/security_network.html platform_v2/static/css/security-network.css platform_v2/static/js/security-network.js
git commit -m "feat(security): rebuild Security Network UI — 8-tab LCARS NOC dashboard"
```

---

## Phase 3 — V.I.G.I.L. Agent Integration

### Task 12: Register Agent Loop Jobs in Autonomy Module

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Read agent_loop.py to find the job registration pattern**

Read the `start()` method to see how existing jobs are registered with APScheduler. Note the `with_app_context` wrapper, trigger types, and job naming convention.

- [ ] **Step 2: Add V.I.G.I.L. Security & Compliance jobs**

Add 8 new jobs in the `start()` method, following the existing pattern:

```python
# ── V.I.G.I.L. Security & Compliance Department Jobs ──

# Job: Network Health Monitor (every 60s)
self.scheduler.add_job(
    with_app_context(self._vigilil_network_health),
    trigger=IntervalTrigger(seconds=60),
    id="vigilil_network_health",
    name="V.I.G.I.L.: Network Health Monitor",
    replace_existing=True,
)

# Job: Traffic Aggregator (every 5 min)
self.scheduler.add_job(
    with_app_context(self._vigilil_traffic_aggregator),
    trigger=IntervalTrigger(minutes=5),
    id="vigilil_traffic_aggregator",
    name="V.I.G.I.L.: Traffic Aggregator",
    replace_existing=True,
)

# Job: Nagios Sync (every 2 min)
self.scheduler.add_job(
    with_app_context(self._vigilil_nagios_sync),
    trigger=IntervalTrigger(minutes=2),
    id="vigilil_nagios_sync",
    name="V.I.G.I.L.: Nagios Sync",
    replace_existing=True,
)

# Job: Device Watcher (every 5 min)
self.scheduler.add_job(
    with_app_context(self._vigilil_device_watcher),
    trigger=IntervalTrigger(minutes=5),
    id="vigilil_device_watcher",
    name="V.I.G.I.L.: Device Watcher",
    replace_existing=True,
)

# Job: DNS Anomaly Detector (every 5 min)
self.scheduler.add_job(
    with_app_context(self._vigilil_dns_anomaly),
    trigger=IntervalTrigger(minutes=5),
    id="vigilil_dns_anomaly",
    name="V.I.G.I.L.: DNS Anomaly Detector",
    replace_existing=True,
)

# Job: Log Health Monitor (every 15 min)
self.scheduler.add_job(
    with_app_context(self._vigilil_log_health),
    trigger=IntervalTrigger(minutes=15),
    id="vigilil_log_health",
    name="V.I.G.I.L.: Log Health Monitor",
    replace_existing=True,
)

# Job: Bandwidth Reporter (daily at 06:00)
self.scheduler.add_job(
    with_app_context(self._vigilil_daily_report),
    trigger=CronTrigger(hour=6, minute=0),
    id="vigilil_daily_report",
    name="V.I.G.I.L.: Daily Bandwidth Reporter",
    replace_existing=True,
)

# Job: Threat Responder (every 30s)
self.scheduler.add_job(
    with_app_context(self._vigilil_threat_responder),
    trigger=IntervalTrigger(seconds=30),
    id="vigilil_threat_responder",
    name="V.I.G.I.L.: Threat Responder",
    replace_existing=True,
)
```

- [ ] **Step 3: Implement job handler methods**

Add the handler methods to the AgentLoop class. Each method should:
1. Import the relevant service
2. Perform its check/collection
3. Write alerts to `network_alerts` table if issues found
4. Log actions to `governance_audit_log`

Implementation details for each handler:

**`_vigilil_network_health`**: Check AdGuard, ntopng, Nagios, fail2ban, DDNS health. Write alert if any service is down. Attempt auto-restart for Docker containers.

**`_vigilil_traffic_aggregator`**: Call ntopng `get_hosts()` and AdGuard stats. Write hourly aggregates to `network_traffic_stats` and `network_dns_stats`.

**`_vigilil_nagios_sync`**: Call Nagios `get_all_for_cache()`. Upsert into `nagios_check_results`.

**`_vigilil_device_watcher`**: Compare current ntopng hosts + AdGuard clients against `network_devices`. Insert new devices. Alert on unknown.

**`_vigilil_dns_anomaly`**: Check AdGuard query log for high-entropy domains (DNS tunneling indicator), tracking domain spikes, unusual query volumes.

**`_vigilil_log_health`**: Check `/var/log/syslog`, `auth.log`, `kern.log` file sizes. Alert if any > 500MB.

**`_vigilil_daily_report`**: Call ReportService to generate daily device + user reports. Send summary via Telegram + email.

**`_vigilil_threat_responder`**: Check fail2ban for new bans, AdGuard for malware queries, Nagios for critical alerts. Auto-block high severity. Write to `network_alerts`.

Note: Each handler method is 30-60 lines. Write them one at a time, deploy, verify in the Autonomy module job list.

- [ ] **Step 4: Deploy and verify jobs appear**

Run: `docker compose restart archie_platform && sleep 10`

Verify: Check the Autonomy module UI or call `mcp__archie__get_quick_summary` to confirm 8 new jobs are registered.

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(autonomy): register 8 V.I.G.I.L. agent loop jobs — network health, traffic, threats, reports"
```

---

### Task 13: Environment Variables + Credentials

**Files:**
- Modify: `platform_v2/.env`
- Modify: `.env`

- [ ] **Step 1: Add new env vars to both .env files**

Add to both `.env` and `platform_v2/.env`:

```bash
# Nagios monitoring
NAGIOS_HOST=192.168.1.200
NAGIOS_PORT=8082
NAGIOS_USER=nagiosadmin
NAGIOS_PASS=<check Nagios container for current password>

# ntopng traffic monitoring
NTOPNG_HOST=127.0.0.1
NTOPNG_PORT=3001
NTOPNG_USER=admin
NTOPNG_ADMIN_PASSWORD=<from docker inspect network_ntopng env>
```

Note: Get actual passwords from `docker inspect` — never hardcode or guess. The ntopng password was visible in earlier inspection: `dNyEJxnH23cAOQ8u`

- [ ] **Step 2: Verify services are accessible with credentials**

```bash
# Test Nagios
curl -s -u "nagiosadmin:$NAGIOS_PASS" http://192.168.1.200:8082/nagios/cgi-bin/statusjson.cgi?query=hostcount

# Test ntopng
curl -s -u "admin:$NTOPNG_ADMIN_PASSWORD" http://127.0.0.1:3001/lua/rest/v2/get/ntopng/interfaces.lua
```

- [ ] **Step 3: Commit (DO NOT commit .env files)**

The .env files are not committed. Just verify they're in `.gitignore`.

---

### Task 14: Final Integration Test

- [ ] **Step 1: Verify all data sources**

```bash
# AdGuard
curl -s -u "archie_admin:$ADGUARD_PASS" http://192.168.1.200:5355/control/stats

# ntopng
curl -s -u "admin:$NTOPNG_ADMIN_PASSWORD" http://127.0.0.1:3001/lua/rest/v2/get/host/active.lua?ifid=0

# Nagios
curl -s -u "nagiosadmin:$NAGIOS_PASS" http://192.168.1.200:8082/nagios/cgi-bin/statusjson.cgi?query=hostlist

# fail2ban
sudo fail2ban-client status

# DDNS
cat /mnt/archie_brain/scripts/.ddns_last_ip
```

- [ ] **Step 2: Verify all API routes**

Test each new route group:
```bash
# NOC Overview
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/noc/overview

# Traffic
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/traffic/bandwidth

# Defense
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/fail2ban/jails
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/ddns/status

# Devices
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/devices/users

# Reports
curl -s -b "session=admin" http://192.168.1.200:3000/tools/security-network/api/reports/list
```

- [ ] **Step 3: Verify UI loads**

Open http://192.168.1.200:3000/tools/security-network in browser. Screenshot all 8 tabs.

- [ ] **Step 4: Verify agent loop jobs**

Check Autonomy module or platform logs for V.I.G.I.L. job execution entries.

- [ ] **Step 5: Final commit + tag**

```bash
git add -A
git commit -m "feat(security): Security Network NOC v1 complete — 5 data sources, 8 tabs, V.I.G.I.L. agent"
```
