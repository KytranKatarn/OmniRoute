"""Generic cookie-session health probe (#4006 — S.C.O.U.T. auth fabric).

Platform-agnostic READ-only skill: navigate to the platform's registered
probe_url with the stored session and report whether we're still logged in.
Used by run_session_health_probe() for platforms that have no dedicated READ
skill (those keep using WARM_SKILLS). Bind the session at call time via
params["_platform"] — PLATFORMS stays empty on purpose.

Heuristic: success = navigation ok AND the final URL doesn't look like a
login/authwall redirect. Callers may pass login_markers to tune per platform.
"""

SKILL_NAME = "session_probe"
PLATFORMS = []  # platform-agnostic — skill_runner binds via params["_platform"]

_DEFAULT_LOGIN_MARKERS = [
    "/login",
    "/signin",
    "/sign_in",
    "/sign-in",
    "/authwall",
    "/checkpoint",
]


def execute(page, params: dict) -> dict:
    probe_url = (params.get("probe_url") or "").strip()
    if not probe_url.startswith("https://"):
        return {"success": False, "error": "probe_url (https) required"}
    markers = [str(m) for m in (params.get("login_markers") or _DEFAULT_LOGIN_MARKERS) if m]

    resp = page.goto(probe_url, wait_until="domcontentloaded", timeout=30000)
    final_url = page.url or ""
    redirected_to_login = any(m in final_url for m in markers)
    ok = bool(resp and resp.ok and not redirected_to_login)
    return {
        "success": ok,
        "status": resp.status if resp else None,
        "final_url": final_url,
        "redirected_to_login": redirected_to_login,
    }
