"""Job-level test for kin_generate_hire_proposals."""

from __future__ import annotations

from unittest.mock import patch


def test_job_inserts_up_to_max_proposals_per_run():
    from services import agent_jobs

    fake_gaps = [{"capability": f"skill_{i}", "gap_reason": "gap"} for i in range(25)]
    with patch(
        "services.agent_jobs._list_current_capability_gaps",
        return_value=fake_gaps,
    ), patch(
        "services.hiring_service.get_shortlist",
        return_value=[
            {
                "agent_id": 1,
                "display_name": "A",
                "proficiency_level": 5,
                "department": "X",
                "decommissioned_at": None,
                "primary_model": "m",
            }
        ],
    ), patch(
        "services.hiring_service.propose_for_gap",
        return_value=42,  # pretend every proposal inserts
    ) as mock_propose, patch(
        "services.agent_jobs._generate_hire_narrative",
        return_value=None,
    ), patch(
        "services.agent_jobs._log_cycle"
    ):
        agent_jobs.kin_generate_hire_proposals(max_proposals_per_run=10)
    assert mock_propose.call_count == 10


def test_job_skips_empty_shortlists():
    from services import agent_jobs

    fake_gaps = [{"capability": "rare", "gap_reason": "gap"}]
    with patch(
        "services.agent_jobs._list_current_capability_gaps",
        return_value=fake_gaps,
    ), patch(
        "services.hiring_service.get_shortlist",
        return_value=[],
    ), patch("services.hiring_service.propose_for_gap") as mock_propose, patch(
        "services.agent_jobs._generate_hire_narrative", return_value=None
    ), patch(
        "services.agent_jobs._log_cycle"
    ):
        agent_jobs.kin_generate_hire_proposals()
    mock_propose.assert_not_called()
