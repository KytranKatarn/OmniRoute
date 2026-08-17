"""#5187 — the daily hire-proposal job must report what it actually inserted.

On 2026-07-24 the job logged {"inserted": 0} on the exact run that filed
hiring_candidates 406-409: the pool-saturation tail ran AFTER _log_cycle, so
its inserts never reached the parent summary. Anyone asking "is the hiring
signal active?" from the job log got precisely the wrong answer, four days
running. These tests pin the corrected ordering: the tail runs first, its
count lands in the same summary row, and a tail failure cannot lose the
zero-agent results.
"""

from unittest import mock

from services import agent_jobs


def _run_with(gaps, pool_return, shortlist=None, propose_return=None):
    """Run kin_generate_hire_proposals with the collaborators mocked; return
    the (job_name, items, fails, duration, kwargs) captured from _log_cycle."""
    captured = {}

    def fake_log_cycle(job, items, fails, duration_ms, **kw):
        captured.update({"job": job, "items": items, "fails": fails, **kw})

    patches = [
        mock.patch.object(agent_jobs, "_list_current_capability_gaps", return_value=gaps),
        mock.patch.object(agent_jobs, "_generate_hire_narrative", return_value=None),
        mock.patch.object(agent_jobs, "_log_cycle", side_effect=fake_log_cycle),
        mock.patch("services.hiring_service.get_shortlist", return_value=shortlist or []),
        mock.patch("services.hiring_service.propose_for_gap", return_value=propose_return),
    ]
    if isinstance(pool_return, Exception):
        patches.append(mock.patch.object(agent_jobs, "kin_recommend_pool_staffing", side_effect=pool_return))
    else:
        patches.append(mock.patch.object(agent_jobs, "kin_recommend_pool_staffing", return_value=pool_return))
    for p in patches:
        p.start()
    try:
        agent_jobs.kin_generate_hire_proposals()
    finally:
        for p in patches:
            p.stop()
    return captured


def test_parent_log_includes_pool_staffing_count():
    cap = _run_with(gaps=[], pool_return=4)
    assert cap["job"] == "kin_generate_hire_proposals"
    details = cap["details"]
    assert details["inserted"] == 0
    assert details["inserted_pool_staffing"] == 4, (
        "the pool tail's inserts must land in the PARENT summary — "
        "'inserted: 0 while inserting 4' is the #5187 defect"
    )
    assert cap["items"] == 4, "items_processed must reflect total real inserts"


def test_tail_failure_does_not_lose_parent_summary():
    cap = _run_with(gaps=[], pool_return=RuntimeError("tail exploded"))
    assert cap["job"] == "kin_generate_hire_proposals"
    assert cap["fails"] == 0, "a tail failure must not condemn the whole run"
    assert cap["details"]["inserted_pool_staffing"] == 0


def test_zero_agent_and_pool_counts_are_additive():
    gaps = [{"capability": "fact_check", "gap_reason": "r"}]
    cap = _run_with(
        gaps=gaps,
        pool_return=2,
        shortlist=[{"display_name": "X"}],
        propose_return=99,
    )
    d = cap["details"]
    assert d["inserted"] == 1 and d["inserted_pool_staffing"] == 2
    assert cap["items"] == 3
