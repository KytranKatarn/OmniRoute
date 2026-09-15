"""Backpressure for the quality_review job (#3333 follow-up).

The reaper BOUNDED the orphaned-queue leak; it never cured it. Its own docstring
says the reaped count IS the size of the upstream problem. Measured 2026-09-15 on
the live queue: 629 quality_scorer rows expired in 24h against 244 completed — the
majority of what this producer enqueued was thrown away 30 minutes later.

Cause: score_entry() blocks up to 240s on the queue and, on timeout, ABANDONS its
row and immediately enqueues the next entry. Nothing consulted the existing
backlog, so a slow cluster turned the job into a generator of work nobody claims.

These tests are PURE — no queue seeding. pytest forces the empty `archie_test` DB,
where a content assertion passes on zero rows (the vacuity trap this repo has hit
before). What is asserted is the shape that can actually be wrong.
"""

import importlib

import pytest

MOD = "services.quality_review_job"


@pytest.fixture()
def job():
    return importlib.import_module(MOD)


def _ctx(rows):
    """Minimal get_db_cursor stand-in returning a fixed fetchone() payload."""

    class _Cur:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return rows

    class _Ctx:
        def __enter__(self):
            return (None, _Cur())

        def __exit__(self, *a):
            return False

    return lambda *a, **k: _Ctx()


def test_backlog_counts_only_unclaimed_rows(job):
    """A row a worker has PICKED UP is real in-flight work, not backlog.

    Counting claimed rows would throttle the producer for work that is actually
    progressing — turning healthy load into a stall.

    ⚠️ Asserts against the SQL LITERAL, not the function source. The docstring in
    queued_backlog() explains the claimed_at rule in prose, so a substring check
    on the source PASSES even with the guard deleted from the query. Verified by
    mutation at authoring time — the first version of this test was vacuous.
    """
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(job.queued_backlog).lstrip()).body[0]
    # Require an actual QUERY: the docstring also names dispatch_pending_queue
    # (to explain why the bridge_jobs helper is wrong), and picking it up was how
    # the previous attempt at this test grabbed prose instead of SQL.
    docstring = ast.get_docstring(fn)
    sql = [
        n.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value != docstring
        and "SELECT" in n.value
        and "FROM dispatch_pending_queue" in n.value
    ]
    assert sql, "no SQL literal found in queued_backlog"
    query = sql[0]
    assert "claimed_at IS NULL" in query, "claimed rows must not count as backlog"
    assert "status = 'queued'" in query
    assert "module_id = 'quality_scorer'" in query


def test_backlog_probe_fails_open(monkeypatch, job):
    """An unreadable count must NOT stop scoring.

    A stuck producer is visible in the queue; a producer that quietly stopped
    because a probe threw is not. Fail open.
    """

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.get_db_cursor", _boom, raising=False)
    assert job.queued_backlog() == 0


def test_cap_never_resolves_to_zero(monkeypatch, job):
    """A cap of 0 would stop the job on iteration 0 — indistinguishable from broken.

    Same trap as a TTL of 0 in dispatch_queue_reaper: fail-safe means fail LONG.
    """
    for bad in ("0", "-5", "not-a-number", "", None):
        monkeypatch.setattr("database.get_db_cursor", _ctx({"value": bad}), raising=False)
        got = job.max_queued_backlog()
        assert got == job.MAX_QUEUED_BACKLOG, f"cap {bad!r} -> {got}"
        assert got > 0


def test_cap_accepts_a_sane_override(monkeypatch, job):
    monkeypatch.setattr("database.get_db_cursor", _ctx({"value": "40"}), raising=False)
    assert job.max_queued_backlog() == 40


def test_cap_lookup_failure_uses_the_default(monkeypatch, job):
    def _boom(*a, **k):
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr("database.get_db_cursor", _boom, raising=False)
    assert job.max_queued_backlog() == job.MAX_QUEUED_BACKLOG


def test_the_loop_checks_backlog_before_enqueueing(job):
    """Order is load-bearing: the check must precede the work, not follow it.

    Checking after score_entry() would still enqueue the row it exists to prevent.

    ⚠️ Matches CALLS by exact name. A substring check for "queued_backlog()" also
    matches "max_queued_backlog()" — the cap reader — so deleting the entire
    backlog check still passed. Verified by mutation at authoring time.
    """
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(job.run_quality_review).lstrip()).body[0]
    calls = [(n.lineno, n.func.id) for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    names = [c[1] for c in calls]
    assert "queued_backlog" in names, "the loop must consult the backlog"
    assert "score_entry" in names

    first_backlog = min(ln for ln, nm in calls if nm == "queued_backlog")
    first_score = min(ln for ln, nm in calls if nm == "score_entry")
    assert first_backlog < first_score, (
        "the backlog check must come BEFORE score_entry, or it enqueues the very " "row it is meant to prevent"
    )

    # the cap is read ONCE, before the loop — not re-queried every iteration
    assert "max_queued_backlog" in names
    loops = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.For)]
    if loops:
        first_cap = min(ln for ln, nm in calls if nm == "max_queued_backlog")
        assert first_cap < min(loops), "the cap must be read before the loop"


def test_throttled_is_reported_not_silent(job):
    """A silent stop reads as 'nothing to do'. The caller must be able to tell."""
    import inspect

    src = inspect.getsource(job.run_quality_review)
    assert '"throttled"' in src or "'throttled'" in src
    assert "throttled" in src and "queue_cap" in src, (
        "the result dict must expose both, so a throttled run is distinguishable " "from an idle one"
    )


def test_it_does_not_use_the_bridge_jobs_helper(job):
    """⚠️ in_flight_over_cap counts bridge_jobs — the WRONG table for this producer.

    quality_scorer never goes through bridge_jobs; it enqueues straight into
    dispatch_pending_queue via queued_dispatch_text. Wiring the existing helper
    here would read 0 forever and throttle nothing, while looking correct.
    """
    import ast
    import inspect

    # ⚠️ Match a CALL, not the words. An earlier draft grepped the source for the
    # name and failed on the docstring above, which mentions it precisely to say
    # it is the wrong helper. Same trap as a comment containing the thing a test
    # forbids — assert against the parsed tree, not the prose.
    tree = ast.parse(inspect.getsource(job))
    called = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert (
        "in_flight_over_cap" not in called
    ), "in_flight_over_cap counts bridge_jobs and cannot see this producer's rows"
    assert "dispatch_pending_queue" in inspect.getsource(job.queued_backlog)
