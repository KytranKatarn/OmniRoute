"""Persistent browser-profile keep-warm (#3982).

A device-trusted profile that sits idle eventually goes stale (cookie expiry,
re-auth walls). Once a day we run a cheap READ-only skill through each
ESTABLISHED profile so the platform sees normal activity and cookies refresh.
Never a posting skill — keep-warm must be invisible.

Registry is a code constant for v1; the S.C.O.U.T. session vault (#3708)
makes it data-driven later.
"""

import logging
import os

import requests

logger = logging.getLogger("platform.browser_keepwarm")

# (agent_id, platform) pairs worth keeping warm. 342 = Kytran LinkedIn
# session (shared by KE Inc. + Creed-AI), 377 = Terry Caetano.
WARM_PROFILES = [(342, "linkedin"), (377, "linkedin")]

# platform → (READ-only skill, params). No entry = platform not warmable yet.
WARM_SKILLS = {"linkedin": ("linkedin_feed", {"limit": 3})}

_SIDECAR = "http://archie_browser_login:4281"


def _profile_established(agent_id: int, platform: str) -> bool:
    """Fail closed — never warm a profile we can't confirm exists."""
    try:
        r = requests.get(
            f"{_SIDECAR}/status",
            params={"agent_id": agent_id, "platform": platform},
            headers={"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"},
            timeout=5,
        )
        return bool((r.json() or {}).get("profile_established"))
    except Exception:
        return False


def run_keepwarm() -> dict:
    """Warm every established registry profile with its platform's READ skill."""
    from services.browser_service import run_skill_sync

    results = {}
    for agent_id, platform in WARM_PROFILES:
        key = f"{agent_id}-{platform}"
        if platform not in WARM_SKILLS:
            results[key] = "no warm skill for platform — skipped"
            continue
        if not _profile_established(agent_id, platform):
            results[key] = "not established — skipped"
            continue
        skill, params = WARM_SKILLS[platform]
        res = run_skill_sync(skill, dict(params), agent_id=agent_id, timeout_s=120)
        if res.get("success"):
            results[key] = "warmed"
        else:
            results[key] = f"FAILED: {str(res.get('error') or res.get('_status') or 'unknown')[:120]}"
            logger.warning("[keepwarm] %s %s", key, results[key])
    logger.info("[keepwarm] %s", results)
    return results


def run_session_health_probe() -> dict:
    """#3708 phase 2 — health-probe every ACTIVE cookie session by running its
    platform's READ-only skill through the stored storage_state. Records the
    result (last_probe_at/ok); a failed probe flips the session to 'stale' so
    skills + the vault stop trusting expired cookies. Platforms with no READ
    skill are skipped (can't probe what we can't read)."""
    from services import browser_session_service
    from services.browser_service import run_skill_sync

    results = {}
    for agent_id, platform in browser_session_service.list_active_sessions():
        key = f"{agent_id}-{platform}"
        if platform not in WARM_SKILLS:
            results[key] = "no probe skill for platform — skipped"
            continue
        skill, params = WARM_SKILLS[platform]
        res = run_skill_sync(skill, dict(params), agent_id=agent_id, timeout_s=120)
        ok = bool(res.get("success"))
        reason = None if ok else str(res.get("error") or res.get("_status") or "probe failed")[:200]
        browser_session_service.record_probe(agent_id, platform, ok, reason)
        results[key] = "ok" if ok else f"STALE: {reason}"
        if not ok:
            logger.warning("[session-probe] %s flipped stale: %s", key, reason)
    logger.info("[session-probe] %s", results)
    return results
