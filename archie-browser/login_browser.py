"""Headed browser runner for the ONE-TIME human login (#3953).

Launched as a child process by login_app.py with DISPLAY pointing at the
sidecar's Xvfb. Opens the persistent profile HEADED so the owner (via noVNC)
can complete LinkedIn login + any 2FA/step-up. The profile dir then carries
the trusted device fingerprint that the headless worker replays.

Exits cleanly on SIGTERM (login_app /stop or idle timeout) so Chromium
flushes the profile to disk.
"""
import os
import signal
import sys
import threading

from playwright.sync_api import sync_playwright

_stop = threading.Event()


def _on_term(_sig, _frm):
    _stop.set()


def _export_state_to_vault(context) -> None:
    """#4006 capture-to-vault — push the freshly-captured storage_state into
    the hub's encrypted browser_sessions store so the S.C.O.U.T. vault and the
    4h health probe see the session immediately (not only after the first
    skill run). Strictly best-effort: the persistent profile on disk is the
    primary artifact; any failure here is logged (type only, no payload/exc
    string) and never blocks context.close(). Must finish well under
    login_app's 20s SIGKILL deadline — 5s HTTP timeout."""
    hub = os.getenv("PLATFORM_INTERNAL_URL", "").rstrip("/")
    token = os.getenv("INTERNAL_API_KEY", "")
    agent_id = os.getenv("LOGIN_AGENT_ID", "")
    platform = os.getenv("LOGIN_PLATFORM", "")
    if not (hub and token and agent_id and platform):
        return
    try:
        import requests

        state = context.storage_state()
        r = requests.post(
            f"{hub}/api/internal/sessions/{agent_id}/{platform}/state",
            json={"state": state},
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        print(f"[login_browser] vault export {agent_id}/{platform}: HTTP {r.status_code}", file=sys.stderr)
    except Exception as exc:
        print(
            f"[login_browser] vault export failed (non-fatal): {type(exc).__name__}",
            file=sys.stderr,
        )


def main() -> int:
    profile_dir = sys.argv[1]
    start_url = sys.argv[2] if len(sys.argv) > 2 else "https://www.linkedin.com/login"
    os.makedirs(profile_dir, exist_ok=True)

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    with sync_playwright() as p:
        # Anti-detection: LinkedIn/Google block logins from browsers that
        # announce automation ("this browser may not be secure"). Strip the
        # navigator.webdriver tell + the --enable-automation default arg so
        # the headed login looks like a normal Chrome. (KB #272122 / #3953)
        #
        # These args now live in browser_fingerprint so the automated re-login
        # (session_manager.setup_session) and the skill runner reopen this profile
        # with the IDENTICAL fingerprint. They had already drifted apart, and a
        # mismatch re-triggers LinkedIn's step-up on a profile this login trusted.
        import browser_fingerprint

        context = p.chromium.launch_persistent_context(
            profile_dir,
            # headed under Xvfb — the human logs in via noVNC
            **browser_fingerprint.persistent_context_kwargs(headless=False, maximized=True),
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            # Idle until /stop, idle-timeout, or the human closes the window.
            while not _stop.is_set():
                if not context.pages:  # all windows closed by the user
                    break
                _stop.wait(2)
            _export_state_to_vault(context)
        finally:
            context.close()  # flushes cookies/localStorage/fingerprint to disk
    return 0


if __name__ == "__main__":
    sys.exit(main())
