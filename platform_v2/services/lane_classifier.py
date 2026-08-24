"""Which lane may take a work item — pure, deterministic, no I/O.

Deliberately not an LLM. This feeds an authority decision, and decision #953
makes safety properties universal: a gate must be reproducible and auditable.
An LLM may later rank candidates for usefulness; it must never authorise one.

The caller passes lane prefixes. This module holds NO copy of PLATFORM_SCOPE —
that lives in archie-code (archie_engine/scope_guard.py) and duplicating it
here is precisely the drift #5002 warns about.
"""

# Blocked for EVERY autonomous lane, including A.R.C.H.I.E.'s. This code
# enforces every other rule — including which lane runs and what gets approved.
KERNEL_PATTERNS: tuple = (
    # DISPATCH & MERGE GOVERNANCE
    "agent_service.py",
    "department_dispatcher.py",
    "repair_bay/services/github_service.py",
    "repair_bay/services/pr_review_service.py",
    # AUTHORIZATION / AUTHENTICATION — who may do what, and how login works
    "rbac.py",
    "module_registry.py",
    "services/auth_service.py",
    # BUILD & INFRASTRUCTURE
    "scripts/check_agent_single_writer.py",
    "scripts/agents/",
    "scripts/backup/",
    "scripts/dr/",
    "database/migrations/",
    ".github/",
    ".git/",
    "secrets/",
    "docker-compose",
    "Dockerfile",
    # THIS BRANCH'S OWN GOVERNANCE SURFACE (#380 review round 2, IMPORTANT) —
    # ruling R7 applied above to rbac.py/module_registry.py/auth_service.py
    # applies identically here: an actor able to rewrite the rules binding it
    # is not governed. maintenance_schedule_service.py writes the manifest AND
    # holds the "refuses once open" guard; lane_classifier.py (this file) can
    # rewrite the very KERNEL_PATTERNS list a lane is classified against;
    # proposer_service.py assembles what gets proposed onto that manifest;
    # services/agents/codex_scope.py is Codex's own deny-by-default allowlist.
    # Note "scripts/agents/" above does NOT match "platform_v2/services/agents/".
    "services/maintenance_schedule_service.py",
    "services/lane_classifier.py",
    "services/proposer_service.py",
    "services/agents/codex_scope.py",
)

_MAX_AUTONOMOUS_TIER = 2


def _is_kernel(path: str) -> bool:
    return any(pat in path for pat in KERNEL_PATTERNS)


def is_kernel_path(path: str) -> bool:
    """Public form of the kernel test, for consumers outside the lane machinery.

    ``pr_review_service.classify_pr_tier`` calls this so the REVIEW tier ladder and the
    LANE boundary share ONE definition of "kernel". Two independent lists of sensitive
    paths is the shape behind #5194 and #5862: a correct guard that some second surface
    never consulted. Adding a pattern to KERNEL_PATTERNS now moves both at once.
    """
    return _is_kernel(path)


def classify(item: dict, lane_prefixes: dict) -> dict:
    """Return {"lane", "tier", "reason"} for one work item.

    lane is None when no autonomous lane may take it — the caller drops it
    rather than escalating, because escalation is the owner's decision.
    """
    path = (item.get("file_path") or "").strip()
    if not path:
        return {"lane": None, "tier": 0, "reason": "no path — cannot prove it is in scope, so no lane may take it"}

    if _is_kernel(path):
        return {
            "lane": None,
            "tier": 0,
            "reason": f"governance kernel ({path}) — blocked for every autonomous lane (#953)",
        }

    # Narrowest lane first: prefer the most constrained actor that can do the job.
    for lane in ("codex", "engine"):
        for prefix in lane_prefixes.get(lane, ()):
            if path.startswith(prefix):
                return {
                    "lane": lane,
                    "tier": min(2, _MAX_AUTONOMOUS_TIER),
                    "reason": f"{path} is under {lane} prefix {prefix}",
                }

    return {"lane": None, "tier": 0, "reason": f"{path} is outside every configured lane prefix"}
