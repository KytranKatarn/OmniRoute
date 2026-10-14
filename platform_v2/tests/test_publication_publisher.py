"""Real disposable process/socket checks, not production host containment proof."""

from contextlib import closing
import json
import multiprocessing
from pathlib import Path
import socket
import sqlite3

import pytest

from tools.host_opencode.publication_fence import PublicationBlocked, PublicationFence
from tools.host_opencode.publication_publisher import PublicationPublisher


@pytest.fixture
def registered(tmp_path):
    f = PublicationFence(tmp_path / "journal.sqlite")
    f.provision()
    context = dict(
        repo="disposable/repo", branch="exercise", head_sha="a" * 40, host_id="test-host", boot_id="test-boot"
    )
    f.register("attempt", **context)
    return f, context


def test_intent_durable_before_transport_and_success_stays_pending(registered):
    f, context = registered
    calls = []

    def transport(**request):
        fresh = PublicationFence(f.path).inspect("attempt", expected=context)
        assert fresh["pending_ops"] == ["push-1"]
        assert dict(request["context"]) == context
        with pytest.raises(TypeError):
            request["context"]["branch"] = "transplant"
        calls.append(request["operation_id"])
        return {"response": "success"}

    publisher = PublicationPublisher(f, "attempt", expected=context, transport=transport)
    assert publisher.publish("push-1", operation="push") == {"response": "success"}
    assert f.inspect("attempt", expected=context)["pending_ops"] == ["push-1"]
    with pytest.raises(PublicationBlocked):
        publisher.publish("push-1", operation="push")
    assert calls == ["push-1"]


@pytest.mark.parametrize("failure", ["stopped", "write_failure", "wrong_boot", "missing_journal"])
def test_no_transport_on_gate_failure(registered, failure):
    f, context = registered
    calls = []
    if failure == "stopped":
        f.stop("attempt")
    elif failure == "write_failure":
        with closing(sqlite3.connect(f.path)) as conn, conn:
            conn.execute(
                "CREATE TRIGGER deny BEFORE INSERT ON publication_events BEGIN SELECT RAISE(ABORT,'fail'); END"
            )
    elif failure == "wrong_boot":
        context = {**context, "boot_id": "other"}
    else:
        Path(f.path).unlink()
    publisher = PublicationPublisher(f, "attempt", expected=context, transport=lambda **r: calls.append(r))
    with pytest.raises((PublicationBlocked, sqlite3.Error)):
        publisher.publish("denied", operation="pr_create")
    assert calls == []


def _delayed_endpoint(remote, accepted, release, evidence_path):
    with remote:
        request = json.loads(remote.recv(8192).decode())
        accepted.set()
        if not release.wait(5):
            raise RuntimeError("release_timeout")
        Path(evidence_path).write_text(json.dumps(request, sort_keys=True))
        # Remote success persists even after the client's process disappears.
        try:
            remote.sendall(b'{"success":true}')
        except BrokenPipeError:
            pass


def _publish_in_child(client, path, context):
    with client:

        def transport(**request):
            request["context"] = dict(request["context"])
            client.sendall(json.dumps(request).encode())
            return client.recv(1024)

        PublicationPublisher(PublicationFence(path), "attempt", expected=context, transport=transport).publish(
            "ambiguous-pr", operation="pr_create"
        )


def _cleanup(*processes):
    for process in processes:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(3)
            if process.is_alive():
                process.kill()
                process.join(3)
            assert not process.is_alive()
            process.close()


def test_client_death_does_not_prove_remote_absence(registered, tmp_path):
    f, context = registered
    mp = multiprocessing.get_context("fork")
    accepted, release = mp.Event(), mp.Event()
    client, remote = socket.socketpair()
    evidence = tmp_path / "remote-outcome.json"
    endpoint = mp.Process(target=_delayed_endpoint, args=(remote, accepted, release, str(evidence)))
    publisher = mp.Process(target=_publish_in_child, args=(client, f.path, context))
    try:
        endpoint.start()
        publisher.start()
        client.close()
        remote.close()
        assert accepted.wait(5)
        publisher.terminate()
        publisher.join(3)
        assert not publisher.is_alive()
        restarted = PublicationFence(f.path)
        restarted.stop("attempt")
        assert restarted.inspect("attempt", expected=context)["pending_ops"] == ["ambiguous-pr"]
        release.set()
        endpoint.join(5)
        assert endpoint.exitcode == 0
        observed = json.loads(evidence.read_text())
        assert observed["assignment_id"] == "attempt"
        assert observed["operation_id"] == "ambiguous-pr"
        assert observed["context"] == context
        assert restarted.inspect("attempt", expected=context)["pending_ops"] == ["ambiguous-pr"]
        restarted.acknowledge("attempt", "ambiguous-pr", disposition="confirmed", evidence=observed)
        result = restarted.inspect("attempt", expected=context)
        assert result["journal_ready"] and result["pending_ops"] == []
        assert result["settled"] is False and result["recovery_eligible"] is False
    finally:
        release.set()
        client.close()
        remote.close()
        _cleanup(publisher, endpoint)


def _race(path, context, barrier, outcomes, stop):
    f = PublicationFence(path)
    barrier.wait(5)
    if stop:
        f.stop("attempt")
        outcomes.put("stopped")
    else:

        def transport(**request):
            outcomes.put("issued")

        try:
            PublicationPublisher(f, "attempt", expected=context, transport=transport).publish("race", operation="push")
        except PublicationBlocked:
            outcomes.put("blocked")


def test_cross_process_stop_race(registered):
    f, context = registered
    mp = multiprocessing.get_context("fork")
    barrier, outcomes = mp.Barrier(2), mp.Queue()
    processes = [mp.Process(target=_race, args=(f.path, context, barrier, outcomes, stop)) for stop in (False, True)]
    try:
        for process in processes:
            process.start()
        results = {outcomes.get(timeout=8), outcomes.get(timeout=8)}
        for process in processes:
            process.join(5)
            assert process.exitcode == 0
        assert results in ({"stopped", "issued"}, {"stopped", "blocked"})
        pending = f.inspect("attempt", expected=context)["pending_ops"]
        assert pending == (["race"] if "issued" in results else [])
        with pytest.raises(PublicationBlocked):
            PublicationPublisher(
                f, "attempt", expected=context, transport=lambda **r: pytest.fail("late operation")
            ).publish("late", operation="push")
    finally:
        _cleanup(*processes)
        outcomes.close()
        outcomes.join_thread()


def test_missing_intent_mutation_is_detected(registered):
    """Removing commit-before-transport must break the durable-intent assertion."""
    from tools.host_opencode import publication_publisher

    source = Path(publication_publisher.__file__).read_text()
    mutant = source.replace("self.fence.begin(self.assignment, operation_id, operation=operation)", "pass")
    assert mutant != source
    namespace = {"__package__": "tools.host_opencode"}
    exec(compile(mutant, "<unsafe-publisher-copy>", "exec"), namespace)
    f, context = registered

    def transport(**request):
        assert PublicationFence(f.path).inspect("attempt", expected=context)["pending_ops"] == ["mutant"]

    with pytest.raises(AssertionError):
        namespace["PublicationPublisher"](f, "attempt", expected=context, transport=transport).publish(
            "mutant", operation="push"
        )
