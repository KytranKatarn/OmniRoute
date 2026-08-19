"""Guards for bounded analysis concurrency (#5791) and the proxy default (#5794).

Measured 2026-08-18. `tech/routes.py:analyze_article` spawned a daemon thread per
POST with NO cap, NO semaphore and NO in-flight dedup; the only brake was the
`ai_analyzed` cache hit, which by definition only helps for work already done. On a
512m container that is unbounded work accepted from an unbounded caller.

PR #2687 bounded the TRIGGER at the consumer edge (5/hour, verified live: 8 rapid
POSTs returned "200 429 429 200 429 429 429 429"). It did not bound THIS — a caller
spread across IPs, or any internal path reaching tech directly rather than through
the consumer proxy, still lands on the spawn site.

`analyze_guard.py` imports nothing outside the stdlib so these tests exec it by path
and can never silently skip (KB #290497).
"""

import importlib.util
import pathlib
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOD = ROOT / "tech" / "analyze_guard.py"
TECH_ROUTES = ROOT / "tech" / "routes.py"
CONSUMER_ROUTES = ROOT / "consumer" / "routes.py"


def _load():
    spec = importlib.util.spec_from_file_location("_analyze_guard", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ag = _load()


def test_module_is_stdlib_only():
    """Parsed with ast, not grepped — a substring scan matches the module's own
    docstring (which names the libraries it avoids) and fails on a correct file."""
    import ast

    tree = ast.parse(MOD.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported.add(f".{node.module or ''}")
            elif node.module:
                imported.add(node.module.split(".")[0])
    allowed = {"math", "threading", "typing", "__future__"}
    offenders = sorted(m for m in imported if m not in allowed)
    assert not offenders, f"analyze_guard must stay stdlib-only; found {offenders}"


# ── dedup ────────────────────────────────────────────────────────────────────

def test_same_article_twice_is_deduped():
    """The common case: a user mashing the button, or several readers opening the
    same story. The second caller must NOT start a second thread."""
    g = ag.AnalyzeGuard(max_concurrent=4, workers=1)
    assert g.try_acquire(1) == ag.ACCEPTED
    assert g.try_acquire(1) == ag.ALREADY_RUNNING
    assert g.try_acquire(1) == ag.ALREADY_RUNNING
    assert g.in_flight() == 1, "a duplicate must not consume a second slot"


def test_dedup_is_checked_before_capacity():
    """A duplicate for an already-running article must never be refused for
    capacity — serving it costs no additional work."""
    g = ag.AnalyzeGuard(max_concurrent=2, workers=1)
    g.try_acquire(1)
    g.try_acquire(2)                       # now full
    assert g.try_acquire(3) == ag.AT_CAPACITY
    assert g.try_acquire(1) == ag.ALREADY_RUNNING, (
        "a duplicate of an in-flight article must dedup, not report capacity"
    )


# ── capacity ─────────────────────────────────────────────────────────────────

def test_distinct_articles_hit_the_ceiling():
    g = ag.AnalyzeGuard(max_concurrent=3, workers=1)
    assert [g.try_acquire(i) for i in range(3)] == [ag.ACCEPTED] * 3
    assert g.try_acquire(99) == ag.AT_CAPACITY
    assert g.in_flight() == 3


def test_release_frees_the_slot():
    g = ag.AnalyzeGuard(max_concurrent=1, workers=1)
    assert g.try_acquire(1) == ag.ACCEPTED
    assert g.try_acquire(2) == ag.AT_CAPACITY
    g.release(1)
    assert g.try_acquire(2) == ag.ACCEPTED


def test_release_is_idempotent():
    """A double-release in an error path must not corrupt the count — otherwise the
    ceiling drifts upward and the cap silently stops capping."""
    g = ag.AnalyzeGuard(max_concurrent=2, workers=1)
    g.try_acquire(1)
    g.release(1)
    g.release(1)
    g.release(999)                          # never held
    assert g.in_flight() == 0
    assert [g.try_acquire(i) for i in (10, 11)] == [ag.ACCEPTED] * 2
    assert g.try_acquire(12) == ag.AT_CAPACITY


# ── per-worker division ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "total,workers,expected",
    [(6, 2, 3), (6, 1, 6), (6, 4, 1), (1, 4, 1), (0, 2, 1), (6, 0, 6)],
)
def test_effective_cap(total, workers, expected):
    assert ag.effective_cap(total, workers) == expected


def test_effective_cap_never_zero():
    """A rounding artifact must not make the endpoint permanently refuse."""
    for total in range(0, 12):
        for workers in range(1, 9):
            assert ag.effective_cap(total, workers) >= 1


# ── thread safety ────────────────────────────────────────────────────────────

def test_concurrent_acquire_never_exceeds_the_cap():
    """The whole point is a ceiling under real concurrency, not under a for-loop."""
    g = ag.AnalyzeGuard(max_concurrent=5, workers=1)
    accepted = []
    lock = threading.Lock()

    def worker(i):
        if g.try_acquire(i) == ag.ACCEPTED:
            with lock:
                accepted.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(accepted) == 5, f"cap breached under concurrency: {len(accepted)}"
    assert g.in_flight() == 5


# ── wiring ───────────────────────────────────────────────────────────────────

def test_route_releases_the_slot_in_a_finally():
    """_analyze_bg guards each of its three tasks individually but has NO top-level
    handler, so an exception outside that loop would kill the thread. Without a
    finally the slot leaks permanently, and enough leaks wedge the endpoint shut."""
    src = TECH_ROUTES.read_text()
    assert "_analyze_guard.try_acquire" in src, "route must reserve a slot"
    acquire_at = src.index("_analyze_guard.try_acquire")
    tail = src[acquire_at:acquire_at + 2500]
    assert "finally:" in tail and "_analyze_guard.release" in tail, (
        "the release must sit in a finally, or a crashing thread leaks its slot"
    )
    fin = tail.index("finally:")
    rel = tail.index("_analyze_guard.release")
    assert fin < rel, "release must be INSIDE the finally block"


def test_route_no_longer_spawns_unguarded():
    """The bare spawn must be gone — a guard that some paths bypass is not a cap."""
    src = TECH_ROUTES.read_text()
    assert "target=_analyze_bg," not in src, (
        "found a direct _analyze_bg thread spawn; it must go through the guard"
    )


def test_proxy_tech_default_is_not_the_public_hostname():
    """#5794 — a public default silently routes every consumer->tech call over the
    internet (60s CDN cap, bypasses the queue, invisible to task_execution_log) if
    the env var is ever dropped."""
    src = CONSUMER_ROUTES.read_text()
    assert 'os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")' not in src
    assert 'os.environ.get("WTF_TECH_URL", "http://wtf-tech:8104")' in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
