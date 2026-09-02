"""The scheduled caller that makes Academy Standby's TTL real (#383).

`academy_standby.arm()` records an expiry. `expire_if_due()` acts on it. Between
those two sat nothing — a TTL that existed only as a comment, which is the
declared-but-never-applied shape this codebase has shipped twice: the vps
retention tier declared for 10 components with no pruner (#5616), and the
`backups` table that a monitor queried and that never existed (#2366).

Standby holds ~109 background controls. A forgotten one starves the platform,
and the symptom — everything quietly idle — looks nothing like the cause.
"""

from __future__ import annotations

from pathlib import Path

JOBS = (Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "jobs.py").read_text()


def test_the_expiry_job_exists():
    assert "def academy_standby_expiry_job" in JOBS


def test_it_is_actually_SCHEDULED_not_merely_defined():
    """A defined-but-unregistered job is exactly the failure this guards: the
    code reads as present while nothing ever calls it."""
    assert "with_ctx(academy_standby_expiry_job)" in JOBS
    assert 'id="academy_standby_expiry"' in JOBS


def test_it_calls_expire_if_due():
    assert "from services.academy_standby import expire_if_due" in JOBS
    assert "expire_if_due()" in JOBS


def test_the_interval_is_tighter_than_the_minimum_TTL():
    """MIN_TTL_MIN is 5. A poll slower than the shortest TTL would let a hold
    outlive its expiry by design."""
    from services.academy_standby import MIN_TTL_MIN

    block = JOBS[JOBS.index("with_ctx(academy_standby_expiry_job)") :][:300]
    assert "IntervalTrigger(minutes=5)" in block
    assert 5 <= MIN_TTL_MIN


def test_the_job_cannot_be_the_reason_a_hold_outlives_its_ttl():
    """Wrapped so a job-level exception is logged, never propagated — the reaper
    must not be the thing that breaks."""
    block = JOBS[JOBS.index("def academy_standby_expiry_job") :][:1400]
    assert "try:" in block and "except Exception" in block


def test_expire_if_due_is_a_safe_noop_when_not_armed():
    """Called every 5 minutes forever; the common case must cost nothing and
    must not raise."""
    from services.academy_standby import expire_if_due, status

    if not status().get("armed"):
        r = expire_if_due()
        assert r.get("expired") is False
