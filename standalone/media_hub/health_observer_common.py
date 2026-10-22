"""Shared helpers for Media Hub's scheduled health probes."""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger("media_hub.observer")

_last_diagnostic: dict = {"overall": "unknown", "summary": {}, "generated_at": None, "errors": []}
_seen_grab_ids: set = set()

def _decrypt(key_encrypted: Optional[str]) -> str:
    if not key_encrypted:
        return ""
    from tools.media_hub.encryption import decrypt_api_key  # lazy

    try:
        return decrypt_api_key(key_encrypted)
    except Exception as e:
        log.error("decrypt_api_key failed: %s", e)
        return ""

def _services_rows():
    """Yield enabled service rows. Own DB connection so observer is
    independent of Flask app context (APScheduler threads have none)."""
    from database import get_db_cursor

    with get_db_cursor(cursor_factory=None) as (_conn, cur):
        cur.execute(
            """
            SELECT id, service_type, name, host, port, use_ssl,
                   api_key_encrypted, health_status
            FROM media_hub_services
            WHERE is_enabled = TRUE
            ORDER BY service_type
            """
        )
        return cur.fetchall()

def _write_health(service_id: int, status: str, message: str) -> None:
    from database import get_db_cursor

    with get_db_cursor(cursor_factory=None, commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE media_hub_services
               SET health_status = %s,
                   health_message = %s,
                   last_health_check = CURRENT_TIMESTAMP
             WHERE id = %s
            """,
            (status, message[:500], service_id),
        )

def _arr_health(stype: str, host: str, port: int, api_key: str, use_ssl: bool):
    """GET /api/v3/health on Sonarr/Radarr. Returns list of warnings/errors."""
    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/api/v3/health"
    try:
        r = requests.get(url, headers={"X-Api-Key": api_key}, timeout=8)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as e:
        return None, str(e)

def _prowlarr_indexer_status(host: str, port: int, api_key: str, use_ssl: bool):
    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/api/v1/indexerstatus"
    try:
        r = requests.get(url, headers={"X-Api-Key": api_key}, timeout=8)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as e:
        return None, str(e)

def _log_selfheal(probe: str, capability: str, actions: list) -> None:
    """Record an autonomous self-heal in the DHQ A.R.M.A.D.A. dispatch feed
    (#4757) — one 0-token task_execution_log row per probe run that actually
    took a corrective action. No-op when the probe only observed or escalated
    without fixing (empty actions). Best-effort; never breaks the probe."""
    if not actions:
        return
    try:
        from archie_coordination import log_dispatch

        log_dispatch(
            probe,
            capability=capability,
            description=f"{probe}: " + "; ".join(str(a) for a in actions),
            success=True,
            metadata={"actions": list(actions)},
        )
    except Exception:  # noqa: BLE001 — visibility logging must never break a probe
        pass

def _arr_command(
    base: str,
    payload: dict,
    *,
    headers: dict = None,
    params: dict = None,
    verify_seconds: int = 8,
) -> "tuple[bool, str]":
    """Fire a Sonarr/Radarr command and report WHAT ACTUALLY HAPPENED.

    #5383. Every command call site used to be::

        requests.post(f"{base}/command?apikey={key}", json={...}, timeout=10)
        actions.append("triggered ...")

    The response was discarded, so a rejected command still appended a success
    line. ``download_pipeline_probe`` therefore reported that it had healed the
    pipeline every 30 minutes for 20 days while the command failed instantly
    each time. A self-heal that cannot fail is not a self-heal — it is a lie
    with a cron schedule.

    Two things are checked, because they fail differently:
      1. the POST itself (a rejected command answers non-2xx immediately), and
      2. the command's OUTCOME — *arr accepts a command, queues it, and only
         then fails. `{"status": "failed", "exception": ...}` on the command
         record is the only place the real reason appears, which is why this
         polls instead of trusting the 201.

    Deliberately does NOT guess at missing parameters (e.g. whether a given
    scan needs a ``path``). It surfaces *arr's own error so the next reader
    diagnoses from evidence rather than from a guess.

    Returns ``(ok, detail)``. ``detail`` is always safe to put in an alert.
    """
    try:
        resp = requests.post(
            f"{base}/command", json=payload, headers=headers, params=params, timeout=10
        )
    except Exception as e:  # network/timeout — the command definitely did not run
        return False, f"request failed: {e}"

    if not resp.ok:
        body = (resp.text or "")[:200].replace("\n", " ")
        return False, f"HTTP {resp.status_code}: {body}"

    try:
        cmd_id = (resp.json() or {}).get("id")
    except Exception:
        cmd_id = None
    if not cmd_id:
        # Accepted, but there is nothing to verify against. Say exactly that
        # rather than implying the work completed.
        return True, "accepted (no command id returned — outcome unverified)"

    deadline = _time.time() + verify_seconds
    last = "queued"
    while _time.time() < deadline:
        _time.sleep(1)
        try:
            c = requests.get(
                f"{base}/command/{cmd_id}", headers=headers, params=params, timeout=10
            ).json()
        except Exception as e:
            return True, f"accepted, status check failed ({e}) — outcome unverified"
        last = (c.get("status") or "").lower()
        if last == "failed":
            why = c.get("exception") or c.get("message") or "no reason given"
            return False, f"command failed: {str(why)[:200]}"
        if last in ("completed", "aborted"):
            return (last == "completed"), f"command {last}"
    return True, f"accepted, still {last} after {verify_seconds}s — outcome unverified"

def _orch_windows_enabled() -> bool:
    """Kill-switch for the VRAM-evicting opportunity windows (they briefly displace a
    node's inference). Default ON; set TDARR_OPPORTUNITY_WINDOWS=0 to fall back to pure
    yield (never lease) without a redeploy."""
    import os

    return os.getenv("TDARR_OPPORTUNITY_WINDOWS", "1").strip().lower() not in ("0", "false", "no", "off")

def _orch_window_max_pressure() -> int:
    """Welfare gate (#4766): the max fleet INFERENCE PRESSURE at which an opportunity
    window may still be granted. A window EVICTS a node's inference models, so above this
    threshold we must NOT grant one — inference welfare comes first (the plain per-node
    yield still lets transcodes fill genuinely idle GPU time). Env-tunable
    TDARR_WINDOW_MAX_PRESSURE (default 6); 0 = never window while ANY inference is active."""
    import os

    try:
        return max(0, int(os.getenv("TDARR_WINDOW_MAX_PRESSURE", "6")))
    except (TypeError, ValueError):
        return 6

def _orch_release(node, st, fleet_gpu_lease, tdarr_client, actions, reason):
    """Release a node's VRAM lease (reload its Ollama models) if one is held. Best-effort."""
    models = st.get("leased_models") or []
    if models and st.get("fleet_node_id"):
        fleet_gpu_lease(st["fleet_node_id"], "release", models)
        actions.append(f"released VRAM lease on {node} — reloading {len(models)} model(s) ({reason})")
    st["leased_models"] = []
    st["window_until"] = None

__all__ = [name for name in globals() if not name.startswith("__")]
