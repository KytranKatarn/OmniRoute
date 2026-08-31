"""Warm-residency observer — REPORTING ONLY (step 1 of the warmboot spec).

Spec: docs/superpowers/specs/2026-08-31-warmboot-residency-profiles-design.md

WHY
Cold residency costs 45x (measured: qwen2.5:1.5b 352.2s cold vs 7.5s warm), which
dwarfs every other tuning lever. The platform already plans warm residency in
three places — A.R.M.A.D.A.'s per-node provision-warm-set, the dispatcher's
per-capability CAPABILITY_NODE_AFFINITY, and warmup_fleet_models()' keep-alive
pings — but the INTENT lives in hand-maintained constants and code comments,
so nothing can detect when reality diverges from it.

It has diverged before, silently: department_dispatcher.py records that the
2026-08-21 rebalance ERODED the #1905 warm-review protection across nine
capabilities. Nothing failed and nothing alarmed, because the invariant existed
only as a comment; it surfaced as review success falling to 82%/57%.

WHAT THIS DOES — AND DELIBERATELY DOES NOT
Reports. It changes no routing, loads no model, evicts nothing, and raises no
alert. Per the spec's observer-first sequencing, if this cannot accurately
describe today's IMPLICIT profile then the model is wrong and nothing further
should be built on it.

⚠️ A SNAPSHOT IS NOT A VERDICT. Models load on demand, so a model absent right
now may simply mean nothing asked for it recently. Distinguishing "transiently
absent" from "persistently evicted" needs observation ACROSS CYCLES — which is
why findings carry a `confidence` and why `absent` is never reported as a fault
from a single reading.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A model_load_state row older than this is a stale reading, not evidence of
# residency. The fleet job refreshes every ~5 min; 30 min is generous.
_STALE_READING_MINUTES = 30

# Ollama's KEEP_ALIVE is 60m on every node (see ai-bridge.md). A model absent
# for less than that could simply be idle, not evicted.
_KEEP_ALIVE_MINUTES = 60


# ── the implicit profile ────────────────────────────────────────────────────
# Derived from what the CODE already asserts, not invented here. Each entry
# cites the decision that created it, so a reader can check the claim.
#
# ⚠️ This is a DESCRIPTION of current intent, transcribed by hand from
# department_dispatcher.CAPABILITY_NODE_AFFINITY and its comments. Step 2 of the
# spec replaces it with platform_settings data. Until then, if the dispatcher
# changes and this does not, THIS file is the stale one.
IMPLICIT_PROFILE: Dict[str, Dict[str, Any]] = {
    "starship_76583490e36955ab": {  # USS-246 Defiant, 8GB
        "reserved_vram_gb": 8.0,
        "reserved_for": "code_review",
        "expect_resident": ["qwen2.5:7b"],
        "why": "#1905 — the Defiant's 8GB is reserved for the warm review 7B; "
        "gemma3 6.3GB + 7B ~5GB cannot coexist there.",
    },
    "starship_5501c2766526e746": {  # USS-245 Runabout, 4GB
        "expect_resident": ["qwen2.5:7b"],
        "why": "#5861 — code_review is Runabout-FIRST; it served both review "
        "models at 100% when that change was made.",
    },
    "archie-starbase": {  # hub, 12GB largest card / 20GB total
        "expect_resident": ["gemma3:12b"],
        "cpu_pinned": ["gemma3:12b"],
        "why": "translate + compliance route here BECAUSE gemma3:12b is "
        "CPU-pinned on the hub's 128GB — keeping it off the 8GB Defiant.",
    },
    "outpost_e834ff6949a3d7a6": {  # Citadel
        "expect_resident": ["qwen2.5:7b"],
        "why": "_WTF_CPU_FIRST — WTF fact_check/bias prefer Citadel CPU first.",
    },
}


def _minutes(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def derive_findings(
    declared: Dict[str, Dict[str, Any]], actual: Dict[str, List[Dict[str, Any]]], nodes: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """PURE. No DB, no Flask, no clock — so it is testable and cannot drift.

    declared: node_id -> intent (IMPLICIT_PROFILE shape)
    actual:   node_id -> [{model_name, tier, size_gb, age_minutes}, ...]
    nodes:    node_id -> {node_name, status, gpu_vram_gb, ram_gb, max_model_gb,
                          max_concurrent}
    """
    findings: List[Dict[str, Any]] = []

    for node_id, intent in declared.items():
        node = nodes.get(node_id)
        if not node:
            findings.append(
                {
                    "kind": "node_missing",
                    "node_id": node_id,
                    "severity": "info",
                    "confidence": "certain",
                    "detail": "profile names a node that is not in remote_nodes",
                }
            )
            continue

        # A retired/offline node cannot hold anything — that is not a fault.
        if (node.get("status") or "").lower() != "online":
            findings.append(
                {
                    "kind": "node_offline",
                    "node_id": node_id,
                    "node_name": node.get("node_name"),
                    "severity": "info",
                    "confidence": "certain",
                    "detail": f"node is {node.get('status')}; residency not evaluated",
                }
            )
            continue

        rows = actual.get(node_id) or []
        fresh = [r for r in rows if (_minutes(r.get("age_minutes")) or 1e9) <= _STALE_READING_MINUTES]
        present = {r.get("model_name") for r in fresh}

        # ── 1. declared-resident model absent ──────────────────────────────
        # Reported as an OBSERVATION, never a fault: on-demand loading means a
        # single absent reading proves nothing. Confidence reflects that.
        for want in intent.get("expect_resident", []):
            if want not in present:
                findings.append(
                    {
                        "kind": "expected_model_absent",
                        "node_id": node_id,
                        "node_name": node.get("node_name"),
                        "model": want,
                        "severity": "observation",
                        "confidence": "single_reading",
                        "detail": (
                            f"{want} not resident now. NOT a fault from one "
                            f"reading — needs {_KEEP_ALIVE_MINUTES}m+ of "
                            f"consecutive absence to distinguish eviction "
                            f"from idle."
                        ),
                        "why_declared": intent.get("why"),
                    }
                )

        # ── 2. a RESERVED tier occupied by something else ──────────────────
        # This is the #1905 erosion signature and the reason this file exists.
        reserved = intent.get("reserved_vram_gb")
        if reserved:
            expected = set(intent.get("expect_resident", []))
            squatters = [r for r in fresh if r.get("tier") == "gpu" and r.get("model_name") not in expected]
            if squatters:
                used = sum(float(r.get("size_gb") or 0) for r in squatters)
                findings.append(
                    {
                        "kind": "reserved_tier_occupied",
                        "node_id": node_id,
                        "node_name": node.get("node_name"),
                        "severity": "observation",
                        "confidence": "certain",
                        "detail": (
                            f"{reserved}GB reserved for "
                            f"{intent.get('reserved_for')}, but GPU holds "
                            + ", ".join(f"{r['model_name']} ({r.get('size_gb')}GB)" for r in squatters)
                            + f" = {used:.1f}GB of foreign residency"
                        ),
                        "why_declared": intent.get("why"),
                    }
                )

        # ── 3. UNSATISFIABLE profile — the check nothing does today ────────
        # Ties the capacity knobs to the residency intent. A max_model_gb or
        # gpu_vram_gb change made elsewhere is exactly how #1905 eroded.
        cap = _minutes(node.get("max_model_gb"))
        vram = _minutes(node.get("gpu_vram_gb"))
        for want in intent.get("expect_resident", []):
            need = _model_size_gb(want)
            if need is None:
                continue
            if cap is not None and need > cap:
                findings.append(
                    {
                        "kind": "profile_unsatisfiable",
                        "node_id": node_id,
                        "node_name": node.get("node_name"),
                        "model": want,
                        "severity": "warning",
                        "confidence": "certain",
                        "detail": (
                            f"profile expects {want} (~{need}GB) but the node's "
                            f"max_model_gb={cap} disqualifies it — the "
                            f"capacity knob contradicts the residency intent"
                        ),
                        "why_declared": intent.get("why"),
                    }
                )
            elif want not in intent.get("cpu_pinned", []) and vram is not None and need > vram:
                findings.append(
                    {
                        "kind": "profile_exceeds_gpu",
                        "node_id": node_id,
                        "node_name": node.get("node_name"),
                        "model": want,
                        "severity": "observation",
                        "confidence": "certain",
                        "detail": (
                            f"{want} (~{need}GB) exceeds gpu_vram_gb={vram} "
                            f"(largest single card) — it can only be CPU-"
                            f"resident here, which may be intended"
                        ),
                        "why_declared": intent.get("why"),
                    }
                )

    # ── 4. MULTI-CARD accounting — recorded, then ignored ──────────────────
    # The hub has TWO cards (Quadro M4000 8GB + TITAN X 12GB = 20GB) and
    # remote_nodes.extra_capabilities.gpu_vram_total_gb faithfully records 20.
    # Verified 2026-08-31: the ONLY reference to that key in all of platform_v2
    # is a COMMENT. No code reads it. So every placement and residency decision
    # sizes against gpu_vram_gb=12 (the largest SINGLE card) and the second card
    # is invisible.
    #
    # That single-card value is the CORRECT safety input for sizing ONE model
    # (_fits(), get_agents_for_hardware()), and must stay. But it is the WRONG
    # input for a residency BUDGET, which is about several models coexisting.
    # Nothing computes that budget today.
    #
    # ⚠️ Ollama also SPANS cards routinely on this host (measured:
    # GPULayers:49[Quadro 31, TITAN 18]), and a spanning model consumes headroom
    # on BOTH at once — which is how hub VRAM budget hit 0.0GB on 2026-08-15 and
    # forced qwen2.5:7b onto CPU. Placement does not anticipate this.
    for node_id, node in nodes.items():
        if (node.get("status") or "").lower() != "online":
            continue
        total = _minutes(node.get("gpu_vram_total_gb"))
        largest = _minutes(node.get("gpu_vram_gb"))
        if total is None or largest is None or total <= largest:
            continue  # single-card node, or no total declared — nothing to say
        resident = [
            r
            for r in (actual.get(node_id) or [])
            if r.get("tier") == "gpu" and (_minutes(r.get("age_minutes")) or 1e9) <= _STALE_READING_MINUTES
        ]
        used = sum(float(r.get("size_gb") or 0) for r in resident)
        findings.append(
            {
                "kind": "multi_card_unaccounted",
                "node_id": node_id,
                "node_name": node.get("node_name"),
                "severity": "warning",
                "confidence": "certain",
                "detail": (
                    f"{len(resident)} GPU-resident model(s) using {used:.1f}GB. "
                    f"Node declares gpu_vram_total_gb={total} across multiple cards, "
                    f"but every decision sizes against gpu_vram_gb={largest} (largest "
                    f"single card) and NO code reads the total — so {total - largest:.0f}GB "
                    f"is invisible to placement. Per-card residency is not tracked at "
                    f"all: model_load_state has no card dimension, so which card holds "
                    f"what — and each card's real headroom — is unknown."
                ),
                "models_resident": [
                    {"model": r.get("model_name"), "size_gb": float(r.get("size_gb") or 0)} for r in resident
                ],
            }
        )

    return findings


def _model_size_gb(model: str) -> Optional[float]:
    """Runtime footprint. Uses services.model_sizes — the SSOT — not a guess."""
    try:
        from services.model_sizes import lookup

        f = lookup(model)
        return max(float(f.vram_gb), float(f.ram_gb))
    except Exception:
        return None


# ── DB layer ────────────────────────────────────────────────────────────────
def _load_actual() -> Dict[str, List[Dict[str, Any]]]:
    """What is resident RIGHT NOW, keyed by node_id (varchar).

    ⚠️ model_load_state stores node_db_id — the INT remote_nodes.id — while every
    routing surface uses the VARCHAR node_id. Joining the wrong one is the
    recurring fleet trap (a varchar->int cast aborts the txn). Join on r.id.
    ⚠️ saved_at is `timestamp WITHOUT time zone`, deviating from the platform's
    TIMESTAMPTZ convention, so the age is computed in SQL — subtracting it from
    an aware now() in Python raises TypeError.
    """
    from database import get_db_cursor

    out: Dict[str, List[Dict[str, Any]]] = {}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT COALESCE(r.node_id, 'archie-starbase') AS node_id,
                   m.model_name, m.tier, m.size_gb,
                   EXTRACT(EPOCH FROM (now() AT TIME ZONE 'UTC' - m.saved_at))/60.0
                       AS age_minutes
              FROM model_load_state m
              LEFT JOIN remote_nodes r ON r.id = m.node_db_id
            """
        )
        for row in cur.fetchall():
            d = dict(row)
            out.setdefault(d["node_id"], []).append(d)
    return out


def _load_nodes() -> Dict[str, Dict[str, Any]]:
    from database import get_db_cursor

    out: Dict[str, Dict[str, Any]] = {}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT node_id, node_name, status, gpu_vram_gb, ram_gb, max_concurrent,
                   (extra_capabilities->>'max_model_gb')::numeric AS max_model_gb,
                   (extra_capabilities->>'gpu_vram_total_gb')::numeric AS gpu_vram_total_gb
              FROM remote_nodes
            """
        )
        for row in cur.fetchall():
            d = dict(row)
            out[d["node_id"]] = d
    return out


def _declared():
    """The declared profile, from the resolver — with IMPLICIT_PROFILE as a
    last-resort local fallback.

    Step 2 moved the intent into platform_settings (services/residency_profiles)
    so the DECLARATION and the thing that CHECKS the declaration stop being two
    hand-maintained copies that can silently disagree — which is the whole
    failure mode this observer exists to catch (#1905 eroded exactly that way).

    ⚠️ Falls back to the local literals if the resolver is unavailable, so the
    observer keeps reporting rather than going dark. An observer that stops
    reporting is indistinguishable from a fleet with nothing to report.
    """
    try:
        from services import residency_profiles as rp

        nodes = rp.nodes_for()
        if nodes:
            return nodes, rp.active_name(), rp.source()
    except Exception as exc:  # noqa: BLE001 - observer must never raise
        logger.debug("residency_monitor: resolver unavailable (%s); using literals", exc)
    return IMPLICIT_PROFILE, "default", "monitor_literals"


def check_residency() -> Dict[str, Any]:
    """Entry point. NEVER raises — an observer that can break its caller is worse
    than no observer."""
    try:
        actual = _load_actual()
        nodes = _load_nodes()
        declared, profile_name, profile_source = _declared()
        findings = derive_findings(declared, actual, nodes)
        return {
            "ok": True,
            "profile": profile_name,
            "profile_source": profile_source,
            "nodes_evaluated": len(declared),
            "residency_rows": sum(len(v) for v in actual.values()),
            "findings": findings,
            "counts": _tally(findings),
            "note": "REPORTING ONLY — no routing, loading or eviction performed.",
        }
    except Exception as exc:
        logger.warning("residency_monitor: check failed: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc), "findings": [], "counts": {}}


def _tally(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    t: Dict[str, int] = {}
    for f in findings:
        t[f["kind"]] = t.get(f["kind"], 0) + 1
    return t


if __name__ == "__main__":
    import json
    import sys

    # Executed as a file from /app/services, so /app is not on sys.path and
    # `from database import ...` fails with "unknown location".
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    r = check_residency()
    print(json.dumps(r, indent=2, default=str))
