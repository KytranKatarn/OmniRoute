"""Slice 2 — fetch the LinkedIn email verification code, so a re-login can clear
its own challenge instead of dead-ending at a screenshot.

WHY OVER HTTP: archie_browser is a separate container with no platform_v2 on its
path and no Google OAuth tokens. The hub already owns the connected Gmail accounts
(`google_accounts`) and `gmail_service.search_emails`. So the browser asks the hub
for a code the same way `login_browser._export_state_to_vault` pushes state back —
Bearer INTERNAL_API_KEY over the internal URL. No mail credentials ever reach this
container.

WHY GMAIL AND NOT STALWART: the LinkedIn logins are registered to
kytranempowerment@gmail.com / terry.p.caetano@gmail.com. Stalwart hosts
@kytranempowerment.com and never receives these messages — pointing this at Stalwart
would poll an empty mailbox forever and look like "LinkedIn stopped sending codes".
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# LinkedIn delivers the code within seconds, but the Gmail sync the hub reads is not
# instantaneous. Poll rather than single-shot; give up quietly and let the caller
# fall back to the noVNC handoff.
_POLL_TIMEOUT_S = int(os.getenv("LINKEDIN_CODE_TIMEOUT_S", "90"))
_POLL_INTERVAL_S = 5


def fetch_verification_code(login_email: str, *, not_before: Optional[float] = None) -> Optional[str]:
    """Return a 6-digit LinkedIn verification code for `login_email`, or None.

    `not_before` is a unix timestamp — only codes from mail that arrived AFTER it are
    accepted. This is load-bearing: LinkedIn reuses the same subject line for every
    challenge, so without it a STALE code from a previous attempt is returned, fails,
    and burns one of the limited attempts. Callers should stamp it immediately before
    submitting the password.
    """
    # ⚠️ TWO NAMES FOR ONE THING. The login sidecar (archie_browser_login) is given
    # PLATFORM_INTERNAL_URL; this container (archie_browser) is given
    # ARCHIE_PLATFORM_URL. Reading only the former means the auto-code lookup is a
    # permanent silent no-op HERE while working fine in the sidecar — accept both.
    hub = (os.getenv("PLATFORM_INTERNAL_URL") or os.getenv("ARCHIE_PLATFORM_URL") or "").rstrip("/")
    token = os.getenv("INTERNAL_API_KEY", "")
    if not (hub and token and login_email):
        logger.warning("[challenge-code] not configured (hub/token/login missing) — skipping auto-code")
        return None

    import requests

    deadline = time.time() + _POLL_TIMEOUT_S
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            resp = requests.get(
                f"{hub}/api/internal/linkedin/challenge-code",
                params={"login": login_email, "not_before": int(not_before or 0)},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                code = (resp.json() or {}).get("code")
                if code:
                    logger.info("[challenge-code] got code for %s on attempt %d", login_email, attempt)
                    return str(code)
            elif resp.status_code == 404:
                pass  # no matching mail yet — expected on early polls
            else:
                # Type/status only; never log a response body that may hold the code.
                logger.warning("[challenge-code] hub returned HTTP %s", resp.status_code)
        except Exception as exc:
            logger.warning("[challenge-code] fetch failed: %s", type(exc).__name__)

        time.sleep(_POLL_INTERVAL_S)

    logger.warning("[challenge-code] no code for %s within %ss — noVNC handoff required",
                   login_email, _POLL_TIMEOUT_S)
    return None
