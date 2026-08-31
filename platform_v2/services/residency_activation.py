"""Warm-residency ACTIVATION — step 3 of the warmboot spec.

Spec: docs/superpowers/specs/2026-08-31-warmboot-residency-profiles-design.md
  step 1 services/residency_monitor.py    — observe   (merged, #2987)
  step 2 services/residency_profiles.py   — declare   (#2988)
  step 3 THIS FILE                        — act

This is the FIRST step in the warmboot work that changes anything at runtime, so
it is deliberately the smallest possible action with the largest possible number
of refusals in front of it.

WHAT ACTIVATION DOES
Asks each node named by a profile to make its declared models resident, via
model_service.ensure_model_ready() — the platform's OWN loader, the same one
department_dispatcher calls before inference. Not a direct Ollama call (ADR-013).

WHAT IT DELIBERATELY DOES NOT DO
  - It NEVER evicts. Ollama owns eviction; fighting it is how you get thrash.
    Activation only ever ADDS a request, so the worst case of a wrong profile is
    wasted warm-up, never a model pulled out from under live work.
  - It does NOT change routing. CAPABILITY_NODE_AFFINITY still decides where
    work goes; this only changes what is already warm when it arrives.
  - It does NOT pin or reserve VRAM. We influence what is REQUESTED.

⚠️ CAPACITY **AND PRESENCE** ARE BOTH CHECKED BEFORE ASKING. can_node_run_model() gates every request,
so we never queue a load the drain would refuse anyway. That refusal-after-queue
is the documented #5809 waste — a claimed queue slot and a burnt 30s cycle for a
pin that could never be honoured. Refusals are RETURNED, not swallowed: a profile
that cannot be satisfied should be visible, not silently half-applied.

⚠️ TTL IS MANDATORY. A profile that never expires is a permanent reservation,
and a permanent reservation for one workload is how the other workloads starve.
Activation writes an expiry; nothing renews it automatically.
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ACTIVE_KEY = "fleet:residency:active"
_EXPIRES_KEY = "fleet:residency:active_expires"

# A single node's warm-up must not hold the caller. ensure_model_ready blocks
# for a genuine cold load (measured 352s on this fleet), so activation is
# best-effort per model and simply reports what it achieved.
_DEFAULT_TTL_MIN = 90
_MAX_TTL_MIN = 480  # 8h. Beyond this it is not an activation, it is a config change.


def _node_rows() -> Dict[str, Dict[str, Any]]:
    """Online nodes keyed by the VARCHAR node_id (never the int id)."""
    from database import get_db_cursor

    out: Dict[str, Dict[str, Any]] = {}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT node_id, node_name, hostname, status, gpu_available,
                   gpu_vram_gb, ram_gb, extra_capabilities
              FROM remote_nodes
             WHERE status = 'online'
            """
        )
        for row in cur.fetchall():
            d = dict(row)
            out[d["node_id"]] = d
    return out


def _target_host(node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """ensure_model_ready wants {"hostname", "port"} for a node, None for the hub.

    ⚠️ remote_nodes.hostname MUST be an IP, never a DNS name (fleet.md) — a
    hostname that does not resolve from inside the container fails as a timeout,
    which reads as "the model is slow" rather than "the address is wrong".
    """
    if node is None:
        return None  # hub
    host = (node.get("hostname") or "").strip()
    if not host:
        return None
    return {"hostname": host, "port": 11434}


def activate(
    profile_name: Optional[str] = None,
    ttl_minutes: int = _DEFAULT_TTL_MIN,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Request a profile's declared models resident.

    dry_run=True by DEFAULT. The plan is computed, every gate is evaluated and
    the result is reported, but nothing is loaded. A caller that wants the
    behaviour must ask for it explicitly — the first runtime-affecting step in
    this feature should not be something you get by accident.

    Never raises. Returns a report; `ok=False` carries the reason.
    """
    started = time.time()
    report: Dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "profile": None,
        "ttl_minutes": None,
        "requested": [],
        "refused": [],
        "skipped": [],
        "errors": [],
    }
    try:
        from services import residency_profiles as rp

        name = profile_name or rp.active_name()
        report["profile"] = name
        nodes_intent = rp.nodes_for(name)
        if not nodes_intent:
            report.update(ok=False, errors=[f"profile {name!r} declares no nodes"])
            return report

        ttl = max(1, min(int(ttl_minutes or _DEFAULT_TTL_MIN), _MAX_TTL_MIN))
        report["ttl_minutes"] = ttl

        live = _node_rows()
        try:
            from services.fleet_resource_router import (
                can_node_run_model,
                node_has_model,
            )
        except Exception:  # pragma: no cover - router must exist in prod
            can_node_run_model = node_has_model = None

        for node_id, intent in nodes_intent.items():
            node = live.get(node_id)
            if node is None:
                # Offline or retired. Not an error — a profile may legitimately
                # name a node that is currently down.
                report["skipped"].append({"node": node_id, "reason": "not online"})
                continue

            for model in intent.get("expect_resident", []) or []:
                # Gate BEFORE asking (#5809): never queue a load the drain
                # would refuse anyway.
                if can_node_run_model is not None:
                    try:
                        if not can_node_run_model(node, model):
                            report["refused"].append(
                                {
                                    "node": node_id,
                                    "node_name": node.get("node_name"),
                                    "model": model,
                                    "reason": "capacity gate: can_node_run_model=False",
                                }
                            )
                            continue
                    except Exception as exc:  # fail OPEN — a broken gate must
                        # not block residency entirely, but say so.
                        report["errors"].append(f"{node_id}/{model}: capacity check failed ({exc})")

                # PRESENCE, checked separately from capacity (#5862).
                # can_node_run_model answers "could this node hold it"; it says
                # NOTHING about whether the model is pulled there. Measured on
                # this fleet, the two DISAGREE on real nodes:
                #     Citadel     qwen2.5:7b  capacity=False presence=True
                #     Outpost-US  qwen2.5:7b  capacity=False presence=True
                # and #5863 recorded the reverse costing 16 runs / 0 ok /
                # MODEL_NOT_FOUND. Asking a node to warm a model it does not
                # have is a pull, not a warm-up — minutes of bandwidth, not
                # seconds of load, and never what an activation intended.
                #
                # ⚠️ node_has_model is FAIL-OPEN by design: a missing or empty
                # heartbeat inventory returns True, so a stale reading can never
                # starve residency. It only ever refuses on a POSITIVE absence.
                if node_has_model is not None:
                    try:
                        if not node_has_model(node, model):
                            report["refused"].append(
                                {
                                    "node": node_id,
                                    "node_name": node.get("node_name"),
                                    "model": model,
                                    "reason": "presence gate: model not pulled on this node",
                                }
                            )
                            continue
                    except Exception as exc:
                        report["errors"].append(f"{node_id}/{model}: presence check failed ({exc})")

                entry = {
                    "node": node_id,
                    "node_name": node.get("node_name"),
                    "model": model,
                }
                if dry_run:
                    entry["would_request"] = True
                    report["requested"].append(entry)
                    continue

                try:
                    from services.model_service import get_model_service

                    svc = get_model_service()
                    res = svc.ensure_model_ready("residency_activation", model, _target_host(node)) or {}
                    entry.update(
                        ready=bool(res.get("ready")),
                        tier=res.get("tier"),
                        warm_boot_ms=res.get("warm_boot_ms"),
                    )
                except Exception as exc:
                    entry.update(ready=False, error=str(exc)[:200])
                    report["errors"].append(f"{node_id}/{model}: {exc}")
                report["requested"].append(entry)

        if not dry_run:
            _record_active(name, ttl)

        report["elapsed_s"] = round(time.time() - started, 1)
        return report
    except Exception as exc:
        logger.warning("residency_activation: activate failed: %s", exc, exc_info=True)
        report.update(ok=False, errors=report["errors"] + [str(exc)])
        return report


def _record_active(name: str, ttl_minutes: int) -> None:
    """Persist which profile is active and WHEN IT LAPSES.

    Stored as an absolute epoch so a restart cannot silently extend it — a
    duration would restart its own clock and turn a 90-minute activation into a
    permanent one across a restart loop.
    """
    from database import get_db_cursor

    expires = int(time.time()) + ttl_minutes * 60
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            for key, val in ((_ACTIVE_KEY, name), (_EXPIRES_KEY, str(expires))):
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value)
                         VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (key, val),
                )
    except Exception as exc:
        # The warm-up already happened; failing to RECORD it must not look like
        # the activation failed.
        logger.warning("residency_activation: could not record active profile: %s", exc)


def status() -> Dict[str, Any]:
    """Which profile is active, and whether it has lapsed.

    An EXPIRED activation reports active=False while still naming the profile,
    so an operator can tell 'never activated' from 'activated and lapsed'.
    """
    from services import residency_profiles as rp

    name, expires = None, None
    try:
        name = rp._read_setting(_ACTIVE_KEY)
        raw = rp._read_setting(_EXPIRES_KEY)
        expires = int(raw) if raw else None
    except Exception:
        pass

    now = int(time.time())
    lapsed = bool(expires and now >= expires)
    return {
        "profile": name,
        "active": bool(name) and not lapsed,
        "lapsed": lapsed,
        "expires_at": expires,
        "seconds_remaining": max(0, expires - now) if expires else None,
        "profile_source": rp.source(),
    }


def plan(profile_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """The dry-run plan only — convenience for the Fleet tab and for operators
    who want to see what an activation WOULD do before doing it."""
    return activate(profile_name, dry_run=True).get("requested", [])
