"""
SABnzbd Client
==============
Client for interacting with SABnzbd download client API.
"""

import requests
import logging
from typing import List, Optional, Dict, Any
from ..services import DownloaderInterface, DownloadItem

logger = logging.getLogger(__name__)


class SABnzbdClient(DownloaderInterface):
    """Client for SABnzbd download client"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize SABnzbd client.

        Args:
            host: SABnzbd server host
            port: SABnzbd server port (usually 8080)
            api_key: SABnzbd API key
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}/api"
        self.api_key = api_key
        self.timeout = 10

    def _request(self, mode: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make request to SABnzbd API"""
        default_params = {"apikey": self.api_key, "output": "json", "mode": mode}

        if params:
            default_params.update(params)

        try:
            response = requests.get(self.base_url, params=default_params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"SABnzbd API request failed: {e}")
            return None

    def probe(self) -> tuple[bool, str]:
        """Two-stage reachability + auth probe.

        `mode=version` needs no key (returns version string). Then
        `mode=queue` with key — SABnzbd returns HTTP 200 with JSON body
        `{"status": false, "error": "API Key Incorrect"}` on bad key,
        which would otherwise look identical to a healthy response.
        """
        try:
            resp = requests.get(
                self.base_url,
                params={"mode": "version", "output": "json"},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return False, f"SABnzbd unreachable: mode=version returned HTTP {resp.status_code}"
            try:
                if "version" not in resp.json():
                    return False, "SABnzbd responded to mode=version but payload missing version"
            except ValueError:
                return False, "SABnzbd responded with non-JSON body"
        except requests.RequestException as e:
            return False, f"SABnzbd unreachable at {self.base_url}: {e}"

        if not self.api_key:
            return False, "SABnzbd reachable but no API key configured"

        try:
            resp = requests.get(
                self.base_url,
                params={"mode": "queue", "output": "json", "apikey": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"SABnzbd mode=queue request failed: {e}"

        if resp.status_code in (401, 403):
            return False, "SABnzbd API key invalid — re-paste key in Media Hub settings"
        if resp.status_code != 200:
            return False, f"SABnzbd mode=queue returned HTTP {resp.status_code}"
        try:
            body = resp.json()
        except ValueError:
            return False, "SABnzbd mode=queue responded with non-JSON body"
        if body.get("status") is False and "API Key" in str(body.get("error", "")):
            return False, "SABnzbd API key invalid — re-paste key in Media Hub settings"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

    def _parse_download_item(self, item: Dict, status: str = "downloading") -> DownloadItem:
        """Parse SABnzbd queue/history item to unified format"""
        # Calculate size
        size_bytes = 0
        size_left_bytes = 0

        if "mb" in item:
            size_bytes = int(float(item.get("mb", 0)) * 1024 * 1024)
        if "mbleft" in item:
            size_left_bytes = int(float(item.get("mbleft", 0)) * 1024 * 1024)

        # Calculate progress
        progress = 0
        if "percentage" in item:
            progress = int(float(item.get("percentage", 0)))
        elif size_bytes > 0:
            downloaded = size_bytes - size_left_bytes
            progress = int((downloaded / size_bytes) * 100)

        # Parse ETA (format: "12:34:56" or "0:00:00")
        eta_seconds = None
        if "timeleft" in item:
            try:
                time_parts = item["timeleft"].split(":")
                if len(time_parts) == 3:
                    eta_seconds = int(time_parts[0]) * 3600 + int(time_parts[1]) * 60 + int(time_parts[2])
            except (ValueError, IndexError):
                pass

        # Parse speed
        speed = None
        # Speed is in the queue object, not individual items

        # Determine status
        item_status = status
        if item.get("status") == "Paused":
            item_status = "paused"
        elif item.get("status") == "Downloading":
            item_status = "downloading"
        elif item.get("status") == "Completed":
            item_status = "completed"
        elif item.get("status") == "Failed":
            item_status = "failed"
        elif item.get("status") == "Extracting":
            item_status = "extracting"
        elif item.get("status") == "Queued":
            item_status = "queued"

        return DownloadItem(
            id=item.get("nzo_id", ""),
            filename=item.get("filename", item.get("name", "Unknown")),
            category=item.get("cat", ""),
            size_bytes=size_bytes,
            size_left_bytes=size_left_bytes,
            progress_percent=progress,
            eta_seconds=eta_seconds,
            speed_bytes_sec=speed,
            status=item_status,
        )

    def get_queue(self) -> List[DownloadItem]:
        """Get current download queue"""
        result = self._request("queue")
        items = []

        if result and "queue" in result:
            queue = result["queue"]
            slots = queue.get("slots", [])

            for slot in slots:
                items.append(self._parse_download_item(slot, "downloading"))

        return items

    def get_history(self, limit: int = 20) -> List[DownloadItem]:
        """Get download history"""
        result = self._request("history", {"limit": limit})
        items = []

        if result and "history" in result:
            history = result["history"]
            slots = history.get("slots", [])

            for slot in slots:
                status = "completed" if slot.get("status") == "Completed" else "failed"
                items.append(self._parse_download_item(slot, status))

        return items

    def get_speed(self) -> Dict[str, Any]:
        """Get current download speed and overall status"""
        result = self._request("queue")

        if result and "queue" in result:
            queue = result["queue"]

            # Parse speed (format: "10.5 MB/s")
            speed_str = queue.get("speed", "0")
            speed_bytes = 0
            try:
                speed_parts = speed_str.split()
                if len(speed_parts) >= 2:
                    speed_val = float(speed_parts[0])
                    speed_unit = speed_parts[1].upper()
                    if "KB" in speed_unit:
                        speed_bytes = int(speed_val * 1024)
                    elif "MB" in speed_unit:
                        speed_bytes = int(speed_val * 1024 * 1024)
                    elif "GB" in speed_unit:
                        speed_bytes = int(speed_val * 1024 * 1024 * 1024)
            except (ValueError, IndexError):
                pass

            # Parse size left
            size_left_str = queue.get("sizeleft", "0 B")

            return {
                "speed": speed_str,
                "speed_bytes_sec": speed_bytes,
                "size_left": size_left_str,
                "eta": queue.get("timeleft", ""),
                "paused": queue.get("paused", False),
                "pause_int": queue.get("pause_int", 0),
                "status": queue.get("status", "idle"),
                "slots_count": len(queue.get("slots", [])),
            }

        return {
            "speed": "0",
            "speed_bytes_sec": 0,
            "size_left": "0 B",
            "eta": "",
            "paused": False,
            "status": "unknown",
            "slots_count": 0,
        }

    def pause_queue(self) -> bool:
        """Pause the download queue"""
        result = self._request("pause")
        return result is not None and result.get("status", False)

    def resume_queue(self) -> bool:
        """Resume the download queue"""
        result = self._request("resume")
        return result is not None and result.get("status", False)

    def pause_item(self, nzo_id: str) -> bool:
        """Pause a specific download"""
        result = self._request("queue", {"name": "pause", "value": nzo_id})
        return result is not None and result.get("status", False)

    def resume_item(self, nzo_id: str) -> bool:
        """Resume a specific download"""
        result = self._request("queue", {"name": "resume", "value": nzo_id})
        return result is not None and result.get("status", False)

    def delete_item(self, nzo_id: str) -> bool:
        """Delete a download from queue"""
        result = self._request("queue", {"name": "delete", "value": nzo_id})
        return result is not None and result.get("status", False)

    def set_speed_limit(self, limit_kbps: int) -> bool:
        """Set download speed limit in KB/s"""
        result = self._request("config", {"name": "speedlimit", "value": limit_kbps})
        return result is not None and result.get("status", False)

    def get_categories(self) -> List[str]:
        """Get available categories"""
        result = self._request("get_cats")
        if result and "categories" in result:
            return result["categories"]
        return []

    def get_warnings(self) -> List[str]:
        """Get warnings/errors"""
        result = self._request("warnings")
        if result and "warnings" in result:
            return result["warnings"]
        return []
