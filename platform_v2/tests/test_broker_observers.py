"""
Deterministic fixture tests for Host OpenCode independent observers.

Every test uses injected fakes — no Docker daemon, no systemd, no network,
no filesystem writes outside tmp. Each failure mode from the trusted-stop
contract must yield UNKNOWN (None) or False, never positive evidence.

Run with: python3 platform_v2/tests/test_broker_observers.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "host_opencode"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from containment import (
    evidence_bundle,
    process_reaped,
    verify_confinement,
    verify_isolation,
)
from observers import make_publication_observer, observe_docker, observe_host


def _inspect(state="exited", restart="no", labels=None, name="c-1", cid="sha256:abc"):
    return {
        "Id": cid,
        "Name": "/" + name,
        "State": {"Status": state, "Running": False, "Restarting": False, "Paused": False},
        "HostConfig": {"RestartPolicy": {"Name": restart}},
        "Config": {"Labels": dict(labels or {})},
    }


class DockerObserverTests(unittest.TestCase):
    def test_live_container_rejected(self):
        """A live daemon-owned container after client death stays UNKNOWN."""
        info = _inspect(state="running")
        info["State"]["Running"] = True
        self.assertIsNone(
            observe_docker("c-1", "a-1", inspect_fn=lambda _n: info),
            "running container must not yield evidence",
        )

    def test_pending_start_rejected(self):
        """A pending Docker start after a stop request stays UNKNOWN."""
        self.assertIsNone(
            observe_docker("c-1", "a-1", inspect_fn=lambda _n: _inspect(state="created")),
            "created container must not yield evidence",
        )

    def test_restart_policy_rejected(self):
        """A container that can restart itself must never count as stopped."""
        self.assertIsNone(
            observe_docker("c-1", "a-1", inspect_fn=lambda _n: _inspect(restart="always")),
            "restart-always container must not yield evidence",
        )

    def test_label_mismatch_rejected(self):
        """Expected ownership labels must match exactly."""
        self.assertIsNone(
            observe_docker(
                "c-1",
                "a-1",
                inspect_fn=lambda _n: _inspect(labels={"attempt": "other"}),
                expected_labels={"attempt": "a-1"},
            ),
            "label mismatch must not yield evidence",
        )

    def test_id_mismatch_rejected(self):
        """Never resolve by prefix or by name alone — exact identity only."""
        self.assertIsNone(
            observe_docker("c-2", "a-1", inspect_fn=lambda _n: _inspect(name="c-1")),
            "wrong container name must not yield evidence",
        )

    def test_daemon_error_rejected(self):
        """Daemon unavailability is UNKNOWN, never a stop decision."""

        def _boom(_name):
            raise ConnectionError("daemon down")

        self.assertIsNone(
            observe_docker("c-1", "a-1", inspect_fn=_boom),
            "daemon error must not yield evidence",
        )

    def test_terminal_evidence_accepted(self):
        ev = observe_docker(
            "c-1",
            "a-1",
            inspect_fn=lambda _n: _inspect(labels={"attempt": "a-1"}),
            expected_labels={"attempt": "a-1"},
        )
        self.assertEqual(ev, {"id": "c-1", "state": "exited", "restart_disabled": True, "labels_match": True})

    def test_no_client_rejected(self):
        self.assertIsNone(observe_docker("c-1", "a-1"), "missing client must fail closed")


class HostObserverTests(unittest.TestCase):
    def test_live_child_rejected(self):
        """A detached/TERM-ignoring child in the cgroup stays UNKNOWN."""

        def _pids(_cg):
            return [4242]

        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=_pids,
            ),
            "non-empty cgroup must not yield evidence",
        )

    def test_active_service_rejected(self):
        """A still-active unit stays UNKNOWN even with an empty cgroup."""

        def _pids(_cg):
            return []

        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "active",
                cgroup_pids_fn=_pids,
            ),
            "active service must not yield evidence",
        )

    def test_fork_race_rejected(self):
        """A second non-empty read (fork racing the snapshot) stays UNKNOWN."""
        reads = iter([[], [4242]])

        def _pids(_cg):
            return next(reads)

        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=_pids,
            ),
            "second non-empty read must not yield evidence",
        )

    def test_missing_cgroup_rejected(self):
        def _missing(_cg):
            raise FileNotFoundError("no such cgroup")

        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=_missing,
            ),
            "missing cgroup must not yield evidence",
        )

    def test_quiescent_evidence_accepted(self):
        ev = observe_host(
            "runner",
            "a-1",
            service_state_fn=lambda _u: "inactive",
            cgroup_pids_fn=lambda _cg: [],
        )
        self.assertEqual(ev, {"cgroup_empty": True, "service": "stopped"})


class PublicationObserverTests(unittest.TestCase):
    def _obs(self, push, pr):
        return make_publication_observer(
            "o/r",
            "main",
            get_push_status=lambda: push,
            get_pr_status=lambda: pr,
        )("a-1")

    def test_timeout_create_stays_unknown(self):
        """A timed-out create that may have succeeded remotely stays UNKNOWN."""
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc"},
                {"state": "timeout", "head_sha": "abc", "repo": "o/r", "branch": "main"},
            ),
            "ambiguous PR create must not settle",
        )

    def test_unconfirmed_push_rejected(self):
        self.assertIsNone(
            self._obs(
                {"confirmed": False, "sha": "abc"},
                {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main"},
            ),
            "unconfirmed push must not settle",
        )

    def test_head_mismatch_rejected(self):
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc"},
                {"state": "open", "head_sha": "zzz", "repo": "o/r", "branch": "main"},
            ),
            "foreign PR head must not settle",
        )

    def test_bare_empty_lookup_rejected(self):
        """A single empty lookup cannot establish absence."""
        self.assertIsNone(
            self._obs({"confirmed": True, "sha": "abc"}, {"state": "absent"}),
            "unproven absence must not settle",
        )

    def test_open_matching_settles(self):
        self.assertEqual(
            self._obs(
                {"confirmed": True, "sha": "abc"},
                {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main"},
            ),
            {"settled": True},
        )

    def test_proven_absence_settles(self):
        self.assertEqual(
            self._obs(
                {"confirmed": True, "sha": "abc"},
                {"state": "absent", "absence_proof": True},
            ),
            {"settled": True},
        )


class ContainmentTests(unittest.TestCase):
    def test_migrated_process_rejected(self):
        ok, detail = verify_confinement(
            4242,
            "runner-a",
            read_fn=lambda _pid: "0::/runner-b",
            member_pids_fn=lambda _cg: [4242],
        )
        self.assertFalse(ok, f"migrated process must fail: {detail}")

    def test_absent_from_procs_rejected(self):
        ok, _ = verify_confinement(
            4242,
            "0::/runner-a",
            read_fn=lambda _pid: "0::/runner-a",
            member_pids_fn=lambda _cg: [9999],
        )
        self.assertFalse(ok, "pid absent from cgroup procs must fail")

    def test_unreadable_cgroup_rejected(self):
        def _missing(_pid):
            raise PermissionError("denied")

        ok, _ = verify_confinement(4242, "runner-a", read_fn=_missing)
        self.assertFalse(ok, "unreadable cgroup must fail closed")

    def test_socket_visible_rejected(self):
        ok, detail = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: True,
        )
        self.assertFalse(ok, f"visible supervisor paths must fail: {detail}")

    def test_isolation_check_failure_rejected(self):
        def _boom(_p):
            raise OSError("cannot stat")

        ok, _ = verify_isolation("/work/tree", exists_fn=_boom)
        self.assertFalse(ok, "check failure must fail closed")

    def test_happy_path_confirmed(self):
        ok, _ = verify_confinement(
            4242,
            "0::/runner-a",
            read_fn=lambda _pid: "0::/runner-a",
            member_pids_fn=lambda _cg: [4242],
        )
        self.assertTrue(ok)
        ok2, _ = verify_isolation("/work/tree", exists_fn=lambda _p: False)
        self.assertTrue(ok2)

    def test_reaped_states(self):
        self.assertTrue(process_reaped(4242, exists_fn=lambda _p: False))
        self.assertFalse(process_reaped(4242, exists_fn=lambda _p: True))
        self.assertIsNone(process_reaped(4242, exists_fn=lambda _p: None))

    def test_evidence_bundle_shape(self):
        bundle = evidence_bundle(
            4242,
            "0::/runner-a",
            "/work/tree",
            read_fn=lambda _p: "0::/runner-a",
            member_pids_fn=lambda _c: [4242],
            exists_fn=lambda _p: False,
            proc_exists_fn=lambda _p: False,
        )
        self.assertTrue(bundle["confined"] and bundle["isolated"] and bundle["reaped"])


class TrustedCompletionIntegrationTests(unittest.TestCase):
    """The new observers satisfy the shape broker.check_trusted_completion needs."""

    def test_observer_shapes_match_broker_contract(self):
        import broker as _broker  # noqa: F401  (shape check only)

        docker, host, pub, _ = None, None, None, None

        def docker_observe(cid, aid):
            out = observe_docker(
                cid,
                aid,
                inspect_fn=lambda _n: _inspect(labels={"attempt": aid}),
                expected_labels={"attempt": aid},
            )
            assert out is not None
            return out

        def host_observe(cg, aid):
            out = observe_host(
                cg,
                aid,
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=lambda _c: [],
            )
            assert out is not None
            return out

        def publication_observe(aid):
            maker = make_publication_observer(
                "o/r",
                "main",
                get_push_status=lambda: {"confirmed": True, "sha": "abc"},
                get_pr_status=lambda: {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main"},
            )
            out = maker(aid)
            assert out is not None
            return out

        docker, host, pub = docker_observe, host_observe, publication_observe
        d = docker("c-1", "a-1")
        self.assertEqual(sorted(d.keys()), ["id", "labels_match", "restart_disabled", "state"])
        h = host("runner", "a-1")
        self.assertEqual(sorted(h.keys()), ["cgroup_empty", "service"])
        p = pub("a-1")
        self.assertEqual(p, {"settled": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
