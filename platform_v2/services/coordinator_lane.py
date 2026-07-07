"""Coordinator lane — the single owner of dispatch's meta-reasoning model.

One designated, always-warm, SMALL local model performs the linguistic work of
dispatch (parse intent, classify capability, and — Phase 2 — decompose). Routing
DECISIONS stay in code. The model is config-swappable via platform_settings so a
benchmark (Phase 3) can promote a winner with no deploy.

Isolation invariant: the coordinator model MUST be non-GPU-class (small) so the hub
admission gate (department_dispatcher._execute_llm) never sheds it — see model_sizes
+ _SMALL_MODEL_MARKERS.
"""

import time
import logging

logger = logging.getLogger(__name__)

DEFAULT_COORDINATOR_MODEL = "qwen25-classify"
_MODEL_KEY = "dispatch:coordinator_model"
_ENABLED_KEY = "dispatch:coordinator_lane_enabled"

_CACHE: dict = {}
_CACHE_TTL_S = 60.0


def _reset_cache() -> None:
    """Test hook — clear the TTL cache."""
    _CACHE.clear()


def _read_setting(key: str, default: str) -> str:
    """Read a single platform_settings value with an in-code default. Fail-open."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row.get("value") not in (None, ""):
            return str(row["value"])
        return default
    except Exception:
        logger.warning("[coordinator_lane] setting read failed for %s; using default", key, exc_info=True)
        return default


def _cached(key: str, default: str) -> str:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and (now - hit[1]) < _CACHE_TTL_S:
        return hit[0]
    val = _read_setting(key, default)
    _CACHE[key] = (val, now)
    return val


def get_coordinator_model() -> str:
    """The designated coordinator model name (config-driven, TTL-cached).

    Robust to trailing/leading whitespace in the stored config value; an
    empty string after stripping falls back to the hard-coded default.
    """
    value = _cached(_MODEL_KEY, DEFAULT_COORDINATOR_MODEL).strip()
    return value or DEFAULT_COORDINATOR_MODEL


def coordinator_lane_enabled() -> bool:
    """Kill switch — False reverts callers to plain capability routing."""
    return _cached(_ENABLED_KEY, "true").strip().lower() not in ("false", "0", "no", "off")


def _dispatch():
    """Lazy handle to the module-level dispatch() (avoids an import cycle)."""
    from tools.department_hq.services.department_dispatcher import dispatch

    return dispatch


def coordinator_dispatch(capability, prompt, *, module_id="coordinator", json_mode=False, timeout_s=30, **kwargs):
    """Dispatch a lightweight meta-reasoning task through the coordinator lane.

    Enabled  → forces the config-driven coordinator model + pins I.R.I.S.
    Disabled → plain capability routing (today's behavior). Fail-open: any error
    is the caller's to handle via DispatchResult.success (never raises past dispatch()).
    """
    dispatch = _dispatch()
    if coordinator_lane_enabled():
        kwargs.setdefault("model_override", get_coordinator_model())
        kwargs.setdefault("prefer_agent", "I.R.I.S.")
    return dispatch(
        capability,
        prompt,
        module_id=module_id,
        json_mode=json_mode,
        timeout=timeout_s,
        **kwargs,
    )


COORDINATOR_CAPABILITIES = frozenset({"classify", "sentiment", "tagging", "detect_language"})


def should_apply_floor(capability, caller_pinned_model: bool) -> bool:
    """True when the dispatcher should force the coordinator model for this capability.

    A lightweight coordinator capability + lane enabled + the caller did NOT pin a
    model (model_override/prefer_model). Pure except for the config read; fail-open
    via coordinator_lane_enabled()'s own fail-open.
    """
    if caller_pinned_model:
        return False
    if capability not in COORDINATOR_CAPABILITIES:
        return False
    return coordinator_lane_enabled()
