"""Skill: session_fetch — fetch a page using a STORED (imported) browser session.

Unlike authenticated_fetch (which logs in with username/password), this injects the
encrypted storage_state cookies that were imported via the platform's
/api/internal/sessions/<agent>/<platform>/import-cookies flow. A real logged-in
session sails past Cloudflare / 403 / paywalls on share pages (claude.ai/share,
chat.deepseek.com/share, etc.). See KB #270262 / reference_scout-browser-intelligence.

params:
  agent_id        (int)  — which agent's session to use (default 0)
  platform        (str)  — claude|deepseek|openai|linkedin|… (else inferred from url host)
  content_selector(str)  — optional CSS; else returns inner_text("body")
"""
import json
import logging
import os
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PLATFORM_HOST = {
    "claude": "claude.ai",
    "deepseek": "deepseek.com",
    "openai": "openai.com",
    "linkedin": "linkedin.com",
    "twitter": "twitter.com",
    "facebook": "facebook.com",
}


def _platform_from_url(url: str):
    host = (urlparse(url).hostname or "").lower()
    for plat, h in _PLATFORM_HOST.items():
        if h in host:
            return plat
    return None


def _load_session(agent_id: int, platform: str) -> dict:
    base = os.getenv("PLATFORM_INTERNAL_URL", "http://archie_platform:3000")
    key = os.getenv("INTERNAL_API_KEY", "")
    req = urllib.request.Request(
        f"{base}/api/internal/sessions/{agent_id}/{platform}/state",
        # app.py _require_internal_key guard expects: Authorization: Bearer <INTERNAL_API_KEY>
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return (json.loads(r.read().decode()) or {}).get("state") or {}


def _empty(findings: str, ok: bool = False) -> dict:
    return {"data": {}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": ok}


def run(page, url: str, params: dict, job_id: int) -> dict:
    agent_id = int(params.get("agent_id") or 0)  # int() guards against path traversal
    platform = (params.get("platform") or _platform_from_url(url) or "").lower()
    content_sel = params.get("content_selector")
    # Allowlist platform before it goes into the internal URL — blocks path-traversal/SSRF
    # (e.g. platform='../../admin'). Only known platforms are valid session keys anyway.
    if platform not in _PLATFORM_HOST:
        return _empty(f"session_fetch: unsupported/invalid platform {platform!r} — pass a known params.platform")
    try:
        state = _load_session(agent_id, platform)
    except Exception as exc:
        return _empty(f"session_fetch: could not load {platform} session for agent {agent_id}: {exc}")
    cookies = (state or {}).get("cookies") or []
    if not cookies:
        return _empty(f"session_fetch: no active {platform} session for agent {agent_id} — import cookies first")
    try:
        page.context.add_cookies(cookies)
    except Exception as exc:
        logger.warning("session_fetch: add_cookies failed: %s", exc)

    page.goto(url, wait_until="networkidle", timeout=45000)
    content, items = "", []
    if content_sel:
        els = page.query_selector_all(content_sel)
        items = [el.inner_text().strip() for el in els if el.inner_text().strip()]
        content = "\n".join(items)
    else:
        try:
            content = page.inner_text("body")
        except Exception:
            content = ""

    blocked = any(s in content.lower() for s in ("just a moment", "verify you are", "security verification"))
    findings = (
        f"session_fetch: {'BLOCKED (bot-check still hit) — ' if blocked else ''}"
        f"{len(content)} chars from {url} via {platform} session ({len(cookies)} cookies)"
    )
    return {
        "data": {"content": content[:200000], "chars": len(content), "items": items, "url": page.url, "blocked": blocked},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": not blocked,
    }
