"""#6099 AUX POWER part 1 — review node preference + focus-conditional drain boost.

Three invariants pinned here:

1. The 7B review dispatch sites use the dispatcher's _REVIEW_CLUSTER (Runabout FIRST,
   #5861) via _review_preferred_nodes() — NOT a stale explicit pin. The pre-#6099
   state had an explicit ["Defiant", "hub"] preferred_node at the call sites, which
   WON over CAPABILITY_NODE_AFFINITY and routed every direct review leg to the slow
   path (Defiant timed out 3/3 at 600s on 2026-08-28) for three days after #5861
   shipped. A revert of the site wiring must fail these tests, not just change vibes.

2. The gemma3:12b self-refute auditor deliberately KEEPS its Defiant+hub pin — the
   4GB Runabout cannot hold a 12B (required 24GB > 11.7GB RAM). Routing the auditor
   through _REVIEW_CLUSTER would bounce off the capacity gate on every call.

3. focus_active(family) is fail-safe False and true ONLY under platform mode with a
   matching focus — it gates the drain's focus_max_fixes boost, and a config error
   must never leave a boost stuck on.
"""

import inspect

from services import fleet_dispatch_profile as fdp
from tools.department_hq.services.department_dispatcher import _REVIEW_CLUSTER
from tools.repair_bay.services import pr_diff_analyzer as pda

_RUNABOUT = "starship_5501c2766526e746"
_DEFIANT = "starship_76583490e36955ab"


class TestReviewPreferredNodes:
    def test_helper_returns_the_dispatcher_cluster_runabout_first(self):
        nodes = pda._review_preferred_nodes()
        assert nodes == list(_REVIEW_CLUSTER)
        assert nodes[0] == _RUNABOUT, "#5861: Runabout must be FIRST preference"

    def test_helper_falls_back_to_the_old_pin_if_the_import_breaks(self, monkeypatch):
        import sys

        class _Empty:  # a module object without _REVIEW_CLUSTER
            pass

        monkeypatch.setitem(sys.modules, "tools.department_hq.services.department_dispatcher", _Empty())
        nodes = pda._review_preferred_nodes()
        assert nodes == [_DEFIANT, "archie-starbase"], "fallback must keep A preference"

    def test_structured_review_site_uses_the_helper_not_a_literal(self):
        src = inspect.getsource(pda._dispatch_json_review)
        assert "_review_preferred_nodes()" in src
        assert _DEFIANT not in src, "stale explicit pin must not return to this site"

    def test_freeform_review_site_uses_the_helper_not_a_literal(self):
        src = inspect.getsource(pda._run_forge_review)
        assert "_review_preferred_nodes()" in src
        assert (
            f'"{_DEFIANT}",\n' not in src and f'preferred_node=["{_DEFIANT}"' not in src
        ), "stale explicit pin must not return to this site"

    def test_gemma_auditor_KEEPS_its_explicit_defiant_hub_pin(self):
        # Deliberate: Runabout (4GB) cannot hold the 12B auditor model.
        src = inspect.getsource(pda._self_refute_criticals)
        assert _DEFIANT in src and "archie-starbase" in src
        assert "_review_preferred_nodes" not in src


class TestFocusActive:
    def test_true_only_under_platform_mode_with_matching_focus(self, monkeypatch):
        monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: "platform")
        monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: "repair_bay")
        assert fdp.focus_active("repair_bay") is True
        assert fdp.focus_active("consciousness") is False

    def test_false_outside_platform_mode_even_with_a_stored_focus(self, monkeypatch):
        monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: "auto")
        monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: "repair_bay")
        assert fdp.focus_active("repair_bay") is False

    def test_fail_safe_false_when_the_config_read_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(fdp, "get_dispatch_mode", _boom)
        assert fdp.focus_active("repair_bay") is False


class TestFocusDemotionNodes:
    """#6099 p2 — steering NON-family direct dispatches off the focus cluster head."""

    def _arm(self, monkeypatch, mode="platform", focus="repair_bay"):
        monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: mode)
        monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: focus)

    def test_non_family_work_is_steered_off_runabout_under_focus(self, monkeypatch):
        self._arm(monkeypatch)
        assert fdp.focus_demotion_nodes("wtf_hub") == (_RUNABOUT,)
        assert fdp.focus_demotion_nodes(None) == (_RUNABOUT,)

    def test_family_work_is_NEVER_steered(self, monkeypatch):
        self._arm(monkeypatch)
        for mod in ("repair_bay", "code_health", "forge", "audit_pipeline"):
            assert fdp.focus_demotion_nodes(mod) == ()

    def test_keep_warm_infrastructure_is_NEVER_steered(self, monkeypatch):
        # the warm ping must be able to warm the protected node itself
        self._arm(monkeypatch)
        for mod in ("kin_warmth", "fleet_warmup"):
            assert fdp.focus_demotion_nodes(mod) == ()

    def test_no_steering_outside_platform_mode_or_without_focus(self, monkeypatch):
        self._arm(monkeypatch, mode="auto")
        assert fdp.focus_demotion_nodes("wtf_hub") == ()
        self._arm(monkeypatch, mode="platform", focus="")
        assert fdp.focus_demotion_nodes("wtf_hub") == ()

    def test_focus_family_without_protected_nodes_steers_nothing(self, monkeypatch):
        self._arm(monkeypatch, focus="email")  # valid family, no FAMILY_FOCUS_NODES entry
        assert fdp.focus_demotion_nodes("wtf_hub") == ()

    def test_fail_safe_empty_when_config_read_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(fdp, "get_dispatch_mode", _boom)
        assert fdp.focus_demotion_nodes("wtf_hub") == ()

    def test_protected_ids_are_varchar_node_ids_not_int_ids(self):
        # fleet identity invariants: never the int remote_nodes.id
        for nodes in fdp.FAMILY_FOCUS_NODES.values():
            for n in nodes:
                assert isinstance(n, str) and not n.isdigit()

    def test_dispatcher_steer_matches_on_node_key_and_falls_through(self):
        import inspect as _inspect

        from tools.department_hq.services import department_dispatcher as dd

        src = _inspect.getsource(dd.DepartmentDispatcher._find_fleet_agent_for_hub_agent)
        assert "rn.node_id AS node_key" in src, "picker must expose the varchar node_id"
        # the steer lives at the CALL SITE (request_work), mirrors the #4343 cap skip
        module_src = _inspect.getsource(dd)
        assert "focus_demotion_nodes(module_id)" in module_src
        assert '_node_assign.get("node_key")' in module_src, "must match varchar, never int id"


class TestDrainFocusBoostWiring:
    def test_drain_job_reads_focus_max_fixes_behind_focus_active(self):
        from tools.department_hq import jobs

        src = inspect.getsource(jobs.code_health_backlog_drain_job)
        assert 'focus_active("repair_bay")' in src
        assert "work:code_health_backlog_drain:focus_max_fixes" in src
        # the boost must sit AFTER the base read so focus-off is byte-identical
        assert src.index("drain:max_fixes") < src.index("drain:focus_max_fixes")


def test_repair_bay_warm_model_is_the_review_model(monkeypatch):
    """AUX repair_bay must pre-warm the model REVIEWS actually run (qwen2.5:7b),
    not the code-gen model. Reviews are the dominant repair_bay workload
    (~3000 qwen2.5:7b code_review runs / 30d vs ~700 qwen2.5-coder:7b); warming
    qwen2.5-coder:7b left every review cold-loading while the focus was armed —
    the exact miswiring this fixes (#6662 follow-up)."""
    import services.fleet_dispatch_profile as fdp

    assert fdp.FAMILY_WARM_MODELS["repair_bay"] == "qwen2.5:7b"
    assert fdp.FAMILY_WARM_MODELS["repair_bay"] != "qwen2.5-coder:7b"
    monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: "platform")
    monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: "repair_bay")
    assert fdp.get_focus_warm_model() == "qwen2.5:7b"
