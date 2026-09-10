"""#6653 Phase 3a — the ask-first cloud CODING lane, decision logic (pure)."""

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # /app (platform_v2)

import ai_bridge  # noqa: E402  (package __init__ only — agent_loop itself is heavy)
from services import cloud_code_lane as lane  # noqa: E402

_AGENT_LOOP_SRC = Path(ai_bridge.__file__).resolve().parent / "agent_loop.py"


def test_constants_pin_the_lane_to_code_and_a_distinct_action_type():
    assert lane.CAPABILITY == "code"
    assert lane.JOB_TYPE == "cloud_code"
    assert lane.ACTION_TYPE == "cloud_code_dispatch"
    assert lane.MODULE_ID == "cloud_code_lane"


def test_job_metadata_carries_everything_the_worker_needs():
    m = lane.build_job_metadata(
        prompt="p",
        system_prompt=None,
        provider_key="omniroute",
        model="auto/coding",
        requested_by="cockpit:archie_comms",
    )
    assert m == {
        "lane": "cloud_code_lane",
        "provider": "omniroute",
        "model": "auto/coding",
        "capability": "code",
        "prompt": "p",
        "system_prompt": "",
        "requested_by": "cockpit:archie_comms",
    }


@pytest.mark.parametrize(
    "approval,expected",
    [
        ("approved", "run"),
        ("rejected", "cancel"),
        ("denied", "cancel"),
        ("timeout", "cancel"),
        ("expired", "cancel"),
        ("cancelled", "cancel"),
        ("pending", "skip"),
        (None, "skip"),
    ],
)
def test_plan_worker_action_resolves_the_linked_approval(approval, expected):
    assert lane.plan_worker_action("pending", approval, 10.0) == expected


def test_a_pending_job_older_than_the_horizon_is_cancelled():
    assert lane.plan_worker_action("pending", "pending", lane.EXPIRE_SECONDS + 1) == "cancel"


def test_only_pending_jobs_are_ever_acted_on():
    assert lane.plan_worker_action("running", "approved", 1.0) == "skip"
    assert lane.plan_worker_action("completed", "approved", 1.0) == "skip"


class _Res:
    success = True
    response = "def f(): pass"
    model_used = "deepseek/deepseek-chat"
    provider = "omniroute"
    prompt_tokens = 10
    completion_tokens = 5
    error = None
    metadata = {"served_model_resolved": True, "routing_decision": "provider=deepseek"}


def test_summarize_result_is_json_safe_and_keeps_provenance():
    s = lane.summarize_result(_Res())
    assert s == {
        "success": True,
        "response": "def f(): pass",
        "model_used": "deepseek/deepseek-chat",
        "provider": "omniroute",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "error": None,
        "served_model_resolved": True,
        "routing_decision": "provider=deepseek",
    }


def test_summarize_result_flags_missing_provenance_as_unresolved():
    class R(_Res):
        metadata = {}

    assert lane.summarize_result(R())["served_model_resolved"] is False


def test_cloud_code_worker_is_defined_and_scheduled():
    src = _AGENT_LOOP_SRC.read_text(encoding="utf-8")
    assert re.search(r"^\s{4}def cloud_code_worker\(self\):", src, re.M) is not None
    assert 'id="cloud_code_worker"' in src
    assert "with_app_context(self.cloud_code_worker)" in src


def test_cloud_code_dispatch_approvals_land_in_the_ship_tab():
    from tools.department_hq.services.approvals_bulk import category_of, CATEGORY_SHIP

    assert category_of("cloud_code_dispatch") == CATEGORY_SHIP


def test_plan_worker_action_runs_on_executed_and_cancels_on_failed():
    # The approval-queue drain rewrites a human's 'approved' to 'executed' once the
    # executor acknowledges the row; the worker must still treat that as YES.
    assert lane.plan_worker_action("pending", "executed", 0) == "run"
    assert lane.plan_worker_action("pending", "approved", 0) == "run"
    # An executor failure on the row is a terminal NO, not a 24h wait.
    assert lane.plan_worker_action("pending", "failed", 0) == "cancel"


def test_approval_executor_acknowledges_worker_drained_lanes():
    # Structural: the executor must handle both worker-drained ask-first types
    # BEFORE its UNHANDLED fallback, else a human's YES is recorded as FAILED.
    src = _AGENT_LOOP_SRC.read_text(encoding="utf-8")
    i_branch = src.find('action_type in ("cloud_code_dispatch", "cloud_comparison")')
    i_unhandled = src.find("UNHANDLED action_type")
    assert i_branch != -1, "no executor branch for the worker-drained lanes"
    assert i_unhandled != -1 and i_branch < i_unhandled
