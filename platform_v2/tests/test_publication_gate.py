"""Publication gate: provisioning, exclusive publishing, reconciliation, containment.

Disposable SQLite files, faked ownership and real forked processes/sockets — no
network, production keys, DB or inference. A pass here is NOT host containment
proof: the isolated supervisor identity and credentials do not exist yet, so the
gate is exercised against an injected identity and a local controlled endpoint.
"""

import json
import multiprocessing
import os
from pathlib import Path
import socket
import sqlite3
import stat as stat_mod
import threading
import time

import pytest

from tools.host_opencode.publication_fence import PublicationBlocked, PublicationFence
from tools.host_opencode.publication_gate import (
    DockerStartStopGate,
    FileObservationAuthority,
    PublicationGate,
    ValidatedObservation,
    build_publication_observer,
    record_outcome,
    verify_publication_binding,
    verify_supervisor_provisioning,
)

UID = 4242
SEAL = {
    "assignment_id": "attempt-1",
    "repo": "owner/repo",
    "branch": "codex/repair",
    "commit_sha": "a" * 40,
    "cgroup": "host-opencode-runner",
}


def _stat_result(mode, uid):
    return os.stat_result((mode, 0, 0, 1, uid, uid, 0, 0, 0, 0))


def make_env(tmp_path, *, uid=UID, journal_mode=0o600, keys_mode=0o700, parent_mode=0o755):
    """A disposable journal + key dir whose ``stat`` reports an isolated owner."""
    journal = tmp_path / "journal.sqlite"
    journal.write_bytes(b"")
    keys = tmp_path / "keys"
    keys.mkdir()
    os.chmod(keys, keys_mode)
    overrides = {
        os.path.abspath(journal): _stat_result(stat_mod.S_IFREG | journal_mode, uid),
        os.path.abspath(tmp_path): _stat_result(stat_mod.S_IFDIR | parent_mode, uid),
        os.path.abspath(keys): _stat_result(stat_mod.S_IFDIR | keys_mode, uid),
    }
    real_stat = os.stat

    def stat_fn(path):
        key = os.path.abspath(str(path))
        return overrides.get(key) or real_stat(path)

    try:
        provisioning = verify_supervisor_provisioning(
            str(journal), str(keys), supervisor_uid=uid, euid=uid, stat_fn=stat_fn
        )
    except PublicationBlocked:
        # Deliberately malformed environments (used to drive fail-closed cases).
        provisioning = None

    return {
        "journal": str(journal),
        "keys": str(keys),
        "stat_fn": stat_fn,
        "uid": uid,
        "provisioning": provisioning,
    }


def make_gate(env, *, transport=None, authority=None, external_pin=None, assignment="attempt-1"):
    fence = PublicationFence(env["journal"])
    if not Path(env["journal"]).exists():
        raise AssertionError("journal vanished")
    return PublicationGate(
        fence,
        assignment,
        transport=transport or (lambda **request: {"ok": True}),
        authority=authority,
        provisioning=env["provisioning"],
        verify_seal=lambda seal: True,
        external_pin=external_pin,
        euid_fn=lambda: env["uid"],
        stat_fn=env["stat_fn"],
    )


def register(gate, **overrides):
    seal = dict(SEAL, **overrides)
    seal["assignment_id"] = gate.assignment
    gate.register_from_seal(dict(seal), host_id="host-1", boot_id="boot-1", generation="gen-1")


@pytest.fixture
def env(tmp_path):
    env = make_env(tmp_path)
    PublicationFence(env["journal"]).provision()
    return env


# ---------------------------------------------------------------------------
# 1. Isolated supervisor identity / journal / keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation,code",
    [
        ({"uid": 1000}, "not_supervisor_identity"),
        ({"journal_mode": 0o666}, "journal_group_or_world_writable"),
        ({"keys_mode": 0o755}, "keys_dir_not_private"),
        ({"parent_mode": 0o777}, "journal_dir_group_or_world_writable"),
    ],
)
def test_provisioning_fails_closed(tmp_path, mutation, code):
    env = make_env(tmp_path, **mutation)
    with pytest.raises(PublicationBlocked, match=code):
        verify_supervisor_provisioning(
            env["journal"],
            env["keys"],
            supervisor_uid=UID,
            euid=env["uid"] if mutation.get("uid") == 1000 else UID,
            stat_fn=env["stat_fn"],
        )


def test_provisioning_refuses_runner_euid(tmp_path):
    env = make_env(tmp_path)
    with pytest.raises(PublicationBlocked, match="not_supervisor_identity"):
        verify_supervisor_provisioning(
            env["journal"], env["keys"], supervisor_uid=UID, euid=1000, stat_fn=env["stat_fn"]
        )


def test_provisioning_refuses_missing_journal(tmp_path):
    env = make_env(tmp_path)
    missing = str(tmp_path / "does-not-exist.sqlite")
    with pytest.raises(PublicationBlocked, match="journal_missing"):
        verify_supervisor_provisioning(missing, env["keys"], supervisor_uid=UID, euid=UID, stat_fn=env["stat_fn"])


# ---------------------------------------------------------------------------
# 2. Registration binding to the durable seal + attempt/generation + host/boot
# ---------------------------------------------------------------------------


def test_registration_binds_every_identity(env):
    gate = make_gate(env)
    register(gate)
    assert gate.expected == {
        "repo": "owner/repo",
        "branch": "codex/repair",
        "head_sha": "a" * 40,
        "host_id": "host-1",
        "boot_id": "boot-1",
        "attempt_id": "attempt-1",
        "generation": "gen-1",
    }


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"repo": ""}, "seal_publication_unbound"),
        ({"branch": ""}, "seal_publication_unbound"),
        ({"commit_sha": "short"}, "head_invalid"),
        ({"assignment_id": "another"}, "seal_assignment_mismatch"),
    ],
)
def test_registration_rejects_unbound_seal(env, overrides, code):
    gate = make_gate(env)
    seal = dict(SEAL, **overrides)
    with pytest.raises(PublicationBlocked, match=code):
        gate.register_from_seal(dict(seal), host_id="h", boot_id="b", generation="g")


def test_registration_rejects_unverified_seal(env):
    gate = make_gate(env)
    gate.verify_seal = lambda seal: False
    with pytest.raises(PublicationBlocked, match="seal_invalid"):
        gate.register_from_seal(dict(SEAL), host_id="h", boot_id="b", generation="g")


def test_registration_context_conflict(env):
    gate = make_gate(env)
    register(gate)
    with pytest.raises(PublicationBlocked, match="context_conflict"):
        gate.register_from_seal(dict(SEAL), host_id="other-host", boot_id="boot-1", generation="gen-1")


# ---------------------------------------------------------------------------
# 3. Exclusive publishing with durable intent (no bypass)
# ---------------------------------------------------------------------------


def test_intent_is_committed_before_transport(env):
    seen = {}

    def transport(**request):
        fresh = PublicationFence(env["journal"]).inspect("attempt-1", expected=gate.expected)
        seen["pending"] = fresh["pending_ops"]
        return {"ok": True}

    gate = make_gate(env, transport=transport)
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    assert seen["pending"] == ["push-1"]
    # success stays pending: the transport's return is not an acknowledgement.
    assert gate.inspect()["pending_ops"] == ["push-1"]
    assert gate.inspect()["journal_ready"] is False


def test_transport_failure_keeps_pending_intent(env):
    def transport(**request):
        raise RuntimeError("connection reset")

    gate = make_gate(env, transport=transport)
    register(gate)
    with pytest.raises(RuntimeError):
        gate.publish("push-1", operation="push", request_id="req-1")
    assert gate.inspect()["pending_ops"] == ["push-1"]


def test_stop_wins_and_blocks_further_publishing(env):
    calls = []
    gate = make_gate(env, transport=lambda **request: calls.append(request))
    register(gate)
    gate.stop()
    with pytest.raises(PublicationBlocked, match="assignment_stopping_or_missing"):
        gate.publish("push-1", operation="push", request_id="req-1")
    assert calls == []


def test_duplicate_intent_cannot_authorize_a_repeat(env):
    calls = []
    gate = make_gate(env, transport=lambda **request: calls.append(request))
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    with pytest.raises(PublicationBlocked, match="operation_already_registered"):
        gate.publish("push-1", operation="push", request_id="req-1")
    assert len(calls) == 1


def test_publish_refuses_without_supervisor_identity(env):
    gate = make_gate(env)
    register(gate)
    gate._euid_fn = lambda: 1000  # runner identity
    with pytest.raises(PublicationBlocked, match="not_supervisor_identity"):
        gate.publish("push-1", operation="push", request_id="req-1")


def test_publish_requires_request_identity(env):
    gate = make_gate(env)
    register(gate)
    with pytest.raises(PublicationBlocked, match="request_identity_missing"):
        gate.publish("push-1", operation="push", request_id="")


# ---------------------------------------------------------------------------
# 4. Independent reconciliation (a dict cannot mint trust; timeout stays UNKNOWN)
# ---------------------------------------------------------------------------


class _StubAuthority:
    authority_id = "endpoint"

    def __init__(self, result):
        self._result = result

    def observe(self, **_kwargs):
        return self._result


def test_reconcile_unknown_stays_pending(env):
    gate = make_gate(env, authority=_StubAuthority(None))
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    assert gate.reconcile("push-1", operation="push") is None
    assert gate.inspect()["pending_ops"] == ["push-1"]


def test_reconcile_rejects_unvalidated_dict(env):
    gate = make_gate(env, authority=_StubAuthority({"disposition": "confirmed"}))
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    assert gate.reconcile("push-1", operation="push") is None
    assert gate.inspect()["pending_ops"] == ["push-1"]


def test_reconcile_rejects_observation_for_other_identity(env):
    forged = ValidatedObservation(
        authority_id="endpoint",
        assignment_id="attempt-1",
        operation_id="push-1",
        operation="push",
        request_id="different-request",
        disposition="confirmed",
        observed_at=1,
    )
    gate = make_gate(env, authority=_StubAuthority(forged))
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    assert gate.reconcile("push-1", operation="push") is None
    assert gate.inspect()["pending_ops"] == ["push-1"]


def test_reconcile_confirms_from_authority(env, tmp_path):
    ledger = str(tmp_path / "outcomes.jsonl")
    auth = FileObservationAuthority(ledger, authority_id="endpoint")
    gate = make_gate(env, authority=auth)
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    record_outcome(
        ledger,
        authority_id="endpoint",
        assignment_id="attempt-1",
        operation_id="push-1",
        operation="push",
        request_id="req-1",
        disposition="confirmed",
        observed_at=10,
        detail={"head_sha": "a" * 40},
    )
    observation = gate.reconcile("push-1", operation="push")
    assert observation.disposition == "confirmed"
    assert gate.inspect()["pending_ops"] == []


def test_confirmed_absent_is_a_distinct_disposition(env, tmp_path):
    ledger = str(tmp_path / "outcomes.jsonl")
    gate = make_gate(env, authority=FileObservationAuthority(ledger, authority_id="endpoint"))
    register(gate)
    gate.publish("create-1", operation="pr_create", request_id="req-9")
    record_outcome(
        ledger,
        authority_id="endpoint",
        assignment_id="attempt-1",
        operation_id="create-1",
        operation="pr_create",
        request_id="req-9",
        disposition="confirmed_absent",
        observed_at=11,
    )
    assert gate.reconcile("create-1", operation="pr_create").disposition == "confirmed_absent"


# ---------------------------------------------------------------------------
# 5. Tail rollback / missing journal (external pin, never auto-provision)
# ---------------------------------------------------------------------------


def test_external_pin_detects_tail_rollback(env):
    gate = make_gate(env)
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    tail = gate.receipt_binding()
    pin = (tail["sequence"], tail["digest"])

    # truncate the journal's last event: internal continuity still holds
    with sqlite3.connect(env["journal"]) as conn:
        conn.execute("DELETE FROM publication_events WHERE sequence = (SELECT MAX(sequence) FROM publication_events)")

    pinned_gate = make_gate(env, external_pin=pin)
    pinned_gate.expected = gate.expected
    with pytest.raises(PublicationBlocked, match="tail_rollback_or_missing"):
        pinned_gate.publish("push-2", operation="push", request_id="req-2")


def test_external_pin_matching_tail_allows_publishing(env):
    gate = make_gate(env)
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    tail = gate.receipt_binding()
    gate.external_pin = (tail["sequence"], tail["digest"])
    gate.publish("push-2", operation="push", request_id="req-2")


def test_missing_journal_is_unavailable_not_recreated(env):
    gate = make_gate(env)
    register(gate)
    os.remove(env["journal"])
    with pytest.raises(PublicationBlocked, match="journal_unavailable"):
        gate.reconcile("whatever", operation="push")


# ---------------------------------------------------------------------------
# 6. Receipt binding
# ---------------------------------------------------------------------------


def test_receipt_binding_tracks_disposition_and_outcomes(env, tmp_path):
    ledger = str(tmp_path / "outcomes.jsonl")
    gate = make_gate(env, authority=FileObservationAuthority(ledger, authority_id="endpoint"))
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    binding = gate.receipt_binding()
    assert binding["disposition"] == "unsettled"
    assert binding["operations"][0]["disposition"] == "pending"
    assert binding["sequence"] == 2 and len(binding["digest"]) == 64

    record_outcome(
        ledger,
        authority_id="endpoint",
        assignment_id="attempt-1",
        operation_id="push-1",
        operation="push",
        request_id="req-1",
        disposition="confirmed",
        observed_at=5,
    )
    gate.reconcile("push-1", operation="push")
    gate.stop()
    binding = gate.receipt_binding()
    assert binding["disposition"] == "publication_settled"
    assert binding["operations"][0]["disposition"] == "confirmed"
    assert verify_publication_binding(binding) == ("ok", True)
    assert build_publication_observer(gate)("attempt-1")["settled"] is True
    assert build_publication_observer(gate)("other") is None


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda b: b.update(extra=1), "binding_invalid"),
        (lambda b: b.update(disposition="weird"), "binding_invalid"),
        (lambda b: b.update(sequence=0), "binding_invalid"),
        (lambda b: b.update(digest="x" * 63), "binding_invalid"),
        (lambda b: b.update(operations="nope"), "binding_invalid"),
        (lambda b: b["operations"][0].update(operation="rm"), "binding_invalid"),
        (lambda b: b["operations"][0].update(disposition="pending"), "binding_inconsistent"),
    ],
)
def test_verify_publication_binding_rejects(env, mutate, code):
    gate = make_gate(env, authority=_StubAuthority(None))
    register(gate)
    gate.publish("push-1", operation="push", request_id="req-1")
    gate.stop()
    gate.reconcile("push-1", operation="push")  # unknown -> no ack
    binding = gate.receipt_binding()
    binding["disposition"] = "publication_settled"  # make it look settled for the pending case
    binding["operations"][0]["disposition"] = "confirmed"
    mutate(binding)
    assert verify_publication_binding(binding)[0] == code


def test_stop_converts_an_unexpected_journal_failure_into_a_refusal(env):
    """The gate's contract is ONE refusal type: no exception escapes stop() raw.

    F.O.R.G.E. (#3891) flagged that ``fence.stop`` could raise unhandled. The durable
    journal can fail in ways other than sqlite3.Error, and a caller that catches only
    PublicationBlocked must still see a refusal rather than a KeyError.
    """
    gate = make_gate(env)
    register(gate)
    inner = gate.fence

    class ExplodingFence:
        def stop(self, assignment):
            raise KeyError("journal record corrupt")

        def __getattr__(self, name):
            return getattr(inner, name)

    gate.fence = ExplodingFence()
    with pytest.raises(PublicationBlocked, match="journal_stop_failed") as excinfo:
        gate.stop()
    assert isinstance(excinfo.value.__cause__, KeyError)


def test_stop_propagates_the_fences_own_refusal_unchanged(env):
    """The fence's semantic refusals are not translated — they already mean "refused"."""
    gate = make_gate(env)
    register(gate)
    inner = gate.fence

    class RefusingFence:
        def stop(self, assignment):
            raise PublicationBlocked("assignment_missing")

        def __getattr__(self, name):
            return getattr(inner, name)

    gate.fence = RefusingFence()
    with pytest.raises(PublicationBlocked, match="assignment_missing"):
        gate.stop()


def test_publish_converts_an_unexpected_journal_failure_into_a_refusal(env):
    """Same invariant on the intent write: a begin() failure is a refusal, never a traceback."""
    gate = make_gate(env)
    register(gate)
    inner = gate.fence

    class ExplodingFence:
        def begin(self, assignment, operation_id, **kwargs):
            raise KeyError("journal record corrupt")

        def __getattr__(self, name):
            return getattr(inner, name)

    gate.fence = ExplodingFence()
    with pytest.raises(PublicationBlocked, match="journal_intent_failed"):
        gate.publish("push-1", operation="push", request_id="req-1")


# ---------------------------------------------------------------------------
# 7. Separate durable containment gate (Docker start/stop)
# ---------------------------------------------------------------------------


@pytest.fixture
def docker_gate(tmp_path):
    gate = DockerStartStopGate(tmp_path / "docker.sqlite")
    gate.provision()
    return gate


def test_container_start_and_stop_are_gated(docker_gate):
    token = docker_gate.admit_start("c-1")
    with pytest.raises(PublicationBlocked, match="container_already_started"):
        docker_gate.admit_start("c-1")
    with pytest.raises(PublicationBlocked, match="stop_not_admitted"):
        docker_gate.admit_stop("c-1", "wrong-token")
    ran = []
    with pytest.raises(PublicationBlocked, match="start_not_admitted"):
        docker_gate.guarded_run("start", "c-1", "wrong-token", lambda **k: ran.append(k))
    assert ran == []
    docker_gate.admit_stop("c-1", token)
    docker_gate.guarded_run("stop", "c-1", token, lambda **k: ran.append(k))
    assert docker_gate.history("c-1")["outstanding_start"] is None


def test_container_cannot_stop_without_start(docker_gate):
    with pytest.raises(PublicationBlocked, match="stop_not_admitted"):
        docker_gate.admit_stop("foreign", "t")


def test_container_gate_is_durable_and_tamper_evident(docker_gate, tmp_path):
    token = docker_gate.admit_start("c-1")
    reopened = DockerStartStopGate(tmp_path / "docker.sqlite")
    assert reopened.history("c-1")["outstanding_start"] == token
    with sqlite3.connect(str(tmp_path / "docker.sqlite")) as conn:
        conn.execute("UPDATE docker_admissions SET container='evil' WHERE container='c-1'")
    assert reopened.history("c-1") is None


# ---------------------------------------------------------------------------
# 8. Real process exercise: delayed success after the publishing client dies
# ---------------------------------------------------------------------------


def _endpoint(listener, ledger, delay, received, killed):
    conn, _addr = listener.accept()
    with conn:
        request = json.loads(conn.recv(65536))
        received.set()
        killed.wait(10)
        time.sleep(delay)  # the authoritative success lands AFTER the client is gone
        record_outcome(
            ledger,
            authority_id="endpoint",
            assignment_id=request["assignment_id"],
            operation_id=request["operation_id"],
            operation=request["operation"],
            request_id=request["request_id"],
            disposition="confirmed",
            observed_at=99,
            detail={"head_sha": "a" * 40},
        )
        try:
            conn.sendall(b"ok")
        except OSError:
            pass


def _publishing_client(env_journal, port, ready):
    from tools.host_opencode.publication_fence import PublicationFence
    from tools.host_opencode.publication_gate import PublicationGate

    def stat_fn(path):
        st = os.stat(path)
        mode = (stat_mod.S_IFDIR | 0o700) if stat_mod.S_ISDIR(st.st_mode) else (stat_mod.S_IFREG | 0o600)
        return os.stat_result((mode, st.st_ino, st.st_dev, st.st_nlink, UID, UID, 0, 0, 0, 0))

    def transport(**request):
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        # Only the retained operation/request identity crosses the wire.
        sock.sendall(
            json.dumps(
                {
                    "assignment_id": request["assignment_id"],
                    "operation_id": request["operation_id"],
                    "operation": request["operation"],
                    "request_id": request["request_id"],
                }
            ).encode()
        )
        ready.set()
        sock.recv(4096)  # blocks until the endpoint responds — or the client is killed
        return {"ok": True}

    gate = PublicationGate(
        PublicationFence(env_journal),
        "attempt-1",
        transport=transport,
        authority=None,
        provisioning=type(
            "P",
            (),
            {
                "supervisor_uid": UID,
                "journal_path": env_journal,
                "keys_dir": os.path.join(os.path.dirname(env_journal), "keys"),
            },
        )(),
        verify_seal=lambda seal: True,
        euid_fn=lambda: UID,
        stat_fn=stat_fn,
    )
    gate.register_from_seal(dict(SEAL), host_id="host-1", boot_id="boot-1", generation="gen-1")
    gate.publish("push-1", operation="push", request_id="req-1")
    time.sleep(30)


def test_delayed_success_survives_publishing_client_death(env, tmp_path):
    ledger = str(tmp_path / "outcomes.jsonl")
    gate = make_gate(env, authority=FileObservationAuthority(ledger, authority_id="endpoint"))
    register(gate)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    ctx = multiprocessing.get_context("fork")
    received = ctx.Event()
    killed = ctx.Event()

    ready = ctx.Event()
    client = ctx.Process(target=_publishing_client, args=(env["journal"], port, ready))
    client.start()
    # Start the endpoint thread only after the fork (single-threaded child).
    endpoint = threading.Thread(target=_endpoint, args=(listener, ledger, 0.2, received, killed), daemon=True)
    endpoint.start()
    assert ready.wait(10), "client never issued the request"
    assert received.wait(10), "endpoint never received the request"
    client.kill()  # client dies BEFORE the endpoint's response
    client.join(10)
    killed.set()
    endpoint.join(10)
    listener.close()

    # The intent survived the client's death; only independent reading acknowledges.
    assert gate.inspect()["pending_ops"] == ["push-1"]
    deadline = time.time() + 5
    while time.time() < deadline and gate.reconcile("push-1", operation="push") is None:
        time.sleep(0.05)
    assert gate.inspect()["pending_ops"] == []
