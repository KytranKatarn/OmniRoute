"""Department Job Registry — maps every platform job to its owning department.

Single source of truth for job ownership. Used by:
- Job monitoring dashboard in Department HQ
- autonomy_loop_log department column
- Job health reporting

Registry: 137 definitions; scheduling remains in the original source files.
All descriptions and ownership metadata are retained in the three private
_job_registry_entries modules and merged below in their original order.
"""

# Each entry: job_id -> {department, director, description, interval, source_file}
from ._job_registry_entries_1 import JOB_ENTRIES as _entries_1
from ._job_registry_entries_2 import JOB_ENTRIES as _entries_2
from ._job_registry_entries_3 import JOB_ENTRIES as _entries_3

JOB_REGISTRY = {**_entries_1, **_entries_2, **_entries_3}

# Note: agent_loop.py and security_network/jobs.py both register
# id="agent_anomaly_detection". The security_network version wins at runtime
# (registered later, replace_existing=True). The agent_loop.py version is
# effectively dead — only the security_network entry is in this registry.


def get_department_for_job(job_name):
    """Look up department for a job name.

    Handles both APScheduler IDs (e.g. 'agent_fleet_health') and the shorter
    names used by ``_log_cycle`` (e.g. 'fleet_health_check').  Lookup order:
    1. Exact match
    2. With ``agent_`` prefix
    3. With ``agent_`` prefix + ``_check`` suffix stripped

    Args:
        job_name: Job identifier (APScheduler id or _log_cycle short name).

    Returns:
        Department name string, or 'UNKNOWN' if not registered.
    """
    # 1. Exact match
    entry = JOB_REGISTRY.get(job_name)
    if entry:
        return entry["department"]

    # 2. Try with agent_ prefix
    prefixed = f"agent_{job_name}"
    entry = JOB_REGISTRY.get(prefixed)
    if entry:
        return entry["department"]

    # 3. Fallback — scan for substring match (handles rename drift)
    return "UNKNOWN"


def get_jobs_by_department(department=None):
    """Get all jobs, optionally filtered by department.

    Args:
        department: Optional department name to filter by.

    Returns:
        Dict of job_id -> metadata for matching jobs.
    """
    if department:
        return {k: v for k, v in JOB_REGISTRY.items() if v["department"] == department}
    return JOB_REGISTRY


def get_all_departments():
    """Get list of all departments with job counts.

    Returns:
        Dict of department_name -> {director, count}.
    """
    depts = {}
    for meta in JOB_REGISTRY.values():
        d = meta["department"]
        if d not in depts:
            depts[d] = {"director": meta["director"], "count": 0}
        depts[d]["count"] += 1
    return depts


def get_job_info(job_name):
    """Get full metadata for a specific job.

    Args:
        job_name: The APScheduler job id.

    Returns:
        Dict with department, director, description, interval, source_file
        or None if not found.
    """
    return JOB_REGISTRY.get(job_name)


def get_unregistered_jobs(scheduler_job_ids):
    """Find jobs running in the scheduler that aren't in the registry.

    Args:
        scheduler_job_ids: List of job ids from APScheduler.

    Returns:
        List of job ids not found in JOB_REGISTRY.
    """
    registered = set(JOB_REGISTRY.keys())
    return [jid for jid in scheduler_job_ids if jid not in registered]
