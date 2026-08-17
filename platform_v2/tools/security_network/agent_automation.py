"""
Security Agent Automation Service
==================================
Manages agent suggestions, auto-actions, and configuration.
Default: suggest-only. Per-category auto-mode toggleable.
Includes suggestion engine that scans integrations for actionable findings.
"""

import os
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from psycopg2.extras import RealDictCursor, Json
from database import get_db

logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "mode": "suggest",
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
        if self._config:
            return self._config
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT setting_value FROM security_auto_block_settings
                WHERE setting_key = 'agent_config'
            """
            )
            result = cur.fetchone()
            if result:
                self._config = json.loads(result["setting_value"])
                return self._config
        except Exception as e:
            logger.warning("Failed to load agent config from DB: %s", e)
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass
        self._config = DEFAULT_CONFIG.copy()
        return self._config

    def save_config(self, config: Dict) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_auto_block_settings (setting_key, setting_value)
                VALUES ('agent_config', %s)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value
            """,
                (json.dumps(config),),
            )
            conn.commit()
            self._config = config
            return True
        except Exception as e:
            logger.warning("Failed to save agent config: %s", e)
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

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
    def create_suggestion(
        self, category: str, title: str, description: str, reasoning: str, data: dict = None
    ) -> Optional[int]:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_agent_actions
                (action_type, category, title, description, reasoning, status, data)
                VALUES ('suggest', %s, %s, %s, %s, 'pending', %s) RETURNING id
            """,
                (category, title, description, reasoning, Json(data or {})),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            return action_id
        except Exception as e:
            logger.warning("Failed to create suggestion: %s", e)
            return None
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def approve_suggestion(self, suggestion_id: int) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE security_agent_actions
                SET status = 'approved', executed_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """,
                (suggestion_id,),
            )
            affected = cur.rowcount
            conn.commit()
            return affected > 0
        except Exception as e:
            logger.warning("Failed to approve suggestion %s: %s", suggestion_id, e)
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def dismiss_suggestion(self, suggestion_id: int) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE security_agent_actions
                SET status = 'dismissed', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """,
                (suggestion_id,),
            )
            affected = cur.rowcount
            conn.commit()
            return affected > 0
        except Exception as e:
            logger.warning("Failed to dismiss suggestion %s: %s", suggestion_id, e)
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def get_pending_suggestions(self, category: str = None, limit: int = 50) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            if category:
                cur.execute(
                    """
                    SELECT * FROM security_agent_actions
                    WHERE status = 'pending' AND category = %s
                    ORDER BY created_at DESC LIMIT %s
                """,
                    (category, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM security_agent_actions
                    WHERE status = 'pending'
                    ORDER BY created_at DESC LIMIT %s
                """,
                    (limit,),
                )
            results = cur.fetchall()
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning("Failed to get pending suggestions: %s", e)
            return []
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def get_action_history(self, limit: int = 100) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT * FROM security_agent_actions
                ORDER BY created_at DESC LIMIT %s
            """,
                (limit,),
            )
            results = cur.fetchall()
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning("Failed to get action history: %s", e)
            return []
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def log_auto_action(
        self, category: str, title: str, description: str, reasoning: str, data: dict = None, success: bool = True
    ) -> Optional[int]:
        status = "executed" if success else "failed"
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_agent_actions
                (action_type, category, title, description, reasoning, status, data, executed_at)
                VALUES ('auto_execute', %s, %s, %s, %s, %s, %s, NOW()) RETURNING id
            """,
                (category, title, description, reasoning, status, Json(data or {})),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            return action_id
        except Exception as e:
            logger.warning("Failed to log auto action: %s", e)
            return None
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    # =================================================================
    # Suggestion Engine
    # =================================================================

    def _has_pending_suggestion(self, suggestion_type: str) -> bool:
        """Check if a pending suggestion of this type already exists (dedup)."""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 1 FROM security_agent_actions
                WHERE status = 'pending'
                  AND data->>'suggestion_type' = %s
                LIMIT 1
            """,
                (suggestion_type,),
            )
            return cur.fetchone() is not None
        except Exception as e:
            logger.debug("Failed to check pending suggestion '%s': %s", suggestion_type, e)
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def _create_typed_suggestion(
        self,
        suggestion_type: str,
        category: str,
        title: str,
        description: str,
        reasoning: str,
        severity: str = "medium",
        extra_data: dict = None,
    ) -> Optional[int]:
        """Create a suggestion with dedup check. Returns id or None if duplicate."""
        if self._has_pending_suggestion(suggestion_type):
            return None
        data = {"suggestion_type": suggestion_type, "severity": severity}
        if extra_data:
            data.update(extra_data)
        return self.create_suggestion(category, title, description, reasoning, data)

    # --- Individual Suggestion Generators ---

    def _suggest_filter_update(self) -> List[int]:
        """Check if AdGuard filter lists need refreshing (>7 days old)."""
        created = []
        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()
            status = ag.get_filtering_status()
            if not status:
                return created

            filters = status.get("filters", [])
            now = datetime.now(timezone.utc)
            stale_filters = []

            for f in filters:
                if not f.get("enabled"):
                    continue
                last_updated = f.get("last_updated")
                if not last_updated:
                    stale_filters.append(f.get("name", "unknown"))
                    continue
                try:
                    # AdGuard returns ISO format timestamps
                    updated_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                    if (now - updated_dt) > timedelta(days=7):
                        stale_filters.append(f.get("name", "unknown"))
                except (ValueError, TypeError):
                    stale_filters.append(f.get("name", "unknown"))

            if stale_filters:
                sid = self._create_typed_suggestion(
                    suggestion_type="filter_update_available",
                    category="filters",
                    title="Filter lists need refreshing",
                    description=(
                        f"{len(stale_filters)} filter list(s) haven't been updated in over 7 days: "
                        f"{', '.join(stale_filters[:5])}"
                        + (f" and {len(stale_filters) - 5} more" if len(stale_filters) > 5 else "")
                    ),
                    reasoning="Stale filter lists may miss newly categorized ad/tracking domains.",
                    severity="medium",
                    extra_data={"stale_filters": stale_filters},
                )
                if sid:
                    created.append(sid)
        except Exception as e:
            logger.warning("_suggest_filter_update failed: %s", e)
        return created

    def _suggest_new_devices(self) -> List[int]:
        """Flag unregistered devices as needing attention."""
        created = []
        try:
            from .device_registry_service import DeviceRegistryService

            registry = DeviceRegistryService()
            unregistered = registry.get_unregistered()

            for device in unregistered:
                ip = device.get("ip_address", "unknown")
                hostname = device.get("hostname") or "unknown"
                mac = device.get("mac_address") or "unknown"
                suggestion_type = f"device_vulnerability:{ip}"

                sid = self._create_typed_suggestion(
                    suggestion_type=suggestion_type,
                    category="scanning",
                    title=f"Unregistered device detected: {ip}",
                    description=(
                        f"Device at {ip} (hostname: {hostname}, MAC: {mac}) is active "
                        f"on the network but not registered. It should be classified into "
                        f"a security zone."
                    ),
                    reasoning=(
                        "Unregistered devices default to no zone policy. They should be "
                        "registered and assigned to a security zone for proper DNS filtering."
                    ),
                    severity="high",
                    extra_data={
                        "ip_address": ip,
                        "hostname": hostname,
                        "mac_address": mac,
                        "manufacturer": device.get("manufacturer"),
                    },
                )
                if sid:
                    created.append(sid)
        except Exception as e:
            logger.warning("_suggest_new_devices failed: %s", e)
        return created

    def _suggest_query_spike(self) -> List[int]:
        """Detect unusual DNS query patterns — spike >2x normal or blocked >50% in recent window."""
        created = []
        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()
            stats = ag.get_stats()
            if not stats:
                return created

            # AdGuard stats returns arrays of per-time-unit counts
            dns_queries = stats.get("dns_queries", [])
            blocked_filtering = stats.get("blocked_filtering", [])

            if not dns_queries or len(dns_queries) < 2:
                return created

            # Compare last period to average of previous periods
            recent = dns_queries[-1] if dns_queries else 0
            if len(dns_queries) > 2:
                avg_previous = sum(dns_queries[:-1]) / max(len(dns_queries) - 1, 1)
            else:
                avg_previous = dns_queries[0] if dns_queries else 0

            # Query spike: >2x normal rate
            if avg_previous > 0 and recent > (avg_previous * 2) and recent > 100:
                sid = self._create_typed_suggestion(
                    suggestion_type="network_anomaly",
                    category="dns",
                    title="Unusual DNS query spike detected",
                    description=(
                        f"Recent period saw {recent} queries vs average of "
                        f"{avg_previous:.0f} — a {recent / avg_previous:.1f}x increase."
                    ),
                    reasoning="Query spikes may indicate malware, misconfigured devices, or DNS amplification.",
                    severity="high",
                    extra_data={
                        "recent_queries": recent,
                        "average_queries": round(avg_previous, 1),
                        "multiplier": round(recent / avg_previous, 2),
                    },
                )
                if sid:
                    created.append(sid)

            # Blocked query spike: last period >50% blocked
            recent_blocked = blocked_filtering[-1] if blocked_filtering else 0
            if recent > 50 and recent_blocked > 0:
                blocked_pct = (recent_blocked / recent) * 100
                if blocked_pct > 50:
                    sid = self._create_typed_suggestion(
                        suggestion_type="query_spike_detected",
                        category="dns",
                        title="Blocked queries spike detected",
                        description=(
                            f"{blocked_pct:.0f}% of recent queries were blocked "
                            f"({recent_blocked} of {recent}). This is unusually high."
                        ),
                        reasoning="A high block rate may indicate a compromised device generating ad/malware traffic.",
                        severity="high",
                        extra_data={
                            "blocked_count": recent_blocked,
                            "total_count": recent,
                            "blocked_percent": round(blocked_pct, 1),
                        },
                    )
                    if sid:
                        created.append(sid)
        except Exception as e:
            logger.warning("_suggest_query_spike failed: %s", e)
        return created

    def _suggest_camera_offline(self) -> List[int]:
        """Check for cameras that have been offline (unavailable state)."""
        created = []
        try:
            from .ha_surveillance_service import HASurveillanceService

            ha = HASurveillanceService()
            if not ha.available:
                return created

            cameras = ha.get_cameras()
            if not cameras:
                return created

            for cam in cameras:
                state = cam.get("state", "")
                if state in ("unavailable", "unknown"):
                    entity_id = cam.get("entity_id", "unknown")
                    name = cam.get("friendly_name") or entity_id
                    suggestion_type = f"camera_coverage_gap:{entity_id}"

                    sid = self._create_typed_suggestion(
                        suggestion_type=suggestion_type,
                        category="camera",
                        title=f"Camera offline: {name}",
                        description=(
                            f"Camera '{name}' ({entity_id}) is currently {state}. "
                            f"This creates a coverage gap in surveillance."
                        ),
                        reasoning="Offline cameras leave blind spots. Check power, network, and HA integration.",
                        severity="high",
                        extra_data={
                            "entity_id": entity_id,
                            "friendly_name": name,
                            "state": state,
                        },
                    )
                    if sid:
                        created.append(sid)
        except Exception as e:
            logger.warning("_suggest_camera_offline failed: %s", e)
        return created

    def _suggest_device_offline(self) -> List[int]:
        """Check for trusted/family devices that went offline unexpectedly (>4 hours).

        The age is computed IN SQL (per .claude/rules/database.md): `last_seen_at` is a
        timestamp WITHOUT time zone, so subtracting it from an aware `now()` in Python
        raised a naive/aware TypeError on every run — this check never produced output
        until 2026-08-17 (#5706). Postgres coerces the tz itself, so the TypeError is
        structurally impossible here.
        """
        created = []
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT ip_address::text AS ip_address, friendly_name, hostname,
                           security_zone AS zone,
                           last_seen_at::text AS last_seen_text,
                           EXTRACT(EPOCH FROM (now() - last_seen_at)) / 3600 AS hours_offline
                    FROM network_devices
                    WHERE security_zone IN ('trusted', 'family')
                      AND status = 'active'
                      AND last_seen_at IS NOT NULL
                      AND last_seen_at < now() - interval '4 hours'
                    """
                )
                rows = cur.fetchall()
                cur.close()
            finally:
                conn.close()

            for device in rows:
                hours_offline = float(device["hours_offline"] or 0)
                ip = device.get("ip_address") or "unknown"
                name = device.get("friendly_name") or device.get("hostname") or ip
                zone = device.get("zone")
                suggestion_type = f"device_offline_unexpected:{ip}"

                sid = self._create_typed_suggestion(
                    suggestion_type=suggestion_type,
                    category="scanning",
                    title=f"Trusted device offline: {name}",
                    description=(
                        f"Device '{name}' ({ip}, zone: {zone}) hasn't been seen "
                        f"for {hours_offline:.1f} hours. Last seen: {device.get('last_seen_text')}"
                    ),
                    reasoning=(
                        "Trusted/family devices going offline unexpectedly may indicate "
                        "network issues, device failure, or unauthorized removal."
                    ),
                    severity="medium",
                    extra_data={
                        "ip_address": ip,
                        "friendly_name": name,
                        "zone": zone,
                        "hours_offline": round(hours_offline, 1),
                        "last_seen_at": device.get("last_seen_text"),
                    },
                )
                if sid:
                    created.append(sid)
        except Exception as e:
            logger.warning("_suggest_device_offline failed: %s", e)
        return created

    def _suggest_ssh_threats(self) -> List[int]:
        """Check fail2ban for recent bans (SSH brute force attempts)."""
        created = []
        try:
            # Try to get fail2ban status from host
            result = subprocess.run(
                ["fail2ban-client", "status", "sshd"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return created

            output = result.stdout
            # Parse banned IPs from fail2ban output
            banned_ips = []
            for line in output.split("\n"):
                line = line.strip()
                if "Banned IP list:" in line:
                    ip_part = line.split("Banned IP list:")[-1].strip()
                    if ip_part:
                        banned_ips = [ip.strip() for ip in ip_part.split() if ip.strip()]
                elif "Currently banned:" in line:
                    try:
                        count = int(line.split(":")[-1].strip())
                        if count == 0:
                            return created
                    except (ValueError, IndexError):
                        pass

            if banned_ips:
                sid = self._create_typed_suggestion(
                    suggestion_type="ssh_brute_force",
                    category="access",
                    title=f"SSH brute force: {len(banned_ips)} IP(s) banned",
                    description=(
                        f"fail2ban has banned {len(banned_ips)} IP(s) for SSH brute force attempts: "
                        f"{', '.join(banned_ips[:10])}"
                        + (f" and {len(banned_ips) - 10} more" if len(banned_ips) > 10 else "")
                    ),
                    reasoning="Banned IPs indicate active brute force attacks. Review and consider permanent blocks.",
                    severity="critical" if len(banned_ips) >= 5 else "high",
                    extra_data={
                        "banned_ips": banned_ips[:50],
                        "ban_count": len(banned_ips),
                    },
                )
                if sid:
                    created.append(sid)
        except FileNotFoundError:
            # fail2ban-client not available in container — expected
            pass
        except subprocess.TimeoutExpired:
            logger.warning("fail2ban-client timed out")
        except Exception as e:
            logger.warning("_suggest_ssh_threats failed: %s", e)
        return created

    def _suggest_dns_block_recommendation(self) -> List[int]:
        """Recommend blocking suspicious high-frequency domains not yet blocked."""
        created = []
        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()
            stats = ag.get_stats()
            if not stats:
                return created

            # Top queried domains — look for known ad/tracking patterns
            top_queried = stats.get("top_queried_domains", [])
            if not top_queried:
                return created

            suspicious_patterns = [
                "tracker",
                "tracking",
                "telemetry",
                "analytics",
                "doubleclick",
                "adservice",
                "adsystem",
                "adnxs",
                "facebook.net",
                "fbcdn",
                "scorecardresearch",
            ]

            flagged = []
            for entry in top_queried[:50]:
                if isinstance(entry, dict):
                    for domain, count in entry.items():
                        domain_lower = domain.lower()
                        if any(p in domain_lower for p in suspicious_patterns) and count > 20:
                            # Verify it's not already blocked
                            check = ag.check_host(domain)
                            if check and check.get("reason") in ("NotFilteredNotFound", ""):
                                flagged.append({"domain": domain, "count": count})

            if flagged:
                top_flagged = sorted(flagged, key=lambda x: x["count"], reverse=True)[:5]
                domains_str = ", ".join(f"{f['domain']} ({f['count']}x)" for f in top_flagged)

                sid = self._create_typed_suggestion(
                    suggestion_type="dns_block_recommendation",
                    category="dns",
                    title="Suspicious domains detected — consider blocking",
                    description=(
                        f"{len(flagged)} suspicious domain(s) with high query counts are not blocked: " f"{domains_str}"
                    ),
                    reasoning="These domains match known ad/tracking patterns and are queried frequently.",
                    severity="medium",
                    extra_data={"flagged_domains": flagged[:20]},
                )
                if sid:
                    created.append(sid)
        except Exception as e:
            logger.warning("_suggest_dns_block_recommendation failed: %s", e)
        return created

    def _suggest_access_policy_conflict(self) -> List[int]:
        """Detect devices whose activity doesn't match their assigned zone."""
        created = []
        try:
            from .device_registry_service import DeviceRegistryService
            from .adguard_service import AdGuardService

            registry = DeviceRegistryService()
            ag = AdGuardService()

            # Get IoT-zone devices that show browsing activity (shouldn't be browsing)
            iot_devices = registry.get_devices(zone="iot", status="active")
            if not iot_devices:
                return created

            for device in iot_devices:
                ip = device.get("ip_address")
                if not ip:
                    continue
                report = ag.get_client_report(ip, limit=50)
                if not report:
                    continue

                # IoT devices shouldn't have many unique domains — flag if >20
                top_domains = report.get("top_domains", [])
                unique_count = len(top_domains)
                if unique_count > 20:
                    name = device.get("friendly_name") or device.get("hostname") or ip
                    suggestion_type = f"access_policy_conflict:{ip}"

                    sid = self._create_typed_suggestion(
                        suggestion_type=suggestion_type,
                        category="access",
                        title=f"Zone mismatch: IoT device browsing — {name}",
                        description=(
                            f"Device '{name}' ({ip}) is in the IoT zone but queried "
                            f"{unique_count} unique domains, suggesting it may be misclassified."
                        ),
                        reasoning="IoT devices typically query very few domains. High diversity suggests miscategorization.",
                        severity="medium",
                        extra_data={
                            "ip_address": ip,
                            "friendly_name": name,
                            "unique_domains": unique_count,
                            "current_zone": "iot",
                        },
                    )
                    if sid:
                        created.append(sid)
        except Exception as e:
            logger.warning("_suggest_access_policy_conflict failed: %s", e)
        return created

    # --- Main Orchestrator ---

    def generate_suggestions(self) -> Dict[str, Any]:
        """Run all suggestion generators and store new suggestions in DB.

        Returns a summary of what was generated.
        """
        config = self.get_config()
        if config.get("paused"):
            return {"status": "paused", "generated": 0, "details": {}}

        generators = [
            ("filter_update", self._suggest_filter_update),
            ("new_devices", self._suggest_new_devices),
            ("query_spike", self._suggest_query_spike),
            ("camera_offline", self._suggest_camera_offline),
            ("device_offline", self._suggest_device_offline),
            ("ssh_threats", self._suggest_ssh_threats),
            ("dns_block_recommendation", self._suggest_dns_block_recommendation),
            ("access_policy_conflict", self._suggest_access_policy_conflict),
        ]

        details = {}
        total = 0

        for name, generator in generators:
            try:
                ids = generator()
                details[name] = {"created": len(ids), "ids": ids}
                total += len(ids)
            except Exception as e:
                details[name] = {"created": 0, "error": str(e)}
                logger.error("Suggestion generator '%s' failed: %s", name, e)

        logger.info("Suggestion engine completed: %d new suggestion(s)", total)
        return {"status": "completed", "generated": total, "details": details}
