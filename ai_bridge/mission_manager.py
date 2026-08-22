"""
Mission Manager — Profile loading, activation, scheduling, event triggers,
and event-driven flow routing (conditional branching for mission profiles).

Project #146: Station Operations / Task #953, #957

Manages 6 mission profiles that dynamically reconfigure Bridge dispatcher
routing, station priorities, agent warmup, and C.R.E.E.D. welfare thresholds.

Flow Router (Task #957): Inspired by CrewAI Flows. Predefined workflow
flows allow the completion of one job to automatically trigger the next
job in a chain, with conditional branching based on job results.

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

# --- Timed-window revert bookkeeping (#5902) ---------------------------------
# NOT steering keys. `active_mission_profile` (and, for real routing,
# `system_config['fleet_dispatch_mode']`) decide what the fleet does; these two
# only record that a TIMED window is outstanding and which profile it belongs to.
# Keeping the pair together is what stops a stale revert from overriding a later
# manual activation — see _apply_pending_revert.
_REVERT_AT_KEY = "mission_revert_at"
_REVERT_FROM_KEY = "mission_revert_from"
_REVERT_TARGET = "standard_operations"


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
        return self._cache["profile"] is not None and (time.time() - self._cache["timestamp"]) < self._cache["ttl"]

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
                cur.execute("SELECT value FROM system_config WHERE key = 'active_mission_profile'")
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
                    cur.execute("SELECT * FROM mission_profiles WHERE is_default = TRUE LIMIT 1")
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
                cur.execute("SELECT * FROM mission_profiles ORDER BY is_default DESC, name ASC")
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
                        reason or f"{triggered_by}: {old_profile.get('display_name')} -> {profile['display_name']}",
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
        # End any elapsed timed window FIRST (#5902). Deliberately before the
        # croniter import: a missing croniter must not strand a pending revert,
        # and reverting is useful even when no schedule can fire.
        try:
            self._apply_pending_revert()
        except Exception as e:  # a stuck revert must never break schedule checks
            logger.warning(f"Pending-revert check failed: {e}")

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

        ⚠️ ``from_profile`` is PERSISTED, not just accepted (#5902). Without it a
        pending revert cannot tell whether the profile it was scheduled for is
        still the active one — so a stale revert would yank a LATER, deliberate
        manual activation back to standard_operations. The reader
        (``_apply_pending_revert``) refuses to act when they disagree.
        """
        try:
            revert_at = datetime.now().timestamp() + (duration_minutes * 60)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO system_config (key, value, description, updated_at)
                    VALUES (%s, %s, 'When to revert mission profile', NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (_REVERT_AT_KEY, str(revert_at)),
                )
                cur.execute(
                    """
                    INSERT INTO system_config (key, value, description, updated_at)
                    VALUES (%s, %s, 'Profile the pending revert applies to', NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (_REVERT_FROM_KEY, str(from_profile or "")),
                )
        except Exception as e:
            logger.warning(f"Failed to schedule revert from {from_profile}: {e}")

    def _clear_pending_revert(self):
        """Drop both revert keys. Called once a revert is applied or invalidated."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "DELETE FROM system_config WHERE key IN (%s, %s)",
                    (_REVERT_AT_KEY, _REVERT_FROM_KEY),
                )
        except Exception as e:
            logger.warning(f"Failed to clear pending revert: {e}")

    def _read_pending_revert(self):
        """``(revert_at_epoch, from_profile)``; ``(None, None)`` when nothing pends."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT key, value FROM system_config WHERE key IN (%s, %s)",
                    (_REVERT_AT_KEY, _REVERT_FROM_KEY),
                )
                rows = {
                    (r["key"] if isinstance(r, dict) else r[0]): (r["value"] if isinstance(r, dict) else r[1])
                    for r in (cur.fetchall() or [])
                }
        except Exception as e:
            logger.warning(f"Failed to read pending revert: {e}")
            return None, None

        raw = rows.get(_REVERT_AT_KEY)
        if raw in (None, ""):
            return None, None
        try:
            return float(raw), (rows.get(_REVERT_FROM_KEY) or None)
        except (TypeError, ValueError):
            # Garbage in the slot would otherwise wedge every future check.
            logger.warning("mission_revert_at is unparseable (%r) — clearing", raw)
            self._clear_pending_revert()
            return None, None

    def _apply_pending_revert(self):
        """End a timed mission window whose duration has elapsed (#5902).

        THE BUG THIS FIXES: ``_schedule_revert`` wrote ``mission_revert_at`` and
        NOTHING read it — the key appeared exactly once in the whole codebase. Its
        own docstring promised "a future check_schedule call can switch back", and
        check_schedule never did. Live consequence: the one active schedule
        (``maintenance``, cron ``0 2 * * 0``, 120 min) fired on Sunday 2026-08-16,
        wrote a 04:04 revert, and the platform sat in ``maintenance`` from then on
        — re-arming a revert nobody honoured every Sunday since.

        ⚠️ Refuses to act if the active profile is no longer the one the revert was
        scheduled for. A revert is permission to end ONE window, never a licence to
        override whatever a human chose afterwards.
        """
        revert_at, scheduled_from = self._read_pending_revert()
        if revert_at is None:
            return False
        if datetime.now().timestamp() < revert_at:
            return False

        active = (self.get_active_profile() or {}).get("name")
        if scheduled_from and active and active != scheduled_from:
            logger.info(
                "mission revert due for %r but active profile is %r — "
                "the window was superseded; dropping the revert",
                scheduled_from,
                active,
            )
            self._clear_pending_revert()
            return False

        if active == _REVERT_TARGET:
            # Already where the revert would take us; just tidy the keys.
            self._clear_pending_revert()
            return False

        self.activate_profile(
            _REVERT_TARGET,
            triggered_by="schedule_revert",
            reason=f"Timed window on {scheduled_from or 'a scheduled profile'} elapsed",
        )
        self._clear_pending_revert()
        logger.info("mission profile reverted %s -> %s", active, _REVERT_TARGET)
        return True

    # ------------------------------------------------------------------
    # Event triggers
    # ------------------------------------------------------------------

    def check_event_triggers(self, event_type: str, event_data: Optional[Dict] = None) -> Optional[str]:
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

    def _evaluate_condition(self, condition: str, event_type: str, event_data: Dict) -> bool:
        """Evaluate a single trigger condition against event data."""
        # fail2ban_bans_gt_N
        if condition.startswith("fail2ban_bans_gt_"):
            threshold = int(condition.split("_")[-1])
            return event_type == "fail2ban" and event_data.get("ban_count", 0) > threshold

        # ssh_brute_force
        if condition == "ssh_brute_force":
            return event_type == "ssh_brute_force"

        # critical_alerts_gt_N
        if condition.startswith("critical_alerts_gt_"):
            threshold = int(condition.split("_")[-1])
            return event_type == "critical_alert" and event_data.get("count", 0) > threshold

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

    # ------------------------------------------------------------------
    # Flow Router — Event-driven conditional branching (Task #957)
    # ------------------------------------------------------------------

    def start_flow(self, flow_name: str, initial_data: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Start a workflow flow, creating the first job.

        Args:
            flow_name: Key in WORKFLOW_FLOWS.
            initial_data: Arbitrary data passed through the flow steps.

        Returns:
            Dict with flow_name, job_id, step, total on success; None if
            flow_name is unknown or job creation fails.
        """
        flow = WORKFLOW_FLOWS.get(flow_name)
        if not flow:
            logger.warning(f"Unknown flow: {flow_name}")
            return None

        first_step = flow["steps"][0]
        metadata = {
            "flow_name": flow_name,
            "flow_step": 0,
            "flow_total": len(flow["steps"]),
            "flow_data": initial_data or {},
        }

        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        job_id = dispatcher.create_job(
            job_type=first_step["job_type"],
            module_source="flow_engine",
            description=f"Flow: {flow['name']} - Step 1/{len(flow['steps'])}",
            total_steps=1,
            metadata=metadata,
        )

        if not job_id:
            logger.error(f"Failed to create first job for flow {flow_name}")
            return None

        logger.info(f"Flow started: {flow['name']} (job {job_id}, " f"step 1/{len(flow['steps'])})")
        return {
            "flow_name": flow_name,
            "job_id": job_id,
            "step": 1,
            "total": len(flow["steps"]),
        }

    def advance_flow(self, job_id: int, job_result: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Called when a flow job completes — advance to next step or end.

        Reads flow metadata from the completed job, evaluates any
        conditional gate, and creates the next job if appropriate.

        Args:
            job_id: The bridge_jobs.id that just completed.
            job_result: Result data from the completed job (used for
                        conditional evaluation).

        Returns:
            Dict with status ('completed', 'skipped', 'advanced') and
            details, or None if the job has no flow metadata.
        """
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT metadata FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
        except Exception as e:
            logger.error(f"Failed to read flow metadata for job {job_id}: {e}")
            return None

        if not row or not row.get("metadata"):
            return None

        meta = row["metadata"]
        if isinstance(meta, str):
            import json

            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                return None

        flow_name = meta.get("flow_name")
        step_idx = meta.get("flow_step", 0)

        if not flow_name:
            return None

        flow = WORKFLOW_FLOWS.get(flow_name)
        if not flow:
            logger.warning(f"Flow {flow_name} not found in WORKFLOW_FLOWS")
            return None

        current_step = flow["steps"][step_idx]
        next_idx = step_idx + 1

        # Check if flow is complete
        if current_step.get("on_complete") == "end" or next_idx >= len(flow["steps"]):
            logger.info(f"Flow completed: {flow['name']} at step {step_idx + 1}")
            return {"status": "completed", "flow_name": flow_name}

        # Check conditional gate
        if current_step.get("on_complete") == "conditional":
            condition = current_step.get("condition", {})
            if not self._evaluate_flow_condition(condition, job_result):
                reason = f"{condition.get('field')} {condition.get('operator')} " f"{condition.get('value')}"
                logger.info(f"Flow skipped: {flow['name']} — condition not met ({reason})")
                return {
                    "status": "skipped",
                    "flow_name": flow_name,
                    "reason": f"Condition not met: {reason}",
                }

        # Create next job
        next_step = flow["steps"][next_idx]
        next_meta = {
            "flow_name": flow_name,
            "flow_step": next_idx,
            "flow_total": len(flow["steps"]),
            "flow_data": meta.get("flow_data", {}),
        }

        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        next_job_id = dispatcher.create_job(
            job_type=next_step["job_type"],
            module_source="flow_engine",
            description=(f"Flow: {flow['name']} - " f"Step {next_idx + 1}/{len(flow['steps'])}"),
            total_steps=1,
            metadata=next_meta,
        )

        if not next_job_id:
            logger.error(f"Failed to create next job for flow {flow_name} step {next_idx + 1}")
            return {
                "status": "error",
                "flow_name": flow_name,
                "error": "Failed to create next job",
            }

        logger.info(f"Flow advanced: {flow['name']} → step {next_idx + 1}/" f"{len(flow['steps'])} (job {next_job_id})")
        return {
            "status": "advanced",
            "flow_name": flow_name,
            "next_job_id": next_job_id,
            "step": next_idx + 1,
            "total": len(flow["steps"]),
        }

    @staticmethod
    def _evaluate_flow_condition(condition: Dict[str, Any], job_result: Optional[Dict]) -> bool:
        """
        Evaluate a conditional gate for flow routing.

        Supported operators: gt, gte, lt, lte, eq, ne.
        """
        if not condition:
            return True

        field = condition.get("field")
        operator = condition.get("operator")
        value = condition.get("value")

        if not field or not operator:
            return True

        result_value = (job_result or {}).get(field, 0)

        if operator == "gt":
            return result_value > value
        elif operator == "gte":
            return result_value >= value
        elif operator == "lt":
            return result_value < value
        elif operator == "lte":
            return result_value <= value
        elif operator == "eq":
            return result_value == value
        elif operator == "ne":
            return result_value != value

        logger.warning(f"Unknown flow condition operator: {operator}")
        return False

    def get_available_flows(self) -> Dict[str, Any]:
        """Return all predefined workflow flows."""
        return WORKFLOW_FLOWS


# ======================================================================
# Predefined Workflow Flows (Task #957)
# ======================================================================
# Each flow is a sequence of steps routed through stations.
# on_complete: "next" (always advance), "conditional" (check gate), "end"

WORKFLOW_FLOWS: Dict[str, Any] = {
    "security_scan_flow": {
        "name": "Security Scan Flow",
        "description": "Scan for vulnerabilities, analyse threats, then review code.",
        "steps": [
            {
                "job_type": "vulnerability_scan",
                "station": "SECURITY",
                "on_complete": "next",
            },
            {
                "job_type": "threat_analysis",
                "station": "SECURITY",
                "on_complete": "conditional",
                "condition": {
                    "field": "findings_count",
                    "operator": "gt",
                    "value": 0,
                },
            },
            {
                "job_type": "code_review",
                "station": "ENGINEERING",
                "on_complete": "end",
            },
        ],
    },
    "content_pipeline": {
        "name": "Content Pipeline",
        "description": "Write content then send for engineering review.",
        "steps": [
            {
                "job_type": "content_writing",
                "station": "CREATIVE",
                "on_complete": "next",
            },
            {
                "job_type": "code_review",
                "station": "ENGINEERING",
                "on_complete": "end",
            },
        ],
    },
    "incident_response": {
        "name": "Incident Response",
        "description": "Analyse threat, respond to incident, produce DNS report.",
        "steps": [
            {
                "job_type": "threat_analysis",
                "station": "SECURITY",
                "on_complete": "next",
            },
            {
                "job_type": "incident_response",
                "station": "SECURITY",
                "on_complete": "next",
            },
            {
                "job_type": "dns_report",
                "station": "SECURITY",
                "on_complete": "end",
            },
        ],
    },
}
