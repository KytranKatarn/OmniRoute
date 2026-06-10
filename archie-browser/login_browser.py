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


def main() -> int:
    profile_dir = sys.argv[1]
    start_url = sys.argv[2] if len(sys.argv) > 2 else "https://www.linkedin.com/login"
    os.makedirs(profile_dir, exist_ok=True)

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,  # headed under Xvfb — the human logs in via noVNC
            args=["--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"],
            viewport=None,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            # Idle until /stop, idle-timeout, or the human closes the window.
            while not _stop.is_set():
                if not context.pages:  # all windows closed by the user
                    break
                _stop.wait(2)
        finally:
            context.close()  # flushes cookies/localStorage/fingerprint to disk
    return 0


if __name__ == "__main__":
    sys.exit(main())
