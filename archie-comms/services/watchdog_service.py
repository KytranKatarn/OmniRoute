"""Platform Health Watchdog — monitors archie_platform from archie_comms.

Pings platform health endpoint every 30s. After 3 consecutive failures,
alerts Kytran via Telegram. Notifies again when platform recovers.
"""

import logging
import os
import time
import threading
import urllib.request

logger = logging.getLogger(__name__)

PLATFORM_URL = os.getenv("PLATFORM_URL", "http://archie_platform:3000")
CHECK_INTERVAL = 30
FAILURE_THRESHOLD = 3


class PlatformWatchdog:
    def __init__(self):
        self._failures = 0
        self._alerted = False
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="platform-watchdog")
        self._thread.start()
        logger.info("Platform watchdog started (checking %s every %ds)", PLATFORM_URL, CHECK_INTERVAL)

    def stop(self):
        self._running = False

    def _check_health(self):
        try:
            req = urllib.request.Request(f"{PLATFORM_URL}/api/health", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def _loop(self):
        while self._running:
            time.sleep(CHECK_INTERVAL)
            if self._check_health():
                if self._failures > 0:
                    logger.info("Platform recovered after %d failures", self._failures)
                    if self._alerted:
                        self._send_recovery_alert()
                self._failures = 0
                self._alerted = False
            else:
                self._failures += 1
                logger.warning("Platform health check failed (%d/%d)", self._failures, FAILURE_THRESHOLD)
                if self._failures >= FAILURE_THRESHOLD and not self._alerted:
                    self._send_down_alert()
                    self._alerted = True

    def _send_down_alert(self):
        try:
            from services.telegram_service import send_system
            send_system(
                "Platform Down",
                f"archie_platform has been unreachable for {self._failures * CHECK_INTERVAL}s. "
                f"I'm still here and monitoring. Will notify you when it recovers.",
                source_module="watchdog_service",
            )
        except Exception as e:
            logger.error("Watchdog: failed to send down alert: %s", e)

    def _send_recovery_alert(self):
        try:
            from services.telegram_service import send_system
            send_system(
                "Platform Recovered",
                f"archie_platform is back online after ~{self._failures * CHECK_INTERVAL}s downtime.",
                source_module="watchdog_service",
            )
        except Exception as e:
            logger.error("Watchdog: failed to send recovery alert: %s", e)
