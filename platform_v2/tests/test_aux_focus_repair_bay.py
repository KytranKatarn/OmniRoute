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


class TestDrainFocusBoostWiring:
    def test_drain_job_reads_focus_max_fixes_behind_focus_active(self):
        from tools.department_hq import jobs

        src = inspect.getsource(jobs.code_health_backlog_drain_job)
        assert 'focus_active("repair_bay")' in src
        assert "work:code_health_backlog_drain:focus_max_fixes" in src
        # the boost must sit AFTER the base read so focus-off is byte-identical
        assert src.index("drain:max_fixes") < src.index("drain:focus_max_fixes")
