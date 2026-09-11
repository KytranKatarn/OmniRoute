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

    def test_non_family_work_is_steered_off_defiant_under_focus(self, monkeypatch):
        """MOVED Runabout -> Defiant on 2026-09-11 (#6662).

        Steering protects the focus family's best HARDWARE. For repair_bay that
        is now Defiant: its RTX 3070 (8GB) is the only Starship card a 5.5GB 7B
        coder fits on — Runabout's 3050 is 4GB, where the same model can only
        CPU-demote. Reviews are unaffected: they reach Runabout through the
        separate preferred_node ordering asserted above, not through steering.

        ⚠️ Exactly ONE node is protected, deliberately. Steering both Starships
        would push every non-family dispatch onto the hub — measured 24h, that
        is 622 WTF beat_classification runs off Defiant alone, landing on the
        node that is already saturated.
        """
        self._arm(monkeypatch)
        assert fdp.focus_demotion_nodes("wtf_hub") == (_DEFIANT,)
        assert fdp.focus_demotion_nodes(None) == (_DEFIANT,)
        assert _RUNABOUT not in fdp.focus_demotion_nodes("wtf_hub")

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


def test_repair_bay_warms_the_COLD_model_first_not_the_busy_one(monkeypatch):
    """REVERSED 2026-09-11 (#6662). This test used to assert the opposite —
    that repair_bay warms qwen2.5:7b because "reviews are the dominant workload
    (~3000 runs/30d vs ~700 code-gen)". Dominance is the wrong criterion, and
    the fleet measured why:

      qwen2.5:7b        2,664 runs/day  -> a request every ~30s against
                                           KEEP_ALIVE=60m. It is NEVER cold.
                                           A pin buys nothing.
      qwen2.5-coder:7b      3 runs/day, 0 ok, 401s avg -> cold on EVERY request.

    A warm-pin only pays for itself on the model that is actually cold. The
    reviewer stays hot on the hub from its own demand (1,649 runs/day there).
    """
    import services.fleet_dispatch_profile as fdp

    models = fdp._as_model_tuple(fdp.FAMILY_WARM_MODELS["repair_bay"])
    assert models[0] == "qwen2.5-coder:7b", "the COLD model must be pinned first"
    assert "qwen2.5:7b" in models, "the reviewer stays declared, just lower priority"

    monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: "platform")
    monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: "repair_bay")
    assert fdp.get_focus_warm_models() == ("qwen2.5-coder:7b", "qwen2.5:7b")
    # the scalar accessor still works for out-of-tree callers
    assert fdp.get_focus_warm_model() == "qwen2.5-coder:7b"


def test_focus_models_are_empty_unless_platform_mode_and_a_focus(monkeypatch):
    """Inert by default. Shipping this must change NOTHING until AUX is armed."""
    import services.fleet_dispatch_profile as fdp

    monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: "auto")
    monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: "repair_bay")
    assert fdp.get_focus_warm_models() == ()

    monkeypatch.setattr(fdp, "get_dispatch_mode", lambda: "platform")
    monkeypatch.setattr(fdp, "get_dispatch_focus", lambda: "")
    assert fdp.get_focus_warm_models() == ()


def test_a_bare_string_value_still_works():
    """Back-compat: the other four families are still plain strings."""
    import services.fleet_dispatch_profile as fdp

    assert fdp._as_model_tuple("mistral:7b") == ("mistral:7b",)
    assert fdp._as_model_tuple(None) == ()
    assert fdp._as_model_tuple(("a", "", "b")) == ("a", "b")


class TestFocusWarmAssignment:
    """The distribution rule: one model per node, by fit, biggest card first.

    The bug being fixed: the old code pinned ONE model to the head of EVERY GPU
    node's single warm slot (TOP_K=1), so both Starships warmed the same model.
    """

    # Real fleet shapes, measured 2026-09-11.
    DEFIANT = {  # RTX 3070 8GB — a 5.5GB 7B fits
        "node_id": "starship_76583490e36955ab",
        "gpu_available": True,
        "gpu_vram_gb": 8,
        "models": ["qwen2.5-coder:7b", "qwen2.5:7b", "mistral:7b"],
    }
    RUNABOUT = {  # RTX 3050 4GB — a 5.5GB 7B does NOT fit
        "node_id": "starship_5501c2766526e746",
        "gpu_available": True,
        "gpu_vram_gb": 4,
        "models": ["qwen2.5-coder:7b", "qwen2.5:7b", "mistral:7b"],
    }
    OUTPOST = {  # no GPU at all
        "node_id": "outpost_us_001",
        "gpu_available": False,
        "gpu_vram_gb": 0,
        "models": ["qwen2.5:7b"],
    }

    def _plan(self, models, nodes):
        import services.fleet_dispatch_profile as fdp

        return fdp.plan_focus_warm_assignments(models, nodes)

    def test_the_priority_model_takes_the_biggest_card(self):
        got = self._plan(("qwen2.5-coder:7b", "qwen2.5:7b"), [self.RUNABOUT, self.DEFIANT])
        assert got[self.DEFIANT["node_id"]] == "qwen2.5-coder:7b"

    def test_one_model_per_node_never_the_same_model_twice(self):
        """THE REGRESSION GUARD. The old broadcast gave both Starships the same
        model; with TOP_K=1 that wasted half the GPU fleet."""
        got = self._plan(("qwen2.5-coder:7b", "qwen2.5:7b"), [self.DEFIANT, self.RUNABOUT])
        assert len(set(got.values())) == len(got.values()), f"a model was pinned twice: {got}"
        assert len(got) <= 2

    def test_a_model_that_cannot_fit_the_card_is_not_assigned_there(self):
        """qwen2.5:7b is 5.5GB; Runabout's card is 4GB. Pinning it there would
        reserve the slot for something that can only CPU-demote."""
        got = self._plan(("qwen2.5:7b",), [self.RUNABOUT])
        assert got == {}

    def test_a_node_without_the_model_is_skipped_never_pulled(self):
        """The warm-pin must never queue a pull (outpost-vps.md trap)."""
        bare = dict(self.DEFIANT, models=["mistral:7b"])
        assert self._plan(("qwen2.5-coder:7b",), [bare]) == {}

    def test_cpu_nodes_are_never_pinned(self):
        assert self._plan(("qwen2.5:7b",), [self.OUTPOST]) == {}

    def test_empty_and_garbage_inputs_fail_safe_to_no_pin(self):
        assert self._plan((), [self.DEFIANT]) == {}
        assert self._plan(("qwen2.5-coder:7b",), []) == {}
        assert self._plan(("no-such-model:999b",), [self.DEFIANT]) == {}


def test_the_coding_cluster_head_is_defiant_not_runabout():
    """USS-246 is the only Starship whose card fits a 5.5GB 7B coder (8GB vs
    4GB), and it has the i9-12900K. Steering protects ONE node deliberately:
    protecting both would push every non-family dispatch onto the saturated hub.
    """
    import services.fleet_dispatch_profile as fdp

    heads = fdp.FAMILY_FOCUS_NODES["repair_bay"]
    assert heads == ("starship_76583490e36955ab",), f"expected Defiant only, got {heads}"
