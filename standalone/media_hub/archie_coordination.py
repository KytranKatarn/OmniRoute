"""
A.R.C.H.I.E. coordination helper (Media Hub / M.A.V.E.N.)
========================================================
M.A.V.E.N. reaches Kytran ONLY through A.R.C.H.I.E. — never as itself. This is the
single outbound path from the standalone to the hub (project #385 Phase 1):

  notify_archie(title, message, priority, telegram)
      -> a platform notification (+ Telegram in A.R.C.H.I.E.'s voice for
         high/urgent priority, or when telegram=True).

  request_approval(title, reason, payload) -> approval_id | None
      -> a Tier-2 approval (Telegram Approve/Deny). Used for DESTRUCTIVE / major
         actions (delete download/request, remove/replace a file, a re-encode that
         replaces the original). The standalone polls check_approval() and only
         executes locally once it flips to 'approved' — the hub cannot reach
         Radarr / SABnzbd / Tdarr, so execution stays here.

  check_approval(approval_id) -> 'pending' | 'approved' | 'denied' | ... | None

Transport is mesh-only: ARCHIE_HUB_URL defaults to the Headscale hub
(http://100.64.0.4:3000), authed with Bearer ARCHIE_INTERNAL_API_KEY (= the
platform INTERNAL_API_KEY). Every call is best-effort and NEVER raises — a hub
outage must not break a probe; the stdout log is the fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger("media_hub.archie")

# Mesh IP by default — NEVER the public CDN hostname (60s cap, bypasses the queue,
# hides from task_execution_log). See feedback_dhq-mesh-routing-mandate.
_DEFAULT_HUB = "http://100.64.0.4:3000"


def _hub() -> str:
    return (os.getenv("ARCHIE_HUB_URL") or _DEFAULT_HUB).rstrip("/")


def _headers() -> Optional[dict]:
    key = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else None


def notify_archie(
    title: str,
    message: str,
    priority: str = "normal",
    source: str = "media_hub_maven",
    telegram: Optional[bool] = None,
) -> bool:
    """Send a notification through A.R.C.H.I.E. Returns True on 2xx. Never raises.

    high/urgent priority also reaches Kytran on Telegram (in A.R.C.H.I.E.'s voice);
    pass telegram=True to force it at any priority, telegram=False to suppress.
    """
    h = _headers()
    if not h:
        log.warning("notify_archie: ARCHIE_INTERNAL_API_KEY unset — cannot reach hub (%s)", title)
        return False
    body = {"title": title, "message": message, "priority": priority, "source": source}
    if telegram is not None:
        body["telegram"] = bool(telegram)
    try:
        r = requests.post(f"{_hub()}/api/internal/notify", json=body, headers=h, timeout=6)
        if not r.ok:
            log.warning("notify_archie non-2xx (%s): %s", r.status_code, title)
        return r.ok
    except Exception as exc:  # noqa: BLE001 — best-effort, hub outage must not break a probe
        log.warning("notify_archie failed (%s) — %s", title, exc)
        return False


def request_approval(title: str, reason: str, payload: Optional[dict] = None) -> Optional[int]:
    """Raise a Tier-2 Telegram approval for a destructive/major action.

    Returns the approval_id (int) to poll, or None on failure / a pending
    duplicate (the hub dedups one media_hub_action at a time). Never raises.
    """
    h = _headers()
    if not h:
        log.warning("request_approval: ARCHIE_INTERNAL_API_KEY unset (%s)", title)
        return None
    try:
        r = requests.post(
            f"{_hub()}/api/internal/approval-request",
            json={"title": title, "reason": reason, "payload": payload or {}},
            headers=h,
            timeout=8,
        )
        if r.ok:
            return (r.json() or {}).get("approval_id")
        log.warning("request_approval non-2xx (%s): %s %s", title, r.status_code, r.text[:120])
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("request_approval failed (%s) — %s", title, exc)
        return None


def check_approval(approval_id: Optional[int]) -> Optional[str]:
    """Poll an approval's status ('pending'|'approved'|'denied'|...). None on error."""
    h = _headers()
    if not h or not approval_id:
        return None
    try:
        r = requests.get(f"{_hub()}/api/internal/approval/{approval_id}", headers=h, timeout=6)
        if r.ok:
            return (r.json() or {}).get("status")
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("check_approval failed (%s) — %s", approval_id, exc)
        return None
