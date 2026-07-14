"""ai_dispatcher.py — HTTP client calling hub /tools/wtf-hub/api/analyze."""
import logging
import os

import requests

logger = logging.getLogger("wtf-ingest")

_HUB_URL = os.environ.get("WTF_HUB_URL", "")
_HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
_TIMEOUT = int(os.environ.get("WTF_HUB_TIMEOUT", "90"))
_ENABLED = bool(_HUB_URL and _HUB_TOKEN)


def analyze_with_status(task: str, article_id: int, title: str, body: str,
                        source_slug: str = "") -> dict:
    """Dispatch analysis task to hub. Returns {result, status} where status is one of:

      ok            — hub returned a usable result dict
      rate_limited  — hub returned ok:true but result:null + rate_limited:true
                      (per-task interval not elapsed — retry later, not a failure)
      failed        — hub returned ok:false, dispatcher disabled, timeout, or network error
                      (don't retry without reason)

    Callers that don't need the distinction can use analyze() — see below.
    Closes #2944.
    """
    if not _ENABLED:
        logger.debug("ai_dispatcher: WTF_HUB_URL or WTF_HUB_TOKEN not set — skipping %s", task)
        return {"result": None, "status": "failed"}
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
            if data.get("rate_limited"):
                # Surface the hub's pacing hint so callers can wait-and-continue
                # instead of abandoning their run (audit 2026-07-14, #4897).
                return {
                    "result": None,
                    "status": "rate_limited",
                    "retry_after": data.get("retry_after"),
                }
            return {"result": data.get("result"), "status": "ok"}
        logger.warning("ai_dispatcher: task=%s failed: %s", task, data.get("error"))
        return {"result": None, "status": "failed"}
    except requests.Timeout:
        logger.warning("ai_dispatcher: task=%s timed out after %ss", task, _TIMEOUT)
        return {"result": None, "status": "failed"}
    except requests.RequestException as exc:
        logger.error("ai_dispatcher: task=%s connectivity error: %s", task, exc)
        return {"result": None, "status": "failed"}
    except Exception as exc:
        logger.warning("ai_dispatcher: task=%s unexpected error: %s", task, exc)
        return {"result": None, "status": "failed"}


def analyze(task: str, article_id: int, title: str, body: str, source_slug: str = "") -> dict | None:
    """Back-compat wrapper — returns the result dict or None on any non-ok outcome.

    Rate-limited and hard-failed both collapse to None here, matching the pre-#2944
    contract. New code should prefer analyze_with_status() so it can distinguish
    transient rate-limits from real failures (per-task counters, retry strategy).
    """
    return analyze_with_status(task, article_id, title, body, source_slug).get("result")
