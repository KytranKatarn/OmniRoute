"""Tier-1 overload must DEFER an article, never escalate it to the heavier Tier-2 model.

2026-10-15: the hub hit load average 36 with /analyze calls running up to 664 s. When Tier 1 was rate-limited or timed out, both tier routers fell
through to Tier 2 ("tier1_failed_fallback"), which is the slower, heavier call, so overload amplified itself. Now overload (status rate_limited or
unavailable) returns a rate_limited result that the backlog workers already treat as "skip, retry next cycle". A genuine Tier-1 failure (the hub
answered with something unusable) still falls through, so no article is lost.
"""
import os
import sys
from unittest import mock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import quick_analyzer, tier_router  # noqa: E402

FLOWS = [
    pytest.param(tier_router.analyze_tiered, id="bias"),
    pytest.param(tier_router.analyze_factcheck_tiered, id="factcheck"),
]
BODY = "x" * 4000


def _run(flow, tier1):
    with mock.patch.object(tier_router.quick_analyzer, "analyze_quick", return_value=tier1), \
         mock.patch.object(tier_router.ai_dispatcher, "analyze_with_status",
                           return_value={"result": {"claims": []}, "status": "ok"}) as t2:
        out = flow(1, "t", BODY, source_slug="s")
    return out, t2


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("status", ["rate_limited", "unavailable"])
def test_overloaded_tier1_defers_and_never_calls_tier2(flow, status):
    out, t2 = _run(flow, {"result": None, "status": status})
    assert t2.call_count == 0, "Tier 2 must not run when Tier 1 asked us to back off"
    assert out["status"] == "rate_limited"
    assert out["result"] is None
    assert out["tier_meta"]["tier2_ran"] is False
    assert out["tier_meta"]["analysis_tier"] == "pending"
    assert out["tier_meta"]["gate_reason"] == f"tier1_backoff:{status}"


@pytest.mark.parametrize("flow", FLOWS)
def test_genuine_tier1_failure_still_falls_through_to_tier2(flow):
    out, t2 = _run(flow, {"result": None, "status": "failed"})
    assert t2.call_count == 1, "a Tier-1 failure the hub ANSWERED must still reach Tier 2"
    assert out["tier_meta"]["tier2_ran"] is True


@pytest.mark.parametrize("exc", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_quick_analyzer_maps_unanswered_hub_to_unavailable(exc):
    with mock.patch.object(quick_analyzer, "_ENABLED", True), \
         mock.patch.object(quick_analyzer.requests, "post", side_effect=exc):
        out = quick_analyzer.analyze_quick(task="bias", article_id=1, title="t", body="b", source_slug="s")
    assert out == {"result": None, "status": "unavailable"}


def test_quick_analyzer_keeps_failed_for_unexpected_errors():
    with mock.patch.object(quick_analyzer, "_ENABLED", True), \
         mock.patch.object(quick_analyzer.requests, "post", side_effect=ValueError("boom")):
        out = quick_analyzer.analyze_quick(task="bias", article_id=1, title="t", body="b", source_slug="s")
    assert out["status"] == "failed"
