"""
Network Integration Module for A.R.C.H.I.E. Platform
Integrates with AdGuard, ntopng, Nagios, Nginx Proxy Manager
"""

import os
import requests
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_api_config(service_name):
    """Get API configuration for a service"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT api_key, api_secret, additional_config
        FROM api_keys_config
        WHERE service_name = %s AND is_active = TRUE
    """,
        (service_name,),
    )

    config = cur.fetchone()
    cur.close()
    conn.close()

    return config


# ============================================================================
# ADGUARD INTEGRATION
# ============================================================================


class AdGuardAPI:
    def __init__(self):
        config = get_api_config("adguard")
        self.base_url = "http://192.168.1.250:5354"
        self.username = config["api_key"] if config else None
        self.password = config["api_secret"] if config else None

    def _request(self, method, endpoint, data=None):
        """Make API request to AdGuard"""
        url = f"{self.base_url}/{endpoint}"
        auth = (self.username, self.password) if self.username else None

        if method == "GET":
            response = requests.get(url, auth=auth)
        elif method == "POST":
            response = requests.post(url, auth=auth, json=data)

        response.raise_for_status()
        return response.json()

    def get_stats(self):
        """Get AdGuard statistics"""
        try:
            return self._request("GET", "control/stats")
        except:
            return None

    def block_ip(self, ip_address, reason="Blocked by A.R.C.H.I.E."):
        """Add IP to blacklist"""
        try:
            # Add to database
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO ip_access_control (ip_address, type, reason, is_active)
                VALUES (%s, 'blacklist', %s, TRUE)
                ON CONFLICT (ip_address) DO UPDATE
                SET type = 'blacklist', reason = EXCLUDED.reason, is_active = TRUE
            """,
                (ip_address, reason),
            )

            conn.commit()
            cur.close()
            conn.close()

            # TODO: Add to AdGuard via API when endpoint available
            return True
        except Exception as e:
            print(f"Block IP error: {e}")
            return False

    def unblock_ip(self, ip_address):
        """Remove IP from blacklist"""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE ip_access_control
                SET is_active = FALSE
                WHERE ip_address = %s AND type = 'blacklist'
            """,
                (ip_address,),
            )

            conn.commit()
            cur.close()
            conn.close()

            return True
        except Exception as e:
            print(f"Unblock IP error: {e}")
            return False

    def get_blocked_ips(self):
        """Get list of blocked IPs"""
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM ip_access_control
            WHERE type = 'blacklist' AND is_active = TRUE
            ORDER BY created_at DESC
        """
        )

        blocked_ips = cur.fetchall()
        cur.close()
        conn.close()

        return blocked_ips


# ============================================================================
# NTOPNG INTEGRATION
# ============================================================================


class NtopngAPI:
    def __init__(self):
        config = get_api_config("ntopng")
        self.base_url = "http://192.168.1.250:3001"
        self.username = config["api_key"] if config else "admin"
        self.password = config["api_secret"] if config else ""

    def _request(self, endpoint, params=None):
        """Make API request to ntopng"""
        url = f"{self.base_url}/lua/rest/v1/{endpoint}"
        auth = (self.username, self.password)

        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()
            return response.json()
        except:
            return None

    def get_interface_stats(self):
        """Get network interface statistics"""
        return self._request("get/interface/data.lua")

    def get_top_hosts(self, limit=10):
        """Get top hosts by traffic"""
        return self._request("get/host/top_hosts.lua", {"limit": limit})

    def get_network_traffic(self):
        """Get current network traffic stats"""
        stats = self.get_interface_stats()
        if stats:
            return {
                "bytes_sent": stats.get("bytes.sent", 0),
                "bytes_received": stats.get("bytes.rcvd", 0),
                "packets_sent": stats.get("packets.sent", 0),
                "packets_received": stats.get("packets.rcvd", 0),
            }
        return None


# ============================================================================
# NAGIOS INTEGRATION
# ============================================================================


class NagiosAPI:
    def __init__(self):
        config = get_api_config("nagios")
        self.base_url = "http://192.168.1.250:8082/nagios"
        self.username = config["api_key"] if config else "nagiosadmin"
        self.password = config["api_secret"] if config else ""

    def _request(self, endpoint):
        """Make API request to Nagios"""
        url = f"{self.base_url}/{endpoint}"
        auth = (self.username, self.password)

        try:
            response = requests.get(url, auth=auth)
            response.raise_for_status()
            return response.text
        except:
            return None

    def get_host_status(self):
        """Get status of all monitored hosts"""
        # Note: Actual Nagios API endpoints may vary
        return self._request("cgi-bin/status.cgi?host=all")

    def get_service_status(self):
        """Get status of all services"""
        return self._request("cgi-bin/status.cgi?servicegroup=all&style=detail")

    def get_alerts(self):
        """Get current alerts"""
        return self._request("cgi-bin/notifications.cgi")


# ============================================================================
# NGINX PROXY MANAGER INTEGRATION
# ============================================================================


class NginxProxyAPI:
    def __init__(self):
        config = get_api_config("nginx_proxy_manager")
        self.base_url = "http://192.168.1.250:81/api"
        self.token = config["api_key"] if config else None

    def _request(self, method, endpoint, data=None):
        """Make API request to Nginx Proxy Manager"""
        url = f"{self.base_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        try:
            if method == "GET":
                response = requests.get(url, headers=headers)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data)
            elif method == "PUT":
                response = requests.put(url, headers=headers, json=data)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers)

            response.raise_for_status()
            return response.json()
        except:
            return None

    def get_proxy_hosts(self):
        """Get all proxy hosts"""
        return self._request("GET", "nginx/proxy-hosts")

    def create_proxy_host(self, domain, forward_host, forward_port, ssl=True):
        """Create new proxy host"""
        data = {
            "domain_names": [domain],
            "forward_scheme": "http",
            "forward_host": forward_host,
            "forward_port": forward_port,
            "access_list_id": 0,
            "certificate_id": 0 if not ssl else "new",
            "ssl_forced": ssl,
            "http2_support": True,
            "hsts_enabled": True,
            "hsts_subdomains": True,
        }

        return self._request("POST", "nginx/proxy-hosts", data)

    def get_ssl_certificates(self):
        """Get all SSL certificates"""
        return self._request("GET", "nginx/certificates")


# ============================================================================
# NETWORK MONITORING
# ============================================================================


def get_network_overview():
    """Get comprehensive network overview from all services"""
    try:
        adguard = AdGuardAPI()
        ntopng = NtopngAPI()
        nagios = NagiosAPI()

        overview = {
            "adguard": {
                "stats": adguard.get_stats(),
                "blocked_ips": len(adguard.get_blocked_ips()),
            },
            "ntopng": {
                "traffic": ntopng.get_network_traffic(),
                "top_hosts": ntopng.get_top_hosts(5),
            },
            "nagios": {"status": "connected"},  # Simplified for now
            "timestamp": datetime.now().isoformat(),
        }

        return overview
    except Exception as e:
        print(f"Network overview error: {e}")
        return None


def check_security_threats():
    """Check for security threats across network"""
    threats = []

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check failed logins in last hour
        cur.execute(
            """
            SELECT ip_address, COUNT(*) as attempts
            FROM failed_logins
            WHERE attempted_at >= NOW() - INTERVAL '1 hour'
            GROUP BY ip_address
            HAVING COUNT(*) >= 5
        """
        )

        suspicious_ips = cur.fetchall()

        for ip in suspicious_ips:
            threats.append(
                {
                    "type": "brute_force",
                    "severity": "high",
                    "ip_address": ip["ip_address"],
                    "attempts": ip["attempts"],
                    "message": f"IP {ip['ip_address']} has {ip['attempts']} failed login attempts in the last hour",
                }
            )

        # Check for unusual traffic patterns (placeholder)
        # This would integrate with ntopng API

        cur.close()
        conn.close()

        return threats
    except Exception as e:
        print(f"Security check error: {e}")
        return []


def auto_block_threats():
    """Automatically block detected threats"""
    threats = check_security_threats()
    adguard = AdGuardAPI()

    blocked_count = 0

    for threat in threats:
        if threat["type"] == "brute_force" and threat["severity"] == "high":
            if adguard.block_ip(threat["ip_address"], f"Auto-blocked: {threat['message']}"):
                blocked_count += 1

                # Create notification
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO system_notifications (type, title, message, source, visibility)
                        VALUES ('warning', 'IP Auto-Blocked', %s, 'security_monitor', 'admin')
                    """,
                        (threat["message"],),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except:
                    pass

    return blocked_count


# ============================================================================
# SYSTEM HEALTH
# ============================================================================


def get_system_health():
    """Get overall system health metrics"""
    import psutil

    health = {
        "cpu": {"percent": psutil.cpu_percent(interval=1), "count": psutil.cpu_count()},
        "memory": {
            "total": psutil.virtual_memory().total,
            "available": psutil.virtual_memory().available,
            "percent": psutil.virtual_memory().percent,
        },
        "disk": {
            "total": psutil.disk_usage("/").total,
            "used": psutil.disk_usage("/").used,
            "free": psutil.disk_usage("/").free,
            "percent": psutil.disk_usage("/").percent,
        },
        "network": get_network_overview(),
        "timestamp": datetime.now().isoformat(),
    }

    return health


# ============================================================================
# INSTANCES (for easy import)
# ============================================================================

adguard_api = AdGuardAPI()
ntopng_api = NtopngAPI()
nagios_api = NagiosAPI()
nginx_proxy_api = NginxProxyAPI()
