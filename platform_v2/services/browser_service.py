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
import os
import time

import requests

logger = logging.getLogger(__name__)

BROWSER_URL = "http://archie_browser:4242"
DEFAULT_AGENT_ID = 342  # kytranempowerment@gmail.com session
DEFAULT_API_KEY = os.getenv("BROWSER_API_KEY", "internal")
DEFAULT_TIMEOUT_S = 120
POLL_INTERVAL_S = 4
# S6-P1-8b: after a publish (idempotency_key set) times out, re-poll a few more times to
# catch a completion that lands just past the client deadline (a cold post can finish ~250s),
# so a published-but-timed-out post reports the truth instead of a false 'timeout'.
RECOVERY_REPOLLS = 3
RECOVERY_BACKOFF_S = 5


def _headers():
    return {"Authorization": f"Bearer {DEFAULT_API_KEY}", "Content-Type": "application/json"}


def run_skill(
    skill_name: str,
    params: dict,
    agent_id: int = DEFAULT_AGENT_ID,
    wait: bool = False,
    idempotency_key: str = None,
    post_metadata: dict = None,
) -> dict:
    """Submit a skill task. Returns task dict immediately (or waits if wait=True).

    idempotency_key (S6-P1-8b): a content+account+slot hash recorded in browser_task_log
    so a timed-out publish is recoverable and a retry cannot double-post."""
    try:
        body = {"agent_id": agent_id, "skill": skill_name, "params": params, "wait": wait}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        if post_metadata:
            body["post_metadata"] = post_metadata
        resp = requests.post(
            f"{BROWSER_URL}/task",
            json=body,
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
    idempotency_key: str = None,
    post_metadata: dict = None,
) -> dict:
    """Submit a skill task and poll until complete. Returns result dict.

    S6-P1-8b: when an idempotency_key is supplied (a publish), a client timeout does NOT
    immediately give up — it re-polls the task a few more times to catch a completion that
    lands just past the deadline (a cold post can finish ~250s). So a post that DID publish
    reports 'completed' (truthful) instead of a false 'timeout' an operator might retry into
    a double-post. The key is also recorded sidecar-side in browser_task_log."""
    submitted = run_skill(skill_name, params, agent_id, idempotency_key=idempotency_key, post_metadata=post_metadata)
    task_id = submitted.get("task_id")
    if not task_id:
        return {"success": False, "error": "No task_id returned", "skill": skill_name}

    def _check():
        """GET the task once. Returns a terminal result dict, or None if still running."""
        try:
            resp = requests.get(f"{BROWSER_URL}/task/{task_id}", headers=_headers(), timeout=10)
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
            if status == "rate_limited":
                # Per-profile token bucket exhausted (S6-P1-7a). NOT a failure — the caller
                # reschedules on its next cycle; the distinct _status lets a caller SKIP.
                return {
                    "success": False,
                    "error": "rate_limited",
                    "retry_after": data.get("retry_after"),
                    "_task_id": task_id,
                    "_skill": skill_name,
                    "_status": "rate_limited",
                }
        except Exception as exc:
            logger.warning("[BrowserService] poll(%s) error: %s", task_id, exc)
        return None

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_S)
        terminal = _check()
        if terminal is not None:
            return terminal

    # S6-P1-8b recovery: a publish (idempotency_key set) gets a bounded grace re-poll so a
    # completion landing just past the deadline is reported truthfully, not as 'timeout'.
    if idempotency_key:
        for _ in range(RECOVERY_REPOLLS):
            time.sleep(RECOVERY_BACKOFF_S)
            terminal = _check()
            if terminal is not None:
                logger.info("[BrowserService] %s completed during grace re-poll (task %s)", skill_name, task_id)
                return terminal

    return {
        "success": False,
        "error": f"Timeout after {timeout_s}s",
        "_task_id": task_id,
        "_skill": skill_name,
        "_status": "timeout",
    }


def is_rate_limited(result: dict) -> bool:
    """True if a run_skill_sync result was deferred by the sidecar's per-profile rate
    bucket (S6-P1-7a). Callers treat this as a transient SKIP, NOT a failure — the work
    reschedules on the caller's next cycle."""
    return bool(result) and result.get("_status") == "rate_limited"


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


def linkedin_delete(
    post_url: str,
    expect_contains: str = "",
    dry_run: bool = False,
    agent_id: int = DEFAULT_AGENT_ID,
) -> dict:
    """Delete a SINGLE LinkedIn post by permalink (#4326).

    Destructive — the guards live in the skill (single-post-by-URL only, rejects
    lists / non-permalink URLs, optional ``expect_contains`` confirmation, and a
    ``dry_run`` that stops at the confirm dialog). ``agent_id`` selects the
    browser identity (342 Kytran / 377 Terry). You can only delete your own posts.
    """
    params = {"post_url": post_url, "dry_run": dry_run}
    if expect_contains:
        params["expect_contains"] = expect_contains
    return run_skill_sync("linkedin_delete", params, agent_id)


def linkedin_post_edit(
    post_url: str,
    new_content: str = "",
    expect_contains: str = "",
    dry_run: bool = False,
    agent_id: int = DEFAULT_AGENT_ID,
) -> dict:
    """Edit a SINGLE published LinkedIn post by permalink (#2600).

    Companion to ``linkedin_delete``. Guards live in the skill: single-post-by-URL
    only, optional ``expect_contains`` confirmation, ``dry_run`` that opens the
    editor and reports current text without saving, and an honesty gate that
    reports failure (not phantom success) if LinkedIn's edit modal fails to close.
    ``agent_id`` selects the browser identity; you can only edit your own posts.
    """
    params = {"post_url": post_url, "dry_run": dry_run}
    if new_content:
        params["new_content"] = new_content
    if expect_contains:
        params["expect_contains"] = expect_contains
    return run_skill_sync("linkedin_post_edit", params, agent_id)


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


def linkedin_creed_post(
    content: str, company_slug: str = "115977300", hashtags: list = None, agent_id: int = DEFAULT_AGENT_ID
) -> dict:
    """Post to Creed-AI Institute LinkedIn organization page.

    Default slug is the numeric LinkedIn company ID; override via LINKEDIN_CREED_SLUG env.
    """
    return run_skill_sync(
        "linkedin_creed_post",
        {"content": content, "company_slug": company_slug, "hashtags": hashtags or []},
        agent_id,
    )


def linkedin_follow(url: str, name: str = "", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_follow", {"url": url, "name": name}, agent_id, timeout_s=60)


def linkedin_like(post_url: str, reaction: str = "like", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_like", {"post_url": post_url, "reaction": reaction}, agent_id)


def linkedin_comment(post_url: str, comment: str, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_comment", {"post_url": post_url, "comment": comment}, agent_id)


def linkedin_share(
    post_url: str, commentary: str = "", hashtags: list = None, agent_id: int = DEFAULT_AGENT_ID
) -> dict:
    return run_skill_sync(
        "linkedin_share", {"post_url": post_url, "commentary": commentary, "hashtags": hashtags or []}, agent_id
    )


def linkedin_first_comment(post_url: str, comment: str = "", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_first_comment", {"post_url": post_url, "comment": comment}, agent_id, timeout_s=90)


def linkedin_post_comments(post_url: str, limit: int = 50, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    """READ-only: scrape the comment thread on a post (#3964 read scope).

    Returns {success, post_url, total, comments:[{urn, author, headline, text,
    timestamp, is_reply}]}. Posts nothing — does not trip the step-up wall.
    """
    return run_skill_sync("linkedin_post_comments", {"post_url": post_url, "limit": limit}, agent_id, timeout_s=120)


def linkedin_article(title: str, body: str, cover_image_path: str = "", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync(
        "linkedin_article",
        {"title": title, "body": body, "cover_image_path": cover_image_path},
        agent_id,
        timeout_s=180,
    )


def linkedin_poll(
    question: str, options: list, preamble: str = "", duration_days: int = 7, agent_id: int = DEFAULT_AGENT_ID
) -> dict:
    return run_skill_sync(
        "linkedin_poll",
        {"question": question, "options": options, "preamble": preamble, "duration_days": duration_days},
        agent_id,
    )


def linkedin_document(
    content: str, doc_path: str, doc_title: str = "", hashtags: list = None, agent_id: int = DEFAULT_AGENT_ID
) -> dict:
    return run_skill_sync(
        "linkedin_document",
        {"content": content, "doc_path": doc_path, "doc_title": doc_title, "hashtags": hashtags or []},
        agent_id,
        timeout_s=180,
    )


def linkedin_featured(url: str, title: str = "", description: str = "", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync(
        "linkedin_featured", {"item_type": "link", "url": url, "title": title, "description": description}, agent_id
    )


def linkedin_analytics(mode: str = "profile", agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_analytics", {"mode": mode}, agent_id, timeout_s=90)


def linkedin_reply(reply_to: str, message: str, agent_id: int = DEFAULT_AGENT_ID) -> dict:
    return run_skill_sync("linkedin_reply", {"reply_to": reply_to, "message": message}, agent_id)


# ---------------------------------------------------------------------------
# Web scraping
# ---------------------------------------------------------------------------

# No agent session needed for scraping — use agent_id=1 (system placeholder).
_SCRAPE_AGENT_ID = int(os.getenv("BROWSER_SCRAPE_AGENT_ID", "1"))


def scrape_article(url: str, timeout_s: int = 30) -> dict:
    """Fetch full article body text from a URL via Playwright.

    Returns {"success": True, "body": str, "chars": int} or
            {"success": False, "error": str}.
    """
    return run_skill_sync(
        "scrape_article",
        {"url": url},
        agent_id=_SCRAPE_AGENT_ID,
        timeout_s=timeout_s,
    )


# ---------------------------------------------------------------------------
# Headed execution (#4649) — run a baked skill in the LOGIN sidecar's headed
# browser (Xvfb :99, trusted profile, same recipe as the human noVNC login).
# Some LinkedIn flows behave differently headless; this is the sanctioned
# fallback tier. Same trust boundary as the headless API: baked skill code
# only, token-gated, profile-mutex'd against live login sessions.
# ---------------------------------------------------------------------------

BROWSER_LOGIN_URL = os.getenv("BROWSER_LOGIN_URL", "http://archie_browser_login:4281")


def _audit_headed_run(skill: str, agent_id: int, platform: str, result: dict, duration_ms: int) -> None:
    """Per-run audit row — 0 tokens, mirrors the scraper telemetry pattern
    (visible on Token Economy without touching LLM accounting)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO task_execution_log
                       (agent_id, agent_name, worker_type, task_type, task_description,
                        module_source, request_origin, model_used, tokens_used,
                        duration_ms, success, error_message, created_at)
                   VALUES (%s, %s, 'internal', 'browser_headed', %s,
                           'browser_headed', 'platform', 'browser', 0,
                           %s, %s, %s, NOW())""",
                (
                    agent_id,
                    "S.C.O.U.T.",
                    f"headed:{skill} ({platform})"[:200],
                    duration_ms,
                    bool(result.get("success")),
                    (str(result.get("error"))[:300] if result.get("error") else None),
                ),
            )
    except Exception:
        logger.warning("headed audit row failed", exc_info=True)


def run_skill_headed(
    skill_name: str,
    params: dict = None,
    agent_id: int = DEFAULT_AGENT_ID,
    platform: str = "linkedin",
    timeout_s: int = 300,
    deny_mutating: bool = False,
) -> dict:
    """Run one baked skill HEADED via the login sidecar. Synchronous (the
    sidecar runs one headed task at a time; 409 = busy/login-session active).
    deny_mutating is enforced sidecar-side where the MUTATING flag lives."""
    started = time.time()
    try:
        resp = requests.post(
            f"{BROWSER_LOGIN_URL}/headed-skill",
            json={
                "skill": skill_name,
                "params": params or {},
                "agent_id": agent_id,
                "platform": platform,
                "deny_mutating": deny_mutating,
            },
            headers={
                "Authorization": f"Bearer {(os.getenv('BROWSER_LOGIN_API_KEY') or os.getenv('INTERNAL_API_KEY', ''))}"
            },
            timeout=timeout_s,
        )
        try:
            result = resp.json()
        except ValueError:
            result = {}
        if not isinstance(result, dict):
            result = {}
        if resp.status_code == 409:
            result.setdefault("success", False)
            result.setdefault("error", "headed sidecar busy (login session or task in flight)")
        elif not resp.ok:
            result = {"success": False, "error": f"headed sidecar http {resp.status_code}"}
        result.setdefault("success", False)
    except Exception as exc:
        result = {"success": False, "error": f"headed call failed: {type(exc).__name__}"}
    _audit_headed_run(skill_name, agent_id, platform, result, int((time.time() - started) * 1000))
    return result


def run_skill_hardened(
    skill_name: str,
    params: dict = None,
    agent_id: int = DEFAULT_AGENT_ID,
    platform: str = "linkedin",
    timeout_s: int = DEFAULT_TIMEOUT_S,
    allow_mutating_fallback: bool = False,
    notify_on_fail: bool = True,
) -> dict:
    """#4649 COO pattern: headless first → HEADED retry → Telegram escalation
    only when both fail. MUTATING skills are NOT retried headed unless the
    caller explicitly allows it (a 'failed' headless publish may have half-
    landed — auto-retrying risks a double-post; the sidecar enforces the
    refusal via deny_mutating)."""
    r = run_skill_sync(skill_name, params or {}, agent_id, timeout_s=timeout_s)
    if isinstance(r, dict) and r.get("success"):
        return r

    headed = run_skill_headed(
        skill_name,
        params,
        agent_id=agent_id,
        platform=platform,
        timeout_s=max(timeout_s, 240),
        deny_mutating=not allow_mutating_fallback,
    )
    if headed.get("success"):
        headed["_recovered_headed"] = True
        logger.info("[Hardened] %s recovered via HEADED retry (agent %s)", skill_name, agent_id)
        return headed

    if notify_on_fail:
        try:
            from services.telegram_service import send_system

            send_system(
                "Headed fallback failed",
                f"Skill {skill_name} (agent {agent_id}/{platform}) failed headless AND headed. "
                f"headless: {str((r or {}).get('error'))[:120]} | headed: {str(headed.get('error'))[:120]}",
                source="browser_service.hardened",
            )
        except Exception:
            pass
    headed.setdefault("_headless_error", (r or {}).get("error"))
    return headed
