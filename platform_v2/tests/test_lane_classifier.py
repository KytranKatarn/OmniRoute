"""Which lane may take an item, and at what tier.

Deterministic on purpose: this feeds an authority decision, and no LLM belongs
in a gate path. An LLM may later RANK candidates; it must never AUTHORISE one.
"""

from services.lane_classifier import classify

# The caller passes its own prefixes — the platform must never hold a second
# copy of PLATFORM_SCOPE (#5002: duplicating a scope list is how it drifts).
LANES = {
    "codex": ("platform_v2/tools/fitness/", "platform_v2/tools/therapy/"),
    "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
}


def test_kernel_paths_go_to_no_autonomous_lane():
    """An actor that can rewrite the rules binding it is not governed (#953)."""
    for path in (
        "platform_v2/services/agent_service.py",
        "platform_v2/tools/department_hq/services/department_dispatcher.py",
        "platform_v2/tools/repair_bay/services/github_service.py",
    ):
        out = classify({"file_path": path, "title": "x"}, LANES)
        assert out["lane"] is None, path
        assert "kernel" in out["reason"].lower()


def test_authorization_authentication_surfaces_blocked():
    """Authorization and authentication surfaces are governance kernels.

    These three control who may do what (rbac.py, module_registry.py) and how
    login works (auth_service.py). They are blocked even under lane prefixes
    that would otherwise qualify them — an actor that controls permissions
    is not governed by permissions.
    """
    # Use lane_prefixes that include platform_v2/ so the paths WOULD qualify
    # for engine lane if not for the kernel check. This verifies the kernel
    # check fires, not just that the paths are out of scope.
    lanes_with_platform = {
        "codex": ("platform_v2/tools/fitness/", "platform_v2/tools/therapy/"),
        "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
    }

    for path in (
        "platform_v2/rbac.py",
        "platform_v2/module_registry.py",
        "platform_v2/services/auth_service.py",
    ):
        out = classify({"file_path": path, "title": "x"}, lanes_with_platform)
        assert out["lane"] is None, f"{path} should be blocked but got {out['lane']}"
        assert "kernel" in out["reason"].lower(), f"reason should mention kernel: {out['reason']}"


def test_this_branchs_own_governance_surface_is_kernel():
    """IMPORTANT (#380 review round 2): an actor able to rewrite the rules
    binding it is not governed (#953) -- the same ruling R7 already applied to
    rbac.py/module_registry.py/auth_service.py above, extended to this branch's
    own governance files. Probed with the REAL production lane_prefixes
    (dept_hq/jobs.py `proposer_draft`, engine=("platform_v2/", ...)), all four
    of these currently classify as lane="engine":

      * maintenance_schedule_service.py -- writes the manifest AND holds the
        'refuses once open' guard
      * lane_classifier.py -- can rewrite the very KERNEL_PATTERNS list a lane
        is classified against
      * proposer_service.py -- assembles what gets proposed
      * services/agents/codex_scope.py -- Codex's own deny-by-default allowlist

    Uses a lane_prefixes whose engine entry includes platform_v2/ (matching the
    real one in jobs.py) so this test proves the kernel check fires -- with a
    prefix set that excluded platform_v2/ these paths would be lane=None by
    scope alone, and the test would pass without the kernel check doing anything.
    """
    lanes_with_platform = {
        "codex": ("platform_v2/tools/fitness/", "platform_v2/tools/therapy/"),
        "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
    }

    for path in (
        "platform_v2/services/maintenance_schedule_service.py",
        "platform_v2/services/lane_classifier.py",
        "platform_v2/services/proposer_service.py",
        "platform_v2/services/agents/codex_scope.py",
    ):
        out = classify({"file_path": path, "title": "x"}, lanes_with_platform)
        assert out["lane"] is None, f"{path} should be blocked but got {out['lane']}"
        assert "kernel" in out["reason"].lower(), f"reason should mention kernel: {out['reason']}"


def test_a_narrow_module_prefers_codex():
    out = classify({"file_path": "platform_v2/tools/fitness/routes.py", "title": "x"}, LANES)
    assert out["lane"] == "codex"


def test_platform_wide_work_goes_to_the_engine():
    out = classify({"file_path": "ai_bridge/agent_loop.py", "title": "x"}, LANES)
    assert out["lane"] == "engine"


def test_an_item_with_no_path_is_unassigned_not_guessed():
    """No path means we cannot prove it is in scope. Fail closed."""
    out = classify({"file_path": None, "title": "something vague"}, LANES)
    assert out["lane"] is None
    assert "no path" in out["reason"].lower()


def test_a_path_outside_every_lane_is_unassigned():
    out = classify({"file_path": "standalone/media_hub/app.py", "title": "x"}, LANES)
    assert out["lane"] is None


def test_tier_never_exceeds_two_for_an_autonomous_lane():
    """Tier 3 is the owner's and is auto-merged by nobody."""
    for path in ("platform_v2/tools/fitness/routes.py", "ai_bridge/agent_loop.py"):
        assert classify({"file_path": path, "title": "x"}, LANES)["tier"] <= 2
