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


FULL_A = "a" * 64
FULL_B = "b" * 64


def _inspect(state="exited", restart="no", labels=None, name="c-1", cid=None):
    return {
        "Id": cid if cid is not None else FULL_A,
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
                pinned_full_id=FULL_A,
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
            pinned_full_id=FULL_A,
            expected_labels={"attempt": "a-1"},
        )
        self.assertEqual(
            ev,
            {
                "id": "c-1",
                "full_id": FULL_A,
                "state": "exited",
                "restart_disabled": True,
                "labels_match": True,
            },
        )

    def test_full_id_target_requires_exact_id(self):
        """A reused name under a sealed full ID is rejected (name reuse)."""
        self.assertIsNone(
            observe_docker(
                FULL_A,
                "a-1",
                inspect_fn=lambda _n: _inspect(name="c-1", cid=FULL_B, labels={"attempt": "a-1"}),
                pinned_full_id=FULL_A,
                expected_labels={"attempt": "a-1"},
            ),
            "same name with different full ID must not yield evidence",
        )
        ev = observe_docker(
            FULL_A,
            "a-1",
            inspect_fn=lambda _n: _inspect(name="c-1", cid=FULL_A, labels={"attempt": "a-1"}),
            pinned_full_id=FULL_A,
            expected_labels={"attempt": "a-1"},
        )
        self.assertIsNotNone(ev, "exact full-ID match must yield evidence")
        self.assertEqual(ev["full_id"], FULL_A)

    def test_short_id_target_rejected(self):
        """A short-ID prefix is not an identity — never match by prefix."""
        self.assertIsNone(
            observe_docker(
                FULL_A[:12],
                "a-1",
                inspect_fn=lambda _n: _inspect(name=FULL_A[:12], cid=FULL_A),
                pinned_full_id=FULL_A,
                expected_labels={"attempt": "a-1"},
            ),
            "short-ID prefix target must not yield evidence",
        )

    def test_full_id_without_labels_rejected(self):
        """A full ID with no ownership labels still proves nothing about
        which assignment claims it."""
        self.assertIsNone(
            observe_docker(
                FULL_A,
                "a-1",
                inspect_fn=lambda _n: _inspect(name="c-1", cid=FULL_A, labels={"attempt": "a-1"}),
            ),
            "full ID without expected labels must not yield evidence",
        )

    def test_full_id_missing_state_flags_rejected(self):
        """Missing State/Running/Restarting/Paused keys stay UNKNOWN even
        for an exact full-ID match with labels."""

        def _bare(_n):
            info = _inspect(name="c-1", cid=FULL_A, labels={"attempt": "a-1"})
            del info["State"]["Running"]
            return info

        self.assertIsNone(
            observe_docker(FULL_A, "a-1", inspect_fn=_bare, pinned_full_id=FULL_A, expected_labels={"attempt": "a-1"}),
            "missing state flags must not yield evidence",
        )

    def test_full_id_missing_restart_policy_rejected(self):
        """A missing restart policy proves nothing about restart behavior."""

        def _nopolicy(_n):
            info = _inspect(name="c-1", cid=FULL_A, labels={"attempt": "a-1"})
            del info["HostConfig"]["RestartPolicy"]
            return info

        self.assertIsNone(
            observe_docker(
                FULL_A, "a-1", inspect_fn=_nopolicy, pinned_full_id=FULL_A, expected_labels={"attempt": "a-1"}
            ),
            "missing restart policy must not yield evidence",
        )

    def test_name_without_pinned_id_rejected(self):
        """A name with matching labels but no durably pinned full ID still
        produces no terminal evidence: resolution must happen at discovery."""
        self.assertIsNone(
            observe_docker(
                "c-1",
                "a-1",
                inspect_fn=lambda _n: _inspect(labels={"attempt": "a-1"}),
                expected_labels={"attempt": "a-1"},
            ),
            "name-only target without pinned ID must not yield evidence",
        )

    def test_name_without_labels_rejected(self):
        """A bare name with no ownership labels proves nothing (reusable)."""
        self.assertIsNone(
            observe_docker("c-1", "a-1", inspect_fn=lambda _n: _inspect()),
            "name without labels must not yield evidence",
        )

    def test_resolve_container_id(self):
        from observers import resolve_container_id

        self.assertEqual(resolve_container_id("c-1", lambda _n: _inspect(name="c-1")), FULL_A)
        self.assertIsNone(
            resolve_container_id("c-1", lambda _n: _inspect(name="c-1", cid="sha256:abc")),
            "non-ID daemon answer must not resolve",
        )

        def _boom(_name):
            raise ConnectionError("down")

        self.assertIsNone(resolve_container_id("c-1", _boom))

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

    def test_missing_inventory_rejected(self):
        """No PID inventory: an empty cgroup alone proves no accounted exit."""
        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=lambda _cg: [],
            ),
            "missing PID inventory must stay unknown",
        )

    def test_empty_inventory_rejected(self):
        """An empty inventory names no exits the reaper could have recorded."""
        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=lambda _cg: [],
                expected_pids=[],
                reap_confirmed_fn=lambda _pid: True,
            ),
            "empty PID inventory must stay unknown",
        )

    def test_migrated_child_alive_rejected(self):
        """Empty cgroup + stopped service, but the reaper has no record for
        the expected PID (migrated out and still alive): must stay unknown."""
        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=lambda _cg: [],
                expected_pids=[4242],
                reap_confirmed_fn=lambda _pid: False,
            ),
            "unaccounted PID must not yield evidence",
        )

    def test_reaped_pids_accepted(self):
        ev = observe_host(
            "runner",
            "a-1",
            service_state_fn=lambda _u: "inactive",
            cgroup_pids_fn=lambda _cg: [],
            expected_pids=[4242, 4243],
            reap_confirmed_fn=lambda _pid: True,
        )
        self.assertEqual(ev, {"cgroup_empty": True, "service": "stopped", "reaped": True})

    def test_reap_check_failure_rejected(self):
        """A failed reaper query fails closed — never assume reaped."""

        def _boom(_pid):
            raise PermissionError("cannot stat")

        self.assertIsNone(
            observe_host(
                "runner",
                "a-1",
                service_state_fn=lambda _u: "inactive",
                cgroup_pids_fn=lambda _cg: [],
                expected_pids=[4242],
                reap_confirmed_fn=_boom,
            ),
            "reaping check failure must not yield evidence",
        )


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
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "timeout", "head_sha": "abc", "repo": "o/r", "branch": "main"},
            ),
            "ambiguous PR create must not settle",
        )

    def test_unconfirmed_push_rejected(self):
        self.assertIsNone(
            self._obs(
                {"confirmed": False, "sha": "abc"},
                {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main", "pending_ops": []},
            ),
            "unconfirmed push must not settle",
        )

    def test_pending_ops_rejected(self):
        """Confirmed push with operations still in flight stays UNKNOWN."""
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": ["op-1"]},
                {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main", "pending_ops": []},
            ),
            "outstanding operations must not settle",
        )

    def test_missing_pending_ops_rejected(self):
        """Absent outstanding-operation status stays UNKNOWN (no default-true)."""
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc"},
                {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main", "pending_ops": []},
            ),
            "missing pending_ops must not settle",
        )

    def test_head_mismatch_rejected(self):
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "open", "head_sha": "zzz", "repo": "o/r", "branch": "main"},
            ),
            "foreign PR head must not settle",
        )

    def test_bare_empty_lookup_rejected(self):
        """A single empty lookup cannot establish absence."""
        self.assertIsNone(
            self._obs({"confirmed": True, "sha": "abc", "pending_ops": []}, {"state": "absent"}),
            "unproven absence must not settle",
        )

    def test_open_matching_settles(self):
        self.assertEqual(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "open", "head_sha": "abc", "repo": "o/r", "branch": "main", "pending_ops": []},
            ),
            {
                "settled": True,
                "assignment_id": "a-1",
                "repo": "o/r",
                "branch": "main",
                "head_sha": "abc",
            },
        )

    def test_proven_absence_settles(self):
        self.assertEqual(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "absent", "absence_proof": True, "repo": "o/r", "branch": "main", "pending_ops": []},
            ),
            {
                "settled": True,
                "assignment_id": "a-1",
                "repo": "o/r",
                "branch": "main",
                "head_sha": "abc",
            },
        )

    def test_wrong_repo_absence_rejected(self):
        """A proof scoped to another repo/branch settles nothing here."""
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "absent", "absence_proof": True, "repo": "o/other", "branch": "main", "pending_ops": []},
            ),
            "foreign-repo absence proof must not settle",
        )
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "absent", "absence_proof": True, "repo": "o/r", "branch": "dev", "pending_ops": []},
            ),
            "foreign-branch absence proof must not settle",
        )

    def test_pending_state_rejected(self):
        """A still-pending PR create stays UNKNOWN."""
        self.assertIsNone(
            self._obs(
                {"confirmed": True, "sha": "abc", "pending_ops": []},
                {"state": "pending", "head_sha": "abc", "repo": "o/r", "branch": "main"},
            ),
            "pending PR state must not settle",
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

    def test_symlink_redirect_rejected(self):
        """A supervisor path resolving inside the runner tree is rejected,
        even when no basename copy is visible (symlink redirection)."""

        def _realpath(path):
            if path == "/run/host-opencode-broker/broker.sock":
                return "/work/tree/link-to-sock"
            return path

        ok, detail = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: False,
            realpath_fn=_realpath,
            supervisor_paths=["/run/host-opencode-broker/broker.sock"],
        )
        self.assertFalse(ok, f"symlink redirect must fail: {detail}")

    def test_resolver_failure_rejected(self):
        """An unresolvable supervisor path fails closed."""

        def _boom(_path):
            raise OSError("cannot resolve")

        ok, _ = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: False,
            realpath_fn=_boom,
            supervisor_paths=["/run/host-opencode-broker/broker.sock"],
        )
        self.assertFalse(ok, "resolver failure must fail closed")

    def test_absolute_paths_confirmed(self):
        ok, _ = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: False,
            realpath_fn=lambda p: p,
            isdir_fn=lambda _p: True,
            supervisor_paths=[
                "/run/host-opencode-broker/broker.sock",
                "/var/lib/host-opencode/keys/broker_private.key",
                "/var/lib/host-opencode/broker_journal.db",
            ],
        )
        self.assertTrue(ok)

    def test_nested_mirror_rejected(self):
        """A private key visible at the runner's nested /var/lib/... mirror
        path is rejected even when the basename copy is absent."""

        def _exists(path):
            return path == "/work/tree/var/lib/host-opencode/keys/broker_private.key"

        ok, detail = verify_isolation(
            "/work/tree",
            exists_fn=_exists,
            realpath_fn=lambda p: p,
            isdir_fn=lambda _p: True,
            supervisor_paths=["/var/lib/host-opencode/keys/broker_private.key"],
        )
        self.assertFalse(ok, f"nested mirror must fail: {detail}")

    def test_nonexistent_root_rejected(self):
        """A missing runner root reports confirmed isolation otherwise —
        require it to exist and be a directory."""
        ok, _ = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: False,
            realpath_fn=lambda p: p,
            isdir_fn=lambda _p: False,
            supervisor_paths=["/run/host-opencode-broker/broker.sock"],
        )
        self.assertFalse(ok, "nonexistent runner root must fail closed")

    def test_unreadable_root_rejected(self):
        def _boom(_p):
            raise PermissionError("cannot stat")

        ok, _ = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: False,
            realpath_fn=lambda p: p,
            isdir_fn=_boom,
            supervisor_paths=["/run/host-opencode-broker/broker.sock"],
        )
        self.assertFalse(ok, "unreadable runner root must fail closed")

    def test_happy_path_confirmed(self):
        ok, _ = verify_confinement(
            4242,
            "0::/runner-a",
            read_fn=lambda _pid: "0::/runner-a",
            member_pids_fn=lambda _cg: [4242],
        )
        self.assertTrue(ok)
        ok2, _ = verify_isolation(
            "/work/tree",
            exists_fn=lambda _p: False,
            realpath_fn=lambda p: p,
            isdir_fn=lambda _p: True,
        )
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
            realpath_fn=lambda p: p,
            isdir_fn=lambda _p: True,
            expected_pids=[4242],
            reap_confirmed_fn=lambda _p: True,
        )
        self.assertTrue(bundle["confined"] and bundle["isolated"] and bundle["reaped"])

    def test_evidence_bundle_without_reaper_is_unknown(self):
        """Disappearance without reaper confirmation never claims reaping."""
        bundle = evidence_bundle(
            4242,
            "0::/runner-a",
            "/work/tree",
            read_fn=lambda _p: "0::/runner-a",
            member_pids_fn=lambda _c: [4242],
            exists_fn=lambda _p: False,
            realpath_fn=lambda p: p,
            isdir_fn=lambda _p: True,
        )
        self.assertTrue(bundle["confined"] and bundle["isolated"])
        self.assertIsNone(bundle["reaped"], "no reaper record must stay unknown")


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
                pinned_full_id=FULL_A,
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
                expected_pids=[4242],
                reap_confirmed_fn=lambda _pid: True,
            )
            assert out is not None
            return out

        def publication_observe(aid):
            maker = make_publication_observer(
                "o/r",
                "main",
                get_push_status=lambda: {"confirmed": True, "sha": "abc", "pending_ops": []},
                get_pr_status=lambda: {
                    "state": "open",
                    "head_sha": "abc",
                    "repo": "o/r",
                    "branch": "main",
                    "pending_ops": [],
                },
            )
            out = maker(aid)
            assert out is not None
            return out

        docker, host, pub = docker_observe, host_observe, publication_observe
        d = docker("c-1", "a-1")
        self.assertEqual(sorted(d.keys()), ["full_id", "id", "labels_match", "restart_disabled", "state"])
        h = host("runner", "a-1")
        self.assertEqual(sorted(h.keys()), ["cgroup_empty", "reaped", "service"])
        p = pub("a-1")
        self.assertEqual(
            p,
            {
                "settled": True,
                "assignment_id": "a-1",
                "repo": "o/r",
                "branch": "main",
                "head_sha": "abc",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
