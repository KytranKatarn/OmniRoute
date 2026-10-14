"""Disposable SQLite publication ordering tests; no network, production keys or DB."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from tools.host_opencode.publication_fence import PublicationBlocked, PublicationFence


@pytest.fixture
def fence(tmp_path):
    f = PublicationFence(tmp_path / "journal.sqlite")
    f.provision()
    f.context = dict(
        repo="owner/repo",
        branch="disposable",
        head_sha="a" * 40,
        host_id="host",
        boot_id="boot",
    )
    f.register("attempt", **f.context)
    return f


def test_pending_ack_restart_and_stop(fence):
    fence.begin("attempt", "push-1", operation="push")
    fence.stop("attempt")
    restarted = PublicationFence(fence.path)
    result = restarted.inspect("attempt", expected=fence.context)
    assert result["pending_ops"] == ["push-1"] and not result["journal_ready"]
    restarted.acknowledge("attempt", "push-1", disposition="confirmed", evidence={"head_sha": "a" * 40})
    result = restarted.inspect("attempt", expected=fence.context)
    assert result["journal_ready"] and not result["settled"] and not result["recovery_eligible"]
    with pytest.raises(PublicationBlocked):
        restarted.begin("attempt", "pr-1", operation="pr_create")


def test_identity_boot_and_missing_journal_fail_closed(fence):
    assert fence.inspect("attempt", expected={**fence.context, "boot_id": "new-boot"}) is None
    with pytest.raises(PublicationBlocked):
        fence.register("attempt", **{**fence.context, "branch": "other"})
    from pathlib import Path

    Path(fence.path).unlink()
    assert fence.inspect("attempt", expected=fence.context) is None
    assert not Path(fence.path).exists()


def test_duplicate_intent_and_conflicting_ack(fence):
    fence.begin("attempt", "pr", operation="pr_create")
    with pytest.raises(PublicationBlocked):
        fence.begin("attempt", "pr", operation="pr_create")
    with pytest.raises(PublicationBlocked):
        fence.acknowledge("attempt", "pr", disposition="timeout", evidence={"timeout": True})
    fence.acknowledge("attempt", "pr", disposition="confirmed_absent", evidence={"reconciled": True})
    fence.acknowledge("attempt", "pr", disposition="confirmed_absent", evidence={"reconciled": True})
    with pytest.raises(PublicationBlocked):
        fence.acknowledge("attempt", "pr", disposition="confirmed", evidence={"pr": 1})


def test_start_stop_race(fence):
    def start():
        try:
            fence.begin("attempt", "push", operation="push")
            return "started"
        except PublicationBlocked:
            return "blocked"

    with ThreadPoolExecutor(2) as pool:
        started = pool.submit(start)
        stopped = pool.submit(fence.stop, "attempt")
        outcome = started.result()
        stopped.result()
    result = fence.inspect("attempt", expected=fence.context)
    assert result["pending_ops"] == (["push"] if outcome == "started" else [])
    with pytest.raises(PublicationBlocked):
        fence.begin("attempt", "late", operation="push")


def test_corruption_and_write_failure(fence):
    with sqlite3.connect(fence.path) as conn:
        conn.execute(
            "CREATE TRIGGER deny_write BEFORE INSERT ON publication_events BEGIN SELECT RAISE(ABORT,'no'); END"
        )
    with pytest.raises(sqlite3.Error):
        fence.begin("attempt", "push", operation="push")
    result = fence.inspect("attempt", expected=fence.context)
    assert result["pending_ops"] == [] and not result["journal_ready"]
    with sqlite3.connect(fence.path) as conn:
        conn.execute("UPDATE publication_events SET payload='{}'")
    assert fence.inspect("attempt", expected=fence.context) is None


def test_stop_guard_mutation_is_detected(tmp_path):
    """Unsafe code exists only in memory; the real after-stop assertion turns red."""
    from pathlib import Path
    from tools.host_opencode import publication_fence

    source = Path(publication_fence.__file__).read_text()
    mutated = source.replace('if not events or any(e[0] == "stop" for e in events):', "if not events:")
    assert mutated != source
    namespace = {}
    exec(compile(mutated, "<unsafe-publication-fence-copy>", "exec"), namespace)
    f = namespace["PublicationFence"](tmp_path / "mutant.sqlite")
    f.provision()
    f.register(
        "attempt",
        repo="owner/repo",
        branch="test",
        head_sha="a" * 40,
        host_id="host",
        boot_id="boot",
    )
    f.stop("attempt")
    with pytest.raises(pytest.fail.Exception):
        with pytest.raises(namespace["PublicationBlocked"]):
            f.begin("attempt", "late-push", operation="push")
