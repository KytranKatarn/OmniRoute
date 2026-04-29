"""ai_dispatcher.py — HTTP client calling hub /tools/wtf-hub/api/analyze."""
import logging
import os

import requests

logger = logging.getLogger("wtf-ingest")

_HUB_URL = os.environ.get("WTF_HUB_URL", "")
_HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
_TIMEOUT = int(os.environ.get("WTF_HUB_TIMEOUT", "90"))
_ENABLED = bool(_HUB_URL and _HUB_TOKEN)


def analyze(task: str, article_id: int, title: str, body: str, source_slug: str = "") -> dict | None:
    """Dispatch analysis task to hub. Returns parsed result dict or None on failure."""
    if not _ENABLED:
        logger.debug("ai_dispatcher: WTF_HUB_URL or WTF_HUB_TOKEN not set — skipping %s", task)
        return None
    try:
        resp = requests.post(
            f"{_HUB_URL}/tools/wtf-hub/api/analyze",
            json={
                "task": task,
                "article_id": article_id,
                "title": title,
                "body": body[:3000],
                "source_slug": source_slug,
            },
            headers={
                "Authorization": f"Bearer {_HUB_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data.get("result")
        logger.warning("ai_dispatcher: task=%s failed: %s", task, data.get("error"))
        return None
    except requests.Timeout:
        logger.warning("ai_dispatcher: task=%s timed out after %ss", task, _TIMEOUT)
        return None
    except requests.RequestException as exc:
        logger.error("ai_dispatcher: task=%s connectivity error: %s", task, exc)
        return None
    except Exception as exc:
        logger.warning("ai_dispatcher: task=%s unexpected error: %s", task, exc)
        return None
