"""quick_analyzer.py — Tier-1 HTTP client for #2943 two-tier LLM.

POSTs to the hub's /tools/wtf-hub/api/analyze-quick endpoint (shipped in PR #807).
Same {result, status} contract as ai_dispatcher.analyze_with_status() so the
tier_router can swap callers without surprise.

The hub-side endpoint is responsible for routing to qwen2.5:1.5b via DHQ; we
just consume the JSON. We DO strip markdown fences around the response — the
hub's qwen2.5:7b habit wraps JSON in ```json ... ``` and we need a clean dict.
"""

import json
import logging
import os
import re

import requests

logger = logging.getLogger("wtf-ingest")

_HUB_URL = os.environ.get("WTF_HUB_URL", "")
_HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
_TIMEOUT = int(os.environ.get("WTF_TIER1_TIMEOUT", "15"))
_ENABLED = bool(_HUB_URL and _HUB_TOKEN)

# Strip ```json fences and stray prefixes (e.g. "Here is the JSON:") that small
# models like to emit. Tolerant — we just want the first {...} JSON object.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.+?)\s*```\s*$", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _coerce_dict(raw):
    """Best-effort: turn the hub's `result` field into a plain dict.

    Hub returns parsed JSON when the model output was clean, else
    {"raw": "<string>"} as a fallback. We unwrap the raw form here.
    """
    if isinstance(raw, dict) and "raw" not in raw:
        return raw
    text = raw.get("raw") if isinstance(raw, dict) else raw
    if not isinstance(text, str):
        return None
    # Strip ```json fences if present
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    # Or pull the first {...} blob out of chatty output
    if not text.lstrip().startswith("{"):
        m = _FIRST_OBJ_RE.search(text)
        if m:
            text = m.group(0)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def analyze_quick(task: str, article_id: int, title: str, body: str,
                  source_slug: str = "", prefer_node: str = "") -> dict:
    """Dispatch Tier-1 quick analysis. Returns {result, status} matching
    ai_dispatcher.analyze_with_status() shape:

      ok            — usable result dict (always has 'tier' = 'quick_v1')
      rate_limited  — hub returned rate_limited (shouldn't happen for quick
                      tier — quick endpoint has no per-task throttle today,
                      but kept for forward compat)
      failed        — dispatcher disabled, timeout, network error, or
                      response couldn't be coerced to dict
    """
    if not _ENABLED:
        logger.debug("quick_analyzer: WTF_HUB_URL or WTF_HUB_TOKEN not set — skipping %s", task)
        return {"result": None, "status": "failed"}

    payload = {
        "task": task,
        "article_id": article_id,
        "title": title,
        "body": body[:2000],
        "source_slug": source_slug,
    }
    if prefer_node:
        payload["prefer_node"] = prefer_node

    try:
        resp = requests.post(
            f"{_HUB_URL}/tools/wtf-hub/api/analyze-quick",
            json=payload,
            headers={
                "Authorization": f"Bearer {_HUB_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            err = data.get("error") or "unknown"
            logger.warning("quick_analyzer: task=%s rejected: %s", task, err)
            return {"result": None, "status": "failed"}
        if data.get("rate_limited"):
            return {"result": None, "status": "rate_limited"}

        raw = data.get("result")
        coerced = _coerce_dict(raw) if raw else None
        if not coerced:
            logger.warning("quick_analyzer: task=%s response not coercible: %r", task, raw)
            return {"result": None, "status": "failed"}
        return {"result": coerced, "status": "ok"}

    except requests.Timeout:
        logger.warning("quick_analyzer: task=%s timed out after %ss", task, _TIMEOUT)
        return {"result": None, "status": "failed"}
    except requests.RequestException as exc:
        logger.error("quick_analyzer: task=%s connectivity error: %s", task, exc)
        return {"result": None, "status": "failed"}
    except Exception as exc:
        logger.warning("quick_analyzer: task=%s unexpected error: %s", task, exc)
        return {"result": None, "status": "failed"}
