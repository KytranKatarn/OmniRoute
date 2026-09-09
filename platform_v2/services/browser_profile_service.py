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
            headers={
                "Authorization": f"Bearer {(os.getenv('BROWSER_LOGIN_API_KEY') or os.getenv('INTERNAL_API_KEY', ''))}"
            },
            timeout=5,
        )
        return bool((r.json() or {}).get("profile_established"))
    except Exception:
        return False


def run_keepwarm() -> dict:
    """Warm every established registry profile with its platform's READ skill."""
    from services.browser_service import is_rate_limited, run_skill_sync

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
        if is_rate_limited(res):
            # Bucket exhausted (S6-P1-7a) — not a warm FAILURE; skip + retry next cycle.
            results[key] = "rate_limited (skipped)"
            logger.info("[keepwarm] %s rate_limited — skipped this cycle", key)
            continue
        # #5627: a warm that LANDS ON THE LOGIN WALL reports success=True (it read *a*
        # page) AND logged_out=True. Treating that as a healthy warm re-stamped a dead
        # profile 'active' every single day, which is what blinded the #1831 release
        # guard. The logged-out signal must be read FIRST and forwarded to record_probe.
        warm_logged_out = bool(res.get("logged_out"))
        if res.get("success") and not warm_logged_out:
            results[key] = "warmed"
            # A successful warm IS a successful health signal — record it so a profile
            # that latched 'stale' on a past transient recovers to active (#4372).
            try:
                from services import browser_session_service

                browser_session_service.record_probe(agent_id, platform, ok=True)
            except Exception as exc:
                logger.debug("[keepwarm] record_probe(ok) failed (best-effort): %s", exc)
        elif warm_logged_out:
            results[key] = "STALE (logged out)"
            logger.warning("[keepwarm] %s landed on the login wall — flipping stale", key)
            try:
                from services import browser_session_service

                browser_session_service.record_probe(
                    agent_id,
                    platform,
                    ok=False,
                    reason="keep-warm landed on a login/authwall",
                    logged_out=True,
                )
            except Exception as exc:
                logger.debug("[keepwarm] record_probe(stale) failed (best-effort): %s", exc)
        else:
            results[key] = f"FAILED: {str(res.get('error') or res.get('_status') or 'unknown')[:120]}"
            logger.warning("[keepwarm] %s %s", key, results[key])
    logger.info("[keepwarm] %s", results)
    return results


def _registry_probe_url(platform: str):
    """#4006 — opt-in generic probe target from the browser_platforms
    registry. None = platform not registered / disabled / no probe_url."""
    try:
        from services import browser_platform_service

        reg = browser_platform_service.get_platform(platform)
        if reg and reg.get("enabled"):
            return reg.get("probe_url") or None
    except Exception:
        return None
    return None


def run_session_health_probe() -> dict:
    """#3708 phase 2 — health-probe every ACTIVE cookie session by running its
    platform's READ-only skill through the stored storage_state. Records the
    result (last_probe_at/ok); a failed probe flips the session to 'stale' so
    skills + the vault stop trusting expired cookies.

    Probe selection (#4006): a dedicated READ skill (WARM_SKILLS) wins;
    otherwise platforms with a registry probe_url use the generic
    session_probe skill; everything else is skipped as before."""
    from services import browser_session_service
    from services.browser_service import is_rate_limited, run_skill_sync

    results = {}
    # Re-probe ACTIVE *and* STALE sessions so a recovered profile can flip back (#4372).
    for agent_id, platform in browser_session_service.list_sessions_for_probe():
        key = f"{agent_id}-{platform}"
        if platform in WARM_SKILLS:
            skill, base_params = WARM_SKILLS[platform]
            params = dict(base_params)
        else:
            probe_url = _registry_probe_url(platform)
            if not probe_url:
                results[key] = "no probe skill for platform — skipped"
                continue
            skill = "session_probe"
            params = {"probe_url": probe_url, "_platform": platform}
        res = run_skill_sync(skill, params, agent_id=agent_id, timeout_s=120)
        if is_rate_limited(res):
            # Bucket exhausted (S6-P1-7a) — the skill never ran, so this is "didn't probe",
            # NOT a probe failure. Skip record_probe entirely → keep last-good status.
            results[key] = "rate_limited (skipped)"
            logger.info("[session-probe] %s rate_limited — skipped, status kept", key)
            continue
        # Only a POSITIVE logged-out signal (skill_runner surfaces result['logged_out']
        # when the page is a login/authwall) flips a session stale. A timeout / lock-busy /
        # generic error is transient and KEEPS the last-good status (#4372 false-negative).
        logged_out = bool(res.get("logged_out"))
        # #5627: a READ skill that lands ON the login wall returns success=True AND
        # logged_out=True. `ok` must therefore EXCLUDE the logged-out case, or the probe
        # reports "ok" and record_probe re-stamps a dead profile 'active'.
        ok = bool(res.get("success")) and not logged_out
        reason = None if ok else str(res.get("error") or res.get("_status") or "probe failed")[:200]
        if logged_out and not reason:
            reason = "probe landed on a login/authwall"
        browser_session_service.record_probe(agent_id, platform, ok, reason, logged_out=logged_out)
        if logged_out:
            results[key] = f"STALE (logged out): {reason}"
            logger.warning("[session-probe] %s flipped stale — logged out: %s", key, reason)
        elif ok:
            results[key] = "ok"
        else:
            results[key] = f"transient (status kept): {reason}"
            logger.info("[session-probe] %s transient probe failure, status kept: %s", key, reason)
    logger.info("[session-probe] %s", results)
    return results
