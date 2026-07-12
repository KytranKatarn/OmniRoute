"""COO command surface — Tools & Actions (Slice 4). A CURATED, SAFE catalog of known-tool
diagnostics she runs from the cockpit chat. run_action executes them synchronously via the
delegation service's known-tool path. Only catalog keys run — nothing state-changing."""

from __future__ import annotations

# key -> {label, capability, description}. SAFE read-only diagnostics ONLY. Do NOT add
# state-changing capabilities (deploy_*, restore_*, *_proposal_adapter, external_fetch, ...).
_CATALOG = {
    "health": {
        "label": "Platform health",
        "capability": "check_platform_health",
        "description": "Live platform + service health.",
    },
    "qa": {
        "label": "QA suite",
        "capability": "run_qa_suite",
        "description": "Run the platform QA test suite.",
    },
    "dep_drift": {
        "label": "Dependency drift",
        "capability": "check_dep_drift",
        "description": "Check for dependency drift.",
    },
    "misroute_audit": {
        "label": "Misroute audit",
        "capability": "run_misroute_audit",
        "description": "Audit agent dispatch misroutes.",
    },
    "briefing_health": {
        "label": "Briefing health",
        "capability": "run_briefing_health",
        "description": "Check the session-briefing pipeline.",
    },
}


def list_actions():
    return [{"key": k, "label": v["label"], "description": v["description"]} for k, v in _CATALOG.items()]


def run_action(key):
    entry = _CATALOG.get((key or "").strip())
    if not entry:
        return {"ok": False, "error": "unknown_action"}
    try:
        from services.delegation_service import _execute_known_tool

        res = _execute_known_tool(entry["capability"], {}, f"Cockpit action: {entry['label']}")
        if res and res.get("success"):
            return {
                "ok": True,
                "label": entry["label"],
                "summary": res.get("summary") or "",
                "result": res.get("result"),
            }
        return {"ok": False, "label": entry["label"], "error": (res or {}).get("error") or "failed"}
    except Exception:
        return {"ok": False, "label": entry["label"], "error": "exception"}
