"""#5319 — infrastructure warm-ups must never bill an agent's welfare ledger.

EVIDENCE (2026-07-27, owner report confirmed): K.I.N. (agent 145) read 122% of
her 67,500/day token budget — but 98% of the spend was capability='warmup'
(663 keep-warm runs, 80,516 tok) vs 1,716 tok of real workforce_planning. The
welfare token throttle then penalises the welfare coordinator herself for
infrastructure noise. Same principle as "welfare must not attribute
infrastructure failures to agents", token flavour.

SSOT: welfare_load.WELFARE_INFRA_CAPABILITIES + welfare_token_filter_sql() —
ONE exclusion source (the carbon _is_llm_model pattern), consumed by all four
welfare token sums: get_welfare_cache, pool_over_budget_by_skill,
recalibrate_token_budgets (so Monday's p90 recalibration cannot bake the
contaminated history into her budget), and the K.I.N.-tab velocity query
(KB #272470: the tab and governance MUST read the same signal).

The consumer checks are source-level on purpose: no test in this suite
executes those queries against a DB (task #5173), so the live proof is
K.I.N.'s tokens_24h dropping ~82k -> ~1.7k after deploy; these tests pin the
filter against silent removal.
"""

import os
import sys

_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

from services import welfare_load  # noqa: E402

_PLATFORM = os.path.join(_TREE_ROOT)


def _source(rel):
    with open(os.path.join(_PLATFORM, rel)) as fh:
        return fh.read()


class TestFilterFragment:
    def test_warmup_is_an_infra_capability(self):
        assert "warmup" in welfare_load.WELFARE_INFRA_CAPABILITIES

    def test_fragment_without_alias(self):
        frag = welfare_load.welfare_token_filter_sql()
        assert frag.startswith(" AND ")
        assert "COALESCE(capability, '')" in frag
        assert "'warmup'" in frag

    def test_fragment_with_alias(self):
        frag = welfare_load.welfare_token_filter_sql("tel")
        assert "COALESCE(tel.capability, '')" in frag

    def test_fragment_is_pure_literals(self):
        """The fragment is interpolated into SQL strings — it must only ever
        contain the hardcoded capability literals, never anything dynamic."""
        for cap in welfare_load.WELFARE_INFRA_CAPABILITIES:
            assert cap.isidentifier() or cap.replace("_", "").isalnum()


class TestConsumersCarryTheFilter:
    def test_welfare_governance_service_both_sums(self):
        src = _source("services/welfare_governance_service.py")
        assert (
            src.count("welfare_token_filter_sql(") >= 2
        ), "both get_welfare_cache and pool_over_budget_by_skill must apply the filter"

    def test_recalibration_is_filtered(self):
        src = _source("services/agent_jobs.py")
        assert (
            "welfare_token_filter_sql(" in src
        ), "recalibrate_token_budgets must exclude warmup or Monday's p90 bakes the contamination in"

    def test_kin_tab_velocity_is_filtered(self):
        src = _source("tools/department_hq/work_routes.py")
        assert (
            "welfare_token_filter_sql(" in src
        ), "KB #272470: the K.I.N. tab must read the same token signal as governance"
