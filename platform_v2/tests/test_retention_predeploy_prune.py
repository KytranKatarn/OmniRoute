"""Pre-deploy snapshot pruning — deletion must actually happen, or be reported (#5030).

Regression cover for the second half of the pre-deploy prune bug.

PR #2378 added `prune_predeploy_snapshots()` and shipped it green: it SELECTED the right
directories, logged "prune: removing ...", returned a count, and exited 0. It deleted
nothing for a full day. Repair Bay writes these snapshots from inside `archie_platform`,
so every file is root:root 0755, while the nightly prune runs from cron as the
unprivileged backup user. `shutil.rmtree` died on the first `metadata.json` with EACCES,
the loop swallowed the OSError, and `backup_triage.sh` logged "retention prune OK".

Nothing exercised the delete path, so the whole failure was invisible. These tests do.
"""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
from tests.repo_root import repo_root

# These are pure unit tests: no database, no /backups, no docker. The module under test
# lives in scripts/, which the archie_platform container does NOT mount, so allow the path
# to be pointed at a copy (RETENTION_PRUNE_PATH=... python3 -m pytest ...) when running
# in-container. Repo-relative resolution is the default for a normal checkout run.
_CANDIDATES = [
    os.environ.get("RETENTION_PRUNE_PATH"),
    repo_root() / "scripts" / "backup" / "retention_prune.py",
]
_MODULE_PATH = next(
    (Path(c) for c in _CANDIDATES if c and Path(c).is_file()),
    None,
)

pytestmark = pytest.mark.skipif(
    _MODULE_PATH is None,
    reason="retention_prune.py not reachable (set RETENTION_PRUNE_PATH)",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("retention_prune", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def rp():
    mod = _load_module()
    mod.DRY_RUN = False
    mod._PREDEPLOY_FAILURES = 0
    return mod


def _make_snapshot(root: Path, name: str) -> Path:
    d = root / name
    (d / "services").mkdir(parents=True)
    (d / "metadata.json").write_text("{}")
    return d


class TestRemovePredeployDir:
    def test_host_rmtree_success_needs_no_container(self, rp, tmp_path, monkeypatch):
        d = _make_snapshot(tmp_path, "20260720_174821_Pre-deploy_x")
        called = []
        monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: called.append(a))

        assert rp._remove_predeploy_dir(d) is True
        assert not d.exists()
        assert called == [], "must not shell out to docker when the host delete worked"

    def test_permission_denied_falls_back_to_container(self, rp, tmp_path, monkeypatch):
        """The real bug: EACCES on root-owned files must not end the attempt."""
        monkeypatch.setattr(rp, "PRIMARY_ROOT", tmp_path)
        monkeypatch.setattr(rp, "DEFAULT_PRIMARY_ROOT", tmp_path)
        d = _make_snapshot(tmp_path, "20260720_174821_Pre-deploy_x")

        def boom(_path):
            raise PermissionError(13, "Permission denied", "metadata.json")

        monkeypatch.setattr(rp.shutil, "rmtree", boom)

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            # Simulate the container (running as root) succeeding.
            for child in sorted(d.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            d.rmdir()
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(rp.subprocess, "run", fake_run)

        assert rp._remove_predeploy_dir(d) is True
        assert not d.exists()
        # No shell: these names embed '#', ':' and '[]' from the proposal title.
        assert seen["cmd"][:3] == ["docker", "exec", "archie_platform"]
        assert "-rf" in seen["cmd"] and "--" in seen["cmd"]
        assert seen["cmd"][-1].endswith("/20260720_174821_Pre-deploy_x")

    def test_reports_failure_when_dir_survives_container_rm(self, rp, tmp_path, monkeypatch):
        """A container rm that returns 0 but leaves the dir must NOT count as deleted."""
        monkeypatch.setattr(rp, "PRIMARY_ROOT", tmp_path)
        monkeypatch.setattr(rp, "DEFAULT_PRIMARY_ROOT", tmp_path)
        d = _make_snapshot(tmp_path, "20260720_174821_Pre-deploy_x")

        def boom(_path):
            raise PermissionError(13, "Permission denied", "metadata.json")

        monkeypatch.setattr(rp.shutil, "rmtree", boom)
        monkeypatch.setattr(rp.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", ""))

        assert rp._remove_predeploy_dir(d) is False
        assert d.exists()

    def test_refuses_container_rm_when_backup_root_overridden(self, rp, tmp_path, monkeypatch):
        """A BACKUP_ROOT override (tests, DR drills) must never rm inside the container."""
        monkeypatch.setattr(rp, "PRIMARY_ROOT", tmp_path)
        monkeypatch.setattr(rp, "DEFAULT_PRIMARY_ROOT", Path("/mnt/data2/backups"))
        d = _make_snapshot(tmp_path, "20260720_174821_Pre-deploy_x")

        def boom(_path):
            raise PermissionError(13, "Permission denied", "metadata.json")

        monkeypatch.setattr(rp.shutil, "rmtree", boom)
        called = []
        monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: called.append(a))

        assert rp._remove_predeploy_dir(d) is False
        assert called == [], "must not rm inside the container against a non-default root"


class TestPrunePredeploySnapshots:
    def test_keeps_newest_by_full_timestamp_and_counts_failures(self, rp, tmp_path, monkeypatch):
        monkeypatch.setattr(rp, "PRIMARY_ROOT", tmp_path)
        # Same DAY, minutes apart — date-only sorting would keep arbitrary ones.
        names = [
            "20260720_174821_Pre-deploy_a",
            "20260720_180720_Pre-deploy_b",
            "20260720_182318_Pre-deploy_c",
            "20260720_210416_Pre-deploy_d",
            "20260720_213918_Pre-deploy_e",
        ]
        for n in names:
            _make_snapshot(tmp_path, n)
        (tmp_path / "20260720_060001_Daily_Triage").mkdir()  # must be ignored

        removed = []

        def fake_remove(run_dir):
            removed.append(run_dir.name)
            return True

        monkeypatch.setattr(rp, "_remove_predeploy_dir", fake_remove)

        assert rp.prune_predeploy_snapshots(keep=3) == 2
        assert sorted(removed) == ["20260720_174821_Pre-deploy_a", "20260720_180720_Pre-deploy_b"]
        assert rp._PREDEPLOY_FAILURES == 0

    def test_failed_removals_increment_the_failure_counter(self, rp, tmp_path, monkeypatch):
        """A prune that cannot delete must surface — main() exits non-zero on this."""
        monkeypatch.setattr(rp, "PRIMARY_ROOT", tmp_path)
        for n in ["20260720_174821_Pre-deploy_a", "20260720_180720_Pre-deploy_b"]:
            _make_snapshot(tmp_path, n)

        monkeypatch.setattr(rp, "_remove_predeploy_dir", lambda _d: False)

        assert rp.prune_predeploy_snapshots(keep=1) == 0
        assert rp._PREDEPLOY_FAILURES == 1
