"""Declared-vs-actual model drift across the fleet (#383 slice 4).

WHAT THIS CATCHES. When the residency profile RESERVES a node for a capability,
it also names the model it will keep warm there. If that capability then
dispatches a DIFFERENT model, the reservation is protecting the wrong thing and
every call pays a cold load onto a card whose headroom is already spoken for.

That is not hypothetical. #6040 changed WHO reviews machine-authored PRs
(F.O.R.G.E. -> P.R.O.B.E.) without changing WHAT the profile warms:

    profile:  USS-246  reserved_for='code_review'  expect_resident=['qwen2.5:7b']
    reality:  code_review dispatches P.R.O.B.E. -> qwen2.5-coder:7b (resident nowhere)

Three consecutive reviews of PR #3072 produced NO verdict — ~60 minutes of fleet
time, zero output — before a human noticed. Task #6276. This module would have
said so the day #6040 landed. Deterministic: no LLM, no judge, no benchmark run.

⚠️ WHY NOT "model is not in the warm set". That was this module's first design
and it was WRONG — measured against the live fleet it produced 22 warnings out of
40 capabilities. The active profile deliberately declares a MINIMAL warm set (4
models across 3 nodes); the fleet legitimately runs many more. "Absent from a
minimal warm set" is close to meaningless, and burying the one real finding under
21 false ones is worse than not checking at all. The RESERVATION is the signal,
because a reservation is an explicit promise about a specific capability.

⚠️ DEMAND-GATED. A capability with no traffic needs no warm model. The K.I.N.
zero-agent gap scan shipped ungated and produced 104 "gaps" with zero demand
behind them. Same lesson, applied up front.

⚠️ THE CALLER MUST FILTER NON-LLM ROWS before calling `derive_drift`, using
`carbon_footprint_service._is_llm_model` — the existing SSOT that already knows
`browser`, `internal`, `comfyui` and `*embed*` are not models. Do NOT write a
second exclude-list here; two lists drift.

⚠️ THIS IS AN OBSERVER. It never warms, evicts or re-routes. Adoption is a
separate, human-gated decision: a checker that silently rewrites placement is a
governance change wearing a monitor's clothes.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Minimum real dispatches before an absent/ mismatched warm model is a finding.
MIN_DISPATCHES = 5

_SEV_MISMATCH = "warning"
_SEV_OBSERVATION = "observation"


def _declared_models(spec: dict) -> list[str]:
    """Every model a node's profile entry declares, GPU-resident or CPU-pinned.

    DEDUPED, order preserved: the hub legitimately lists gemma3:12b in BOTH
    `expect_resident` and `cpu_pinned` (it is pinned to CPU *and* expected
    there), and without this the same absence is reported twice — which reads
    as two problems and inflates any count built on these findings.
    """
    if not isinstance(spec, dict):
        return []
    seen: dict[str, None] = {}
    for m in list(spec.get("expect_resident") or []) + list(spec.get("cpu_pinned") or []):
        if m:
            seen.setdefault(m, None)
    return list(seen)


def derive_drift(
    capability_rows: list[dict],
    profile_nodes: dict[str, dict],
    resident: dict[str, list[str]],
    *,
    min_dispatches: int = MIN_DISPATCHES,
) -> list[dict]:
    """PURE. Compare reservations, declarations and actual residency.

    `capability_rows`: [{capability, agent, model, dispatch_count}] — LLM rows only.
    `profile_nodes`:   {node: {expect_resident: [...], cpu_pinned: [...],
                               reserved_for: 'code_review'|None, ...}}
    `resident`:        {node: [model, ...]} from model_load_state.

    Never raises on odd input: a monitor that dies on a malformed row tells you
    nothing about the rows it never reached.
    """
    findings: list[dict] = []

    # capability -> the models it actually dispatched (with volume)
    by_capability: dict[str, list[dict]] = {}
    for row in capability_rows or []:
        if not isinstance(row, dict):
            continue
        cap = (row.get("capability") or "").strip()
        model = (row.get("model") or "").strip()
        try:
            count = int(row.get("dispatch_count") or 0)
        except (TypeError, ValueError):
            continue
        if not cap or not model or count < min_dispatches:
            continue
        by_capability.setdefault(cap, []).append({"model": model, "count": count, "agent": row.get("agent")})

    resident_anywhere = {m for models in (resident or {}).values() for m in (models or [])}

    # ---- 1. RESERVATION MISMATCH — the #6276 shape, the finding that matters --
    for node, spec in (profile_nodes or {}).items():
        if not isinstance(spec, dict):
            continue
        cap = (spec.get("reserved_for") or "").strip()
        if not cap:
            continue  # no promise made about a capability -> nothing to break
        promised = set(_declared_models(spec))
        actual = by_capability.get(cap) or []
        if not actual:
            continue  # reserved for something with no traffic — not a finding
        offenders = [a for a in actual if a["model"] not in promised]
        if not offenders:
            continue
        offenders.sort(key=lambda a: -a["count"])
        top = offenders[0]
        findings.append(
            {
                "kind": "reservation_mismatch",
                "severity": _SEV_MISMATCH,
                "node": node,
                "capability": cap,
                "promised": sorted(promised),
                "model": top["model"],
                "agent": top["agent"],
                "dispatch_count": top["count"],
                "detail": (
                    f"{node} reserves capacity for '{cap}' and warms {sorted(promised)}, "
                    f"but '{cap}' dispatches {top['agent'] or '?'} on {top['model']} "
                    f"({top['count']} runs). The reservation protects a model the "
                    f"capability does not use — every call pays a cold load."
                ),
            }
        )

    # ---- 2. declared somewhere, resident nowhere (observation, not an alarm) --
    # ONE reading cannot separate an eviction from an idle window — the same care
    # residency_monitor takes with its single-reading findings.
    for node, spec in (profile_nodes or {}).items():
        for model in _declared_models(spec):
            if model in resident_anywhere:
                continue
            findings.append(
                {
                    "kind": "declared_not_resident",
                    "severity": _SEV_OBSERVATION,
                    "node": node,
                    "model": model,
                    "detail": (
                        f"profile declares {model} on {node}; it is resident on no node. "
                        f"NOT a fault from one reading. If it persists, check capacity AND "
                        f"policy — can_node_run_model answers only the first."
                    ),
                }
            )

    return findings


def summarize(findings: list[dict]) -> str:
    """One line a human can act on, or an explicit all-clear."""
    if not findings:
        return "calibration drift: none — reservations match what dispatches"
    warn = [f for f in findings if f.get("severity") == _SEV_MISMATCH]
    parts = [f"{len(findings)} finding(s)"]
    if warn:
        parts.append("MISMATCH: " + ", ".join(f"{f['capability']}@{f['node']} runs {f['model']}" for f in warn[:5]))
    return "calibration drift: " + " | ".join(parts)
