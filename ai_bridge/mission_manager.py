"""
Mission Manager — Profile loading, activation, scheduling, and event triggers.
Project #146: Station Operations / Task #953

Manages 6 mission profiles that dynamically reconfigure Bridge dispatcher
routing, station priorities, agent warmup, and IAAE welfare thresholds.

Profiles: standard_operations, security_audit, feature_sprint,
          content_push, maintenance, emergency_response

Active profile stored in system_config (key='active_mission_profile').
Cached with 60s TTL to avoid repeated DB lookups on every dispatch.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-16
"""

import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from psycopg2.extras import RealDictCursor, Json

from database import get_db_cursor

logger = logging.getLogger(__name__)


class MissionManager:
    """Manages mission profiles for Bridge dispatcher routing."""

    # Class-level cache shared across instances
    _cache = {"profile": None, "timestamp": 0, "ttl": 60}

    def __init__(self):
        self._cache_ttl = 60  # seconds

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _is_cache_valid(self) -> bool:
        """Check if the cached active profile is still fresh."""
        return (
            self._cache["profile"] is not None
            and (time.time() - self._cache["timestamp"]) < self._cache["ttl"]
        )

    def _invalidate_cache(self):
        """Force next lookup to hit DB."""
        self._cache["profile"] = None
        self._cache["timestamp"] = 0

    # ------------------------------------------------------------------
    # Profile queries
    # ------------------------------------------------------------------

    def get_active_profile(self) -> Dict[str, Any]:
        """
        Get the currently active mission profile.

        Reads from system_config (key='active_mission_profile'), falls back
        to 'standard_operations' if unset. Result is cached for 60s.
        """
        if self._is_cache_valid():
            return self._cache["profile"]

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Get active profile name from system_config
                cur.execute(
                    "SELECT value FROM system_config WHERE key = 'active_mission_profile'"
                )
                row = cur.fetchone()
                profile_name = row["value"] if row else "standard_operations"

                # Fetch full profile
                cur.execute(
                    "SELECT * FROM mission_profiles WHERE name = %s",
                    (profile_name,),
                )
                profile = cur.fetchone()

                if not profile:
                    # Fallback to default
                    cur.execute(
                        "SELECT * FROM mission_profiles WHERE is_default = TRUE LIMIT 1"
                    )
                    profile = cur.fetchone()

                if profile:
                    result = dict(profile)
                    self._cache["profile"] = result
                    self._cache["timestamp"] = time.time()
                    return result

        except Exception as e:
            logger.error(f"Failed to get active mission profile: {e}")

        # Hard fallback if DB is unreachable
        return {
            "name": "standard_operations",
            "display_name": "Standard Operations",
            "color": "#00d4ff",
            "icon": "activity",
            "job_routing_overrides": {},
            "station_priorities": {},
            "agent_config": {},
            "loop_job_config": {},
            "event_triggers": [],
            "is_default": True,
        }

    def get_all_profiles(self) -> List[Dict[str, Any]]:
        """List all mission profiles ordered by name."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT * FROM mission_profiles ORDER BY is_default DESC, name ASC"
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to list mission profiles: {e}")
            return []

    def get_profile(self, name_or_id) -> Optional[Dict[str, Any]]:
        """Get a single profile by name (str) or id (int)."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                if isinstance(name_or_id, int):
                    cur.execute(
                        "SELECT * FROM mission_profiles WHERE id = %s",
                        (name_or_id,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM mission_profiles WHERE name = %s",
                        (str(name_or_id),),
                    )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get mission profile {name_or_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate_profile(
        self,
        name_or_id,
        triggered_by: str = "manual",
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Switch the active mission profile.

        1. Resolve the target profile
        2. Update system_config
        3. Log to governance_audit_log
        4. Send Telegram notification
        5. Invalidate cache

        Returns dict with success status and profile info.
        """
        profile = self.get_profile(name_or_id)
        if not profile:
            return {"success": False, "error": f"Profile not found: {name_or_id}"}

        old_profile = self.get_active_profile()

        # Don't re-activate same profile
        if old_profile.get("name") == profile["name"]:
            return {
                "success": True,
                "message": f"Already on {profile['display_name']}",
                "profile": profile,
            }

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Upsert system_config
                cur.execute(
                    """
                    INSERT INTO system_config (key, value, description, updated_at)
                    VALUES ('active_mission_profile', %s, 'Currently active mission profile', NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (profile["name"],),
                )

                # Log to governance_audit_log
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (event_type, event_category, action, target_table,
                         old_value, new_value, reason, outcome, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        "mission_profile_change",
                        "operations",
                        "activate",
                        "mission_profiles",
                        Json({"profile": old_profile.get("name")}),
                        Json({"profile": profile["name"]}),
                        reason
                        or f"{triggered_by}: {old_profile.get('display_name')} -> {profile['display_name']}",
                        "success",
                    ),
                )

            # Invalidate cache so next dispatch picks up new profile
            self._invalidate_cache()

            # Send Telegram notification (best-effort)
            self._notify_telegram(old_profile, profile, triggered_by, reason)

            logger.info(
                f"Mission profile activated: {profile['display_name']} "
                f"(was: {old_profile.get('display_name')}, trigger: {triggered_by})"
            )

            return {
                "success": True,
                "message": f"Activated {profile['display_name']}",
                "old_profile": old_profile.get("name"),
                "profile": profile,
            }

        except Exception as e:
            logger.error(f"Failed to activate mission profile: {e}")
            return {"success": False, "error": str(e)}

    def _notify_telegram(
        self,
        old_profile: Dict,
        new_profile: Dict,
        triggered_by: str,
        reason: str,
    ):
        """Send Telegram notification about profile change (best-effort)."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                message = (
                    f"🔄 Mission Profile Changed\n"
                    f"  {old_profile.get('display_name', '?')} → {new_profile['display_name']}\n"
                    f"  Trigger: {triggered_by}\n"
                )
                if reason:
                    message += f"  Reason: {reason}\n"

                cur.execute(
                    """
                    INSERT INTO system_notifications
                        (type, title, message, created_at)
                    VALUES ('alert', 'Mission Profile Changed', %s, NOW())
                    """,
                    (message,),
                )
        except Exception as e:
            logger.debug(f"Telegram notification failed (non-critical): {e}")

    # ------------------------------------------------------------------
    # Schedule evaluation
    # ------------------------------------------------------------------

    def check_schedule(self):
        """
        Evaluate cron rules from mission_schedules.

        Called every 5 minutes by agent loop. Checks if any schedule
        should activate its profile based on current time.
        """
        try:
            from croniter import croniter
        except ImportError:
            logger.debug("croniter not installed — schedule check skipped")
            return

        now = datetime.now()

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT ms.*, mp.name as profile_name, mp.display_name
                    FROM mission_schedules ms
                    JOIN mission_profiles mp ON mp.id = ms.profile_id
                    WHERE ms.is_active = TRUE
                    """
                )
                schedules = cur.fetchall()

            for schedule in schedules:
                cron = croniter(schedule["cron_expression"], now)
                prev_run = cron.get_prev(datetime)

                # Check if we're within the schedule window
                # (prev cron trigger was within the last 5 minutes)
                minutes_since = (now - prev_run).total_seconds() / 60.0
                if minutes_since <= 5:
                    active = self.get_active_profile()
                    if active.get("name") != schedule["profile_name"]:
                        self.activate_profile(
                            schedule["profile_name"],
                            triggered_by="schedule",
                            reason=f"Cron: {schedule['cron_expression']}",
                        )

                    # If schedule has a duration, schedule revert
                    if schedule.get("duration_minutes"):
                        self._schedule_revert(
                            schedule["duration_minutes"],
                            schedule["profile_name"],
                        )

        except Exception as e:
            logger.debug(f"Schedule check failed: {e}")

    def _schedule_revert(self, duration_minutes: int, from_profile: str):
        """
        Store a revert time in system_config so a future check_schedule
        call can switch back to standard_operations.
        """
        try:
            revert_at = datetime.now().timestamp() + (duration_minutes * 60)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO system_config (key, value, description, updated_at)
                    VALUES ('mission_revert_at', %s, 'When to revert mission profile', NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (str(revert_at),),
                )
        except Exception as e:
            logger.debug(f"Failed to schedule revert: {e}")

    # ------------------------------------------------------------------
    # Event triggers
    # ------------------------------------------------------------------

    def check_event_triggers(
        self, event_type: str, event_data: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Evaluate event triggers across all profiles.

        Checks if any profile's event_triggers match the given event.
        Returns the activated profile name if triggered, None otherwise.

        Supported conditions:
        - fail2ban_bans_gt_N: fail2ban ban count exceeds N
        - ssh_brute_force: SSH brute force detected
        - critical_alerts_gt_N: critical alert count exceeds N
        """
        event_data = event_data or {}

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT name, event_triggers
                    FROM mission_profiles
                    WHERE event_triggers != '[]'::jsonb
                    """
                )
                profiles = cur.fetchall()

            active = self.get_active_profile()

            for profile in profiles:
                triggers = profile.get("event_triggers", [])
                if not isinstance(triggers, list):
                    continue

                for trigger in triggers:
                    condition = trigger.get("condition", "")
                    cooldown_min = trigger.get("cooldown_min", 30)

                    if self._evaluate_condition(condition, event_type, event_data):
                        # Check cooldown
                        if self._is_on_cooldown(profile["name"], cooldown_min):
                            continue

                        # Don't re-trigger same profile
                        if active.get("name") == profile["name"]:
                            continue

                        result = self.activate_profile(
                            profile["name"],
                            triggered_by="event",
                            reason=f"Trigger: {condition} ({event_type})",
                        )
                        if result.get("success"):
                            return profile["name"]

        except Exception as e:
            logger.debug(f"Event trigger check failed: {e}")

        return None

    def _evaluate_condition(
        self, condition: str, event_type: str, event_data: Dict
    ) -> bool:
        """Evaluate a single trigger condition against event data."""
        # fail2ban_bans_gt_N
        if condition.startswith("fail2ban_bans_gt_"):
            threshold = int(condition.split("_")[-1])
            return (
                event_type == "fail2ban"
                and event_data.get("ban_count", 0) > threshold
            )

        # ssh_brute_force
        if condition == "ssh_brute_force":
            return event_type == "ssh_brute_force"

        # critical_alerts_gt_N
        if condition.startswith("critical_alerts_gt_"):
            threshold = int(condition.split("_")[-1])
            return (
                event_type == "critical_alert"
                and event_data.get("count", 0) > threshold
            )

        return False

    def _is_on_cooldown(self, profile_name: str, cooldown_min: int) -> bool:
        """Check if a profile was recently activated (within cooldown window)."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT timestamp FROM governance_audit_log
                    WHERE event_type = 'mission_profile_change'
                      AND new_value->>'profile' = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (profile_name,),
                )
                row = cur.fetchone()
                if row:
                    last_activation = row["timestamp"]
                    elapsed = (datetime.now() - last_activation).total_seconds() / 60.0
                    return elapsed < cooldown_min
        except Exception as e:
            logger.debug(f"Cooldown check failed: {e}")

        return False

    # ------------------------------------------------------------------
    # Config accessors (used by dispatcher, agent loop, warmup)
    # ------------------------------------------------------------------

    def get_routing_overrides(self) -> Dict[str, str]:
        """Return active profile's job_routing_overrides."""
        profile = self.get_active_profile()
        return profile.get("job_routing_overrides", {}) or {}

    def get_station_priorities(self) -> Dict[str, float]:
        """Return active profile's station_priorities."""
        profile = self.get_active_profile()
        return profile.get("station_priorities", {}) or {}

    def get_agent_config(self) -> Dict[str, Any]:
        """Return active profile's agent_config."""
        profile = self.get_active_profile()
        return profile.get("agent_config", {}) or {}

    def get_loop_job_config(self) -> Dict[str, Any]:
        """Return active profile's loop_job_config."""
        profile = self.get_active_profile()
        return profile.get("loop_job_config", {}) or {}
