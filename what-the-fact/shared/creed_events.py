"""C.R.E.E.D. event emission — posts to ARCHIE governance channel."""
import os
import requests
import logging

logger = logging.getLogger(__name__)
CREED_URL = os.environ.get("CREED_EVENT_URL", "").rstrip("/")


def emit(event_type: str, payload: dict) -> bool:
    """Fire-and-forget CREED event. Returns True on HTTP 2xx, False otherwise."""
    if not CREED_URL:
        logger.debug("CREED_EVENT_URL not configured, skipping emit")
        return False
    try:
        r = requests.post(
            f"{CREED_URL}/events",
            json={"event_type": event_type, "payload": payload},
            timeout=3,
        )
        return 200 <= r.status_code < 300
    except Exception as exc:
        logger.warning("CREED emit failed: %s", exc)
        return False
