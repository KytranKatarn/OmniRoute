"""Integration + unit tests for the misroute → proposal adapter (#2187).

Scope: adapter conversion logic + wiring to the audit pipeline. The real
DB-writing ``process_audit_findings`` + approval-queue path has its own
coverage (``test_approvals_multi_source.py``, ``test_forge_triage.py``);
here we mock that boundary so the tests stay fast and deterministic.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services import misroute_to_proposal_adapter as adapter


# ---------------------------------------------------------------------------
# Fixture: a live-shaped findings payload matching misroute_audit_service.
# ---------------------------------------------------------------------------


def _findings(**overrides):
    """Return a dict shaped like misroute_audit_service.run_misroute_audit.findings.

    Defaults model the 2026-04-21 168h production snapshot — matches what
    the adapter will actually see in the wild.
    """
    base = {
        "floor_fallback": [
            {
                "capability": "image_generation",
                "reason": "Throughput: awaiting cloud approval",
                "count": 9,
                "distinct_agents": 0,
            },
            {
                "capability": "chat",
                "reason": "Throughput: awaiting cloud approval",
                "count": 1,
                "distinct_agents": 0,
            },
        ],
        "cloud_escalation": [],
        "missing_capability": [],
        "high_failure_agents": [
            {
                "agent_name": "FORGE",
                "capability": "code_analysis",
                "total_calls": 41,
                "failures": 41,
                "failure_pct": 100.0,
            },
            {
                "agent_name": "EMBER",
                "capability": "batch_embedding",
                "total_calls": 54,
                "failures": 14,
                "failure_pct": 25.9,
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pure conversion — no DB, no mocks needed.
# ---------------------------------------------------------------------------


class TestFloorFallbackMapping:
    def test_maps_each_row_to_yellow_issue(self):
        issues = adapter._from_floor_fallback(_findings()["floor_fallback"])
        assert len(issues) == 2
        assert all(i["severity"] == "yellow" for i in issues)
        assert all(i["code"] == "DISPATCH_FLOOR_FALLBACK" for i in issues)

    def test_file_path_includes_capability(self):
        issues = adapter._from_floor_fallback(_findings()["floor_fallback"])
        assert issues[0]["file"] == "smart_router.py:image_generation"
        assert issues[1]["file"] == "smart_router.py:chat"

    def test_detail_includes_count_and_reason(self):
        issues = adapter._from_floor_fallback(_findings()["floor_fallback"])
        assert "9×" in issues[0]["detail"]
        assert "Throughput" in issues[0]["detail"]

    def test_caps_at_max_per_class(self):
        rows = [{"capability": f"cap_{i}", "reason": "r", "count": 1, "distinct_agents": 0} for i in range(10)]
        issues = adapter._from_floor_fallback(rows)
        assert len(issues) == adapter.MAX_PER_CLASS


class TestCloudEscalationMapping:
    def test_filters_below_cost_threshold(self):
        rows = [
            {
                "capability": "chat",
                "cloud_hits": 20,
                "total_cost_usd": 0.50,  # below threshold
                "distinct_models": 2,
            }
        ]
        assert adapter._from_cloud_escalation(rows) == []

    def test_passes_above_cost_threshold(self):
        rows = [
            {
                "capability": "chat",
                "cloud_hits": 20,
                "total_cost_usd": 5.25,
                "distinct_models": 2,
            }
        ]
        issues = adapter._from_cloud_escalation(rows)
        assert len(issues) == 1
        assert issues[0]["code"] == "DISPATCH_CLOUD_ESCALATION"
        assert issues[0]["severity"] == "yellow"
        assert "$5.25" in issues[0]["detail"]

    def test_handles_missing_cost(self):
        rows = [
            {
                "capability": "chat",
                "cloud_hits": 20,
                "total_cost_usd": None,
                "distinct_models": 2,
            }
        ]
        assert adapter._from_cloud_escalation(rows) == []


class TestMissingCapabilityMapping:
    def test_maps_to_red(self):
        rows = [{"module_source": "consciousness/jobs.py", "missing_cap_calls": 12}]
        issues = adapter._from_missing_capability(rows)
        assert len(issues) == 1
        assert issues[0]["severity"] == "red"
        assert issues[0]["code"] == "DISPATCH_MISSING_CAPABILITY"
        assert issues[0]["file"] == "consciousness/jobs.py"

    def test_falls_back_when_module_source_missing(self):
        rows = [{"module_source": None, "missing_cap_calls": 3}]
        issues = adapter._from_missing_capability(rows)
        assert issues[0]["file"] == "unknown_caller"


class TestHighFailureMapping:
    def test_red_for_50_percent_and_above(self):
        rows = [
            {
                "agent_name": "FORGE",
                "capability": "code_analysis",
                "total_calls": 10,
                "failures": 10,
                "failure_pct": 100.0,
            },
            {
                "agent_name": "ARCHIE",
                "capability": "chat",
                "total_calls": 10,
                "failures": 5,
                "failure_pct": 50.0,
            },
        ]
        issues = adapter._from_high_failure(rows)
        assert all(i["severity"] == "red" for i in issues)

    def test_yellow_below_50_percent(self):
        rows = [
            {
                "agent_name": "EMBER",
                "capability": "batch_embedding",
                "total_calls": 54,
                "failures": 14,
                "failure_pct": 25.9,
            }
        ]
        issues = adapter._from_high_failure(rows)
        assert issues[0]["severity"] == "yellow"

    def test_file_path_encodes_agent_and_capability(self):
        rows = [
            {
                "agent_name": "W.A.T.C.H.",
                "capability": "knowledge_analysis",
                "total_calls": 14,
                "failures": 14,
                "failure_pct": 100.0,
            }
        ]
        issues = adapter._from_high_failure(rows)
        # Dot-separated acronyms must survive — ensures dedup granularity
        assert issues[0]["file"] == "agents/W.A.T.C.H./knowledge_analysis"


# ---------------------------------------------------------------------------
# Aggregate converter — end-to-end without the pipeline.
# ---------------------------------------------------------------------------


class TestConvertFindings:
    def test_empty_findings_returns_empty(self):
        empty = {
            "floor_fallback": [],
            "cloud_escalation": [],
            "missing_capability": [],
            "high_failure_agents": [],
        }
        assert adapter._convert_findings(empty) == []

    def test_mixes_all_four_classes(self):
        findings = _findings(
            missing_capability=[{"module_source": "m", "missing_cap_calls": 1}],
            cloud_escalation=[
                {
                    "capability": "c",
                    "cloud_hits": 5,
                    "total_cost_usd": 10.0,
                    "distinct_models": 1,
                }
            ],
        )
        issues = adapter._convert_findings(findings)
        codes = {i["code"] for i in issues}
        assert codes == {
            "DISPATCH_FLOOR_FALLBACK",
            "DISPATCH_CLOUD_ESCALATION",
            "DISPATCH_MISSING_CAPABILITY",
            "AGENT_HIGH_FAILURE_RATE",
        }

    def test_count_by_code_matches(self):
        issues = adapter._convert_findings(_findings())
        counts = adapter._count_by_code(issues)
        assert counts["DISPATCH_FLOOR_FALLBACK"] == 2
        assert counts["AGENT_HIGH_FAILURE_RATE"] == 2


# ---------------------------------------------------------------------------
# run() wiring — mocks the pipeline boundary.
# ---------------------------------------------------------------------------


class TestRunWiring:
    def test_no_findings_short_circuits_without_calling_pipeline(self):
        audit_result = {
            "ran_at": "2026-04-21T00:00:00+00:00",
            "window_hours": 24,
            "severity": "info",
            "anomaly_count": 0,
            "summary_metrics": {},
            "reasons": [],
            "findings": {
                "floor_fallback": [],
                "cloud_escalation": [],
                "missing_capability": [],
                "high_failure_agents": [],
            },
        }
        with patch.object(adapter, "run", wraps=adapter.run):
            with patch(
                "services.misroute_audit_service.run_misroute_audit",
                return_value=audit_result,
            ), patch("services.audit_pipeline.process_audit_findings") as pipeline:
                summary = adapter.run(window_hours=24)

        assert summary["issues_generated"] == 0
        assert summary["proposals_created"] == 0
        pipeline.assert_not_called()

    def test_passes_module_name_and_issues_to_pipeline(self):
        audit_result = {
            "ran_at": "2026-04-21T00:00:00+00:00",
            "window_hours": 24,
            "severity": "warning",
            "anomaly_count": 4,
            "summary_metrics": {},
            "reasons": [],
            "findings": _findings(),
        }
        with patch(
            "services.misroute_audit_service.run_misroute_audit",
            return_value=audit_result,
        ), patch(
            "services.audit_pipeline.process_audit_findings",
            return_value={
                "proposals_created": 3,
                "skipped_duplicates": 1,
                "info_skipped": 0,
            },
        ) as pipeline:
            summary = adapter.run(window_hours=24)

        pipeline.assert_called_once()
        module_arg, issues_arg = pipeline.call_args.args
        assert module_arg == adapter.MODULE_NAME
        assert module_arg == "[dispatch_routing]"
        # 2 floor_fallback + 2 high_failure + 0 cloud + 0 missing = 4 issues
        assert len(issues_arg) == 4
        assert summary["proposals_created"] == 3
        assert summary["skipped_duplicates"] == 1
        assert summary["audit_severity"] == "warning"

    def test_cap_enforced_against_exploding_findings(self):
        """ARCHIE/translate regression scenario — 20 high-failure agents must
        produce at most MAX_PER_CLASS (5) AGENT_HIGH_FAILURE_RATE issues."""
        giant = _findings(
            high_failure_agents=[
                {
                    "agent_name": f"AGENT_{i}",
                    "capability": "translate",
                    "total_calls": 1000,
                    "failures": 900,
                    "failure_pct": 90.0,
                }
                for i in range(20)
            ]
        )
        audit_result = {
            "ran_at": "2026-04-21T00:00:00+00:00",
            "window_hours": 24,
            "severity": "error",
            "anomaly_count": 22,
            "summary_metrics": {},
            "reasons": [],
            "findings": giant,
        }
        with patch(
            "services.misroute_audit_service.run_misroute_audit",
            return_value=audit_result,
        ), patch(
            "services.audit_pipeline.process_audit_findings",
            return_value={
                "proposals_created": 7,
                "skipped_duplicates": 0,
                "info_skipped": 0,
            },
        ) as pipeline:
            adapter.run(window_hours=24)

        _, issues_arg = pipeline.call_args.args
        high_failure_issues = [i for i in issues_arg if i["code"] == "AGENT_HIGH_FAILURE_RATE"]
        assert len(high_failure_issues) == adapter.MAX_PER_CLASS, (
            f"cap violated — got {len(high_failure_issues)} " f"expected ≤{adapter.MAX_PER_CLASS}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
