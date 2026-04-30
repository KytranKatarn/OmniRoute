"""Browser Service — platform wrapper for archie_browser skill execution.

Allows platform agents and jobs to call LinkedIn browser skills without
knowing the HTTP transport details. All calls are async (task-based).

Usage:
    from services.browser_service import run_skill, run_skill_sync

    # Fire-and-forget (returns task_id)
    task_id = run_skill("linkedin_post", {"content": "Hello LinkedIn!"})

    # Wait for result (blocks up to timeout_s)
    result = run_skill_sync("linkedin_profile_view",
                            {"profile_url": "https://linkedin.com/in/someone"})
    if result["success"]:
        print(result["name"])
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BROWSER_URL = "http://archie_browser:4242"
DEFAULT_AGENT_ID = 342  # kytranempowerment@gmail.com session
DEFAULT_API_KEY = "internal"
DEFAULT_TIMEOUT_S = 120
POLL_INTERVAL_S = 4


def _headers():
    return {"X-API-Key": DEFAULT_API_KEY, "Content-Type": "application/json"}


def run_skill(
    skill_name: str,
    params: dict,
    agent_id: int = DEFAULT_AGENT_ID,
    wait: bool = False,
) -> dict:
    """Submit a skill task. Returns task dict immediately (or waits if wait=True)."""
    try:
        resp = requests.post(
            f"{BROWSER_URL}/task",
            json={"agent_id": agent_id, "skill": skill_name, "params": params, "wait": wait},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("[BrowserService] run_skill(%s) failed: %s", skill_name, exc)
        return {"success": False, "error": str(exc)}


def run_skill_sync(
    skill_name: str,
    params: dict,
    agent_id: int = DEFAULT_AGENT_ID,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Submit a skill task and poll until complete. Returns result dict."""
    submitted = run_skill(skill_name, params, agent_id)
    task_id = submitted.get("task_id")
    if not task_id:
        return {"success": False, "error": "No task_id returned", "skill": skill_name}

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_S)
        try:
            resp = requests.get(
                f"{BROWSER_URL}/task/{task_id}",
                headers=_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status == "completed":
                result = data.get("result") or {}
                result["_task_id"] = task_id
                result["_skill"] = skill_name
                result["_status"] = "completed"
                return result
            if status == "failed":
                return {
                    "success": False,
                    "error": data.get("error", "unknown error"),
                    "_task_id": task_id,
                    "_skill": skill_name,
                    "_status": "failed",
                }
        except Exception as exc:
            logger.warning("[BrowserService] poll(%s) error: %s", task_id, exc)

    return {
        "success": False,
        "error": f"Timeout after {timeout_s}s",
        "_task_id": task_id,
        "_skill": skill_name,
        "_status": "timeout",
    }


def health_check() -> bool:
    """Returns True if archie_browser is reachable and healthy."""
    try:
        resp = requests.get(f"{BROWSER_URL}/health", headers=_headers(), timeout=5)
        return resp.ok and resp.json().get("status") == "ok"
    except Exception:
        return False


def list_skills() -> list:
    """Returns list of available skill names."""
    try:
        resp = requests.get(f"{BROWSER_URL}/health", headers=_headers(), timeout=5)
        return [s["name"] for s in resp.json().get("skills", [])]
    except Exception:
        return []


# ── Convenience wrappers for common operations ──────────────────────────────


def linkedin_post(content: str, hashtags: list = None, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_post", {"content": content, "hashtags": hashtags or []}, agent_id)


def linkedin_post_image(content: str, image_path: str, hashtags: list = None, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync(
        "linkedin_post_image", {"content": content, "image_path": image_path, "hashtags": hashtags or []}, agent_id
    )


def linkedin_profile_view(profile_url: str, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_profile_view", {"profile_url": profile_url}, agent_id)


def linkedin_connect(profile_url: str, note: str = "", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_connect", {"profile_url": profile_url, "note": note}, agent_id)


def linkedin_message(profile_url: str, message: str, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_message", {"profile_url": profile_url, "message": message}, agent_id)


def linkedin_search(query: str, search_type: str = "people", limit: int = 10, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_search", {"query": query, "type": search_type, "limit": limit}, agent_id)


def linkedin_feed(limit: int = 10, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_feed", {"limit": limit}, agent_id)


def linkedin_inbox(limit: int = 10, unread_only: bool = False, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_inbox", {"limit": limit, "unread_only": unread_only}, agent_id)


def linkedin_notifications(limit: int = 15, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_notifications", {"limit": limit}, agent_id)


def linkedin_company_post(
    content: str, company_slug: str = "kytran-empowerment-inc", hashtags: list = None, agent_id: int = DEFAULT_AGENT_ID
) -> dict:
    return run_skill_sync(
        "linkedin_company_post",
        {"content": content, "company_slug": company_slug, "hashtags": hashtags or []},
        agent_id,
    )
