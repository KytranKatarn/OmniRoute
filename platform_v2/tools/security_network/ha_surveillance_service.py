"""
Home Assistant Surveillance Service
====================================
Camera management via HA REST API for Blink cameras.
Provides: snapshots, motion events, arm/disarm, camera states.
"""

import os
import requests
from typing import Optional, Dict, Any, List


class HASurveillanceService:
    """Home Assistant camera integration"""

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
            resp = requests.get(f"{self.base_url}/api/{endpoint}", headers=self._headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.json() if resp.content else None
        except Exception:
            return None

    def _post(self, endpoint: str, data: dict = None, timeout: int = 10) -> Optional[Any]:
        if not self.available:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/{endpoint}", headers=self._headers(), json=data or {}, timeout=timeout
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {"status": "ok"}
        except Exception:
            return None

    def _get_raw(self, endpoint: str, timeout: int = 15) -> Optional[bytes]:
        """Get raw bytes (for camera snapshots)"""
        if not self.available:
            return None
        try:
            resp = requests.get(f"{self.base_url}/api/{endpoint}", headers=self._headers(), timeout=timeout)
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
                motion_entity = f"binary_sensor.{cam_id}_motion_detected"
                motion_state = self._get(f"states/{motion_entity}")
                battery_entity = f"binary_sensor.{cam_id}_battery"
                battery_state = self._get(f"states/{battery_entity}")

                cameras.append(
                    {
                        "id": cam_id,
                        "entity": info["entity"],
                        "location": info["location"],
                        "area": info["area"],
                        "state": state.get("state", "unknown"),
                        "attributes": state.get("attributes", {}),
                        "motion": motion_state.get("state", "off") if motion_state else "unknown",
                        "battery_ok": battery_state.get("state", "on") if battery_state else "unknown",
                        "last_updated": state.get("last_updated", ""),
                    }
                )
            else:
                cameras.append(
                    {
                        "id": cam_id,
                        "entity": info["entity"],
                        "location": info["location"],
                        "area": info["area"],
                        "state": "unavailable",
                        "attributes": {},
                        "motion": "unknown",
                        "battery_ok": "unknown",
                        "last_updated": "",
                    }
                )
        return cameras

    def get_camera_snapshot(self, camera_id: str) -> Optional[bytes]:
        info = self.CAMERAS.get(camera_id)
        if not info:
            return None
        return self._get_raw(f"camera_proxy/{info['entity']}")

    def trigger_snapshot(self, camera_id: str) -> bool:
        info = self.CAMERAS.get(camera_id)
        if not info:
            return False
        result = self._post("services/blink/trigger_camera", {"entity_id": info["entity"]})
        return result is not None

    # --- Arm / Disarm ---
    def get_alarm_state(self) -> Optional[Dict]:
        return self._get(f"states/{self.ALARM_ENTITY}")

    def arm_system(self) -> bool:
        result = self._post("services/alarm_control_panel/alarm_arm_away", {"entity_id": self.ALARM_ENTITY})
        return result is not None

    def disarm_system(self) -> bool:
        result = self._post("services/alarm_control_panel/alarm_disarm", {"entity_id": self.ALARM_ENTITY})
        return result is not None

    # --- Motion Events ---
    def get_recent_events(self, hours: int = 24) -> List[Dict]:
        """Get recent motion events from HA history"""
        events = []
        for cam_id, info in self.CAMERAS.items():
            motion_entity = f"binary_sensor.{cam_id}_motion_detected"
            history = self._get(f"history/period?filter_entity_id={motion_entity}&minimal_response")
            if history and isinstance(history, list) and len(history) > 0:
                for entry in history[0]:
                    if entry.get("state") == "on":
                        events.append(
                            {
                                "camera": cam_id,
                                "location": info["location"],
                                "event_type": "motion",
                                "timestamp": entry.get("last_changed", ""),
                            }
                        )
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events

    def check_health(self) -> bool:
        if not self.available:
            return False
        result = self._get("states")
        return isinstance(result, list)
