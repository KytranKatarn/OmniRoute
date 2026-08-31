"""Warm-residency PROFILES — the declarative layer (step 2 of the warmboot spec).

Spec: docs/superpowers/specs/2026-08-31-warmboot-residency-profiles-design.md
Step 1 (the observer, services/residency_monitor.py) is already live.

WHAT A PROFILE IS
A statement about what should be RESIDENT — per node, per tier — for a named
workload. That is a DIFFERENT statement from CAPABILITY_NODE_AFFINITY, which says
where work is ROUTED. Routing decides where a request goes; residency decides
what is already warm when it arrives. The 45x cold penalty lives entirely in the
second one (measured: qwen2.5:1.5b 352.2s cold vs 7.5s warm).

WHY IT IS DATA AND NOT CONSTANTS
Today the intent lives in ~70 lines of hand-maintained constants and comments in
department_dispatcher.py. That file itself records the failure mode: the
2026-08-21 rebalance ERODED the #1905 warm-review protection across nine
capabilities. Nothing failed, nothing alarmed, and review success fell to
82%/57% — because the invariant existed only as a comment. A comment cannot be
checked; a row can. (Same precedent as `ship_classes`: tune without a deploy.)

⚠️ THIS MODULE CHANGES NO BEHAVIOUR. Nothing dispatches, warms or evicts from it
yet. It is read by the OBSERVER so that the declared intent and the thing that
checks the intent stop being two separate hand-maintained copies. Activation is
step 3 and is deliberately not here.

⚠️ AN ABSENT OR INVALID SETTING IS NOT AN ERROR. It falls back to literals equal
to today's implicit profile, so an unset key, a typo'd JSON blob or a dead DB all
behave exactly as the platform does now. A residency layer that can break the
fleet by being misconfigured is worse than no residency layer.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "fleet:residency:profiles"
_ACTIVE_KEY = "fleet:residency:active"
_TTL_S = 60.0

# RLock, not Lock: _load() acquires the lock ITSELF so the invariant does not
# depend on every caller remembering to. Callers already inside a `with _lock`
# block would deadlock on a plain Lock. (Review finding, PR #2988 — the guard
# was correct but wired per-caller, which is the same shape as every other
# per-caller guard this fleet has been bitten by.)
_lock = threading.RLock()
_cache: Dict[str, Any] = {"at": 0.0, "profiles": None, "source": None}

# The tiers that actually exist on this fleet. `span` is hub-only: Ollama splits
# a model across the M4000 and the TITAN routinely (measured
# GPULayers:49[Quadro 31, TITAN 18]), and a spanning model consumes headroom on
# BOTH cards at once — which placement does not anticipate today.
VALID_TIERS = ("gpu", "span", "cpu_ram")

# ── FALLBACK = today's implicit profile ─────────────────────────────────────
# Transcribed from department_dispatcher.CAPABILITY_NODE_AFFINITY and its
# comments. Each entry cites the decision that created it so a reader can check
# the claim rather than trust this file.
_FALLBACK_PROFILES: Dict[str, Dict[str, Any]] = {
    "default": {
        "description": "Today's implicit residency, transcribed. No behaviour change.",
        "nodes": {
            "starship_76583490e36955ab": {  # USS-246 Defiant, 8GB
                "reserved_vram_gb": 8.0,
                "reserved_for": "code_review",
                "expect_resident": ["qwen2.5:7b"],
                "why": "#1905 — the Defiant's 8GB is reserved for the warm review "
                "7B; gemma3 6.3GB + 7B ~5GB cannot coexist there.",
            },
            "starship_5501c2766526e746": {  # USS-245 Runabout, 4GB
                # ⚠️ qwen2.5:7b REMOVED 2026-08-31. #5861 made code_review
                # Runabout-FIRST, but that is a ROUTING preference and says
                # nothing about whether the model can be made RESIDENT here.
                # It cannot: 8.0GB required vs a 4GB card, so it falls to CPU
                # and the warm-boot TIMES OUT — measured ready=False after
                # 143,000ms against model_service.py:806's 150000ms lock-timeout
                # return.
                #
                # The residency observer had been reporting this since #2987 on
                # EVERY run — "profile_exceeds_gpu ... qwen2.5:7b (~8.0GB)
                # exceeds gpu_vram_gb=4.0" — and it was declared here anyway.
                # The tool worked; the reading of it did not.
                #
                # llama3.2:3b (5.0 required) is what this node can actually hold
                # warm, and it is in its documented warm set.
                "expect_resident": ["llama3.2:3b"],
                "why": "4GB card — 7B models cannot be resident here (measured "
                "warm-boot timeout). llama3.2:3b is its real warm-set member.",
            },
            "archie-starbase": {  # hub — 12GB largest card / 20GB total / 128GB RAM
                "expect_resident": ["gemma3:12b"],
                "cpu_pinned": ["gemma3:12b"],
                "why": "translate + compliance route here BECAUSE gemma3:12b is "
                "CPU-pinned on the hub's 128GB, keeping it off the 8GB Defiant.",
            },
        },
    },
}

# ⚠️ Citadel is deliberately ABSENT. It was removed from _WTF_CPU_FIRST on
# 2026-08-31 (#6216): can_node_run_model(Citadel,'qwen2.5:7b') is False, and the
# owner settled that it stays the DR warm-standby serving five live products
# rather than carrying an 8GB inference model. A profile that declared residency
# there would re-create the dead hop this fleet just removed.


def _read_setting(key: str):
    """Raw platform_settings read. Returns None on ANY problem — absence and
    failure are the same to the caller, and both mean 'use the fallback'."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            if not row:
                return None
            # RealDictCursor here; index by name, never by position.
            return row["value"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.debug("[residency_profiles] settings read failed for %s: %s", key, exc)
        return None


def validate(raw: Any) -> Tuple[bool, List[str]]:
    """PURE. Returns (ok, errors). No DB, no clock — so it is testable directly.

    Deliberately strict: a half-understood profile is more dangerous than none,
    because it would be applied with confidence. Any error rejects the WHOLE
    blob rather than silently keeping the parts that parsed — a partially
    applied residency plan is a plan nobody wrote.
    """
    errors: List[str] = []
    if not isinstance(raw, dict):
        return False, ["top level must be an object of {profile_name: profile}"]
    if not raw:
        return False, ["no profiles defined"]

    for pname, prof in raw.items():
        if not isinstance(prof, dict):
            errors.append(f"{pname}: profile must be an object")
            continue
        nodes = prof.get("nodes")
        if not isinstance(nodes, dict) or not nodes:
            errors.append(f"{pname}: 'nodes' must be a non-empty object")
            continue
        for node_id, intent in nodes.items():
            # node_id is the VARCHAR remote_nodes.node_id. Passing the int id to
            # a `WHERE node_id = %s` query casts, errors, and aborts the txn —
            # the recurring fleet trap (fleet.md identity invariants).
            if not isinstance(node_id, str) or not node_id.strip():
                errors.append(f"{pname}: node key must be the VARCHAR node_id, got {node_id!r}")
                continue
            if node_id.isdigit():
                errors.append(
                    f"{pname}.{node_id}: looks like the INT remote_nodes.id — "
                    f"use the varchar node_id (e.g. 'archie-starbase')"
                )
            if not isinstance(intent, dict):
                errors.append(f"{pname}.{node_id}: intent must be an object")
                continue
            for field in ("expect_resident", "cpu_pinned"):
                v = intent.get(field, [])
                if not isinstance(v, list) or any(not isinstance(m, str) for m in v):
                    errors.append(f"{pname}.{node_id}.{field}: must be a list of model names")
            rv = intent.get("reserved_vram_gb")
            if rv is not None and not isinstance(rv, (int, float)):
                errors.append(f"{pname}.{node_id}.reserved_vram_gb: must be a number")
            for tier in intent.get("tiers", {}) or {}:
                if tier not in VALID_TIERS:
                    errors.append(f"{pname}.{node_id}: unknown tier {tier!r} (valid: {VALID_TIERS})")
    return (not errors), errors


def _load() -> None:
    """Refresh the cache if stale. Takes _lock ITSELF — safe to call locked or
    unlocked, because the lock is re-entrant."""
    with _lock:
        _load_locked()


def _load_locked() -> None:
    now = time.time()
    if _cache["profiles"] is not None and (now - _cache["at"]) < _TTL_S:
        return

    profiles, source = None, "fallback"
    raw = _read_setting(_SETTINGS_KEY)
    if raw:
        try:
            parsed = raw if isinstance(raw, dict) else json.loads(raw)
            ok, errors = validate(parsed)
            if ok:
                profiles, source = parsed, "platform_settings"
            else:
                # LOUD: a configured-but-invalid profile is an operator mistake
                # that would otherwise be indistinguishable from "not configured".
                logger.warning(
                    "[residency_profiles] %s is INVALID, using fallback: %s",
                    _SETTINGS_KEY,
                    "; ".join(errors[:5]),
                )
        except Exception as exc:
            logger.warning("[residency_profiles] %s unparseable, using fallback: %s", _SETTINGS_KEY, exc)

    if profiles is None:
        profiles = json.loads(json.dumps(_FALLBACK_PROFILES))  # deep copy

    _cache.update(at=now, profiles=profiles, source=source)


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, profiles=None, source=None)


def all_profiles() -> Dict[str, Any]:
    with _lock:
        _load()
        return json.loads(json.dumps(_cache["profiles"]))


def source() -> str:
    """'platform_settings' or 'fallback' — so an operator can tell a configured
    fleet from one that merely looks configured."""
    with _lock:
        _load()
        return _cache["source"] or "fallback"


def active_name() -> str:
    """Which profile is currently declared active. Defaults to 'default'.

    NOTE: nothing ACTS on this yet (step 3). It is readable now so the observer
    reports against the same profile activation will later use.
    """
    name = _read_setting(_ACTIVE_KEY)
    name = (name or "").strip() if isinstance(name, str) else ""
    profs = all_profiles()
    if name and name in profs:
        return name
    if name:
        logger.warning("[residency_profiles] active profile %r is not defined; " "falling back to 'default'", name)
    return "default" if "default" in profs else next(iter(profs), "default")


def nodes_for(profile_name: str = None) -> Dict[str, Any]:
    """node_id -> intent, for the named profile (active profile if omitted).

    This is what the observer consumes. Returns {} for an unknown name rather
    than raising — a missing profile must not take the observer down with it.
    """
    profs = all_profiles()
    name = profile_name or active_name()
    prof = profs.get(name)
    if not isinstance(prof, dict):
        return {}
    return prof.get("nodes") or {}
