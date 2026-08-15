"""ONE definition of the anti-detection browser fingerprint.

LinkedIn (and Google) block logins from browsers that announce automation, and —
more subtly — re-trigger their step-up challenge when a profile is reopened with a
DIFFERENT fingerprint than the one that established it. `skill_runner.py` already
carried that warning in a comment (#3953):

    "Match the login browser's anti-detection fingerprint (login_browser.py) so the
     replayed session stays trusted — a mismatch re-triggers LinkedIn's step-up."

A comment cannot enforce anything. The args were duplicated in three places
(login_browser.py, skill_runner.py, session_manager.setup_session) and had ALREADY
drifted: setup_session used a bare `chromium.launch(headless=True)` with none of
them, which is a large part of why an automated re-login lands on a checkpoint while
the noVNC login does not.

Every launcher now imports from here. Change the fingerprint in ONE place or not at
all — a partial change silently invalidates device trust on the profiles.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Chrome build advertised by the headed noVNC login. The persistent profile records
# a fingerprint derived from this; reopening the profile with a different UA is one
# of the tells that triggers a re-challenge.
CANONICAL_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --disable-blink-features=AutomationControlled strips the navigator.webdriver tell.
# --no-sandbox / --disable-dev-shm-usage are container requirements, not stealth.
_BASE_ARGS: List[str] = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

# Playwright passes --enable-automation by default, which is the loudest tell there is.
IGNORE_DEFAULT_ARGS: List[str] = ["--enable-automation"]


def launch_args(*, maximized: bool = False) -> List[str]:
    """Chromium args. `maximized` only for the headed noVNC window."""
    args = list(_BASE_ARGS)
    if maximized:
        args.append("--start-maximized")
    return args


def persistent_context_kwargs(*, headless: bool = True, maximized: bool = False) -> Dict[str, Any]:
    """Full kwargs for `chromium.launch_persistent_context(profile_dir, **kwargs)`.

    Callers pass profile_dir positionally. Keep viewport=None for the headed window
    so it fills the noVNC display; headless gets a fixed desktop-sized viewport,
    because a missing/odd viewport is itself a bot signal.
    """
    kwargs: Dict[str, Any] = {
        "headless": headless,
        "args": launch_args(maximized=maximized),
        "ignore_default_args": list(IGNORE_DEFAULT_ARGS),
        "user_agent": CANONICAL_USER_AGENT,
    }
    kwargs["viewport"] = None if not headless else {"width": 1440, "height": 900}
    return kwargs
