"""
Supervision Controls Service
=============================
Schedule-based DNS blocking per device via AdGuard Home.
"""

import logging
from datetime import datetime

from database import get_db_cursor
from tools.security_network.adguard_service import AdGuardService

logger = logging.getLogger(__name__)


class SupervisionService:
    """Manage supervision control schedules and enforce them via AdGuard."""

    CATEGORY_DOMAINS = {
        "social": [
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "snapchat.com",
            "twitter.com",
            "x.com",
            "reddit.com",
            "pinterest.com",
        ],
        "gaming": [
            "steampowered.com",
            "epicgames.com",
            "roblox.com",
            "minecraft.net",
            "twitch.tv",
            "discord.com",
            "xbox.com",
            "playstation.com",
        ],
        "streaming": [
            "netflix.com",
            "youtube.com",
            "disneyplus.com",
            "hulu.com",
            "primevideo.com",
            "crunchyroll.com",
            "twitch.tv",
            "spotify.com",
        ],
        "adult": [
            "pornhub.com",
            "xvideos.com",
            "xhamster.com",
            "onlyfans.com",
        ],
    }

    def get_schedules(self):
        """Return all supervision schedules joined with device info."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT ps.*,
                       COALESCE(nd.friendly_name, nd.hostname) AS device_display_name,
                       COALESCE(nd.owner, nd.friendly_name) AS device_name
                FROM parental_schedules ps
                LEFT JOIN network_devices nd
                    ON ps.device_mac = nd.mac_address
                ORDER BY ps.created_at DESC
                """
            )
            return cur.fetchall()

    def create_schedule(self, device_mac, user_name, schedule, blocked_categories):
        """Insert a new supervision schedule.

        Args:
            device_mac: MAC address of the device.
            user_name: Friendly name for the person using the device.
            schedule: Dict with weekday/weekend blocked windows, e.g.
                      {"weekday": {"start": "22:00", "end": "07:00"},
                       "weekend": {"start": "23:00", "end": "09:00"}}
            blocked_categories: List of category keys (social, gaming, etc.)
        """
        import psycopg2

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO parental_schedules
                    (device_mac, user_name, schedule, blocked_categories)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (device_mac, user_name, psycopg2.Json(schedule), blocked_categories),
            )
            row = cur.fetchone()
            return row["id"] if row else None

    def update_schedule(self, schedule_id, **kwargs):
        """Update fields on an existing schedule."""
        allowed = {"device_mac", "user_name", "schedule", "blocked_categories", "enabled"}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return False

        import psycopg2

        parts = []
        values = []
        for key, val in fields.items():
            if key == "schedule":
                parts.append("schedule = %s")
                values.append(psycopg2.Json(val))
            elif key == "blocked_categories":
                parts.append("blocked_categories = %s")
                values.append(val)
            else:
                parts.append(f"{key} = %s")
                values.append(val)
        parts.append("updated_at = NOW()")
        values.append(schedule_id)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE parental_schedules SET " + ", ".join(parts) + " WHERE id = %s",
                values,
            )
            return cur.rowcount > 0

    def delete_schedule(self, schedule_id):
        """Delete a supervision schedule."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM parental_schedules WHERE id = %s", (schedule_id,))
            return cur.rowcount > 0

    def enforce_schedules(self):
        """Check all enabled schedules and block/unblock devices via AdGuard.

        Called by agent loop supervision enforcement job every 5 minutes.
        """
        schedules = self._get_enabled_schedules()
        if not schedules:
            return {"enforced": 0, "errors": 0}

        adguard = AdGuardService()
        enforced = 0
        errors = 0
        now = datetime.now()

        for sched in schedules:
            try:
                should_block = self._is_in_blocked_window(sched["schedule"], now)
                mac = sched["device_mac"]
                client_id = f"supervision-{mac.replace(':', '-')}"

                # Build blocked services list from categories
                blocked_services = []
                if should_block:
                    for cat in sched["blocked_categories"] or []:
                        blocked_services.extend(self.CATEGORY_DOMAINS.get(cat, []))

                # Update AdGuard client blocking state
                payload = {
                    "name": client_id,
                    "data": {
                        "name": client_id,
                        "ids": [mac],
                        "use_global_blocked_services": not should_block,
                        "blocked_services": blocked_services if should_block else [],
                        "filtering_enabled": should_block,
                    },
                }

                # Try update first; AdGuard returns error if client doesn't exist
                result = adguard._request("POST", "clients/update", data=payload)
                if result is None:
                    # Client may not exist yet — add it
                    adguard._request("POST", "clients/add", data=payload["data"])

                enforced += 1
            except Exception as exc:
                logger.error("Supervision enforce error for %s: %s", sched.get("device_mac"), exc)
                errors += 1

        logger.info("Supervision enforcement: %d enforced, %d errors", enforced, errors)
        return {"enforced": enforced, "errors": errors}

    def get_category_domains(self):
        """Return dict of category -> domain patterns."""
        return dict(self.CATEGORY_DOMAINS)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_enabled_schedules(self):
        """Fetch only enabled schedules."""
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM parental_schedules WHERE enabled = true")
            return cur.fetchall()

    @staticmethod
    def _is_in_blocked_window(schedule, now):
        """Return True if *now* falls within the blocked window.

        Schedule format:
            {"weekday": {"start": "22:00", "end": "07:00"},
             "weekend": {"start": "23:00", "end": "09:00"}}

        A window where start > end (e.g. 22:00-07:00) wraps past midnight.
        """
        if not schedule:
            return False

        day = now.weekday()  # 0=Mon … 6=Sun
        key = "weekend" if day >= 5 else "weekday"
        window = schedule.get(key)
        if not window:
            return False

        try:
            start = datetime.strptime(window["start"], "%H:%M").time()
            end = datetime.strptime(window["end"], "%H:%M").time()
        except (KeyError, ValueError):
            return False

        current = now.time()

        if start <= end:
            # Simple range (e.g. 08:00 - 12:00)
            return start <= current <= end
        else:
            # Overnight range (e.g. 22:00 - 07:00)
            return current >= start or current <= end
