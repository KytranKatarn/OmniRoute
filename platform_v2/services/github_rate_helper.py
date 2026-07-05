"""GitHub rate-limit guard for bot/agent writes (Platform Audit #2082).

Bot/agent GitHub writes (F.O.R.G.E. auto-merge, Repair Bay PRs, scan-issue
creation, self-heal pushes, Telegram-approve merges) must not exhaust the
5000/hr core quota or trip GitHub's 403 "secondary rate limit" abuse detector —
either one locks out every bot write for the rest of the window.

This module is the single shared guard:

* ``check_before_write(token=...)`` — call at the top of a write. Returns
  ``(allowed, info)``. Blocks when the core quota is near exhaustion OR a
  secondary-rate-limit cooldown is active.
* ``observe(response, is_write=...)`` — call after every GitHub API response.
  Harvests ``X-RateLimit-*`` headers (free, no quota cost) to keep the cached
  write-bucket quota fresh, and trips the secondary-rate-limit cooldown on a
  403 abuse / 429 response. Read responses only feed the cooldown, never the
  write-bucket counter (reads use a different token = a different bucket).

Design invariants:
* **Fail-open** — any error inside the guard allows the write. The guard must
  never block real work because the guard itself failed.
* **Write-bucket only** — the gated quota reflects the write token's bucket,
  fed by write responses + an authenticated ``/rate_limit`` probe. Read-token
  responses never move the write-bucket counter.
* **Thread-safe** — shared state under a lock; jobs, web threads, and the
  Telegram loop all call this.
"""

import logging
import threading
import time
from typing import Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"

# Hard floor: block writes when the write bucket has fewer than this many core
# requests left, reserving a buffer so a multi-call op (merge = PUT + DELETE)
# can't hit 0 mid-flight. NOT the boot-protocol "> 4000 = push freely" advisory
# (that would waste 80% of the quota if used as a hard gate); that value is the
# soft advisory below.
DEFAULT_MIN_CORE_REMAINING = 200
DEFAULT_ADVISORY_THRESHOLD = 4000
# 403 secondary rate limit ("abuse") pause, per the boot-protocol hygiene rule.
SECONDARY_COOLDOWN_S = 3600.0
# How long a harvested/probed quota reading stays fresh before we re-probe.
CACHE_TTL_S = 30.0

_lock = threading.Lock()
_state: Dict[str, Optional[float]] = {
    "core_remaining": None,  # int (write bucket) or None if unknown
    "core_reset": 0.0,  # epoch seconds when the core bucket resets
    "checked_at": 0.0,  # epoch when core_remaining was last learned
    "secondary_until": 0.0,  # epoch when the secondary-limit cooldown ends
}


def _now() -> float:
    return time.time()


def reset_state() -> None:
    """Clear all cached quota/cooldown state. For tests."""
    with _lock:
        _state.update(core_remaining=None, core_reset=0.0, checked_at=0.0, secondary_until=0.0)


def record_secondary_rate_limit(retry_after: Optional[object] = None) -> None:
    """Start (or extend) the cooldown after a 403 secondary-rate-limit / 429.

    Honours a ``Retry-After`` header (seconds) when present, else a 60-min pause.
    """
    cooldown = SECONDARY_COOLDOWN_S
    if retry_after is not None:
        try:
            cooldown = max(float(retry_after), 1.0)
        except (TypeError, ValueError):
            pass
    with _lock:
        _state["secondary_until"] = max(float(_state["secondary_until"] or 0.0), _now() + cooldown)
    logger.warning("GitHub secondary rate limit — pausing bot writes for ~%.0fs", cooldown)


def observe(response: object, is_write: bool = False) -> None:
    """Harvest rate-limit signal from any GitHub API response. Never raises.

    ``is_write`` responses update the gated write-bucket quota; read responses
    only feed the (token-agnostic) secondary-rate-limit cooldown.
    """
    try:
        if response is None:
            return
        headers = getattr(response, "headers", None) or {}
        status = getattr(response, "status_code", None)

        if is_write:
            rem = headers.get("X-RateLimit-Remaining")
            rst = headers.get("X-RateLimit-Reset")
            with _lock:
                if rem is not None:
                    try:
                        _state["core_remaining"] = int(rem)
                        _state["checked_at"] = _now()
                    except (TypeError, ValueError):
                        pass
                if rst is not None:
                    try:
                        _state["core_reset"] = float(rst)
                    except (TypeError, ValueError):
                        pass

        if status in (403, 429):
            body = ""
            try:
                body = (getattr(response, "text", "") or "").lower()
            except Exception:
                body = ""
            if status == 429 or "secondary rate limit" in body or "abuse" in body:
                record_secondary_rate_limit(headers.get("Retry-After"))
    except Exception:
        logger.debug("github_rate_helper.observe failed", exc_info=True)


def _probe_core(token: Optional[str], timeout: float) -> None:
    """Refresh the write-bucket core quota via /rate_limit (free — not counted).

    Must use the WRITE token so the reading matches the bucket writes consume.
    Unauthenticated probes hit the 60/hr IP bucket and would be misleading, so
    with no token we skip the probe and let check_before_write fail-open.
    """
    if not token:
        return
    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        }
        resp = requests.get(f"{API_BASE}/rate_limit", headers=headers, timeout=timeout)
        if resp.status_code < 300:
            core = ((resp.json() or {}).get("resources") or {}).get("core") or {}
            with _lock:
                if "remaining" in core:
                    _state["core_remaining"] = int(core["remaining"])
                if "reset" in core:
                    _state["core_reset"] = float(core["reset"])
                _state["checked_at"] = _now()
    except Exception:
        logger.debug("github_rate_helper._probe_core failed", exc_info=True)


def check_before_write(
    token: Optional[str] = None,
    min_remaining: Optional[int] = None,
    advisory_threshold: int = DEFAULT_ADVISORY_THRESHOLD,
    timeout: float = 8.0,
) -> Tuple[bool, Dict]:
    """Gate a GitHub write. Returns ``(allowed, info)``; fail-open on any error.

    Blocks when a secondary-rate-limit cooldown is active, or the write bucket
    has < ``min_remaining`` core requests left (unless the reset time has already
    elapsed). Callers should skip/defer the write when ``allowed`` is False and
    surface ``info`` to the user.
    """
    floor = DEFAULT_MIN_CORE_REMAINING if min_remaining is None else min_remaining
    try:
        now = _now()
        with _lock:
            secondary_until = float(_state["secondary_until"] or 0.0)
            remaining = _state["core_remaining"]
            reset = float(_state["core_reset"] or 0.0)
            checked_at = float(_state["checked_at"] or 0.0)

        # 1) Secondary (abuse) rate-limit cooldown — hard block regardless of core.
        if now < secondary_until:
            return False, {
                "allowed": False,
                "reason": "secondary_rate_limit_cooldown",
                "retry_after_s": round(secondary_until - now),
            }

        # 2) Refresh the write-bucket reading if we have none or it's stale.
        if remaining is None or (now - checked_at) > CACHE_TTL_S:
            _probe_core(token, timeout)
            with _lock:
                remaining = _state["core_remaining"]
                reset = float(_state["core_reset"] or 0.0)

        # 3) Unknown after a probe attempt → fail-open (never block on no data).
        if remaining is None:
            return True, {"allowed": True, "reason": "rate_unknown_fail_open"}

        # 4) Bucket spent but its reset time has already passed → treat as replenished.
        if remaining < floor and reset and now >= reset:
            return True, {
                "allowed": True,
                "reason": "quota_reset_elapsed",
                "remaining": remaining,
            }

        # 5) Hard block near exhaustion.
        if remaining < floor:
            info = {
                "allowed": False,
                "reason": "core_quota_low",
                "remaining": remaining,
                "min_remaining": floor,
                "reset_in_s": round(max(reset - now, 0)) if reset else None,
            }
            logger.warning(
                "GitHub write blocked: core quota %s < floor %s (reset in %ss)",
                remaining,
                floor,
                info["reset_in_s"],
            )
            return False, info

        # 6) Allowed — attach a soft advisory when below the boot-protocol threshold.
        info = {"allowed": True, "remaining": remaining}
        if remaining < advisory_threshold:
            info["advisory"] = f"core remaining {remaining} < {advisory_threshold}"
            logger.warning("GitHub core quota advisory: %s remaining", remaining)
        return True, info
    except Exception:
        logger.debug("github_rate_helper.check_before_write failed — fail-open", exc_info=True)
        return True, {"allowed": True, "reason": "guard_error_fail_open"}


def status() -> Dict:
    """Snapshot of current guard state (for diagnostics / an admin endpoint)."""
    now = _now()
    with _lock:
        secondary_until = float(_state["secondary_until"] or 0.0)
        return {
            "core_remaining": _state["core_remaining"],
            "core_reset_epoch": _state["core_reset"],
            "checked_at_epoch": _state["checked_at"],
            "secondary_cooldown_active": now < secondary_until,
            "secondary_retry_after_s": round(max(secondary_until - now, 0)),
        }
