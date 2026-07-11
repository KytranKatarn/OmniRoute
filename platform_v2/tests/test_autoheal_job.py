"""Scheduled-job tests for the autonomous Code Health heal cycle (Task A7).

The job is DEFAULT OFF (work-control key 'agent_code_health_autoheal') and must
be a no-op when disabled — autonomy is opt-in via the Autonomy tab.
"""

import tools.department_hq.jobs as jobs


def test_autoheal_job_is_noop_when_disabled(monkeypatch):
    ran = {"n": 0}
    monkeypatch.setattr(jobs, "_autoheal_enabled", lambda: False)
    monkeypatch.setattr(jobs, "_run_autoheal", lambda: ran.__setitem__("n", ran["n"] + 1))
    jobs.code_health_autoheal_job()
    assert ran["n"] == 0


def test_autoheal_job_runs_cycle_when_enabled(monkeypatch):
    ran = {"n": 0}
    logged = {}
    monkeypatch.setattr(jobs, "_autoheal_enabled", lambda: True)
    monkeypatch.setattr(
        jobs,
        "_run_autoheal",
        lambda: ran.__setitem__("n", ran["n"] + 1) or {"proposals_created": 2, "fix_dispatch": {"dispatched": 2}},
    )
    monkeypatch.setattr(
        jobs,
        "_log_cycle",
        lambda job_type, processed, failed, duration_ms, **kw: logged.update(
            {"job_type": job_type, "processed": processed, "failed": failed}
        ),
    )
    jobs.code_health_autoheal_job()
    assert ran["n"] == 1
    assert logged["job_type"] == "code_health_autoheal"
    assert logged["failed"] == 0


def test_autoheal_job_logs_failure_not_raises(monkeypatch):
    logged = {}
    monkeypatch.setattr(jobs, "_autoheal_enabled", lambda: True)

    def boom():
        raise RuntimeError("cycle exploded")

    monkeypatch.setattr(jobs, "_run_autoheal", boom)
    monkeypatch.setattr(
        jobs,
        "_log_cycle",
        lambda job_type, processed, failed, duration_ms, **kw: logged.update({"job_type": job_type, "failed": failed}),
    )
    jobs.code_health_autoheal_job()  # must not raise
    assert logged == {"job_type": "code_health_autoheal", "failed": 1}


def test_autoheal_job_registered_in_catalog():
    from tools.department_hq.services.job_registry import JOB_REGISTRY

    entry = JOB_REGISTRY["agent_code_health_autoheal"]
    assert entry["department"] == "Engineering & Technology"
    assert entry["director"] == "F.O.R.G.E."
    assert entry["source_file"] == "tools/department_hq/jobs.py"
    assert "OFF" in entry["description"]  # default-off is part of the contract
