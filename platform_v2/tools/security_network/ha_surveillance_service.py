"""
Home Assistant Surveillance Service
====================================
Camera management via HA REST API.
Auto-discovers cameras, provides snapshots, stream URLs, and health checks.
"""

import os
import logging
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class HASurveillanceService:
    """Home Assistant camera integration with auto-discovery"""

    ALARM_ENTITY = "alarm_control_panel.blink_home"

    def __init__(self):
        self.base_url = os.getenv("HA_URL", "http://192.168.1.200:8123").rstrip("/")
        self.token = os.getenv("HA_API_TOKEN", "")
        self._camera_cache = None
        self._cache_ts = 0

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
            resp = requests.get(
                f"{self.base_url}/api/{endpoint}",
                headers=self._headers(),
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json() if resp.content else None
        except Exception as e:
            logger.warning("HA GET /api/%s failed: %s", endpoint, e)
            return None

    def _post(self, endpoint: str, data: dict = None, timeout: int = 10) -> Optional[Any]:
        if not self.available:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/{endpoint}",
                headers=self._headers(),
                json=data or {},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {"status": "ok"}
        except Exception as e:
            logger.warning("HA POST /api/%s failed: %s", endpoint, e)
            return None

    def _get_raw(self, endpoint: str, timeout: int = 15) -> Optional[bytes]:
        """Get raw bytes (for camera snapshots)"""
        if not self.available:
            return None
        try:
            resp = requests.get(
                f"{self.base_url}/api/{endpoint}",
                headers=self._headers(),
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning("HA GET raw /api/%s failed: %s", endpoint, e)
            return None

    # --- Auto-Discovery ---
    def _discover_cameras(self) -> List[Dict]:
        """Discover all camera entities from HA states API"""
        import time

        now = time.time()
        # Cache for 60 seconds to avoid hammering HA
        if self._camera_cache is not None and (now - self._cache_ts) < 60:
            return self._camera_cache

        states = self._get("states")
        if not states or not isinstance(states, list):
            return self._camera_cache or []

        cameras = []
        for state in states:
            entity_id = state.get("entity_id", "")
            if entity_id.startswith("camera."):
                attrs = state.get("attributes", {})
                friendly_name = attrs.get("friendly_name", entity_id.replace("camera.", "").replace("_", " ").title())
                cameras.append(
                    {
                        "entity_id": entity_id,
                        "name": friendly_name,
                        "state": state.get("state", "unknown"),
                        "attributes": attrs,
                        "last_updated": state.get("last_updated", ""),
                    }
                )

        self._camera_cache = cameras
        self._cache_ts = now
        return cameras

    # --- Camera States ---
    def get_cameras(self) -> List[Dict]:
        """Get all discovered cameras with friendly names and state"""
        return self._discover_cameras()

    def get_camera_snapshot(self, entity_id: str) -> Optional[bytes]:
        """Get JPEG snapshot for a camera entity.
        entity_id: full entity ID like 'camera.driveway'
        """
        if not entity_id.startswith("camera."):
            return None
        return self._get_raw(f"camera_proxy/{entity_id}")

    def get_camera_stream_url(self, entity_id: str) -> Optional[str]:
        """Get MJPEG stream URL for a camera entity"""
        if not entity_id.startswith("camera."):
            return None
        return f"{self.base_url}/api/camera_proxy_stream/{entity_id}?token={self.token}"

    def check_health(self) -> Dict[str, Any]:
        """Verify HA connection and return status details"""
        if not self.available:
            return {
                "connected": False,
                "error": "HA_API_TOKEN not configured",
                "camera_count": 0,
            }
        try:
            resp = requests.get(
                f"{self.base_url}/api/",
                headers=self._headers(),
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            cameras = self._discover_cameras()
            online = sum(1 for c in cameras if c.get("state") not in ("unavailable", "unknown"))
            return {
                "connected": True,
                "ha_version": data.get("version", "unknown"),
                "camera_count": len(cameras),
                "cameras_online": online,
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "camera_count": 0,
            }

    # --- Arm / Disarm ---
    def get_alarm_state(self) -> Optional[Dict]:
        return self._get(f"states/{self.ALARM_ENTITY}")

    def arm_system(self) -> bool:
        result = self._post(
            "services/alarm_control_panel/alarm_arm_away",
            {"entity_id": self.ALARM_ENTITY},
        )
        return result is not None

    def disarm_system(self) -> bool:
        result = self._post(
            "services/alarm_control_panel/alarm_disarm",
            {"entity_id": self.ALARM_ENTITY},
        )
        return result is not None

    # --- Motion Events ---
    def get_recent_events(self, hours: int = 24) -> List[Dict]:
        """Get recent motion events from HA history"""
        cameras = self._discover_cameras()
        events = []
        for cam in cameras:
            entity_id = cam["entity_id"]
            cam_key = entity_id.replace("camera.", "")
            motion_entity = f"binary_sensor.{cam_key}_motion_detected"
            history = self._get(f"history/period?filter_entity_id={motion_entity}&minimal_response")
            if history and isinstance(history, list) and len(history) > 0:
                for entry in history[0]:
                    if entry.get("state") == "on":
                        events.append(
                            {
                                "camera": cam_key,
                                "camera_entity": entity_id,
                                "location": cam.get("name", cam_key),
                                "event_type": "motion",
                                "timestamp": entry.get("last_changed", ""),
                            }
                        )
        events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return events
